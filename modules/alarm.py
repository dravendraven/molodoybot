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
    def get_cfg(key, default):
        return config().get(key, default) if callable(config) else default

    # Recupera as funções de callback (para falar com o main.py)
    set_safe_state = callbacks.get('set_safe', lambda x: None)
    set_gm_state = callbacks.get('set_gm', lambda x: None)
    send_telegram = callbacks.get('telegram', lambda x: None)
    log_msg = callbacks.get('log', print)

    last_alert_time = 0
    
    # Variável local para persistir se achou GM neste ciclo
    gm_found = False 

    log_msg("🔔 Módulo de Alarme Iniciado.")

    while True:
        # Verifica se o bot deve continuar rodando
        if check_running and not check_running(): return

        # 1. Verifica se o Alarme está ativado (Real-Time)
        enabled = get_cfg('enabled', False)
        if not enabled:
            # Se o usuário desligou o alarme, consideramos "Seguro"
            # para não travar o Trainer/Fisher
            set_safe_state(True)
            set_gm_state(False)
            time.sleep(1)
            continue

        # 2. Lê configurações atuais
        safe_list = get_cfg('safe_list', [])
        alarm_range = get_cfg('range', 8)
        floor_mode = get_cfg('floor', "Padrão")

        if pm is None: time.sleep(1); continue

        try:
            current_name = get_connected_char_name(pm, base_addr)
            list_start = base_addr + TARGET_ID_PTR + REL_FIRST_ID
            my_x, my_y, my_z = get_player_pos(pm, base_addr)
            
            danger = False
            danger_name = ""
            is_gm_cycle = False

            # SCAN DA TELA
            for i in range(MAX_CREATURES):
                slot = list_start + (i * STEP_SIZE)
                try:
                    c_id = pm.read_int(slot)
                    # Se existe criatura e não sou eu
                    if c_id > 0: 
                        name_raw = pm.read_string(slot + OFFSET_NAME, 32)
                        name = name_raw.split('\x00')[0].strip()
                        if name == current_name: continue

                        vis = pm.read_int(slot + OFFSET_VISIBLE)
                        cz = pm.read_int(slot + OFFSET_Z)
                        
                        # Verifica Filtro de Andar
                        valid_floor = False
                        if floor_mode == "Padrão": valid_floor = (cz == my_z)
                        elif floor_mode == "Superior (+1)": valid_floor = (cz == my_z or cz == my_z - 1)
                        elif floor_mode == "Inferior (-1)": valid_floor = (cz == my_z or cz == my_z + 1)
                        else: valid_floor = (abs(cz - my_z) <= 1) # Todos/Raio-X

                        if vis != 0 and valid_floor:
                            # A. É um GM/CM/God?
                            if name.startswith("GM ") or name.startswith("CM ") or name.startswith("God "):
                                danger = True
                                is_gm_cycle = True
                                danger_name = f"GAMEMASTER {name}"
                                break
                            
                            # B. É uma criatura segura (Lista de Amigos)?
                            # Se o nome estiver na lista, ignoramos
                            is_safe_creature = any(s in name for s in safe_list)
                            
                            if not is_safe_creature:
                                cx = pm.read_int(slot + OFFSET_X)
                                cy = pm.read_int(slot + OFFSET_Y)
                                dist = max(abs(my_x - cx), abs(my_y - cy))
                                
                                # C. Está dentro do alcance perigoso?
                                if dist <= alarm_range:
                                    danger = True
                                    danger_name = f"{name} ({dist} sqm)"
                                    break
                except: continue

            # --- AÇÕES FINAIS DO CICLO ---
            
            # Atualiza variáveis globais no Main (via callback)
            if danger:
                set_safe_state(False) # PERIGO!
            else:
                set_safe_state(True)  # Seguro
            
            set_gm_state(is_gm_cycle)

            if danger:
                log_msg(f"⚠️ PERIGO: {danger_name}!")
                
                # Som diferente para GM vs Player/Monstro
                freq = 2000 if is_gm_cycle else 1000
                winsound.Beep(freq, 500)
                
                # Telegram com limitação de spam (1 min)
                if (time.time() - last_alert_time) > 60:
                    send_telegram(f"PERIGO! {danger_name} detectado!")
                    last_alert_time = time.time()
            
            time.sleep(0.5)

        except Exception as e:
            print(f"[ALARM ERROR] {e}")
            time.sleep(1)