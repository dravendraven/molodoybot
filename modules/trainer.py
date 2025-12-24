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

# CORREÇÃO: Importar scan_containers do local original (auto_loot.py)
from modules.auto_loot import scan_containers
from core.player_core import get_connected_char_name
from core.bot_state import state
from core.config_utils import make_config_getter
from core.map_analyzer import MapAnalyzer
from core.astar_walker import AStarWalker

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

def parse_creature_from_bytes(raw_bytes):
    """
    Parseia dados de uma criatura a partir de um bloco de bytes (batch read).
    Reduz de 7 syscalls para 1 por criatura.

    Returns:
        dict com id, name, x, y, z, hp, visible ou None se inválido
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

        return {
            'id': c_id,
            'name': name,
            'x': cx,
            'y': cy,
            'z': z,
            'hp': hp,
            'visible': visible
        }
    except:
        return None

def is_valid_creature_slot(creature):
    """
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

            # Skip se é criatura alvo (monster/creature do jogo)
            # Assume que se está em targets_list, é uma criatura, não um player
            is_target_creature = any(target in entity['name'] for target in targets_list)
            if is_target_creature:
                if debug:
                    log_func(f"  [DETECT] Skip: Criatura alvo '{entity['name']}'")
                continue

            # Se chegou aqui, é potencialmente um player real
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

def trainer_loop(pm, base_addr, hwnd, monitor, check_running, config):

    get_cfg = make_config_getter(config)

    current_monitored_id = 0
    current_target_id = 0  # Inicializado aqui para uso consistente
    last_target_data = None
    next_attack_time = 0

    # Retargeting State
    last_reachability_check_time = 0.0
    became_unreachable_time = None

    # Será inicializado dentro do loop com debug_mode
    mapper = None
    analyzer = None
    walker = None

    # PacketManager para envio de pacotes
    packet = PacketManager(pm, base_addr)

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
            time.sleep(0.5)
            continue

        # Protege ciclo de runemaking - não atacar durante runemaking
        if state.is_runemaking:
            time.sleep(0.5)
            continue
        
        min_delay = get_cfg('min_delay', 1.0)
        max_delay = get_cfg('max_delay', 2.0)
        trigger_range = get_cfg('range', 1)  # Range para ACIONAR ataque (não confundir com MELEE_RANGE)
        log = get_cfg('log_callback', print)
        debug_mode = get_cfg('debug_mode', False)
        loot_enabled = get_cfg('loot_enabled', False)
        targets_list = get_cfg('targets', [])
        ignore_first = get_cfg('ignore_first', False)
        ks_enabled = get_cfg('ks_prevention_enabled', KS_PREVENTION_ENABLED)

        # Log de configuração anti-KS (apenas primeira iteração)
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

        # Inicializa componentes de pathfinding na primeira iteração com debug_mode
        if mapper is None:
            mapper = MemoryMap(pm, base_addr)
            analyzer = MapAnalyzer(mapper)
            walker = AStarWalker(analyzer, max_depth=150, debug=debug_mode)

        try:  
            player_id = pm.read_int(base_addr + OFFSET_PLAYER_ID)

            current_name = get_my_char_name(pm, base_addr)
            if not current_name: 
                time.sleep(0.5); continue
            
            target_addr = base_addr + TARGET_ID_PTR
            list_start = base_addr + TARGET_ID_PTR + REL_FIRST_ID
            my_x, my_y, my_z = get_player_pos(pm, base_addr)
            
            if my_z == 0: 
                time.sleep(0.2)
                continue
            
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

            # SCAN ADAPTATIVO: contador de slots inválidos consecutivos
            invalid_streak = 0

            for i in range(MAX_CREATURES):
                slot = list_start + (i * STEP_SIZE)
                try:
                    # BATCH READ: 1 syscall ao invés de 7
                    raw_bytes = pm.read_bytes(slot, STEP_SIZE)
                    creature = parse_creature_from_bytes(raw_bytes)

                    # EARLY-EXIT: Validação robusta para detectar fim da lista
                    if not is_valid_creature_slot(creature):
                        invalid_streak += 1
                        if invalid_streak >= INVALID_SLOT_THRESHOLD:
                            if debug_mode:
                                print(f"   [EARLY-EXIT] {invalid_streak} slots inválidos consecutivos - parando scan no slot {i}")
                            break
                        continue
                    else:
                        invalid_streak = 0  # Reset quando encontra slot válido

                    if creature:
                        c_id = creature['id']
                        name = creature['name']
                        vis = creature['visible']
                        z = creature['z']
                        cx = creature['x']
                        cy = creature['y']
                        hp = creature['hp']

                        dist_x = abs(my_x - cx)
                        dist_y = abs(my_y - cy)
                        is_in_range = (dist_x <= trigger_range and dist_y <= trigger_range)

                        if debug_mode: print(f"Slot {i}: {name} (Vis:{vis} Z:{z} HP:{hp} Dist:({dist_x},{dist_y}))")

                        if name == current_name: continue

                        is_on_battle_list = (vis == 1 and z == my_z)

                        if is_on_battle_list:
                            # Adiciona a lista de entidades visíveis (para KS detection)
                            all_visible_entities.append({
                                'id': c_id,
                                'name': name,
                                'abs_x': cx,
                                'abs_y': cy,
                                'hp': hp
                            })

                            if debug_mode: print(f"   [LINHA {visual_line_count}] -> {name} (ID: {c_id})")
                            current_line = visual_line_count
                            visual_line_count += 1

                            if any(t in name for t in targets_list):
                                if is_in_range and hp > 0:

                                    # NOVO: Atualiza histórico de HP para KS detection
                                    engagement_detector.update_hp(c_id, hp)

                                    is_reachable = True

                                    # Calculamos posição relativa
                                    rel_x = cx - my_x
                                    rel_y = cy - my_y
                                    dist_sqm = max(abs(rel_x), abs(rel_y))

                                    # DEBUG: Log antes de verificar acessibilidade
                                    if debug_mode: print(f"   📍 Checking {name} (ID:{c_id}) at ({cx},{cy}) | Rel:({rel_x},{rel_y}) Dist:{dist_sqm}")

                                    # SEMPRE verificar acessibilidade com A*, exceto se dist == 0 (mesmo tile)
                                    if dist_sqm == 0:
                                        # Mesmo tile que o player - sempre acessível (não deveria acontecer)
                                        if debug_mode: print(f"      ⚠️ Monstro no mesmo tile (dist=0)")
                                    else:
                                        # Pergunta ao A*: "Consigo dar o primeiro passo em direção a esse destino?"
                                        next_step = walker.get_next_step(rel_x, rel_y, activate_fallback=False)

                                        # Se next_step for None, o caminho está bloqueado (parede ou outro monstro)
                                        if next_step is None:
                                            is_reachable = False
                                            if debug_mode: print(f"      ❌ INACESSÍVEL: {name} (A* retornou None)")
                                        else:
                                            if debug_mode: print(f"      ✅ ACESSÍVEL: Next step = {next_step}")

                                    if is_reachable:
                                        # NOVO: Verifica KS prevention antes de adicionar ao candidatos
                                        skip_ks = False

                                        if ks_enabled:
                                            # Log pré-KS check
                                            if debug_mode:
                                                print(f"\n[KS CHECK] Avaliando {name} (ID:{c_id})")
                                                print(f"[KS CHECK]   Posição: ({cx}, {cy}) | Rel: ({rel_x}, {rel_y})")
                                                print(f"[KS CHECK]   HP: {hp}%")
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
                                                {'id': c_id, 'abs_x': cx, 'abs_y': cy, 'hp': hp},
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

                                        if not skip_ks:
                                            if debug_mode: print(f"      → CANDIDATO: HP:{hp} Dist:({dist_x},{dist_y})")
                                            valid_candidates.append({
                                                "id": c_id,
                                                "name": name,
                                                "hp": hp,
                                                "dist_x": dist_x,
                                                "dist_y": dist_y,
                                                "abs_x": cx,
                                                "abs_y": cy,
                                                "z": z,
                                                "is_in_range": is_in_range,
                                                "line": current_line
                                            })
                except: continue

            if debug_mode:
                print(f"--- FIM DO SCAN ---")

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
                                    log(f"⚔️ RETARGET: {nearest['name']} (custo: {cost})")

                                    # Ataca novo alvo
                                    packet.attack(nearest["id"])

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
                    target_in_battlelist = None

                    for i in range(MAX_CREATURES):
                        slot = list_start + (i * STEP_SIZE)
                        try:
                            # BATCH READ: 1 syscall ao invés de 7
                            raw_bytes = pm.read_bytes(slot, STEP_SIZE)
                            creature = parse_creature_from_bytes(raw_bytes)

                            if creature and creature['id'] == current_target_id:
                                # Encontrou na battle list!
                                target_in_battlelist = {
                                    'id': creature['id'],
                                    'name': creature['name'],
                                    'hp': creature['hp'],
                                    'abs_x': creature['x'],
                                    'abs_y': creature['y'],
                                    'z': creature['z'],
                                    'visible': creature['visible']
                                }
                                break
                        except:
                            continue

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
                                            log(f"⚔️ RETARGET: {nearest['name']} (custo: {cost})")
                                            packet.attack(nearest["id"])
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

           # CENÁRIO B: Alvo Sumiu
            elif current_target_id == 0 and current_monitored_id != 0:
                target_still_alive = False
                if last_target_data:
                    for m in valid_candidates:
                        if m["id"] == last_target_data["id"]:
                            target_still_alive = True
                            break
                
                if target_still_alive:
                    log("🛑 Ataque interrompido (Monstro ainda vivo).")
                    monitor.stop_and_report()
                    current_monitored_id = 0
                    last_target_data = None
                    became_unreachable_time = None
                    should_attack_new = True 
                
                else:
                    log("💀 Alvo eliminado.")
                    
                    if last_target_data and loot_enabled:
                        gauss_wait(0.9, 15)

                        # CHAMA FUNÇÃO COM LÓGICA DE INDEX DINÂMICO
                        success = open_corpse_via_packet(pm, base_addr, last_target_data, player_id, log_func=log)
                        
                        if success:
                            log(f"📂 Corpo aberto (Packet).")
                            gauss_wait(0.5, 20)

                    elif last_target_data and not loot_enabled:
                        if debug_mode: log("ℹ️ Auto Loot desligado.")

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
                
                if len(final_candidates) > 0:
                    if next_attack_time == 0:
                        delay = random.uniform(min_delay, max_delay)
                        next_attack_time = time.time() + delay
                        log(f"⏳ Aguardando {delay:.2f}s para atacar...")

                    if time.time() >= next_attack_time:
                        # RE-VALIDAÇÃO KS: Verifica engagement no momento do ataque
                        # Corrige cenário onde bot vê criatura antes do player
                        best = None
                        for candidate in final_candidates:
                            if candidate["id"] == current_target_id:
                                continue

                            # Re-valida KS com lista ATUAL de entidades
                            if ks_enabled:
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
                                    debug=debug_mode,
                                    log_func=print
                                )
                                if is_engaged:
                                    log(f"⚠️ [KS RE-CHECK] {candidate['name']} engajada - pulando")
                                    continue

                            best = candidate
                            break

                        if best and best["id"] != current_target_id:
                            log(f"⚔️ ATACANDO: {best['name']}")
                            packet.attack(best["id"])

                            current_target_id = best["id"]
                            current_monitored_id = best["id"]
                            last_target_data = best.copy()
                            monitor.start(best["id"], best["name"], best["hp"])

                            next_attack_time = 0
                            gauss_wait(0.5, 20)
                        elif not best and len(final_candidates) > 0:
                            # Todos engajados - reseta para tentar novamente
                            next_attack_time = 0

            # Throttle dinâmico baseado no estado
            if current_target_id != 0:
                # EM COMBATE: scan máximo para reagir rápido a mudanças
                time.sleep(SCAN_DELAY_COMBAT)
            elif len(valid_candidates) > 0:
                # TEM ALVOS: scan médio (vai atacar em breve após delay humanizado)
                time.sleep(SCAN_DELAY_TARGETS)
            else:
                # SEM ALVOS: scan lento (só monitorando battle list)
                time.sleep(SCAN_DELAY_IDLE)

        except Exception as e:
            print(f"[ERRO LOOP] {e}")
            time.sleep(1)