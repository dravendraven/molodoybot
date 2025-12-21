# modules/cavebot.py
import random
import time
import math
import threading


from config import *
from core.packet import *
from core.packet_mutex import PacketMutex
from core.map_core import get_player_pos
from core.map_analyzer import MapAnalyzer
from core.astar_walker import AStarWalker
from core.memory_map import MemoryMap
from core.inventory_core import find_item_in_containers, find_item_in_equipment # Necessário para achar a corda
from database.tiles_config import ROPE_ITEM_ID, SHOVEL_ITEM_ID
from core.bot_state import state
from core.global_map import GlobalMap
from core.player_core import get_player_speed


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

    def __init__(self, pm, base_addr):
        self.pm = pm
        self.base_addr = base_addr

        # Inicializa o MemoryMap e o Analisador
        self.memory_map = MemoryMap(pm, base_addr)
        self.analyzer = MapAnalyzer(self.memory_map)
        self.walker = AStarWalker(self.analyzer, debug=DEBUG_PATHFINDING)
        
        # [NAVEGAÇÃO HIBRIDA] Inicializa o "GPS" (Global)
        self.global_map = GlobalMap(MAPS_DIRECTORY, WALKABLE_COLORS)
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
            if DEBUG_PATHFINDING:
                reasons = []
                if state.is_in_combat:
                    reasons.append("COMBATE")
                if state.has_open_loot:
                    reasons.append("AUTO-LOOT")
                print(f"[Cavebot] ⏸️ Pausado: {', '.join(reasons)}")
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
            # Ao recalcular global, limpamos o cache local
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
        # 3. LÓGICA DE CACHE LOCAL (Prioridade Máxima)
        # ============================================================
        
        if self.local_path_cache:
            if self.local_path_index < len(self.local_path_cache):
                dx, dy = self.local_path_cache[self.local_path_index]
                
                # [CRÍTICO] Checagem de Segurança em Tempo Real
                # O cache diz para ir, mas verificamos AGORA se o tile continua livre.
                # Isso previne bater em Magic Walls ou Players que apareceram depois do cálculo.
                props = self.analyzer.get_tile_properties(dx, dy)
                
                if props['walkable']:
                    # Caminho livre! Executa passo fluido.
                    # Set walking state
                    with self._waypoints_lock:
                        wp_num = self._current_index + 1
                    self.current_state = self.STATE_WALKING
                    self.state_message = f"🚶 Andando até WP #{wp_num}"

                    self._execute_smooth_step(dx, dy)
                    self.local_path_index += 1
                    return
                else:
                    # Obstáculo dinâmico detectado! O cache "mentiu". Invalida e recalcula.
                    # print("[Nav] ⚠️ Obstáculo dinâmico (MW/Player) invalidou cache.")
                    self.local_path_cache = []
            else:
                # Cache esgotado
                self.local_path_cache = []


        # ============================================================
        # 4. CÁLCULO DE NOVA ROTA LOCAL (Se não houver cache)
        # ============================================================
        # C. Execução Local (A* Walker)
        # Calcula coordenadas relativas para o Walker
        rel_x = target_local_x - my_x
        rel_y = target_local_y - my_y

        # ===== NOVO: LIMITAR DISTÂNCIA DO A* =====
        # Se destino está muito longe e não temos rota global,
        # usa navegação por aproximação com sub-destinos incrementais
        MAX_LOCAL_ASTAR_DIST = 7
        dist_to_target = math.sqrt(rel_x**2 + rel_y**2)

        if dist_to_target > MAX_LOCAL_ASTAR_DIST and not self.current_global_path:
            # Normaliza direção
            norm_x = rel_x / dist_to_target
            norm_y = rel_y / dist_to_target

            # Sub-destino a 7 SQM na direção correta
            rel_x = int(norm_x * MAX_LOCAL_ASTAR_DIST)
            rel_y = int(norm_y * MAX_LOCAL_ASTAR_DIST)

            if DEBUG_PATHFINDING:
                print(f"[Nav] 📍 Destino longe ({dist_to_target:.1f} sqm), usando sub-destino ({rel_x}, {rel_y})")
        
        full_path = self.walker.get_full_path(rel_x, rel_y)

        if full_path:
            # Enche o cache!
            self.local_path_cache = full_path
            self.local_path_index = 0

            # Executa o primeiro passo imediatamente
            dx, dy = self.local_path_cache[0]

            # Set walking state
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
            # Falha Local
            self.global_recalc_counter += 1
            self.current_state = self.STATE_STUCK
            self.state_message = f"⚠️ Bloqueio local, tentando global... ({self.global_recalc_counter}/{GLOBAL_RECALC_LIMIT})"
            print(f"[Nav] ⚠️ Bloqueio Local! ({self.global_recalc_counter}/{GLOBAL_RECALC_LIMIT})")

            if self.global_recalc_counter >= GLOBAL_RECALC_LIMIT:
                self._handle_hard_stuck(dest_x, dest_y, dest_z, my_x, my_y)

        # # Pede o próximo passo
        # step = self.walker.get_next_step(rel_x, rel_y)
            
        # if step:
        #     # Caminho Livre!
        #     dx, dy = step
        #     self._move_step(dx, dy)
        #     # Sucesso no movimento local reduz a frustração global
        #     if self.global_recalc_counter > 0:
        #         print(f"[Nav] ✓ Movimento local com sucesso. Resetando stuck.")
        #         self.global_recalc_counter -= 1
        # else:
        #     # D. Tratamento de Bloqueio (Local Falhou)
        #     print(f"[Nav] Caminho Local Bloqueado.")
        #     self.global_recalc_counter += 1
        #     print(f"[Nav] ⚠️ Bloqueio Local! ({self.global_recalc_counter}/{GLOBAL_RECALC_LIMIT})")

        #     # Se falhar muitas vezes localmente, assume "Hard Stuck" (ex: player trapando)
        #     if self.global_recalc_counter >= GLOBAL_RECALC_LIMIT:
        #         self._handle_hard_stuck(dest_x, dest_y, dest_z, my_x, my_y)

    def _execute_smooth_step(self, dx, dy):
        """
        Executa um passo e calcula o delay exato para permitir Pre-Move.
        Isso garante que o próximo pacote seja enviado antes do char parar.
        """
        # 1. Envia o pacote de movimento
        self._move_step(dx, dy)
        
        # 2. Atualiza cache de velocidade (a cada 2s)
        if time.time() - self.last_speed_check > 2.0:
            self.cached_speed = get_player_speed(self.pm, self.base_addr)
            if self.cached_speed <= 0: self.cached_speed = 220
            self.last_speed_check = time.time()
            
        player_speed = self.cached_speed
        
        # 3. Define Custo do Terreno (Tibia 7.72)
        # Diagonal gasta muito mais tempo que reto em versões antigas
        # Ajuste: Use 3 para diagonal, 1 para reto. 
        is_diagonal = (dx != 0 and dy != 0)
        tile_cost = 4 if is_diagonal else 1
        
        # 4. Fórmula de Tempo (ms) = (1000 * cost) / speed
        duration_ms = (1000 * tile_cost) / player_speed
        
        # 5. Buffer de Pre-Move (Antecipação)
        # Enviamos o próximo comando X ms antes de terminar o passo atual.
        # 90ms é um valor seguro para ping médio. Se tiver lag, diminua para 50ms.
        pre_move_buffer = 0.090 
        
        wait_time = (duration_ms / 1000.0) - pre_move_buffer
        
        # Trava de segurança: Delay mínimo de 50ms para evitar flood se a conta der errada
        wait_time = max(0.05, wait_time)
        
        # Define o tempo em que o bot vai "acordar" para o próximo passo
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
            with PacketMutex("cavebot"):
                walk(self.pm, opcode)
        else:
            print(f"[Cavebot] Direção inválida: {dx}, {dy}")

    def _handle_special_tile(self, rel_x, rel_y, ftype, special_id, px, py, pz):
        """Executa a ação correta para tiles especiais (escadas, buracos, rope)."""
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
            # Rope precisa de adjacência cardeal, tile livre e corda no inventário.
            if not self._ensure_cardinal_adjacent(rel_x, rel_y):
                return
            
            rope_source = self._get_rope_source_position()
            if not rope_source:
                print("[Cavebot] Corda (3003) não encontrada em containers ou mãos.")
                return

            if not self._clear_rope_spot(rel_x, rel_y, px, py, pz, special_id or 386):
                return
            
            with PacketMutex("cavebot"):
                use_with(self.pm, rope_source, ROPE_ITEM_ID, 0, target_pos, special_id or 386, 0)
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
            with PacketMutex("cavebot"):
                use_with(self.pm, shovel_source, SHOVEL_ITEM_ID, 0, target_pos, top_id, 0)
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

        use_item(self.pm, target_pos, ladder_id, stack_pos=stack_pos)
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

        use_item(self.pm, target_pos, tile_id, stack_pos=stack_pos)
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
        move_item(self.pm, from_pos, drop_pos, top_id, 1, stack_pos=stack_pos)
        print(f"[Cavebot] Movendo item {top_id} (stack_pos={stack_pos}) para liberar rope spot.")
        return False

    def _check_stuck(self, px, py, pz, current_index):
        """
        Detecta se o player está travado no mesmo tile.
        Se sim, tenta recuperar pulando waypoint ou aumentando delay.
        """
        current_pos = (px, py, pz)

        if self.last_known_pos == current_pos:
            self.stuck_counter += 1

            if self.stuck_counter >= self.stuck_threshold:
                stuck_time = self.stuck_counter * self.walk_delay
                self.current_state = self.STATE_STUCK
                self.state_message = f"🧱 Stuck! Pulando WP #{current_index + 1}"
                print(f"[Cavebot] ⚠️ STUCK! {stuck_time:.1f}s parado no mesmo tile ({px}, {py}, {pz})")

                # Estratégia de recuperação: Pula para próximo waypoint
                with self._waypoints_lock:
                    if len(self._waypoints) > 1:
                        print(f"[Cavebot] Pulando para próximo waypoint...")
                        self._advance_waypoint()
                        self.current_global_path = [] # Reseta ao pular

                # Reseta contador
                self.stuck_counter = 0
                self.last_known_pos = current_pos
        else:
            # Player se moveu, reseta contador
            self.stuck_counter = 0
            self.last_known_pos = current_pos
