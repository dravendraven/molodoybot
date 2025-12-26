import time
import random
import win32con

from core.packet import (
    PacketManager, get_inventory_pos, get_container_pos,
    OP_WALK_NORTH, OP_WALK_EAST, OP_WALK_SOUTH, OP_WALK_WEST,
    OP_WALK_NORTH_EAST, OP_WALK_SOUTH_EAST, OP_WALK_SOUTH_WEST, OP_WALK_NORTH_WEST
)
from core.packet_mutex import PacketMutex
from config import *
from core.inventory_core import find_item_in_containers
from modules.auto_loot import scan_containers
from core.map_core import get_player_pos, get_game_view, get_screen_coord
from modules.eater import attempt_eat
from core.input_core import press_hotkey, left_click_at
from database import foods_db
from core.config_utils import make_config_getter
from core.bot_state import state

# Usar constantes do config.py ao invés de redefinir
# SLOT_RIGHT e SLOT_LEFT removidos (usar HandSlot do config)

def get_vk_code(key_str):
    key_str = key_str.upper().strip()
    mapping = {
        "F1": win32con.VK_F1, "F2": win32con.VK_F2, "F3": win32con.VK_F3,
        "F4": win32con.VK_F4, "F5": win32con.VK_F5, "F6": win32con.VK_F6,
        "F7": win32con.VK_F7, "F8": win32con.VK_F8, "F9": win32con.VK_F9,
        "F10": win32con.VK_F10, "F11": win32con.VK_F11, "F12": win32con.VK_F12
    }
    return mapping.get(key_str, win32con.VK_F3)

def move_to_coord_hybrid(pm, base_addr, hwnd, target_pos, log_func=print, packet=None):
    # Cria PacketManager se não foi passado
    if packet is None:
        packet = PacketManager(pm, base_addr)

    px, py, pz = get_player_pos(pm, base_addr)
    tx, ty, tz = target_pos

    # 1. Chegou?
    if px == tx and py == ty: return True
    if pz != tz: return False # Andar errado

    dx = tx - px
    dy = ty - py

    dist_sqm = max(abs(dx), abs(dy))

    # [MELHORIA] Se estiver no SQM adjacente (Distância 1)
    if dist_sqm == 1:
        op_code = None

        if dy < 0 and dx > 0:   op_code = OP_WALK_NORTH_EAST
        elif dy > 0 and dx > 0: op_code = OP_WALK_SOUTH_EAST
        elif dy > 0 and dx < 0: op_code = OP_WALK_SOUTH_WEST
        elif dy < 0 and dx < 0: op_code = OP_WALK_NORTH_WEST

        elif dy < 0: op_code = OP_WALK_NORTH
        elif dy > 0: op_code = OP_WALK_SOUTH
        elif dx < 0: op_code = OP_WALK_WEST
        elif dx > 0: op_code = OP_WALK_EAST

        if op_code:
            packet.walk(op_code)
            time.sleep(0.5 + random.uniform(0.05, 0.15))
            return False 

    # 2. SE ESTIVER LONGE (> 1 SQM) -> USA MOUSE
    gv = get_game_view(pm, base_addr)
    if gv:
        screen_x, screen_y = get_screen_coord(gv, dx, dy, hwnd)
        left_click_at(hwnd, screen_x, screen_y)
        time.sleep(0.5 + (dist_sqm * 0.1)) 
        return False
            
    return False

def get_item_id_in_hand(pm, base_addr, slot_enum):
    try:
        offset = 0
        if slot_enum == SLOT_RIGHT: offset = OFFSET_SLOT_RIGHT
        elif slot_enum == SLOT_LEFT:  offset = OFFSET_SLOT_LEFT
        else: return 0
        return pm.read_int(base_addr + offset)
    except:
        return 0

def get_free_slot_in_container(pm, base_addr, target_container_idx=0):
    """
    Encontra o próximo slot livre em um container específico.

    Retorna: (container_index, free_slot) ou (None, None) se container cheio/não encontrado.

    O slot livre é determinado por container.amount (quantidade de itens),
    que corresponde ao próximo índice disponível (append no final).
    """
    containers = scan_containers(pm, base_addr)

    for cont in containers:
        if cont.index == target_container_idx:
            # Verifica se tem espaço (amount < volume)
            if cont.amount < cont.volume:
                # Próximo slot livre = quantidade atual de itens
                return cont.index, cont.amount
            else:
                # Container cheio
                return None, None

    # Container não encontrado (fechado?)
    return None, None
    
def unequip_hand(pm, base_addr, slot_enum, dest_container_idx=0, dest_slot=None, packet=None):
    """
    Unequip item from hand slot and move to container.

    Returns the item ID if successful, None if it failed or slot was empty.

    Uses DUAL VALIDATION to handle:
    1. Network latency (retries with exponential backoff: 0.5s, 0.8s, 1.1s)
    2. Memory context staleness (verifies item is in container, not just hand empty)

    The dual validation catches race conditions when Cavebot pauses for Runemaker,
    which can cause Pymem to read stale memory values during context switch.

    Args:
        dest_slot: If None (default), automatically finds the next free slot.
                   If specified, uses that slot (legacy behavior).
        packet: PacketManager instance (created if None)

    Returns:
        int: Item ID if successfully unequipped (hand empty + item in container)
        None: If unequip failed, slot was empty, or container is full
    """
    # Cria PacketManager se não foi passado
    if packet is None:
        packet = PacketManager(pm, base_addr)

    current_id = get_item_id_in_hand(pm, base_addr, slot_enum)
    if current_id <= 0:
        return None

    # Encontra o próximo slot livre se dest_slot não foi especificado
    if dest_slot is None:
        _, found_slot = get_free_slot_in_container(pm, base_addr, dest_container_idx)
        if found_slot is None:
            print(f"[RUNEMAKER] ⚠️ Container {dest_container_idx} está cheio! Não é possível desequipar.")
            return None
        dest_slot = found_slot

    pos_from = get_inventory_pos(slot_enum)
    pos_to = get_container_pos(dest_container_idx, dest_slot)
    packet.move_item(pos_from, pos_to, current_id, 1)

    # DUAL VALIDATION: Verify both hand is empty AND item in container
    max_attempts = 3
    for attempt in range(max_attempts):
        time.sleep(0.5 + (attempt * 0.3))  # 0.5s, 0.8s, 1.1s waits

        # Check 1: Hand slot is empty
        check_id = get_item_id_in_hand(pm, base_addr, slot_enum)
        if check_id == 0:
            # Hand is empty - verify item reached destination container
            # This catches Cavebot context staleness issues
            try:
                item_data = find_item_in_containers(pm, base_addr, current_id)
                if item_data and item_data['container_index'] == dest_container_idx:
                    # DUAL CONFIRMATION: Hand empty + Item in correct container
                    return current_id
                # Item not in container yet, will retry
                continue
            except Exception as e:
                # If container scan fails but hand is empty, trust hand check
                # (hand check is more direct and reliable than container scan)
                return current_id

    # All attempts failed - item still in hand or not found in containers
    return None

def reequip_hand(pm, base_addr, item_id, target_slot_enum, container_idx=0, max_retries=3, packet=None):
    if not item_id: return False

    # Cria PacketManager se não foi passado
    if packet is None:
        packet = PacketManager(pm, base_addr)

    # Retry logic: item might not be in containers immediately after move_item
    for attempt in range(max_retries):
        time.sleep(0.3)  # Wait for server to process the previous move_item
        item_data = find_item_in_containers(pm, base_addr, item_id)

        if item_data:
            pos_from = get_container_pos(item_data['container_index'], item_data['slot_index'])
            pos_to = get_inventory_pos(target_slot_enum)
            packet.move_item(pos_from, pos_to, item_id, 1)
            time.sleep(0.4)
            return True

        if attempt < max_retries - 1:
            print(f"[RUNEMAKER] ⚠️ Item {item_id} não encontrado, tentativa {attempt + 1}/{max_retries}")

    print(f"[RUNEMAKER] ❌ Falha ao re-equipar item {item_id} após {max_retries} tentativas!")
    return False

def get_target_id(pm, base_addr):
    try:
        return pm.read_int(base_addr + TARGET_ID_PTR)
    except:
        return 0
    
def runemaker_loop(pm, base_addr, hwnd, check_running=None, config=None, is_safe_callback=None, is_gm_callback=None, log_callback=None, eat_callback=None):

    get_cfg = make_config_getter(config)

    def log_msg(text):
        timestamp = time.strftime("%H:%M:%S")
        print(f"[{timestamp}] [RUNEMAKER] {text}")
        if log_callback: log_callback(f"[RUNE] {text}")

    # Variáveis de Estado
    STATE_IDLE = 0
    STATE_FLEEING = 1
    STATE_RETURNING = 2
    STATE_WORKING = 3
    
    current_state = STATE_IDLE
    
    last_log_wait = 0
    return_timer_start = 0
    next_cast_time = 0
    
    # Controle de "Barriga Cheia"
    is_full_lock = False
    full_lock_time = 0
    FULL_COOLDOWN_SECONDS = 60 
    
    # Controle de Combate
    last_combat_time = 0
    COMBAT_COOLDOWN = 7  # Aumentado para 7s: aguarda estabilização do loot (3-5s) + margem de segurança

    log_msg(f"Iniciado (Modo Segurança Avançada).")

    # PacketManager para envio de pacotes
    packet = PacketManager(pm, base_addr)

    while True:
        if check_running and not check_running(): return

        # Configs em Tempo Real
        hotkey_str = get_cfg('hotkey', 'F3')
        vk_hotkey = get_vk_code(hotkey_str)
        mana_req = get_cfg('mana_req', 100)
        return_delay = get_cfg('return_delay', 300)
        work_pos = get_cfg('work_pos', (0,0,0))
        safe_pos = get_cfg('safe_pos', (0,0,0))
        enable_move = get_cfg('enable_movement', False)
        
        # Flag especial vinda do Main (Controla Cool-off)
        can_act = get_cfg('can_perform_actions', True)

        # Checagem de Segurança
        is_safe = is_safe_callback() if is_safe_callback else True
        is_gm = is_gm_callback() if is_gm_callback else False
        
        # ======================================================================
        # PRIORIDADE 1: GM DETECTADO (PÂNICO TOTAL)
        # ======================================================================
        if is_gm:
            # Se for GM, paramos TUDO. Não movemos.
            # O estado de movimento também é ignorado.
            if time.time() - last_log_wait > 5:
                log_msg("👮 GM DETECTADO! Congelando ações...")
                packet.stop()
                last_log_wait = time.time()
            time.sleep(1)
            continue 

        # ======================================================================
        # PRIORIDADE 2: FUGA (MONSTRO/PK)
        # ======================================================================
        if not is_safe and enable_move:
            if current_state != STATE_FLEEING:
                flee_delay = get_cfg('flee_delay', 0)
                if flee_delay > 0:
                    wait = random.uniform(flee_delay, flee_delay * 1.2)
                    log_msg(f"🚨 PERIGO! Reagindo em {wait:.1f}s...")
                    time.sleep(wait)
                
                log_msg("🏃 Fugindo para Safe Spot...")
                current_state = STATE_FLEEING
            
            # Movimento para Safe
            move_to_coord_hybrid(pm, base_addr, hwnd, safe_pos, log_func=None)
            time.sleep(0.5)
            continue 

        # ======================================================================
        # PRIORIDADE 3: RETORNO
        # ======================================================================
        if is_safe and current_state == STATE_FLEEING:
            current_state = STATE_RETURNING
            return_timer_start = time.time() + return_delay
            log_msg(f"🛡️ Seguro. Retornando em {return_delay}s...")

        if current_state == STATE_RETURNING:
            if time.time() < return_timer_start:
                time.sleep(1)
                continue
            else:
                if enable_move:
                    log_msg("🚶 Voltando para o Work Spot...")
                    arrived = move_to_coord_hybrid(pm, base_addr, hwnd, work_pos, log_func=None)
                    if arrived:
                        current_state = STATE_WORKING
                        log_msg("📍 Cheguei no trabalho.")
                    else:
                        continue # Continua andando até chegar
                else:
                    current_state = STATE_WORKING

        # ======================================================================
        # PRIORIDADE 4: MODO DE ESPERA (COOL-OFF / SEGURANÇA GLOBAL)
        # ======================================================================
        # Se 'can_perform_actions' for False, significa que estamos no delay de segurança
        # definido pelo Main (ex: GM sumiu há pouco tempo, ou monstro sumiu e move=off).
        if not can_act:
            if time.time() - last_log_wait > 10:
                log_msg("⏳ Aguardando segurança para retomar ações...")
                last_log_wait = time.time()
            time.sleep(1)
            continue

        # ======================================================================
        # PRIORIDADE 5: TRABALHO (MANA TRAIN / RUNAS / COMIDA)
        # ======================================================================
        
        # 1. Proteção de Combate (integrada com bot_state)
        # Só pausa para combate/loot se cavebot estiver ativo
        # Permite runemaking durante treino (trainer-only mode)
        if state.cavebot_active and (state.is_in_combat or state.has_open_loot):
            time.sleep(0.5); continue

        # Cooldown mais inteligente: aguarda 7s após combate terminar
        # Permite que auto-loot (3-5s) termine completamente
        # Só aplica cooldown se cavebot estiver ativo
        if state.cavebot_active and (time.time() - state.last_combat_time < COMBAT_COOLDOWN):
            time.sleep(0.5); continue

        # 2. Auto Eat
        if get_cfg('auto_eat', False):
            if is_full_lock and (time.time() - full_lock_time > FULL_COOLDOWN_SECONDS):
                is_full_lock = False 
            
            if not is_full_lock:
                check_hunger = get_cfg('check_hunger', lambda: False)
                if check_hunger():
                    try:
                        res = attempt_eat(pm, base_addr, hwnd)
                        if res == "FULL":
                            is_full_lock = True
                            full_lock_time = time.time()
                        elif res:
                            if eat_callback: eat_callback(res)
                    except: pass

        # 3. Mana Train (Prioridade sobre Runas se ativo)
        if get_cfg('mana_train', False):
            try:
                curr_mana = pm.read_int(base_addr + OFFSET_PLAYER_MANA)
                if curr_mana >= mana_req:
                    if next_cast_time == 0:
                        h_min = get_cfg('human_min', 0)
                        h_max = get_cfg('human_max', 0)
                        if h_max > 0:
                            delay = random.uniform(h_min, h_max)
                            next_cast_time = time.time() + delay
                            log_msg(f"⏳ Mana cheia! Aguardando {int(delay)}s (Treino)...")
                        else:
                            next_cast_time = time.time()

                    if time.time() >= next_cast_time:
                        log_msg(f"⚡ Mana cheia. Usando {hotkey_str}...")
                        press_hotkey(hwnd, vk_hotkey)
                        next_cast_time = 0
                        time.sleep(2.2)
                else:
                    next_cast_time = 0
            except: pass
            
            time.sleep(0.5)
            continue # Pula Runemaker se Mana Train está ativo

        # 4. Fabricação de Runas
        try:
            curr_mana = pm.read_int(base_addr + OFFSET_PLAYER_MANA)
            
            if curr_mana >= mana_req:
                if next_cast_time == 0:
                    h_min = get_cfg('human_min', 2)
                    h_max = get_cfg('human_max', 10)
                    delay = random.uniform(h_min, h_max)
                    next_cast_time = time.time() + delay
                    log_msg(f"⏳ Mana cheia! Aguardando {int(delay)}s...")

                if time.time() >= next_cast_time:
                    log_msg(f"⚡ Mana ok ({curr_mana}). Fabricando...")
                    state.set_runemaking(True)

                    try:
                        hand_mode = get_cfg('hand_mode', 'RIGHT')
                        hands_to_use = []
                        if hand_mode == "BOTH": hands_to_use = [SLOT_LEFT, SLOT_RIGHT]
                        elif hand_mode == "LEFT": hands_to_use = [SLOT_LEFT]
                        else: hands_to_use = [SLOT_RIGHT]

                        # Verifica se temos blank runes no inventário ANTES de desarmar
                        blank_id = get_cfg('blank_id', 3147)
                        blank_data = find_item_in_containers(pm, base_addr, blank_id)
                        if not blank_data:
                            log_msg(f"⚠️ Sem Blanks na BP!")
                            next_cast_time = 0
                            continue

                        # PACKET MUTEX: Wrap entire runemaking cycle (unequip -> blank -> cast -> return -> reequip)
                        with PacketMutex("runemaker"):
                            # STOP: Garante que o personagem pare antes de mover itens
                            packet.stop()
                            time.sleep(0.3)

                            # PHASE 1: Unequip all hands and store their items
                            # (This fixes the bug where unequipped_item_id gets overwritten with "BOTH" hands)
                            # Agora usa slot livre automaticamente via get_free_slot_in_container
                            unequipped_items = {}  # slot_enum → (item_id, dest_slot)
                            for slot_enum in hands_to_use:
                                if is_safe_callback and not is_safe_callback(): break

                                unequipped_item_id = unequip_hand(pm, base_addr, slot_enum, dest_container_idx=0, packet=packet)
                                unequipped_items[slot_enum] = (unequipped_item_id, 0)

                                log_msg(f"🔓 Desarmou {slot_enum}: Item {unequipped_item_id}")

                                time.sleep(1.2)

                            # PHASE 2: Equip blank runes
                            active_runes = []

                            for slot_enum in hands_to_use:
                                if is_safe_callback and not is_safe_callback(): break

                                # Move Blank -> Mão
                                pos_from = get_container_pos(blank_data['container_index'], blank_data['slot_index'])
                                pos_to = get_inventory_pos(slot_enum)
                                packet.move_item(pos_from, pos_to, blank_id, 1)

                                # Adiciona à lista de runes ativas
                                restorable_item, orig_dest_slot = unequipped_items[slot_enum]
                                active_runes.append({
                                    "hand_pos": pos_to,
                                    "origin_idx": blank_data['container_index'],
                                    "slot_enum": slot_enum,
                                    "restorable_item": restorable_item,
                                    "orig_dest_slot": orig_dest_slot  # Track where the weapon was stored
                                })
                                time.sleep(1.2)

                            if active_runes:
                                log_msg(f"🪄 Pressionando {hotkey_str}...")
                                press_hotkey(hwnd, vk_hotkey)

                                time.sleep(1.2) # Wait process

                                # PHASE 4: Return ALL runes to backpack FIRST (before re-equipping)
                                # IMPORTANTE: Quando usa BOTH hands, precisa devolver AMBAS as runas
                                # antes de tentar re-equipar (especialmente itens que ocupam 2 mãos)
                                for info in active_runes:
                                    # 1. Identifica o que foi fabricado
                                    detected_id = get_item_id_in_hand(pm, base_addr, info['slot_enum'])
                                    rune_id_to_move = detected_id if detected_id > 0 else blank_id

                                    # 2. Devolve Runa para Backpack
                                    pos_dest = get_container_pos(info['origin_idx'], 0)
                                    packet.move_item(info['hand_pos'], pos_dest, rune_id_to_move, 1)
                                    log_msg(f"📦 Devolvido: Runa {rune_id_to_move} → Container {info['origin_idx']}")
                                    time.sleep(1.5)  # Aguarda servidor processar movimento

                                # PHASE 5: Re-equip ALL original items AFTER all runes are returned
                                # Separar em outra fase garante que nenhum item fica equipado enquanto
                                # ainda há runas nas mãos (importante para itens com 2 mãos)
                                log_msg(f"🔙 Restaurando {len([i for i in active_runes if i['restorable_item']])} item(ns) original(is)...")
                                for info in active_runes:
                                    if info['restorable_item']:
                                        log_msg(f"🔄 Tentando re-equipar {info['restorable_item']} na mão {info['slot_enum']}...")
                                        success = reequip_hand(pm, base_addr, info['restorable_item'], info['slot_enum'], packet=packet)
                                        if success:
                                            log_msg(f"✅ Item {info['restorable_item']} re-equipado com sucesso!")
                                        else:
                                            log_msg(f"⚠️ Falha ao re-equipar {info['restorable_item']}")
                                        time.sleep(0.5)  # Pequena pausa entre re-equipamentos

                                log_msg("✅ Ciclo concluído.")
                                next_cast_time = 0
                    finally:
                        state.set_runemaking(False)
            else:
                next_cast_time = 0

        except Exception as e:
            print(f"Rune Error: {e}")
            state.set_runemaking(False)

        time.sleep(0.5)