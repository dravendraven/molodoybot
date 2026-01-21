"""
Spear Picker Module - Pega spears do chao automaticamente.

Funcionalidade para Paladinos:
- Identifica spears (ID 3277) no chao em tiles adjacentes
- Move itens que estao acima da spear (ex: corpo de criatura) para tile adjacente
- Verifica cap do personagem e calcula quantas pode pegar (20 oz cada)
- Move para a mao que ja tem spear ou esta vazia
- Repete o processo (quando ataca com spear, ela cai no tile da criatura)
"""

import time
import random

from config import (
    OFFSET_PLAYER_ID,
    SLOT_RIGHT,
    SLOT_LEFT,
)
from database.movable_items_db import is_movable
from core.map_core import get_player_pos
from core.memory_map import MemoryMap
from core.packet import PacketManager, get_ground_pos, get_inventory_pos
from core.packet_mutex import PacketMutex
from core.player_core import get_player_cap
from core.inventory_core import get_item_id_in_hand, get_spear_count_in_hands
from utils.timing import gauss_wait

# Constantes do modulo
SPEAR_ID = 3277          # ID da spear
SPEAR_WEIGHT = 20.0      # Peso de cada spear em oz

# Probabilidade minima de pegar spear (quando esta com max-1)
MIN_PICK_CHANCE = 0.15   # 10%

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

# Delays humanizados
SCAN_DELAY = 0.3         # Delay entre scans quando nao encontra spear
PRE_PICKUP_DELAY = 0.2   # Delay antes de pegar spear (variacao alta)
# Nota: delays de move_item agora sao dinamicos via apply_delay=True no packet.py


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
    Calcula a probabilidade de pegar a spear baseado em quantas faltam.

    Logica humanizada:
    - Mao vazia (0 spears): 100% de chance
    - max-1 spears: chance minima (MIN_PICK_CHANCE, ~10%)
    - Valores intermediarios: interpolacao linear

    Exemplo com max=3:
    - 0 spears na mao: 100% chance (faltam 3)
    - 1 spear na mao: ~55% chance (faltam 2)
    - 2 spears na mao: ~10% chance (faltam 1)
    - 3 spears na mao: 0% (ja esta cheio)

    Args:
        current_count: Quantidade atual de spears na mao
        max_count: Quantidade maxima configurada

    Returns:
        Float entre 0.0 e 1.0 representando a probabilidade
    """
    if current_count >= max_count:
        return 0.0  # Ja esta cheio

    if current_count == 0:
        return 1.0  # Mao vazia, sempre pegar

    # Quantas faltam para o maximo
    missing = max_count - current_count

    # Interpolacao: de 1.0 (faltam todas) ate MIN_PICK_CHANCE (falta 1)
    # Quando missing = max_count, chance = 1.0
    # Quando missing = 1, chance = MIN_PICK_CHANCE
    if max_count <= 1:
        return 1.0  # Caso especial: max=1

    # Formula: chance = MIN_PICK_CHANCE + (1 - MIN_PICK_CHANCE) * (missing - 1) / (max_count - 1)
    chance = MIN_PICK_CHANCE + (1.0 - MIN_PICK_CHANCE) * (missing - 1) / (max_count - 1)
    return min(1.0, max(0.0, chance))


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
    Encontra um tile para mover itens que estao acima da spear.
    Pode ser qualquer tile walkable (inclusive com criaturas).

    Logica randomizada:
    - 50% das vezes: tile do proprio player
    - 50% das vezes: tile adjacente ao tile da spear

    Args:
        mapper: MemoryMap instance
        spear_rel_x, spear_rel_y: Posicao relativa do tile com a spear
        my_x, my_y, my_z: Posicao absoluta do player

    Returns:
        Tuple (abs_x, abs_y, z) ou None se nao encontrar
    """
    # 50% chance de dropar no tile do player
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

        tile = mapper.get_tile_visible(check_rel_x, check_rel_y)
        if tile is None or len(tile.items) == 0:
            continue

        # Tile valido para drop (qualquer tile walkable)
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


def spear_picker_loop(pm, base_addr, check_running, get_enabled, get_max_spears=lambda: 3, log_func=print):
    """
    Loop principal do spear picker.

    Args:
        pm: Instancia do Pymem
        base_addr: Endereco base do processo
        check_running: Funcao que retorna False para encerrar
        get_enabled: Funcao que retorna True/False se modulo esta ativo
        get_max_spears: Funcao que retorna o maximo de spears configurado
        log_func: Funcao de log (default: print)
    """
    mapper = MemoryMap(pm, base_addr)
    packet = PacketManager(pm, base_addr)

    while True:
        if check_running and not check_running():
            return

        # Verifica se modulo esta habilitado
        if not get_enabled():
            time.sleep(1)
            continue

        if pm is None:
            time.sleep(1)
            continue

        try:
            # Le posicao do player
            my_x, my_y, my_z = get_player_pos(pm, base_addr)
            if my_z == 0:
                time.sleep(0.5)
                continue

            # Le capacidade atual
            current_cap = get_player_cap(pm, base_addr)

            # Verifica se tem cap para pelo menos 1 spear
            if current_cap < SPEAR_WEIGHT:
                time.sleep(SCAN_DELAY)
                continue

            # Encontra mao alvo
            target_hand = find_target_hand(pm, base_addr)
            if target_hand is None:
                # Ambas maos ocupadas com outros items
                time.sleep(SCAN_DELAY)
                continue

            # === Verifica probabilidade de pegar ===
            current_spears, _ = get_spear_count_in_hands(pm, base_addr, SPEAR_ID)
            max_spears = get_max_spears()

            # Ja esta cheio?
            if current_spears >= max_spears:
                time.sleep(SCAN_DELAY)
                continue

            # Calcula probabilidade e rola o dado
            pick_chance = calculate_pick_probability(current_spears, max_spears)
            if random.random() > pick_chance:
                # Nao vai pegar desta vez (simula humano esperando acumular)
                time.sleep(SCAN_DELAY)
                continue

            # Le mapa
            player_id = pm.read_int(base_addr + OFFSET_PLAYER_ID)
            if not mapper.read_full_map(player_id):
                time.sleep(0.5)
                continue

            # Procura spear em tiles adjacentes
            spear_location = find_spear_on_adjacent_tiles(mapper, my_x, my_y, my_z)

            if spear_location is None:
                # Nenhuma spear encontrada
                time.sleep(SCAN_DELAY)
                continue

            # Primeira deteccao apenas para saber se tem spear (vamos reler apos delay)
            _, _, _, _, _, _, _ = spear_location

            # Calcula quantas spears o cap permite
            cap_allows = int(current_cap / SPEAR_WEIGHT)
            if cap_allows <= 0:
                time.sleep(SCAN_DELAY)
                continue

            # Delay humanizado antes de pegar (variacao alta ~40%)
            gauss_wait(PRE_PICKUP_DELAY, 40)

            # Rele o mapa apos o delay para verificar estado atual do tile
            my_x, my_y, my_z = get_player_pos(pm, base_addr)
            if not mapper.read_full_map(player_id):
                time.sleep(0.3)
                continue

            # Procura spear novamente (pode ter mudado durante o delay)
            spear_location = find_spear_on_adjacent_tiles(mapper, my_x, my_y, my_z)
            if spear_location is None:
                # Spear sumiu durante o delay
                time.sleep(SCAN_DELAY)
                continue

            abs_x, abs_y, z, spear_list_index, rel_x, rel_y, tile = spear_location

            # === DEBUG: Mostra todos os items no tile com tipos ===
            print(f"[Spear DEBUG] Tile ({abs_x}, {abs_y}, {z}) - {len(tile.items)} items:")
            first_movable = -1
            for idx, item_id in enumerate(tile.items):
                data1 = 0
                if hasattr(tile, 'items_debug') and idx < len(tile.items_debug):
                    _, data1, _, _ = tile.items_debug[idx]

                item_type = "MAP_OBJ" if data1 == 0 else "MOVABLE"
                if data1 == 1 and first_movable == -1:
                    first_movable = idx

                marker = ""
                if item_id == SPEAR_ID:
                    marker = " <-- SPEAR"
                if item_id == CREATURE_ID:
                    marker = " (CREATURE)"

                print(f"  [idx={idx}] ID={item_id} | {item_type}{marker}")

            print(f"[Spear DEBUG] Spear em idx={spear_list_index}, primeiro_movable={first_movable}")
            # === FIM DEBUG ===

            # Verifica se ha itens acima da spear que precisam ser movidos
            # Items acima = idx < spear_list_index (menor idx = mais acima visualmente)
            items_above = get_items_above_spear(tile, spear_list_index)
            print(f"[Spear DEBUG] Items acima da spear (idx < {spear_list_index}): {items_above}")

            if items_above:
                # Encontra tile para mover os itens
                drop_tile = find_drop_tile(mapper, rel_x, rel_y, my_x, my_y, my_z)

                if drop_tile is None:
                    # Nao encontrou tile para dropar, tenta novamente depois
                    time.sleep(SCAN_DELAY)
                    continue

                drop_x, drop_y, drop_z = drop_tile

                # Move cada item acima da spear (do topo para baixo)
                # Topo visual = idx=1 na memoria = stack_pos = len-1 para o servidor
                for item_id, _ in items_above:
                    from_pos = get_ground_pos(abs_x, abs_y, z)
                    to_pos = get_ground_pos(drop_x, drop_y, drop_z)

                    # Topo sempre tem stack_pos = len(items) - 1
                    top_stack_pos = len(tile.items) - 1

                    with PacketMutex("spear_picker"):
                        packet.move_item(from_pos, to_pos, item_id, 1, top_stack_pos, apply_delay=True)

                    print(f"[Spear] Moveu item {item_id} (stack_pos={top_stack_pos}) para liberar spear")

                    # Atualiza a lista local apos mover (remove idx=1, o topo)
                    if len(tile.items) > 1:
                        tile.items.pop(1)

                # Apos mover os itens, a spear agora esta no topo
                # Releitura do mapa para confirmar
                if not mapper.read_full_map(player_id):
                    time.sleep(0.3)
                    continue

            # Calcula stack_pos da spear
            # Descoberta: stack_pos = len(items) - 1 - posicao_entre_movables
            # Onde posicao_entre_movables = idx - primeiro_movable_idx
            if items_above:
                # Apos mover items acima, spear esta no topo dos movables
                new_tile = mapper.get_tile_visible(rel_x, rel_y)
                if new_tile:
                    spear_stack_pos = len(new_tile.items) - 1
                else:
                    spear_stack_pos = len(tile.items) - 1
            else:
                # Spear esta na posicao original
                # Encontra o primeiro indice de item movel (data1=1)
                first_movable_idx = 0
                if hasattr(tile, 'items_debug'):
                    for idx_check in range(len(tile.items_debug)):
                        _, data1, _, _ = tile.items_debug[idx_check]
                        if data1 == 1:  # Primeiro item movel
                            first_movable_idx = idx_check
                            break

                # Posicao da spear entre os movables (0 = topo)
                movable_position = spear_list_index - first_movable_idx
                # stack_pos = len - 1 - posicao
                spear_stack_pos = len(tile.items) - 1 - movable_position

            print(f"[Spear DEBUG] Tentando pegar spear com stack_pos={spear_stack_pos}")

            # Sempre pega apenas 1 spear por vez (mais humanizado)
            count_to_pick = 1

            print(f"[Spear DEBUG] count_to_pick={count_to_pick} (sempre 1)")

            # Move spear do chao para a mao
            from_pos = get_ground_pos(abs_x, abs_y, z)
            to_pos = get_inventory_pos(target_hand)

            print(f"[Spear DEBUG] move_item(from=({abs_x},{abs_y},{z}), to=hand_{target_hand}, id={SPEAR_ID}, count={count_to_pick}, stack_pos={spear_stack_pos})")

            with PacketMutex("spear_picker"):
                packet.move_item(from_pos, to_pos, SPEAR_ID, count_to_pick, spear_stack_pos, apply_delay=True)

            hand_name = "direita" if target_hand == SLOT_RIGHT else "esquerda"
            print(f"[Spear] Pegou spear do chao -> mao {hand_name}")

        except Exception as e:
            print(f"[Spear] Erro: {e}")
            time.sleep(1)
