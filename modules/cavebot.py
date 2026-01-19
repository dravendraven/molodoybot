# modules/cavebot.py
import random
import time
import math
import threading

from utils.timing import gauss_wait
from config import *
from core.packet import (
    PacketManager, get_ground_pos, get_container_pos, get_inventory_pos,
    OP_WALK_NORTH, OP_WALK_EAST, OP_WALK_SOUTH, OP_WALK_WEST,
    OP_WALK_NORTH_EAST, OP_WALK_SOUTH_EAST, OP_WALK_SOUTH_WEST, OP_WALK_NORTH_WEST,
    OP_STOP
)
# PacketMutex removido - locks globais em PacketManager cuidam da sincronização
from core.map_core import get_player_pos
from core.map_analyzer import MapAnalyzer
from core.astar_walker import AStarWalker
from core.memory_map import MemoryMap
from core.inventory_core import find_item_in_containers, find_item_in_equipment # Necessário para achar a corda
from database.tiles_config import ROPE_ITEM_ID, SHOVEL_ITEM_ID, get_ground_speed
from core.bot_state import state
from core.global_map import GlobalMap
from core.player_core import get_player_speed, is_player_moving, wait_until_stopped


COOLDOWN_AFTER_COMBAT = random.uniform(2.5, 5)  # 1s a 1.5s de cooldown após combate
GLOBAL_RECALC_LIMIT = 5

# Mapeamento de Delta (dx, dy) para Opcode do Packet
MOVE_OPCODES = {
    (0, -1): OP_WALK_NORTH,
    (0, 1):  OP_WALK_SOUTH,
    (-1, 0): OP_WALK_WEST,
    (1, 0):  OP_WALK_EAST,
    (1, -1): OP_WALK_NORTH_EAST,
    (1, 1):  OP_WALK_SOUTH_EAST,
    (-1, 1): OP_WALK_SOUTH_WEST,
    (-1, -1): OP_WALK_NORTH_WEST
}

class Cavebot:
    # Estados possíveis do cavebot
    STATE_IDLE = "idle"
    STATE_WALKING = "walking"
    STATE_FLOOR_CHANGE = "floor_change"
    STATE_RECALCULATING = "recalculating"
    STATE_STUCK = "stuck"
    STATE_COMBAT_COOLDOWN = "combat_cooldown"
    STATE_FLOOR_COOLDOWN = "floor_cooldown"
    STATE_PAUSED = "paused"
    STATE_WAYPOINT_REACHED = "waypoint_reached"

    def __init__(self, pm, base_addr, maps_directory=None):
        self.pm = pm
        self.base_addr = base_addr

        # Inicializa o PacketManager
        self.packet = PacketManager(pm, base_addr)

        # Inicializa o MemoryMap e o Analisador
        self.memory_map = MemoryMap(pm, base_addr)
        self.analyzer = MapAnalyzer(self.memory_map)
        self.walker = AStarWalker(self.analyzer, debug=DEBUG_PATHFINDING)

        # [NAVEGAÇÃO HIBRIDA] Inicializa o "GPS" (Global)
        # Usa maps_directory passado como parâmetro, ou fallback para config.py
        effective_maps_dir = maps_directory if maps_directory else MAPS_DIRECTORY
        self.global_map = GlobalMap(effective_maps_dir, WALKABLE_COLORS)
        self.current_global_path = [] # Lista de nós [(x,y,z), ...] da rota atual

        # Thread-safe waypoints
        self._waypoints_lock = threading.Lock()
        self._waypoints = []
        self._current_index = 0
        self._direction = 1  # 1 = forward (0→50), -1 = backward (50→0)

        self.enabled = False
        self.last_action_time = 0

        # Detecção de stuck
        self.stuck_counter = 0
        self.last_known_pos = None
        self.stuck_threshold = 10  # 5 segundos (10 * 0.5s)
        self.global_recalc_counter = 0 # Para acionar o GlobalMap

        # --- CONFIGURAÇÃO DE FLUIDEZ (NOVO) ---
        self.walk_delay = 0.4 # Valor base, será sobrescrito dinamicamente
        self.local_path_cache = [] # Armazena a lista de passos [(dx,dy), ...]
        self.local_path_index = 0  # Qual passo estamos executando
        self.cached_speed = 250    # Cache de velocidade para não ler battle list todo frame
        self.last_speed_check = 0  # Timestamp da última leitura de speed
        self.last_floor_change_time = 0  # Timestamp do último floor change (subir/descer andar)

        # --- ESTADO PARA MINIMAP (NOVO) ---
        self.current_state = self.STATE_IDLE
        self.state_message = ""  # Mensagem detalhada para exibição

    def load_waypoints(self, waypoints_list):
        """
        Carrega lista de waypoints com validação thread-safe.
        Ex: [{'x': 32000, 'y': 32000, 'z': 7, 'action': 'walk'}, ...]
        """
        validated = []

        for i, wp in enumerate(waypoints_list):
            try:
                # Validação de estrutura
                if not isinstance(wp, dict):
                    print(f"[Cavebot] Aviso: Waypoint {i} não é dict, ignorando")
                    continue

                # Validação de campos obrigatórios
                if 'x' not in wp or 'y' not in wp or 'z' not in wp:
                    print(f"[Cavebot] Aviso: Waypoint {i} falta coordenadas (x, y, z), ignorando")
                    continue

                # Validação de tipos
                if not isinstance(wp['x'], (int, float)) or \
                   not isinstance(wp['y'], (int, float)) or \
                   not isinstance(wp['z'], (int, float)):
                    print(f"[Cavebot] Aviso: Waypoint {i} coordenadas inválidas, ignorando")
                    continue

                validated.append(wp)
            except Exception as e:
                print(f"[Cavebot] Erro ao validar waypoint {i}: {e}")
                continue

        # Thread-safe assignment
        with self._waypoints_lock:
            self._waypoints = validated

            # ✅ NOVO: Inicialização inteligente baseada em waypoint mais próximo
            if validated:
                try:
                    px, py, pz = get_player_pos(self.pm, self.base_addr)

                    closest_idx = 0
                    closest_dist = float('inf')

                    for i, wp in enumerate(validated):
                        # Distância Euclidiana (mesma usada no run_cycle linha 195)
                        dist = math.sqrt((wp['x'] - px)**2 + (wp['y'] - py)**2)

                        # Penaliza waypoints em andares diferentes
                        if wp['z'] != pz:
                            dist += 1000  # Prefer same floor

                        if dist < closest_dist:
                            closest_dist = dist
                            closest_idx = i

                    self._current_index = closest_idx
                    self._direction = 1  # Sempre FORWARD e ciclico

                    print(f"[Cavebot] 🎯 Inicialização inteligente: WP mais próximo é #{closest_idx} (Dist: {closest_dist:.1f} SQM)")
                    print(f"[Cavebot]    Navegação: #{closest_idx} → #{closest_idx + 1} → ... → #{len(validated) - 1} → #0 → #1 ... (FORWARD ciclico)")

                except Exception as e:
                    # Fallback para comportamento padrão se houver erro
                    print(f"[Cavebot] ⚠️ Erro ao calcular waypoint inicial: {e}")
                    self._current_index = 0
                    self._direction = 1
            else:
                self._current_index = 0
                self._direction = 1

        print(f"[Cavebot] Carregados {len(validated)} waypoints válidos de {len(waypoints_list)} totais")

    def start(self):
        self.enabled = True
        state.set_cavebot_state(True)  # Notifica que Cavebot está ativo

        # NOVO: Sincroniza com estado atual do jogo ao (re)iniciar
        # Isso garante que se o player se moveu durante pause, o cavebot
        # usa a posição REAL da tela, não dados em cache
        with self._waypoints_lock:
            if self._waypoints:
                try:
                    # 1. Recalibra o mapa para ler posição atual da tela
                    player_id = self.pm.read_int(self.base_addr + OFFSET_PLAYER_ID)
                    self.memory_map.read_full_map(player_id)

                    # 2. Agora lê a posição atualizada
                    px, py, pz = get_player_pos(self.pm, self.base_addr)

                    # 3. Encontra waypoint mais próximo
                    closest_idx = 0
                    closest_dist = float('inf')

                    for i, wp in enumerate(self._waypoints):
                        dist = math.sqrt((wp['x'] - px)**2 + (wp['y'] - py)**2)

                        # Penaliza waypoints em andares diferentes
                        if wp['z'] != pz:
                            dist += 1000

                        if dist < closest_dist:
                            closest_dist = dist
                            closest_idx = i

                    old_idx = self._current_index

                    # 4. Atualiza índice e limpa caches para forçar recálculo
                    self._current_index = closest_idx
                    self.current_global_path = []
                    self.local_path_cache = []
                    self.global_recalc_counter = 0
                    self.stuck_counter = 0
                    self.last_known_pos = None

                    if old_idx != closest_idx:
                        print(f"[Cavebot] 🎯 Reposicionado: WP #{old_idx} → #{closest_idx} (Pos: {px},{py},{pz} | Dist: {closest_dist:.1f} SQM)")
                    else:
                        print(f"[Cavebot] ✓ Mantendo WP #{closest_idx} (Pos: {px},{py},{pz} | Dist: {closest_dist:.1f} SQM)")

                except Exception as e:
                    print(f"[Cavebot] ⚠️ Erro ao sincronizar estado: {e}")

        print("[Cavebot] Iniciado.")

    def stop(self):
        self.enabled = False
        state.set_cavebot_state(False)  # Notifica que Cavebot está inativo
        print("[Cavebot] Parado.")

    def run_cycle(self):
        """Deve ser chamado no loop principal do bot."""
        # Thread-safe check de waypoints
        with self._waypoints_lock:
            if not self.enabled or not self._waypoints:
                return

            # Cópia local para evitar lock durante todo ciclo
            current_waypoints = self._waypoints
            current_index = self._current_index

        # NOVO: Pausa APENAS se GM detectado (não pausa para criaturas/players)
        if state.is_gm_detected:
            self.current_state = self.STATE_PAUSED
            self.state_message = "⏸️ Pausado (GM detectado)"
            # Reseta cooldown para evitar movimento imediato ao retomar
            self.last_action_time = time.time()
            return

        # NOVO: Pausa enquanto runemaker está ativo
        if state.is_runemaking:
            self.current_state = self.STATE_PAUSED
            self.state_message = "⏸️ Pausado (Runemaker ativo)"
            self.last_action_time = time.time()
            if DEBUG_PATHFINDING:
                print(f"[Cavebot] ⏸️ PAUSA: Runemaker ativo")
            return

        # NOVO: Pausa para atividades de maior prioridade
        # Aguarda combate terminar E auto-loot finalizar completamente
        if state.is_in_combat or state.has_open_loot:
            self.last_action_time = time.time()
            # Atualiza status para exibição na GUI
            reasons = []
            if state.is_in_combat:
                reasons.append("Combate")
            if state.has_open_loot:
                reasons.append("Loot")
            self.current_state = self.STATE_PAUSED
            self.state_message = f"⏸️ Pausado ({', '.join(reasons)})"
            if DEBUG_PATHFINDING:
                print(f"[Cavebot] {self.state_message}")
            return

        # NOVO: Cooldown de 1s após combate/loot para estabilização
        # Evita race condition: matar criatura → delay 1s → abrir loot → próximo combate
        if time.time() - state.last_combat_time < COOLDOWN_AFTER_COMBAT:
            remaining = COOLDOWN_AFTER_COMBAT - (time.time() - state.last_combat_time)
            self.current_state = self.STATE_COMBAT_COOLDOWN
            self.state_message = f"⏰ Cooldown pós-combate ({remaining:.1f}s)"
            if DEBUG_PATHFINDING:
                print(f"[Cavebot] ⏸️ Cooldown pós-combate: {remaining:.1f}s")
            self.last_action_time = time.time()
            return

        # Controle de Cooldown
        if time.time() - self.last_action_time < self.walk_delay:
            return

        # NOVO: Cooldown após mudança de andar (floor change)
        # Aguarda 1 segundo após subir/descer para permitir combate no novo andar
        FLOOR_CHANGE_COOLDOWN = 1.0
        if time.time() - self.last_floor_change_time < FLOOR_CHANGE_COOLDOWN:
            remaining = FLOOR_CHANGE_COOLDOWN - (time.time() - self.last_floor_change_time)
            self.current_state = self.STATE_FLOOR_COOLDOWN
            self.state_message = "⏰ Cooldown pós-stairs"
            if DEBUG_PATHFINDING:
                print(f"[Cavebot] ⏸️ Cooldown pós-floor-change: {remaining:.1f}s")
            self.last_action_time = time.time()
            return

        # 1. Atualizar Posição e Mapa
        px, py, pz = get_player_pos(self.pm, self.base_addr)
        player_id = self.pm.read_int(self.base_addr + OFFSET_PLAYER_ID)
        success = self.memory_map.read_full_map(player_id)

        # RETRY LOGIC: Se calibração falhar, tenta novamente
        if not success or not self.memory_map.is_calibrated:
            print(f"[Cavebot] Calibração do mapa falhou, tentando novamente...")
            time.sleep(0.1)  # Aguarda 100ms para estabilizar
            player_id = self.pm.read_int(self.base_addr + OFFSET_PLAYER_ID)
            success = self.memory_map.read_full_map(player_id)

            if not success or not self.memory_map.is_calibrated:
                print(f"[Cavebot] ⚠️ Calibração falhou novamente. Pulando ciclo.")
                self.last_action_time = time.time()
                return

        # 2. Selecionar Waypoint Atual (thread-safe)
        wp = current_waypoints[current_index]

        # DEBUG: Estado do Cérebro do Cavebot
        if DEBUG_PATHFINDING:
            print(f"\n[🧠 CAVEBOT] Posição: ({px}, {py}, {pz}) | WP Atual: #{current_index}/{len(current_waypoints)-1} → ({wp['x']}, {wp['y']}, {wp['z']})")

        # 3. Checar se chegou (Distância < 1.5 SQM e mesmo Z)
        dist = math.sqrt((wp['x'] - px)**2 + (wp['y'] - py)**2)

        if dist <= 1.5 and wp['z'] == pz:
            self.current_state = self.STATE_WAYPOINT_REACHED
            self.state_message = f"✅ Waypoint #{current_index + 1} alcançado"
            print(f"[Cavebot] ✅ Chegou no WP {current_index}: ({wp['x']}, {wp['y']}, {wp['z']})")
            with self._waypoints_lock:
                self._advance_waypoint()
                self.current_global_path = []
                self.last_lookahead_idx = -1
            return

        # ======================================================================
        # 4. LÓGICA DE ANDARES (FLOOR CHANGE)
        # ======================================================================
        if wp['z'] != pz:
            direction = "↑ SUBIR" if wp['z'] < pz else "↓ DESCER"
            self.current_state = self.STATE_FLOOR_CHANGE
            self.state_message = f"🪜 Mudança de andar ({direction} para Z={wp['z']})"
            if DEBUG_PATHFINDING:
                print(f"[🪜 FLOOR CHANGE] Necessário {direction}: Z atual={pz} → Z alvo={wp['z']}")

            # O scanner retorna: (rel_x, rel_y, type, special_id)
            floor_target = self.analyzer.scan_for_floor_change(wp['z'], pz)

            if floor_target:
                fx, fy, ftype, fid = floor_target
                dist_obj = math.sqrt(fx**2 + fy**2)

                if DEBUG_PATHFINDING:
                    print(f"[🪜 FLOOR CHANGE] Encontrado {ftype} (ID:{fid}) em ({fx:+d}, {fy:+d}), distância={dist_obj:.1f} SQM")

                # Se estamos ADJACENTES (dist <= 1.5) ou EM CIMA (dist == 0)
                # Para Ladder e Rope, precisamos estar PERTO.
                if dist_obj <= 1.5:
                    if DEBUG_PATHFINDING:
                        print(f"[🪜 FLOOR CHANGE] ✓ Adjacente ao {ftype}, executando...")
                    self._handle_special_tile(fx, fy, ftype, fid, px, py, pz)

                    # NOVO: Registra timestamp do floor change para cooldown
                    self.last_floor_change_time = time.time()
                    if DEBUG_PATHFINDING:
                        print(f"[🪜 FLOOR CHANGE] ⏳ Aguardando 1s para permitir combate no novo andar")

                    # Após uma interação de andar/usar, a posição global pode ter mudado (ex: subir de andar).
                    npx, npy, npz = get_player_pos(self.pm, self.base_addr)
                    if wp['z'] == npz:
                        dist_after = math.sqrt((wp['x'] - npx) ** 2 + (wp['y'] - npy) ** 2)
                        if dist_after <= 1.5:
                            print(f"[Cavebot] Chegou no WP {current_index} após floor change")
                            with self._waypoints_lock:
                                self._advance_waypoint()
                            self.last_action_time = time.time()
                            return
                else:
                    # Para escadas de USE, prefira parar em um tile cardinal adjacente e usar à distância.
                    target_fx, target_fy = fx, fy
                    if ftype == 'UP_USE':
                        target_fx, target_fy = self._get_adjacent_use_tile(fx, fy)

                    if DEBUG_PATHFINDING:
                        print(f"[🪜 FLOOR CHANGE] Longe do {ftype}, calculando caminho para ({target_fx:+d}, {target_fy:+d})...")
                    abs_ladder_x = px + target_fx
                    abs_ladder_y = py + target_fy
                    self._navigate_hybrid(abs_ladder_x, abs_ladder_y, pz, px, py)
            else:
                print(f"[Cavebot] ⚠️ Nenhuma escada/rope encontrada! Z atual={pz}, Z alvo={wp['z']}")
            
            self.last_action_time = time.time()
            return
    
        # ======================================================================
        # 5. NAVEGAÇÃO HÍBRIDA (Substitui o antigo "Caminho Normal")
        # ======================================================================
        # Chama a função que integra GlobalMap e Local A*
        self._navigate_hybrid(wp['x'], wp['y'], wp['z'], px, py)
        
        self.last_action_time = time.time()
        
        # Detecção de Stuck Geral (player parado no mesmo tile)
        self._check_stuck(px, py, pz, current_index)

    def _navigate_hybrid(self, dest_x, dest_y, dest_z, my_x, my_y):
        """
        Decide se usa rota Global ou Local e move o personagem.
        """
        dist_total = math.sqrt((dest_x - my_x)**2 + (dest_y - my_y)**2)

        # A. Decisão: Precisamos de rota Global?
        # Condições: Distância > 7 SQM ou estamos travados localmente (tentando dar a volta)
        need_global = False
        reason = ""

        if not self.current_global_path:
            if dist_total > 7:
                need_global = True
                reason = f"Destino Longe ({dist_total:.1f} sqm)"
            elif self.global_recalc_counter > 2:
                need_global = True
                reason = "Stuck Local (Tentando desvio)"
        
        if need_global:
            self.current_state = self.STATE_RECALCULATING
            self.state_message = "🔄 Recalculando rota global..."
            print(f"[Nav] 🌍 Calculando Rota Global... Motivo: {reason}")
            # Ao recalcular global, limpamos o cache local (só se estiver usando cache)
            if not REALTIME_PATHING_ENABLED:
                self.local_path_cache = []

            # ===== NOVO: Usar fallback inteligente =====
            path = self.global_map.get_path_with_fallback(
                (my_x, my_y, dest_z),
                (dest_x, dest_y, dest_z),
                max_offset=2  # Busca até 2 tiles de distância
            )

            if path:
                self.current_global_path = path
                self.global_recalc_counter = 0 # Sucesso, reseta contador
                self.last_lookahead_idx = -1
                print(f"[Nav] 🛤️ Rota Global Gerada: {len(path)} nós.")
            else:
                print(f"[Nav] ⚠️ GlobalMap não achou rota (nem com fallback). Tentando direto.")
        
        # B. Definir o Sub-Destino (Janela Deslizante)
        # O A* local não consegue ir até o destino final se for longe.
        # Precisamos dar a ele um alvo visível (~7 sqm).
        target_local_x, target_local_y = dest_x, dest_y

        if self.current_global_path:
            # Sincroniza: Onde estou na rota?
            closest_idx = -1
            min_dist_path = 9999
            
            # Otimização: Busca apenas nos primeiros 40 nós
            search_limit = min(len(self.current_global_path), 40)
            for i in range(search_limit):
                px, py, pz = self.current_global_path[i]
                d = math.sqrt((px - my_x)**2 + (py - my_y)**2)
                if d < min_dist_path:
                    min_dist_path = d
                    closest_idx = i
            
            if closest_idx != -1:
                # Poda o passado
                self.current_global_path = self.current_global_path[closest_idx:]
                # Lookahead: Pega o nó X passos à frente
                lookahead = min(7, len(self.current_global_path) - 1)

                if lookahead != self.last_lookahead_idx:
                    print(f"[Nav] 🚶 Seguindo Global: Nó {lookahead}/{len(self.current_global_path)}")
                    self.last_lookahead_idx = lookahead

                tx, ty, tz = self.current_global_path[lookahead]
                target_local_x, target_local_y = tx, ty
            else:
                # Perdemos a rota, limpa para recalcular
                print("[Nav] ⚠️ Perdido da rota global. Resetando.")
                self.current_global_path = []
        
        # ============================================================
        # 3. LÓGICA DE PATHING (CACHE vs REAL-TIME)
        # ============================================================
        # REALTIME_PATHING_ENABLED:
        #   True  = calcula próximo passo em tempo real (mais preciso)
        #   False = usa cache de caminho completo (mais fluido)

        # Calcula coordenadas relativas para o Walker
        rel_x = target_local_x - my_x
        rel_y = target_local_y - my_y

        # Limita distância do A* para sub-destinos incrementais
        MAX_LOCAL_ASTAR_DIST = 7
        dist_to_target = math.sqrt(rel_x**2 + rel_y**2)

        if dist_to_target > MAX_LOCAL_ASTAR_DIST and not self.current_global_path:
            norm_x = rel_x / dist_to_target
            norm_y = rel_y / dist_to_target
            rel_x = int(norm_x * MAX_LOCAL_ASTAR_DIST)
            rel_y = int(norm_y * MAX_LOCAL_ASTAR_DIST)
            if DEBUG_PATHFINDING:
                print(f"[Nav] 📍 Destino longe ({dist_to_target:.1f} sqm), sub-destino ({rel_x}, {rel_y})")

        if REALTIME_PATHING_ENABLED:
            # ========== MODO REAL-TIME ==========
            # Calcula o próximo passo baseado no estado ATUAL do mapa
            # Mais preciso, evita obstáculos fantasmas e diagonais erráticas

            step = self.walker.get_next_step(rel_x, rel_y)

            if step:
                dx, dy = step

                # OBSTACLE CLEARING: Tenta mover mesa/cadeira se estiver no caminho
                if OBSTACLE_CLEARING_ENABLED:
                    props = self.analyzer.get_tile_properties(dx, dy)
                    if DEBUG_OBSTACLE_CLEARING:
                        print(f"[ObstacleClear] REALTIME: Próximo passo ({dx},{dy}) - walkable={props['walkable']}, type={props.get('type')}")

                    # Verificar se tem MOVE item mesmo que "walkable" (bug fix)
                    obstacle_info = self.analyzer.get_obstacle_type(dx, dy)
                    if DEBUG_OBSTACLE_CLEARING:
                        print(f"[ObstacleClear] REALTIME: obstacle_info={obstacle_info}")

                    # Se tem obstáculo MOVE ou STACK, tenta limpar mesmo que tile seja "walkable"
                    if obstacle_info['type'] in ('MOVE', 'STACK') and obstacle_info['clearable']:
                        if DEBUG_OBSTACLE_CLEARING or DEBUG_STACK_CLEARING:
                            print(f"[ObstacleClear] REALTIME: Detectou {obstacle_info['type']} item, tentando limpar...")
                        cleared = self._attempt_clear_obstacle(dx, dy)
                        if cleared:
                            props = self.analyzer.get_tile_properties(dx, dy)
                            if DEBUG_OBSTACLE_CLEARING:
                                print(f"[ObstacleClear] REALTIME: Após limpeza, walkable={props['walkable']}")
                    elif not props['walkable']:
                        if DEBUG_OBSTACLE_CLEARING:
                            print(f"[ObstacleClear] REALTIME: Tile não walkable, tentando limpar...")
                        cleared = self._attempt_clear_obstacle(dx, dy)
                        if cleared:
                            props = self.analyzer.get_tile_properties(dx, dy)
                        if not props['walkable']:
                            # Obstáculo não removível, recalcula no próximo ciclo
                            if DEBUG_OBSTACLE_CLEARING:
                                print(f"[ObstacleClear] REALTIME: Não conseguiu limpar, recalculando...")
                            self.global_recalc_counter += 1
                            return

                with self._waypoints_lock:
                    wp_num = self._current_index + 1
                self.current_state = self.STATE_WALKING
                self.state_message = f"🚶 Andando até WP #{wp_num}"

                self._execute_smooth_step(dx, dy)

                if self.global_recalc_counter > 0:
                    print(f"[Nav] ✓ Movimento com sucesso. Resetando stuck.")
                    self.global_recalc_counter = 0
            else:
                # ===== NOVO: Tentar limpar obstáculo quando A* não encontra caminho =====
                # Quando A* não encontra step, pode ser que um MOVE/STACK bloqueie a única rota
                obstacle_cleared = False

                if OBSTACLE_CLEARING_ENABLED or STACK_CLEARING_ENABLED:
                    # Calcular direção geral ao destino
                    dir_x = 1 if rel_x > 0 else (-1 if rel_x < 0 else 0)
                    dir_y = 1 if rel_y > 0 else (-1 if rel_y < 0 else 0)

                    # Tiles adjacentes a verificar (prioriza direção do destino)
                    tiles_to_check = []
                    if dir_x != 0 or dir_y != 0:
                        tiles_to_check.append((dir_x, dir_y))  # Direção principal
                    if dir_x != 0:
                        tiles_to_check.append((dir_x, 0))  # Horizontal
                    if dir_y != 0:
                        tiles_to_check.append((0, dir_y))  # Vertical

                    for check_x, check_y in tiles_to_check:
                        if check_x == 0 and check_y == 0:
                            continue

                        obstacle_info = self.analyzer.get_obstacle_type(check_x, check_y)
                        if DEBUG_OBSTACLE_CLEARING or DEBUG_STACK_CLEARING:
                            print(f"[ObstacleClear] NO_STEP: Verificando ({check_x},{check_y}) = {obstacle_info}")

                        if obstacle_info['clearable'] and obstacle_info['type'] in ('MOVE', 'STACK'):
                            if DEBUG_OBSTACLE_CLEARING or DEBUG_STACK_CLEARING:
                                print(f"[ObstacleClear] NO_STEP: Encontrou {obstacle_info['type']} em ({check_x},{check_y}), tentando limpar...")

                            if self._attempt_clear_obstacle(check_x, check_y):
                                obstacle_cleared = True
                                if DEBUG_OBSTACLE_CLEARING or DEBUG_STACK_CLEARING:
                                    print(f"[ObstacleClear] NO_STEP: Limpeza bem sucedida!")
                                break

                if obstacle_cleared:
                    # Obstáculo removido, próximo ciclo deve encontrar caminho
                    return

                # Código original de stuck (mantido)
                self.global_recalc_counter += 1
                self.current_state = self.STATE_STUCK
                self.state_message = f"⚠️ Bloqueio local ({self.global_recalc_counter}/{GLOBAL_RECALC_LIMIT})"
                print(f"[Nav] ⚠️ Bloqueio Local! ({self.global_recalc_counter}/{GLOBAL_RECALC_LIMIT})")

                if self.global_recalc_counter >= GLOBAL_RECALC_LIMIT:
                    self._handle_hard_stuck(dest_x, dest_y, dest_z, my_x, my_y)

        else:
            # ========== MODO CACHE (CÓDIGO ORIGINAL) ==========
            # Usa full_path com cache para fluidez máxima
            # Pode dessincronizar em ambientes muito dinâmicos

            if self.local_path_cache:
                if self.local_path_index < len(self.local_path_cache):
                    dx, dy = self.local_path_cache[self.local_path_index]

                    # [CRÍTICO] Checagem de Segurança em Tempo Real
                    props = self.analyzer.get_tile_properties(dx, dy)
                    if DEBUG_OBSTACLE_CLEARING:
                        print(f"[ObstacleClear] CACHE: Próximo passo ({dx},{dy}) - walkable={props['walkable']}, type={props.get('type')}")

                    # Verificar se tem MOVE item mesmo que "walkable" (bug fix)
                    if OBSTACLE_CLEARING_ENABLED:
                        obstacle_info = self.analyzer.get_obstacle_type(dx, dy)
                        if DEBUG_OBSTACLE_CLEARING:
                            print(f"[ObstacleClear] CACHE: obstacle_info={obstacle_info}")

                        # Se tem obstáculo MOVE, tenta limpar mesmo que tile seja "walkable"
                        if obstacle_info['type'] == 'MOVE' and obstacle_info['clearable']:
                            if DEBUG_OBSTACLE_CLEARING:
                                print(f"[ObstacleClear] CACHE: Detectou MOVE item, tentando limpar...")
                            cleared = self._attempt_clear_obstacle(dx, dy)
                            if cleared:
                                props = self.analyzer.get_tile_properties(dx, dy)
                                if DEBUG_OBSTACLE_CLEARING:
                                    print(f"[ObstacleClear] CACHE: Após limpeza, walkable={props['walkable']}")

                    if props['walkable']:
                        with self._waypoints_lock:
                            wp_num = self._current_index + 1
                        self.current_state = self.STATE_WALKING
                        self.state_message = f"🚶 Andando até WP #{wp_num}"

                        self._execute_smooth_step(dx, dy)
                        self.local_path_index += 1
                        return
                    else:
                        # Obstáculo dinâmico detectado!
                        if DEBUG_OBSTACLE_CLEARING:
                            print(f"[ObstacleClear] CACHE: Tile não walkable, tentando limpar...")
                        if OBSTACLE_CLEARING_ENABLED:
                            cleared = self._attempt_clear_obstacle(dx, dy)
                            if cleared:
                                props = self.analyzer.get_tile_properties(dx, dy)
                                if props['walkable']:
                                    with self._waypoints_lock:
                                        wp_num = self._current_index + 1
                                    self.current_state = self.STATE_WALKING
                                    self.state_message = f"🚶 Andando até WP #{wp_num}"
                                    self._execute_smooth_step(dx, dy)
                                    self.local_path_index += 1
                                    return

                        # Invalida cache
                        if DEBUG_OBSTACLE_CLEARING:
                            print(f"[ObstacleClear] CACHE: Não conseguiu limpar, invalidando cache")
                        self.local_path_cache = []
                else:
                    # Cache esgotado
                    self.local_path_cache = []

            # Calcula nova rota completa
            full_path = self.walker.get_full_path(rel_x, rel_y)

            if full_path:
                self.local_path_cache = full_path
                self.local_path_index = 0

                dx, dy = self.local_path_cache[0]

                with self._waypoints_lock:
                    wp_num = self._current_index + 1
                self.current_state = self.STATE_WALKING
                self.state_message = f"🚶 Andando até WP #{wp_num}"

                self._execute_smooth_step(dx, dy)
                self.local_path_index += 1

                if self.global_recalc_counter > 0:
                    print(f"[Nav] ✓ Movimento local com sucesso. Resetando stuck.")
                    self.global_recalc_counter = 0
            else:
                self.global_recalc_counter += 1
                self.current_state = self.STATE_STUCK
                self.state_message = f"⚠️ Bloqueio local ({self.global_recalc_counter}/{GLOBAL_RECALC_LIMIT})"
                print(f"[Nav] ⚠️ Bloqueio Local! ({self.global_recalc_counter}/{GLOBAL_RECALC_LIMIT})")

                if self.global_recalc_counter >= GLOBAL_RECALC_LIMIT:
                    self._handle_hard_stuck(dest_x, dest_y, dest_z, my_x, my_y)

    def _execute_smooth_step(self, dx, dy):
        """
        Executa um passo com delay dinâmico baseado no ground speed do tile destino
        e variação humana natural (jitter + micro-pausas).
        """
        # 1. Envia o pacote de movimento
        self._move_step(dx, dy)

        # 2. Atualiza cache de velocidade (a cada 2s)
        if time.time() - self.last_speed_check > 2.0:
            self.cached_speed = get_player_speed(self.pm, self.base_addr)
            if self.cached_speed <= 0:
                self.cached_speed = 220  # Fallback
            self.last_speed_check = time.time()

        player_speed = self.cached_speed

        # 3. NOVO: Obtém o ground speed do tile de destino
        dest_tile = self.memory_map.get_tile_visible(dx, dy)

        if dest_tile and dest_tile.items:
            # O ground é sempre o primeiro item da pilha (items[0])
            ground_id = dest_tile.items[0]
        else:
            ground_id = None  # Fallback para 150 (grass)

        ground_speed = get_ground_speed(ground_id)

        # 4. Calcula effective speed (diagonal = 3x mais lento no Tibia 7.7)
        is_diagonal = (dx != 0 and dy != 0)
        effective_speed = ground_speed * 3 if is_diagonal else ground_speed

        # 5. Fórmula de Tempo Base (ms) = (1000 * effective_speed) / player_speed
        base_ms = (1000.0 * effective_speed) / player_speed

        # 6. NOVO: Adiciona jitter gaussiano (±4% de variação)
        # Simula variação natural de timing humano
        jitter_std = base_ms * 0.04  # Desvio padrão = 4% do base
        jitter = random.gauss(0, jitter_std)

        # 7. NOVO: Adiciona micro-pausa aleatória (2% de chance)
        # Simula pequenas hesitações humanas (30-100ms)
        if random.random() < 0.02:
            jitter += random.uniform(30, 100)

        # 8. Calcula delay final com jitter
        total_ms = base_ms + jitter

        # 9. Buffer de Pre-Move (Antecipação)
        # Enviamos o próximo comando X ms antes de terminar o passo atual
        pre_move_buffer = 90  # ms (90ms é seguro para ping médio)

        wait_time = (total_ms / 1000.0) - (pre_move_buffer / 1000.0)

        # 10. Trava de segurança: Delay mínimo de 50ms para evitar flood
        wait_time = max(0.05, wait_time)

        # Debug opcional (pode ser ativado com DEBUG_PATHFINDING)
        if DEBUG_PATHFINDING:
            print(f"[Movement] Ground ID={ground_id}, Speed={ground_speed}, "
                  f"Diagonal={is_diagonal}, Base={base_ms:.1f}ms, "
                  f"Jitter={jitter:.1f}ms, Total={total_ms:.1f}ms, Wait={wait_time:.3f}s")

        #print(f"[Cavebot] 🚶 Andando ({dx},{dy}) - Próximo em {wait_time:.2f}s")

        # 11. Define o tempo em que o bot vai "acordar" para o próximo passo
        self.last_action_time = time.time() + wait_time

    def _handle_hard_stuck(self, dest_x, dest_y, dest_z, my_x, my_y):
        """Marca bloqueio no mapa global e força nova rota (Desvio)."""
        print("[Nav] HARD STUCK! Adicionando bloqueio temporário e recalculando...")
        
        block_node = None
        
        # Tenta bloquear o próximo nó da rota global
        if self.current_global_path:
            for node in self.current_global_path:
                nx, ny, nz = node
                # Se for adjacente, é o provável culpado
                if max(abs(nx - my_x), abs(ny - my_y)) == 1:
                    block_node = node
                    break
        
        # Fallback: Bloqueia tile na direção do destino
        if not block_node:
            dx = 1 if dest_x > my_x else -1 if dest_x < my_x else 0
            dy = 1 if dest_y > my_y else -1 if dest_y < my_y else 0
            if dx != 0 or dy != 0:
                block_node = (my_x + dx, my_y + dy, dest_z)

        if block_node:
            bx, by, bz = block_node
            # Adiciona bloqueio de 20s no Global Map
            print(f"[Nav] 🧱 Adicionando barreira virtual em ({bx}, {by}) por 20s.")
            self.global_map.add_temp_block(bx, by, bz, duration=20)
        else:
            print("[Nav] ❓ Não foi possível identificar o tile de bloqueio.")
        
        # Limpa rota para forçar recálculo imediato na próxima volta
        print("[Nav] 🔄 Forçando recálculo de rota global...")
        self.current_global_path = []
        self.global_recalc_counter = 0

    def _advance_waypoint(self):
        """
        Avança para o próximo waypoint em lógica SEMPRE FORWARD e CIRCULAR.

        Comportamento:
        - Sempre vai para frente: 0 → 1 → 2 → ... → n-1 → 0 → 1 → ...
        - Loop infinito sem inversão de direção
        - Simples e previsível

        Garante navegação circular e linear sem mudança de direção.
        """
        if not self._waypoints:
            return

        n_waypoints = len(self._waypoints)

        # Avança sempre para o próximo (forward)
        self._current_index = (self._current_index + 1) % n_waypoints

        if self._current_index == 0:
            # Completou um loop e voltou ao início
            print(f"[Cavebot] 🔁 Loop completo! Reiniciando do WP #0")

    def _move_step(self, dx, dy):
        """Envia o pacote de andar."""
        opcode = MOVE_OPCODES.get((dx, dy))
        if opcode:
            self.packet.walk(opcode)
        else:
            print(f"[Cavebot] Direção inválida: {dx}, {dy}")

    def _handle_special_tile(self, rel_x, rel_y, ftype, special_id, px, py, pz):
        """Executa a ação correta para tiles especiais (escadas, buracos, rope)."""
        # Aguarda personagem parar antes de interagir com tile especial
        if not wait_until_stopped(self.pm, self.base_addr, packet=self.packet, timeout=1.5):
            if DEBUG_PATHFINDING:
                print(f"[Cavebot] ⏳ Aguardando parada para usar {ftype}...")
            return  # Tenta novamente no próximo ciclo

        abs_x = px + rel_x
        abs_y = py + rel_y
        target_pos = get_ground_pos(abs_x, abs_y, pz)
        special_id = special_id or 0

        if ftype in ['UP_WALK', 'DOWN']:
            # Essas escadas/buracos sobem/descem IMEDIATAMENTE ao pisar nelas.
            # O personagem é TELETRANSPORTADO para o novo andar assim que o servidor processa.
            if rel_x != 0 or rel_y != 0:
                self._move_step(rel_x, rel_y)
                # CRÍTICO: Aguarda o servidor processar a mudança de andar
                # Sem isso, o próximo ciclo pode enviar comandos baseados na posição antiga
                time.sleep(1)  # Tempo para o servidor processar teleport
            return

        if ftype == 'DOWN_USE':
            # Sewer grate e similares: requer USE para descer
            chebyshev = max(abs(rel_x), abs(rel_y))

            if chebyshev == 0:
                # Já estamos em cima do sewer grate, apenas usa
                print(f"[Cavebot] Em cima do sewer grate, executando USE. Chebyshev = {chebyshev}")
                self._use_down_tile(target_pos, special_id, 0, 0)
            elif chebyshev == 1:
                # Adjacente (inclui cardinal e diagonal): usa à distância
                print(f"[Cavebot] Adjacente ao sewer grate (cardinal ou diagonal), executando USE à distância. Chebyshev = {chebyshev}")
                self._use_down_tile(target_pos, special_id, rel_x, rel_y)
            else:
                # Mais longe: alinhar para adjacência e tentar novamente
                print(f"[Cavebot] Longe do sewer grate (Chebyshev = {chebyshev}), alinhando para adjacência.")
                if not self._ensure_cardinal_adjacent(rel_x, rel_y, label="sewer grate"):
                    return
            return

        if ftype == 'UP_USE':
            chebyshev = max(abs(rel_x), abs(rel_y))
            if chebyshev == 0:
                # Já estamos em cima da ladder, apenas usa.
                print(f"[Cavebot] Em cima da ladder, executando USE. Chebyshev = {chebyshev}")
                self._use_ladder_tile(target_pos, special_id, 0, 0)
            elif chebyshev == 1:
                # Adjacente (inclui cardinal e diagonal): usa à distância.
                print(f"[Cavebot] Adjacente à ladder (cardinal ou diagonal), executando USE à distância. Chebyshev = {chebyshev}")
                self._use_ladder_tile(target_pos, special_id, rel_x, rel_y)
            else:
                # Mais longe: alinhar para adjacência e tentar novamente.
                print(f"[Cavebot] Longe da ladder (Chebyshev = {chebyshev}), alinhando para adjacência.")
                if not self._ensure_cardinal_adjacent(rel_x, rel_y, label="ladder"):
                    return
            return

        if ftype == 'ROPE':
            # Rope EXIGE adjacência - o personagem NÃO pode estar em cima do rope spot
            chebyshev = max(abs(rel_x), abs(rel_y))

            if chebyshev == 0:
                # Estamos EM CIMA do rope spot - precisamos sair para uma posição adjacente
                print("[Cavebot] ⚠️ Em cima do rope spot! Movendo para posição adjacente...")

                # Procura um tile adjacente walkable para se mover
                adjacent_options = [
                    (0, -1), (0, 1), (-1, 0), (1, 0),  # Cardinais primeiro
                    (-1, -1), (1, -1), (-1, 1), (1, 1)  # Diagonais depois
                ]

                moved = False
                for adj_dx, adj_dy in adjacent_options:
                    props = self.analyzer.get_tile_properties(adj_dx, adj_dy)
                    if props['walkable']:
                        self._move_step(adj_dx, adj_dy)
                        print(f"[Cavebot] Movendo para ({adj_dx}, {adj_dy}) para usar rope.")
                        moved = True
                        break

                if not moved:
                    print("[Cavebot] ⚠️ Nenhum tile adjacente livre para sair do rope spot!")
                return  # Volta no próximo ciclo para tentar usar a rope

            if chebyshev > 1:
                # Está longe - precisa se aproximar
                if not self._ensure_cardinal_adjacent(rel_x, rel_y):
                    return

            # chebyshev == 1: Está adjacente, pode usar a rope
            rope_source = self._get_rope_source_position()
            if not rope_source:
                print("[Cavebot] Corda (3003) não encontrada em containers ou mãos.")
                return

            if not self._clear_rope_spot(rel_x, rel_y, px, py, pz, special_id or 386):
                return

            self.packet.use_with(rope_source, ROPE_ITEM_ID, 0, target_pos, special_id or 386, 0,
                                 rel_x=rel_x, rel_y=rel_y)
            print("[Cavebot] Ação: USAR CORDA para subir de andar.")
            # CRÍTICO: Aguarda o servidor processar a mudança de andar
            # Rope teletransporta o jogador para o andar de cima
            time.sleep(1)
            return

        if ftype == 'SHOVEL':
            # Shovel precisa de pá no inventário/equipamento
            if not self._ensure_cardinal_adjacent(rel_x, rel_y, label="shovel"):
                return

            shovel_source = self._get_shovel_source_position()
            if not shovel_source:
                print("[Cavebot] Pá (3457) não encontrada em containers ou mãos.")
                return

            # Obtém o ID do stone pile no tile
            shovel_tile = self.memory_map.get_tile_visible(rel_x, rel_y)
            if not shovel_tile or shovel_tile.count == 0:
                print("[Cavebot] Tile do shovel spot não encontrado na memória.")
                return

            top_id = shovel_tile.get_top_item()

            # Valida se o item é um stone pile válido (593, 606, 608)
            from database.tiles_config import FLOOR_CHANGE
            valid_shovel_ids = FLOOR_CHANGE.get('SHOVEL', set())

            if top_id not in valid_shovel_ids:
                print(f"[Cavebot] Item {top_id} no shovel spot não é um stone pile válido. Esperado: {valid_shovel_ids}")
                return

            # Usa a pá no stone pile para criar o buraco (593 → 594)
            self.packet.use_with(shovel_source, SHOVEL_ITEM_ID, 0, target_pos, top_id, 0,
                                 rel_x=rel_x, rel_y=rel_y)
            print(f"[Cavebot] Ação: USAR PÁ para abrir buraco. (Stone pile ID: {top_id})")

            # Aguarda o servidor processar (stone pile se torna hole)
            time.sleep(1)
            return

    def _use_ladder_tile(self, target_pos, ladder_id, rel_x=0, rel_y=0):
        """Executa o packet de USE na ladder quando estivermos sobre ela."""
        if ladder_id == 0:
            print("[Cavebot] Ladder sem ID especial, abortando USE.")
            return
        stack_pos = 0
        ladder_tile = self.memory_map.get_tile_visible(rel_x, rel_y)
        if ladder_tile and ladder_tile.items:
            # Procura o stackpos real do ID da ladder (última ocorrência = topo).
            for idx, item_id in enumerate(ladder_tile.items):
                if item_id == ladder_id:
                    stack_pos = idx
        else:
            print("[Cavebot] Tile da ladder não encontrado na memória, usando stack_pos=0.")

        self.packet.use_item(target_pos, ladder_id, stack_pos=stack_pos)
        print(f"[Cavebot] Ação: USAR LADDER (ID: {ladder_id}, target_pos: {target_pos}, rel_x {rel_x}, rel_y {rel_y}, stack_pos: {stack_pos})")
        # CRÍTICO: Aguarda o servidor processar a mudança de andar
        # Ladders teletransportam o jogador assim que o servidor processa
        time.sleep(0.6)

    def _use_down_tile(self, target_pos, tile_id, rel_x=0, rel_y=0):
        """Executa o packet de USE em tiles que descem (sewer grate, etc.)."""
        if tile_id == 0:
            print("[Cavebot] Sewer grate sem ID especial, abortando USE.")
            return

        stack_pos = 0
        down_tile = self.memory_map.get_tile_visible(rel_x, rel_y)

        if down_tile and down_tile.items:
            # Procura o stackpos real do ID do sewer grate (última ocorrência = topo)
            for idx, item_id in enumerate(down_tile.items):
                if item_id == tile_id:
                    stack_pos = idx
        else:
            print("[Cavebot] Tile do sewer grate não encontrado na memória, usando stack_pos=0.")

        self.packet.use_item(target_pos, tile_id, stack_pos=stack_pos)
        print(f"[Cavebot] Ação: USAR SEWER GRATE (ID: {tile_id}, target_pos: {target_pos}, rel_x {rel_x}, rel_y {rel_y}, stack_pos: {stack_pos})")

        # CRÍTICO: Aguarda o servidor processar a mudança de andar
        # Sewer grates teletransportam o jogador assim que o servidor processa
        time.sleep(0.6)

    def _get_adjacent_use_tile(self, ladder_rel_x, ladder_rel_y):
        """
        Escolhe um tile cardinal adjacente à ladder para usar à distância.
        Prioriza o mais próximo do player e walkable; fallback é o próprio tile da ladder.
        """
        options = [
            (ladder_rel_x + 1, ladder_rel_y),
            (ladder_rel_x - 1, ladder_rel_y),
            (ladder_rel_x, ladder_rel_y + 1),
            (ladder_rel_x, ladder_rel_y - 1),
        ]

        best = (ladder_rel_x, ladder_rel_y)
        best_dist = 999
        for ox, oy in options:
            props = self.analyzer.get_tile_properties(ox, oy)
            if not props['walkable']:
                continue
            dist = abs(ox) + abs(oy)
            if dist < best_dist:
                best_dist = dist
                best = (ox, oy)
        return best

    def _ensure_cardinal_adjacent(self, rel_x, rel_y, label="rope"):
        """
        Verifica se está adjacente (Chebyshev = 1, inclui diagonal e cardinal).
        NOTA: O nome é enganoso, mas funciona para rope/shovel que aceitam AMBOS cardinal e diagonal.
        UP_USE também usa essa função e aceita ambos.
        Se estiver mais longe, tenta se aproximar movendo em um eixo de cada vez.
        Se estiver no mesmo tile (Chebyshev = 0), retorna False (inválido).
        """
        chebyshev = max(abs(rel_x), abs(rel_y))

        if chebyshev == 1:
            # Já está adjacente (cardinal ou diagonal)
            return True

        if chebyshev == 0:
            print(f"[Cavebot] {label.capitalize()} inválido (rel=0,0 - mesmo tile do player).")
            return False

        # Está longe (Chebyshev > 1): tenta se aproximar
        # Prioridade: move primeiro no eixo com maior distância
        if abs(rel_x) > abs(rel_y):
            # X é maior: move em X para chegar perto
            print(f"[Cavebot] {label.capitalize()} longe (Chebyshev={chebyshev}), movendo no eixo X...")
            self._move_step(1 if rel_x > 0 else -1, 0)
        else:
            # Y é maior ou igual: move em Y
            print(f"[Cavebot] {label.capitalize()} longe (Chebyshev={chebyshev}), movendo no eixo Y...")
            self._move_step(0, 1 if rel_y > 0 else -1)

        return False

    def _get_rope_source_position(self):
        """Procura a corda nos equipamentos ou containers e retorna a posição do packet."""
        equip = find_item_in_equipment(self.pm, self.base_addr, ROPE_ITEM_ID)
        if equip:
            slot_map = {'right': 5, 'left': 6, 'ammo': 10}
            slot_enum = slot_map.get(equip['slot'])
            if slot_enum:
                return get_inventory_pos(slot_enum)

        cont_data = find_item_in_containers(self.pm, self.base_addr, ROPE_ITEM_ID)
        if cont_data:
            return get_container_pos(cont_data['container_index'], cont_data['slot_index'])
        return None

    def _get_shovel_source_position(self):
        """Procura a pá nos equipamentos ou containers e retorna a posição do packet."""
        equip = find_item_in_equipment(self.pm, self.base_addr, SHOVEL_ITEM_ID)
        if equip:
            slot_map = {'right': 5, 'left': 6, 'ammo': 10}
            slot_enum = slot_map.get(equip['slot'])
            if slot_enum:
                return get_inventory_pos(slot_enum)

        cont_data = find_item_in_containers(self.pm, self.base_addr, SHOVEL_ITEM_ID)
        if cont_data:
            return get_container_pos(cont_data['container_index'], cont_data['slot_index'])
        return None

    def _clear_rope_spot(self, rel_x, rel_y, px, py, pz, rope_tile_id):
        """
        Rope spot precisa estar livre.
        Caso o topo tenha item diferente do rope spot, tentamos arrastar para nosso tile.

        Itens na lista ROPE_SPOT_IGNORE_IDS (poças de sangue, etc.) não são movidos,
        pois não bloqueiam o uso da rope.
        """
        tile = self.memory_map.get_tile_visible(rel_x, rel_y)
        if not tile or tile.count == 0:
            print("[Cavebot] Tile do rope spot não encontrado na memória.")
            return False

        top_id = tile.get_top_item()
        rope_id = rope_tile_id or 386

        if top_id in (0, rope_id):
            return True

        if top_id == 99:
            print("[Cavebot] Rope spot bloqueado por criatura/jogador. Não moveremos por enquanto.")
            return False

        # NOVO: Se o item está na lista de exceção (poças, etc.), considera como "limpo"
        if top_id in ROPE_SPOT_IGNORE_IDS:
            print(f"[Cavebot] Item {top_id} no rope spot (permitido). Rope pode ser usada.")
            return True

        # Calcula stack_pos do item no topo
        # items[-1] é o topo, e seu índice na pilha é len(items) - 1
        stack_pos = len(tile.items) - 1

        from_pos = get_ground_pos(px + rel_x, py + rel_y, pz)
        drop_pos = get_ground_pos(px, py, pz)
        self.packet.move_item(from_pos, drop_pos, top_id, 1, stack_pos=stack_pos)
        print(f"[Cavebot] Movendo item {top_id} (stack_pos={stack_pos}) para liberar rope spot.")
        return False

    # ==================================================================
    # OBSTACLE CLEARING - Move mesas/cadeiras do caminho
    # ==================================================================

    def _attempt_clear_obstacle(self, rel_x, rel_y):
        """
        Tenta remover um obstáculo MOVE (mesa, cadeira) ou STACK (parcel) do caminho.
        Protegido pelos toggles OBSTACLE_CLEARING_ENABLED e STACK_CLEARING_ENABLED.

        Args:
            rel_x, rel_y: Posição relativa ao player

        Returns:
            bool: True se conseguiu limpar, False caso contrário
        """
        if DEBUG_OBSTACLE_CLEARING or DEBUG_STACK_CLEARING:
            print(f"[ObstacleClear] _attempt_clear_obstacle chamado para rel({rel_x},{rel_y})")

        obstacle = self.analyzer.get_obstacle_type(rel_x, rel_y)
        if DEBUG_OBSTACLE_CLEARING or DEBUG_STACK_CLEARING:
            print(f"[ObstacleClear] get_obstacle_type retornou: {obstacle}")

        if not obstacle['clearable']:
            if DEBUG_OBSTACLE_CLEARING or DEBUG_STACK_CLEARING:
                print(f"[ObstacleClear] Obstáculo não é clearable, abortando")
            return False

        px, py, pz = get_player_pos(self.pm, self.base_addr)
        target_x, target_y = px + rel_x, py + rel_y

        if obstacle['type'] == 'MOVE':
            if not OBSTACLE_CLEARING_ENABLED:
                if DEBUG_OBSTACLE_CLEARING:
                    print(f"[ObstacleClear] OBSTACLE_CLEARING_ENABLED=False, abortando")
                return False
            if DEBUG_OBSTACLE_CLEARING:
                print(f"[ObstacleClear] Tipo MOVE detectado, chamando _push_move_item")
            return self._push_move_item(target_x, target_y, pz, rel_x, rel_y, obstacle)

        if obstacle['type'] == 'STACK':
            if not STACK_CLEARING_ENABLED:
                if DEBUG_STACK_CLEARING:
                    print(f"[StackClear] STACK_CLEARING_ENABLED=False, abortando")
                return False
            if DEBUG_STACK_CLEARING:
                print(f"[StackClear] Tipo STACK detectado, chamando _push_stack_item")
            return self._push_stack_item(target_x, target_y, pz, rel_x, rel_y, obstacle)

        if DEBUG_OBSTACLE_CLEARING or DEBUG_STACK_CLEARING:
            print(f"[ObstacleClear] Tipo {obstacle['type']} não suportado")
        return False

    def _push_move_item(self, target_x, target_y, pz, rel_x, rel_y, obstacle):
        """
        Move um item MOVE (mesa/cadeira) para liberar o caminho.

        Ordem de prioridade:
        1. Arrastar para tile adjacente ao PLAYER (cardinais)
        2. Arrastar para tile adjacente ao PLAYER (diagonais)
        3. Empurrar para tile adjacente à MESA (fallback)
        """
        px, py, _ = get_player_pos(self.pm, self.base_addr)

        if DEBUG_OBSTACLE_CLEARING:
            print(f"[ObstacleClear] Mesa em rel({rel_x},{rel_y}) abs({target_x},{target_y})")
            print(f"[ObstacleClear] Player em ({px},{py},{pz})")
            print(f"[ObstacleClear] Item ID={obstacle['item_id']}, stack_pos={obstacle['stack_pos']}")

        # ============================================================
        # PRIORIDADE 1: Tiles adjacentes ao PLAYER (cardinais)
        # ============================================================
        player_cardinals = [(-1, 0), (1, 0), (0, -1), (0, 1)]

        result = self._try_move_to_tiles(
            player_cardinals, rel_x, rel_y,
            target_x, target_y, pz, px, py, obstacle,
            ref_type="player"
        )
        if result:
            return True

        # ============================================================
        # PRIORIDADE 2: Tiles adjacentes ao PLAYER (diagonais)
        # ============================================================
        player_diagonals = [(-1, -1), (-1, 1), (1, -1), (1, 1)]

        result = self._try_move_to_tiles(
            player_diagonals, rel_x, rel_y,
            target_x, target_y, pz, px, py, obstacle,
            ref_type="player"
        )
        if result:
            return True

        # ============================================================
        # PRIORIDADE 3 (FALLBACK): Tiles adjacentes à MESA
        # ============================================================
        if DEBUG_OBSTACLE_CLEARING:
            print(f"[ObstacleClear] Fallback: tentando empurrar para tiles adjacentes à mesa")

        # Todas as 8 direções relativas à mesa
        mesa_adjacent = [
            (-1, 0), (1, 0), (0, -1), (0, 1),      # cardinais
            (-1, -1), (-1, 1), (1, -1), (1, 1)     # diagonais
        ]

        result = self._try_move_to_tiles(
            mesa_adjacent, rel_x, rel_y,
            target_x, target_y, pz, px, py, obstacle,
            ref_type="mesa"
        )
        if result:
            return True

        if DEBUG_OBSTACLE_CLEARING:
            print(f"[ObstacleClear] Nenhum tile livre encontrado em nenhuma prioridade!")
        return False

    def _try_move_to_tiles(self, directions, rel_x, rel_y, target_x, target_y, pz, px, py, obstacle, ref_type="player"):
        """
        Tenta mover a mesa para um dos tiles nas direções especificadas.

        Args:
            directions: Lista de (dx, dy) para tentar
            ref_type: "player" = direções relativas ao player
                      "mesa" = direções relativas à mesa
        """
        from database.tiles_config import MOVE_IDS, BLOCKING_IDS

        for dx, dy in directions:
            # Calcular posição do tile destino
            if ref_type == "player":
                # Direção relativa ao player
                check_rel_x, check_rel_y = dx, dy
                dest_x = px + dx
                dest_y = py + dy
            else:
                # Direção relativa à mesa
                check_rel_x = rel_x + dx
                check_rel_y = rel_y + dy
                dest_x = target_x + dx
                dest_y = target_y + dy

            # Pular o tile onde a mesa está
            if check_rel_x == rel_x and check_rel_y == rel_y:
                continue

            # Pular o tile onde o player está
            if check_rel_x == 0 and check_rel_y == 0:
                continue

            # Verificar se tile está livre
            tile = self.memory_map.get_tile_visible(check_rel_x, check_rel_y)

            if not tile or not tile.items:
                if DEBUG_OBSTACLE_CLEARING:
                    print(f"[ObstacleClear] ({check_rel_x},{check_rel_y}) - tile vazio/inexistente")
                continue

            # Verificar se tem item bloqueador
            has_blocking = False
            for item_id in tile.items:
                if item_id in MOVE_IDS or item_id in BLOCKING_IDS:
                    if DEBUG_OBSTACLE_CLEARING:
                        print(f"[ObstacleClear] ({check_rel_x},{check_rel_y}) - bloqueador {item_id}")
                    has_blocking = True
                    break

            if has_blocking:
                continue

            # Verificar walkability
            dest_props = self.analyzer.get_tile_properties(check_rel_x, check_rel_y)
            if not dest_props['walkable']:
                if DEBUG_OBSTACLE_CLEARING:
                    print(f"[ObstacleClear] ({check_rel_x},{check_rel_y}) - não walkable")
                continue

            # Tile válido! Executar movimento
            if DEBUG_OBSTACLE_CLEARING:
                print(f"[ObstacleClear] Movendo para ({check_rel_x},{check_rel_y}) abs({dest_x},{dest_y})")

            from_pos = get_ground_pos(target_x, target_y, pz)
            to_pos = get_ground_pos(dest_x, dest_y, pz)

            self.packet.move_item(
                from_pos, to_pos,
                obstacle['item_id'], 1,
                stack_pos=obstacle['stack_pos']
            )

            print(f"[Cavebot] 📦 Moveu mesa {obstacle['item_id']} para ({dest_x},{dest_y})")
            gauss_wait(0.3, 20)
            return True

        return False

    def _push_stack_item(self, target_x, target_y, pz, rel_x, rel_y, obstacle):
        """
        Move um item STACK (parcel/box) para liberar o caminho.

        Diferença do MOVE: STACK items podem ser movidos para o pé do player (0,0)

        Ordem de prioridade:
        1. Mover para o pé do player (0, 0) - PRIORITÁRIO
        2. Arrastar para tile adjacente ao PLAYER (cardinais)
        3. Arrastar para tile adjacente ao PLAYER (diagonais)
        4. Empurrar para tile adjacente ao ITEM (fallback)
        """
        px, py, _ = get_player_pos(self.pm, self.base_addr)

        if DEBUG_STACK_CLEARING:
            print(f"[StackClear] Parcel em rel({rel_x},{rel_y}) abs({target_x},{target_y})")
            print(f"[StackClear] Player em ({px},{py},{pz})")
            print(f"[StackClear] Item ID={obstacle['item_id']}, stack_pos={obstacle['stack_pos']}")

        # ============================================================
        # PRIORIDADE 0: Mover para o pé do player (0, 0)
        # STACK items PODEM ser movidos para o tile do player!
        # ============================================================
        dest_x, dest_y = px, py

        if DEBUG_STACK_CLEARING:
            print(f"[StackClear] Tentando mover para pé do player ({dest_x},{dest_y})")

        from_pos = get_ground_pos(target_x, target_y, pz)
        to_pos = get_ground_pos(dest_x, dest_y, pz)

        self.packet.move_item(
            from_pos, to_pos,
            obstacle['item_id'], 1,
            stack_pos=obstacle['stack_pos']
        )

        print(f"[Cavebot] 📦 Moveu parcel {obstacle['item_id']} para pé do player ({dest_x},{dest_y})")
        gauss_wait(0.3, 20)
        return True

        # NOTA: Se no futuro a prioridade 0 falhar (ex: height excessivo no tile do player),
        # podemos adicionar fallback usando _try_move_to_tiles() com as prioridades 1-4.
        # Por agora, mover para (0,0) é sempre válido para parcels.

    def _check_stuck(self, px, py, pz, current_index):
        """
        Detecta se o player está travado.
        Usa is_player_moving como fonte primária de detecção.

        Lógica:
        - Se estamos em rota e o personagem NÃO está se movendo
        - E a posição não mudou = provavelmente stuck
        """
        current_pos = (px, py, pz)
        is_moving = is_player_moving(self.pm, self.base_addr)

        # Se está se movendo, não está stuck - reseta contador
        if is_moving:
            self.stuck_counter = 0
            self.last_known_pos = current_pos
            return

        # Personagem parado - verificar se deveria estar andando
        if self.last_known_pos == current_pos:
            self.stuck_counter += 1

            if DEBUG_PATHFINDING:
                print(f"[Cavebot] ⚠️ Parado há {self.stuck_counter} ciclos (is_moving=False)")

            if self.stuck_counter >= self.stuck_threshold:
                stuck_time = self.stuck_counter * self.walk_delay
                self.current_state = self.STATE_STUCK
                self.state_message = f"🧱 Stuck! Pulando WP #{current_index + 1}"
                print(f"[Cavebot] ⚠️ STUCK! {stuck_time:.1f}s parado ({px}, {py}, {pz})")

                # Estratégia de recuperação: Pula para próximo waypoint
                with self._waypoints_lock:
                    if len(self._waypoints) > 1:
                        print(f"[Cavebot] Pulando para próximo waypoint...")
                        self._advance_waypoint()
                        self.current_global_path = []

                self.stuck_counter = 0
        else:
            # Posição mudou (mesmo que is_moving=False agora) - não está stuck
            self.stuck_counter = 0
            self.last_known_pos = current_pos
