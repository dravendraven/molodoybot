import time
import random
import win32gui

from core import packet
from config import *
from core.map_core import get_player_pos, get_game_view, get_screen_coord
from core.input_core import ctrl_right_click_at
from core.mouse_lock import acquire_mouse, release_mouse

# Definições de Delay (Copiados do main.py original)
SCAN_DELAY = 0.5
# HUMAN_DELAY_MIN = 1
# HUMAN_DELAY_MAX = 2

def get_connected_char_name(pm, base_addr):
    """Lê o nome do personagem logado para evitar auto-target."""
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

def trainer_loop(pm, base_addr, hwnd, monitor, check_running, config):
    
    # --- HELPER PARA LER CONFIGURAÇÃO EM TEMPO REAL ---
    def get_cfg(key, default=None):
        return config().get(key, default) if callable(config) else default

    current_monitored_id = 0
    last_target_data = None 
    next_attack_time = 0       
    #waiting_for_attack = False

    # Loop Infinito do Módulo
    while True:
        # Verifica se o bot deve continuar rodando (Running + Connected)
        if check_running and not check_running(): 
            return # Encerra a thread se desconectar ou fechar o bot

        # 1. Verifica se o Trainer está ativado (Real-Time)
        if not get_cfg('enabled', False): 
            time.sleep(1)
            continue
        
        # 2. Verifica se o cliente está aberto
        if pm is None: 
            time.sleep(1)
            continue
            
        # 3. Atualiza o Handle da Janela se necessário
        if hwnd == 0: 
            hwnd = win32gui.FindWindow("TibiaClient", None) or win32gui.FindWindow(None, "Tibia")
            
        # 4. Verifica Segurança (Alarme) (Real-Time)
        if not get_cfg('is_safe', True): 
            time.sleep(0.5)
            continue 
        
        min_delay = get_cfg('min_delay', 1.0)
        max_delay = get_cfg('max_delay', 2.0)
        attack_range = get_cfg('range', 1) # Padrão 1 (Melee)
        log = get_cfg('log_callback', print)
        debug_mode = get_cfg('debug_mode', False)
        loot_enabled = get_cfg('loot_enabled', False)
        targets_list = get_cfg('targets', [])
        ignore_first = get_cfg('ignore_first', False)

        try:  
            current_name = get_connected_char_name(pm, base_addr)
            if not current_name: 
                time.sleep(0.5); continue
            
            target_addr = base_addr + TARGET_ID_PTR
            list_start = base_addr + TARGET_ID_PTR + REL_FIRST_ID
            my_x, my_y, my_z = get_player_pos(pm, base_addr)
            
            if my_z == 0: 
                time.sleep(0.2)
                continue

            # 2. SCAN: MAPEAR O CAMPO DE BATALHA
            valid_candidates = []
            visual_line_count = 0 

            if debug_mode: print(f"\n--- INÍCIO DO SCAN (Meu Z: {my_z}) ---")
            
            for i in range(MAX_CREATURES):
                slot = list_start + (i * STEP_SIZE)
                try:
                    c_id = pm.read_int(slot)
                    if c_id > 0:
                        raw = pm.read_string(slot + OFFSET_NAME, 32)
                        name = raw.split('\x00')[0].strip()
                        vis = pm.read_int(slot + OFFSET_VISIBLE)
                        z = pm.read_int(slot + OFFSET_Z)
                        cx = pm.read_int(slot + OFFSET_X)
                        cy = pm.read_int(slot + OFFSET_Y)
                        hp = pm.read_int(slot + OFFSET_HP)
                        
                        dist_x = abs(my_x - cx)
                        dist_y = abs(my_y - cy)
                        is_in_range = (dist_x <= attack_range and dist_y <= attack_range)
                
                        if debug_mode: print(f"Slot {i}: {name} (Vis:{vis} Z:{z} HP:{hp} Dist:({dist_x},{dist_y}))")

                        if name == current_name: continue

                        is_on_battle_list = (vis == 1 and z == my_z)

                        if is_on_battle_list:
                            if debug_mode: print(f"   [LINHA {visual_line_count}] -> {name} (ID: {c_id})")
                            current_line = visual_line_count
                            visual_line_count += 1 
                            
                            # Usa a lista dinâmica de targets
                            if any(t in name for t in targets_list):
                                if is_in_range and hp > 0:
                                    if debug_mode: print(f"      -> CANDIDATO: HP:{hp} Dist:({dist_x},{dist_y})")
                                    valid_candidates.append({
                                        "id": c_id,
                                        "name": name,
                                        "hp": hp,
                                        "dist_x": dist_x,
                                        "dist_y": dist_y,
                                        "abs_x": cx,
                                        "abs_y": cy,
                                        "z": z,
                                        "is_in_range": is_in_range,
                                        "line": current_line
                                    })
                except: continue

            if debug_mode:
                print(f"--- FIM DO SCAN (Total Linhas: {visual_line_count}) ---\n")
                print("--- CANDIDATOS VÁLIDOS ---")
                print(f"Valid Candidates:")
                print(f"Candidato 1: {valid_candidates[0] if len(valid_candidates) > 0 else 'Nenhum'}")
                print(f"Candidato 2: {valid_candidates[1] if len(valid_candidates) > 1 else 'Nenhum'}")
                print("-------------------------")
                print("---- TOMADA DE DECISÃO ----")

            current_target_id = pm.read_int(target_addr)
            should_attack_new = False

            # Cenário A: Já estou atacando alguém
            if current_target_id != 0:
                if debug_mode: print(f"Atacando ID: {current_target_id}")
                target_data = next((c for c in valid_candidates if c["id"] == current_target_id), None)
                if debug_mode: print(f"-> Target Data: {target_data}")
                
                if target_data:
                    #waiting_for_attack = False 
                    next_attack_time = 0       
                    last_target_data = target_data.copy()
                    if current_target_id != current_monitored_id:
                        monitor.start(current_target_id, target_data["name"], target_data["hp"])
                        current_monitored_id = current_target_id
                        if debug_mode: print(f"--> Iniciando monitoramento em {target_data['name']} (ID: {current_target_id})")
                    else:
                        monitor.update(target_data["hp"])
                        if debug_mode: print(f"--> Atualizando monitoramento em {target_data['name']} (HP: {target_data['hp']})")
                else:
                    if debug_mode: print("-> Alvo inválido (morto/fora de alcance).")
                    pass

           # --- CENÁRIO B: O ALVO SUMIU (MORREU OU PAREI DE ATACAR?) ---
            elif current_target_id == 0 and current_monitored_id != 0:
                target_still_alive = False
                if last_target_data:
                    for m in valid_candidates:
                        if m["id"] == last_target_data["id"]:
                            target_still_alive = True
                            break
                
                if target_still_alive:
                    log("🛑 Ataque interrompido (Monstro ainda vivo).")
                    monitor.stop_and_report()
                    current_monitored_id = 0
                    last_target_data = None
                    should_attack_new = True 
                
                else:
                    log("💀 Alvo eliminado (Confirmado).")
                    
                    if last_target_data and loot_enabled:
                        dx = last_target_data["abs_x"] - my_x
                        dy = last_target_data["abs_y"] - my_y
                        
                        if abs(dx) <= 1 and abs(dy) <= 1 and last_target_data["z"] == my_z:

                            gv = get_game_view(pm, base_addr)
                            if gv:
                                click_x, click_y = get_screen_coord(gv, dx, dy, hwnd)
                                log(f"🔪 Abrindo corpo em ({dx}, {dy})...")

                                acquire_mouse()
                                try:
                                    time.sleep(random.uniform(0.8, 1.2))
                                    ctrl_right_click_at(hwnd, click_x, click_y)
                                finally:
                                    release_mouse()
                                time.sleep(0.8) 
                            else:
                                log("❌ Erro ao calcular GameView.")
                    
                    elif last_target_data and not loot_enabled:
                        log("ℹ️ Auto Loot desligado. Ignorando corpo.")

                    monitor.stop_and_report()
                    current_monitored_id = 0
                    last_target_data = None 
                    should_attack_new = True

            # Cenário C: Não estou atacando ninguém
            else:
                if debug_mode: print("Não estou atacando ninguém.")
                if current_monitored_id != 0:
                    monitor.stop_and_report()
                    current_monitored_id = 0
                    if debug_mode: print("--> Monitoramento finalizado.")
                should_attack_new = True

            # 4. AÇÃO FINAL
            if should_attack_new:
                final_candidates = valid_candidates

                if ignore_first:
                    if len(valid_candidates) >= 2:
                        final_candidates = [valid_candidates[1]]
                    else:
                        final_candidates = []
                
                if debug_mode: print("Decidido: Atacar novo alvo.")
                if len(final_candidates) > 0:

                    if next_attack_time == 0:
                        delay = random.uniform(min_delay, max_delay)
                        next_attack_time = time.time() + delay 
                        #waiting_for_attack = True
                        log(f"⏳ Aguardando {delay:.2f}s para atacar...")   

                    if time.time() >= next_attack_time:
                        best = final_candidates[0]
                        if debug_mode: print(f"-> Melhor Candidato: {best['name']} (ID: {best['id']})")            
                        if best["id"] != current_target_id:
                            log(f"⚔️ ATACANDO: {best['name']}")
                            packet.attack(pm, base_addr, best["id"])
                            
                            # --- CORREÇÃO: REGISTRO IMEDIATO (INSTANT KILL FIX) ---
                            current_target_id = best["id"]
                            current_monitored_id = best["id"] 
                            last_target_data = best.copy()
                            monitor.start(best["id"], best["name"], best["hp"]) 
                            # -----------------------------------------------------

                            next_attack_time = 0
                            #waiting_for_attack = False
                            time.sleep(0.5)
                        pass

            if debug_mode: print("---- FIM DA ITERAÇÃO ----")
            time.sleep(SCAN_DELAY)

        except Exception as e:
            print(f"[ERRO LOOP] {e}")
            time.sleep(1)