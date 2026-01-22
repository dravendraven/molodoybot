"""
Spear Picker Module - Pega spears do chao automaticamente.

Funcionalidade para Paladinos:
- Identifica spears (ID 3277) no chao em tiles adjacentes
- Move itens que estao acima da spear (ex: corpo de criatura) para tile adjacente
- Verifica cap do personagem e calcula quantas pode pegar (20 oz cada)
- Move para a mao que ja tem spear ou esta vazia
- Repete o processo (quando ataca com spear, ela cai no tile da criatura)

Sistema de Scanning (2 scans independentes):

SCAN 1 - Monitoramento de Mão (150ms):
  - Verifica quantidade de spears na mão constantemente
  - Detecta quando houve ataque (spear count diminuiu)
  - Roda SEMPRE, independente do estado

SCAN 2 - Busca no Chão (200ms):
  - Escaneia tiles adjacentes procurando spears
  - Roda APENAS quando spears < max_spears
  - Ativado automaticamente pelo SCAN 1

Delays Humanizados (aplicados APENAS em ações):
  - Tempo de reação ao detectar spear: 250ms + variação gaussiana 30%
  - Tempo entre move_items: 250ms + variação gaussiana 30%
"""

import time
import random
import threading

from config import (
    OFFSET_PLAYER_ID,
    SLOT_RIGHT,
    SLOT_LEFT,
)
from database.movable_items_db import is_movable
from core.map_core import get_player_pos
from core.memory_map import MemoryMap
from core.map_analyzer import MapAnalyzer
from core.packet import PacketManager, get_ground_pos, get_inventory_pos
from core.packet_mutex import PacketMutex
from core.player_core import get_player_cap
from core.inventory_core import get_item_id_in_hand, get_spear_count_in_hands
from core.bot_state import state
from utils.timing import gauss_wait

# Constantes do modulo
SPEAR_ID = 3277          # ID da spear
SPEAR_WEIGHT = 20.0      # Peso de cada spear em oz

# Decremento de probabilidade por spear na mao (15% por spear)
PICK_CHANCE_DECREMENT = 0.15

# Tiles a escanear (proprio tile + adjacentes incluindo diagonais)
ADJACENT_TILES = [
    (0,  0),                      # Proprio tile do jogador
    (-1, -1), (0, -1), (1, -1),   # Norte
    (-1,  0),          (1,  0),   # Leste/Oeste
    (-1,  1), (0,  1), (1,  1),   # Sul
]

# IDs de criaturas/players (item ID 99 na memoria do mapa)
CREATURE_ID = 99

# Chance de dropar no tile do player (50%)
DROP_ON_PLAYER_CHANCE = 0.5

# ========== DELAYS DE SCAN (RÁPIDOS, SEM HUMANIZAÇÃO) ==========
# Estes delays controlam a velocidade dos loops de monitoramento
SCAN_HAND_DELAY = 0.15         # Delay entre scans de spears na mao (monitoramento constante)
SCAN_TILES_DELAY = 0.500         # Delay entre scans de tiles ao redor (procurando spears no chao)

# ========== DELAYS HUMANIZADOS (APLICADOS APENAS EM AÇÕES) ==========
# Estes delays simulam tempo de reação humana e são aplicados APENAS em move_item
REACTION_DELAY_MIN = 0.25      # Delay minimo de reacao ao detectar spear no chao (250ms base)
MOVE_ITEM_DELAY_MIN = 0.50     # Delay minimo global apos QUALQUER move_item (250ms base)
# Nota: Variacao gaussiana de ~30% sera aplicada sobre estes valores base


class SpearPickerState:
    """
    Estado compartilhado entre threads do spear picker (thread-safe).

    Thread Monitor: atualiza via update_from_hand_scan()
    Thread Ações: lê via get_action_state() e atualiza via update_after_pickup()
    """

    def __init__(self):
        self.last_spear_count = 0
        self.needs_spears = False  # Flag: precisa procurar spears no chão
        self.max_spears = 3
        self.lock = threading.Lock()

    def update_from_hand_scan(self, current_spears, max_spears):
        """
        Atualiza estado baseado em scan de mão (Thread Monitor).

        Args:
            current_spears: Quantidade atual de spears na mão
            max_spears: Quantidade máxima configurada

        Returns:
            True se detectou ataque (spear count diminuiu)
        """
        with self.lock:
            attack_detected = current_spears < self.last_spear_count
            self.last_spear_count = current_spears
            self.max_spears = max_spears
            self.needs_spears = (current_spears < max_spears)
            return attack_detected

    def get_action_state(self):
        """
        Retorna cópia do estado para thread de ações.

        Returns:
            Dict com current_spears, max_spears, needs_spears
        """
        with self.lock:
            return {
                'current_spears': self.last_spear_count,
                'max_spears': self.max_spears,
                'needs_spears': self.needs_spears
            }

    def update_after_pickup(self, spears_picked):
        """
        Atualiza count após pegar spears (Thread Ações).

        Args:
            spears_picked: Quantidade de spears que foram pegas
        """
        with self.lock:
            self.last_spear_count += spears_picked
            self.needs_spears = (self.last_spear_count < self.max_spears)


def find_target_hand(pm, base_addr):
    """
    Encontra a mao alvo para colocar a spear.

    Prioridade:
    1. Mao que ja tem spear (stack)
    2. Mao vazia
    3. None se ambas ocupadas com outros items

    Returns:
        SLOT_RIGHT, SLOT_LEFT ou None
    """
    right_id = get_item_id_in_hand(pm, base_addr, SLOT_RIGHT)
    left_id = get_item_id_in_hand(pm, base_addr, SLOT_LEFT)

    # Prioridade 1: Mao que ja tem spear
    if right_id == SPEAR_ID:
        return SLOT_RIGHT
    if left_id == SPEAR_ID:
        return SLOT_LEFT

    # Prioridade 2: Mao vazia
    if right_id == 0:
        return SLOT_RIGHT
    if left_id == 0:
        return SLOT_LEFT

    # Ambas ocupadas com outros items
    return None


def calculate_pick_probability(current_count, max_count):
    """
    Calcula a probabilidade de pegar a spear baseado em quantas tem na mao.

    Logica humanizada - decremento fixo de 15% por spear:
    - 0 spears na mao: 100% de chance
    - 1 spear na mao: 85% de chance
    - 2 spears na mao: 70% de chance
    - 3 spears na mao: 55% de chance
    - 4 spears na mao: 40% de chance
    - max spears na mao: 0% (nao tenta pegar)

    Exemplo com max=2:
    - 0 spears: 100%
    - 1 spear: 85%
    - 2 spears: 0% (nao tenta)

    Exemplo com max=5:
    - 0 spears: 100%
    - 1 spear: 85%
    - 2 spears: 70%
    - 3 spears: 55%
    - 4 spears: 40%
    - 5 spears: 0% (nao tenta)

    Args:
        current_count: Quantidade atual de spears na mao
        max_count: Quantidade maxima configurada

    Returns:
        Float entre 0.0 e 1.0 representando a probabilidade
    """
    if current_count >= max_count:
        return 0.0  # Ja esta cheio, nao tenta pegar

    # Formula simples: 100% - (15% * spears_na_mao)
    # 0 spears = 100%, 1 spear = 85%, 2 spears = 70%, etc.
    chance = 1.0 - (PICK_CHANCE_DECREMENT * current_count)

    # Garante que nao fique negativo
    return max(0.0, chance)


def find_spear_on_adjacent_tiles(mapper, my_x, my_y, my_z):
    """
    Procura spears em tiles adjacentes ao player.

    Returns:
        Tuple (abs_x, abs_y, z, list_index, rel_x, rel_y, tile) ou None se nao encontrar

    Nota: list_index e o indice na lista tile.items (0=fundo, len-1=topo)
    """
    for rel_x, rel_y in ADJACENT_TILES:
        tile = mapper.get_tile_visible(rel_x, rel_y)
        if tile is None:
            continue

        # Procura spear no tile (do topo para baixo)
        for i in range(len(tile.items) - 1, -1, -1):
            if tile.items[i] == SPEAR_ID:
                abs_x = my_x + rel_x
                abs_y = my_y + rel_y
                return (abs_x, abs_y, my_z, i, rel_x, rel_y, tile)

    return None


def find_drop_tile(mapper, spear_rel_x, spear_rel_y, my_x, my_y, my_z):
    """
    Encontra um tile WALKABLE para mover itens que estao acima da spear.

    Requisitos:
    - Tile deve ser walkable (sem paredes, arvores, etc.)
    - Tile deve ser adjacente ao player (distancia <= 1)
    - Tile deve ser adjacente ao tile da spear (distancia <= 1)

    Logica randomizada:
    - 50% das vezes: tile do proprio player
    - 50% das vezes: tile adjacente ao tile da spear (se walkable)

    Args:
        mapper: MemoryMap instance
        spear_rel_x, spear_rel_y: Posicao relativa do tile com a spear
        my_x, my_y, my_z: Posicao absoluta do player

    Returns:
        Tuple (abs_x, abs_y, z) ou None se nao encontrar
    """
    # Cria MapAnalyzer para verificar walkability
    analyzer = MapAnalyzer(mapper)

    # 50% chance de dropar no tile do player (sempre walkable)
    if random.random() < DROP_ON_PLAYER_CHANCE:
        return (my_x, my_y, my_z)

    # Tenta tiles adjacentes ao tile da spear (ordem randomizada)
    adjacent_options = list(ADJACENT_TILES)
    random.shuffle(adjacent_options)

    for dx, dy in adjacent_options:
        check_rel_x = spear_rel_x + dx
        check_rel_y = spear_rel_y + dy

        # Pula o tile da spear (nao faz sentido mover para o mesmo tile)
        if dx == 0 and dy == 0:
            continue

        # Verifica se esta no range visivel
        if abs(check_rel_x) > 7 or abs(check_rel_y) > 7:
            continue

        # Verifica se tile é adjacente ao player (distancia <= 1)
        player_dist = max(abs(check_rel_x), abs(check_rel_y))
        if player_dist > 1:
            continue

        # Verifica se tile existe
        tile = mapper.get_tile_visible(check_rel_x, check_rel_y)
        if tile is None or len(tile.items) == 0:
            continue

        # CRITICAL: Verifica se tile é WALKABLE (sem paredes, arvores, etc.)
        props = analyzer.get_tile_properties(check_rel_x, check_rel_y)
        if not props['walkable']:
            continue

        # Tile valido: walkable e adjacente ao player e spear
        return (my_x + check_rel_x, my_y + check_rel_y, my_z)

    # Fallback: tile do player
    return (my_x, my_y, my_z)


def is_movable_item(item_id):
    """
    Determina se um item pode ser movido.

    Baseado nas flags do objects.srv:
    - Take = item pode ser pego/movido (corpos, itens, etc.)
    - Unmove/Bottom = objeto do mapa (chao, paredes, splashes, etc.)

    Args:
        item_id: ID do item

    Returns:
        True se o item pode ser movido
    """
    # Criaturas (ID=99) sao um caso especial - nao podem ser movidas
    if item_id == CREATURE_ID:
        return False

    # Consulta a database gerada do objects.srv
    result = is_movable(item_id)

    # Se o item nao esta na database, assume que NAO pode mover (mais seguro)
    if result is None:
        return False

    return result


def get_stack_count(tile, item_index):
    """
    Retorna a quantidade de itens empilhados em um slot do tile.

    Para itens stackaveis (como spears), o count esta em data1.
    Se data1=0, assume count=1.

    Args:
        tile: MemoryTile
        item_index: Indice do item na lista tile.items

    Returns:
        Quantidade de itens empilhados (minimo 1)
    """
    if not hasattr(tile, 'items_debug') or item_index >= len(tile.items_debug):
        return 1

    _, data1, _, _ = tile.items_debug[item_index]

    # Para stackaveis, data1 contem o count
    # Se data1=0, pode ser 1 item ou item nao-stackavel
    return data1 if data1 > 0 else 1


def get_items_above_spear(tile, spear_list_index):
    """
    Retorna lista de itens MOVEIS acima da spear no stack.

    Ordem dos MOVABLES na memoria (INVERTIDA):
    - Primeiro movable (menor idx) = TOPO visual
    - Ultimo movable (maior idx) = FUNDO visual

    Items ACIMA da spear = movables com idx MENOR que spear_list_index

    Args:
        tile: MemoryTile
        spear_list_index: Indice da spear na lista tile.items

    Returns:
        Lista de (item_id, list_index) do topo para baixo
    """
    items_above = []

    # Itens acima da spear = indices MENORES que spear_list_index
    # Comeca em 1 para pular o chao (idx=0)
    for i in range(1, spear_list_index):
        item_id = tile.items[i]

        # Verifica se e movivel usando database do objects.srv
        if not is_movable_item(item_id):
            continue

        items_above.append((item_id, i))

    return items_above


def monitor_hand_loop(pm, base_addr, check_running, get_enabled, get_max_spears, shared_state):
    """
    Thread de monitoramento - monitora spears na mão constantemente.

    Responsabilidades:
    - Ler quantidade de spears na mão a cada 150ms
    - Detectar ataques (count diminuiu)
    - Atualizar flag needs_spears
    - Nunca bloqueia, sempre roda

    Args:
        pm: Instancia do Pymem
        base_addr: Endereco base do processo
        check_running: Funcao que retorna False para encerrar
        get_enabled: Funcao que retorna True/False se modulo esta ativo
        get_max_spears: Funcao que retorna o maximo de spears configurado
        shared_state: Instancia de SpearPickerState (estado compartilhado)
    """
    print("[Spear Monitor] Thread iniciada")

    while True:
        if check_running and not check_running():
            print("[Spear Monitor] Thread encerrada")
            return

        if not get_enabled():
            time.sleep(1)
            continue

        if pm is None:
            time.sleep(1)
            continue

        try:
            # Le spears na mão
            current_spears, _ = get_spear_count_in_hands(pm, base_addr, SPEAR_ID)
            max_spears = get_max_spears()

            # Atualiza estado compartilhado (thread-safe)
            attack_detected = shared_state.update_from_hand_scan(current_spears, max_spears)

            if attack_detected:
                print(f"[Spear Monitor] Ataque detectado! Spears: {current_spears}")

            # Delay fixo de scan (sem humanização)
            time.sleep(SCAN_HAND_DELAY)

        except Exception as e:
            print(f"[Spear Monitor] Erro: {e}")
            time.sleep(1)


def action_loop(pm, base_addr, check_running, get_enabled, shared_state):
    """
    Thread de ações - busca e pega spears do chão.

    Responsabilidades:
    - Escanear tiles ao redor quando needs_spears=True
    - Executar ações de move_item (com delays humanizados)
    - Atualizar estado após pegar spears
    - Pode bloquear durante ações, mas não afeta monitor

    Args:
        pm: Instancia do Pymem
        base_addr: Endereco base do processo
        check_running: Funcao que retorna False para encerrar
        get_enabled: Funcao que retorna True/False se modulo esta ativo
        shared_state: Instancia de SpearPickerState (estado compartilhado)
    """
    print("[Spear Action] Thread iniciada")

    mapper = MemoryMap(pm, base_addr)
    packet = PacketManager(pm, base_addr)

    while True:
        if check_running and not check_running():
            print("[Spear Action] Thread encerrada")
            return

        if not get_enabled():
            time.sleep(1)
            continue

        if pm is None:
            time.sleep(1)
            continue

        try:
            # Verifica se precisa procurar spears (thread-safe)
            state_data = shared_state.get_action_state()

            if not state_data['needs_spears']:
                time.sleep(SCAN_TILES_DELAY)
                continue

            # ===== VERIFICAÇÃO DE LOOT PRIORITY =====
            # Pausa spear picker durante ciclo de loot (CORPSE_READY → fim)
            # Previne conflitos durante abertura do corpo e processamento de loot
            if state.is_processing_loot:
                time.sleep(SCAN_TILES_DELAY)  # 200ms
                continue
            # ==========================================

            # === PRÉ-CONDIÇÕES ===
            my_x, my_y, my_z = get_player_pos(pm, base_addr)
            if my_z == 0:
                continue

            current_cap = get_player_cap(pm, base_addr)
            if current_cap < SPEAR_WEIGHT:
                continue

            target_hand = find_target_hand(pm, base_addr)
            if target_hand is None:
                continue

            # === PROBABILIDADE ===
            current_spears = state_data['current_spears']
            max_spears = state_data['max_spears']

            pick_chance = calculate_pick_probability(current_spears, max_spears)
            roll = random.random()
            if roll > pick_chance:
                print(f"[Spear Action] Nao vai pegar (prob={pick_chance:.1%}, roll={roll:.1%})")
                time.sleep(SCAN_TILES_DELAY)
                continue

            print(f"[Spear Action] Vai pegar spear (prob={pick_chance:.1%}, roll={roll:.1%}) - spears={current_spears}/{max_spears}")

            # === BUSCA SPEAR NO CHÃO ===
            player_id = pm.read_int(base_addr + OFFSET_PLAYER_ID)
            if not mapper.read_full_map(player_id):
                time.sleep(0.5)
                continue

            spear_location = find_spear_on_adjacent_tiles(mapper, my_x, my_y, my_z)

            if spear_location is None:
                time.sleep(SCAN_TILES_DELAY)
                continue

            pre_abs_x, pre_abs_y, _, _, pre_rel_x, pre_rel_y, _ = spear_location
            print(f"[Spear Action] Detectou spear em tile ({pre_abs_x},{pre_abs_y}) rel=({pre_rel_x},{pre_rel_y})")

            # ========== DELAY DE REAÇÃO HUMANIZADO ==========
            # Simula tempo para "perceber" que tem spear no chão (min 250ms + variacao)
            gauss_wait(REACTION_DELAY_MIN, 30)

            # ===== VERIFICAÇÃO CRÍTICA: Loot pode ter sido aberto durante delay =====
            if state.is_processing_loot:
                print("[Spear Action] Loot foi aberto durante delay de reação - abortando")
                continue
            # ========================================================================

            # === RELE ESTADO (pode ter mudado durante delay de reação) ===
            my_x, my_y, my_z = get_player_pos(pm, base_addr)
            current_cap = get_player_cap(pm, base_addr)
            state_data = shared_state.get_action_state()  # Estado atualizado pelo monitor
            current_spears = state_data['current_spears']
            max_spears = state_data['max_spears']

            if current_spears >= max_spears:
                print("[Spear Action] Ficou cheio durante delay de reacao")
                continue

            # Rele mapa
            if not mapper.read_full_map(player_id):
                time.sleep(0.3)
                continue

            spear_location = find_spear_on_adjacent_tiles(mapper, my_x, my_y, my_z)
            if spear_location is None:
                print("[Spear Action] Spear sumiu durante delay de reacao")
                continue

            abs_x, abs_y, z, spear_list_index, rel_x, rel_y, tile = spear_location

            # === DEBUG: Mostra todos os items no tile ===
            print(f"[Spear Action] Tile ({abs_x}, {abs_y}, {z}) rel=({rel_x}, {rel_y}) - {len(tile.items)} items:")
            first_movable = -1
            for idx, item_id in enumerate(tile.items):
                data1 = 0
                data2 = 0
                if hasattr(tile, 'items_debug') and idx < len(tile.items_debug):
                    _, data1, data2, _ = tile.items_debug[idx]

                can_move = is_movable_item(item_id)
                item_type = "MOVABLE" if can_move else "MAP_OBJ"

                if can_move and first_movable == -1:
                    first_movable = idx

                marker = ""
                if item_id == SPEAR_ID:
                    marker = f" <-- SPEAR"
                elif item_id == CREATURE_ID:
                    marker = " (CREATURE)"

                print(f"  [idx={idx}] ID={item_id} | {item_type} data1={data1} data2={data2} movable={can_move}{marker}")

            print(f"[Spear Action] Spear em idx={spear_list_index}, primeiro_movable={first_movable}")

            # === VERIFICAR ITEMS ACIMA DA SPEAR ===
            items_above = get_items_above_spear(tile, spear_list_index)
            if items_above:
                print(f"[Spear Action] {len(items_above)} items MOVEIS acima da spear:")
                for item_id, list_idx in items_above:
                    print(f"  - ID={item_id} em idx={list_idx}")
            else:
                print(f"[Spear Action] Nenhum item movel acima da spear (idx < {spear_list_index})")

            # === MOVER BLOQUEADORES (se necessário) ===
            if items_above:
                # ===== VERIFICAÇÃO DEFENSIVA: Loot pode ter sido aberto antes de find_drop_tile =====
                if state.is_processing_loot:
                    print("[Spear Action] Loot foi aberto antes de mover bloqueadores - abortando")
                    continue
                # =====================================================================================

                drop_tile = find_drop_tile(mapper, rel_x, rel_y, my_x, my_y, my_z)

                if drop_tile is None:
                    print("[Spear Action] Nao encontrou tile valido para mover items bloqueadores")
                    continue

                drop_x, drop_y, drop_z = drop_tile
                print(f"[Spear Action] Movendo {len(items_above)} items bloqueadores para tile drop=({drop_x}, {drop_y}, {drop_z})")

                for idx_move, (item_id, list_idx) in enumerate(items_above):
                    # ===== VERIFICAÇÃO CRÍTICA: Loot pode abrir durante delays entre moves =====
                    if state.is_processing_loot:
                        print(f"[Spear Action] Loot foi aberto durante move #{idx_move} de bloqueadores - abortando")
                        continue
                    # ============================================================================

                    from_pos = get_ground_pos(abs_x, abs_y, z)
                    to_pos = get_ground_pos(drop_x, drop_y, drop_z)
                    top_stack_pos = len(tile.items) - 1

                    with PacketMutex("spear_picker"):
                        packet.move_item(from_pos, to_pos, item_id, 1, top_stack_pos, apply_delay=True)

                    print(f"[Spear Action] Moveu item ID={item_id} (idx={list_idx}, stack_pos={top_stack_pos}) de ({abs_x},{abs_y},{z}) -> ({drop_x},{drop_y},{drop_z})")

                    if len(tile.items) > 1:
                        tile.items.pop(1)

                    # ========== DELAY GLOBAL ENTRE MOVE_ITEMS ==========
                    if idx_move < len(items_above) - 1:
                        gauss_wait(MOVE_ITEM_DELAY_MIN, 30)
                        print(f"[Spear Action] Delay global entre move_items: {MOVE_ITEM_DELAY_MIN}s base")

                # Rele mapa após mover bloqueadores
                if not mapper.read_full_map(player_id):
                    time.sleep(0.3)
                    continue

                # ========== DELAY GLOBAL APÓS MOVER BLOQUEADORES ==========
                gauss_wait(MOVE_ITEM_DELAY_MIN, 30)
                print(f"[Spear Action] Delay global após move_items antes de pegar spear")

                # ===== VERIFICAÇÃO CRÍTICA: Loot pode ter sido aberto durante moves dos bloqueadores =====
                if state.is_processing_loot:
                    print("[Spear Action] Loot foi aberto durante move dos bloqueadores - abortando")
                    continue
                # ================================================================================================

            # === CALCULA STACK_POS ===
            if items_above:
                new_tile = mapper.get_tile_visible(rel_x, rel_y)
                if new_tile:
                    spear_stack_pos = len(new_tile.items) - 1
                else:
                    spear_stack_pos = len(tile.items) - 1
            else:
                first_movable_idx = 0
                for idx_check in range(len(tile.items)):
                    item_id_check = tile.items[idx_check]
                    if is_movable_item(item_id_check):
                        first_movable_idx = idx_check
                        data1 = 0
                        data2 = 0
                        if hasattr(tile, 'items_debug') and idx_check < len(tile.items_debug):
                            _, data1, data2, _ = tile.items_debug[idx_check]
                        print(f"[Spear Action] Primeiro movable: idx={idx_check}, ID={item_id_check}, data1={data1}, data2={data2}")
                        break

                movable_position = spear_list_index - first_movable_idx
                spear_stack_pos = len(tile.items) - 1 - movable_position
                print(f"[Spear Action] Calculo stack_pos: len(items)={len(tile.items)}, first_movable_idx={first_movable_idx}, spear_list_index={spear_list_index}, movable_position={movable_position}, stack_pos={spear_stack_pos}")

            # === CALCULA QUANTIDADE A PEGAR ===
            spears_on_tile = get_stack_count(tile, spear_list_index)
            cap_allows = int(current_cap / SPEAR_WEIGHT)
            space_left = max_spears - current_spears

            count_to_pick = min(spears_on_tile, cap_allows, space_left)
            count_to_pick = max(1, count_to_pick)

            print(f"[Spear Action] Estado: cap={current_cap:.1f}oz, spears_na_mao={current_spears}/{max_spears}, spears_no_tile={spears_on_tile}")
            print(f"[Spear Action] Limites: tile={spears_on_tile}, cap_permite={cap_allows}, falta_para_max={space_left}")
            print(f"[Spear Action] Calculado stack_pos={spear_stack_pos} (movable_pos entre items moveis)")
            print(f"[Spear Action] Pegando count={count_to_pick} spear(s) (min entre tile/cap/max)")

            # === MOVE SPEAR PARA MÃO ===
            # ===== VERIFICAÇÃO FINAL: Loot pode ter sido aberto durante moves de bloqueadores =====
            if state.is_processing_loot:
                print("[Spear Action] Loot foi aberto - abortando antes de pegar spear")
                continue
            # =======================================================================================

            from_pos = get_ground_pos(abs_x, abs_y, z)
            to_pos = get_inventory_pos(target_hand)
            hand_name = "direita" if target_hand == SLOT_RIGHT else "esquerda"

            print(f"[Spear Action] move_item: from=({abs_x},{abs_y},{z}) to=hand_{target_hand}({hand_name}) id={SPEAR_ID} count={count_to_pick} stack_pos={spear_stack_pos}")

            with PacketMutex("spear_picker"):
                packet.move_item(from_pos, to_pos, SPEAR_ID, count_to_pick, spear_stack_pos, apply_delay=True)

            # Atualiza estado compartilhado (thread-safe)
            shared_state.update_after_pickup(count_to_pick)

            print(f"[Spear Action] ✓ Pegou {count_to_pick} spear(s) do chao ({abs_x},{abs_y},{z}) -> mao {hand_name}")

            # ========== DELAY GLOBAL APÓS PEGAR SPEAR ==========
            gauss_wait(MOVE_ITEM_DELAY_MIN, 30)
            print(f"[Spear Action] Delay global após pegar spear na mão")

        except Exception as e:
            print(f"[Spear Action] Erro: {e}")
            time.sleep(1)


def spear_picker_loop(pm, base_addr, check_running, get_enabled, get_max_spears=lambda: 3, log_func=print):
    """
    Inicia o sistema de spear picker com 2 threads independentes.

    Arquitetura de 2 threads:

    Thread 1 (Monitor):
    - Monitora spears na mão constantemente (150ms)
    - Detecta ataques em tempo real
    - Atualiza flag needs_spears
    - Nunca bloqueia, sempre roda

    Thread 2 (Ações):
    - Busca spears no chão quando needs_spears=True
    - Executa move_items com delays humanizados
    - Pode bloquear, mas não afeta monitor
    - Usa dados sempre atualizados do monitor

    Delays humanizados (APENAS em ações):
    - Tempo de reação ao detectar spear: 250ms + variação 30%
    - Tempo entre move_items: 250ms + variação 30%

    Args:
        pm: Instancia do Pymem
        base_addr: Endereco base do processo
        check_running: Funcao que retorna False para encerrar
        get_enabled: Funcao que retorna True/False se modulo esta ativo
        get_max_spears: Funcao que retorna o maximo de spears configurado
        log_func: Funcao de log (default: print)
    """
    print("[SpearPicker] Iniciando sistema com 2 threads independentes")

    # Estado compartilhado entre threads (thread-safe)
    shared_state = SpearPickerState()

    # Cria threads
    monitor_thread = threading.Thread(
        target=monitor_hand_loop,
        args=(pm, base_addr, check_running, get_enabled, get_max_spears, shared_state),
        name="SpearMonitor",
        daemon=True
    )

    action_thread = threading.Thread(
        target=action_loop,
        args=(pm, base_addr, check_running, get_enabled, shared_state),
        name="SpearAction",
        daemon=True
    )

    # Inicia threads
    monitor_thread.start()
    action_thread.start()

    print("[SpearPicker] Threads iniciadas: Monitor + Action")

    # Aguarda threads finalizarem
    try:
        monitor_thread.join()
        action_thread.join()
    except KeyboardInterrupt:
        print("[SpearPicker] Interrompido pelo usuário")
