import time
import random
import win32con 

from core import packet 
from config import *
from core.inventory_core import find_item_in_containers
from core.map_core import get_player_pos, get_game_view, get_screen_coord
from modules.eater import attempt_eat
from core.input_core import press_hotkey, left_click_at
from database import foods_db # Importante para os logs de comida
from core.inventory_core import find_item_in_containers

# Slots do Inventário
SLOT_RIGHT = 5
SLOT_LEFT = 6

def get_vk_code(key_str):
    key_str = key_str.upper().strip()
    mapping = {
        "F1": win32con.VK_F1, "F2": win32con.VK_F2, "F3": win32con.VK_F3,
        "F4": win32con.VK_F4, "F5": win32con.VK_F5, "F6": win32con.VK_F6,
        "F7": win32con.VK_F7, "F8": win32con.VK_F8, "F9": win32con.VK_F9,
        "F10": win32con.VK_F10, "F11": win32con.VK_F11, "F12": win32con.VK_F12
    }
    return mapping.get(key_str, win32con.VK_F3)

def move_to_coord_hybrid(pm, base_addr, hwnd, target_pos, log_func=print):
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
        
        # --- PRIORIDADE 1: DIAGONAIS ---
        if dy < 0 and dx > 0:   op_code = packet.OP_WALK_NORTH_EAST
        elif dy > 0 and dx > 0: op_code = packet.OP_WALK_SOUTH_EAST
        elif dy > 0 and dx < 0: op_code = packet.OP_WALK_SOUTH_WEST
        elif dy < 0 and dx < 0: op_code = packet.OP_WALK_NORTH_WEST
        
        # --- PRIORIDADE 2: ORTOGONAIS (Retas) ---
        elif dy < 0: op_code = packet.OP_WALK_NORTH
        elif dy > 0: op_code = packet.OP_WALK_SOUTH
        elif dx < 0: op_code = packet.OP_WALK_WEST
        elif dx > 0: op_code = packet.OP_WALK_EAST
        
        if op_code:
            packet.walk(pm, op_code)
            time.sleep(0.5 + random.uniform(0.05, 0.15)) 
            return False 

    # 2. SE ESTIVER LONGE (> 1 SQM) -> USA MOUSE (CLIENT PATHFINDER)
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
    
def unequip_hand(pm, base_addr, slot_enum, dest_container_idx=0):
    current_id = get_item_id_in_hand(pm, base_addr, slot_enum)
    if current_id > 0:
        pos_from = packet.get_inventory_pos(slot_enum)
        pos_to = packet.get_container_pos(dest_container_idx, 0) 
        packet.move_item(pm, pos_from, pos_to, current_id, 1)
        time.sleep(0.5)
        check_id = get_item_id_in_hand(pm, base_addr, slot_enum)
        if check_id == 0: return current_id
        else: return None
    return None

def reequip_hand(pm, base_addr, item_id, target_slot_enum, container_idx=0):
    if not item_id: return
    item_data = find_item_in_containers(pm, base_addr, item_id)
    if item_data:
        pos_from = packet.get_container_pos(item_data['container_index'], item_data['slot_index'])
        pos_to = packet.get_inventory_pos(target_slot_enum)
        packet.move_item(pm, pos_from, pos_to, item_id, 1)
        time.sleep(0.4)

def get_target_id(pm, base_addr):
    """Lê o ID do alvo atual na memória."""
    try:
        # Usa o OFFSET definido no config.py
        return pm.read_int(base_addr + TARGET_ID_PTR)
    except:
        return 0
    
def runemaker_loop(pm, base_addr, hwnd, check_running=None, config=None, is_safe_callback=None, is_gm_callback=None, log_callback=None, eat_callback=None):
    
    if config is None: config = {}

    def log_msg(text):
        timestamp = time.strftime("%H:%M:%S")
        print(f"[{timestamp}] [RUNEMAKER] {text}")
        if log_callback: log_callback(f"[RUNE] {text}")

    log_msg(f"Iniciado (Packet Mode + Hotkeys).")
    
    hotkey_str = config.get('hotkey', 'F3')
    vk_hotkey = get_vk_code(hotkey_str)
    
    last_danger_time = 0 
    return_delay = config.get('return_delay', 300)
    is_fleeing_active = False 
    last_mana_log = 0

    # CONTROLE DE "BARRIGA CHEIA"
    is_full_lock = False
    full_lock_time = 0
    FULL_COOLDOWN_SECONDS = 60 
    last_combat_time = 0
    COMBAT_COOLDOWN = 5

    # CONTROLE DE HUMANIZAÇÃO (DELAY)
    next_cast_time = 0

    while True:
        if check_running and not check_running(): return
        
        is_safe = is_safe_callback() if is_safe_callback else True
        is_gm = is_gm_callback() if is_gm_callback else False
        
        if is_gm:
            log_msg("👮 GM DETECTADO! Parando...")
            packet.stop(pm) 
            time.sleep(2)
            continue

        # ======================================================================
        # 🛡️ PROTEÇÃO DE BATALHA (SEGURANÇA)
        # ======================================================================
        current_target = get_target_id(pm, base_addr)
        
        if current_target != 0:
            # Estamos atacando algo!
            last_combat_time = time.time()
            # Resetamos o timer de cast para não castar assim que a luta acabar
            # next_cast_time = 0 
            time.sleep(0.5)
            continue # Pula o resto do loop (não come, não treina, não faz runa)
            
        # Se não estamos atacando, verificamos o cooldown
        if time.time() - last_combat_time < COMBAT_COOLDOWN:
            # Estamos no "buffer" de segurança pós-combate
            time.sleep(0.5)
            continue # Ainda perigoso, espera...

        # ======================================================================
        # LÓGICA DE COMIDA (AUTO EAT)
        # ======================================================================
        if config.get('auto_eat', False):
            if is_full_lock:
                if time.time() - full_lock_time > FULL_COOLDOWN_SECONDS:
                    is_full_lock = False 
            
            if not is_full_lock:
                is_hungry_func = config.get('check_hunger')
                if is_hungry_func and is_hungry_func():
                    try:
                        result = attempt_eat(pm, base_addr, hwnd)
                        if result == "FULL":
                            log_msg("⚠️ Personagem cheio. Pausando comida por 60s.")
                            is_full_lock = True
                            full_lock_time = time.time()
                        elif result:
                            food_id = result
                            # Busca o nome no DB para log bonito
                            food_name = foods_db.get_food_name(food_id)
                            log_msg(f"🍖 {food_name} consumida.")
                            if eat_callback: eat_callback(food_id)
                    except Exception as e:
                        print(f"[DEBUG] Erro ao comer: {e}")

        # ======================================================================
        # MANA TRAIN
        # ======================================================================
        if config.get('mana_train', False):
            if not is_safe:
                if time.time() - last_mana_log > 5:
                    log_msg("⚠️ Alarme ativo! Mana Train pausado.")
                    last_mana_log = time.time()
                time.sleep(1)
                continue
            
            try:
                curr_mana = pm.read_int(base_addr + OFFSET_PLAYER_MANA)
                mana_req = config.get('mana_req', 100)
                
                if curr_mana >= mana_req:
                    # 1. Se não tem timer definido, cria um
                    if next_cast_time == 0:
                        h_min = config.get('human_min', 0)
                        h_max = config.get('human_max', 0)
                        
                        if h_max > 0:
                            delay = random.uniform(h_min, h_max)
                            next_cast_time = time.time() + delay
                            log_msg(f"⏳ Mana cheia! Aguardando {int(delay)}s (Treino)...")
                        else:
                            next_cast_time = time.time() # Sem delay

                    # 2. Verifica se já passou o tempo
                    if time.time() >= next_cast_time:
                        log_msg(f"⚡ Mana cheia ({curr_mana}). Usando {hotkey_str}...")
                        press_hotkey(hwnd, vk_hotkey)
                        
                        # Reseta o timer
                        next_cast_time = 0
                        time.sleep(2.2) # Cooldown padrão do Tibia

                else:
                    # Se mana baixou, reseta o timer
                    next_cast_time = 0
                    time.sleep(1)

            except: time.sleep(1)
            continue # Pula o resto (Runemaker) 

        # ======================================================================
        # RUNEMAKER (Movimento + Runas)
        # ======================================================================
        
        safe_pos = config.get('safe_pos', (0,0,0))
        work_pos = config.get('work_pos', (0,0,0))

        coords_defined = (safe_pos[0] != 0)
        movement_allowed = config.get('enable_movement', False) 
        has_coords = coords_defined and movement_allowed
        
        target_destination = None
        mode = "IDLE"
            
        if not is_safe and has_coords:
            mode = "FLEEING"
            last_danger_time = time.time()
            curr_pos = get_player_pos(pm, base_addr)
            at_safe = (curr_pos[0] == safe_pos[0] and curr_pos[1] == safe_pos[1])
            if not at_safe:
                if not is_fleeing_active:
                    flee_delay = config.get('flee_delay', 0)
                    if flee_delay > 0:
                        wait = random.uniform(flee_delay, flee_delay * 1.2)
                        log_msg(f"🚨 PERIGO! Reagindo em {wait:.1f}s...")
                        time.sleep(wait)
                    is_fleeing_active = True
                target_destination = safe_pos
        else:
            is_fleeing_active = False
            time_since = time.time() - last_danger_time
            if last_danger_time > 0 and time_since < return_delay:
                mode = "WAITING"
                if has_coords: target_destination = safe_pos
            else:
                mode = "WORKING"
                if has_coords: target_destination = work_pos

        if target_destination:
            at_dest = move_to_coord_hybrid(pm, base_addr, hwnd, target_destination, log_func=log_msg)
            if not at_dest: continue 

        # --- Ciclo de Fabricação ---
        if mode == "WORKING":
            try:
                curr_mana = pm.read_int(base_addr + OFFSET_PLAYER_MANA)
            except: time.sleep(1); continue

            mana_req = config.get('mana_req', 100)

            # >>> LÓGICA DE HUMANIZAÇÃO (BUFFER DE TEMPO) <<<
            if curr_mana >= mana_req:
                # Se ainda não definimos um tempo de espera, define agora
                if next_cast_time == 0:
                    h_min = config.get('human_min', 0)
                    h_max = config.get('human_max', 0)
                    
                    if h_max > 0:
                        delay = random.uniform(h_min, h_max)
                        next_cast_time = time.time() + delay
                        log_msg(f"⏳ Mana cheia! Aguardando {int(delay)}s (Humanização)...")
                    else:
                        # Se não tiver config, casta imediatamente
                        next_cast_time = time.time()

                # Verifica se o tempo de espera já passou
                if time.time() >= next_cast_time:
                    log_msg(f"⚡ Mana ok ({curr_mana}). Fabricando...")
                    
                    hand_mode = config.get('hand_mode', 'RIGHT')
                    hands_to_use = []
                    if hand_mode == "BOTH": hands_to_use = [SLOT_LEFT, SLOT_RIGHT]
                    elif hand_mode == "LEFT": hands_to_use = [SLOT_LEFT]
                    else: hands_to_use = [SLOT_RIGHT]
                    
                    active_runes = []
                    
                    for slot_enum in hands_to_use:
                        if is_safe_callback and not is_safe_callback(): break
                        
                        # === LIMPEZA DE MÃO ===
                        unequipped_item_id = unequip_hand(pm, base_addr, slot_enum)
                        
                        # === BUSCA DA BLANK RUNE ===
                        blank_data = find_item_in_containers(pm, base_addr, config.get('blank_id', 3147))
                        
                        if not blank_data:
                            log_msg(f"⚠️ Sem Blanks na BP! (Ou não encontrada)")
                            if unequipped_item_id:
                                reequip_hand(pm, base_addr, unequipped_item_id, slot_enum)
                            break
                        
                        # Move Blank -> Mão
                        pos_from = packet.get_container_pos(blank_data['container_index'], blank_data['slot_index'])
                        pos_to = packet.get_inventory_pos(slot_enum)
                        packet.move_item(pm, pos_from, pos_to, config.get('blank_id', 3147), 1)
                        
                        active_runes.append({
                            "hand_pos": pos_to, 
                            "origin_idx": blank_data['container_index'], 
                            "slot_enum": slot_enum,
                            "restorable_item": unequipped_item_id 
                        })
                        time.sleep(0.4)

                    if active_runes:
                        log_msg(f"🪄 Pressionando {hotkey_str}...")
                        
                        # >>>>>> AQUI OCORRE O PRESS HOTKEY <<<<<<
                        press_hotkey(hwnd, vk_hotkey)
                        
                        time.sleep(1.2) # Wait server process
                        
                        for info in active_runes:
                             # 1. Identifica o que foi fabricado
                             detected_id = get_item_id_in_hand(pm, base_addr, info['slot_enum'])
                             
                             rune_id_to_move = 0
                             if detected_id > 0:
                                 rune_id_to_move = detected_id
                             else:
                                 log_msg(f"⚠️ Erro: ID não detectado na mão! Usando Blank padrão.")
                                 rune_id_to_move = config.get('blank_id', 3147)

                             # 2. Devolve Runa para Backpack
                             pos_dest = packet.get_container_pos(info['origin_idx'], 0)
                             packet.move_item(pm, info['hand_pos'], pos_dest, rune_id_to_move, 1)
                             time.sleep(0.4)
                             
                             # === PASSO FINAL: RESTAURAR EQUIPAMENTO ===
                             if info['restorable_item']:
                                 reequip_hand(pm, base_addr, info['restorable_item'], info['slot_enum'])
                        
                        log_msg("✅ Ciclo concluído.")
                        # Reseta o timer para a próxima vez
                        next_cast_time = 0 
            else:
                # Se a mana baixou (ex: usou exura na mão), reseta o timer
                next_cast_time = 0

        time.sleep(0.5)