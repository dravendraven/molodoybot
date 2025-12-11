import time
import random
import packet 
import win32con 
from config import *
from inventory_core import find_item_in_containers
from map_core import get_player_pos, get_game_view, get_screen_coord
from eater import attempt_eat
from input_core import press_hotkey, left_click_at
import foods_db

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
        # Verifica se precisa andar em DOIS eixos ao mesmo tempo
        if dy < 0 and dx > 0:   op_code = packet.OP_WALK_NORTH_EAST
        elif dy > 0 and dx > 0: op_code = packet.OP_WALK_SOUTH_EAST
        elif dy > 0 and dx < 0: op_code = packet.OP_WALK_SOUTH_WEST
        elif dy < 0 and dx < 0: op_code = packet.OP_WALK_NORTH_WEST
        
        # --- PRIORIDADE 2: ORTOGONAIS (Retas) ---
        # Se não caiu nas diagonais, verifica as retas
        elif dy < 0: op_code = packet.OP_WALK_NORTH
        elif dy > 0: op_code = packet.OP_WALK_SOUTH
        elif dx < 0: op_code = packet.OP_WALK_WEST
        elif dx > 0: op_code = packet.OP_WALK_EAST
        
        if op_code:
            # log_func(f"🚶 Passo exato (Packet: {hex(op_code)})...")
            packet.walk(pm, op_code)
            
            # Delay levemente randomizado para humanizar o "passo"
            time.sleep(0.5 + random.uniform(0.05, 0.15)) 
            return False 

    # 2. SE ESTIVER LONGE (> 1 SQM) -> USA MOUSE (CLIENT PATHFINDER)
    gv = get_game_view(pm, base_addr)
    if gv:
        # Calcula posição relativa na tela
        screen_x, screen_y = get_screen_coord(gv, dx, dy, hwnd)
        
        left_click_at(hwnd, screen_x, screen_y)
        
        # Espera inteligente baseada na distância
        # (Distancia * 0.1s) + base fixa
        time.sleep(0.5 + (dist_sqm * 0.1)) 
        return False
            
    return False

def get_item_id_in_hand(pm, base_addr, slot_enum):
    """
    Lê o ID do item que está na mão especificada (Left/Right) direto da memória.
    """
    try:
        offset = 0
        # Mapeia o Enum do Packet (5/6) para o Offset da Memória (config.py)
        if slot_enum == SLOT_RIGHT: # 5
            offset = OFFSET_SLOT_RIGHT # 0x1CED90
        elif slot_enum == SLOT_LEFT:  # 6
            offset = OFFSET_SLOT_LEFT  # 0x1CED9C
        else:
            return 0
            
        # Lê o ID (4 bytes)
        return pm.read_int(base_addr + offset)
    except:
        return 0
    
def unequip_hand(pm, base_addr, slot_enum, dest_container_idx=0):
    """
    Verifica se a mão está ocupada. Se estiver, move o item para a BP.
    Retorna: O ID do item removido (ou None se estava vazia).
    """
    # 1. Lê o que está na mão agora
    current_id = get_item_id_in_hand(pm, base_addr, slot_enum)
    
    if current_id > 0:
        # print(f"[RUNE] Mão ocupada por {current_id}. Guardando...")
        
        # Posição de Origem: Mão
        pos_from = packet.get_inventory_pos(slot_enum)
        
        # Posição de Destino: Container 0 (BP Principal), Slot 0 (Empurra o resto)
        # Nota: Usamos slot 254 ou 0 dependendo da implementação do packet, 
        # mas jogar no slot 0 geralmente funciona para empurrar.
        pos_to = packet.get_container_pos(dest_container_idx, 0) 
        
        # Move o item
        packet.move_item(pm, pos_from, pos_to, current_id, 1)
        time.sleep(0.5) # Tempo para o item chegar na BP
        
        check_id = get_item_id_in_hand(pm, base_addr, slot_enum)
        if check_id == 0:
            return current_id
        else:
            print(f"[RUNE] FALHA ao desequipar! Item {check_id} ainda na mão (BP cheia?).")
            return None # Falha crítica
    
    return None

def reequip_hand(pm, base_addr, item_id, target_slot_enum, container_idx=0):
    """
    Procura o item antigo na BP e coloca de volta na mão.
    """
    if not item_id: return
    
    # 1. Precisa achar onde o item foi parar na BP (os slots mudam!)
    # Usamos a função que já existe no inventory_core
    from inventory_core import find_item_in_containers
    
    # Busca o item específico
    item_data = find_item_in_containers(pm, base_addr, item_id)
    
    if item_data:
        # print(f"[RUNE] Restaurando item {item_id} para a mão...")
        pos_from = packet.get_container_pos(item_data['container_index'], item_data['slot_index'])
        pos_to = packet.get_inventory_pos(target_slot_enum)
        
        packet.move_item(pm, pos_from, pos_to, item_id, 1)
        time.sleep(0.4)
    else:
        print(f"[RUNE] ERRO: Não consegui achar o item {item_id} para reequipar!")
    
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
    FULL_COOLDOWN_SECONDS = 60 # Se estiver full, espera 1 minuto antes de tentar de novo

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
        # LÓGICA DE COMIDA (AUTO EAT)
        # ======================================================================
        if config.get('auto_eat', False):
            # 1. Verifica se estamos no "Castigo" (Full Lock)
            if is_full_lock:
                if time.time() - full_lock_time > FULL_COOLDOWN_SECONDS:
                    is_full_lock = False 
                    print("[RUNE-EAT] Castigo de Full acabou. Liberado para tentar comer.")
                else:
                    # Opcional: print só a cada 5s para não spammar
                    # print(f"[RUNE-EAT] Bloqueado por FULL. Restam {int(FULL_COOLDOWN_SECONDS - (time.time() - full_lock_time))}s")
                    pass

            # 2. Se não estiver bloqueado, consulta a lógica da GUI (check_hunger)
            if not is_full_lock:
                is_hungry_func = config.get('check_hunger')
                
                if is_hungry_func:
                    # AQUI ESTÁ O SEGREDO: Chamamos a função e guardamos o resultado
                    status_fome = is_hungry_func() 
                    
                    # Agora o print vai mostrar True ou False
                    #print(f"[RUNE-EAT] Check Fome retornou: {status_fome}") 

                    if status_fome:
                        print(f"[RUNE-EAT] Iniciando tentativa de comer...")
                        try:
                            result = attempt_eat(pm, base_addr, hwnd)
                            
                            if result == "FULL":
                                log_msg("⚠️ Personagem cheio. Pausando comida por 60s.")
                                is_full_lock = True
                                full_lock_time = time.time()
                            
                            elif result:
                                food_id = result
                                food_name = foods_db.get_food_name(food_id)
                                log_msg(f"🍖 {food_name} consumida.")
                                
                                # CHAMA O CALLBACK SE EXISTIR
                                if eat_callback: eat_callback(food_id)
                            
                            else:
                                print("[RUNE-EAT] Tentou comer mas não achou comida (attempt_eat retornou False)")
                                pass
                                
                        except Exception as e:
                            print(f"[DEBUG] Erro ao comer: {e}")
                    else:
                        # Caiu aqui pq status_fome é False
                        # Motivos prováveis: Não sincronizou regen ainda, ou está Full no tracker
                        pass


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
                
                if time.time() - last_mana_log > 10:
                    # Log menos frequente para não poluir
                    last_mana_log = time.time()

                if curr_mana >= mana_req:
                    log_msg(f"⚡ Mana cheia ({curr_mana}). Usando {hotkey_str}...")
                    press_hotkey(hwnd, vk_hotkey)
                    time.sleep(2.2) 
                else:
                    time.sleep(1)
            except: time.sleep(1)
            continue 

        # ======================================================================
        # RUNEMAKER (Movimento + Runas)
        # ======================================================================
        
        # ... (Lógica de Movimento e Safe Spot permanece igual) ...
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
        # --- Ciclo de Fabricação ---
        if mode == "WORKING":
            try:
                curr_mana = pm.read_int(base_addr + OFFSET_PLAYER_MANA)
            except: time.sleep(1); continue

            if curr_mana >= config.get('mana_req', 100):
                log_msg(f"⚡ Mana ok ({curr_mana}). Fabricando...")
                
                hand_mode = config.get('hand_mode', 'RIGHT')
                hands_to_use = []
                if hand_mode == "BOTH": hands_to_use = [SLOT_LEFT, SLOT_RIGHT]
                elif hand_mode == "LEFT": hands_to_use = [SLOT_LEFT]
                else: hands_to_use = [SLOT_RIGHT]
                
                active_runes = []
                
                for slot_enum in hands_to_use:
                    if is_safe_callback and not is_safe_callback(): break
                    
                    # === PASSO 2.1a: LIMPEZA DE MÃO (NOVO) ===
                    # Verifica se a mão está ocupada e guarda o item
                    unequipped_item_id = unequip_hand(pm, base_addr, slot_enum)
                    
                    # === BUSCA DA BLANK RUNE ===
                    # Fazemos a busca AGORA, pois se movemos uma espada para a BP, 
                    # os slots mudaram de lugar.
                    blank_data = find_item_in_containers(pm, base_addr, config.get('blank_id', 3147))
                    
                    if not blank_data:
                        log_msg(f"⚠️ Sem Blanks na BP! (Ou não encontrada)")
                        # Se tiramos a espada, tenta devolver antes de abortar
                        if unequipped_item_id:
                            reequip_hand(pm, base_addr, unequipped_item_id, slot_enum)
                        break
                    
                    # Move Blank -> Mão
                    pos_from = packet.get_container_pos(blank_data['container_index'], blank_data['slot_index'])
                    pos_to = packet.get_inventory_pos(slot_enum)
                    packet.move_item(pm, pos_from, pos_to, config.get('blank_id', 3147), 1)
                    
                    # Registra ação para finalizar depois
                    active_runes.append({
                        "hand_pos": pos_to, 
                        "origin_idx": blank_data['container_index'], 
                        "slot_enum": slot_enum,
                        "restorable_item": unequipped_item_id # Guardamos o ID da espada aqui
                    })
                    time.sleep(0.4)

                if active_runes:
                    log_msg(f"🪄 Pressionando {hotkey_str}...")
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
                    
        time.sleep(0.5)