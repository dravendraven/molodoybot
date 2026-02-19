import time
import random
import struct
import win32gui

from utils.timing import gauss_wait
from core.packet import PacketManager, get_container_pos, get_ground_pos
from core.packet_mutex import PacketMutex
from config import *
from core.map_core import get_player_pos
from core.memory_map import MemoryMap
from database import corpses
from database.creature_outfits import is_humanoid_creature

# CORREÇÃO: Importar scan_containers do local original (auto_loot.py)
from modules.auto_loot import scan_containers
from core.player_core import get_connected_char_name, get_player_id
from core.bot_state import state
from core.game_state import game_state
from core.config_utils import make_config_getter
from core.map_analyzer import MapAnalyzer
from core.astar_walker import AStarWalker
from core.battlelist import BattleListScanner, SpawnTracker
from core.models import Position
from core.overlay_renderer import renderer as overlay_renderer

# Definições de Delay (Throttle Dinâmico)
SCAN_DELAY_COMBAT = 0.1      # Em combate: scan máximo
SCAN_DELAY_TARGETS = 0.2     # Tem alvos disponíveis: scan médio
SCAN_DELAY_IDLE = 0.4        # Sem alvos: scan lento

# Retargeting Configuration
RETARGET_DELAY = 1.0  # Segundos para aguardar antes de retargetar alvo inacessível
REACHABILITY_CHECK_INTERVAL = 1.0  # Frequência de verificação de acessibilidade

# Scan Adaptativo (Early-Exit)
INVALID_SLOT_THRESHOLD = 15  # Slots inválidos consecutivos para parar scan

# Cálculo de Distância
# True = usa A* (considera obstáculos, mais preciso, mais CPU)
# False = usa Manhattan simples (ignora obstáculos, mais rápido)
USE_PATHFINDING_DISTANCE = True

# Range de Combate (distância para deferir dano)
# 1 = melee (armas corpo-a-corpo)
# Diferente de 'range' da config que é a distância para ACIONAR o ataque
MELEE_RANGE = 1


# ==============================================================================
# FUNÇÕES DE CONVERSÃO: Creature -> Dict (Backward Compatibility)
# ==============================================================================

def creature_to_candidate_dict(creature, my_x, my_y, trigger_range, visual_line, is_attacking_me=False):
    """
    Converte Creature (core.models) para dict no formato esperado pelo trainer.
    Mantém backward compatibility com EngagementDetector e lógica de retargeting.
    """
    dist_x = abs(my_x - creature.position.x)
    dist_y = abs(my_y - creature.position.y)
    return {
        "id": creature.id,
        "name": creature.name,
        "hp": creature.hp_percent,
        "dist_x": dist_x,
        "dist_y": dist_y,
        "abs_x": creature.position.x,
        "abs_y": creature.position.y,
        "z": creature.position.z,
        "is_in_range": (dist_x <= trigger_range and dist_y <= trigger_range),
        "line": visual_line,
        "is_attacking_me": is_attacking_me
    }


def creature_to_entity_dict(creature):
    """
    Converte Creature para dict usado em KS detection (all_visible_entities).
    """
    return {
        'id': creature.id,
        'name': creature.name,
        'abs_x': creature.position.x,
        'abs_y': creature.position.y,
        'hp': creature.hp_percent,
        'is_player': creature.is_player
    }


def update_trainer_overlay(all_creatures, my_x, my_y, my_z, current_target_id, my_name):
    """
    Atualiza overlay de debug com informações das criaturas visíveis.
    Exibe: vis, hp%, distância, is_attacking_player acima de cada criatura.

    Ativado via XRAY_TRAINER_DEBUG no config.py.
    """
    if not XRAY_TRAINER_DEBUG:
        overlay_renderer.unregister_layer('trainer')
        return

    overlay_data = []
    for creature in all_creatures:
        # Skip próprio personagem
        if creature.name == my_name:
            continue

        # Skip se não está visível ou em outro andar
        if not creature.is_visible or creature.position.z != my_z:
            continue

        dx = creature.position.x - my_x
        dy = creature.position.y - my_y
        dist = max(abs(dx), abs(dy))  # Chebyshev distance

        # Cor diferente para target atual
        color = '#FF4444' if creature.id == current_target_id else '#FFFF00'

        # Calcula is_attacking_player
        is_attacking = 1 if creature.is_attacking_player() else 0

        overlay_data.append({
            'type': 'creature_info',
            'dx': dx,
            'dy': dy,
            'text': f"hp:{creature.hp_percent}% d:{dist} is_attacking={is_attacking}",
            'color': color,
            'offset_y': -25  # Pixels acima da criatura
        })

    overlay_renderer.register_layer('trainer', overlay_data)


# ==============================================================================
# DEPRECATED: Funções mantidas para backward compatibility
# Usar BattleListScanner para novos desenvolvimentos
# ==============================================================================

# DEPRECATED: Usar BattleListScanner._parse_creature()
def parse_creature_from_bytes(raw_bytes):
    """
    Parseia dados de uma criatura a partir de um bloco de bytes (batch read).
    Reduz de 7 syscalls para 1 por criatura.

    Returns:
        dict com id, name, x, y, z, hp, visible, is_player ou None se inválido
    """
    try:
        # ID está no offset 0 (4 bytes, little-endian int)
        c_id = struct.unpack_from('<I', raw_bytes, 0)[0]
        if c_id <= 0:
            return None

        # Nome: offset 4, até 32 bytes, null-terminated
        name_bytes = raw_bytes[OFFSET_NAME:OFFSET_NAME + 32]
        name = name_bytes.split(b'\x00')[0].decode('latin-1', errors='ignore').strip()

        # Coordenadas e stats (little-endian ints)
        cx = struct.unpack_from('<i', raw_bytes, OFFSET_X)[0]
        cy = struct.unpack_from('<i', raw_bytes, OFFSET_Y)[0]
        z = struct.unpack_from('<i', raw_bytes, OFFSET_Z)[0]
        hp = struct.unpack_from('<i', raw_bytes, OFFSET_HP)[0]
        visible = struct.unpack_from('<i', raw_bytes, OFFSET_VISIBLE)[0]

        # Outfit (para diferenciar players de criaturas)
        outfit_type = struct.unpack_from('<I', raw_bytes, OFFSET_OUTFIT_TYPE)[0]
        outfit_head = struct.unpack_from('<I', raw_bytes, OFFSET_OUTFIT_HEAD)[0]
        outfit_body = struct.unpack_from('<I', raw_bytes, OFFSET_OUTFIT_BODY)[0]
        outfit_legs = struct.unpack_from('<I', raw_bytes, OFFSET_OUTFIT_LEGS)[0]
        outfit_feet = struct.unpack_from('<I', raw_bytes, OFFSET_OUTFIT_FEET)[0]

        # NPCs have bit 31 set in their creature ID (0x80000000+)
        is_npc = (c_id & 0x80000000) != 0

        has_colors = (outfit_head + outfit_body + outfit_legs + outfit_feet) > 0

        # Dupla validação: outfit + nome devem bater para ser criatura humanoid
        # Isso evita que criaturas como Amazon/Hunter sejam detectadas como players
        # E também detecta players disfarçados com outfit de criatura
        is_known_humanoid = is_humanoid_creature(name, outfit_type, outfit_head, outfit_body, outfit_legs, outfit_feet)

        # Player = tem cores E NÃO é criatura humanoid conhecida E NÃO é NPC
        is_player = has_colors and not is_known_humanoid and not is_npc

        return {
            'id': c_id,
            'name': name,
            'x': cx,
            'y': cy,
            'z': z,
            'hp': hp,
            'visible': visible,
            'is_player': is_player,
            'is_npc': is_npc
        }
    except:
        return None

# DEPRECATED: BattleListScanner já faz validação interna (Creature.is_valid)
def is_valid_creature_slot(creature):
    """
    DEPRECATED: Use BattleListScanner - validação é feita internamente.

    Validação robusta de slot de criatura para Scan Adaptativo.
    Verifica múltiplos campos para evitar falsos positivos com "sujeira" na memória.

    Returns:
        True se o slot contém dados válidos de uma criatura
    """
    if creature is None:
        return False

    # HP deve estar entre 0-100 (percentual)
    if creature['hp'] < 0 or creature['hp'] > 100:
        return False

    # Visible deve ser 0 ou 1
    if creature['visible'] not in (0, 1):
        return False

    # Nome deve ter pelo menos 1 caractere
    if len(creature['name']) == 0:
        return False

    # Z (andar) deve estar em range válido (0-15 no Tibia)
    if creature['z'] < 0 or creature['z'] > 15:
        return False

    return True

def steps_to_adjacent(dx, dy, attack_range=1):
    """
    Calcula passos Manhattan até o tile adjacente mais próximo.

    No Tibia, movimento diagonal custa 3x mais tempo que cardinal.
    Por isso, sempre preferimos caminhar em passos cardinais.

    Args:
        dx, dy: Distância relativa ao alvo (pode ser negativo)
        attack_range: Alcance de ataque (default 1 = melee)

    Returns:
        Número de passos cardinais até posição de ataque
    """
    steps_x = max(0, abs(dx) - attack_range)
    steps_y = max(0, abs(dy) - attack_range)
    return steps_x + steps_y

def get_adjacent_target(rel_x, rel_y, attack_range=1):
    """
    Calcula o tile adjacente mais próximo ao alvo.

    O A* vai ATÉ o destino, não para no adjacente.
    Por isso precisamos calcular o tile adjacente primeiro.

    Args:
        rel_x, rel_y: Posição relativa do ALVO
        attack_range: Alcance de ataque

    Returns:
        (target_x, target_y): Tile adjacente mais próximo para onde devemos ir
    """
    # Se já está adjacente (Chebyshev <= attack_range)
    if abs(rel_x) <= attack_range and abs(rel_y) <= attack_range:
        return (0, 0)

    # Calcula tile adjacente na direção do alvo
    if abs(rel_x) > attack_range:
        target_x = rel_x - attack_range if rel_x > 0 else rel_x + attack_range
    else:
        target_x = 0  # Já está dentro do range nesse eixo

    if abs(rel_y) > attack_range:
        target_y = rel_y - attack_range if rel_y > 0 else rel_y + attack_range
    else:
        target_y = 0

    return (target_x, target_y)

def get_bot_path_cost(walker, rel_x, rel_y, attack_range=1):
    """
    Calcula custo real de movimento do bot via A* até tile adjacente.
    Considera obstáculos e penalidade de diagonal (30 vs 10).

    Returns:
        Custo em unidades, ou float('inf') se sem caminho
    """
    # Calcula tile adjacente (onde precisamos chegar para atacar)
    target_x, target_y = get_adjacent_target(rel_x, rel_y, attack_range)

    if target_x == 0 and target_y == 0:
        return 0  # Já está adjacente

    path = walker.get_full_path(target_x, target_y)
    if not path:
        return float('inf')
    return sum(30 if dx != 0 and dy != 0 else 10 for dx, dy in path)

def get_distance_cost(walker, rel_x, rel_y, attack_range=1):
    """
    Calcula custo de movimento até posição de ataque.

    Usa A* ou Manhattan dependendo de USE_PATHFINDING_DISTANCE.

    Returns:
        Custo em unidades (escala 10 = 1 passo cardinal)
    """
    if USE_PATHFINDING_DISTANCE and walker:
        return get_bot_path_cost(walker, rel_x, rel_y, attack_range)
    else:
        # Manhattan simples: passos até adjacente * 10
        return steps_to_adjacent(rel_x, rel_y, attack_range) * 10

def get_my_char_name(pm, base_addr):
    """
    Retorna o nome do personagem usando BotState.
    Evita buscar na BattleList toda vez.
    """
    # Usa cache do BotState (thread-safe)
    if not state.char_name:
        name = get_connected_char_name(pm, base_addr)
        if name:
            state.char_name = name
            # Também setar o char_id
            try:
                player_id = get_player_id(pm, base_addr)
                if player_id and player_id > 0:
                    state.char_id = player_id
            except:
                pass
    return state.char_name

def open_corpse_via_packet(pm, base_addr, target_data, player_id, log_func=print, packet=None):
    """
    Localiza o corpo via memória e abre no próximo slot de container livre.
    """
    try:
        # Cria PacketManager se não foi passado
        if packet is None:
            packet = PacketManager(pm, base_addr)

        # 1. Validação do ID
        monster_name = target_data["name"]
        corpse_id = corpses.get_corpse_id(monster_name)
        if corpse_id == 0:
            log_func(f"⚠️ Corpo desconhecido para: {monster_name}")
            return False

        # 2. Leitura do Mapa
        mapper = MemoryMap(pm, base_addr)
        if not mapper.read_full_map(player_id):
            return False

        # 3. Posição Relativa
        my_x, my_y, my_z = get_player_pos(pm, base_addr)
        target_x = target_data["abs_x"]
        target_y = target_data["abs_y"]
        target_z = target_data["z"]

        dx = target_x - my_x
        dy = target_y - my_y

        tile = mapper.get_tile_visible(dx, dy)
        if not tile:
            log_func(f"⚠️ Tile do corpo fora do alcance ({dx}, {dy}).")
            return False

        # 4. Encontra StackPos
        found_stack_pos = -1
        # Itera de trás para frente para pegar o topo da pilha
        for i in range(len(tile.items) - 1, -1, -1):
            item_id = tile.items[i]
            if item_id == corpse_id:
                found_stack_pos = i 
                break
        
        if found_stack_pos != -1:
            pos_dict = {'x': target_x, 'y': target_y, 'z': target_z}
            
            # 5. CÁLCULO INTELIGENTE DO INDEX
            # Lê containers atuais para saber onde abrir
            try:
                open_containers = scan_containers(pm, base_addr)
                num_open = len(open_containers)
            except Exception as e:
                log_func(f"⚠️ Erro ao escanear containers: {e}")
                num_open = 1 # Fallback seguro (vai abrir no idx 1 se scan falhar)
            
            # Define o índice alvo como o próximo slot disponível
            # Ex: Se tenho 2 containers (0 e 1), abro no 2.
            target_index = num_open
            
            # Limite de segurança do cliente
            if target_index > 15: target_index = 15 
            
            # Envia packet usando o índice calculado
            with PacketMutex("trainer"):
                packet.use_item(pos_dict, corpse_id, found_stack_pos, index=target_index)
            return True
            
        else:
            log_func(f"⚠️ Corpo ID {corpse_id} não encontrado no chão.")
            return False

    except Exception as e:
        log_func(f"🔥 Erro OpenCorpse: {e}")
        return False

def find_nearest_reachable_target(candidates, my_x, my_y, walker, attack_range=1, current_id=0):
    """
    Encontra o alvo acessível mais próximo da lista de candidatos.

    Args:
        candidates: Lista de dicts de candidatos válidos
        my_x, my_y: Posição absoluta do player
        walker: AStarWalker para calcular custo real
        attack_range: Alcance de ataque
        current_id: ID do alvo atual para excluir

    Returns:
        Dict do candidato mais próximo ou None
    """
    # Filtra: no alcance, vivo, não é o alvo atual
    valid = [c for c in candidates
             if c["is_in_range"] and c["hp"] > 0 and c["id"] != current_id]

    if not valid:
        return None

    # Ordena por custo de caminho (A* ou Manhattan dependendo de USE_PATHFINDING_DISTANCE)
    valid.sort(key=lambda c: get_distance_cost(walker, c["abs_x"] - my_x, c["abs_y"] - my_y, attack_range))

    return valid[0]

class EngagementDetector:
    """Detecta se criaturas estão engajadas com outros players via distância relativa e HP tracking."""

    # Limites para prevenir memory leak
    MAX_HISTORY_SIZE = 100  # Máximo de creature_ids no histórico
    DEAD_CREATURE_TTL = 30.0  # Segundos para manter criatura morta no histórico

    def __init__(self):
        self.hp_history = {}  # {creature_id: [(timestamp, hp), ...]}

    def update_hp(self, creature_id, hp):
        """Atualiza histórico de HP com timestamp."""
        now = time.time()
        if creature_id not in self.hp_history:
            self.hp_history[creature_id] = []

        # Limpa histórico antigo (> KS_HISTORY_DURATION segundos)
        cutoff = now - KS_HISTORY_DURATION
        self.hp_history[creature_id] = [
            (ts, h) for ts, h in self.hp_history[creature_id]
            if ts > cutoff
        ]
        self.hp_history[creature_id].append((now, hp))

    def cleanup_dead_creatures(self, visible_creature_ids: set):
        """
        Remove criaturas mortas/despawnadas do histórico.
        Deve ser chamado periodicamente no loop principal.

        Args:
            visible_creature_ids: Set de IDs das criaturas atualmente visíveis
        """
        now = time.time()
        cutoff = now - self.DEAD_CREATURE_TTL

        # Remove criaturas não visíveis há mais de DEAD_CREATURE_TTL segundos
        to_remove = []
        for cid, history in self.hp_history.items():
            if cid not in visible_creature_ids:
                # Criatura não visível - verifica último timestamp
                if history:
                    last_ts = history[-1][0]
                    if last_ts < cutoff:
                        to_remove.append(cid)
                else:
                    # Histórico vazio, remove
                    to_remove.append(cid)

        for cid in to_remove:
            del self.hp_history[cid]

        # Limita tamanho máximo (remove entradas mais antigas se exceder)
        if len(self.hp_history) > self.MAX_HISTORY_SIZE:
            # Ordena por último timestamp e mantém apenas as mais recentes
            sorted_items = sorted(
                self.hp_history.items(),
                key=lambda x: x[1][-1][0] if x[1] else 0,
                reverse=True
            )
            self.hp_history = dict(sorted_items[:self.MAX_HISTORY_SIZE])

    def is_engaged_with_other(self, creature, my_name, my_pos, all_entities, my_target_id, targets_list, walker=None, attack_range=1, debug=False, log_func=print):
        """
        Detecta se criatura está engajada com outro player.

        MÉTODO PRINCIPAL: Comparação de custo de movimento
        Bot usa A* (custo real), players usam Manhattan (aproximação).

        Returns:
            tuple: (is_engaged: bool, reason: str or None)
        """
        creature_x, creature_y = creature['abs_x'], creature['abs_y']
        creature_id = creature['id']
        my_x, my_y = my_pos

        # Custo do bot até criatura (A* ou Manhattan dependendo de USE_PATHFINDING_DISTANCE)
        rel_x = creature_x - my_x
        rel_y = creature_y - my_y
        creature_dist_to_bot = get_distance_cost(walker, rel_x, rel_y, attack_range)

        if debug:
            log_func(f"  [DETECT] Iniciando comparação de custos")
            log_func(f"  [DETECT]   Criatura: ({creature_x}, {creature_y})")
            log_func(f"  [DETECT]   Bot: ({my_x}, {my_y})")
            log_func(f"  [DETECT]   Custo criatura→bot: {creature_dist_to_bot}")

        # Método 1: Comparação de custo de movimento (PRINCIPAL)
        for entity in all_entities:
            # Skip self (pela criatura)
            if entity['id'] == creature_id:
                continue

            # Skip self (player)
            if entity['name'] == my_name:
                continue

            # Skip se NÃO é player (usa is_player da Creature, detectado por outfit)
            # CORREÇÃO: Substitui filtro por nome que falhava com "Trollkiller" vs "Troll"
            if not entity.get('is_player', False):
                if debug:
                    log_func(f"  [DETECT] Skip: Não é player '{entity['name']}' (is_player=False)")
                continue

            # Se chegou aqui, é um player confirmado (detectado por outfit)
            if debug:
                log_func(f"  [DETECT] Comparando com: '{entity['name']}' (ID:{entity['id']})")

            # Calcula custo do player até criatura (Manhattan aproximado)
            player_x, player_y = entity['abs_x'], entity['abs_y']
            creature_dist_to_player = steps_to_adjacent(creature_x - player_x, creature_y - player_y, attack_range) * 10

            if debug:
                log_func(f"  [DETECT]   Posição: ({player_x}, {player_y})")
                log_func(f"  [DETECT]   Custo criatura→entidade: {creature_dist_to_player}")

            # REGRA: Se player está mais perto (ou igual custo) que o bot
            # Igual = player provavelmente chegou primeiro
            if creature_dist_to_player <= creature_dist_to_bot:
                reason = f"Mais próxima de '{entity['name']}' (custo {creature_dist_to_player}) vs bot (custo {creature_dist_to_bot})"
                if debug:
                    log_func(f"  [DETECT]   ⚠️ ENGAGED! {reason}")
                return (True, reason)
            else:
                if debug:
                    log_func(f"  [DETECT]   ✓ Bot mais próximo desta entidade")

        # Método 2: HP decrescente sem ser meu alvo (COMPLEMENTAR)
        if creature['id'] != my_target_id:
            if creature['id'] in self.hp_history:
                history = self.hp_history[creature['id']]
                if len(history) >= 2:
                    oldest_hp = history[0][1]
                    current_hp = creature['hp']
                    hp_loss = oldest_hp - current_hp

                    # Se perdeu > KS_HP_LOSS_THRESHOLD em KS_HISTORY_DURATION, está sendo atacado
                    if hp_loss > KS_HP_LOSS_THRESHOLD:
                        reason = f"HP caiu {hp_loss:.1f}% em {KS_HISTORY_DURATION}s (não é meu alvo)"
                        if debug:
                            log_func(f"  [DETECT] ⚠️ HP Loss detected: {reason}")
                        return (True, reason)

        if debug:
            log_func(f"  [DETECT] ✅ Resultado final: NÃO ENGAJADA")

        return (False, None)


def safe_attack(packet, creature_id, log_func=print):
    """
    Wrapper para packet.attack() com verificações de segurança.

    Previne ataques a:
    1. Criaturas na blacklist de suspeitos (possível summon de GM)
    2. Quando alarme está ativo (is_safe=False)

    Returns:
        True se ataque foi enviado, False se bloqueado
    """
    # Check 1: Criatura suspeita? (possível GM summon)
    if state.is_suspicious_creature(creature_id):
        log_func(f"🛑 BLOQUEADO: Criatura {creature_id} é suspeita (possível GM summon)!")
        return False

    # Check 2: Alarme ativo? (pode ter sido disparado entre decisão e ataque)
    if not state.is_safe():
        log_func(f"🛑 BLOQUEADO: Alarme ativo no momento do ataque!")
        return False

    # Tudo OK - envia ataque
    packet.attack(creature_id)
    return True


def trainer_loop(pm, base_addr, hwnd, monitor, check_running, config, status_callback=None):
    """
    Loop principal do trainer.
    status_callback: função opcional para reportar status ao Status Panel (ex: "atacando Troll")
    """
    def set_status(msg):
        """Helper para atualizar status do módulo."""
        if status_callback:
            try:
                status_callback(msg)
            except:
                pass

    # Será definida dentro do loop após ler debug_decisions
    log_decision = None

    get_cfg = make_config_getter(config)

    current_monitored_id = 0
    current_target_id = 0  # Inicializado aqui para uso consistente
    last_target_data = None
    next_attack_time = 0

    # Retargeting State
    last_reachability_check_time = 0.0
    became_unreachable_time = None

    # Death State Tracking (3-phase death detection)
    class DeathState:
        ALIVE = "alive"
        DYING = "dying"              # hp=0, vis=1 - waiting for despawn
        CORPSE_READY = "corpse_ready"  # hp=0, vis=0 - corpse spawned

    death_state = DeathState.ALIVE
    dying_creature_data = None    # Stores creature data during DYING phase
    death_timestamp = None        # When creature entered DYING state

    # Follow State Tracking (Spear Picker Integration)
    is_currently_following = False
    follow_target_id = 0

    # Floor Change KS Guard
    last_z = 0
    floor_change_time = 0.0
    FLOOR_CHANGE_KS_GUARD = 1.5  # seconds - guard period for KS check after floor change

    # Será inicializado dentro do loop com debug_mode
    mapper = None
    analyzer = None
    walker = None

    # PacketManager para envio de pacotes
    packet = PacketManager(pm, base_addr)

    # Scanner centralizado do battlelist
    scanner = BattleListScanner(pm, base_addr)

    # SpawnTracker INLINE - detecta spawns ANTES do ataque (previne race condition com alarm)
    # Proteção primária: trainer detecta spawn suspeito antes de decidir atacar
    trainer_spawn_tracker = SpawnTracker(suspicious_range=5, floor_change_cooldown=3.0)

    # Anti Kill-Steal Detection
    engagement_detector = EngagementDetector()

    while True:
        if check_running and not check_running(): 
            return

        if not get_cfg('enabled', False): 
            time.sleep(1)
            continue
        
        if pm is None: 
            time.sleep(1)
            continue
            
        if hwnd == 0: 
            hwnd = win32gui.FindWindow("TibiaClient", None) or win32gui.FindWindow(None, "Tibia")
            
        if not get_cfg('is_safe', True):
            # Cleanup follow/combat state when alarm triggers
            if is_currently_following:
                state.stop_follow()
                is_currently_following = False
                follow_target_id = 0
                print("[TRAINER] 🛑 Alarm: Follow cancelado")

            # Clear target (remove red square) and stop monitor
            if current_target_id != 0 or current_monitored_id != 0:
                try:
                    pm.write_int(base_addr + TARGET_ID_PTR, 0)
                except:
                    pass
                if current_monitored_id != 0:
                    monitor.stop_and_report()
                current_target_id = 0
                current_monitored_id = 0
                last_target_data = None
                became_unreachable_time = None
                print("[TRAINER] 🛑 Alarm: Target/Monitor limpos")

            time.sleep(0.5)
            continue

        # Protege ciclo de runemaking - não atacar durante runemaking
        if state.is_runemaking:
            time.sleep(0.5)
            continue

        # Pausa durante conversa de chat (AI respondendo)
        if state.is_chat_paused:
            time.sleep(0.5)
            continue

        # Pausa durante AFK humanization
        if state.is_afk_paused:
            time.sleep(0.5)
            continue

        min_delay = get_cfg('min_delay', 1.0)
        max_delay = get_cfg('max_delay', 2.0)
        trigger_range = get_cfg('range', 1)  # Range para ACIONAR ataque (não confundir com MELEE_RANGE)
        log = get_cfg('log_callback', print)
        debug_mode = get_cfg('debug_mode', False)
        debug_decisions = get_cfg('debug_mode_decisions_only', TRAINER_DEBUG_DECISIONS_ONLY)  # Log simplificado (apenas decisões)

        # Helper para log de decisões críticas (modo simplificado)
        def log_decision(msg):
            if debug_decisions or debug_mode:
                print(f"[DECISION] {msg}")

        loot_enabled = get_cfg('loot_enabled', False)
        targets_list = get_cfg('targets', [])
        ignore_first = get_cfg('ignore_first', False)
        ks_enabled = get_cfg('ks_prevention_enabled', KS_PREVENTION_ENABLED)

        # Spear Picker Integration - Follow before attack (DESABILITADO por padrão)
        # Requer: follow_before_attack_enabled=True E spear_picker_enabled=True E range > 1
        spear_picker_enabled = get_cfg('spear_picker_enabled', False)
        follow_before_attack_enabled = get_cfg('follow_before_attack_enabled', False)

        # FOLLOW_THEN_ATTACK: config independente para seguir antes de atacar
        follow_then_attack_standalone = get_cfg('follow_then_attack', FOLLOW_THEN_ATTACK)

        # Ativa se: standalone config OU (spear picker combo)
        follow_before_attack = follow_then_attack_standalone or (follow_before_attack_enabled and spear_picker_enabled and trigger_range > 1)

        # Log de configuração anti-KS (apenas primeira iteração)
        if mapper is None:
            print(f"[TRAINER] Iniciando... (debug_mode={debug_mode})")
        if debug_mode and mapper is None:
            log("="*70)
            log("[TRAINER] Configuração Anti Kill-Steal")
            log("="*70)
            log(f"  Enabled: {ks_enabled}")
            if ks_enabled:
                log(f"  HP Loss Threshold: {KS_HP_LOSS_THRESHOLD}%")
                log(f"  History Duration: {KS_HISTORY_DURATION}s")
                log(f"  Detection: Distance comparison + HP tracking")
            log("="*70)

            # Log de configuração Follow-Before-Attack
            log("="*70)
            log("[TRAINER] Configuração Follow-Before-Attack (Spear Picker)")
            log("="*70)
            log(f"  Follow Before Attack Flag: {follow_before_attack_enabled}")
            log(f"  Spear Picker Enabled: {spear_picker_enabled}")
            log(f"  Trigger Range: {trigger_range}")
            log(f"  Follow Before Attack ATIVO: {follow_before_attack}")
            if follow_before_attack:
                log(f"  Modo: FOLLOW quando dist > 1, ATTACK quando dist <= 1")
            else:
                log(f"  Modo: ATTACK direto (comportamento normal)")
            log("="*70)

        # Inicializa componentes de pathfinding na primeira iteração com debug_mode
        if mapper is None:
            mapper = MemoryMap(pm, base_addr)
            analyzer = MapAnalyzer(mapper)
            walker = AStarWalker(analyzer, max_depth=150, debug=debug_mode)

        try:
            player_id = state.get_player_id(pm, base_addr)

            current_name = get_my_char_name(pm, base_addr)
            if not current_name: 
                time.sleep(0.5); continue
            
            target_addr = base_addr + TARGET_ID_PTR
            my_x, my_y, my_z = get_player_pos(pm, base_addr)
            
            if my_z == 0:
                time.sleep(0.2)
                continue

            # Detecta mudança de andar para guard do KS
            if last_z != 0 and my_z != last_z:
                floor_change_time = time.time()
                log_decision(f"⚠️ Floor change ({last_z} → {my_z}) - KS guard {FLOOR_CHANGE_KS_GUARD}s")
            last_z = my_z

            mapper.read_full_map(player_id)

            # Lê target ID ANTES do scan para uso correto no KS check
            current_target_id = pm.read_int(target_addr)

            # 2. SCAN
            valid_candidates = []
            visual_line_count = 0
            all_visible_entities = []  # Todas as entidades visíveis (para KS detection)

            if debug_mode:
                print(f"\n{'='*70}")
                print(f"--- INÍCIO DO SCAN (Z: {my_z}) ---")
                print(f"  My Position: ({my_x}, {my_y}, {my_z})")
                print(f"  Current Target ID: {current_target_id}")
                print(f"  KS Prevention: {ks_enabled}")
                print(f"{'='*70}\n")

            # SCAN via game_state cache (20Hz) com fallback para BattleListScanner
            # game_state reduz syscalls: 1 thread escaneia, todos os módulos consomem
            all_creatures = game_state.get_creatures() + game_state.get_players()

            # Fallback: se game_state ainda não populou, usa scanner direto
            if not all_creatures:
                all_creatures = scanner.scan_all()

            # Atualiza overlay de debug (se XRAY_TRAINER_DEBUG ativo)
            update_trainer_overlay(all_creatures, my_x, my_y, my_z, current_target_id, current_name)

            # Cleanup de criaturas mortas no HP history (previne memory leak)
            visible_ids = {c.id for c in all_creatures if c.is_visible}
            engagement_detector.cleanup_dead_creatures(visible_ids)

            # ==============================================================================
            # SPAWN PROTECTION: Detecta spawns suspeitos ANTES de decidir atacar
            # Previne race condition onde trainer ataca antes do alarm detectar GM summon
            # ==============================================================================
            suspicious_spawns = trainer_spawn_tracker.update(
                all_creatures, my_x, my_y, my_z, self_id=state.char_id
            )

            # Marca spawns suspeitos na blacklist compartilhada
            # Durante pausa AFK, ignora spawns suspeitos (evita falso positivo de respawns naturais)
            if suspicious_spawns and not state.is_afk_paused:
                for creature in suspicious_spawns:
                    state.add_suspicious_creature(creature.id)
                    log(f"👮 [TRAINER] Spawn suspeito: {creature.name} (ID:{creature.id})")

                # Dispara alarme e aborta este ciclo
                state.trigger_alarm(is_gm=True, reason="SPAWN_SUSPICIOUS")
                log_decision(f"🚨 {len(suspicious_spawns)} spawn(s) suspeito(s)! Abortando ataque.")
                set_status(f"👮 Spawn suspeito detectado!")
                time.sleep(0.5)
                continue

            # Filtra APENAS PLAYERS visíveis no mesmo andar (para KS detection)
            # CORREÇÃO: Usa c.is_player em vez de filtrar por nome depois
            all_visible_entities = [
                creature_to_entity_dict(c)
                for c in all_creatures
                if c.is_visible and c.position.z == my_z and c.name != current_name and c.is_player
            ]

            # ==============================================================================
            # DEATH PHASE POLLING: Monitor DYING → CORPSE_READY transition
            # ==============================================================================
            if death_state == DeathState.DYING and dying_creature_data:
                # Check elapsed time since death
                elapsed = time.time() - death_timestamp

                # Safety timeout: 3 seconds max wait
                if elapsed > 3.0:
                    print(f"⚠️ Death timeout: {dying_creature_data['name']} - assuming corpse ready")
                    death_state = DeathState.CORPSE_READY
                    # Will trigger corpse opening below
                else:
                    # Re-scan battlelist to check creature's current visibility
                    dying_creature = scanner.get_creature_by_id(dying_creature_data["id"])

                    if dying_creature and dying_creature.hp_percent == 0:
                        if not dying_creature.is_visible:
                            # TRANSITION: DYING → CORPSE_READY
                            death_state = DeathState.CORPSE_READY
                            if debug_mode:
                                log(f"💀 {dying_creature_data['name']} despawned (vis=0) - corpse ready")
                        else:
                            # Still visible - remain in DYING state
                            if debug_mode:
                                log(f"⏳ {dying_creature_data['name']} dying phase (vis=1, elapsed={elapsed:.2f}s)")
                    elif dying_creature and dying_creature.hp_percent > 0:
                        # NOVO: Criatura REVIVEU (falso positivo ou healing) - abortar loot cycle
                        if debug_mode:
                            log(f"⚠️ {dying_creature_data['name']} reviveu (HP={dying_creature.hp_percent}%) - abortando loot")
                        state.end_loot_cycle()
                        print(f"⚠️ Loot cycle abortado: {dying_creature_data['name']} reviveu")
                        death_state = DeathState.ALIVE
                        dying_creature_data = None
                        death_timestamp = None
                        current_monitored_id = 0
                        should_attack_new = True
                    else:
                        # Creature disappeared from battlelist entirely
                        # Fallback: assume corpse ready
                        if debug_mode:
                            log(f"⚠️ {dying_creature_data['name']} disappeared from battlelist - assuming corpse ready")
                        death_state = DeathState.CORPSE_READY

                # DEATH PHASE POLLING não executa mais ações
                # Apenas monitora transição DYING → CORPSE_READY
                # As ações serão executadas no CENÁRIO B

            # Processa candidatos válidos
            for creature in all_creatures:
                # Skip self
                if creature.name == current_name:
                    continue

                # Verifica se é alvo válido (mesmo andar, visível, vivo)
                if not creature.is_targetable(my_z):
                    continue

                # Ignora players (só ataca monstros)
                if creature.is_player:
                    if debug_mode:
                        print(f"   🚫 SKIP PLAYER: {creature.name}")
                    continue

                # ===== CALCULA is_attacking_me CEDO para bypass de filtros =====
                is_attacking_me = creature.is_attacking_player(BLACKSQUARE_THRESHOLD_MS, debug=debug_mode)

                # Extrai dados
                c_id = creature.id
                name = creature.name
                cx = creature.position.x
                cy = creature.position.y
                hp = creature.hp_percent

                dist_x = abs(my_x - cx)
                dist_y = abs(my_y - cy)
                dist_tiles = max(dist_x, dist_y)  # Distância em tiles (adjacente = 1)
                is_in_range = (dist_x <= trigger_range and dist_y <= trigger_range)

                if debug_mode:
                    print(f"Slot {creature.slot_index}: {name} (Vis:1 Z:{my_z} HP:{hp} Dist:({dist_x},{dist_y}) Attacking:{is_attacking_me})")

                # ===== REGRA ABSOLUTA: Criatura atacando a 1 tile = candidato imediato =====
                # Bypass total de range, accessibility e KS checks
                if is_attacking_me and dist_tiles <= 1 and hp > 0:
                    # Ainda precisa estar na lista de alvos
                    if any(t in name for t in targets_list):
                        if debug_mode:
                            print(f"   ⚔️ PRIORIDADE: {name} está atacando e adjacente - bypass total")
                        # Conta linha visual antes de adicionar
                        current_line = visual_line_count
                        visual_line_count += 1
                        valid_candidates.append(
                            creature_to_candidate_dict(creature, my_x, my_y, trigger_range, current_line, is_attacking_me=True)
                        )
                        continue  # Já adicionado, pula para próxima criatura

                # Conta linha visual
                current_line = visual_line_count
                visual_line_count += 1

                if debug_mode:
                    print(f"   [LINHA {current_line}] -> {name} (ID: {c_id})")

                # Verifica se é alvo desejado (lista de targets é absoluta)
                if not any(t in name for t in targets_list):
                    continue

                # Verifica range e HP
                if not (is_in_range and hp > 0):
                    continue

                # Atualiza histórico HP para KS detection
                engagement_detector.update_hp(c_id, hp)

                is_reachable = True

                # Calculamos posição relativa
                rel_x = cx - my_x
                rel_y = cy - my_y
                dist_sqm = max(abs(rel_x), abs(rel_y))

                # DEBUG: Log antes de verificar acessibilidade
                if debug_mode:
                    print(f"   📍 Checking {name} (ID:{c_id}) at ({cx},{cy}) | Rel:({rel_x},{rel_y}) Dist:{dist_sqm} | Attacking:{is_attacking_me}")

                # Pula check de acessibilidade se criatura está nos atacando
                if not is_attacking_me:
                    # SEMPRE verificar acessibilidade com A*, exceto se dist == 0 (mesmo tile)
                    if dist_sqm == 0:
                        # Mesmo tile que o player - sempre acessível (não deveria acontecer)
                        if debug_mode:
                            print(f"      ⚠️ Monstro no mesmo tile (dist=0)")
                    else:
                        # Pergunta ao A*: "Consigo dar o primeiro passo em direção a esse destino?"
                        next_step = walker.get_next_step(rel_x, rel_y, activate_fallback=False)

                        # Se next_step for None, o caminho está bloqueado (parede ou outro monstro)
                        if next_step is None:
                            is_reachable = False
                            if debug_mode:
                                print(f"      ❌ INACESSÍVEL: {name} (A* retornou None)")
                            continue
                        else:
                            if debug_mode:
                                print(f"      ✅ ACESSÍVEL: Next step = {next_step}")
                else:
                    if debug_mode:
                        print(f"      ⚡ BYPASS: Criatura nos atacando - ignorando check de acessibilidade")

                # Verifica KS prevention antes de adicionar aos candidatos
                skip_ks = False

                # KS check: só executa se KS habilitado E criatura NÃO está nos atacando
                # (is_attacking_me já foi calculado antes do A* check)
                if ks_enabled and not is_attacking_me:
                    # KS check normal via engagement detector
                    # Log pré-KS check
                    if debug_mode:
                        print(f"\n[KS CHECK] Avaliando {name} (ID:{c_id})")
                        print(f"[KS CHECK]   Posição: ({cx}, {cy}) | Rel: ({rel_x}, {rel_y})")
                        print(f"[KS CHECK]   HP: {hp}%")
                        print(f"[KS CHECK]   Blacksquare: {creature.blacksquare}")
                        print(f"[KS CHECK]   Meu Target Atual: {current_target_id}")
                        print(f"[KS CHECK]   Entidades Visíveis: {len(all_visible_entities)}")

                        if len(all_visible_entities) > 0:
                            print(f"[KS CHECK]   Lista de Entidades:")
                            for idx, ent in enumerate(all_visible_entities):
                                ent_dist = max(abs(ent['abs_x'] - my_x), abs(ent['abs_y'] - my_y))
                                is_player_guess = not any(t in ent['name'] for t in targets_list)
                                entity_type = "PLAYER?" if is_player_guess else "CREATURE"
                                print(f"    [{idx:2d}] {ent['name']:25s} | "
                                      f"ID:{ent['id']:6d} | "
                                      f"Pos:({ent['abs_x']:5d},{ent['abs_y']:5d}) | "
                                      f"Dist:{ent_dist:2d} SQM | "
                                      f"HP:{ent['hp']:3d}% | "
                                      f"Type:{entity_type}")

                    is_engaged, ks_reason = engagement_detector.is_engaged_with_other(
                        creature_to_entity_dict(creature),
                        current_name,
                        (my_x, my_y),
                        all_visible_entities,
                        current_target_id,
                        targets_list,
                        walker=walker,
                        attack_range=MELEE_RANGE,
                        debug=debug_mode,
                        log_func=print
                    )

                    # Log pós-KS check
                    if debug_mode:
                        if is_engaged:
                            print(f"[KS CHECK]   Resultado: ❌ SKIP - {ks_reason}\n")
                        else:
                            print(f"[KS CHECK]   Resultado: ✅ PASS - Sem engagement detectado\n")

                    if is_engaged:
                        skip_ks = True
                elif is_attacking_me and debug_mode:
                    print(f"\n[KS CHECK] ✅ BYPASS: {name} está nos atacando - ignorando KS check")

                # REGRA ABSOLUTA: Criatura atacando player SEMPRE é candidato válido
                # Mesmo que anti-KS a descartasse, se is_attacking_me=True, é válida
                if is_attacking_me or not skip_ks:
                    if debug_mode:
                        reason = "ATACANDO PLAYER" if is_attacking_me else "KS PASS"
                        print(f"      → CANDIDATO ({reason}): HP:{hp} Dist:({dist_x},{dist_y})")
                    valid_candidates.append(
                        creature_to_candidate_dict(creature, my_x, my_y, trigger_range, current_line, is_attacking_me=is_attacking_me)
                    )

            if debug_mode:
                print(f"--- FIM DO SCAN ---")

            # Atualiza flag de alvos visíveis para coordenação com cavebot
            # Cavebot usa isso para evitar iniciar navegação quando há alvos na tela
            state.set_visible_targets(len(valid_candidates) > 0)

            # PRIORIZAÇÃO POR DISTÂNCIA: Ordena candidatos pelo mais próximo primeiro
            # Usa A* ou Manhattan dependendo de USE_PATHFINDING_DISTANCE
            if valid_candidates:
                valid_candidates.sort(key=lambda c: get_distance_cost(walker, c["abs_x"] - my_x, c["abs_y"] - my_y, MELEE_RANGE))
                if debug_mode:
                    mode = "A*" if USE_PATHFINDING_DISTANCE else "Manhattan"
                    print(f"[SORT] Candidatos ordenados por custo ({mode}):")
                    for idx, c in enumerate(valid_candidates):
                        cost = get_distance_cost(walker, c["abs_x"] - my_x, c["abs_y"] - my_y, MELEE_RANGE)
                        print(f"  [{idx}] {c['name']} - custo {cost}")

            should_attack_new = False

            # Cenário A: Já estou atacando
            if current_target_id != 0:
                target_data = next((c for c in valid_candidates if c["id"] == current_target_id), None)
                
                if target_data:
                    # === VALIDAÇÃO CONTÍNUA DE ACESSIBILIDADE ===
                    current_time = time.time()

                    # Verifica acessibilidade a cada REACHABILITY_CHECK_INTERVAL segundos
                    if current_time - last_reachability_check_time >= REACHABILITY_CHECK_INTERVAL:
                        last_reachability_check_time = current_time

                        # Calcula posição relativa para check do A*
                        rel_x = target_data["abs_x"] - my_x
                        rel_y = target_data["abs_y"] - my_y
                        dist_sqm = max(abs(rel_x), abs(rel_y))

                        # SEMPRE verifica acessibilidade com A*, exceto se dist == 0 (mesmo tile)
                        is_reachable = True
                        if dist_sqm == 0:
                            # Mesmo tile que o player - sempre acessível
                            pass
                        else:
                            next_step = walker.get_next_step(rel_x, rel_y, activate_fallback=False)
                            if next_step is None:
                                is_reachable = False
                                if debug_mode:
                                    log(f"   🔍 Retargeting check: {target_data['name']} - ❌ INACESSÍVEL (A* retornou None)")

                        # Trata detecção de inacessibilidade
                        if not is_reachable:
                            # Inicia timer na primeira detecção
                            if became_unreachable_time is None:
                                became_unreachable_time = current_time
                                if debug_mode:
                                    log(f"⚠️ Target {target_data['name']} se tornou inacessível (iniciando timer de {RETARGET_DELAY}s)")

                            # Verifica se threshold de delay foi atingido
                            unreachable_duration = current_time - became_unreachable_time

                            if unreachable_duration >= RETARGET_DELAY:
                                # FORÇA RETARGET PARA CRIATURA MAIS PRÓXIMA ACESSÍVEL
                                log(f"🔄 Alvo inacessível por {RETARGET_DELAY}s - retargeting para mais próximo")

                                # Para monitoramento do alvo antigo
                                if current_monitored_id != 0:
                                    monitor.stop_and_report()
                                    current_monitored_id = 0

                                # Limpa memória do cliente (remove quadrado vermelho)
                                pm.write_int(target_addr, 0)

                                # Encontra alvo acessível mais próximo
                                nearest = find_nearest_reachable_target(
                                    valid_candidates, my_x, my_y, walker, MELEE_RANGE, current_target_id
                                )

                                if nearest:
                                    cost = get_distance_cost(walker, nearest['abs_x'] - my_x, nearest['abs_y'] - my_y, MELEE_RANGE)
                                    dist_to_nearest = max(abs(nearest['dist_x']), abs(nearest['dist_y']))

                                    # Usa mesma lógica de follow_before_attack
                                    if follow_before_attack and dist_to_nearest > 1:
                                        log(f"🏃 RETARGET (follow): {nearest['name']} (dist={dist_to_nearest})")
                                        log_decision(f"🔄 RETARGET: alvo inacessível → {nearest['name']} (follow, dist:{dist_to_nearest})")
                                        packet.follow(nearest["id"])
                                        state.start_follow(nearest["id"])
                                        is_currently_following = True
                                        follow_target_id = nearest["id"]
                                    else:
                                        log(f"⚔️ RETARGET: {nearest['name']} (custo: {cost})")
                                        log_decision(f"🔄 RETARGET: alvo inacessível → {nearest['name']} (attack)")
                                        if not safe_attack(packet, nearest["id"], log):
                                            time.sleep(0.5)
                                            continue
                                        if is_currently_following:
                                            state.stop_follow()
                                            is_currently_following = False
                                            follow_target_id = 0

                                    # Atualiza variáveis de estado
                                    current_target_id = nearest["id"]
                                    current_monitored_id = nearest["id"]
                                    last_target_data = nearest.copy()

                                    # Inicia monitoramento do novo alvo
                                    monitor.start(nearest["id"], nearest["name"], nearest["hp"])

                                    # Reseta estado de retarget
                                    became_unreachable_time = None
                                    next_attack_time = 0  # Sem delay (troca tática)
                                else:
                                    log("⚠️ Nenhum alvo acessível disponível - aguardando")
                                    became_unreachable_time = None  # Reseta para tentar no próximo scan

                                # Pula resto do processamento do Cenário A
                                time.sleep(SCAN_DELAY_COMBAT)
                                continue

                        else:  # Alvo está acessível
                            # Reseta timer de inacessibilidade
                            if became_unreachable_time is not None:
                                if debug_mode:
                                    log(f"✅ Target {target_data['name']} está acessível novamente")
                                became_unreachable_time = None

                    # === TRANSIÇÃO FOLLOW → ATTACK ===
                    # Quando seguindo criatura e ela chega a distância <= 1, troca para attack
                    if is_currently_following and current_target_id == follow_target_id:
                        rel_x = target_data["abs_x"] - my_x
                        rel_y = target_data["abs_y"] - my_y
                        dist_now = max(abs(rel_x), abs(rel_y))

                        if debug_mode:
                            print(f"[FOLLOW-DEBUG] Monitorando follow: {target_data['name']}")
                            print(f"[FOLLOW-DEBUG]   Distância atual: {dist_now} tiles (rel_x={rel_x}, rel_y={rel_y})")
                            print(f"[FOLLOW-DEBUG]   Transição para attack em: dist <= 1")

                        if dist_now <= 1:
                            # === KS FAIL-SAFE: Verifica engagement antes de atacar ===
                            # Se criatura NÃO está nos atacando, pode ter sido pega por outro player
                            # durante nosso trajeto de follow
                            is_attacking_me = target_data.get("is_attacking_me", False)

                            if not is_attacking_me and ks_enabled:
                                # Re-verifica KS antes de atacar
                                is_engaged, ks_reason = engagement_detector.is_engaged_with_other(
                                    {'id': target_data["id"], 'abs_x': target_data["abs_x"],
                                     'abs_y': target_data["abs_y"], 'hp': target_data["hp"]},
                                    current_name,
                                    (my_x, my_y),
                                    all_visible_entities,
                                    current_target_id,
                                    targets_list,
                                    walker=walker,
                                    attack_range=MELEE_RANGE,
                                    debug=debug_mode,
                                    log_func=print
                                )

                                if is_engaged:
                                    log(f"⚠️ [KS FAIL-SAFE] {target_data['name']} engajada ao chegar - cancelando ataque")
                                    log_decision(f"🛑 KS FAIL-SAFE: {target_data['name']} engajada ({ks_reason}) - buscando novo alvo")

                                    # CRÍTICO: Envia packet.stop() para parar follow no cliente
                                    packet.stop()

                                    # Cancela follow e limpa estado
                                    state.stop_follow()
                                    is_currently_following = False
                                    follow_target_id = 0
                                    pm.write_int(target_addr, 0)  # Remove red square
                                    if current_monitored_id != 0:
                                        monitor.stop_and_report()
                                    current_target_id = 0
                                    current_monitored_id = 0
                                    should_attack_new = True
                                    time.sleep(SCAN_DELAY_COMBAT)
                                    continue

                                if debug_mode:
                                    print(f"[KS FAIL-SAFE] ✅ Criatura livre - pode atacar")

                            # Criatura está nos atacando OU passou no KS check - pode atacar
                            log(f"⚔️ TRANSIÇÃO: Follow → Attack ({target_data['name']})")
                            set_status(f"atacando {target_data['name']}")
                            log_decision(f"🔄 Follow → Attack: {target_data['name']} (dist:{dist_now}, attacking:{is_attacking_me})")
                            if not safe_attack(packet, current_target_id, log):
                                time.sleep(0.5)
                                continue

                            # Para estado de follow
                            state.stop_follow()
                            is_currently_following = False
                            follow_target_id = 0

                            if debug_mode:
                                print(f"[FOLLOW-DEBUG] ✓ TRANSIÇÃO COMPLETA: Follow → Attack")
                                print(f"[FOLLOW-DEBUG]   Pacote ATTACK enviado (0xA1)")
                                print(f"[FOLLOW-DEBUG]   state.is_following={state.is_following}")

                    # === LÓGICA EXISTENTE DE ATUALIZAÇÃO DO MONITOR ===
                    next_attack_time = 0
                    last_target_data = target_data.copy()
                    if current_target_id != current_monitored_id:
                        monitor.start(current_target_id, target_data["name"], target_data["hp"])
                        current_monitored_id = current_target_id
                        if debug_mode: print(f"--> Iniciando monitoramento em {target_data['name']} (ID: {current_target_id})")
                    else:
                        monitor.update(target_data["hp"])
                else:
                    # Alvo não está em valid_candidates - pode ser:
                    # (A) Fora de alcance (dist > attack_range)
                    # (B) Morto (hp <= 0)
                    # (C) Despawned (não está mais na battle list)
                    # (D) INACESSÍVEL (no alcance mas bloqueado)

                    # Tenta encontrar o alvo na battle list inteira (não filtrada)
                    # para distinguir entre "despawned" e "fora de alcance/inacessível"
                    # Usa scanner centralizado - elimina scan duplicado
                    target_creature = scanner.get_creature_by_id(current_target_id)
                    if target_creature:
                        target_in_battlelist = creature_to_entity_dict(target_creature)
                        target_in_battlelist['z'] = target_creature.position.z
                        target_in_battlelist['visible'] = 1 if target_creature.is_visible else 0
                    else:
                        target_in_battlelist = None

                    if target_in_battlelist:
                        # Alvo está na battle list, mas não em valid_candidates
                        # Pode estar: fora de alcance, ou INACESSÍVEL

                        if target_in_battlelist['hp'] <= 0:
                            # Está morto
                            if debug_mode: print("-> Alvo morto na battle list.")
                            became_unreachable_time = None
                        elif target_in_battlelist['z'] != my_z:
                            # Mudou de andar
                            if debug_mode: print("-> Alvo em andar diferente.")
                            became_unreachable_time = None
                        else:
                            # Alvo vivo e no mesmo andar, mas fora de valid_candidates
                            # Trata como INACESSÍVEL (verificar com A*)
                            current_time = time.time()

                            if current_time - last_reachability_check_time >= REACHABILITY_CHECK_INTERVAL:
                                last_reachability_check_time = current_time

                                # Verifica acessibilidade com A*
                                rel_x = target_in_battlelist['abs_x'] - my_x
                                rel_y = target_in_battlelist['abs_y'] - my_y
                                dist_sqm = max(abs(rel_x), abs(rel_y))

                                is_reachable = True
                                if dist_sqm == 0:
                                    is_reachable = True
                                else:
                                    next_step = walker.get_next_step(rel_x, rel_y, activate_fallback=False)
                                    if next_step is None:
                                        is_reachable = False

                                if not is_reachable:
                                    # Alvo está inacessível!
                                    if became_unreachable_time is None:
                                        became_unreachable_time = current_time
                                        if debug_mode:
                                            log(f"⚠️ Target {target_in_battlelist['name']} está INACESSÍVEL (fora de valid_candidates) - iniciando timer de {RETARGET_DELAY}s")

                                    unreachable_duration = current_time - became_unreachable_time

                                    if unreachable_duration >= RETARGET_DELAY:
                                        log(f"🔄 Target inacessível por {RETARGET_DELAY}s - forçando retarget")

                                        # Limpa memória do cliente
                                        pm.write_int(target_addr, 0)

                                        # Para monitoramento
                                        if current_monitored_id != 0:
                                            monitor.stop_and_report()
                                            current_monitored_id = 0

                                        # Encontra alvo mais próximo
                                        nearest = find_nearest_reachable_target(
                                            valid_candidates, my_x, my_y, walker, MELEE_RANGE, current_target_id
                                        )

                                        if nearest:
                                            cost = get_distance_cost(walker, nearest['abs_x'] - my_x, nearest['abs_y'] - my_y, MELEE_RANGE)
                                            dist_to_nearest = max(abs(nearest['dist_x']), abs(nearest['dist_y']))

                                            # Usa mesma lógica de follow_before_attack
                                            if follow_before_attack and dist_to_nearest > 1:
                                                log(f"🏃 RETARGET (follow): {nearest['name']} (dist={dist_to_nearest})")
                                                log_decision(f"🔄 RETARGET: alvo inacessível → {nearest['name']} (follow, dist:{dist_to_nearest})")
                                                packet.follow(nearest["id"])
                                                state.start_follow(nearest["id"])
                                                is_currently_following = True
                                                follow_target_id = nearest["id"]
                                            else:
                                                log(f"⚔️ RETARGET: {nearest['name']} (custo: {cost})")
                                                log_decision(f"🔄 RETARGET: alvo inacessível → {nearest['name']} (attack)")
                                                if not safe_attack(packet, nearest["id"], log):
                                                    time.sleep(0.5)
                                                    continue
                                                if is_currently_following:
                                                    state.stop_follow()
                                                    is_currently_following = False
                                                    follow_target_id = 0

                                            current_target_id = nearest["id"]
                                            current_monitored_id = nearest["id"]
                                            last_target_data = nearest.copy()
                                            monitor.start(nearest["id"], nearest["name"], nearest["hp"])
                                            became_unreachable_time = None
                                            next_attack_time = 0
                                        else:
                                            log("⚠️ Nenhum alvo acessível disponível - aguardando")
                                            became_unreachable_time = None

                                        time.sleep(SCAN_DELAY_COMBAT)
                                        continue
                                else:
                                    # Alvo se tornou acessível novamente
                                    if became_unreachable_time is not None:
                                        if debug_mode:
                                            log(f"✅ Target {target_in_battlelist['name']} está acessível novamente")
                                        became_unreachable_time = None
                    else:
                        # Alvo não está na battle list - está despawned/morto
                        if debug_mode: print("-> Alvo não está mais na battle list (despawned).")
                        became_unreachable_time = None

           # CENÁRIO B: Alvo Sumiu (Tibia limpou target_id)
            elif current_target_id == 0 and current_monitored_id != 0:
                # === VERIFICAÇÃO DUPLA DE MORTE ===
                # Método 1: Verifica se último alvo ainda está em valid_candidates
                target_in_candidates = False
                if last_target_data:
                    for m in valid_candidates:
                        if m["id"] == last_target_data["id"]:
                            target_in_candidates = True
                            break

                # Método 2: Verifica diretamente na battlelist E identifica fase de morte
                target_creature = scanner.get_creature_by_id(last_target_data["id"]) if last_target_data else None

                if target_creature:
                    # Determine death phase based on hp and visibility
                    if target_creature.hp_percent > 0:
                        death_phase = DeathState.ALIVE
                    elif target_creature.is_visible:
                        death_phase = DeathState.DYING  # hp=0, vis=1 - corpse not spawned yet
                    else:
                        death_phase = DeathState.CORPSE_READY  # hp=0, vis=0 - corpse spawned
                else:
                    death_phase = None  # Not in battlelist (despawned)

                target_alive_in_battlelist = (death_phase == DeathState.ALIVE)

                if debug_mode:
                    print(f"   [Death Check] in_candidates={target_in_candidates}, alive_in_bl={target_alive_in_battlelist}")

                # Alvo está vivo se estiver em candidates OU vivo na battlelist
                target_still_alive = target_in_candidates or target_alive_in_battlelist

                if target_still_alive:
                    log("🛑 Ataque interrompido (Monstro ainda vivo - verificação dupla).")
                    monitor.stop_and_report()
                    current_monitored_id = 0
                    last_target_data = None
                    became_unreachable_time = None
                    should_attack_new = True

                else:
                    # MORTE CONFIRMADA (dupla verificação)
                    # Check death phase to decide action

                    if death_phase == DeathState.DYING:
                        if debug_mode:
                            print("DEBUG: DYING phase")
                        # hp=0 but still visible - enter DYING state, wait for despawn
                        log(f"☠️ {last_target_data['name']} morto mas visível (hp=0, vis=1) - aguardando despawn")

                        # Para follow se estava seguindo (criatura morreu)
                        if is_currently_following:
                            state.stop_follow()
                            is_currently_following = False
                            follow_target_id = 0
                            if debug_mode:
                                print(f"[FOLLOW-DEBUG] ✓ Follow parado - criatura morreu ({last_target_data['name']})")
                                print(f"[FOLLOW-DEBUG]   state.is_following={state.is_following}")

                        # ===== MARCA INÍCIO DO CICLO DE LOOT (APENAS SE AUTO_LOOT HABILITADO) =====
                        # Pausa spear picker IMEDIATAMENTE quando criatura morre (se auto_loot ativo)
                        if loot_enabled:
                            state.start_loot_cycle()
                            if debug_mode:
                                print("DEBUG: Iniciando ciclo de loot (DYING phase).")
                        # ================================================================================

                        death_state = DeathState.DYING
                        dying_creature_data = last_target_data.copy()
                        death_timestamp = time.time()
                        monitor.stop_and_report()
                        # NÃO zera current_monitored_id - mantém vivo para próxima iteração pegar CORPSE_READY
                        # DON'T reset last_target_data - needed for polling
                        became_unreachable_time = None
                        # DON'T set should_attack_new - will be set after corpse opened

                    elif death_phase == DeathState.CORPSE_READY or death_phase is None:
                        if debug_mode:
                            print("DEBUG: CORPSE_READY or None")
                        # hp=0 and NOT visible - corpse ready OR creature despawned
                        log("💀 Alvo eliminado (verificação dupla confirmada).")
                        if last_target_data:
                            log_decision(f"💀 {last_target_data['name']} morto" + (" - iniciando loot" if loot_enabled else ""))

                        if last_target_data and loot_enabled:
                            if debug_mode:
                                print("DEBUG: Tentando abrir corpo...")
                            # ===== MARCA INÍCIO DO CICLO DE LOOT =====
                            # Guard: só inicia se não estiver ativo (pode já ter sido iniciado em DYING)
                            if not state.is_processing_loot:
                                state.start_loot_cycle()
                                if debug_mode:
                                    print("DEBUG: Iniciando ciclo de loot (CORPSE_READY phase).")
                            # ==========================================

                            monster_name = last_target_data["name"]
                            should_skip_loot = any(skip_name in monster_name for skip_name in NO_LOOT_CREATURES)

                            if should_skip_loot:
                                if debug_mode:
                                    log(f"⏭️ Pulando loot de {monster_name} (sem loot)")
                                state.end_loot_cycle()
                                if debug_mode:
                                    print("DEBUG: Pulando loot - sem loot definido para essa criatura.")
                            else:
                                # Corpse ready - wait and open
                                gauss_wait(0.4, 25)  # 300-500ms humanized delay
                                success = open_corpse_via_packet(pm, base_addr, last_target_data, player_id, log_func=log)
                                if success:
                                    log(f"📂 Corpo aberto (Packet).")

                                    # NOVO: Polling ativo - aguarda container abrir ou timeout
                                    timeout = 4.0  # 4 segundos (permite latência de rede)
                                    poll_interval = 0.1  # Verifica a cada 100ms
                                    elapsed = 0.0

                                    if debug_mode:
                                        log("⏳ Aguardando container de loot abrir...")

                                    while elapsed < timeout:
                                        if state.has_open_loot:
                                            # Container abriu com sucesso!
                                            if debug_mode:
                                                log(f"✓ Container detectado em {elapsed:.1f}s")
                                            break

                                        time.sleep(poll_interval)
                                        elapsed += poll_interval
                                    else:
                                        # Timeout atingido sem detectar container
                                        log(f"⚠️ Timeout ({timeout}s): Container de loot não abriu - finalizando ciclo")
                                        state.end_loot_cycle()
                                        if debug_mode:
                                            print("⚠️ Falha ao abrir corpo - ciclo de loot finalizado.")
                                else:
                                    if debug_mode:
                                        print("DEBUG: Falha ao abrir corpo.")
                                    state.end_loot_cycle()
                                    if debug_mode:
                                        print("⚠️ Falha ao abrir corpo via packet - ciclo de loot finalizado.")

                        elif last_target_data and not loot_enabled:
                            if debug_mode: log("ℹ️ Auto Loot desligado.")
                            # Se start_loot_cycle foi chamado no DYING, garante cleanup
                            state.end_loot_cycle()
                            if debug_mode:
                                print("DEBUG: Auto Loot desligado - garantindo fim do ciclo de loot.")

                        # ===== RESET APÓS PROCESSAR LOOT =====
                        # Reseta death_state aqui (não mais no polling)
                        death_state = DeathState.ALIVE
                        dying_creature_data = None
                        death_timestamp = None

                        # Limpa criatura da blacklist de suspeitos (se estava lá)
                        if last_target_data:
                            state.remove_suspicious_creature(last_target_data["id"])

                        monitor.stop_and_report()
                        current_monitored_id = 0
                        last_target_data = None
                        became_unreachable_time = None
                        should_attack_new = True

            # Cenário C: Ninguém atacando
            else:
                if current_monitored_id != 0:
                    monitor.stop_and_report()
                    current_monitored_id = 0
                    became_unreachable_time = None
                should_attack_new = True

            # 4. AÇÃO
            if should_attack_new:
                final_candidates = valid_candidates

                if ignore_first:
                    if len(valid_candidates) >= 2:
                        final_candidates = [valid_candidates[1]]
                    else:
                        final_candidates = []

                # ===== FLOOR CHANGE KS GUARD =====
                # Após mudar de andar, battlelist pode estar incompleta (players não popularam)
                # Só permite alvos adjacentes atacando até battlelist estabilizar
                if ks_enabled:
                    floor_change_elapsed = time.time() - floor_change_time
                    if floor_change_elapsed < FLOOR_CHANGE_KS_GUARD and len(all_visible_entities) == 0:
                        final_candidates = [
                            c for c in final_candidates
                            if c.get("is_attacking_me", False) and max(abs(c["dist_x"]), abs(c["dist_y"])) <= 1
                        ]
                        if not final_candidates:
                            log_decision(f"⏸️ Floor change KS guard: no visible players yet ({floor_change_elapsed:.1f}s)")

                # ===== PAUSA DURANTE LOOT/SPEAR PICKUP =====
                # Não ataca novos alvos durante ciclo de loot ou spear pickup
                # EXCEÇÃO: Alvos que estão atacando E adjacentes (emergência)
                if state.is_processing_loot or state.is_spear_pickup_pending:
                    # Filtra apenas alvos de emergência
                    emergency_candidates = [
                        c for c in final_candidates
                        if c.get("is_attacking_me", False) and max(abs(c["dist_x"]), abs(c["dist_y"])) <= 1
                    ]

                    if not emergency_candidates:
                        # Sem alvo de emergência - pula ataque neste ciclo
                        reason = "loot" if state.is_processing_loot else "spear pickup"
                        log_decision(f"⏸️ Pausa: {reason} em andamento (sem emergência)")
                        next_attack_time = 0  # Reseta delay para próximo ciclo
                        # Continua processamento mas não ataca
                        final_candidates = []
                    else:
                        # Há alvo de emergência - restringe candidatos
                        reason = "loot" if state.is_processing_loot else "spear pickup"
                        log_decision(f"⚠️ EMERGÊNCIA: {emergency_candidates[0]['name']} atacando durante {reason}!")
                        final_candidates = emergency_candidates
                # =============================================

                if len(final_candidates) > 0:
                    if next_attack_time == 0:
                        delay = random.uniform(min_delay, max_delay)
                        next_attack_time = time.time() + delay
                        log(f"⏳ Aguardando {delay:.2f}s para atacar...")
                        # Status: aguardando delay
                        target_name = final_candidates[0]['name'] if final_candidates else "alvo"
                        set_status(f"delay {delay:.1f}s → {target_name}")

                    if time.time() >= next_attack_time:
                        # ===== LOG DETALHADO DE DECISÃO =====
                        if debug_decisions or debug_mode:
                            print(f"\n{'='*60}")
                            print(f"[DECISION] 🎯 AVALIANDO NOVO ALVO")
                            print(f"{'='*60}")
                            print(f"[DECISION] Minha posição: ({my_x}, {my_y}, {my_z})")
                            print(f"[DECISION] KS Prevention: {'ATIVO' if ks_enabled else 'DESATIVADO'}")

                            # Lista candidatos
                            print(f"\n[DECISION] 📋 CANDIDATOS ({len(final_candidates)}):")
                            for idx, c in enumerate(final_candidates):
                                c_dist = max(abs(c['dist_x']), abs(c['dist_y']))
                                c_cost = get_distance_cost(walker, c['abs_x'] - my_x, c['abs_y'] - my_y, MELEE_RANGE)
                                attacking_me = "⚔️ ATACANDO" if c.get('is_attacking_me') else ""
                                print(f"  [{idx}] {c['name']} | pos:({c['abs_x']},{c['abs_y']}) | dist:{c_dist} | custo_A*:{c_cost} | HP:{c['hp']}% {attacking_me}")

                            # Lista entidades visíveis (potenciais players)
                            potential_players = [e for e in all_visible_entities if not any(t in e['name'] for t in targets_list)]
                            if potential_players:
                                print(f"\n[DECISION] 👥 PLAYERS VISÍVEIS ({len(potential_players)}):")
                                for e in potential_players:
                                    e_dist = max(abs(e['abs_x'] - my_x), abs(e['abs_y'] - my_y))
                                    print(f"  • {e['name']} | pos:({e['abs_x']},{e['abs_y']}) | dist_de_mim:{e_dist}")
                            else:
                                print(f"\n[DECISION] 👥 PLAYERS VISÍVEIS: Nenhum")
                            print(f"")

                        # RE-VALIDAÇÃO KS: Verifica engagement no momento do ataque
                        # Corrige cenário onde bot vê criatura antes do player
                        best = None
                        skipped_candidates = []  # Rastreia candidatos rejeitados

                        for candidate in final_candidates:
                            if candidate["id"] == current_target_id:
                                continue

                            c_dist = max(abs(candidate['dist_x']), abs(candidate['dist_y']))
                            c_cost = get_distance_cost(walker, candidate['abs_x'] - my_x, candidate['abs_y'] - my_y, MELEE_RANGE)

                            # Re-valida KS com lista ATUAL de entidades
                            # BYPASS: Se criatura está atacando o player, ignora KS check
                            if ks_enabled and not candidate.get("is_attacking_me", False):
                                # Log detalhado do KS check
                                if debug_decisions or debug_mode:
                                    print(f"[DECISION] 🔍 KS CHECK: {candidate['name']}")
                                    print(f"[DECISION]   Criatura em: ({candidate['abs_x']}, {candidate['abs_y']})")
                                    print(f"[DECISION]   Meu custo até ela (A*): {c_cost}")

                                    # Calcula distância de cada player até esta criatura
                                    for e in all_visible_entities:
                                        if e['name'] == current_name:
                                            continue
                                        if any(t in e['name'] for t in targets_list):
                                            continue
                                        player_cost = steps_to_adjacent(candidate['abs_x'] - e['abs_x'], candidate['abs_y'] - e['abs_y'], MELEE_RANGE) * 10
                                        comparison = "⚠️ PLAYER MAIS PERTO" if player_cost <= c_cost else "✓ Eu mais perto"
                                        print(f"[DECISION]   → {e['name']}: custo={player_cost} | {comparison}")

                                is_engaged, ks_reason = engagement_detector.is_engaged_with_other(
                                    {'id': candidate["id"], 'abs_x': candidate["abs_x"],
                                     'abs_y': candidate["abs_y"], 'hp': candidate["hp"]},
                                    current_name,
                                    (my_x, my_y),
                                    all_visible_entities,
                                    current_target_id,
                                    targets_list,
                                    walker=walker,
                                    attack_range=MELEE_RANGE,
                                    debug=False,  # Já logamos acima
                                    log_func=print
                                )
                                if is_engaged:
                                    if debug_decisions or debug_mode:
                                        print(f"[DECISION]   ❌ REJEITADO: {ks_reason}")
                                    log(f"⚠️ [KS RE-CHECK] {candidate['name']} engajada - pulando")
                                    skipped_candidates.append((candidate['name'], ks_reason))
                                    continue
                                else:
                                    if debug_decisions or debug_mode:
                                        print(f"[DECISION]   ✅ APROVADO: Nenhum player mais próximo")
                            elif candidate.get("is_attacking_me", False):
                                if debug_decisions or debug_mode:
                                    print(f"[DECISION] ⚡ KS BYPASS: {candidate['name']} está me atacando!")

                            best = candidate
                            break

                        # Log resumo da decisão
                        if debug_decisions or debug_mode:
                            if skipped_candidates:
                                print(f"\n[DECISION] 🚫 CANDIDATOS REJEITADOS POR KS:")
                                for name, reason in skipped_candidates:
                                    print(f"  • {name}: {reason}")
                            print(f"")

                        if best and best["id"] != current_target_id:
                            # Calcula distância Chebyshev para o alvo
                            dist_to_target = max(abs(best["dist_x"]), abs(best["dist_y"]))
                            best_cost = get_distance_cost(walker, best['abs_x'] - my_x, best['abs_y'] - my_y, MELEE_RANGE)

                            # LOG FINAL DE DECISÃO
                            if debug_decisions or debug_mode:
                                action = "FOLLOW" if follow_before_attack and dist_to_target > 1 else "ATTACK"
                                print(f"[DECISION] ✅ ALVO SELECIONADO: {best['name']}")
                                print(f"[DECISION]   Posição: ({best['abs_x']}, {best['abs_y']})")
                                print(f"[DECISION]   Distância: {dist_to_target} tiles | Custo A*: {best_cost}")
                                print(f"[DECISION]   HP: {best['hp']}%")
                                print(f"[DECISION]   Atacando-me: {'SIM' if best.get('is_attacking_me') else 'NÃO'}")
                                print(f"[DECISION]   Ação: {action}")
                                print(f"{'='*60}\n")

                            # DEBUG: Log da decisão follow/attack (verbose)
                            if debug_mode:
                                print(f"[FOLLOW-DEBUG] Novo alvo: {best['name']} (id={best['id']})")
                                print(f"[FOLLOW-DEBUG]   Distância: {dist_to_target} tiles")
                                print(f"[FOLLOW-DEBUG]   follow_before_attack={follow_before_attack}")
                                print(f"[FOLLOW-DEBUG]   Decisão: {'FOLLOW' if follow_before_attack and dist_to_target > 1 else 'ATTACK'}")

                            # FOLLOW BEFORE ATTACK: Quando spear_picker + range > 1
                            if follow_before_attack and dist_to_target > 1:
                                # Usa FOLLOW em vez de attack
                                log(f"🏃 SEGUINDO: {best['name']} (dist={dist_to_target})")
                                set_status(f"seguindo {best['name']}")
                                log_decision(f"🏃 SEGUINDO: {best['name']} (dist:{dist_to_target}) - ataca ao chegar dist<=1")
                                packet.follow(best["id"])

                                # Atualiza estado de follow
                                state.start_follow(best["id"])
                                is_currently_following = True
                                follow_target_id = best["id"]

                                if debug_mode:
                                    print(f"[FOLLOW-DEBUG] ✓ Pacote FOLLOW enviado (0xA2) para creature_id={best['id']}")
                                    print(f"[FOLLOW-DEBUG]   state.is_following={state.is_following}")
                                    print(f"[FOLLOW-DEBUG]   state.is_in_combat={state.is_in_combat}")
                            else:
                                # Attack normal (distância <= 1 ou follow desabilitado)
                                log(f"⚔️ ATACANDO: {best['name']}")
                                set_status(f"atacando {best['name']}")
                                ks_status = "KS: bypass (atacando)" if best.get('is_attacking_me') else "KS: pass"
                                log_decision(f"⚔️ ATACANDO: {best['name']} (HP:{best['hp']}%, dist:{dist_to_target}) | {ks_status}")
                                if not safe_attack(packet, best["id"], log):
                                    time.sleep(0.5)
                                    continue

                                # Para follow se estava seguindo
                                if is_currently_following:
                                    state.stop_follow()
                                    if debug_mode:
                                        print(f"[FOLLOW-DEBUG] ✓ Follow parado - trocou para ATTACK")
                                    is_currently_following = False
                                    follow_target_id = 0

                            current_target_id = best["id"]
                            current_monitored_id = best["id"]
                            last_target_data = best.copy()
                            monitor.start(best["id"], best["name"], best["hp"])

                            # Reset death state when attacking new target
                            death_state = DeathState.ALIVE
                            dying_creature_data = None
                            death_timestamp = None

                            next_attack_time = 0
                            gauss_wait(0.5, 20)
                        elif not best and len(final_candidates) > 0:
                            # Todos engajados - reseta para tentar novamente
                            if debug_decisions or debug_mode:
                                print(f"[DECISION] ⚠️ NENHUM ALVO VÁLIDO")
                                print(f"[DECISION]   Todos os {len(final_candidates)} candidatos foram rejeitados por KS")
                                print(f"[DECISION]   Aguardando próximo ciclo...")
                                print(f"{'='*60}\n")
                            next_attack_time = 0

            # Throttle dinâmico baseado no estado
            if current_target_id != 0:
                # EM COMBATE: scan máximo para reagir rápido a mudanças
                if last_target_data:
                    set_status(f"em combate: {last_target_data.get('name', '?')} ({last_target_data.get('hp', 0)}%)")
                time.sleep(SCAN_DELAY_COMBAT)
            elif len(valid_candidates) > 0:
                # TEM ALVOS: scan médio (vai atacar em breve após delay humanizado)
                time.sleep(SCAN_DELAY_TARGETS)
            else:
                # SEM ALVOS: scan lento (só monitorando battle list)
                set_status("procurando alvos...")
                time.sleep(SCAN_DELAY_IDLE)

        except Exception as e:
            print(f"[ERRO LOOP] {e}")
            time.sleep(1)