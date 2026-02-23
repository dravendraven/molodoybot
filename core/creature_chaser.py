# core/creature_chaser.py
"""
Sistema de perseguicao de criaturas usando A* walker.
Substitui packet.follow() com suporte a obstacle clearing e movimentacao humanizada.

Projetado para ser chamado tick-a-tick pelo trainer loop (nao-bloqueante).
"""

import time
import random
from enum import Enum

from utils.timing import gauss_wait

from core.astar_walker import AStarWalker
from core.map_analyzer import MapAnalyzer
from core.memory_map import MemoryMap
from core.map_core import get_player_pos
from core.player_core import get_player_speed, is_player_moving
from core.packet import (
    PacketManager, get_ground_pos,
    OP_WALK_NORTH, OP_WALK_EAST, OP_WALK_SOUTH, OP_WALK_WEST,
    OP_WALK_NORTH_EAST, OP_WALK_SOUTH_EAST, OP_WALK_SOUTH_WEST, OP_WALK_NORTH_WEST
)

DIRECTION_TO_OPCODE = {
    (0, -1): OP_WALK_NORTH,
    (0, 1): OP_WALK_SOUTH,
    (-1, 0): OP_WALK_WEST,
    (1, 0): OP_WALK_EAST,
    (1, -1): OP_WALK_NORTH_EAST,
    (1, 1): OP_WALK_SOUTH_EAST,
    (-1, 1): OP_WALK_SOUTH_WEST,
    (-1, -1): OP_WALK_NORTH_WEST,
}


class ChaseResult(Enum):
    """Resultado de cada tick do chase."""
    WAITING = "waiting"          # Aguardando delay do passo anterior
    STEPPED = "stepped"          # Deu um passo em direcao ao alvo
    REACHED = "reached"          # Chegou a distancia de ataque (Chebyshev <= 1)
    BLOCKED = "blocked"          # Caminho bloqueado (A* retornou None)
    CLEARING = "clearing"        # Removendo obstaculo do caminho
    IDLE = "idle"                # Chase nao esta ativo


class CreatureChaser:
    """
    Persegue uma criatura usando A* pathfinding step-by-step.

    Uso:
        chaser = CreatureChaser(pm, base_addr, packet, walker, analyzer, memory_map)
        chaser.start_chase(creature_id, x, y, z)

        # A cada tick do trainer:
        result = chaser.update(creature_x, creature_y, creature_z)
        if result == ChaseResult.REACHED:
            # Transiciona para attack
        elif result == ChaseResult.BLOCKED:
            # Retarget
    """

    def __init__(self, pm, base_addr, packet, walker, analyzer, memory_map, debug=False):
        """
        Args:
            pm: Pymem instance
            base_addr: Base address do processo
            packet: PacketManager existente (compartilhado com trainer)
            walker: AStarWalker existente (compartilhado com trainer)
            analyzer: MapAnalyzer existente (compartilhado com trainer)
            memory_map: MemoryMap existente (compartilhado com trainer)
            debug: Ativa logs detalhados
        """
        self.pm = pm
        self.base_addr = base_addr
        self.packet = packet
        self.walker = walker
        self.analyzer = analyzer
        self.memory_map = memory_map
        self.debug = debug

        # Estado do chase
        self._active = False
        self._creature_id = 0
        self._target_x = 0
        self._target_y = 0
        self._target_z = 0

        # Timing
        self._next_step_time = 0.0
        self._cached_speed = 220  # Fallback
        self._last_speed_check = 0.0

        # Stuck detection
        self._stuck_counter = 0
        self._last_pos = None
        self._max_stuck = 8  # Apos N tentativas bloqueadas, retorna BLOCKED

        # Step history (oscillation detection)
        self._step_history = []
        self._max_history = 6
        self._last_step_dir = None

    @property
    def is_active(self):
        return self._active

    @property
    def creature_id(self):
        return self._creature_id

    def start_chase(self, creature_id, x, y, z):
        """Inicia perseguicao de uma criatura."""
        self._active = True
        self._creature_id = creature_id
        self._target_x = x
        self._target_y = y
        self._target_z = z
        self._next_step_time = 0.0
        self._stuck_counter = 0
        self._last_pos = None
        self._step_history.clear()
        self._last_step_dir = None

        if self.debug:
            print(f"[CHASE] Iniciando chase: creature_id={creature_id} pos=({x},{y},{z})")

    def stop(self):
        """Para a perseguicao."""
        if self._active and self.debug:
            print(f"[CHASE] Chase parado (creature_id={self._creature_id})")
        self._active = False
        self._creature_id = 0
        self._stuck_counter = 0
        self._step_history.clear()

    def update(self, creature_x, creature_y, creature_z=None):
        """
        Chamado a cada tick do trainer. Tenta dar o proximo passo em direcao a criatura.

        Args:
            creature_x, creature_y: Posicao atual da criatura (abs)
            creature_z: Andar da criatura (opcional, usa o do start se None)

        Returns:
            ChaseResult
        """
        if not self._active:
            return ChaseResult.IDLE

        # Atualiza posicao do alvo (criatura pode ter se movido)
        self._target_x = creature_x
        self._target_y = creature_y
        if creature_z is not None:
            self._target_z = creature_z

        # Posicao do player
        my_x, my_y, my_z = get_player_pos(self.pm, self.base_addr)

        # Andar diferente - chase nao suporta multifloor (retorna BLOCKED)
        if my_z != self._target_z:
            if self.debug:
                print(f"[CHASE] Andar diferente: player={my_z} target={self._target_z}")
            return ChaseResult.BLOCKED

        # Calcula distancia Chebyshev
        rel_x = self._target_x - my_x
        rel_y = self._target_y - my_y
        dist = max(abs(rel_x), abs(rel_y))

        # Ja esta adjacente (dist <= 1)
        if dist <= 1:
            if self.debug:
                print(f"[CHASE] REACHED: dist={dist} rel=({rel_x},{rel_y})")
            self._stuck_counter = 0
            return ChaseResult.REACHED

        # Verifica timing - ainda nao e hora do proximo passo
        now = time.time()
        if now < self._next_step_time:
            return ChaseResult.WAITING

        # Verifica se player ainda esta se movendo do passo anterior
        if is_player_moving(self.pm, self.base_addr):
            return ChaseResult.WAITING

        # Stuck detection: mesma posicao por muitas tentativas
        current_pos = (my_x, my_y)
        if self._last_pos == current_pos:
            self._stuck_counter += 1
        else:
            self._stuck_counter = 0
            self._last_pos = current_pos

        if self._stuck_counter >= self._max_stuck:
            if self.debug:
                print(f"[CHASE] BLOCKED: stuck_counter={self._stuck_counter} na pos ({my_x},{my_y})")
            return ChaseResult.BLOCKED

        # Calcula proximo passo via A*
        step = self.walker.get_next_step(rel_x, rel_y, activate_fallback=True)

        if step is None:
            # A* nao encontrou caminho - tenta limpar obstaculos
            cleared = self._try_clear_path(rel_x, rel_y)
            if cleared:
                if self.debug:
                    print(f"[CHASE] Obstaculo removido, retentando no proximo tick")
                return ChaseResult.CLEARING

            self._stuck_counter += 1
            if self.debug:
                print(f"[CHASE] A* sem caminho para rel({rel_x},{rel_y}) stuck={self._stuck_counter}")

            if self._stuck_counter >= self._max_stuck:
                return ChaseResult.BLOCKED

            # Espera um pouco antes de tentar novamente
            self._next_step_time = now + 0.2
            return ChaseResult.WAITING

        dx, dy = step

        # Verifica obstacle clearing no tile do proximo passo
        obstacle = self.analyzer.get_obstacle_type(dx, dy)
        if obstacle and obstacle.get('type') in ('MOVE', 'STACK') and obstacle.get('clearable'):
            if self.debug:
                print(f"[CHASE] Obstaculo {obstacle['type']} em ({dx},{dy}), tentando limpar")
            if self._attempt_clear_obstacle(dx, dy):
                return ChaseResult.CLEARING

        # Verifica walkability do proximo tile
        tile_props = self.analyzer.get_tile_properties(dx, dy)
        if not tile_props.get('walkable'):
            # Tile nao walkable - tenta limpar
            if self._attempt_clear_obstacle(dx, dy):
                return ChaseResult.CLEARING
            # Nao conseguiu limpar - incrementa stuck
            self._stuck_counter += 1
            self._next_step_time = now + 0.15
            return ChaseResult.WAITING

        # Oscillation detection
        if self._detect_oscillation(dx, dy):
            if self.debug:
                print(f"[CHASE] Oscillacao detectada para ({dx},{dy}), aguardando")
            self._next_step_time = now + 0.3 + random.uniform(0.05, 0.15)
            return ChaseResult.WAITING

        # Executa passo
        self._execute_step(dx, dy)
        self._record_step(dx, dy)

        if self.debug:
            print(f"[CHASE] Step ({dx},{dy}) - player ({my_x},{my_y}) -> target ({creature_x},{creature_y}) dist={dist}")

        return ChaseResult.STEPPED

    # =========================================================================
    # MOVEMENT EXECUTION (mesma formula do cavebot/navigation_utils)
    # =========================================================================

    def _execute_step(self, dx, dy):
        """Envia walk packet e calcula delay humanizado."""
        opcode = DIRECTION_TO_OPCODE.get((dx, dy))
        if not opcode:
            if self.debug:
                print(f"[CHASE] Direcao invalida: ({dx},{dy})")
            return

        self.packet.walk(opcode)

        # Atualiza cache de velocidade (a cada 2s)
        now = time.time()
        if now - self._last_speed_check > 2.0:
            self._cached_speed = get_player_speed(self.pm, self.base_addr)
            if self._cached_speed <= 0:
                self._cached_speed = 220
            self._last_speed_check = now

        player_speed = self._cached_speed

        # Ground speed do tile de destino
        ground_speed = self.analyzer.get_ground_speed(dx, dy)

        # Diagonal = 3x mais lento (mecanica Tibia 7.7)
        is_diagonal = (dx != 0 and dy != 0)
        effective_speed = ground_speed * 3 if is_diagonal else ground_speed

        # Formula: base_ms = (1000 * effective_speed) / player_speed
        base_ms = (1000.0 * effective_speed) / player_speed

        # Direction change delay (simula tempo de reacao humano ao inverter)
        direction_change_delay = 0
        if self._last_step_dir is not None:
            last_dx, last_dy = self._last_step_dir
            # Direcao oposta
            if (dx == -last_dx and dy == -last_dy) and (dx != 0 or dy != 0):
                direction_change_delay = random.uniform(50, 150)

        # Jitter gaussiano ±4%
        jitter_std = base_ms * 0.04
        jitter = random.gauss(0, jitter_std)

        # Micro-pausa aleatoria (2% chance, 30-100ms)
        if random.random() < 0.02:
            jitter += random.uniform(30, 100)

        total_ms = base_ms + jitter + direction_change_delay

        # Pre-move buffer (antecipacao)
        pre_move_buffer = 150  # ms
        wait_time = (total_ms / 1000.0) - (pre_move_buffer / 1000.0)

        # Minimo 50ms para evitar flood
        wait_time = max(0.05, wait_time)

        self._next_step_time = time.time() + wait_time
        self._last_step_dir = (dx, dy)

    # =========================================================================
    # OSCILLATION DETECTION
    # =========================================================================

    def _record_step(self, dx, dy):
        """Registra passo no historico e reseta counters de stuck."""
        self._step_history.append((dx, dy))
        if len(self._step_history) > self._max_history:
            self._step_history.pop(0)
        # Reset stuck counter apos step bem-sucedido (mesma logica do cavebot)
        self._stuck_counter = 0

    def _detect_oscillation(self, dx, dy):
        """Detecta padroes de vai-volta (ex: N,S,N,S)."""
        if len(self._step_history) < 3:
            return False

        # Verifica padrao A,B,A,B (oscillacao de 2 passos)
        h = self._step_history
        proposed = (dx, dy)

        # Checa se os ultimos 3 passos + o proposto formam A,B,A,B
        if len(h) >= 3:
            if (h[-1] == proposed and h[-2] != proposed and
                    h[-3] == proposed):
                return True

        # Checa padrao de inversao simples (ultimo passo e oposto do proposto)
        if len(h) >= 2:
            last = h[-1]
            if (dx == -last[0] and dy == -last[1]) and (dx != 0 or dy != 0):
                second_last = h[-2]
                if second_last == proposed:
                    return True

        return False

    # =========================================================================
    # OBSTACLE CLEARING (baseado em navigation_utils.py)
    # =========================================================================

    def _try_clear_path(self, target_rel_x, target_rel_y):
        """Tenta limpar caminho na direcao do alvo."""
        from config import OBSTACLE_CLEARING_ENABLED, STACK_CLEARING_ENABLED

        if not OBSTACLE_CLEARING_ENABLED and not STACK_CLEARING_ENABLED:
            return False

        # Calcula direcao geral ao destino (normalizada -1, 0, 1)
        dir_x = 1 if target_rel_x > 0 else (-1 if target_rel_x < 0 else 0)
        dir_y = 1 if target_rel_y > 0 else (-1 if target_rel_y < 0 else 0)

        # Tiles adjacentes a verificar (prioriza direcao do destino)
        tiles_to_check = []
        if dir_x != 0 and dir_y != 0:
            tiles_to_check.append((dir_x, dir_y))  # Diagonal
        if dir_x != 0:
            tiles_to_check.append((dir_x, 0))  # Horizontal
        if dir_y != 0:
            tiles_to_check.append((0, dir_y))  # Vertical

        # Fallback: outras direcoes cardeais
        for d in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            if d not in tiles_to_check:
                tiles_to_check.append(d)

        for check_x, check_y in tiles_to_check:
            if check_x == 0 and check_y == 0:
                continue

            obstacle_info = self.analyzer.get_obstacle_type(check_x, check_y)
            if obstacle_info and obstacle_info.get('clearable') and obstacle_info.get('type') in ('MOVE', 'STACK'):
                if self._attempt_clear_obstacle(check_x, check_y):
                    return True

        return False

    def _attempt_clear_obstacle(self, rel_x, rel_y):
        """Tenta remover obstaculo de um tile."""
        from config import OBSTACLE_CLEARING_ENABLED, STACK_CLEARING_ENABLED

        try:
            obstacle = self.analyzer.get_obstacle_type(rel_x, rel_y)

            if not obstacle or not obstacle.get('clearable'):
                return False

            obs_type = obstacle.get('type')

            if obs_type == 'MOVE' and OBSTACLE_CLEARING_ENABLED:
                if self.debug:
                    print(f"[CHASE] Movendo MOVE item id={obstacle.get('item_id')} em ({rel_x},{rel_y})")
                return self._push_move_item(rel_x, rel_y, obstacle)
            elif obs_type == 'STACK' and STACK_CLEARING_ENABLED:
                if self.debug:
                    print(f"[CHASE] Movendo STACK item id={obstacle.get('item_id')} em ({rel_x},{rel_y})")
                return self._push_stack_item(rel_x, rel_y, obstacle)

            return False
        except Exception as e:
            if self.debug:
                print(f"[CHASE] _attempt_clear_obstacle ERRO: {e}")
            return False

    def _push_move_item(self, rel_x, rel_y, obstacle):
        """Move item bloqueador (mesa/cadeira) para tile adjacente."""
        from database.tiles_config import MOVE_IDS, BLOCKING_IDS

        item_id = obstacle.get('item_id')
        stack_pos = obstacle.get('stack_pos', 0)

        if not item_id:
            return False

        px, py, pz = get_player_pos(self.pm, self.base_addr)
        obs_x, obs_y = px + rel_x, py + rel_y

        # Prioridade 1: Tiles cardeais adjacentes ao player
        # Prioridade 2: Tiles diagonais adjacentes ao player
        # Prioridade 3: Tiles adjacentes ao obstaculo (fallback)
        candidates = []

        # Player adjacent (cardeais primeiro, depois diagonais)
        for adj_x, adj_y in [(-1, 0), (1, 0), (0, -1), (0, 1),
                              (-1, -1), (-1, 1), (1, -1), (1, 1)]:
            if adj_x == rel_x and adj_y == rel_y:
                continue  # Pula tile do obstaculo
            if adj_x == 0 and adj_y == 0:
                continue  # Pula tile do player
            candidates.append((adj_x, adj_y, 'player'))

        # Obstacle adjacent (fallback)
        for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1),
                        (-1, -1), (-1, 1), (1, -1), (1, 1)]:
            check_rel_x = rel_x + dx
            check_rel_y = rel_y + dy
            if check_rel_x == rel_x and check_rel_y == rel_y:
                continue
            if check_rel_x == 0 and check_rel_y == 0:
                continue
            # Evita duplicatas
            already = any(c[0] == check_rel_x and c[1] == check_rel_y for c in candidates)
            if not already:
                candidates.append((check_rel_x, check_rel_y, 'obstacle'))

        for check_rel_x, check_rel_y, ref in candidates:
            tile = self.memory_map.get_tile_visible(check_rel_x, check_rel_y)
            if not tile or not tile.items:
                continue

            # Verifica se tem item bloqueador
            has_blocking = False
            for tid in tile.items:
                if tid in MOVE_IDS or tid in BLOCKING_IDS:
                    has_blocking = True
                    break
            if has_blocking:
                continue

            # Verifica walkability
            props = self.analyzer.get_tile_properties(check_rel_x, check_rel_y)
            if not props.get('walkable'):
                continue

            # Tile valido - mover obstaculo
            dest_x = px + check_rel_x
            dest_y = py + check_rel_y
            pos_from = get_ground_pos(obs_x, obs_y, pz)
            pos_to = get_ground_pos(dest_x, dest_y, pz)

            self.packet.move_item(pos_from, pos_to, item_id, 1, stack_pos=stack_pos)

            if self.debug:
                print(f"[CHASE] Moveu {item_id} de ({obs_x},{obs_y}) para ({dest_x},{dest_y})")

            # Delay humanizado gaussiano (mesma distribuicao do cavebot)
            gauss_wait(1.0, 50)
            self._next_step_time = time.time() + 0.1
            return True

        return False

    def _push_stack_item(self, rel_x, rel_y, obstacle):
        """Move item STACK (parcel/box) - pode ir para tile do player."""
        item_id = obstacle.get('item_id')
        stack_pos = obstacle.get('stack_pos', 0)

        if not item_id:
            return False

        px, py, pz = get_player_pos(self.pm, self.base_addr)
        obs_x, obs_y = px + rel_x, py + rel_y

        # Prioridade 0: Move para tile do player (STACK items podem stackar)
        pos_from = get_ground_pos(obs_x, obs_y, pz)
        pos_to = get_ground_pos(px, py, pz)

        self.packet.move_item(pos_from, pos_to, item_id, 1, stack_pos=stack_pos)

        if self.debug:
            print(f"[CHASE] Moveu parcel {item_id} para pe do player ({px},{py})")

        # Delay humanizado gaussiano (mesma distribuicao do cavebot)
        gauss_wait(1.0, 50)
        self._next_step_time = time.time() + 0.1
        return True
