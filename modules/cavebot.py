# modules/cavebot.py
import os
import random
import time
import math
from datetime import datetime

def _ts():
    """Timestamp para logs: HH:MM:SS"""
    return datetime.now().strftime("%H:%M:%S")
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
from database.tiles_config import ROPE_ITEM_ID, SHOVEL_ITEM_ID, get_ground_speed, GROUND_SPEEDS
from core.bot_state import state
from core.global_map import GlobalMap
from core.player_core import get_player_speed, is_player_moving, wait_until_stopped
from core.advancement_tracker import AdvancementTracker
from core.battlelist import BattleListScanner
from core.models import Position
from core.spawn_parser import parse_spawns, SpawnArea
from core.spawn_selector import SpawnSelector
from core.floor_connector import FloorConnector


def _get_bundled_path(filename):
    """Retorna caminho para arquivo bundled (PyInstaller) ou do projeto."""
    import sys
    if getattr(sys, 'frozen', False):
        return os.path.join(sys._MEIPASS, filename)
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), filename)


COOLDOWN_AFTER_COMBAT_BASE = 1.0    # Média de 3 segundos
COOLDOWN_AFTER_COMBAT_VARIANCE = 30  # ±30% variação gaussiana
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

    def __init__(self, pm, base_addr, maps_directory=None, spear_picker_enabled_callback=None):
        self.pm = pm
        self.base_addr = base_addr

        # Callback para verificar se spear picker está habilitado
        self._spear_picker_enabled_callback = spear_picker_enabled_callback or (lambda: False)

        # Inicializa o PacketManager
        self.packet = PacketManager(pm, base_addr)

        # Inicializa o MemoryMap e o Analisador
        self.memory_map = MemoryMap(pm, base_addr)
        self.analyzer = MapAnalyzer(self.memory_map)
        self.walker = AStarWalker(self.analyzer, debug=DEBUG_PATHFINDING)

        # [NAVEGAÇÃO HIBRIDA] Inicializa o "GPS" (Global)
        # Usa maps_directory passado como parâmetro, ou fallback para config.py
        effective_maps_dir = maps_directory if maps_directory else MAPS_DIRECTORY
        # Floor transitions e archways são bundled no .exe
        transitions_path = _get_bundled_path("floor_transitions.json")
        archway_files = [_get_bundled_path(f"archway{i}.txt") for i in range(1, 5)]
        self.global_map = GlobalMap(effective_maps_dir, WALKABLE_COLORS,
                                    transitions_file=transitions_path,
                                    archway_files=archway_files)
        self.current_global_path = [] # Lista de nós [(x,y,z), ...] da rota atual
        self.last_lookahead_idx = -1

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
        self._hard_stuck_count = 0  # Contador de hard stucks consecutivos

        # --- CONFIGURAÇÃO DE FLUIDEZ (NOVO) ---
        self.walk_delay = 0.4 # Valor base, será sobrescrito dinamicamente
        self.next_walk_time = 0  # Timestamp mínimo para próximo passo (corrige bug de steps duplicados)
        self.local_path_cache = [] # Armazena a lista de passos [(dx,dy), ...]
        self.local_path_index = 0  # Qual passo estamos executando
        self.cached_speed = 250    # Cache de velocidade para não ler battle list todo frame
        self.last_speed_check = 0  # Timestamp da última leitura de speed
        self.last_floor_change_time = 0  # Timestamp do último floor change (subir/descer andar)
        self._last_floor_change_from_z = None  # Z de onde veio na última transição (yo-yo protection)
        self._multifloor_full_path = None  # Rota multifloor completa (quando same-Z requer desvio por outro andar)

        # --- ESTADO PARA MINIMAP (NOVO) ---
        self.current_state = self.STATE_IDLE
        self.state_message = ""  # Mensagem detalhada para exibição
        self._last_logged_pause = ""  # Dedup: evita spam de logs repetidos

        # --- HUMANIZAÇÃO: Detecção de Falta de Progresso ---
        self.advancement_tracker = AdvancementTracker(
            window_seconds=ADVANCEMENT_WINDOW_SECONDS,
            min_advancement_ratio=ADVANCEMENT_MIN_RATIO
        )
        self.no_progress_response_time = 0  # Timestamp da última resposta a bloqueio
        self.last_global_path_time = 0  # Timestamp da última geração de rota global
        self._was_paused = False  # Para detectar transição pausa → navegação

        # --- COOLDOWN PÓS-COMBATE DINÂMICO ---
        self._combat_cooldown_duration = 0.0  # Duração randomizada do cooldown atual

        # --- AUTO-EXPLORE ---
        self.auto_explore_enabled = False
        self._spawn_selector = None          # SpawnSelector instance
        self._current_spawn_target = None    # SpawnArea ativo
        self._cached_transition = None       # (spawn_id, FloorTransition) cache
        self._nav_fail_count = 0              # Contador de falhas de navegação
        self._explore_initialized = False
        self._explore_xml_path = None        # Caminho para world-spawn.xml
        self._explore_target_monsters = []   # Lista de monstros alvo (filtro)
        self._explore_battlelist = None      # BattleListScanner para detecção de players

        # --- PRE-COMPUTATION (pipelining de passos) ---
        self._precomputed_step = None        # (dx, dy) pré-calculado durante wait
        self._precomputed_pos = None         # (px, py, pz) quando foi calculado
        self._precompute_done = False        # True se já tentou precomputar neste ciclo de wait
        self._precompute_last_used_pos = None  # Pos quando último passo pré-calculado foi enviado (detecção de falha)

        # --- OSCILLATION DETECTION (detecção de vai-volta) ---
        self._step_history = []              # Lista de (dx, dy) dos últimos N passos
        self._step_history_max = 10          # Tamanho máximo do histórico
        self._oscillation_skip_count = 0     # Contador de tentativas de resolução
        self._cached_spawn_target_pos = None # Cache do último alvo (auto-explore)
        self._last_closest_idx = -1          # Último índice de sincronização na rota

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
                    print(f"[{_ts()}] [Cavebot] Aviso: Waypoint {i} não é dict, ignorando")
                    continue

                # Validação de campos obrigatórios
                if 'x' not in wp or 'y' not in wp or 'z' not in wp:
                    print(f"[{_ts()}] [Cavebot] Aviso: Waypoint {i} falta coordenadas (x, y, z), ignorando")
                    continue

                # Validação de tipos
                if not isinstance(wp['x'], (int, float)) or \
                   not isinstance(wp['y'], (int, float)) or \
                   not isinstance(wp['z'], (int, float)):
                    print(f"[{_ts()}] [Cavebot] Aviso: Waypoint {i} coordenadas inválidas, ignorando")
                    continue

                validated.append(wp)
            except Exception as e:
                print(f"[{_ts()}] [Cavebot] Erro ao validar waypoint {i}: {e}")
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

                    print(f"[{_ts()}] [Cavebot] 🎯 Inicialização inteligente: WP mais próximo é #{closest_idx} (Dist: {closest_dist:.1f} SQM)")
                    print(f"[{_ts()}] [Cavebot]    Navegação: #{closest_idx} → #{closest_idx + 1} → ... → #{len(validated) - 1} → #0 → #1 ... (FORWARD ciclico)")

                except Exception as e:
                    # Fallback para comportamento padrão se houver erro
                    print(f"[{_ts()}] [Cavebot] ⚠️ Erro ao calcular waypoint inicial: {e}")
                    self._current_index = 0
                    self._direction = 1
            else:
                self._current_index = 0
                self._direction = 1

        print(f"[{_ts()}] [Cavebot] Carregados {len(validated)} waypoints válidos de {len(waypoints_list)} totais")

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
                    player_id = state.get_player_id(self.pm, self.base_addr)
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
                    if self.current_global_path:
                        print(f"[{_ts()}] [DEBUG] Path limpo em: start() (tinha {len(self.current_global_path)} nós)")
                    self.current_global_path = []
                    self.local_path_cache = []
                    self.global_recalc_counter = 0
                    self.stuck_counter = 0
                    self.last_known_pos = None

                    if old_idx != closest_idx:
                        print(f"[{_ts()}] [Cavebot] 🎯 Reposicionado: WP #{old_idx} → #{closest_idx} (Pos: {px},{py},{pz} | Dist: {closest_dist:.1f} SQM)")
                    else:
                        print(f"[{_ts()}] [Cavebot] ✓ Mantendo WP #{closest_idx} (Pos: {px},{py},{pz} | Dist: {closest_dist:.1f} SQM)")

                except Exception as e:
                    print(f"[{_ts()}] [Cavebot] ⚠️ Erro ao sincronizar estado: {e}")

        print(f"[{_ts()}] [Cavebot] Iniciado.")

    def stop(self):
        self.enabled = False
        state.set_cavebot_state(False)  # Notifica que Cavebot está inativo
        print(f"[{_ts()}] [Cavebot] Parado.")

    def run_cycle(self):
        """Deve ser chamado no loop principal do bot."""
        # Thread-safe check
        with self._waypoints_lock:
            if not self.enabled:
                return
            if not self.auto_explore_enabled and not self._waypoints:
                return

            # Cópia local para evitar lock durante todo ciclo
            current_waypoints = self._waypoints
            current_index = self._current_index

        # Atualiza estado no bot_state para alarm stuck detection
        # O estado atual (do ciclo anterior) é publicado no início de cada ciclo
        state.set_cavebot_current_state(self.current_state)

        # NOVO: Pausa APENAS se GM detectado (não pausa para criaturas/players)
        if state.is_gm_detected:
            self.current_state = self.STATE_PAUSED
            self.state_message = "⏸️ Pausado (GM detectado)"
            # Reseta cooldown para evitar movimento imediato ao retomar
            self.last_action_time = time.time()
            self._precomputed_step = None
            self._precompute_done = False
            return

        # NOVO: Pausa enquanto runemaker está ativo
        if state.is_runemaking:
            self.current_state = self.STATE_PAUSED
            self.state_message = "⏸️ Pausado (Runemaker ativo)"
            self.last_action_time = time.time()
            if DEBUG_PATHFINDING and self.state_message != self._last_logged_pause:
                self._last_logged_pause = self.state_message
                print(f"[{_ts()}] [Cavebot] ⏸️ PAUSA: Runemaker ativo")
            return

        # NOVO: Pausa durante conversa de chat (AI respondendo)
        if state.is_chat_paused:
            self.current_state = self.STATE_PAUSED
            remaining = state.get_chat_pause_remaining()
            self.state_message = f"💬 Pausado (Chat - {remaining:.1f}s)"
            self.last_action_time = time.time()
            if DEBUG_PATHFINDING and self._last_logged_pause != "chat_paused":
                self._last_logged_pause = "chat_paused"
                print(f"[{_ts()}] [Cavebot] ⏸️ PAUSA: Chat ativo ({remaining:.1f}s restantes)")
            return

        # NOVO: Pausa para atividades de maior prioridade
        # Aguarda combate terminar E ciclo de loot finalizar completamente
        # is_processing_loot garante que spear_picker tenha tempo de detectar/pegar spears
        if state.is_in_combat or state.has_open_loot or state.is_processing_loot:
            self.last_action_time = time.time()
            self._was_paused = True  # Marcar que estávamos pausados
            self._precomputed_step = None
            self._precompute_done = False
            # Atualiza status para exibição na GUI
            reasons = []
            if state.is_in_combat:
                reasons.append("Combate")
            if state.has_open_loot:
                reasons.append("Loot")
            if state.is_processing_loot:
                reasons.append("Proc.Loot")
            self.current_state = self.STATE_PAUSED
            self.state_message = f"⏸️ Pausado ({', '.join(reasons)})"
            if DEBUG_PATHFINDING and self.state_message != self._last_logged_pause:
                self._last_logged_pause = self.state_message
                print(f"[{_ts()}] [Cavebot] {self.state_message}")
            return

        # NOVO: Cooldown dinâmico após combate/loot/spear pickup
        # Gera novo valor aleatório a cada transição (não fixo por sessão)
        elapsed_since_combat = time.time() - state.last_combat_time

        # Gera novo cooldown quando transição é detectada (elapsed < 0.5s = acabou de sair)
        if self._combat_cooldown_duration == 0.0 and elapsed_since_combat < 0.5:
            sigma = COOLDOWN_AFTER_COMBAT_BASE * (COOLDOWN_AFTER_COMBAT_VARIANCE / 100)
            self._combat_cooldown_duration = max(0.5, random.gauss(COOLDOWN_AFTER_COMBAT_BASE, sigma))
            if DEBUG_PATHFINDING:
                print(f"[{_ts()}] [Cavebot] Novo cooldown gerado: {self._combat_cooldown_duration:.1f}s")

        # Verifica se ainda está em cooldown
        if elapsed_since_combat < self._combat_cooldown_duration:
            remaining = self._combat_cooldown_duration - elapsed_since_combat
            self._was_paused = True  # Marcar que estávamos pausados
            self.current_state = self.STATE_COMBAT_COOLDOWN
            self.state_message = f"⏰ Cooldown pós-combate ({remaining:.1f}s)"
            if DEBUG_PATHFINDING and self._last_logged_pause != "combat_cooldown":
                self._last_logged_pause = "combat_cooldown"
                print(f"[{_ts()}] [Cavebot] ⏸️ Cooldown: {remaining:.1f}s")
            self.last_action_time = time.time()
            return

        # Cooldown expirou - resetar para próximo evento
        if self._combat_cooldown_duration > 0:
            self._combat_cooldown_duration = 0.0

        # NOVO: Pausa durante coleta de spears pós-loot (somente se feature habilitada)
        if state.is_spear_pickup_pending and self._spear_picker_enabled_callback():
            self._was_paused = True  # Marcar que estávamos pausados
            self.current_state = self.STATE_PAUSED
            self.state_message = "⏸️ Pausado (Spear pickup)"
            if DEBUG_PATHFINDING and self.state_message != self._last_logged_pause:
                self._last_logged_pause = self.state_message
                print(f"[{_ts()}] [Cavebot] ⏸️ PAUSA: Spear pickup em progresso")
            self.last_action_time = time.time()
            return

        # NOVO: Evita iniciar navegação se há alvos visíveis (dar tempo ao trainer)
        # Um humano veria a criatura na tela antes de começar a andar
        if state.has_visible_targets:
            # Expor contexto da rota para Combat Movement (se habilitado)
            if state.combat_movement_enabled:
                try:
                    px, py, pz = get_player_pos(self.pm, self.base_addr)
                    with self._waypoints_lock:
                        current_wp = self._waypoints[self._current_index] if self._waypoints else None
                        next_idx = (self._current_index + 1) % len(self._waypoints) if self._waypoints else 0
                        next_wp = self._waypoints[next_idx] if self._waypoints else None
                    state.set_route_context(current_wp, next_wp, (px, py, pz))
                except Exception as e:
                    if DEBUG_PATHFINDING:
                        print(f"[{_ts()}] [Cavebot] Erro ao expor route_context: {e}")

            self._was_paused = True
            self.current_state = self.STATE_PAUSED
            self.state_message = "⏸️ Pausado (alvos visíveis)"
            if DEBUG_PATHFINDING and self._last_logged_pause != "visible_targets":
                self._last_logged_pause = "visible_targets"
                print(f"[{_ts()}] [Cavebot] ⏸️ PAUSA: Alvos visíveis na tela (aguardando trainer)")
            self.last_action_time = time.time()
            return

        # NOVO: Pausa durante AFK humanization (pausas aleatórias)
        if state.is_afk_paused:
            self._was_paused = True
            self.current_state = self.STATE_PAUSED
            remaining = state.get_afk_pause_remaining()
            self.state_message = f"💤 Pausa AFK ({remaining:.0f}s)"
            if DEBUG_PATHFINDING and self._last_logged_pause != "afk_pause":
                self._last_logged_pause = "afk_pause"
                print(f"[{_ts()}] [Cavebot] 💤 PAUSA AFK: {remaining:.0f}s restantes")
            self.last_action_time = time.time()
            return

        # Controle de Cooldown - Verifica se já pode dar o próximo passo
        # Usa next_walk_time (timestamp futuro) ao invés de last_action_time - walk_delay
        now = time.time()
        if now < self.next_walk_time:
            # PRE-COMPUTATION: Enquanto espera, lê mapa e calcula próximo passo
            if not self._precompute_done:
                self._precompute_done = True
                self._try_precompute_next_step()
            #elif DEBUG_PATHFINDING:
                #print(f"[{_ts()}] [DEBUG] Blocked: now={now:.3f}, next_walk={self.next_walk_time:.3f}, diff={self.next_walk_time - now:.3f}s")
            return

        # NOVO: Cooldown após mudança de andar (floor change)
        # Aguarda 1 segundo após subir/descer para permitir combate no novo andar
        FLOOR_CHANGE_COOLDOWN = 1.0
        if time.time() - self.last_floor_change_time < FLOOR_CHANGE_COOLDOWN:
            remaining = FLOOR_CHANGE_COOLDOWN - (time.time() - self.last_floor_change_time)
            self.current_state = self.STATE_FLOOR_COOLDOWN
            self.state_message = "⏰ Cooldown pós-stairs"
            if DEBUG_PATHFINDING:
                print(f"[{_ts()}] [Cavebot] ⏸️ Cooldown pós-floor-change: {remaining:.1f}s")
            self.last_action_time = time.time()
            self._precomputed_step = None
            self._precompute_done = False
            return

        # PRE-COMPUTATION: Se temos passo pré-calculado, usa direto (pula map read + A*)
        if self._precomputed_step is not None:
            px, py, pz = get_player_pos(self.pm, self.base_addr)
            if (px, py, pz) == self._precomputed_pos:
                # Detecta falha: se último passo pré-calculado não moveu o bot, cai no fluxo normal
                if self._precompute_last_used_pos == (px, py, pz):
                    if DEBUG_PATHFINDING:
                        print(f"[{_ts()}] [Nav] ⚠️ Passo pré-calculado falhou (posição não mudou). Usando fluxo normal.")
                    self._precomputed_step = None
                    self._precompute_done = False
                    self._precompute_last_used_pos = None
                    # Fall through para fluxo normal com stuck detection
                else:
                    dx, dy = self._precomputed_step
                    self._precomputed_step = None
                    self._precompute_done = False
                    self._precompute_last_used_pos = (px, py, pz)
                    if DEBUG_PATHFINDING:
                        print(f"[{_ts()}] [Nav] ⚡ Usando passo pré-calculado: ({dx}, {dy})")
                    self._execute_smooth_step(dx, dy)
                    self.last_action_time = time.time()
                    return
            else:
                # Posição mudou (combat knockback, etc) - descarta e recalcula
                self._precomputed_step = None
                self._precomputed_pos = None
                self._precompute_last_used_pos = None

        self._precompute_done = False

        # 1. Atualizar Posição e Mapa
        px, py, pz = get_player_pos(self.pm, self.base_addr)
        player_id = state.get_player_id(self.pm, self.base_addr)
        success = self.memory_map.read_full_map(player_id)

        # RETRY LOGIC: Se calibração falhar, tenta novamente
        if not success or not self.memory_map.is_calibrated:
            print(f"[{_ts()}] [Cavebot] Calibração do mapa falhou, tentando novamente...")
            time.sleep(0.1)  # Aguarda 100ms para estabilizar
            player_id = state.get_player_id(self.pm, self.base_addr)
            success = self.memory_map.read_full_map(player_id)

            if not success or not self.memory_map.is_calibrated:
                print(f"[{_ts()}] [Cavebot] ⚠️ Calibração falhou novamente. Pulando ciclo.")
                self.last_action_time = time.time()
                return

        # === AUTO-EXPLORE MODE ===
        if self.auto_explore_enabled:
            self._run_auto_explore(px, py, pz)
            self.last_action_time = time.time()
            return

        # 2. Selecionar Waypoint Atual (thread-safe)
        wp = current_waypoints[current_index]

        # DEBUG: Estado do Cérebro do Cavebot
        if DEBUG_PATHFINDING:
            print(f"\n[🧠 CAVEBOT] Posição: ({px}, {py}, {pz}) | WP Atual: #{current_index}/{len(current_waypoints)-1} → ({wp['x']}, {wp['y']}, {wp['z']})")

        # 3. Checar se chegou (Distância < 1.5 SQM e mesmo Z)
        dist = math.sqrt((wp['x'] - px)**2 + (wp['y'] - py)**2)

        # HUMANIZAÇÃO: Registrar distância para tracking de avanço (fallback)
        # Nodes são registrados mais tarde quando temos a rota global
        if ADVANCEMENT_TRACKING_ENABLED:
            self.advancement_tracker.record_distance(dist)

        if dist <= 1.5 and wp['z'] == pz:
            self.current_state = self.STATE_WAYPOINT_REACHED
            self.state_message = f"✅ Waypoint #{current_index + 1} alcançado"
            print(f"[{_ts()}] [Cavebot] ✅ Chegou no WP {current_index}: ({wp['x']}, {wp['y']}, {wp['z']})")
            with self._waypoints_lock:
                self._advance_waypoint()
                if self.current_global_path:
                    print(f"[{_ts()}] [DEBUG] Path limpo em: waypoint_reached (tinha {len(self.current_global_path)} nós)")
                self.current_global_path = []
                self.last_lookahead_idx = -1
            # Limpa tracker ao mudar de waypoint
            self.advancement_tracker.reset()
            return

        # DETECÇÃO DE TRANSIÇÃO: Pausa → Navegação
        # Se chegamos aqui, NÃO estamos mais pausados (todos os returns de pausa já passaram)
        # Se _was_paused é True, acabamos de sair de uma pausa - resetar tracker
        if self._was_paused:
            self.advancement_tracker.reset()
            self.last_global_path_time = time.time()
            self._was_paused = False
            self._last_logged_pause = ""
            if DEBUG_PATHFINDING:
                print(f"[{_ts()}] [Cavebot] ✓ Saiu de pausa, resetando tracker de progresso")

        # HUMANIZAÇÃO: Verificar se estamos avançando (apenas fora de combate/loot)
        # NOVO: Não verificar imediatamente após gerar rota global (dar tempo de começar a andar)
        if ADVANCEMENT_TRACKING_ENABLED and wp['z'] == pz:
            if not state.is_in_combat and not state.has_open_loot:
                # Cooldown de 5s após gerar rota global antes de verificar progresso
                if time.time() - self.last_global_path_time < 5.0:
                    pass  # Pula verificação de progresso
                elif not self.advancement_tracker.is_advancing(ADVANCEMENT_EXPECTED_SPEED):
                    self._handle_no_progress(px, py, pz, wp)
                    return

        # ======================================================================
        # 4. LÓGICA DE ANDARES (FLOOR CHANGE)
        # ======================================================================
        # Multifloor same-Z: se temos rota multifloor e consumimos os tiles do andar atual,
        # precisamos mudar de andar mesmo que wp['z'] == pz
        if wp['z'] == pz and self._multifloor_full_path and not self.current_global_path:
            # Encontrar o próximo Z na rota multifloor
            next_z = None
            for t in self._multifloor_full_path:
                if t[2] != pz:
                    next_z = t[2]
                    break
            if next_z is not None:
                direction = "↑ SUBIR" if next_z < pz else "↓ DESCER"
                if DEBUG_PATHFINDING:
                    print(f"[{_ts()}] [🪜 MULTIFLOOR SAME-Z] Precisa {direction}: Z atual={pz} → Z intermediário={next_z}")
                floor_target = self.analyzer.scan_for_floor_change(
                    next_z, pz,
                    player_abs_x=px, player_abs_y=py,
                    transitions_by_floor=self.global_map._transitions_by_floor if hasattr(self, 'global_map') and self.global_map else None
                )
                if floor_target:
                    fx, fy, ftype, fid = floor_target
                    dist_obj = math.sqrt(fx**2 + fy**2)
                    if DEBUG_PATHFINDING:
                        print(f"[{_ts()}] [🪜 MULTIFLOOR SAME-Z] Encontrado {ftype} (ID:{fid}) em ({fx:+d}, {fy:+d}), dist={dist_obj:.1f}")
                    if dist_obj <= 1.5:
                        fc_success = self._handle_special_tile(fx, fy, ftype, fid, px, py, pz)
                        self.current_global_path = []
                        if fc_success:
                            self.last_floor_change_time = time.time()
                            self._last_floor_change_from_z = pz
                            # Recalcular multifloor do novo andar
                            self._multifloor_full_path = None
                        return
                    else:
                        # Navegar até a transição
                        abs_x = px + fx
                        abs_y = py + fy
                        self._navigate_hybrid(abs_x, abs_y, pz, px, py)
                        self.last_action_time = time.time()
                        return

        if wp['z'] != pz:
            direction = "↑ SUBIR" if wp['z'] < pz else "↓ DESCER"
            self.current_state = self.STATE_FLOOR_CHANGE
            self.state_message = f"🪜 Mudança de andar ({direction} para Z={wp['z']})"
            if DEBUG_PATHFINDING:
                print(f"[{_ts()}] [🪜 FLOOR CHANGE] Necessário {direction}: Z atual={pz} → Z alvo={wp['z']}")

            # O scanner retorna: (rel_x, rel_y, type, special_id)
            floor_target = self.analyzer.scan_for_floor_change(
                wp['z'], pz,
                player_abs_x=px, player_abs_y=py,
                dest_x=wp['x'], dest_y=wp['y'],
                transitions_by_floor=self.global_map._transitions_by_floor if hasattr(self, 'global_map') and self.global_map else None
            )

            # Se escada visível, validar contra multifloor (mesmo com 1 andar restante)
            if floor_target and USE_MULTIFLOOR_PATHFINDING and hasattr(self, 'global_map') and self.global_map:
                fx, fy, ftype, fid = floor_target
                abs_stair_x = px + fx
                abs_stair_y = py + fy
                # Computar multifloor se não temos path cacheado
                if not self.current_global_path:
                    full_path = self.global_map.get_path_multilevel(
                        (px, py, pz), (wp['x'], wp['y'], wp['z'])
                    )
                    if full_path:
                        # Inserir waypoints adjacentes às transições
                        full_path = self._insert_transition_waypoints(full_path)
                        same_floor = [t for t in full_path if t[2] == pz]
                        if same_floor:
                            self.current_global_path = same_floor
                # Comparar escada visível com destino do multifloor
                if self.current_global_path:
                    mf_target = self.current_global_path[-1]  # Última tile no andar atual
                    if abs(mf_target[0] - abs_stair_x) + abs(mf_target[1] - abs_stair_y) > 3:
                        print(f"[{_ts()}] [FloorChange] Escada visível ({abs_stair_x},{abs_stair_y}) ≠ multifloor target ({mf_target[0]},{mf_target[1]}). Seguindo multifloor.")
                        floor_target = None

            # Yo-yo protection: não usar transição que volta pro andar de onde acabamos de vir
            if floor_target and self._last_floor_change_from_z is not None:
                fx, fy, ftype, fid = floor_target
                would_go_to_z = pz + (1 if ftype in ('DOWN', 'DOWN_USE', 'SHOVEL') else -1)
                if would_go_to_z == self._last_floor_change_from_z:
                    elapsed = time.time() - self.last_floor_change_time
                    if elapsed < 5.0:
                        if DEBUG_PATHFINDING:
                            print(f"[{_ts()}] [Nav] Ignorando {ftype} — voltaria ao Z={self._last_floor_change_from_z} (yo-yo protection, {elapsed:.1f}s)")
                        floor_target = None

            if floor_target:
                fx, fy, ftype, fid = floor_target
                dist_obj = math.sqrt(fx**2 + fy**2)

                if DEBUG_PATHFINDING:
                    print(f"[{_ts()}] [🪜 FLOOR CHANGE] Encontrado {ftype} (ID:{fid}) em ({fx:+d}, {fy:+d}), distância={dist_obj:.1f} SQM")

                # Se estamos ADJACENTES (dist <= 1.5) ou EM CIMA (dist == 0)
                # Para Ladder e Rope, precisamos estar PERTO.
                if dist_obj <= 1.5:
                    if DEBUG_PATHFINDING:
                        print(f"[{_ts()}] [🪜 FLOOR CHANGE] ✓ Adjacente ao {ftype}, executando...")
                    fc_success = self._handle_special_tile(fx, fy, ftype, fid, px, py, pz)

                    # Limpar path global ao mudar de andar (path antigo é inválido)
                    if self.current_global_path:
                        print(f"[{_ts()}] [DEBUG] Path limpo em: floor_change (tinha {len(self.current_global_path)} nós)")
                    self.current_global_path = []
                    self.last_lookahead_idx = -1

                    # Registra timestamp do floor change para cooldown apenas se teve sucesso
                    if fc_success:
                        self.last_floor_change_time = time.time()
                    if DEBUG_PATHFINDING:
                        print(f"[{_ts()}] [🪜 FLOOR CHANGE] ⏳ Aguardando 1s para permitir combate no novo andar")

                    # Após uma interação de andar/usar, a posição global pode ter mudado (ex: subir de andar).
                    npx, npy, npz = get_player_pos(self.pm, self.base_addr)
                    if npz != pz:
                        self._last_floor_change_from_z = pz
                    if wp['z'] == npz:
                        dist_after = math.sqrt((wp['x'] - npx) ** 2 + (wp['y'] - npy) ** 2)
                        if dist_after <= 1.5:
                            print(f"[{_ts()}] [Cavebot] Chegou no WP {current_index} após floor change")
                            with self._waypoints_lock:
                                self._advance_waypoint()
                            self.last_action_time = time.time()
                            return
                else:
                    # Para tiles de USE, prefira parar em um tile cardinal adjacente e usar à distância.
                    # Para DOWN/UP_WALK, navegar para tile adjacente (A* não pode pathing para non-walkable)
                    target_fx, target_fy = fx, fy
                    if ftype in ('UP_USE', 'DOWN_USE', 'SHOVEL', 'ROPE'):
                        target_fx, target_fy = self._get_adjacent_use_tile(fx, fy)
                    elif ftype in ('DOWN', 'UP_WALK'):
                        adj = self._get_walkable_adjacent_tile(fx, fy)
                        if adj:
                            target_fx, target_fy = adj

                    if DEBUG_PATHFINDING:
                        print(f"[{_ts()}] [🪜 FLOOR CHANGE] Longe do {ftype}, calculando caminho para ({target_fx:+d}, {target_fy:+d})...")
                    abs_ladder_x = px + target_fx
                    abs_ladder_y = py + target_fy
                    self._navigate_hybrid(abs_ladder_x, abs_ladder_y, pz, px, py)
            else:
                # Escada/rope fora da tela - navegar até lá
                nav_target_x, nav_target_y = wp['x'], wp['y']
                dist_to_target = math.sqrt((nav_target_x - px)**2 + (nav_target_y - py)**2)

                # Se já temos uma rota global, apenas caminhar (não recalcular toda tick)
                if self.current_global_path and dist_to_target > 2:
                    last_tile = self.current_global_path[-1]
                    self._navigate_hybrid(last_tile[0], last_tile[1], pz, px, py)
                    self.last_action_time = time.time()
                    return

                if dist_to_target > 2:
                    print(f"[{_ts()}] [Cavebot] 🔍 Escada não visível. Navegando até ({nav_target_x}, {nav_target_y}) Z={wp['z']} (dist: {dist_to_target:.1f})")

                    path = None

                    # Multifloor: calcular rota completa cross-floor e extrair segmento atual
                    if USE_MULTIFLOOR_PATHFINDING:
                        print(f"[{_ts()}] [Cavebot] 🔍 Multifloor: ({px},{py},{pz}) → ({wp['x']},{wp['y']},{wp['z']})")
                        print(f"[{_ts()}] [Cavebot]   Transitions disponíveis: andares={list(self.global_map._transitions_by_floor.keys()) if self.global_map._transitions_by_floor else 'NENHUM'}")
                        trans_from_here = self.global_map._transitions_by_floor.get(pz, [])
                        print(f"[{_ts()}] [Cavebot]   Transições do andar {pz}: {len(trans_from_here)} registradas")
                        if trans_from_here:
                            for tx, ty, tz in trans_from_here[:5]:
                                mdist = abs(tx - px) + abs(ty - py)
                                print(f"[{_ts()}] [Cavebot]     → ({tx},{ty}) Z→{tz} dist={mdist}")
                        full_path = self.global_map.get_path_multilevel(
                            (px, py, pz),
                            (wp['x'], wp['y'], wp['z'])
                        )
                        if full_path:
                            print(f"[{_ts()}] [Cavebot]   ✅ Multifloor encontrou path: {len(full_path)} tiles")
                            # Inserir waypoints adjacentes às transições
                            full_path = self._insert_transition_waypoints(full_path)
                            # Extrair apenas tiles do andar atual (até a transição)
                            same_floor_path = []
                            for tile in full_path:
                                if tile[2] == pz:
                                    same_floor_path.append(tile)
                                else:
                                    break
                            # Parar 2 tiles antes da transição para detectar tile especial
                            if len(same_floor_path) > 2:
                                same_floor_path = same_floor_path[:-2]
                            if same_floor_path:
                                path = same_floor_path
                                print(f"[{_ts()}] [Cavebot] 🛤️ Rota multifloor: {len(full_path)} tiles total, {len(path)} neste andar")

                    if USE_MULTIFLOOR_PATHFINDING and not path:
                        print(f"[{_ts()}] [Cavebot]   ❌ Multifloor falhou (full_path={'None' if not full_path else f'{len(full_path)} tiles, same_floor=0'})")

                    # Fallback: rota same-floor até coordenada do waypoint
                    if not path:
                        path = self.global_map.get_path_with_fallback(
                            (px, py, pz),
                            (nav_target_x, nav_target_y, pz),
                            max_offset=5
                        )

                    if path:
                        self.current_global_path = path
                        if not USE_MULTIFLOOR_PATHFINDING:
                            print(f"[{_ts()}] [Cavebot] 🛤️ Rota para escada: {len(path)} tiles")
                        # Iniciar movimento imediatamente
                        last_tile = path[-1]
                        self._navigate_hybrid(last_tile[0], last_tile[1], pz, px, py)
                    else:
                        print(f"[{_ts()}] [Cavebot] ⚠️ GlobalMap falhou. Usando navegação local.")
                        self._navigate_hybrid(nav_target_x, nav_target_y, pz, px, py)
                else:
                    # Chegou perto mas ainda não achou escada - incrementa stuck
                    self.global_recalc_counter += 1
                    print(f"[{_ts()}] [Cavebot] ⚠️ Escada não encontrada perto de ({nav_target_x}, {nav_target_y}, {pz})! ({self.global_recalc_counter}/{GLOBAL_RECALC_LIMIT})")

                    if self.global_recalc_counter >= GLOBAL_RECALC_LIMIT:
                        print(f"[{_ts()}] [Cavebot] ⚠️ Limite atingido. Pulando para próximo waypoint.")
                        with self._waypoints_lock:
                            self._advance_waypoint()
                            if self.current_global_path:
                                print(f"[{_ts()}] [DEBUG] Path limpo em: escada_stuck (tinha {len(self.current_global_path)} nós)")
                            self.current_global_path = []
                        self.global_recalc_counter = 0
            
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

    # ==================================================================
    # AUTO-EXPLORE
    # ==================================================================

    def init_auto_explore(self, xml_path, target_monsters=None, search_radius=None, revisit_cooldown=None):
        """Configura o modo auto-explore. Chamado pela GUI ao ativar."""
        self._explore_xml_path = xml_path
        self._explore_target_monsters = target_monsters or []
        self._explore_search_radius = search_radius or AUTO_EXPLORE_SEARCH_RADIUS
        self._explore_revisit_cooldown = revisit_cooldown or AUTO_EXPLORE_REVISIT_COOLDOWN
        self._explore_initialized = False
        self._current_spawn_target = None
        self._spawn_selector = None
        self._nav_fail_count = 0

    def _init_auto_explore_selector(self, px, py, pz):
        """Inicializa o SpawnSelector com suporte multi-andar."""
        if not self._explore_xml_path:
            print(f"[{_ts()}] [AutoExplore] XML path nao configurado!")
            return False

        try:
            all_spawns = parse_spawns(self._explore_xml_path)

            # FloorConnector para navegação multi-andar
            max_floors = AUTO_EXPLORE_MAX_FLOORS
            floor_connector = None
            if max_floors > 0:
                transitions_path = _get_bundled_path("floor_transitions.json")
                floor_connector = FloorConnector(self.global_map, transitions_file=transitions_path)
                self._floor_connector = floor_connector

            # Carregar grafo pré-computado se disponível
            spawn_graph = None
            graph_path = _get_bundled_path("spawn_graph.json")
            if os.path.isfile(graph_path):
                try:
                    import json
                    with open(graph_path, 'r') as f:
                        raw = json.load(f)
                    # Extract only edges, discard nodes (~4.2 MB savings)
                    raw_edges = raw.get("edges", {})
                    del raw
                    # Convert {"to": str, "cost": int} -> (str, int) (~27 MB savings)
                    spawn_graph = {
                        key: [(e["to"], e["cost"]) for e in edge_list]
                        for key, edge_list in raw_edges.items()
                    }
                    del raw_edges
                    if DEBUG_AUTO_EXPLORE:
                        print(f"[{_ts()}] [AutoExplore] Grafo de spawns carregado: {graph_path}")
                except Exception as e:
                    print(f"[{_ts()}] [AutoExplore] Erro ao carregar grafo: {e}")

            self._spawn_selector = SpawnSelector(
                spawns=all_spawns,
                global_map=self.global_map,
                floor_connector=floor_connector,
                target_monsters=self._explore_target_monsters,
                revisit_cooldown=self._explore_revisit_cooldown,
                search_radius=self._explore_search_radius,
                max_floors=max_floors,
                spawn_graph=spawn_graph,
            )
            count = self._spawn_selector.initialize((px, py, pz))
            self._explore_initialized = True
            self._current_spawn_target = None

            if DEBUG_AUTO_EXPLORE:
                print(f"[{_ts()}] [AutoExplore] Inicializado: {count} spawns acessiveis (Z={pz}, max_floors={max_floors})")
                print(f"[{_ts()}] [AutoExplore] Filtros: monstros={self._explore_target_monsters}, raio={self._explore_search_radius}")
                # Log spawns por andar
                floors = {}
                for s in self._spawn_selector.active_spawns:
                    floors.setdefault(s.cz, []).append(s)
                for z in sorted(floors):
                    print(f"[{_ts()}] [AutoExplore]   Z={z}: {len(floors[z])} spawns")

            if count == 0:
                print(f"[{_ts()}] [AutoExplore] Nenhum spawn acessivel encontrado!")
                return False

            return True
        except Exception as e:
            print(f"[{_ts()}] [AutoExplore] Erro ao inicializar: {e}")
            import traceback
            traceback.print_exc()
            return False

    def _run_auto_explore(self, px, py, pz):
        """Lógica principal do auto-explore. Chamado dentro de run_cycle."""
        # 1. Inicialização lazy ou re-init ao mudar de andar
        if not self._explore_initialized:
            if not self._init_auto_explore_selector(px, py, pz):
                self.current_state = self.STATE_STUCK
                self.state_message = "Auto-Explore: sem spawns"
                return

        # 2. Sem target? Selecionar proximo spawn
        if not self._current_spawn_target:
            self._nav_fail_count = 0
            visible_players = self._get_visible_players(pz)
            self._current_spawn_target = self._spawn_selector.select_next(
                (px, py, pz), visible_players
            )
            if not self._current_spawn_target:
                self.current_state = self.STATE_IDLE
                self.state_message = "Auto-Explore: aguardando cooldown"
                if DEBUG_AUTO_EXPLORE:
                    print(f"[{_ts()}] [AutoExplore] Nenhum spawn disponivel (todos em cooldown)")
                return

            if DEBUG_AUTO_EXPLORE:
                spawn = self._current_spawn_target
                print(f"[{_ts()}] [AutoExplore] Novo destino: ({spawn.cx}, {spawn.cy}, {spawn.cz}) - {spawn.monster_names()}")
            self.advancement_tracker.reset()
            self.last_global_path_time = time.time()

        spawn = self._current_spawn_target

        # HUMANIZAÇÃO: Registrar distância para tracking de avanço
        if ADVANCEMENT_TRACKING_ENABLED:
            dist_to_spawn = spawn.distance_to(px, py)
            self.advancement_tracker.record_distance(dist_to_spawn)

        # 3. Chegou na area do spawn?
        if spawn.is_inside(px, py, pz):
            self._spawn_selector.mark_visited(spawn)
            if DEBUG_AUTO_EXPLORE:
                print(f"[{_ts()}] [AutoExplore] Spawn visitado: ({spawn.cx}, {spawn.cy}, {spawn.cz})")
            self._current_spawn_target = None
            self._cached_transition = None
            self.current_global_path = []
            self.advancement_tracker.reset()
            return

        # 4. Player mais proximo do spawn? Pular (só no mesmo andar)
        if spawn.cz == pz:
            visible_players = self._get_visible_players(pz)
            if self._spawn_selector.is_occupied_by_closer_player(spawn, px, py, visible_players):
                if DEBUG_AUTO_EXPLORE:
                    player_info = [(p.name, p.position.x, p.position.y, p.position.z) for p in visible_players[:3]]
                    print(f"[{_ts()}] [AutoExplore] Spawn ocupado por player, trocando destino. Players: {player_info}")
                self._spawn_selector.skip_spawn(spawn, "ocupado por player", (px, py, pz), cooldown_override=600)
                self._current_spawn_target = None
                self.current_global_path = []
                self.advancement_tracker.reset()
                return

        # HUMANIZAÇÃO: Verificar se estamos avançando ao spawn
        if ADVANCEMENT_TRACKING_ENABLED and spawn.cz == pz:
            if not state.is_in_combat and not state.has_open_loot:
                if time.time() - self.last_global_path_time < 5.0:
                    pass  # Cooldown após gerar rota
                elif not self.advancement_tracker.is_advancing(ADVANCEMENT_EXPECTED_SPEED):
                    self._handle_no_progress_explore(px, py, pz, spawn)
                    return

        # 5. Spawn em andar diferente? Usar lógica de floor change
        if spawn.cz != pz:
            target_z = spawn.cz
            direction = "SUBIR" if target_z < pz else "DESCER"
            self.current_state = self.STATE_FLOOR_CHANGE
            self.state_message = f"Auto-Explore: {direction} para Z={target_z}"

            # Tenta encontrar tile especial na tela (escada/buraco/rope)
            floor_target = self.analyzer.scan_for_floor_change(
                target_z, pz,
                player_abs_x=px, player_abs_y=py,
                dest_x=spawn.cx, dest_y=spawn.cy,
                transitions_by_floor=self.global_map._transitions_by_floor if hasattr(self, 'global_map') and self.global_map else None
            )

            if floor_target:
                fx, fy, ftype, fid = floor_target
                dist_obj = math.sqrt(fx**2 + fy**2)

                # Yo-yo protection: não usar transição que volta pro andar de onde acabamos de vir
                if self._last_floor_change_from_z is not None:
                    would_go_to_z = pz + (1 if ftype in ('DOWN', 'DOWN_USE', 'SHOVEL') else -1)
                    if would_go_to_z == self._last_floor_change_from_z:
                        elapsed = time.time() - self.last_floor_change_time
                        if elapsed < 5.0:
                            if DEBUG_AUTO_EXPLORE:
                                print(f"[{_ts()}] [AutoExplore] Ignorando {ftype} — voltaria ao Z={self._last_floor_change_from_z} (yo-yo protection, {elapsed:.1f}s)")
                            floor_target = None

            if floor_target:
                fx, fy, ftype, fid = floor_target
                dist_obj = math.sqrt(fx**2 + fy**2)

                if dist_obj <= 1.5:
                    # Adjacente — interagir com o tile
                    if DEBUG_AUTO_EXPLORE:
                        print(f"[{_ts()}] [AutoExplore] Adjacente ao {ftype}, usando...")
                    fc_success = self._handle_special_tile(fx, fy, ftype, fid, px, py, pz)
                    if fc_success:
                        self.last_floor_change_time = time.time()

                    # Verificar se mudou de andar
                    npx, npy, npz = get_player_pos(self.pm, self.base_addr)
                    if npz != pz:
                        if DEBUG_AUTO_EXPLORE:
                            print(f"[{_ts()}] [AutoExplore] Mudou de andar: Z={pz} -> Z={npz}")
                        self._last_floor_change_from_z = pz
                        # Não limpar target — manter o spawn alvo para continuar navegando até ele no novo andar
                        self._cached_transition = None
                        self.current_global_path = []
                    return
                else:
                    # Longe — navegar até tile adjacente ao tile especial
                    target_fx, target_fy = fx, fy
                    if ftype in ('UP_USE', 'DOWN_USE', 'SHOVEL', 'ROPE'):
                        target_fx, target_fy = self._get_adjacent_use_tile(fx, fy)
                    elif ftype in ('DOWN', 'UP_WALK'):
                        # DOWN/UP_WALK: navegar para tile ADJACENTE (não para o buraco/escada)
                        # porque A* não pode pathing para tiles non-walkable
                        adj = self._get_walkable_adjacent_tile(fx, fy)
                        if adj:
                            target_fx, target_fy = adj
                    abs_x = px + target_fx
                    abs_y = py + target_fy
                    if DEBUG_AUTO_EXPLORE:
                        print(f"[{_ts()}] [AutoExplore] Navegando ate {ftype} em ({abs_x}, {abs_y})")
                    # Bug 5 fix: Only clear path if target changed (prevents recalculation loop)
                    if not self.current_global_path or self.current_global_path[-1][:2] != (abs_x, abs_y):
                        if DEBUG_AUTO_EXPLORE:
                            print(f"[{_ts()}] [AutoExplore] Limpando path - novo target: ({abs_x}, {abs_y})")
                        self.current_global_path = []
                    self._navigate_hybrid(abs_x, abs_y, pz, px, py)
                    return
            else:
                # Tile especial fora de vista — usar get_path_multilevel para rota até spawn
                target_pos = spawn.nearest_walkable_target(self.global_map)
                if not target_pos:
                    self._current_spawn_target = None
                    self._cached_spawn_target_pos = None
                    return

                # CACHE CHECK: Só recalcula path se necessário (evita recálculo a cada ciclo)
                need_recalc = False
                if not self.current_global_path:
                    need_recalc = True
                elif self._cached_spawn_target_pos != target_pos:
                    need_recalc = True

                if need_recalc:
                    # Atualiza cache
                    self._cached_spawn_target_pos = target_pos
                    full_path = self.global_map.get_path_multilevel(
                        (px, py, pz), target_pos
                    )
                    if not full_path:
                        if DEBUG_AUTO_EXPLORE:
                            print(f"[{_ts()}] [AutoExplore] Sem rota multilevel de Z={pz} para spawn Z={spawn.cz}")
                        self._current_spawn_target = None
                        return
                    # Inserir waypoints adjacentes às transições
                    full_path = self._insert_transition_waypoints(full_path)
                    # Extrair tiles do andar atual para navegar até a escada
                    same_floor = [t for t in full_path if t[2] == pz]
                    # Parar 2 tiles antes da transição para que scan_for_floor_change
                    # possa detectar e interagir com o tile especial (rope/escada)
                    if len(same_floor) > 2:
                        same_floor = same_floor[:-2]
                    if same_floor:
                        self.current_global_path = same_floor

                # Navegar usando path cacheado ou recém-calculado
                if self.current_global_path:
                    last_tile = self.current_global_path[-1]
                    self._navigate_hybrid(last_tile[0], last_tile[1], pz, px, py)
                return

        # 6. Mesmo andar: navegar ate o spawn
        target_pos = spawn.nearest_walkable_target(self.global_map)
        if not target_pos:
            if DEBUG_AUTO_EXPLORE:
                print(f"[{_ts()}] [AutoExplore] Nenhum tile walkable no spawn, pulando")
            self._current_spawn_target = None
            self._cached_spawn_target_pos = None
            return

        # CACHE DE TARGET: Detectar mudança significativa (pode causar oscilação)
        if self._cached_spawn_target_pos and target_pos != self._cached_spawn_target_pos:
            dist_change = math.sqrt(
                (target_pos[0] - self._cached_spawn_target_pos[0])**2 +
                (target_pos[1] - self._cached_spawn_target_pos[1])**2
            )
            if dist_change > 3:  # Mudança significativa (> 3 SQM)
                if DEBUG_AUTO_EXPLORE or DEBUG_OSCILLATION:
                    print(f"[{_ts()}] [AutoExplore] ⚠️ Target mudou: {self._cached_spawn_target_pos} → {target_pos} (Δ={dist_change:.1f})")
                # Limpa histórico de passos para evitar falso-positivo de oscilação
                self._step_history.clear()
        self._cached_spawn_target_pos = target_pos

        # Verificar se rota existe antes de navegar (só quando não tem rota ativa)
        if not self.current_global_path:
            if USE_MULTIFLOOR_PATHFINDING and pz != target_pos[2]:
                path = self.global_map.get_path_multilevel((px, py, pz), target_pos)
            else:
                path = self.global_map.get_path((px, py, pz), target_pos)
            if not path:
                self._nav_fail_count += 1
                if self._nav_fail_count >= 3:
                    if DEBUG_AUTO_EXPLORE:
                        print(f"[{_ts()}] [AutoExplore] Spawn inalcançável após {self._nav_fail_count} tentativas, pulando")
                    self._spawn_selector.skip_spawn(spawn, "inalcançável", (px, py, pz))
                    self._current_spawn_target = None
                    self._nav_fail_count = 0
                return
            self._nav_fail_count = 0
        cost = spawn.distance_to(px, py)
        self.current_state = self.STATE_WALKING
        self.state_message = f"Auto-Explore: {', '.join(sorted(spawn.monster_names())[:2])} ({cost:.0f} passos)"

        self._navigate_hybrid(target_pos[0], target_pos[1], target_pos[2], px, py)

        # Detecção de Stuck (player parado no mesmo tile)
        self._check_stuck(px, py, pz, mode="auto_explore")

    def _get_visible_players(self, pz=None):
        """Retorna lista de players visíveis via BattleList."""
        try:
            if not self._explore_battlelist:
                self._explore_battlelist = BattleListScanner(self.pm, self.base_addr)
            creatures = self._explore_battlelist.scan_all()
            player_id = state.get_player_id(self.pm, self.base_addr)
            players = [c for c in creatures
                       if c.is_player and c.id != player_id and c.is_visible]
            if pz is not None:
                players = [p for p in players if p.position.z == pz]
            return players
        except Exception:
            return []

    # ==================================================================
    # WAYPOINT NAVIGATION
    # ==================================================================

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
            print(f"[{_ts()}] [Nav] 🌍 Calculando Rota Global... Motivo: {reason}")
            # Ao recalcular global, limpamos o cache local (só se estiver usando cache)
            if not REALTIME_PATHING_ENABLED:
                self.local_path_cache = []

            # ===== NOVO: Usar fallback inteligente =====
            _, _, my_z = get_player_pos(self.pm, self.base_addr)
            if USE_MULTIFLOOR_PATHFINDING and my_z != dest_z:
                path = self.global_map.get_path_multilevel(
                    (my_x, my_y, my_z),
                    (dest_x, dest_y, dest_z)
                )
                # Se o path cruza andares, extrair apenas tiles do andar atual
                if path and any(t[2] != my_z for t in path):
                    # Inserir waypoints adjacentes às transições
                    path = self._insert_transition_waypoints(path)
                    same_floor = []
                    for t in path:
                        if t[2] == my_z:
                            same_floor.append(t)
                        else:
                            break
                    # Parar 2 tiles antes da transição (para scan_for_floor_change detectar)
                    if len(same_floor) > 2:
                        same_floor = same_floor[:-2]
                    if same_floor:
                        path = same_floor
                        print(f"[{_ts()}] [Nav] 🔀 Rota multifloor detectada, usando {len(path)} tiles do andar atual")
                    else:
                        # Bot já está perto da transição — tentar floor change
                        print(f"[{_ts()}] [Nav] 🔀 Bot próximo de transição de andar, tentando floor change...")
                        next_z = next((t[2] for t in path if t[2] != my_z), None)
                        if next_z is not None:
                            floor_target = self.analyzer.scan_for_floor_change(
                                next_z, my_z,
                                player_abs_x=my_x, player_abs_y=my_y,
                                transitions_by_floor=self.global_map._transitions_by_floor if self.global_map else None
                            )
                            if floor_target:
                                fx, fy, ftype, fid = floor_target
                                dist_obj = math.sqrt(fx**2 + fy**2)
                                if dist_obj <= 1.5:
                                    print(f"[{_ts()}] [Nav] 🪜 Adjacente a {ftype}, usando...")
                                    fc_success = self._handle_special_tile(fx, fy, ftype, fid, my_x, my_y, dest_z)
                                    self.current_global_path = []
                                    if fc_success:
                                        self.last_floor_change_time = time.time()
                                    return
                                else:
                                    # Navegar até o tile especial
                                    abs_x = my_x + fx
                                    abs_y = my_y + fy
                                    path = self.global_map.get_path(
                                        (my_x, my_y, dest_z), (abs_x, abs_y, dest_z)
                                    )
                            if not floor_target or not path:
                                path = None
                        else:
                            path = None
            else:
                path = None

            if not path:
                path = self.global_map.get_path_with_fallback(
                    (my_x, my_y, dest_z),
                    (dest_x, dest_y, dest_z),
                    max_offset=2
                )
                if path:
                    # Same-floor funcionou, limpar rota multifloor se existia
                    self._multifloor_full_path = None

            # Fallback: se same-floor falhou, tentar multifloor (barreira pode exigir desvio por outro andar)
            if not path and USE_MULTIFLOOR_PATHFINDING:
                ml_path = self.global_map.get_path_multilevel(
                    (my_x, my_y, my_z),
                    (dest_x, dest_y, dest_z)
                )
                if ml_path and any(t[2] != my_z for t in ml_path):
                    # Salvar rota completa para o floor change handler usar
                    self._multifloor_full_path = ml_path
                    # Inserir waypoints adjacentes às transições para evitar oscilação
                    ml_path = self._insert_transition_waypoints(ml_path)
                    same_floor = []
                    for t in ml_path:
                        if t[2] == my_z:
                            same_floor.append(t)
                        else:
                            break
                    if len(same_floor) > 2:
                        same_floor = same_floor[:-2]
                    if same_floor:
                        path = same_floor
                        print(f"[{_ts()}] [Nav] 🔀 Same-floor falhou, usando rota multifloor ({len(path)} tiles ate transicao)")
                    else:
                        # Já estamos perto da transição — não cortar tiles
                        path = None
                elif ml_path:
                    path = ml_path

            if path:
                self.current_global_path = path
                self.global_recalc_counter = 0 # Sucesso, reseta contador
                self.last_lookahead_idx = -1
                self.advancement_tracker.reset()  # Reseta tracker para dar tempo de começar a andar
                self.last_global_path_time = time.time()  # Marca quando gerou rota para cooldown
                print(f"[{_ts()}] [Nav] 🛤️ Rota Global Gerada: {len(path)} nós.")
            else:
                print(f"[{_ts()}] [Nav] ⚠️ GlobalMap não achou rota (nem com fallback). Tentando direto.")
        
        # B. Definir o Sub-Destino (Janela Deslizante)
        # O A* local não consegue ir até o destino final se for longe.
        # Precisamos dar a ele um alvo visível (~7 sqm).
        target_local_x, target_local_y = dest_x, dest_y

        if self.current_global_path:
            # Get player Z for lookahead validation (avoid jumping past floor transitions)
            _, _, current_z = get_player_pos(self.pm, self.base_addr)

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
                MIN_LOOKAHEAD = 3  # Evita sub-destino muito próximo (causa oscilação)

                # Reduz lookahead se sub-destino ficaria fora do range de memória (±7)
                # ou se estiver em outro andar (evita pular transições de floor)
                while lookahead > MIN_LOOKAHEAD:
                    lx, ly, lz = self.current_global_path[lookahead]
                    if abs(lx - my_x) <= 7 and abs(ly - my_y) <= 7 and lz == current_z:
                        break
                    lookahead -= 1

                # Garante lookahead mínimo (se path for muito curto, usa o que tem)
                lookahead = max(min(MIN_LOOKAHEAD, len(self.current_global_path) - 1), lookahead)

                if lookahead != self.last_lookahead_idx:
                    print(f"[{_ts()}] [Nav] 🚶 Seguindo Global: Nó {lookahead}/{len(self.current_global_path)}")
                    self.last_lookahead_idx = lookahead

                tx, ty, tz = self.current_global_path[lookahead]
                target_local_x, target_local_y = tx, ty

                # HUMANIZAÇÃO: Registrar nodes restantes (mais preciso que distância)
                if ADVANCEMENT_TRACKING_ENABLED:
                    self.advancement_tracker.record_nodes(len(self.current_global_path))
            else:
                # Perdemos a rota, limpa para recalcular
                print(f"[{_ts()}] [Nav] ⚠️ Perdido da rota global. Resetando.")
                if self.current_global_path:
                    print(f"[{_ts()}] [DEBUG] Path limpo em: perdido_da_rota (tinha {len(self.current_global_path)} nós)")
                self.current_global_path = []

        # DEBUG: Log do sub-destino definido
        if DEBUG_PATHFINDING:
            has_global = len(self.current_global_path) > 0
            source = "Global[lookahead]" if has_global else "WP direto"
            sub_dist = math.sqrt((target_local_x - my_x)**2 + (target_local_y - my_y)**2)
            print(f"[{_ts()}] [Nav] 🎯 Sub-destino: ({target_local_x}, {target_local_y}) | Fonte: {source} | Dist: {sub_dist:.1f} sqm")

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
                print(f"[{_ts()}] [Nav] 📍 Destino longe ({dist_to_target:.1f} sqm), sub-destino ({rel_x}, {rel_y})")

        if REALTIME_PATHING_ENABLED:
            # ========== MODO REAL-TIME ==========
            # Calcula o próximo passo baseado no estado ATUAL do mapa
            # Mais preciso, evita obstáculos fantasmas e diagonais erráticas

            # DEBUG: Log antes de chamar A* local
            if DEBUG_PATHFINDING:
                print(f"[{_ts()}] [Nav] 🔍 A* Local: buscando passo para rel({rel_x}, {rel_y})")

            step = self.walker.get_next_step(rel_x, rel_y)

            if step:
                dx, dy = step

                # DEBUG: Log do resultado do A* local (sucesso)
                if DEBUG_PATHFINDING:
                    print(f"[{_ts()}] [Nav] ✅ A* Local encontrou: passo ({dx}, {dy})")

                # OBSTACLE CLEARING: Tenta mover mesa/cadeira se estiver no caminho
                if OBSTACLE_CLEARING_ENABLED:
                    props = self.analyzer.get_tile_properties(dx, dy)
                    if DEBUG_OBSTACLE_CLEARING:
                        print(f"[{_ts()}] [ObstacleClear] REALTIME: Próximo passo ({dx},{dy}) - walkable={props['walkable']}, type={props.get('type')}")

                    # Verificar se tem MOVE item mesmo que "walkable" (bug fix)
                    obstacle_info = self.analyzer.get_obstacle_type(dx, dy)
                    if DEBUG_OBSTACLE_CLEARING:
                        print(f"[{_ts()}] [ObstacleClear] REALTIME: obstacle_info={obstacle_info}")

                    # Se tem obstáculo MOVE ou STACK, tenta limpar mesmo que tile seja "walkable"
                    if obstacle_info['type'] in ('MOVE', 'STACK') and obstacle_info['clearable']:
                        if DEBUG_OBSTACLE_CLEARING or DEBUG_STACK_CLEARING:
                            print(f"[{_ts()}] [ObstacleClear] REALTIME: Detectou {obstacle_info['type']} item, tentando limpar...")
                        cleared = self._attempt_clear_obstacle(dx, dy)
                        if cleared:
                            props = self.analyzer.get_tile_properties(dx, dy)
                            if DEBUG_OBSTACLE_CLEARING:
                                print(f"[{_ts()}] [ObstacleClear] REALTIME: Após limpeza, walkable={props['walkable']}")
                    elif not props['walkable']:
                        if DEBUG_OBSTACLE_CLEARING:
                            print(f"[{_ts()}] [ObstacleClear] REALTIME: Tile não walkable, tentando limpar...")
                        cleared = self._attempt_clear_obstacle(dx, dy)
                        if cleared:
                            props = self.analyzer.get_tile_properties(dx, dy)
                        if not props['walkable']:
                            # Obstáculo não removível, recalcula no próximo ciclo
                            if DEBUG_OBSTACLE_CLEARING:
                                print(f"[{_ts()}] [ObstacleClear] REALTIME: Não conseguiu limpar, recalculando...")
                            self.global_recalc_counter += 1
                            self.next_walk_time = time.time() + 0.1  # Prevent tight loop
                            return

                with self._waypoints_lock:
                    wp_num = self._current_index + 1
                self.current_state = self.STATE_WALKING
                self.state_message = f"🚶 Andando até WP #{wp_num}"

                self._execute_smooth_step(dx, dy)
                self._precompute_last_used_pos = None  # Reset para permitir precompute no próximo passo

                if self.global_recalc_counter > 0 or self._hard_stuck_count > 0:
                    print(f"[{_ts()}] [Nav] ✓ Movimento com sucesso. Resetando stuck.")
                    self.global_recalc_counter = 0
                    self._hard_stuck_count = 0
            else:
                # DEBUG: Log do resultado do A* local (falha)
                if DEBUG_PATHFINDING:
                    print(f"[{_ts()}] [Nav] ❌ A* Local não encontrou caminho para rel({rel_x}, {rel_y})")

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
                            print(f"[{_ts()}] [ObstacleClear] NO_STEP: Verificando ({check_x},{check_y}) = {obstacle_info}")

                        if obstacle_info['clearable'] and obstacle_info['type'] in ('MOVE', 'STACK'):
                            if DEBUG_OBSTACLE_CLEARING or DEBUG_STACK_CLEARING:
                                print(f"[{_ts()}] [ObstacleClear] NO_STEP: Encontrou {obstacle_info['type']} em ({check_x},{check_y}), tentando limpar...")

                            if self._attempt_clear_obstacle(check_x, check_y):
                                obstacle_cleared = True
                                if DEBUG_OBSTACLE_CLEARING or DEBUG_STACK_CLEARING:
                                    print(f"[{_ts()}] [ObstacleClear] NO_STEP: Limpeza bem sucedida!")
                                break

                if obstacle_cleared:
                    # Obstáculo removido, próximo ciclo deve encontrar caminho
                    return

                # Código original de stuck (mantido)
                self.global_recalc_counter += 1
                self.current_state = self.STATE_STUCK
                self.state_message = f"⚠️ Bloqueio local ({self.global_recalc_counter}/{GLOBAL_RECALC_LIMIT})"
                print(f"[{_ts()}] [Nav] ⚠️ Bloqueio Local! ({self.global_recalc_counter}/{GLOBAL_RECALC_LIMIT})")

                if self.global_recalc_counter >= GLOBAL_RECALC_LIMIT:
                    # Passa o sub-destino (lookahead) para bloquear o tile correto
                    self._handle_hard_stuck(target_local_x, target_local_y, dest_z, my_x, my_y)

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
                        print(f"[{_ts()}] [ObstacleClear] CACHE: Próximo passo ({dx},{dy}) - walkable={props['walkable']}, type={props.get('type')}")

                    # Verificar se tem MOVE item mesmo que "walkable" (bug fix)
                    if OBSTACLE_CLEARING_ENABLED:
                        obstacle_info = self.analyzer.get_obstacle_type(dx, dy)
                        if DEBUG_OBSTACLE_CLEARING:
                            print(f"[{_ts()}] [ObstacleClear] CACHE: obstacle_info={obstacle_info}")

                        # Se tem obstáculo MOVE, tenta limpar mesmo que tile seja "walkable"
                        if obstacle_info['type'] == 'MOVE' and obstacle_info['clearable']:
                            if DEBUG_OBSTACLE_CLEARING:
                                print(f"[{_ts()}] [ObstacleClear] CACHE: Detectou MOVE item, tentando limpar...")
                            cleared = self._attempt_clear_obstacle(dx, dy)
                            if cleared:
                                props = self.analyzer.get_tile_properties(dx, dy)
                                if DEBUG_OBSTACLE_CLEARING:
                                    print(f"[{_ts()}] [ObstacleClear] CACHE: Após limpeza, walkable={props['walkable']}")

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
                            print(f"[{_ts()}] [ObstacleClear] CACHE: Tile não walkable, tentando limpar...")
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
                            print(f"[{_ts()}] [ObstacleClear] CACHE: Não conseguiu limpar, invalidando cache")
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

                if self.global_recalc_counter > 0 or self._hard_stuck_count > 0:
                    print(f"[{_ts()}] [Nav] ✓ Movimento local com sucesso. Resetando stuck.")
                    self.global_recalc_counter = 0
                    self._hard_stuck_count = 0
            else:
                self.global_recalc_counter += 1
                self.current_state = self.STATE_STUCK
                self.state_message = f"⚠️ Bloqueio local ({self.global_recalc_counter}/{GLOBAL_RECALC_LIMIT})"
                print(f"[{_ts()}] [Nav] ⚠️ Bloqueio Local! ({self.global_recalc_counter}/{GLOBAL_RECALC_LIMIT})")

                if self.global_recalc_counter >= GLOBAL_RECALC_LIMIT:
                    # Passa o sub-destino (lookahead) para bloquear o tile correto
                    self._handle_hard_stuck(target_local_x, target_local_y, dest_z, my_x, my_y)

    def _try_precompute_next_step(self):
        """
        Pré-calcula o próximo passo durante o tempo de espera (blocked).
        Lê o mapa e roda A* local para ter o (dx, dy) pronto quando next_walk_time expirar.
        Só funciona para o caso comum: andando no mesmo andar com rota global existente.
        """
        try:
            # Verificações rápidas: só precomputa em cenários simples
            if state.is_in_combat or state.has_open_loot or state.is_processing_loot:
                return
            if state.is_runemaking or state.is_gm_detected:
                return

            # Ler posição e mapa
            px, py, pz = get_player_pos(self.pm, self.base_addr)
            player_id = state.get_player_id(self.pm, self.base_addr)
            success = self.memory_map.read_full_map(player_id)
            if not success or not self.memory_map.is_calibrated:
                return

            # Auto-explore: precisa de spawn target no mesmo andar
            if self.auto_explore_enabled:
                spawn = self._current_spawn_target
                if not spawn or spawn.cz != pz:
                    return  # Floor change ou sem target - fluxo normal
                if spawn.is_inside(px, py, pz):
                    return  # Chegou - fluxo normal decide próximo spawn

                target_pos = spawn.nearest_walkable_target(self.global_map)
                if not target_pos:
                    return

                dest_x, dest_y, dest_z = target_pos
            else:
                # Waypoint mode
                with self._waypoints_lock:
                    if not self._waypoints:
                        return
                    wp = self._waypoints[self._current_index]
                dest_x, dest_y, dest_z = wp['x'], wp['y'], wp['z']
                if dest_z != pz:
                    return  # Floor change - fluxo normal

            # Precisamos de rota global existente para o lookahead
            if not self.current_global_path:
                return  # Rota global será calculada no fluxo normal

            if not REALTIME_PATHING_ENABLED:
                return  # Só funciona com realtime pathing

            # Calcular lookahead (mesma lógica de _navigate_hybrid)
            closest_idx = -1
            min_dist_path = 9999
            search_limit = min(len(self.current_global_path), 40)
            for i in range(search_limit):
                gx, gy, gz = self.current_global_path[i]
                d = math.sqrt((gx - px)**2 + (gy - py)**2)
                if d < min_dist_path:
                    min_dist_path = d
                    closest_idx = i

            if closest_idx == -1:
                return

            path_remaining = self.current_global_path[closest_idx:]
            lookahead = min(7, len(path_remaining) - 1)
            MIN_LOOKAHEAD = 3  # Evita sub-destino muito próximo (causa oscilação)

            while lookahead > MIN_LOOKAHEAD:
                lx, ly, _ = path_remaining[lookahead]
                if abs(lx - px) <= 7 and abs(ly - py) <= 7:
                    break
                lookahead -= 1

            # Garante mínimo (mas não exceder tamanho do path)
            lookahead = max(min(MIN_LOOKAHEAD, len(path_remaining) - 1), lookahead)

            tx, ty, _ = path_remaining[lookahead]
            rel_x = tx - px
            rel_y = ty - py

            # A* local
            step = self.walker.get_next_step(rel_x, rel_y)
            if step:
                self._precomputed_step = step
                self._precomputed_pos = (px, py, pz)
                if DEBUG_PATHFINDING:
                    print(f"[{_ts()}] [Nav] 🔮 Pré-calculado: passo ({step[0]}, {step[1]}) em pos ({px}, {py}, {pz})")
        except Exception as e:
            # Qualquer erro: silenciosamente falha, fluxo normal assume
            self._precomputed_step = None
            self._precomputed_pos = None

    def _execute_smooth_step(self, dx, dy):
        """
        Executa um passo com delay dinâmico baseado no ground speed do tile destino
        e variação humana natural (jitter + micro-pausas).
        """
        # 0. OSCILLATION DETECTION: Verificar se criaria oscilação
        if self._detect_oscillation(dx, dy):
            if DEBUG_OSCILLATION:
                print(f"[{_ts()}] [Oscillation] Detectada oscilação para passo ({dx}, {dy})")
            self._handle_oscillation(dx, dy)
            return  # Não executa o passo original

        # 1. Envia o pacote de movimento
        self._move_step(dx, dy)

        # 1.1 Registra passo no histórico (para detecção de oscilação)
        self._record_step(dx, dy)

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

        # 5.1 HUMANIZAÇÃO: Delay adicional se mudança de direção oposta
        # Simula tempo de reação humano ao inverter movimento (ex: Norte→Sul)
        direction_change_delay = 0
        if DIRECTION_CHANGE_DELAY_ENABLED and self._is_opposite_direction(dx, dy):
            direction_change_delay = random.uniform(
                DIRECTION_CHANGE_DELAY_MIN_MS,
                DIRECTION_CHANGE_DELAY_MAX_MS
            )
            if DEBUG_PATHFINDING:
                last_dx, last_dy = self._step_history[-1]
                print(f"[{_ts()}] [Nav] 🔄 Mudança de direção: ({last_dx},{last_dy})→({dx},{dy}) +{direction_change_delay:.0f}ms")

        # 6. NOVO: Adiciona jitter gaussiano (±4% de variação)
        # Simula variação natural de timing humano
        jitter_std = base_ms * 0.04  # Desvio padrão = 4% do base
        jitter = random.gauss(0, jitter_std)

        # 7. NOVO: Adiciona micro-pausa aleatória (2% de chance)
        # Simula pequenas hesitações humanas (30-100ms)
        if random.random() < 0.02:
            jitter += random.uniform(30, 100)

        # 8. Calcula delay final com jitter e delay de mudança de direção
        total_ms = base_ms + jitter + direction_change_delay

        # 9. Buffer de Pre-Move (Antecipação)
        # Enviamos o próximo comando X ms antes de terminar o passo atual
        pre_move_buffer = 150  # ms (90ms é seguro para ping médio)

        wait_time = (total_ms / 1000.0) - (pre_move_buffer / 1000.0)

        # 10. Trava de segurança: Delay mínimo de 50ms para evitar flood
        wait_time = max(0.05, wait_time)

        # Debug opcional (pode ser ativado com DEBUG_PATHFINDING)
        if DEBUG_PATHFINDING:
            print(f"[{_ts()}] [Movement] Ground ID={ground_id}, Speed={ground_speed}, "
                  f"Diagonal={is_diagonal}, Base={base_ms:.1f}ms, "
                  f"Jitter={jitter:.1f}ms, Total={total_ms:.1f}ms, Wait={wait_time:.3f}s")

        #print(f"[{_ts()}] [Cavebot] 🚶 Andando ({dx},{dy}) - Próximo em {wait_time:.2f}s")

        # 11. Define o tempo em que o bot vai "acordar" para o próximo passo
        # last_action_time = quando a ação foi executada (para outros usos)
        # next_walk_time = quando pode executar o próximo passo (corrige bug de steps duplicados)
        self.last_action_time = time.time()
        self.next_walk_time = time.time() + wait_time
        if DEBUG_PATHFINDING:
            print(f"[{_ts()}] [DEBUG] Set next_walk_time={self.next_walk_time:.3f} (now + {wait_time:.3f}s)")

    def _handle_hard_stuck(self, dest_x, dest_y, dest_z, my_x, my_y):
        """Marca bloqueio no mapa global e força nova rota (Desvio)."""
        self._hard_stuck_count += 1
        print(f"[{_ts()}] [Nav] HARD STUCK! (#{self._hard_stuck_count}) Adicionando bloqueio temporário e recalculando...")

        # Após 3+ hard stucks consecutivos, tentar floor change (bot pode estar preso em sala)
        if self._hard_stuck_count >= 3:
            print(f"[{_ts()}] [Nav] 🔀 {self._hard_stuck_count} hard stucks seguidos — verificando se precisa mudar de andar...")
            # Tentar subir (z-1) e descer (z+1)
            for try_z in [dest_z - 1, dest_z + 1]:
                floor_target = self.analyzer.scan_for_floor_change(
                    try_z, dest_z,
                    player_abs_x=my_x, player_abs_y=my_y,
                    transitions_by_floor=self.global_map._transitions_by_floor if self.global_map else None
                )
                if floor_target:
                    fx, fy, ftype, fid = floor_target
                    dist_obj = math.sqrt(fx**2 + fy**2)
                    print(f"[{_ts()}] [Nav] 🪜 Encontrou {ftype} (ID:{fid}) em ({fx:+d},{fy:+d}) dist={dist_obj:.1f}")
                    if dist_obj <= 1.5:
                        print(f"[{_ts()}] [Nav] 🪜 Adjacente — usando {ftype}!")
                        fc_success = self._handle_special_tile(fx, fy, ftype, fid, my_x, my_y, dest_z)
                        self.current_global_path = []
                        if fc_success:
                            self.last_floor_change_time = time.time()
                        self._hard_stuck_count = 0
                        self.global_recalc_counter = 0
                        return
                    else:
                        # Navegar até o tile especial
                        abs_x = my_x + fx
                        abs_y = my_y + fy
                        path = self.global_map.get_path(
                            (my_x, my_y, dest_z), (abs_x, abs_y, dest_z)
                        )
                        if path:
                            print(f"[{_ts()}] [Nav] 🪜 Navegando até {ftype} em ({abs_x},{abs_y})")
                            self.current_global_path = path
                            self._hard_stuck_count = 0
                            self.global_recalc_counter = 0
                            return

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
            print(f"[{_ts()}] [Nav] 🧱 Adicionando barreira virtual em ({bx}, {by}) por 20s.")
            self.global_map.add_temp_block(bx, by, bz, duration=20)
        else:
            print(f"[{_ts()}] [Nav] ❓ Não foi possível identificar o tile de bloqueio.")

        # Limpa rota para forçar recálculo imediato na próxima volta
        print(f"[{_ts()}] [Nav] 🔄 Forçando recálculo de rota global...")
        if self.current_global_path:
            print(f"[{_ts()}] [DEBUG] Path limpo em: hard_stuck (tinha {len(self.current_global_path)} nós)")
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
            print(f"[{_ts()}] [Cavebot] 🔁 Loop completo! Reiniciando do WP #0")

    def _move_step(self, dx, dy):
        """Envia o pacote de andar."""
        opcode = MOVE_OPCODES.get((dx, dy))
        if opcode:
            self.packet.walk(opcode)
        else:
            print(f"[{_ts()}] [Cavebot] Direção inválida: {dx}, {dy}")

    def _insert_transition_waypoints(self, ml_path):
        """
        Insere waypoints adjacentes aos tiles de transição no path multifloor.
        Isso garante que o bot tenha sub-destinos próximos antes/depois de cada transição,
        evitando oscilação quando o A* retorna paths com gaps grandes após mudança de andar.
        """
        if not ml_path or len(ml_path) < 2:
            return ml_path

        enhanced_path = []

        for i in range(len(ml_path)):
            x, y, z = ml_path[i]
            enhanced_path.append((x, y, z))

            # Check if next node has Z change (transition point)
            if i < len(ml_path) - 1:
                next_x, next_y, next_z = ml_path[i + 1]

                if next_z != z:  # Z changes - this is a transition!
                    # Insert waypoint ADJACENT to transition tile
                    for dx, dy in [(1, 0), (-1, 0), (0, 1), (0, -1)]:
                        adj_x, adj_y = x + dx, y + dy

                        # Check if adjacent tile is walkable (ignore transition blocking)
                        if self.global_map.is_walkable(adj_x, adj_y, z, ignore_transitions=True):
                            # Avoid duplicates with recent nodes
                            recent = enhanced_path[-2:] if len(enhanced_path) >= 2 else enhanced_path
                            if (adj_x, adj_y, z) not in recent:
                                enhanced_path.append((adj_x, adj_y, z))
                                if DEBUG_PATHFINDING:
                                    print(f"[{_ts()}] [Nav] 📍 Waypoint de transição inserido: ({adj_x}, {adj_y}, {z})")
                            break

        return enhanced_path

    def _handle_special_tile(self, rel_x, rel_y, ftype, special_id, px, py, pz):
        """Executa a ação correta para tiles especiais (escadas, buracos, rope)."""
        # Re-check combate antes de executar floor change (race condition com trainer)
        if state.is_in_combat:
            print(f"[{_ts()}] [Cavebot] Abortando floor change ({ftype}) — combate iniciado.")
            return False

        # Aguarda personagem parar antes de interagir com tile especial
        if not wait_until_stopped(self.pm, self.base_addr, packet=self.packet, timeout=1.5):
            if DEBUG_PATHFINDING:
                print(f"[{_ts()}] [Cavebot] ⏳ Aguardando parada para usar {ftype}...")
            return  # Tenta novamente no próximo ciclo

        abs_x = px + rel_x
        abs_y = py + rel_y
        target_pos = get_ground_pos(abs_x, abs_y, pz)
        special_id = special_id or 0

        if ftype in ['UP_WALK', 'DOWN']:
            # Essas escadas/buracos sobem/descem IMEDIATAMENTE ao pisar nelas.
            # O personagem é TELETRANSPORTADO para o novo andar assim que o servidor processa.
            if rel_x != 0 or rel_y != 0:
                # Se diagonal, primeiro alinha para cardinal-adjacente (evita step diagonal unreliable)
                if rel_x != 0 and rel_y != 0:
                    # Verificar qual direção cardinal está walkable
                    tile_x = self.analyzer.get_tile_properties(rel_x, 0)
                    tile_y = self.analyzer.get_tile_properties(0, rel_y)

                    if tile_x.get('walkable', False):
                        self._move_step(rel_x, 0)
                    elif tile_y.get('walkable', False):
                        self._move_step(0, rel_y)
                    else:
                        # Nenhum cardinal walkable, tentar diagonal direto
                        self._move_step(rel_x, rel_y)

                    self.next_walk_time = time.time() + 0.8
                    return  # Próximo ciclo vai pisar no tile cardinalmente
                self._move_step(rel_x, rel_y)
                self.next_walk_time = time.time() + 1.0  # Previne steps duplicados durante floor change
                # CRÍTICO: Aguarda o servidor processar a mudança de andar
                # Sem isso, o próximo ciclo pode enviar comandos baseados na posição antiga
                time.sleep(1)  # Tempo para o servidor processar teleport
            return

        if ftype == 'DOWN_USE':
            # Sewer grate e similares: requer USE para descer
            chebyshev = max(abs(rel_x), abs(rel_y))

            if chebyshev == 0:
                # Já estamos em cima do sewer grate, apenas usa
                print(f"[{_ts()}] [Cavebot] Em cima do sewer grate, executando USE. Chebyshev = {chebyshev}")
                self._use_down_tile(target_pos, special_id, 0, 0)
            elif chebyshev == 1:
                # Adjacente (inclui cardinal e diagonal): usa à distância
                print(f"[{_ts()}] [Cavebot] Adjacente ao sewer grate (cardinal ou diagonal), executando USE à distância. Chebyshev = {chebyshev}")
                self._use_down_tile(target_pos, special_id, rel_x, rel_y)
            else:
                # Mais longe: alinhar para adjacência e tentar novamente
                print(f"[{_ts()}] [Cavebot] Longe do sewer grate (Chebyshev = {chebyshev}), alinhando para adjacência.")
                if not self._ensure_cardinal_adjacent(rel_x, rel_y, label="sewer grate"):
                    return
            return

        if ftype == 'UP_USE':
            chebyshev = max(abs(rel_x), abs(rel_y))
            if chebyshev == 0:
                # Já estamos em cima da ladder, apenas usa.
                print(f"[{_ts()}] [Cavebot] Em cima da ladder, executando USE. Chebyshev = {chebyshev}")
                self._use_ladder_tile(target_pos, special_id, 0, 0)
            elif chebyshev == 1:
                # Adjacente (inclui cardinal e diagonal): usa à distância.
                print(f"[{_ts()}] [Cavebot] Adjacente à ladder (cardinal ou diagonal), executando USE à distância. Chebyshev = {chebyshev}")
                self._use_ladder_tile(target_pos, special_id, rel_x, rel_y)
            else:
                # Mais longe: alinhar para adjacência e tentar novamente.
                print(f"[{_ts()}] [Cavebot] Longe da ladder (Chebyshev = {chebyshev}), alinhando para adjacência.")
                if not self._ensure_cardinal_adjacent(rel_x, rel_y, label="ladder"):
                    return
            return

        if ftype == 'ROPE':
            # Rope EXIGE adjacência - o personagem NÃO pode estar em cima do rope spot
            chebyshev = max(abs(rel_x), abs(rel_y))
            print(f"[{_ts()}] [Cavebot] [ROPE] Iniciando: pos=({px},{py},{pz}) rel=({rel_x},{rel_y}) chebyshev={chebyshev} special_id={special_id}")

            if chebyshev == 0:
                # Estamos EM CIMA do rope spot - precisamos sair para uma posição adjacente
                print(f"[{_ts()}] [Cavebot] ⚠️ Em cima do rope spot! Movendo para posição adjacente...")

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
                        self.next_walk_time = time.time() + 0.5
                        print(f"[{_ts()}] [Cavebot] Movendo para ({adj_dx}, {adj_dy}) para usar rope.")
                        moved = True
                        time.sleep(0.6)
                        # Atualiza posição relativa e absoluta após o movimento
                        rel_x = -adj_dx
                        rel_y = -adj_dy
                        px = px + adj_dx
                        py = py + adj_dy
                        break

                if not moved:
                    print(f"[{_ts()}] [Cavebot] ⚠️ Nenhum tile adjacente livre para sair do rope spot!")
                    return False
                # Continua para usar a rope agora que estamos adjacentes
                print(f"[{_ts()}] [Cavebot] [ROPE] Saiu do rope spot. Nova pos=({px},{py}) rel=({rel_x},{rel_y})")

            if chebyshev > 1:
                # Está longe - precisa se aproximar
                if not self._ensure_cardinal_adjacent(rel_x, rel_y):
                    return False

            # chebyshev == 1: Está adjacente, pode usar a rope
            print(f"[{_ts()}] [Cavebot] [ROPE] Adjacente, preparando uso. rel=({rel_x},{rel_y})")
            rope_source = self._get_rope_source_position()
            if not rope_source:
                print(f"[{_ts()}] [Cavebot] Corda (3003) não encontrada em containers ou mãos.")
                return False

            if not self._clear_rope_spot(rel_x, rel_y, px, py, pz, special_id or 386):
                print(f"[{_ts()}] [Cavebot] [ROPE] _clear_rope_spot retornou False, abortando uso da corda.")
                return False

            # Re-check combate após sleeps (race condition com trainer)
            if state.is_in_combat:
                print(f"[{_ts()}] [Cavebot] Abortando rope — combate iniciado durante preparação.")
                return False

            self.packet.use_with(rope_source, ROPE_ITEM_ID, 0, target_pos, special_id or 386, 0,
                                 rel_x=rel_x, rel_y=rel_y)
            print(f"[{_ts()}] [Cavebot] Ação: USAR CORDA para subir de andar.")
            time.sleep(1)
            return True

        if ftype == 'SHOVEL':
            # Shovel precisa de pá no inventário/equipamento
            if not self._ensure_cardinal_adjacent(rel_x, rel_y, label="shovel"):
                return

            shovel_source = self._get_shovel_source_position()
            if not shovel_source:
                print(f"[{_ts()}] [Cavebot] Pá (3457) não encontrada em containers ou mãos.")
                return

            # Obtém o ID do stone pile no tile
            shovel_tile = self.memory_map.get_tile_visible(rel_x, rel_y)
            if not shovel_tile or shovel_tile.count == 0:
                print(f"[{_ts()}] [Cavebot] Tile do shovel spot não encontrado na memória.")
                return

            top_id = shovel_tile.get_top_item()

            # Valida se o item é um stone pile válido (593, 606, 608)
            from database.tiles_config import FLOOR_CHANGE
            valid_shovel_ids = FLOOR_CHANGE.get('SHOVEL', set())

            if top_id not in valid_shovel_ids:
                print(f"[{_ts()}] [Cavebot] Item {top_id} no shovel spot não é um stone pile válido. Esperado: {valid_shovel_ids}")
                return

            # Usa a pá no stone pile para criar o buraco (593 → 594)
            self.packet.use_with(shovel_source, SHOVEL_ITEM_ID, 0, target_pos, top_id, 0,
                                 rel_x=rel_x, rel_y=rel_y)
            print(f"[{_ts()}] [Cavebot] Ação: USAR PÁ para abrir buraco. (Stone pile ID: {top_id})")

            # Aguarda o servidor processar (stone pile se torna hole)
            time.sleep(1)
            return

    def _use_ladder_tile(self, target_pos, ladder_id, rel_x=0, rel_y=0):
        """Executa o packet de USE na ladder quando estivermos sobre ela."""
        if ladder_id == 0:
            print(f"[{_ts()}] [Cavebot] Ladder sem ID especial, abortando USE.")
            return
        stack_pos = 0
        ladder_tile = self.memory_map.get_tile_visible(rel_x, rel_y)
        if ladder_tile and ladder_tile.items:
            # Procura o stackpos real do ID da ladder (última ocorrência = topo).
            for idx, item_id in enumerate(ladder_tile.items):
                if item_id == ladder_id:
                    stack_pos = idx
        else:
            print(f"[{_ts()}] [Cavebot] Tile da ladder não encontrado na memória, usando stack_pos=0.")

        self.packet.use_item(target_pos, ladder_id, stack_pos=stack_pos)
        print(f"[{_ts()}] [Cavebot] Ação: USAR LADDER (ID: {ladder_id}, target_pos: {target_pos}, rel_x {rel_x}, rel_y {rel_y}, stack_pos: {stack_pos})")
        # CRÍTICO: Aguarda o servidor processar a mudança de andar
        # Ladders teletransportam o jogador assim que o servidor processa
        time.sleep(0.6)

    def _use_down_tile(self, target_pos, tile_id, rel_x=0, rel_y=0):
        """Executa o packet de USE em tiles que descem (sewer grate, etc.)."""
        if tile_id == 0:
            print(f"[{_ts()}] [Cavebot] Sewer grate sem ID especial, abortando USE.")
            return

        stack_pos = 0
        down_tile = self.memory_map.get_tile_visible(rel_x, rel_y)

        if down_tile and down_tile.items:
            # Procura o stackpos real do ID do sewer grate (última ocorrência = topo)
            for idx, item_id in enumerate(down_tile.items):
                if item_id == tile_id:
                    stack_pos = idx
        else:
            print(f"[{_ts()}] [Cavebot] Tile do sewer grate não encontrado na memória, usando stack_pos=0.")

        self.packet.use_item(target_pos, tile_id, stack_pos=stack_pos)
        print(f"[{_ts()}] [Cavebot] Ação: USAR SEWER GRATE (ID: {tile_id}, target_pos: {target_pos}, rel_x {rel_x}, rel_y {rel_y}, stack_pos: {stack_pos})")

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

    def _get_walkable_adjacent_tile(self, special_rel_x, special_rel_y):
        """
        Encontra um tile WALKABLE adjacente a um tile especial (buraco/escada).
        Usado para navegação: A* não pode pathing para tiles non-walkable,
        então navegamos até um tile adjacente e depois pisamos no especial.

        Prioriza:
        1. Tiles cardeais (mais fácil pisar no especial depois)
        2. Tiles mais próximos do player
        3. Tiles diagonais como fallback

        Returns: (rel_x, rel_y) do tile adjacente ou None se nenhum walkable.
        """
        # Cardeais primeiro (preferência para pisar em buracos)
        cardinal = [
            (special_rel_x + 1, special_rel_y),
            (special_rel_x - 1, special_rel_y),
            (special_rel_x, special_rel_y + 1),
            (special_rel_x, special_rel_y - 1),
        ]
        # Diagonais como fallback
        diagonal = [
            (special_rel_x + 1, special_rel_y + 1),
            (special_rel_x + 1, special_rel_y - 1),
            (special_rel_x - 1, special_rel_y + 1),
            (special_rel_x - 1, special_rel_y - 1),
        ]

        best = None
        best_dist = 999

        # Prioridade 1: Cardeais walkable
        for ox, oy in cardinal:
            props = self.analyzer.get_tile_properties(ox, oy)
            if not props['walkable']:
                continue
            dist = abs(ox) + abs(oy)
            if dist < best_dist:
                best_dist = dist
                best = (ox, oy)

        # Prioridade 2: Diagonais walkable (se nenhum cardinal disponível)
        if best is None:
            for ox, oy in diagonal:
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
            print(f"[{_ts()}] [Cavebot] {label.capitalize()} inválido (rel=0,0 - mesmo tile do player).")
            return False

        # Está longe (Chebyshev > 1): tenta se aproximar
        # Prioridade: move primeiro no eixo com maior distância
        if abs(rel_x) > abs(rel_y):
            # X é maior: move em X para chegar perto
            print(f"[{_ts()}] [Cavebot] {label.capitalize()} longe (Chebyshev={chebyshev}), movendo no eixo X...")
            self._move_step(1 if rel_x > 0 else -1, 0)
            self.next_walk_time = time.time() + 0.5  # Previne steps duplicados
        else:
            # Y é maior ou igual: move em Y
            print(f"[{_ts()}] [Cavebot] {label.capitalize()} longe (Chebyshev={chebyshev}), movendo no eixo Y...")
            self._move_step(0, 1 if rel_y > 0 else -1)
            self.next_walk_time = time.time() + 0.5  # Previne steps duplicados

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
            print(f"[{_ts()}] [Cavebot] Tile do rope spot não encontrado na memória.")
            return False

        top_id = tile.get_top_item()
        rope_id = rope_tile_id or 386
        print(f"[{_ts()}] [Cavebot] [ROPE] _clear_rope_spot: top_id={top_id}, rope_id={rope_id}, items={tile.count}")

        if top_id in (0, rope_id):
            return True

        # Ground tiles (cave floor, grass, etc.) don't block rope usage
        if top_id in GROUND_SPEEDS:
            return True

        if top_id == 99:
            print(f"[{_ts()}] [Cavebot] Rope spot bloqueado por criatura/jogador. Não moveremos por enquanto.")
            return False

        # NOVO: Se o item está na lista de exceção (poças, etc.), considera como "limpo"
        if top_id in ROPE_SPOT_IGNORE_IDS:
            print(f"[{_ts()}] [Cavebot] Item {top_id} no rope spot (permitido). Rope pode ser usada.")
            return True

        # Calcula stack_pos do item no topo
        # items[-1] é o topo, e seu índice na pilha é len(items) - 1
        stack_pos = len(tile.items) - 1

        from_pos = get_ground_pos(px + rel_x, py + rel_y, pz)
        drop_pos = get_ground_pos(px, py, pz)
        self.packet.move_item(from_pos, drop_pos, top_id, 1, stack_pos=stack_pos)
        print(f"[{_ts()}] [Cavebot] Movendo item {top_id} (stack_pos={stack_pos}) para liberar rope spot.")
        time.sleep(0.4)
        return True

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
            print(f"[{_ts()}] [ObstacleClear] _attempt_clear_obstacle chamado para rel({rel_x},{rel_y})")

        obstacle = self.analyzer.get_obstacle_type(rel_x, rel_y)
        if DEBUG_OBSTACLE_CLEARING or DEBUG_STACK_CLEARING:
            print(f"[{_ts()}] [ObstacleClear] get_obstacle_type retornou: {obstacle}")

        if not obstacle['clearable']:
            if DEBUG_OBSTACLE_CLEARING or DEBUG_STACK_CLEARING:
                print(f"[{_ts()}] [ObstacleClear] Obstáculo não é clearable, abortando")
            return False

        px, py, pz = get_player_pos(self.pm, self.base_addr)
        target_x, target_y = px + rel_x, py + rel_y

        if obstacle['type'] == 'MOVE':
            if not OBSTACLE_CLEARING_ENABLED:
                if DEBUG_OBSTACLE_CLEARING:
                    print(f"[{_ts()}] [ObstacleClear] OBSTACLE_CLEARING_ENABLED=False, abortando")
                return False
            if DEBUG_OBSTACLE_CLEARING:
                print(f"[{_ts()}] [ObstacleClear] Tipo MOVE detectado, chamando _push_move_item")
            return self._push_move_item(target_x, target_y, pz, rel_x, rel_y, obstacle)

        if obstacle['type'] == 'STACK':
            if not STACK_CLEARING_ENABLED:
                if DEBUG_STACK_CLEARING:
                    print(f"[{_ts()}] [StackClear] STACK_CLEARING_ENABLED=False, abortando")
                return False
            if DEBUG_STACK_CLEARING:
                print(f"[{_ts()}] [StackClear] Tipo STACK detectado, chamando _push_stack_item")
            return self._push_stack_item(target_x, target_y, pz, rel_x, rel_y, obstacle)

        if DEBUG_OBSTACLE_CLEARING or DEBUG_STACK_CLEARING:
            print(f"[{_ts()}] [ObstacleClear] Tipo {obstacle['type']} não suportado")
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
            print(f"[{_ts()}] [ObstacleClear] Mesa em rel({rel_x},{rel_y}) abs({target_x},{target_y})")
            print(f"[{_ts()}] [ObstacleClear] Player em ({px},{py},{pz})")
            print(f"[{_ts()}] [ObstacleClear] Item ID={obstacle['item_id']}, stack_pos={obstacle['stack_pos']}")

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
            print(f"[{_ts()}] [ObstacleClear] Fallback: tentando empurrar para tiles adjacentes à mesa")

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
            print(f"[{_ts()}] [ObstacleClear] Nenhum tile livre encontrado em nenhuma prioridade!")
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
                    print(f"[{_ts()}] [ObstacleClear] ({check_rel_x},{check_rel_y}) - tile vazio/inexistente")
                continue

            # Verificar se tem item bloqueador
            has_blocking = False
            for item_id in tile.items:
                if item_id in MOVE_IDS or item_id in BLOCKING_IDS:
                    if DEBUG_OBSTACLE_CLEARING:
                        print(f"[{_ts()}] [ObstacleClear] ({check_rel_x},{check_rel_y}) - bloqueador {item_id}")
                    has_blocking = True
                    break

            if has_blocking:
                continue

            # Verificar walkability
            dest_props = self.analyzer.get_tile_properties(check_rel_x, check_rel_y)
            if not dest_props['walkable']:
                if DEBUG_OBSTACLE_CLEARING:
                    print(f"[{_ts()}] [ObstacleClear] ({check_rel_x},{check_rel_y}) - não walkable")
                continue

            # Tile válido! Executar movimento
            if DEBUG_OBSTACLE_CLEARING:
                print(f"[{_ts()}] [ObstacleClear] Movendo para ({check_rel_x},{check_rel_y}) abs({dest_x},{dest_y})")

            from_pos = get_ground_pos(target_x, target_y, pz)
            to_pos = get_ground_pos(dest_x, dest_y, pz)

            self.packet.move_item(
                from_pos, to_pos,
                obstacle['item_id'], 1,
                stack_pos=obstacle['stack_pos']
            )

            print(f"[{_ts()}] [Cavebot] 📦 Moveu mesa {obstacle['item_id']} para ({dest_x},{dest_y})")
            # Delay humanizado após mover obstáculo (1s ± 50%)
            gauss_wait(1.0, 50)
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
            print(f"[{_ts()}] [StackClear] Parcel em rel({rel_x},{rel_y}) abs({target_x},{target_y})")
            print(f"[{_ts()}] [StackClear] Player em ({px},{py},{pz})")
            print(f"[{_ts()}] [StackClear] Item ID={obstacle['item_id']}, stack_pos={obstacle['stack_pos']}")

        # ============================================================
        # PRIORIDADE 0: Mover para o pé do player (0, 0)
        # STACK items PODEM ser movidos para o tile do player!
        # ============================================================
        dest_x, dest_y = px, py

        if DEBUG_STACK_CLEARING:
            print(f"[{_ts()}] [StackClear] Tentando mover para pé do player ({dest_x},{dest_y})")

        from_pos = get_ground_pos(target_x, target_y, pz)
        to_pos = get_ground_pos(dest_x, dest_y, pz)

        self.packet.move_item(
            from_pos, to_pos,
            obstacle['item_id'], 1,
            stack_pos=obstacle['stack_pos']
        )

        print(f"[{_ts()}] [Cavebot] 📦 Moveu parcel {obstacle['item_id']} para pé do player ({dest_x},{dest_y})")
        # Delay humanizado após mover obstáculo (1s ± 50%)
        gauss_wait(1.0, 50)
        return True

        # NOTA: Se no futuro a prioridade 0 falhar (ex: height excessivo no tile do player),
        # podemos adicionar fallback usando _try_move_to_tiles() com as prioridades 1-4.
        # Por agora, mover para (0,0) é sempre válido para parcels.

    def _check_stuck(self, px, py, pz, current_index=None, mode="waypoint"):
        """
        Detecta se o player está travado.
        Usa is_player_moving como fonte primária de detecção.

        Args:
            mode: "waypoint" = pula para próximo waypoint
                  "auto_explore" = pula spawn atual

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
                print(f"[{_ts()}] [Cavebot] ⚠️ Parado há {self.stuck_counter} ciclos (is_moving=False)")

            if self.stuck_counter >= self.stuck_threshold:
                stuck_time = self.stuck_counter * self.walk_delay
                self.current_state = self.STATE_STUCK

                if mode == "auto_explore":
                    # Estratégia de recuperação: Pula spawn atual
                    self.state_message = f"🧱 Stuck! Pulando spawn"
                    print(f"[{_ts()}] [AutoExplore] ⚠️ STUCK! {stuck_time:.1f}s parado ({px}, {py}, {pz}). Pulando spawn.")
                    if self._current_spawn_target and self._spawn_selector:
                        self._spawn_selector.skip_spawn(self._current_spawn_target, "stuck", (px, py, pz))
                        self._current_spawn_target = None
                    if self.current_global_path:
                        print(f"[{_ts()}] [DEBUG] Path limpo em: check_stuck_explore (tinha {len(self.current_global_path)} nós)")
                    self.current_global_path = []
                else:
                    # Estratégia de recuperação: Pula para próximo waypoint
                    self.state_message = f"🧱 Stuck! Pulando WP #{current_index + 1 if current_index is not None else '?'}"
                    print(f"[{_ts()}] [Cavebot] ⚠️ STUCK! {stuck_time:.1f}s parado ({px}, {py}, {pz})")
                    with self._waypoints_lock:
                        if len(self._waypoints) > 1:
                            print(f"[{_ts()}] [Cavebot] Pulando para próximo waypoint...")
                            self._advance_waypoint()
                            if self.current_global_path:
                                print(f"[{_ts()}] [DEBUG] Path limpo em: check_stuck (tinha {len(self.current_global_path)} nós)")
                            self.current_global_path = []

                self.stuck_counter = 0
        else:
            # Posição mudou (mesmo que is_moving=False agora) - não está stuck
            self.stuck_counter = 0
            self.last_known_pos = current_pos

    # =========================================================================
    # OSCILLATION DETECTION: Detecção de movimento "vai e volta"
    # =========================================================================

    def _detect_oscillation(self, dx, dy) -> bool:
        """
        Detecta padrão de oscilação nos últimos passos.
        Retorna True se o passo atual criaria oscilação.

        Padrão detectado (threshold=3):
        - [+1, -1, +1] no eixo X ou Y
        - Ou seja, 3 alternâncias consecutivas
        """
        if not OSCILLATION_DETECTION_ENABLED:
            return False

        threshold = OSCILLATION_THRESHOLD
        if len(self._step_history) < threshold - 1:
            return False

        # Verifica eixo X
        x_pattern = [s[0] for s in self._step_history[-(threshold-1):]] + [dx]
        if self._is_alternating(x_pattern, threshold):
            return True

        # Verifica eixo Y
        y_pattern = [s[1] for s in self._step_history[-(threshold-1):]] + [dy]
        if self._is_alternating(y_pattern, threshold):
            return True

        return False

    def _is_alternating(self, values, threshold=3) -> bool:
        """Verifica se valores alternam entre positivo e negativo."""
        if len(values) < threshold:
            return False

        # Remove zeros (passos que não são nesse eixo)
        non_zero = [v for v in values if v != 0]
        if len(non_zero) < threshold:
            return False

        # Verifica alternância: sign muda a cada passo
        for i in range(1, len(non_zero)):
            if non_zero[i] * non_zero[i-1] >= 0:  # Mesmo sinal ou zero
                return False

        return True

    def _handle_oscillation(self, dx, dy):
        """
        Chamado quando oscilação é detectada.
        Aplica estratégia de recuperação em 3 níveis:
        1. Passo perpendicular
        2. Bloqueio temporário + recalc
        3. Skip waypoint/spawn (última opção)
        """
        self._oscillation_skip_count += 1
        print(f"[{_ts()}] [Cavebot] ⚠️ OSCILAÇÃO DETECTADA! (tentativa {self._oscillation_skip_count}/{OSCILLATION_MAX_ATTEMPTS})")
        print(f"[{_ts()}] [Cavebot]    Últimos passos: {self._step_history[-3:]}")

        # Estratégia 3: Após N tentativas, SKIP para próximo waypoint/spawn
        if self._oscillation_skip_count >= OSCILLATION_MAX_ATTEMPTS:
            print(f"[{_ts()}] [Cavebot] ⏭️ Oscilação persistente! Pulando para próximo destino.")
            self._oscillation_skip_count = 0
            self._step_history.clear()
            self.current_global_path = []
            self.local_path_cache = []

            if self.auto_explore_enabled and self._current_spawn_target:
                # Skip spawn no auto-explore
                if self._spawn_selector:
                    px, py, pz = get_player_pos(self.pm, self.base_addr)
                    self._spawn_selector.skip_spawn(
                        self._current_spawn_target,
                        "oscilação persistente",
                        (px, py, pz)
                    )
                self._current_spawn_target = None
                print(f"[{_ts()}] [Cavebot] ⏭️ Spawn pulado, selecionando próximo...")
            else:
                # Skip waypoint no modo normal
                with self._waypoints_lock:
                    if len(self._waypoints) > 1:
                        old_idx = self._current_index
                        self._advance_waypoint()
                        print(f"[{_ts()}] [Cavebot] ⏭️ Waypoint #{old_idx} → #{self._current_index}")
            return

        # Estratégia 1: Tentar passo perpendicular
        perpendicular_steps = self._get_perpendicular_steps(dx, dy)
        for perp_dx, perp_dy in perpendicular_steps:
            props = self.analyzer.get_tile_properties(perp_dx, perp_dy)
            if props['walkable']:
                print(f"[{_ts()}] [Cavebot] 🔄 Tentando passo perpendicular: ({perp_dx}, {perp_dy})")
                self._step_history.clear()  # Limpa histórico
                self._move_step(perp_dx, perp_dy)
                self.next_walk_time = time.time() + 0.5  # Delay para estabilizar
                return

        # Estratégia 2: Se não há perpendicular, aplicar bloqueio e recalcular
        print(f"[{_ts()}] [Cavebot] 🔄 Forçando recálculo com bloqueio temporário")

        # Bloqueia o tile na direção oposta ao último passo
        if self._step_history:
            last_dx, last_dy = self._step_history[-1]
            px, py, pz = get_player_pos(self.pm, self.base_addr)
            block_x = px - last_dx  # Tile de onde veio
            block_y = py - last_dy
            self.global_map.add_temp_block(block_x, block_y, pz, duration=30)
            print(f"[{_ts()}] [Cavebot] 🧱 Bloqueio temporário em ({block_x}, {block_y}) por 30s")

        # Limpa tudo para forçar nova rota
        self._step_history.clear()
        self.current_global_path = []
        self.local_path_cache = []
        self.global_recalc_counter = 0

    def _get_perpendicular_steps(self, dx, dy):
        """Retorna passos perpendiculares ao movimento atual."""
        if dx != 0:  # Movimento horizontal → tenta vertical
            return [(0, 1), (0, -1)]
        elif dy != 0:  # Movimento vertical → tenta horizontal
            return [(1, 0), (-1, 0)]
        return []

    def _is_opposite_direction(self, dx, dy) -> bool:
        """
        Verifica se o passo atual é na direção oposta ao último passo.
        Usado para humanização: adicionar delay extra ao inverter direção.

        Exemplos de direções opostas:
        - (0, -1) Norte → (0, +1) Sul = OPOSTO
        - (+1, 0) Leste → (-1, 0) Oeste = OPOSTO
        - (+1, -1) NE → (-1, +1) SW = OPOSTO (diagonal inversa)

        NÃO são opostas (apenas 90° ou similar):
        - (0, -1) Norte → (+1, 0) Leste
        - (+1, 0) Leste → (+1, -1) NE
        """
        if not self._step_history:
            return False

        last_dx, last_dy = self._step_history[-1]

        # Direção oposta: sinais invertidos em AMBOS os eixos (ou zero em um)
        # Para cardinal: um eixo é 0, o outro inverte
        # Para diagonal: ambos invertem

        x_opposite = (last_dx != 0 and dx == -last_dx) or (last_dx == 0 and dx == 0)
        y_opposite = (last_dy != 0 and dy == -last_dy) or (last_dy == 0 and dy == 0)

        # Pelo menos um eixo deve ter invertido (não apenas zeros)
        has_inversion = (last_dx != 0 and dx == -last_dx) or (last_dy != 0 and dy == -last_dy)

        return x_opposite and y_opposite and has_inversion

    def _record_step(self, dx, dy):
        """Registra um passo no histórico de oscilação."""
        self._step_history.append((dx, dy))
        if len(self._step_history) > self._step_history_max:
            self._step_history.pop(0)
        # Reset contador de skip se passo foi bem sucedido
        self._oscillation_skip_count = 0

    # =========================================================================
    # HUMANIZAÇÃO: Detecção de Falta de Progresso
    # =========================================================================

    def _handle_no_progress(self, px, py, pz, wp):
        """
        Chamado quando detectamos que não estamos avançando ao waypoint.
        Identifica causa e aplica resposta humanizada.
        """
        # Cooldown entre respostas (evita spam de ações)
        if time.time() - self.no_progress_response_time < 3.0:
            return

        # 1. Verificar se há player adjacente (1 tile)
        nearby_player = self._find_adjacent_player(px, py, pz)

        if nearby_player:
            # Player é provavelmente a causa
            self._respond_to_player_blocking(nearby_player, px, py, pz, wp)
        else:
            # Outra causa (pathing ruim, obstáculo, etc)
            self._respond_to_general_stuck(px, py, pz, wp)

        self.no_progress_response_time = time.time()

    def _find_adjacent_player(self, px, py, pz):
        """
        Retorna player adjacente (1 tile de distância Chebyshev) ou None.
        """
        scanner = BattleListScanner(self.pm, self.base_addr)
        player_id = state.get_player_id(self.pm, self.base_addr)
        players = scanner.get_players(exclude_self_id=player_id)

        for player in players:
            if player.position.z != pz:
                continue
            # Distância Chebyshev (máximo de dx e dy)
            dist = max(abs(player.position.x - px), abs(player.position.y - py))
            if dist <= 1:  # Adjacente
                return player
        return None

    def _respond_to_player_blocking(self, player, px, py, pz, wp):
        """
        Resposta humanizada quando player está bloqueando.
        Escolhe aleatoriamente entre: WAIT, AVOID, SKIP
        """
        response = random.choices(
            ['WAIT', 'AVOID', 'SKIP'],
            weights=[0.6, 0.3, 0.1]  # 60% esperar, 30% desviar, 10% pular
        )[0]

        info = self.advancement_tracker.get_advancement_info()
        if DEBUG_ADVANCEMENT or DEBUG_PATHFINDING:
            if info['mode'] == 'nodes':
                print(f"[{_ts()}] [Cavebot] ⚠️ Sem progresso! Modo: nodes, taxa: {info['node_rate']:.2f} nodes/s")
            else:
                print(f"[{_ts()}] [Cavebot] ⚠️ Sem progresso! Modo: distância, taxa: {info['distance_rate']:.2f} SQM/s")
            print(f"[{_ts()}] [Cavebot] Player '{player.name}' adjacente em ({player.position.x}, {player.position.y}). Resposta: {response}")

        if response == 'WAIT':
            # Ficar parado 1-4 segundos (gaussiano)
            min_wait, max_wait = PLAYER_BLOCK_WAIT_RANGE
            wait_time = random.gauss((min_wait + max_wait) / 2, (max_wait - min_wait) / 4)
            wait_time = max(min_wait, min(max_wait, wait_time))

            self.current_state = self.STATE_PAUSED
            self.state_message = f"⏸️ Aguardando player passar ({wait_time:.1f}s)"
            print(f"[{_ts()}] [Cavebot] ⏸️ Aguardando player '{player.name}' passar ({wait_time:.1f}s)")

            time.sleep(wait_time)
            # Após esperar, limpa o tracker para dar nova chance
            self.advancement_tracker.reset()

        elif response == 'AVOID':
            # Aplicar peso 2x nos tiles do player para A* preferir desviar
            self._set_player_avoidance(player.position.x, player.position.y, px, py)
            # Limpar cache para forçar recálculo de rota
            self.local_path_cache = []
            if self.current_global_path:
                print(f"[{_ts()}] [DEBUG] Path limpo em: player_avoid (tinha {len(self.current_global_path)} nós)")
            self.current_global_path = []
            print(f"[{_ts()}] [Cavebot] 🔄 Tentando desviar de '{player.name}' (peso 2x nos tiles adjacentes)")

        elif response == 'SKIP':
            # Pular para próximo waypoint
            print(f"[{_ts()}] [Cavebot] ⏭️ Pulando WP #{self._current_index} devido a bloqueio por '{player.name}'")
            with self._waypoints_lock:
                self._advance_waypoint()
                if self.current_global_path:
                    print(f"[{_ts()}] [DEBUG] Path limpo em: player_skip (tinha {len(self.current_global_path)} nós)")
                self.current_global_path = []
            self.advancement_tracker.reset()

    def _respond_to_general_stuck(self, px, py, pz, wp):
        """
        Resposta quando não há player adjacente mas não estamos avançando.
        Provavelmente pathing ruim ou obstáculo não detectado.
        """
        info = self.advancement_tracker.get_advancement_info()
        if DEBUG_ADVANCEMENT or DEBUG_PATHFINDING:
            if info['mode'] == 'nodes':
                print(f"[{_ts()}] [Cavebot] ⚠️ Sem progresso (sem player). Modo: nodes, taxa: {info['node_rate']:.2f} nodes/s")
            else:
                print(f"[{_ts()}] [Cavebot] ⚠️ Sem progresso (sem player). Modo: distância, taxa: {info['distance_rate']:.2f} SQM/s")

        # Limpar player avoidance (pode ter sido setado anteriormente)
        self.analyzer.clear_player_avoidance()

        # Forçar recálculo de rota global
        if self.current_global_path:
            print(f"[{_ts()}] [DEBUG] Path limpo em: general_stuck (tinha {len(self.current_global_path)} nós)")
        self.current_global_path = []
        self.local_path_cache = []
        self.global_recalc_counter += 1

        # Reseta tracker para dar nova chance
        self.advancement_tracker.reset()

    def _set_player_avoidance(self, player_x, player_y, my_x, my_y):
        """
        Configura o MapAnalyzer para penalizar tiles próximos do player.
        """
        # Define referência de posição para conversão rel -> abs
        self.analyzer.set_player_reference(my_x, my_y)
        # Define penalidade nos tiles do player e adjacentes
        self.analyzer.set_player_avoidance(player_x, player_y)

    # ==================================================================
    # AUTO-EXPLORE: Respostas a falta de progresso
    # ==================================================================

    def _handle_no_progress_explore(self, px, py, pz, spawn):
        """
        Chamado quando não estamos avançando ao spawn no auto-explore.
        Identifica causa e aplica resposta humanizada.
        """
        if time.time() - self.no_progress_response_time < 3.0:
            return

        nearby_player = self._find_adjacent_player(px, py, pz)

        if nearby_player:
            self._respond_to_player_blocking_explore(nearby_player, px, py, pz, spawn)
        else:
            self._respond_to_general_stuck_explore(px, py, pz, spawn)

        self.no_progress_response_time = time.time()

    def _respond_to_player_blocking_explore(self, player, px, py, pz, spawn):
        """
        Resposta humanizada quando player está bloqueando no auto-explore.
        Escolhe aleatoriamente entre: WAIT, AVOID, SKIP
        """
        response = random.choices(
            ['WAIT', 'AVOID', 'SKIP'],
            weights=[0.6, 0.3, 0.1]  # 60% esperar, 30% desviar, 10% pular
        )[0]

        if DEBUG_ADVANCEMENT or DEBUG_AUTO_EXPLORE:
            info = self.advancement_tracker.get_advancement_info()
            if info['mode'] == 'nodes':
                print(f"[{_ts()}] [AutoExplore] Sem progresso! Modo: nodes, taxa: {info['node_rate']:.2f} nodes/s")
            else:
                print(f"[{_ts()}] [AutoExplore] Sem progresso! Modo: distância, taxa: {info['distance_rate']:.2f} SQM/s")
            print(f"[{_ts()}] [AutoExplore] Player '{player.name}' adjacente em ({player.position.x}, {player.position.y}). Resposta: {response}")

        if response == 'WAIT':
            min_wait, max_wait = PLAYER_BLOCK_WAIT_RANGE
            wait_time = random.gauss((min_wait + max_wait) / 2, (max_wait - min_wait) / 4)
            wait_time = max(min_wait, min(max_wait, wait_time))

            self.current_state = self.STATE_PAUSED
            self.state_message = f"⏸️ Aguardando player passar ({wait_time:.1f}s)"
            print(f"[{_ts()}] [AutoExplore] ⏸️ Aguardando player '{player.name}' passar ({wait_time:.1f}s)")

            time.sleep(wait_time)
            self.advancement_tracker.reset()

        elif response == 'AVOID':
            self._set_player_avoidance(player.position.x, player.position.y, px, py)
            self.local_path_cache = []
            if self.current_global_path:
                print(f"[{_ts()}] [DEBUG] Path limpo em: player_avoid_explore (tinha {len(self.current_global_path)} nós)")
            self.current_global_path = []
            print(f"[{_ts()}] [AutoExplore] Tentando desviar de '{player.name}' (peso 2x nos tiles adjacentes)")

        elif response == 'SKIP':
            print(f"[{_ts()}] [AutoExplore] Pulando spawn devido a bloqueio por '{player.name}'")
            self._spawn_selector.skip_spawn(spawn, f"bloqueado por {player.name}", (px, py, pz), cooldown_override=600)
            self._current_spawn_target = None
            if self.current_global_path:
                print(f"[{_ts()}] [DEBUG] Path limpo em: player_skip_explore (tinha {len(self.current_global_path)} nós)")
            self.current_global_path = []
            self.advancement_tracker.reset()

    def _respond_to_general_stuck_explore(self, px, py, pz, spawn):
        """
        Resposta quando sem progresso e sem player adjacente no auto-explore.
        Provavelmente pathing ruim ou obstáculo não detectado.
        """
        info = self.advancement_tracker.get_advancement_info()
        if DEBUG_ADVANCEMENT or DEBUG_AUTO_EXPLORE:
            if info['mode'] == 'nodes':
                print(f"[{_ts()}] [AutoExplore] Sem progresso (sem player). Modo: nodes, taxa: {info['node_rate']:.2f} nodes/s")
            else:
                print(f"[{_ts()}] [AutoExplore] Sem progresso (sem player). Modo: distância, taxa: {info['distance_rate']:.2f} SQM/s")

        self.analyzer.clear_player_avoidance()

        if self.current_global_path:
            print(f"[{_ts()}] [DEBUG] Path limpo em: general_stuck_explore (tinha {len(self.current_global_path)} nós)")
        self.current_global_path = []
        self.local_path_cache = []
        self.global_recalc_counter += 1

        self.advancement_tracker.reset()
