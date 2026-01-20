"""
Spear Picker Module - Pega spears do chao automaticamente.

Funcionalidade para Paladinos:
- Identifica spears (ID 3277) no chao em tiles adjacentes
- Verifica cap do personagem e calcula quantas pode pegar (20 oz cada)
- Move para a mao que ja tem spear ou esta vazia
- Repete o processo (quando ataca com spear, ela cai no tile da criatura)
"""

import time
from config import *
from core.map_core import get_player_pos
from core.memory_map import MemoryMap
from core.packet import PacketManager, get_ground_pos, get_inventory_pos
from core.packet_mutex import PacketMutex
from utils.timing import gauss_wait

# Constantes
SPEAR_ID = 3277          # ID da spear
SPEAR_WEIGHT = 20.0      # Peso de cada spear em oz
SLOT_RIGHT = 5           # Slot da mao direita
SLOT_LEFT = 6            # Slot da mao esquerda

# Offsets de leitura do inventory (slots de mao)
OFFSET_SLOT_RIGHT_ID = 0x1CED90
OFFSET_SLOT_LEFT_ID = 0x1CED9C

# Tiles adjacentes ao player (incluindo diagonais)
ADJACENT_TILES = [
    (-1, -1), (0, -1), (1, -1),  # Norte
    (-1,  0),          (1,  0),  # Leste/Oeste
    (-1,  1), (0,  1), (1,  1),  # Sul
]

# Delays humanizados
SCAN_DELAY = 0.3         # Delay entre scans quando nao encontra spear
PICKUP_DELAY_MIN = 0.15  # Delay minimo apos pegar spear
PICKUP_DELAY_MAX = 0.35  # Delay maximo apos pegar spear


def get_player_cap(pm, base_addr):
    """Le a capacidade atual do jogador."""
    try:
        val = pm.read_float(base_addr + OFFSET_PLAYER_CAP)
        if val < 0.1:
            val = float(pm.read_int(base_addr + OFFSET_PLAYER_CAP))
        return val
    except:
        return 0.0


def get_hand_item_id(pm, base_addr, slot):
    """
    Le o ID do item na mao especificada.

    Args:
        slot: SLOT_RIGHT (5) ou SLOT_LEFT (6)

    Returns:
        ID do item ou 0 se vazio
    """
    try:
        if slot == SLOT_RIGHT:
            return pm.read_int(base_addr + OFFSET_SLOT_RIGHT_ID)
        elif slot == SLOT_LEFT:
            return pm.read_int(base_addr + OFFSET_SLOT_LEFT_ID)
        return 0
    except:
        return 0


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
    right_id = get_hand_item_id(pm, base_addr, SLOT_RIGHT)
    left_id = get_hand_item_id(pm, base_addr, SLOT_LEFT)

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


def find_spear_on_adjacent_tiles(mapper, my_x, my_y, my_z):
    """
    Procura spears em tiles adjacentes ao player.

    Returns:
        Tuple (abs_x, abs_y, z, stack_pos) ou None se nao encontrar
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
                return (abs_x, abs_y, my_z, i)

    return None


def spear_picker_loop(pm, base_addr, check_running, get_enabled, log_func=print):
    """
    Loop principal do spear picker.

    Args:
        pm: Instancia do Pymem
        base_addr: Endereco base do processo
        check_running: Funcao que retorna False para encerrar
        get_enabled: Funcao que retorna True/False se modulo esta ativo
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

            abs_x, abs_y, z, stack_pos = spear_location

            # Calcula quantas spears pode pegar
            max_spears = int(current_cap / SPEAR_WEIGHT)
            if max_spears <= 0:
                time.sleep(SCAN_DELAY)
                continue

            # Limita a 1 por vez (mais humano e evita problemas de sync)
            count_to_pick = 1

            # Move spear do chao para a mao
            from_pos = get_ground_pos(abs_x, abs_y, z)
            to_pos = get_inventory_pos(target_hand)

            with PacketMutex("spear_picker"):
                packet.move_item(from_pos, to_pos, SPEAR_ID, count_to_pick, stack_pos)

            hand_name = "direita" if target_hand == SLOT_RIGHT else "esquerda"
            log_func(f"[Spear] Pegou spear do chao -> mao {hand_name}")

            # Delay humanizado apos pegar
            gauss_wait((PICKUP_DELAY_MIN + PICKUP_DELAY_MAX) / 2, 20)

        except Exception as e:
            log_func(f"[Spear] Erro: {e}")
            time.sleep(1)
