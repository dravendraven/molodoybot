import time
import random

from core import packet 
from config import *
from core.inventory_core import find_item_in_containers, find_item_in_equipment
from core.map_core import get_player_pos, get_game_view, get_screen_coord
from core.input_core import shift_click_at
from core.mouse_lock import acquire_mouse, release_mouse
from modules.stacker import auto_stack_items
from database import fishing_db
from core.memory_map import MemoryMap

# ==============================================================================
# FUNÇÕES AUXILIARES
# ==============================================================================
def get_player_cap(pm, base_addr):
    try:
        val = pm.read_float(base_addr + OFFSET_PLAYER_CAP)
        if val < 0.1:
             val = float(pm.read_int(base_addr + OFFSET_PLAYER_CAP))
        return val
    except: return 0.0

def get_status_message(pm, base_addr):
    """Lê a mensagem atual da barra de status para identificar erros específicos."""
    try:
        timer = int(pm.read_int(base_addr + OFFSET_STATUS_TIMER))
        if timer > 0:
            return pm.read_string(base_addr + OFFSET_STATUS_TEXT, 64).lower()
        return ""
    except: return ""

def format_cooldown(seconds_left):
    """Formata segundos para texto curto (ex: '50s' ou '2m')."""
    if seconds_left <= 0: return ""
    if seconds_left < 60: return f"{int(seconds_left)}s"
    mins = int(seconds_left // 60)
    return f"{mins}m"

def get_rod_packet_position(pm, base_addr):
    equip = find_item_in_equipment(pm, base_addr, ROD_ID) 
    if equip:
        if equip['slot'] == 'right': return packet.get_inventory_pos(5) 
        elif equip['slot'] == 'left': return packet.get_inventory_pos(6) 
        elif equip['slot'] == 'ammo': return packet.get_inventory_pos(10)
            
    if pm.read_int(base_addr + OFFSET_SLOT_LEFT) == ROD_ID: return packet.get_inventory_pos(6)
    if pm.read_int(base_addr + OFFSET_SLOT_RIGHT) == ROD_ID: return packet.get_inventory_pos(5)
    
    cont_data = find_item_in_containers(pm, base_addr, ROD_ID)
    if cont_data:
        return packet.get_container_pos(cont_data['container_index'], cont_data['slot_index'])
    return None

def probe_tile(pm, base_addr, hwnd, gv, dx, dy, abs_x, abs_y, z, logger=None):
    tx, ty = get_screen_coord(gv, dx, dy, hwnd)
    acquire_mouse()
    try:
        shift_click_at(hwnd, tx, ty)
    finally:
        release_mouse()
    
    time.sleep(0.35) 
    
    offset_interaction = globals().get('OFFSET_LAST_INTERACTION_ID', 0x31C630)
    last_id = pm.read_int(base_addr + offset_interaction)
    
    # Só salva no banco se for TRUE (água confirmada)
    is_water = (last_id in WATER_IDS)
    if is_water:
        fishing_db.update_tile_type(abs_x, abs_y, z, True)
    else:
        # Se deu False, pode ser lag ou erro de clique.
        # NÃO salvamos 'False' no banco para não estragar o spot.
        # Apenas retornamos False para o loop pular essa tentativa.
        print(f"[PROTEÇÃO] Probe falhou ou não é água em {abs_x},{abs_y}. Não atualizando DB.")
        pass 

    return is_water, last_id



# ==============================================================================
# LOOP PRINCIPAL
# ==============================================================================

def fishing_loop(pm, base_addr, hwnd, check_running=None, log_callback=None, 
                 debug_hud_callback=None, config=None):
    
    # --- HELPER DE CONFIGURAÇÃO DINÂMICA ---
    def get_cfg(key, default):
        # Se 'config' for uma função, chama ela para pegar o dicionário atualizado
        if callable(config):
            return config().get(key, default)
        return default

    def log_msg(text):
        timestamp = time.strftime("%H:%M:%S")
        print(f"[{timestamp}] [FISHER] {text}")
        if log_callback: log_callback(f"[FISHER] {text}")

    log_msg("🎣 Fisher Iniciado (Scan Memória + Lógica Tentativa).")

    #mapper = MemoryMap(pm, base_addr)

    # Cache do Player ID (necessário para o MemoryMap calibrar a posição)
    #player_id = 0
    
    tile_id_cache = {} 
    
    def get_updated_hud_batch(p_x, p_y, p_z):
        batch = []
        for c_dy in range(-6, 7):
            for c_dx in range(-8, 9):
                if c_dx == 0 and c_dy == 0: continue
                c_abs_x = p_x + c_dx
                c_abs_y = p_y + c_dy
                try:
                    ts_release = fishing_db.get_cooldown_timestamp(c_abs_x, c_abs_y, p_z)
                except AttributeError: ts_release = 0 
                
                time_left = ts_release - time.time()
                if time_left > 0:
                    batch.append({
                        'dx': c_dx, 'dy': c_dy,
                        'color': '#555555', 
                        'text': format_cooldown(time_left)
                    })
        return batch

    while True:
        if check_running and not check_running(): return

        # ======================================================================
        # LEITURA DAS CONFIGS (AGORA DENTRO DO LOOP)
        # ======================================================================
        # Lemos os valores a cada ciclo. Se você mudou no GUI, muda aqui.
        current_check_cap = get_cfg('check_cap', True)
        current_min_cap = get_cfg('min_cap_val', 6.0)
        min_attempts = get_cfg('min_attempts', 4)
        max_attempts = get_cfg('max_attempts', 6)
        
        # ======================================================================
        # VERIFICAÇÃO DE CAP
        # ======================================================================
        if current_check_cap:
            current_cap = get_player_cap(pm, base_addr)
            if current_cap < current_min_cap:
                # time.sleep(5) 
                # continue 
                # (Mantendo comportamento original de pausa silenciosa ou log se preferir)
                time.sleep(2)
                continue 

        rod_pos = get_rod_packet_position(pm, base_addr)
        if not rod_pos:
            log_msg("❌ Vara não encontrada.")
            time.sleep(5)
            continue
            
        px, py, pz = get_player_pos(pm, base_addr)
        
        range_x = 7
        range_y = 5
        
        priority_tiles = []
        secondary_tiles = []
        
        for dy in range(-range_y, range_y + 1):
            for dx in range(-range_x, range_x + 1):
                if dx == 0 and dy == 0: continue
                abs_x, abs_y = px + dx, py + dy
                status = fishing_db.is_tile_ready(abs_x, abs_y, pz)
                if status == "READY" or status == "COOLDOWN":
                    priority_tiles.append((dx, dy))
                elif status == "UNKNOWN":
                    secondary_tiles.append((dx, dy))

        priority_tiles.sort(key=lambda p: max(abs(p[0]), abs(p[1])))
        secondary_tiles.sort(key=lambda p: max(abs(p[0]), abs(p[1])))
        
        tiles_to_check = priority_tiles + secondary_tiles
        
        cycle_fish_count = 0      
        cycle_tiles_fished = 0    
        cycle_tiles_cooldown = 0  

        hud_batch = get_updated_hud_batch(px, py, pz)
        if debug_hud_callback: debug_hud_callback(hud_batch)

        # ======================================================================
        # LOOP DE AÇÃO (TILES)
        # ======================================================================
        
        for (dx, dy) in tiles_to_check:
            if check_running and not check_running(): return
            
            # Re-checa cap dentro do loop interno com a config atualizada
            if current_check_cap:
                current_cap_loop = get_player_cap(pm, base_addr)
                if current_cap_loop < current_min_cap:
                    log_msg(f"⛔ Cap atingiu o limite ({current_cap_loop} oz).")
                    break 

            current_batch = list(hud_batch)
            current_batch.append({'dx': dx, 'dy': dy, 'color': '#00FFFF', 'text': None}) 
            if debug_hud_callback: debug_hud_callback(current_batch)

            abs_x, abs_y = px + dx, py + dy
            status = fishing_db.is_tile_ready(abs_x, abs_y, pz)
            
            if status == "COOLDOWN":
                cycle_tiles_cooldown += 1
            
            target_water_id = 0
            need_probe = (status == "UNKNOWN")
            
            if status == "READY":
                if (abs_x, abs_y) in tile_id_cache:
                    target_water_id = tile_id_cache[(abs_x, abs_y)]
                else:
                    need_probe = True

            if need_probe:
                current_batch[-1] = {'dx': dx, 'dy': dy, 'color': '#FFFF00', 'text': 'PROBE'}
                if debug_hud_callback: debug_hud_callback(current_batch)

                gv = get_game_view(pm, base_addr)
                if gv:
                    is_water, probed_id = probe_tile(pm, base_addr, hwnd, gv, dx, dy, abs_x, abs_y, pz, logger=None)
                    if is_water:
                        status = "READY"
                        target_water_id = probed_id
                        tile_id_cache[(abs_x, abs_y)] = probed_id 
                    else:
                        status = "IGNORE"
                else:
                    continue 

            if status == "READY" and target_water_id > 0:
                current_batch[-1] = {'dx': dx, 'dy': dy, 'color': '#00FF00', 'text': None}
                if debug_hud_callback: debug_hud_callback(current_batch)
                
                water_pos = packet.get_ground_pos(abs_x, abs_y, pz)
                success = False
                attempts = 0
                
                # --- USA A CONFIG DINÂMICA PARA O LIMITE ---
                limit = random.randint(min_attempts, max_attempts)
                # -------------------------------------------

                while attempts < limit:
                    if check_running and not check_running(): return
                    
                    cap_before = get_player_cap(pm, base_addr)
                    packet.use_with(pm, rod_pos, ROD_ID, 0, water_pos, target_water_id, 0)
                    
                    wait_time = random.uniform(1.5, 3.5) 
                    time.sleep(wait_time) 
                    
                    error_msg = get_status_message(pm, base_addr)
                    
                    if error_msg:
                        if "throw there" in error_msg:
                            log_msg(f"🧱 Obstrução em ({dx}, {dy}). Pulando.")
                            current_batch[-1] = {'dx': dx, 'dy': dy, 'color': '#FFA500', 'text': 'BLOCK'}
                            if debug_hud_callback: debug_hud_callback(current_batch)
                            break 
                        
                        elif any(x in error_msg for x in ["not possible", "cannot use", "sorry"]):
                            log_msg(f"⚠️ Erro ambíguo em ({dx}, {dy}). Re-checando tile...")
                            current_batch[-1] = {'dx': dx, 'dy': dy, 'color': '#A020F0', 'text': 'CHK'}
                            if debug_hud_callback: debug_hud_callback(current_batch)
                            
                            gv = get_game_view(pm, base_addr)
                            if gv:
                                is_still_water, new_id = probe_tile(pm, base_addr, hwnd, gv, dx, dy, abs_x, abs_y, pz)
                                if is_still_water:
                                    log_msg(f"✅ Confirmado água (ID: {new_id}). Retentando...")
                                    target_water_id = new_id
                                    tile_id_cache[(abs_x, abs_y)] = new_id
                                    current_batch[-1] = {'dx': dx, 'dy': dy, 'color': '#00FF00', 'text': None}
                                    if debug_hud_callback: debug_hud_callback(current_batch)
                                    continue 
                                else:
                                    log_msg(f"⛔ Confirmado: Não é mais água.")
                                    fishing_db.update_tile_type(abs_x, abs_y, pz, False)
                                    break
                            else:
                                break
                    
                    cap_after = get_player_cap(pm, base_addr)
                    if (cap_before - cap_after) > 4.0:
                        # SUCESSO
                        log_msg(f"✅ Peixe! ({dx}, {dy})")
                        fishing_db.mark_fish_caught(abs_x, abs_y, pz) 

                        hud_batch = get_updated_hud_batch(px, py, pz)
                        current_batch = list(hud_batch)
                        current_batch.append({'dx': dx, 'dy': dy, 'color': '#00FF00', 'text': None})
                        if debug_hud_callback: debug_hud_callback(current_batch)

                        success = True
                        cycle_fish_count += 1
                        cycle_tiles_fished += 1
                        
                        did_stack = auto_stack_items(pm, base_addr, hwnd)
                        if did_stack: time.sleep(0.2)
                        break
                    else:
                        attempts += 1
                
                if not success:
                    final_msg = get_status_message(pm, base_addr)
                    if not ("throw there" in final_msg or "not possible" in final_msg):
                        penalty = FISH_RESPAWN_TIME - FISH_FAIL_COOLDOWN 
                        fake_time = time.time() - penalty
                        fishing_db.mark_fish_caught(abs_x, abs_y, pz, custom_timestamp=fake_time)
                        
                        hud_batch = get_updated_hud_batch(px, py, pz)
                        current_batch = list(hud_batch)
                        current_batch.append({'dx': dx, 'dy': dy, 'color': '#FF0000', 'text': None}) 
                        if debug_hud_callback: debug_hud_callback(current_batch)
                        
                        cycle_tiles_fished += 1
                
                time.sleep(random.uniform(0.1, 0.3))

            if debug_hud_callback: debug_hud_callback(hud_batch)

        if cycle_tiles_fished > 0:
            log_msg(f"📊 RESUMO: +{cycle_fish_count} Peixes | {cycle_tiles_fished} Locais")
        elif cycle_tiles_cooldown > 0:
            log_msg(f"⏳ Tudo em Cooldown ({cycle_tiles_cooldown})...")
            if debug_hud_callback: debug_hud_callback(hud_batch) 
            time.sleep(5)
        else:
            time.sleep(2)