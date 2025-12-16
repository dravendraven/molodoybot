import time
import winsound
from config import *
from core.map_core import get_player_pos

def get_connected_char_name(pm, base_addr):
    """Lê o nome do próprio personagem para evitar alarme falso."""
    try:
        if pm is None: return ""
        player_id = pm.read_int(base_addr + OFFSET_PLAYER_ID)
        if player_id == 0: return ""

        list_start = base_addr + TARGET_ID_PTR + REL_FIRST_ID
        for i in range(MAX_CREATURES):
            slot = list_start + (i * STEP_SIZE)
            c_id = pm.read_int(slot)
            if c_id == player_id:
                name = pm.read_string(slot + OFFSET_NAME, 32)
                return name.split('\x00')[0].strip()
    except: pass
    return ""

def alarm_loop(pm, base_addr, check_running, config, callbacks):
    
    # --- HELPER: LER CONFIGURAÇÃO EM TEMPO REAL ---
    # Usamos esta função interna para puxar dados do lambda no main.py
    def get_cfg(key, default):
        return config().get(key, default) if callable(config) else default

    # Callbacks
    set_safe_state = callbacks.get('set_safe', lambda x: None)
    set_gm_state = callbacks.get('set_gm', lambda x: None)
    send_telegram = callbacks.get('telegram', lambda x: None)
    log_msg = callbacks.get('log', print)

    last_alert_time = 0
    last_hp_alert = 0 # Controle de spam do beep de vida
    
    log_msg("🔔 Módulo de Alarme Iniciado.")

    while True:
        if check_running and not check_running(): return

        # 1. Verifica se o Alarme Global está ativado
        enabled = get_cfg('enabled', False)
        if not enabled:
            set_safe_state(True)
            set_gm_state(False)
            time.sleep(1)
            continue

        if pm is None: time.sleep(1); continue

        # Lê configs dinâmicas
        safe_list = get_cfg('safe_list', [])
        alarm_range = get_cfg('range', 8)
        floor_mode = get_cfg('floor', "Padrão")
        
        # Lê configs de HP (Novas)
        hp_check_enabled = get_cfg('hp_enabled', False)
        hp_threshold = get_cfg('hp_percent', 50)

        try:
            # =================================================================
            # A. VERIFICAÇÃO DE HP BAIXO
            # =================================================================
            if hp_check_enabled:
                curr_hp = pm.read_int(base_addr + OFFSET_PLAYER_HP)
                max_hp = pm.read_int(base_addr + OFFSET_PLAYER_HP_MAX)
                
                if max_hp > 0 and curr_hp > 0:
                    pct = (curr_hp / max_hp) * 100
                    
                    if pct < hp_threshold:
                        # Limita o alerta a cada 2 segundos para não travar
                        if (time.time() - last_hp_alert) > 2.0:
                            log_msg(f"🩸 ALARME DE VIDA: {pct:.1f}% (Abaixo de {hp_threshold}%)")
                            # Som mais agudo e rápido para diferenciar
                            winsound.Beep(2000, 200) 
                            winsound.Beep(2000, 200)
                            last_hp_alert = time.time()

            # =================================================================
            # B. VERIFICAÇÃO DE CRIATURAS/GM
            # =================================================================
            current_name = get_connected_char_name(pm, base_addr)
            list_start = base_addr + TARGET_ID_PTR + REL_FIRST_ID
            my_x, my_y, my_z = get_player_pos(pm, base_addr)
            
            danger = False
            danger_name = ""
            is_gm_cycle = False

            for i in range(MAX_CREATURES):
                slot = list_start + (i * STEP_SIZE)
                try:
                    c_id = pm.read_int(slot)
                    if c_id > 0: 
                        name_raw = pm.read_string(slot + OFFSET_NAME, 32)
                        name = name_raw.split('\x00')[0].strip()
                        if name == current_name: continue

                        vis = pm.read_int(slot + OFFSET_VISIBLE)
                        cz = pm.read_int(slot + OFFSET_Z)
                        
                        valid_floor = False
                        if floor_mode == "Padrão": valid_floor = (cz == my_z)
                        elif floor_mode == "Superior (+1)": valid_floor = (cz == my_z or cz == my_z - 1)
                        elif floor_mode == "Inferior (-1)": valid_floor = (cz == my_z or cz == my_z + 1)
                        else: valid_floor = (abs(cz - my_z) <= 1)

                        if vis != 0 and valid_floor:
                            if name.startswith("GM ") or name.startswith("CM ") or name.startswith("God "):
                                danger = True
                                is_gm_cycle = True
                                danger_name = f"GAMEMASTER {name}"
                                break
                            
                            is_safe_creature = any(s in name for s in safe_list)
                            
                            if not is_safe_creature:
                                cx = pm.read_int(slot + OFFSET_X)
                                cy = pm.read_int(slot + OFFSET_Y)
                                dist = max(abs(my_x - cx), abs(my_y - cy))
                                
                                if dist <= alarm_range:
                                    danger = True
                                    danger_name = f"{name} ({dist} sqm)"
                                    break
                except: continue

            # Atualiza Main
            if danger:
                set_safe_state(False)
            else:
                set_safe_state(True)
            
            set_gm_state(is_gm_cycle)

            if danger:
                log_msg(f"⚠️ PERIGO: {danger_name}!")
                
                # Som grave para monstros
                freq = 2500 if is_gm_cycle else 1000
                winsound.Beep(freq, 500)
                
                if (time.time() - last_alert_time) > 60:
                    send_telegram(f"PERIGO! {danger_name} detectado!")
                    last_alert_time = time.time()
            
            time.sleep(0.5)

        except Exception as e:
            print(f"[ALARM ERROR] {e}")
            time.sleep(1)