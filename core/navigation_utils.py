# core/navigation_utils.py
"""
Utilitario de navegacao standalone para movimentacao ate coordenadas exatas.
Usa pathfinding A* e movement via packets (sem mouse clicks).
"""

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
import time
import random

# Mapping de direcao para opcode
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

class SimpleNavigator:
    """
    Navegador simplificado para mover ate coordenada exata.
    Projetado para uso em runemaker, alarm e outros modulos.
    """

    def __init__(self, pm, base_addr, hwnd=None, packet=None):
        self.pm = pm
        self.base_addr = base_addr
        self.hwnd = hwnd
        self.packet = packet or PacketManager(pm, base_addr)

        # Componentes de navegacao
        self.memory_map = MemoryMap(pm, base_addr)
        self.analyzer = MapAnalyzer(self.memory_map)
        self.walker = AStarWalker(self.analyzer)

        # Estado
        self.stuck_counter = 0
        self.last_pos = None

    def navigate_to(self, target_pos, check_safety=None, max_steps=100,
                    clear_obstacles=True, log_func=None, allow_multifloor=True):
        """
        Navega ate a posicao alvo exata usando A* e packets.
        Suporta navegacao entre andares (escadas, buracos, rope, shovel).

        Args:
            target_pos: Tupla (x, y, z) da posicao alvo
            check_safety: Callback opcional que retorna False se deve abortar
            max_steps: Limite de passos para evitar loops infinitos
            clear_obstacles: Se True, tenta mover obstaculos bloqueadores
            log_func: Funcao de log opcional
            allow_multifloor: Se True, permite navegacao entre andares

        Returns:
            True se chegou no tile exato, False se abortou/falhou
        """
        from config import OFFSET_PLAYER_ID

        tx, ty, tz = target_pos
        steps_taken = 0
        last_step_succeeded = False  # Track if last step moved successfully (for fluid movement)

        while steps_taken < max_steps:
            # Atualiza mapa da memoria (CRITICO: sem isso, scan_for_floor_change retorna None)
            try:
                player_id = self.pm.read_int(self.base_addr + OFFSET_PLAYER_ID)
                self.memory_map.read_full_map(player_id)
            except:
                pass  # Continua mesmo se falhar

            # Verifica seguranca
            if check_safety and not check_safety():
                return False

            # Posicao atual
            px, py, pz = get_player_pos(self.pm, self.base_addr)

            # Chegou no tile exato?
            if px == tx and py == ty and pz == tz:
                self.stuck_counter = 0
                return True

            # Andar diferente - tenta transicao de andar
            if pz != tz:
                if not allow_multifloor:
                    if log_func:
                        log_func(f"Andar errado: {pz} vs {tz} (multifloor desabilitado)")
                    return False

                # Busca transicao de andar visivel
                floor_change = self.analyzer.scan_for_floor_change(
                    target_z=tz,
                    current_z=pz,
                    range_sqm=7,
                    dest_x=tx,
                    dest_y=ty
                )

                if floor_change:
                    rel_x, rel_y, ftype, special_id = floor_change
                    dist = max(abs(rel_x), abs(rel_y))

                    if dist <= 1:
                        # Adjacente: executa transicao
                        if log_func:
                            log_func(f"Usando {ftype} em ({rel_x},{rel_y})")
                        if self._handle_floor_change(rel_x, rel_y, ftype, special_id, px, py, pz):
                            time.sleep(0.3)
                            steps_taken += 1
                            continue
                    # Se distante, continua navegacao normal - A* vai direcionar
                else:
                    if log_func:
                        log_func(f"Sem transicao visivel de {pz} para {tz}")
                    return False

            # ===== FLUID MOVEMENT =====
            # Se acabamos de completar um step com sucesso, NÃO esperamos o player parar
            # Isso permite "pipelining" de comandos para movimento fluido
            player_moving = is_player_moving(self.pm, self.base_addr)

            if player_moving and not last_step_succeeded:
                # Player está movendo MAS não foi de um step nosso que acabou de suceder
                # Pode ser movimento externo ou primeiro step - espera
                time.sleep(0.02)
                continue

            # Reset flag - só vale para uma iteração
            last_step_succeeded = False

            # Calcula posicao relativa do alvo
            rel_x = tx - px
            rel_y = ty - py

            # Obtem proximo passo via A*
            step = self.walker.get_next_step(rel_x, rel_y, activate_fallback=True)

            if step is None:
                # Sem caminho - tenta clear obstacle
                if clear_obstacles and self._try_clear_path(rel_x, rel_y):
                    time.sleep(0.5)
                    continue

                self.stuck_counter += 1
                if self.stuck_counter > 5:
                    if log_func:
                        log_func("Completamente bloqueado!")
                    return False
                time.sleep(0.3)
                continue

            dx, dy = step

            # Verifica se o tile esta bloqueado
            tile_props = self.analyzer.get_tile_properties(dx, dy)

            # BUG FIX: Verificar se tem MOVE/STACK item MESMO QUE "walkable"
            # (quando OBSTACLE_CLEARING_ENABLED=True, mesas são removidas de BLOCKING_IDS,
            # fazendo o tile parecer walkable, mas fisicamente ainda bloqueia!)
            if clear_obstacles:
                obstacle = self.analyzer.get_obstacle_type(dx, dy)
                if obstacle.get('type') in ('MOVE', 'STACK') and obstacle.get('clearable'):
                    print(f"[NAV] Detectou {obstacle.get('type')} no caminho, tentando limpar...")
                    if self._attempt_clear_obstacle(dx, dy):
                        time.sleep(0.5)
                        continue
                # Fallback: se não é walkable por outro motivo
                elif not tile_props.get('walkable') and obstacle.get('clearable'):
                    if self._attempt_clear_obstacle(dx, dy):
                        time.sleep(0.5)
                        continue

            # Executa o passo via packet
            opcode = DIRECTION_TO_OPCODE.get((dx, dy))
            if opcode:
                step_start = time.time()
                self.packet.walk(opcode)
                steps_taken += 1

                # Delay humanizado baseado no ground speed
                delay = self._get_step_delay(dx, dy)
                time.sleep(delay)

                # Verifica se moveu
                new_x, new_y, _ = get_player_pos(self.pm, self.base_addr)
                step_total = (time.time() - step_start) * 1000
                print(f"[NAV DEBUG] Step complete: ({px},{py})→({new_x},{new_y}) total_time={step_total:.0f}ms")

                if (new_x, new_y) == (px, py):
                    self.stuck_counter += 1
                    last_step_succeeded = False  # Não conseguiu mover
                    print(f"[NAV DEBUG] STUCK! counter={self.stuck_counter}")
                else:
                    self.stuck_counter = 0
                    last_step_succeeded = True  # Step OK - próxima iteração pode enviar imediatamente
            else:
                time.sleep(0.1)

        return False  # Excedeu max_steps

    def _get_step_delay(self, dx, dy):
        """Calcula delay humanizado para um passo (mesma lógica do cavebot)."""
        try:
            ground_speed = self.analyzer.get_ground_speed(dx, dy)
            player_speed = get_player_speed(self.pm, self.base_addr)
            if player_speed <= 0:
                player_speed = 220  # Fallback

            # Diagonal = 3x o custo
            multiplier = 3 if (dx != 0 and dy != 0) else 1
            effective_speed = ground_speed * multiplier

            # Fórmula do Tibia
            base_ms = (1000.0 * effective_speed) / player_speed

            # Jitter gaussiano ±4% (mais humano que uniforme)
            jitter_std = base_ms * 0.04
            jitter = random.gauss(0, jitter_std)

            # Micro-pausa aleatória (2% chance, 30-100ms)
            if random.random() < 0.02:
                jitter += random.uniform(30, 100)

            total_ms = base_ms + jitter

            # Pre-move buffer (antecipação - envia comando antes de terminar)
            # 180ms é mais agressivo que cavebot (150ms), mas is_player_moving atua como safety net
            pre_move_buffer = 180  # ms
            wait_time = (total_ms / 1000.0) - (pre_move_buffer / 1000.0)

            # Mínimo 50ms para evitar flood
            final_delay = max(0.05, wait_time)

            # DEBUG: Log do cálculo de delay
            print(f"[NAV DEBUG] Step({dx},{dy}) ground={ground_speed} player={player_speed} "
                  f"base={base_ms:.0f}ms total={total_ms:.0f}ms wait={final_delay*1000:.0f}ms")

            return final_delay
        except Exception as e:
            print(f"[NAV DEBUG] Exception in _get_step_delay: {e}")
            return 0.15 + random.uniform(0.01, 0.05)  # Fallback mais rápido

    def _try_clear_path(self, target_rel_x, target_rel_y):
        """
        Tenta limpar caminho na direção do alvo.
        Usa a mesma lógica do cavebot para calcular direção.
        """
        # Calcular direção geral ao destino (normalizada para -1, 0, ou 1)
        dir_x = 1 if target_rel_x > 0 else (-1 if target_rel_x < 0 else 0)
        dir_y = 1 if target_rel_y > 0 else (-1 if target_rel_y < 0 else 0)

        # Tiles adjacentes a verificar (prioriza direção do destino)
        tiles_to_check = []

        # 1. Direção diagonal (se aplicável)
        if dir_x != 0 and dir_y != 0:
            tiles_to_check.append((dir_x, dir_y))

        # 2. Direção horizontal
        if dir_x != 0:
            tiles_to_check.append((dir_x, 0))

        # 3. Direção vertical
        if dir_y != 0:
            tiles_to_check.append((0, dir_y))

        # 4. Fallback: outras direções cardeais (para casos de rota não-linear)
        for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            if (dx, dy) not in tiles_to_check:
                tiles_to_check.append((dx, dy))

        for check_x, check_y in tiles_to_check:
            if check_x == 0 and check_y == 0:
                continue

            obstacle_info = self.analyzer.get_obstacle_type(check_x, check_y)

            if obstacle_info.get('clearable') and obstacle_info.get('type') in ('MOVE', 'STACK'):
                if self._attempt_clear_obstacle(check_x, check_y):
                    return True

        return False

    def _attempt_clear_obstacle(self, rel_x, rel_y):
        """
        Tenta remover obstaculo de um tile.
        Baseado no _attempt_clear_obstacle do cavebot.
        """
        try:
            obstacle = self.analyzer.get_obstacle_type(rel_x, rel_y)

            # DEBUG: Log para diagnosticar problemas
            print(f"[NAV] _attempt_clear_obstacle({rel_x},{rel_y}): {obstacle}")

            if not obstacle or not obstacle.get('clearable'):
                return False

            obs_type = obstacle.get('type')

            if obs_type == 'MOVE':
                print(f"[NAV] Tentando mover MOVE item id={obstacle.get('item_id')} stack={obstacle.get('stack_pos')}")
                return self._push_move_item(rel_x, rel_y, obstacle)
            elif obs_type == 'STACK':
                print(f"[NAV] Tentando mover STACK item id={obstacle.get('item_id')} stack={obstacle.get('stack_pos')}")
                return self._push_stack_item(rel_x, rel_y, obstacle)

            return False
        except Exception as e:
            print(f"[NAV] _attempt_clear_obstacle ERRO: {e}")
            return False

    def _push_move_item(self, rel_x, rel_y, obstacle):
        """Move item bloqueador para tile adjacente."""
        from database.tiles_config import MOVE_IDS, BLOCKING_IDS

        item_id = obstacle.get('item_id')
        stack_pos = obstacle.get('stack_pos', 0)

        if not item_id:
            print(f"[NAV] _push_move_item: item_id é None, abortando")
            return False

        px, py, pz = get_player_pos(self.pm, self.base_addr)
        obs_x, obs_y = px + rel_x, py + rel_y

        # Tenta mover para tiles adjacentes ao obstaculo
        # (prioriza tiles adjacentes ao PLAYER como no cavebot)
        player_adjacent = [(-1, 0), (1, 0), (0, -1), (0, 1)]  # Cardeais ao player
        obstacle_adjacent = [
            (rel_x - 1, rel_y), (rel_x + 1, rel_y),
            (rel_x, rel_y - 1), (rel_x, rel_y + 1),
        ]

        # Primeiro tenta tiles adjacentes ao player
        for adj_x, adj_y in player_adjacent:
            # Pula tile onde o obstáculo está
            if adj_x == rel_x and adj_y == rel_y:
                continue
            # Pula tile onde o player está
            if adj_x == 0 and adj_y == 0:
                continue

            # Verifica se destino tem item bloqueador (outra mesa, etc)
            dest_tile = self.memory_map.get_tile_visible(adj_x, adj_y)
            if not dest_tile or not dest_tile.items:
                continue  # Tile vazio/inexistente

            has_blocking = False
            for tile_item_id in dest_tile.items:
                if tile_item_id in MOVE_IDS or tile_item_id in BLOCKING_IDS:
                    print(f"[NAV] ({adj_x},{adj_y}) já tem item bloqueador {tile_item_id}, pulando")
                    has_blocking = True
                    break

            if has_blocking:
                continue

            adj_props = self.analyzer.get_tile_properties(adj_x, adj_y)
            if adj_props.get('walkable'):
                pos_from = get_ground_pos(obs_x, obs_y, pz)
                pos_to = get_ground_pos(px + adj_x, py + adj_y, pz)

                print(f"[NAV] Movendo item {item_id} de ({obs_x},{obs_y}) para ({px + adj_x},{py + adj_y})")
                self.packet.move_item(pos_from, pos_to, item_id, 1, stack_pos=stack_pos)
                time.sleep(0.4 + random.uniform(0.1, 0.2))
                return True

        # Fallback: tiles adjacentes ao obstáculo
        for adj_x, adj_y in obstacle_adjacent:
            # Pula tile onde o player está
            if adj_x == 0 and adj_y == 0:
                continue

            # Verifica se destino tem item bloqueador
            dest_tile = self.memory_map.get_tile_visible(adj_x, adj_y)
            if not dest_tile or not dest_tile.items:
                continue

            has_blocking = False
            for tile_item_id in dest_tile.items:
                if tile_item_id in MOVE_IDS or tile_item_id in BLOCKING_IDS:
                    has_blocking = True
                    break

            if has_blocking:
                continue

            adj_props = self.analyzer.get_tile_properties(adj_x, adj_y)
            if adj_props.get('walkable'):
                pos_from = get_ground_pos(obs_x, obs_y, pz)
                pos_to = get_ground_pos(px + adj_x, py + adj_y, pz)

                print(f"[NAV] Movendo item {item_id} de ({obs_x},{obs_y}) para ({px + adj_x},{py + adj_y}) (fallback)")
                self.packet.move_item(pos_from, pos_to, item_id, 1, stack_pos=stack_pos)
                time.sleep(0.4 + random.uniform(0.1, 0.2))
                return True

        print(f"[NAV] _push_move_item: nenhum tile livre encontrado para mover item")
        return False

    def _push_stack_item(self, rel_x, rel_y, obstacle):
        """Empilha item em outro tile."""
        # Similar ao _push_move_item, mas permite stackar
        return self._push_move_item(rel_x, rel_y, obstacle)

    # =========================================================================
    # MULTIFLOOR NAVIGATION
    # =========================================================================

    def _handle_floor_change(self, rel_x, rel_y, ftype, special_id, px, py, pz):
        """
        Executa transicao de andar baseado no tipo.
        Baseado em cavebot._handle_special_tile()
        """
        from core.player_core import wait_until_stopped
        from database.tiles_config import ROPE_ITEM_ID, SHOVEL_ITEM_ID

        # Aguarda parar antes de transicao
        if not wait_until_stopped(self.pm, self.base_addr, packet=self.packet, timeout=1.5):
            return False

        # UP_WALK / DOWN: Apenas andar no tile
        if ftype in ('UP_WALK', 'DOWN'):
            # Normaliza step para direcao unitaria
            if rel_x != 0:
                step_x = 1 if rel_x > 0 else -1
            else:
                step_x = 0
            if rel_y != 0:
                step_y = 1 if rel_y > 0 else -1
            else:
                step_y = 0

            # Se diagonal, prioriza eixo maior para alinhar
            if abs(rel_x) > 0 and abs(rel_y) > 0:
                if abs(rel_x) >= abs(rel_y):
                    step = (step_x, 0)
                else:
                    step = (0, step_y)
            else:
                step = (step_x, step_y)

            opcode = DIRECTION_TO_OPCODE.get(step)
            if opcode:
                self.packet.walk(opcode)
                time.sleep(0.8)
                return True
            return False

        # UP_USE / DOWN_USE: Usar item (ladder, sewer grate)
        if ftype in ('UP_USE', 'DOWN_USE'):
            return self._use_floor_tile(px + rel_x, py + rel_y, pz, special_id, rel_x, rel_y)

        # ROPE: Usar rope no spot
        if ftype == 'ROPE':
            return self._use_rope(px, py, pz, rel_x, rel_y, special_id)

        # SHOVEL: Usar shovel na pedra
        if ftype == 'SHOVEL':
            return self._use_shovel(px, py, pz, rel_x, rel_y, special_id)

        return False

    def _use_floor_tile(self, target_x, target_y, target_z, tile_id, rel_x, rel_y):
        """Usa tile de transicao (ladder, sewer grate)."""
        if not tile_id:
            return False

        # Encontra stackpos correto
        tile = self.memory_map.get_tile_visible(rel_x, rel_y)
        if not tile:
            return False

        stack_pos = 0
        for i, item_id in enumerate(tile.items):
            if item_id == tile_id:
                stack_pos = i
                break

        pos = get_ground_pos(target_x, target_y, target_z)
        self.packet.use_item(pos, tile_id, stack_pos)
        time.sleep(0.8)
        return True

    def _use_rope(self, px, py, pz, rel_x, rel_y, rope_tile_id):
        """Usa rope em rope spot."""
        from database.tiles_config import ROPE_ITEM_ID

        # Busca rope no inventario
        rope_source = self._find_item_position(ROPE_ITEM_ID)
        if not rope_source:
            return False

        # Limpa spot se necessario
        if not self._clear_rope_spot(rel_x, rel_y, px, py, pz, rope_tile_id):
            return False

        target_pos = get_ground_pos(px + rel_x, py + rel_y, pz)
        self.packet.use_with(rope_source, ROPE_ITEM_ID, 0, target_pos, rope_tile_id or 386, 0)
        time.sleep(1.0)
        return True

    def _use_shovel(self, px, py, pz, rel_x, rel_y, pile_id):
        """Usa shovel em stone pile."""
        from database.tiles_config import SHOVEL_ITEM_ID

        shovel_source = self._find_item_position(SHOVEL_ITEM_ID)
        if not shovel_source:
            return False

        target_pos = get_ground_pos(px + rel_x, py + rel_y, pz)
        self.packet.use_with(shovel_source, SHOVEL_ITEM_ID, 0, target_pos, pile_id, 0)
        time.sleep(1.0)
        return True

    def _find_item_position(self, item_id):
        """Busca item no inventario (slots de equipamento ou containers)."""
        from core.inventory_core import find_item_in_containers
        from core.packet import get_inventory_pos, get_container_pos
        from config import SLOT_RIGHT, SLOT_LEFT, OFFSET_SLOT_RIGHT, OFFSET_SLOT_LEFT

        # Checa slots de equipamento
        for slot, offset in [(SLOT_RIGHT, OFFSET_SLOT_RIGHT), (SLOT_LEFT, OFFSET_SLOT_LEFT)]:
            try:
                slot_item = self.pm.read_int(self.base_addr + offset)
                if slot_item == item_id:
                    return get_inventory_pos(slot)
            except:
                pass

        # Busca em containers
        item_data = find_item_in_containers(self.pm, self.base_addr, item_id)
        if item_data:
            return get_container_pos(item_data['container_index'], item_data['slot_index'])

        return None

    def _clear_rope_spot(self, rel_x, rel_y, px, py, pz, rope_tile_id):
        """Limpa rope spot se tiver item bloqueando."""
        tile = self.memory_map.get_tile_visible(rel_x, rel_y)
        if not tile or not tile.items:
            return False

        top_item = tile.items[-1] if tile.items else 0

        # Se top item e o rope spot ou ground, esta limpo
        if top_item == rope_tile_id or top_item < 100:
            return True

        # Se e criatura, nao pode limpar
        if top_item == 99:
            return False

        # Move item bloqueador para tile do player
        pos_from = get_ground_pos(px + rel_x, py + rel_y, pz)
        pos_to = get_ground_pos(px, py, pz)
        stack_pos = len(tile.items) - 1

        self.packet.move_item(pos_from, pos_to, top_item, stack_pos)
        time.sleep(0.5)
        return True


def navigate_to_position(pm, base_addr, hwnd, target_pos,
                         check_safety=None, packet=None,
                         clear_obstacles=True, log_func=None,
                         allow_multifloor=True):
    """
    Funcao wrapper para navegacao completa (com suporte multifloor).

    Args:
        pm: Pymem instance
        base_addr: Base address do processo
        hwnd: Window handle
        target_pos: Tupla (x, y, z) da posicao alvo
        check_safety: Callback que retorna False para abortar
        packet: PacketManager existente (opcional)
        clear_obstacles: Se True, move obstaculos bloqueadores
        log_func: Funcao de log
        allow_multifloor: Se True, permite navegacao entre andares

    Returns:
        True se chegou na posicao exata, False caso contrario
    """
    navigator = SimpleNavigator(pm, base_addr, hwnd, packet)
    return navigator.navigate_to(
        target_pos,
        check_safety=check_safety,
        clear_obstacles=clear_obstacles,
        log_func=log_func,
        allow_multifloor=allow_multifloor
    )
