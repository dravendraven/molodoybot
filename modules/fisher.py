import time
import random
import traceback
import math 
from core import packet 
from config import *
from core.inventory_core import find_item_in_containers, find_item_in_equipment
from core.map_core import get_player_pos
from modules.stacker import auto_stack_items
from database import fishing_db
from core.memory_map import MemoryMap

# ==============================================================================
# VARIÁVEIS GLOBAIS DE SESSÃO
# ==============================================================================
fishing_sessions = {}

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
    try:
        timer = int(pm.read_int(base_addr + OFFSET_STATUS_TIMER))
        if timer > 0:
            return pm.read_string(base_addr + OFFSET_STATUS_TEXT, 64).lower()
        return ""
    except: return ""

def format_cooldown(seconds_left):
    if seconds_left <= 0: return ""
    if seconds_left < 60: return f"{int(seconds_left)}s"
    mins = int(seconds_left // 60)
    return f"{mins}m"

def get_rod_packet_position(pm, base_addr):
    try:
        if pm.read_int(base_addr + OFFSET_SLOT_AMMO) == ROD_ID: 
            return packet.get_inventory_pos(10)
        if pm.read_int(base_addr + OFFSET_SLOT_LEFT) == ROD_ID: 
            return packet.get_inventory_pos(6)
        if pm.read_int(base_addr + OFFSET_SLOT_RIGHT) == ROD_ID: 
            return packet.get_inventory_pos(5)
    except: pass

    equip = find_item_in_equipment(pm, base_addr, ROD_ID) 
    if equip:
        if equip['slot'] == 'right': return packet.get_inventory_pos(5) 
        elif equip['slot'] == 'left': return packet.get_inventory_pos(6) 
        elif equip['slot'] == 'ammo': return packet.get_inventory_pos(10)
    
    cont_data = find_item_in_containers(pm, base_addr, ROD_ID)
    if cont_data:
        return packet.get_container_pos(cont_data['container_index'], cont_data['slot_index'])
    return None

# ==============================================================================
# LOOP PRINCIPAL
# ==============================================================================

def fishing_loop(pm, base_addr, hwnd, check_running=None, log_callback=None, 
                 debug_hud_callback=None, config=None):
    
    def get_cfg(key, default):
        if callable(config): return config().get(key, default)
        return default

    def log_msg(text):
        timestamp = time.strftime("%H:%M:%S")
        print(f"[{timestamp}] [FISHER] {text}")
        if log_callback: log_callback(f"[FISHER] {text}")

    # Inicializa Fadiga (Controle Interno)
    fatigue_count = 0
    fatigue_limit = random.randint(*FATIGUE_ACTIONS_RANGE)
    fatigue_active_msg_shown = False 

    # Inicializa Stats Globais (Para Log e Display)
    session_fish_caught = 0
    session_total_casts = 0

    log_msg("🎣 Fisher Iniciado.")

    mapper = MemoryMap(pm, base_addr)
    player_id = 0
    cap_paused = False 
    
    current_target_coords = None

    # try:
    #     w_len = len(WATER_IDS)
    #     #log_msg(f"ℹ️ Config: {w_len} IDs. Validação ID: {FISH_CAUGHT_VALIDATION_BY_ID}")
    # except NameError:
    #     log_msg("❌ ERRO: IDs/Flags não configurados no config.py!")
    #     return

    # --- LÓGICA DE DELAY COM MICRO-PAUSAS (FADIGA MOTOR) ---
    def calculate_human_delay(tile_dx, tile_dy, current_fatigue=0, max_fatigue=100):
        # 1. Distância Física (Lei de Fitts)
        ROD_VIRTUAL_X = 14
        ROD_VIRTUAL_Y = 0 
        dist_sqm = math.sqrt((ROD_VIRTUAL_X - tile_dx)**2 + (ROD_VIRTUAL_Y - tile_dy)**2)
        
        base_reaction = random.uniform(BASE_REACTION_MIN, BASE_REACTION_MAX) 
        travel_speed = random.uniform(TRAVEL_SPEED_MIN, TRAVEL_SPEED_MAX) 
        
        raw_delay = base_reaction + (dist_sqm * travel_speed)

        # 2. Fator Fadiga (Lentidão Progressiva)
        fatigue_ratio = current_fatigue / max_fatigue if max_fatigue > 0 else 0
        motor_penalty = 0
        
        if fatigue_ratio > 0.5:
            # Curva exponencial suave: quanto mais cansado, mais lento
            intensity = (fatigue_ratio - 0.5) * 2 
            motor_penalty = raw_delay * (FATIGUE_MOTOR_PENALTY * intensity)
            
        return raw_delay + motor_penalty

    # --- SELEÇÃO PONDERADA (BIAS DIREITA + CLUSTERING) ---
    def select_best_target(candidates_list, last_coords):
        if not candidates_list: return None
        
        # Pega a força do config (ou usa 3.0 como padrão)
        bias_strength = get_cfg('right_bias', 3.0) 

        weights = []
        for cand in candidates_list:
            cdx, cdy, _ = cand
            weight = 50.0 
            
            # Peso por posição (Direita > Esquerda)
            weight += (cdx * bias_strength) 
            
            # Peso por proximidade (Clustering)
            if last_coords:
                ldx, ldy = last_coords
                dist = math.sqrt((cdx - ldx)**2 + (cdy - ldy)**2)
                proximity_bonus = (15.0 / (dist + 1.0)) * 5.0
                weight += proximity_bonus
            
            if weight < 1: weight = 1
            weights.append(weight)
            
        return random.choices(candidates_list, weights=weights, k=1)[0]

    while True:
        try:
            if check_running and not check_running(): return
            
            # Lê config de fadiga em tempo real
            is_fatigue_enabled = get_cfg('fatigue', True)

            # Log inicial da fadiga (apenas uma vez)
            if is_fatigue_enabled and not fatigue_active_msg_shown:
                log_msg(f"🔋 Stamina Inicial: {fatigue_limit} ações.")
                fatigue_active_msg_shown = True

            # -------------------------------------------------------------
            # 1. VERIFICAÇÕES DE ESTADO
            # -------------------------------------------------------------
            current_check_cap = get_cfg('check_cap', True)
            current_min_cap = get_cfg('min_cap_val', 6.0)

            if current_check_cap:
                cap_now = get_player_cap(pm, base_addr)
                if cap_now < current_min_cap:
                    if not cap_paused:
                        log_msg(f"⛔ Cap baixa ({cap_now:.1f} oz). Pausando...")
                        cap_paused = True
                        if debug_hud_callback: debug_hud_callback([]) 
                    time.sleep(2) 
                    continue 
                else:
                    if cap_paused:
                        log_msg(f"✅ Cap recuperada. Retomando...")
                        cap_paused = False

            if player_id == 0:
                try:
                    player_id = pm.read_int(base_addr + OFFSET_PLAYER_ID)
                    if player_id == 0: time.sleep(1); continue
                except: time.sleep(1); continue

            if not mapper.read_full_map(player_id):
                time.sleep(0.5); continue
            
            if mapper.center_index == -1:
                time.sleep(1); continue

            rod_pos = get_rod_packet_position(pm, base_addr)
            if not rod_pos:
                log_msg("❌ Vara não encontrada.")
                time.sleep(5); continue
                
            px, py, pz = get_player_pos(pm, base_addr)
            
            # -------------------------------------------------------------
            # 2. SCAN & HUD BUILDER
            # -------------------------------------------------------------
            candidates = []
            hud_grid = {} 
            
            for dy in range(-5, 6):
                for dx in range(-7, 8):
                    if dx == 0 and dy == 0: continue
                    tile = mapper.get_tile(dx, dy)
                    if tile:
                        top_id = tile.get_top_item()
                        if top_id in WATER_IDS:
                            abs_x = px + dx
                            abs_y = py + dy
                            
                            ts_release = 0
                            try: ts_release = fishing_db.get_cooldown_timestamp(abs_x, abs_y, pz)
                            except: pass
                            
                            time_left = max(0, ts_release - time.time())
                            
                            # PRIORIDADE 1: COOLDOWN (CINZA)
                            if time_left > 0:
                                hud_grid[(dx, dy)] = {'color': '#808080', 'text': format_cooldown(time_left)}
                            else:
                                # PRIORIDADE 2: DISPONÍVEL
                                if top_id in VISUAL_EMPTY_IDS:
                                    # Vermelho Sutil (Sem Texto)
                                    hud_grid[(dx, dy)] = {'color': '#CD5C5C', 'text': str(top_id)}
                                else:
                                    # Verde Sutil (Candidato)
                                    status = fishing_db.is_tile_ready(abs_x, abs_y, pz)
                                    if status == "READY" or status == "UNKNOWN":
                                        candidates.append((dx, dy, top_id))
                                        hud_grid[(dx, dy)] = {'color': '#010092', 'text': ''}

            # Sobreposição de Sessão (Amarelo)
            for (sx, sy), s_data in fishing_sessions.items():
                sdx = sx - px
                sdy = sy - py
                if abs(sdx) <= 7 and abs(sdy) <= 5:
                    if (sdx, sdy) in hud_grid and '808080' not in hud_grid[(sdx, sdy)]['color']:
                        hud_grid[(sdx, sdy)] = {'color': '#FFFFE0', 'text': f"{s_data['done']}/{s_data['limit']}"}

            if debug_hud_callback:
                final_batch = [{'dx': k[0], 'dy': k[1], **v} for k, v in hud_grid.items()]
                debug_hud_callback(final_batch)

            if not candidates:
                time.sleep(1)
                continue
            
            # -------------------------------------------------------------
            # 3. SELEÇÃO DE ALVO
            # -------------------------------------------------------------
            target = None
            min_att = get_cfg('min_attempts', 4)
            max_att = get_cfg('max_attempts', 6)

            # Chance de trocar: 30% ou se não tiver alvo
            should_switch = (random.random() < 0.5) or (current_target_coords is None)
            
            if current_target_coords:
                is_valid = False
                for c in candidates:
                    if c[0] == current_target_coords[0] and c[1] == current_target_coords[1]:
                        target = c
                        is_valid = True
                        break
                if not is_valid: should_switch = True

            if should_switch or not target:
                target = select_best_target(candidates, current_target_coords) 
                if target: current_target_coords = (target[0], target[1])

            dx, dy, water_id = target
            abs_x = px + dx
            abs_y = py + dy
            
            if (abs_x, abs_y) not in fishing_sessions:
                limit = random.randint(min_att, max_att)
                if FISH_CAUGHT_VALIDATION_BY_ID: limit = 8
                fishing_sessions[(abs_x, abs_y)] = {
                    'done': 0, 'limit': limit, 'start_time': time.time()
                }
            
            session = fishing_sessions[(abs_x, abs_y)]
            
            # Sobreposição Alvo (Verde Forte)
            hud_grid[(dx, dy)] = {'color': '#00FF00', 'text': 'x'}
            if debug_hud_callback:
                final_batch = [{'dx': k[0], 'dy': k[1], **v} for k, v in hud_grid.items()]
                debug_hud_callback(final_batch)

            # -------------------------------------------------------------
            # 4. EXECUÇÃO
            # -------------------------------------------------------------
            water_pos = packet.get_ground_pos(abs_x, abs_y, pz)
            
            # CALCULA DELAY (COM FADIGA)
            human_wait = calculate_human_delay(dx, dy, fatigue_count, fatigue_limit)
            time.sleep(human_wait)
            
            cap_before = get_player_cap(pm, base_addr)
            packet.use_with(pm, rod_pos, ROD_ID, 0, water_pos, water_id, 0)
            
            # Atualiza Contadores
            session_total_casts += 1 
            if is_fatigue_enabled:
                fatigue_count += 1
            
            time.sleep(random.uniform(0.6, 0.8))
            
            # --- CHECAGEM DE DESCANSO (FADIGA) ---
            if is_fatigue_enabled and fatigue_count >= fatigue_limit:
                rest_time = random.uniform(*FATIGUE_REST_RANGE)
                log_msg(f"🥱 Cansou ({fatigue_count} ações). Pausa de {rest_time:.1f}s...")
                
                # Feedback visual de descanso (apenas passivos)
                if debug_hud_callback: 
                    passive_batch = [{'dx': k[0], 'dy': k[1], **v} for k, v in hud_grid.items() if v['color'] != '#00FF00']
                    debug_hud_callback(passive_batch)
                
                time.sleep(rest_time)
                
                # Reset
                fatigue_count = 0
                fatigue_limit = random.randint(*FATIGUE_ACTIONS_RANGE)
                log_msg(f"🔋 Energia cheia! Próxima pausa em ~{fatigue_limit} ações.")
                continue 

            error_msg = get_status_message(pm, base_addr)
            if "throw there" in error_msg or any(x in error_msg for x in ["not possible", "cannot use", "sorry"]):
                if (abs_x, abs_y) in fishing_sessions: del fishing_sessions[(abs_x, abs_y)]
                continue

            # -------------------------------------------------------------
            # 5. VALIDAÇÃO
            # -------------------------------------------------------------
            success = False
            cap_after = get_player_cap(pm, base_addr)
            
            if not FISH_CAUGHT_VALIDATION_BY_ID:
                if (cap_before - cap_after) > 1.0: success = True
            else:
                time.sleep(0.2) 
                if mapper.read_full_map(player_id):
                    new_tile = mapper.get_tile(dx, dy)
                    if new_tile:
                        new_id = new_tile.get_top_item()
                        if new_id in VISUAL_EMPTY_IDS: success = True

            session['done'] += 1
            
            if success:
                session_fish_caught += 1
                
                # LOG GLOBAL ATUALIZADO
                log_msg(f"✅ PEIXE! [{session_fish_caught}/{session_total_casts}]")
                
                fishing_db.mark_fish_caught(abs_x, abs_y, pz)
                auto_stack_items(pm, base_addr, hwnd)
                if (abs_x, abs_y) in fishing_sessions: del fishing_sessions[(abs_x, abs_y)]
                current_target_coords = None 
                
            else:
                if session['done'] >= session['limit']:
                    log_msg(f"💨 Desisto ({dx}, {dy})...")
                    penalty = 600 
                    fake_last = time.time() + penalty - FISH_RESPAWN_TIME
                    fishing_db.mark_fish_caught(abs_x, abs_y, pz, custom_timestamp=fake_last)
                    if (abs_x, abs_y) in fishing_sessions: del fishing_sessions[(abs_x, abs_y)]
                    current_target_coords = None
                    
                    hud_grid[(dx, dy)] = {'color': '#CD5C5C', 'text': ''}
                    if debug_hud_callback:
                        final_batch = [{'dx': k[0], 'dy': k[1], **v} for k, v in hud_grid.items()]
                        debug_hud_callback(final_batch)

            now = time.time()
            to_remove = [k for k, v in fishing_sessions.items() if (now - v['start_time']) > 300]
            for k in to_remove: del fishing_sessions[k]

        except Exception as e:
            log_msg(f"🔥 ERRO: {e}")
            traceback.print_exc()
            time.sleep(5)