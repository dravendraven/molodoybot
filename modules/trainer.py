import time
import random
import win32gui

from core import packet
from core.packet_mutex import PacketMutex
from config import *
from core.map_core import get_player_pos
from core.memory_map import MemoryMap
from database import corpses

# CORREÇÃO: Importar scan_containers do local original (auto_loot.py)
from modules.auto_loot import scan_containers
from core.player_core import get_connected_char_name
from core.bot_state import state
from core.config_utils import make_config_getter

# Definições de Delay
SCAN_DELAY = 0.5

def get_my_char_name(pm, base_addr):
    """
    Retorna o nome do personagem usando BotState.
    Evita buscar na BattleList toda vez.
    """
    # Usa cache do BotState (thread-safe)
    if not state.char_name:
        name = get_connected_char_name(pm, base_addr)
        if name:
            state.char_name = name
    return state.char_name

def open_corpse_via_packet(pm, base_addr, target_data, player_id, log_func=print):
    """
    Localiza o corpo via memória e abre no próximo slot de container livre.
    """
    try:
        # 1. Validação do ID
        monster_name = target_data["name"]
        corpse_id = corpses.get_corpse_id(monster_name)
        if corpse_id == 0:
            log_func(f"⚠️ Corpo desconhecido para: {monster_name}")
            return False

        # 2. Leitura do Mapa
        mapper = MemoryMap(pm, base_addr)
        if not mapper.read_full_map(player_id):
            return False

        # 3. Posição Relativa
        my_x, my_y, my_z = get_player_pos(pm, base_addr)
        target_x = target_data["abs_x"]
        target_y = target_data["abs_y"]
        target_z = target_data["z"]

        dx = target_x - my_x
        dy = target_y - my_y

        tile = mapper.get_tile(dx, dy)
        if not tile:
            log_func(f"⚠️ Tile do corpo fora do alcance ({dx}, {dy}).")
            return False

        # 4. Encontra StackPos
        found_stack_pos = -1
        # Itera de trás para frente para pegar o topo da pilha
        for i in range(len(tile.items) - 1, -1, -1):
            item_id = tile.items[i]
            if item_id == corpse_id:
                found_stack_pos = i 
                break
        
        if found_stack_pos != -1:
            pos_dict = {'x': target_x, 'y': target_y, 'z': target_z}
            
            # 5. CÁLCULO INTELIGENTE DO INDEX
            # Lê containers atuais para saber onde abrir
            try:
                open_containers = scan_containers(pm, base_addr)
                num_open = len(open_containers)
            except Exception as e:
                log_func(f"⚠️ Erro ao escanear containers: {e}")
                num_open = 1 # Fallback seguro (vai abrir no idx 1 se scan falhar)
            
            # Define o índice alvo como o próximo slot disponível
            # Ex: Se tenho 2 containers (0 e 1), abro no 2.
            target_index = num_open
            
            # Limite de segurança do cliente
            if target_index > 15: target_index = 15 
            
            # Envia packet usando o índice calculado
            with PacketMutex("trainer"):
                packet.use_item(pm, pos_dict, corpse_id, found_stack_pos, index=target_index)
            return True
            
        else:
            log_func(f"⚠️ Corpo ID {corpse_id} não encontrado no chão.")
            return False

    except Exception as e:
        log_func(f"🔥 Erro OpenCorpse: {e}")
        return False

def trainer_loop(pm, base_addr, hwnd, monitor, check_running, config):

    get_cfg = make_config_getter(config)

    current_monitored_id = 0
    last_target_data = None 
    next_attack_time = 0       

    while True:
        if check_running and not check_running(): 
            return

        if not get_cfg('enabled', False): 
            time.sleep(1)
            continue
        
        if pm is None: 
            time.sleep(1)
            continue
            
        if hwnd == 0: 
            hwnd = win32gui.FindWindow("TibiaClient", None) or win32gui.FindWindow(None, "Tibia")
            
        if not get_cfg('is_safe', True): 
            time.sleep(0.5)
            continue 
        
        min_delay = get_cfg('min_delay', 1.0)
        max_delay = get_cfg('max_delay', 2.0)
        attack_range = get_cfg('range', 1)
        log = get_cfg('log_callback', print) 
        debug_mode = get_cfg('debug_mode', False)
        loot_enabled = get_cfg('loot_enabled', False)
        targets_list = get_cfg('targets', [])
        ignore_first = get_cfg('ignore_first', False)

        try:  
            player_id = pm.read_int(base_addr + OFFSET_PLAYER_ID)

            current_name = get_my_char_name(pm, base_addr)
            if not current_name: 
                time.sleep(0.5); continue
            
            target_addr = base_addr + TARGET_ID_PTR
            list_start = base_addr + TARGET_ID_PTR + REL_FIRST_ID
            my_x, my_y, my_z = get_player_pos(pm, base_addr)
            
            if my_z == 0: 
                time.sleep(0.2)
                continue

            # 2. SCAN
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
                print(f"--- FIM DO SCAN ---")

            current_target_id = pm.read_int(target_addr)
            should_attack_new = False

            # Cenário A: Já estou atacando
            if current_target_id != 0:
                target_data = next((c for c in valid_candidates if c["id"] == current_target_id), None)
                
                if target_data:
                    next_attack_time = 0       
                    last_target_data = target_data.copy()
                    if current_target_id != current_monitored_id:
                        monitor.start(current_target_id, target_data["name"], target_data["hp"])
                        current_monitored_id = current_target_id
                        if debug_mode: print(f"--> Iniciando monitoramento em {target_data['name']} (ID: {current_target_id})")
                    else:
                        monitor.update(target_data["hp"])
                else:
                    if debug_mode: print("-> Alvo inválido (morto/fora de alcance).")
                    pass

           # CENÁRIO B: Alvo Sumiu
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
                    log("💀 Alvo eliminado.")
                    
                    if last_target_data and loot_enabled:
                        time.sleep(1)
                        
                        # CHAMA FUNÇÃO COM LÓGICA DE INDEX DINÂMICO
                        success = open_corpse_via_packet(pm, base_addr, last_target_data, player_id, log_func=log)
                        
                        if success:
                            log(f"📂 Corpo aberto (Packet).")
                            time.sleep(0.5) 
                    
                    elif last_target_data and not loot_enabled:
                        if debug_mode: log("ℹ️ Auto Loot desligado.")

                    monitor.stop_and_report()
                    current_monitored_id = 0
                    last_target_data = None 
                    should_attack_new = True

            # Cenário C: Ninguém atacando
            else:
                if current_monitored_id != 0:
                    monitor.stop_and_report()
                    current_monitored_id = 0
                should_attack_new = True

            # 4. AÇÃO
            if should_attack_new:
                final_candidates = valid_candidates

                if ignore_first:
                    if len(valid_candidates) >= 2:
                        final_candidates = [valid_candidates[1]]
                    else:
                        final_candidates = []
                
                if len(final_candidates) > 0:
                    if next_attack_time == 0:
                        delay = random.uniform(min_delay, max_delay)
                        next_attack_time = time.time() + delay 
                        log(f"⏳ Aguardando {delay:.2f}s para atacar...")   

                    if time.time() >= next_attack_time:
                        best = final_candidates[0]
                        if best["id"] != current_target_id:
                            log(f"⚔️ ATACANDO: {best['name']}")
                            packet.attack(pm, base_addr, best["id"])
                            
                            current_target_id = best["id"]
                            current_monitored_id = best["id"] 
                            last_target_data = best.copy()
                            monitor.start(best["id"], best["name"], best["hp"]) 

                            next_attack_time = 0
                            time.sleep(0.5)

            time.sleep(SCAN_DELAY)

        except Exception as e:
            print(f"[ERRO LOOP] {e}")
            time.sleep(1)