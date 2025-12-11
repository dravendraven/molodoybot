import customtkinter as ctk 
import threading
import pymem
import pymem.process
import time
import win32gui 
import win32con
import win32api
import requests
import winsound
import os
import json
import random # Para o delay humano
from datetime import datetime
from PIL import Image # Import necessário para imagens
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import matplotlib
matplotlib.use("TkAgg") # Define o backend para funcionar com Tkinter
import sys
import traceback
import ctypes

# arquivos do bot
from monitor import *
from config import *
import config
from auto_loot import *
from stacker import auto_stack_items
from mouse_lock import acquire_mouse, release_mouse
from map_core import get_game_view, get_screen_coord, get_player_pos
from input_core import ctrl_right_click_at, alt_right_click_at
#from food_tracker import get_food_regen_time
from fisher import fishing_loop # Vamos usar essa função principal
import packet
from cavebot_core import *
import foods_db
import corpses

# ==============================================================================
# 1. SETUP DE AMBIENTE E SISTEMA
# ==============================================================================

# CORREÇÃO DE DPI (WINDOWS SCALING)
try:
    # Tenta definir Awareness para PER MONITOR (V2)
    ctypes.windll.shcore.SetProcessDpiAwareness(2) 
except Exception:
    try:
        # Fallback para Windows 8.1
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except: 
        # Fallback para Windows 7/8
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except: pass

# ==============================================================================
# 2. VARIÁVEIS GLOBAIS E CONFIGURAÇÃO
# ==============================================================================

toplevel_settings = None
CONFIG_FILE = "bot_config.json"
cavebot_manager = None


# Estado Global do Bot
BOT_SETTINGS = {
    # Geral
    "telegram_chat_id": TELEGRAM_CHAT_ID, # Do config.py
    "vocation": "Knight",
    "debug_mode": False,
    "ignore_first": False,
    
    # Listas
    "targets": list(TARGET_MONSTERS),
    "safe": list(SAFE_CREATURES),
    
    # Alarme
    "alarm_range": 8,
    "alarm_floor": "Padrão",
    
    # Loot
    "loot_containers": 2,
    "loot_dest": 0,
    
    # Fisher
    "fisher_min": 4,
    "fisher_max": 6,
    "fisher_check_cap": True,   # Ativa/Desativa checagem
    "fisher_min_cap": 6.0,     # Valor da Cap mínima
    
    # Runemaker
    "rune_mana": 100,
    "rune_hotkey": "F3",
    "rune_blank_id": 3147,
    "rune_hand": "RIGHT",
    "rune_work_pos": (0,0,0),
    "rune_safe_pos": (0,0,0),
    "rune_return_delay": 300,
    "rune_flee_delay": 2.0,
    "auto_eat": False,
    "mana_train": False,
    "rune_movement": True,
    "rune_human_min": 15,   # Segundos mínimos de espera
    "rune_human_max": 300  # Segundos máximos de espera
}

# Variáveis de Controle de Execução
is_attacking = False
is_looting = False
bot_running = True
pm = None 
base_addr = 0
is_safe_to_bot = True # True = Sem players por perto, pode atacar
is_connected = False # True apenas se: Processo Aberto + Logado no Char
is_gm_detected = False
is_graph_visible = False
gm_found = False
full_light_enabled = False # <--- NOVO
xray_window = None
hud_overlay_data = [] # Lista de dicionários para Fisher HUD
lbl_status = None 

# Variáveis de Regeneração e Timing
global_regen_seconds = 0
global_is_hungry = False
global_is_synced = False
global_is_full = False
SCAN_DELAY = 0.5  # Delay entre scans do trainer
HUMAN_DELAY_MIN = 1  # Segundos mínimos para "pensar"
HUMAN_DELAY_MAX = 2  # Segundos máximos para "pensar"

# --- CARREGAR CONFIGURAÇÕES (JSON) ---
if os.path.exists("bot_config.json"):
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            BOT_SETTINGS.update(data)
            
            # Correção específica para Tuplas (JSON salva como lista)
            if "rune_work_pos" in BOT_SETTINGS: 
                BOT_SETTINGS["rune_work_pos"] = tuple(BOT_SETTINGS["rune_work_pos"])
            if "rune_safe_pos" in BOT_SETTINGS: 
                BOT_SETTINGS["rune_safe_pos"] = tuple(BOT_SETTINGS["rune_safe_pos"])
                
        print("Configurações carregadas.")
    except Exception as e:
        print(f"Erro ao carregar: {e}")

# ==============================================================================
# 3. OBJETOS DE MONITORAMENTO (INSTANCIAS)
# ==============================================================================
monitor = TrainingMonitor(log_callback=lambda msg: log(msg)) # Lambda para resolver escopo se necessário, ou direto
# Nota: Definido como direto no original, ajustado abaixo para uso nas funções
sword_tracker = SkillTracker("Sword")
shield_tracker = SkillTracker("Shield")
magic_tracker = SkillTracker("Magic")
exp_tracker = ExpTracker()
gold_tracker = GoldTracker()
regen_tracker = RegenTracker()

# ==============================================================================
# 4. FUNÇÕES UTILITÁRIAS E HELPERS
# ==============================================================================

def log(msg):
    try:
        now = datetime.now().strftime("%H:%M:%S")
        final_msg = f"[{now}] {msg}\n"
        txt_log.insert("end", final_msg)
        txt_log.see("end")
    except: pass

def send_telegram(msg):
    if "TOKEN" in TELEGRAM_TOKEN: return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        data = {"chat_id": BOT_SETTINGS['telegram_chat_id'], "text": f"🚨 {msg}"}
        requests.post(url, data=data, timeout=2)
        print("[TELEGRAM] Mensagem enviada.")
    except: pass

def save_config_file():
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(BOT_SETTINGS, f, indent=4)
        print(f"[CONFIG] Salvo com sucesso.")
    except Exception as e:
        print(f"[CONFIG] Erro ao salvar: {e}")

def get_connected_char_name():
    """
    Lê o ID do jogador local e busca o nome correspondente na Battle List.
    """
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

def register_food_eaten(item_id):
    """
    Chamado pelos módulos (Runemaker/AutoLoot/MonitorManual) quando comem algo.
    """
    global global_regen_seconds, global_is_synced, global_is_hungry
    regen_time = foods_db.get_regen_time(item_id)
    
    if regen_time > 0:
        if global_is_synced:
            global_regen_seconds += regen_time
            if global_regen_seconds > MAX_FOOD_TIME:
                global_regen_seconds = MAX_FOOD_TIME
            global_is_hungry = False
        elif global_is_hungry:
            log(f"🍽️ Sincronizado por Fome! Início: {regen_time}s")
            global_is_synced = True
            global_regen_seconds = regen_time
            global_is_hungry = False
        else:
            log(f"🍖 Comeu durante 'Calc...' (Timer continua desconhecido)")
            pass

def attach_window():
    try:
        hwnd_tibia = win32gui.FindWindow("TibiaClient", None)
        if not hwnd_tibia: hwnd_tibia = win32gui.FindWindow(None, "Tibia")
        hwnd_bot = win32gui.GetParent(app.winfo_id())
        if hwnd_tibia and hwnd_bot:
            win32gui.SetWindowLong(hwnd_bot, -8, hwnd_tibia)
            app.attributes("-topmost", False)
    except: pass

def apply_full_light(enable):
    try:
        if not pm: return
        if enable:
            pm.write_bytes(base_addr + OFFSET_LIGHT_NOP, b'\x90\x90', 2)
            pm.write_uchar(base_addr + OFFSET_LIGHT_AMOUNT, 255)
        else:
            pm.write_bytes(base_addr + OFFSET_LIGHT_NOP, LIGHT_DEFAULT_BYTES, 2)
            pm.write_uchar(base_addr + OFFSET_LIGHT_AMOUNT, 128)
    except: pass

def update_fisher_hud(data_list):
    """
    Recebe uma lista de dados para desenhar no HUD.
    Formato esperado: [{'dx': int, 'dy': int, 'color': str, 'text': str|None}, ...]
    """
    global hud_overlay_data
    hud_overlay_data = data_list if data_list else []

# ==============================================================================
# 5. THREADS DE LÓGICA DO BOT (WORKERS)
# ==============================================================================

def connection_watchdog():
    global pm, base_addr, is_connected, bot_running
    was_connected_once = False
    while bot_running:
        try:
            # 1. Se não tem processo atrelado, tenta atrelar
            if pm is None:
                try:
                    pm = pymem.Pymem(PROCESS_NAME)
                    base_addr = pymem.process.module_from_name(pm.process_handle, PROCESS_NAME).lpBaseOfDll
                    log("✅ Processo do Tibia detectado.")
                except:
                    if was_connected_once:
                        print("Tibia fechou. Encerrando bot...")
                        os._exit(0) # Mata o bot
                    is_connected = False
                    lbl_connection.configure(text="Cliente Fechado ❌", text_color="#FF5555")
                    time.sleep(2)
                    continue

            # 2. Se o processo existe, verifica se está LOGADO
            try:
                status = pm.read_int(base_addr + OFFSET_CONNECTION)
                
                if status == 8: # 8 geralmente é "In Game"
                    if not is_connected:
                        log("🟢 Conectado ao mundo!")
                        if full_light_enabled:
                            time.sleep(1) 
                            apply_full_light(True)
                    is_connected = True
                    was_connected_once = True
                    lbl_connection.configure(text="Conectado 🟢", text_color="#00FF00")
                else:
                    is_connected = False
                    lbl_connection.configure(text="Desconectado ⚠️", text_color="#FFFF00")
                    
            except Exception:
                pm = None
                is_connected = False
                if was_connected_once:
                    os._exit(0)
                lbl_connection.configure(text="Cliente Fechado ❌", text_color="#FF5555")

        except Exception as e:
            print(f"Erro Watchdog: {e}")
        
        time.sleep(1)

def trainer_loop():
    hwnd = 0
    current_monitored_id = 0
    last_target_data = None 
    next_attack_time = 0       
    waiting_for_attack = False

    while bot_running:
        if not is_connected: time.sleep(1); continue
        if not switch_trainer.get(): time.sleep(1); continue
        if pm is None: time.sleep(1); continue
        if hwnd == 0: hwnd = win32gui.FindWindow("TibiaClient", None) or win32gui.FindWindow(None, "Tibia")
        if not is_safe_to_bot: time.sleep(0.5); continue 

        try:  
            current_name = get_connected_char_name()
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

            if BOT_SETTINGS['debug_mode']: print(f"\n--- INÍCIO DO SCAN (Meu Z: {my_z}) ---")
            
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
                        is_melee = (dist_x <= 1 and dist_y <= 1)
                
                        if BOT_SETTINGS['debug_mode']: print(f"Slot {i}: {name} (Vis:{vis} Z:{z} HP:{hp} Dist:({dist_x},{dist_y}))")

                        if name == current_name: continue

                        is_on_battle_list = (vis == 1 and z == my_z)

                        if is_on_battle_list:
                            if BOT_SETTINGS['debug_mode']: print(f"   [LINHA {visual_line_count}] -> {name} (ID: {c_id})")
                            current_line = visual_line_count
                            visual_line_count += 1 
                            
                            if any(t in name for t in BOT_SETTINGS['targets']):
                                if is_melee and hp > 0:
                                    if BOT_SETTINGS['debug_mode']: print(f"      -> CANDIDATO: HP:{hp} Dist:({dist_x},{dist_y})")
                                    valid_candidates.append({
                                        "id": c_id,
                                        "name": name,
                                        "hp": hp,
                                        "dist_x": dist_x,
                                        "dist_y": dist_y,
                                        "abs_x": cx,
                                        "abs_y": cy,
                                        "z": z,
                                        "is_melee": is_melee,
                                        "line": current_line
                                    })
                except: continue

            if BOT_SETTINGS['debug_mode']:
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
                if BOT_SETTINGS['debug_mode']: print(f"Atacando ID: {current_target_id}")
                target_data = next((c for c in valid_candidates if c["id"] == current_target_id), None)
                if BOT_SETTINGS['debug_mode']: print(f"-> Target Data: {target_data}")
                
                if target_data:
                    waiting_for_attack = False 
                    next_attack_time = 0       
                    last_target_data = target_data.copy()
                    if current_target_id != current_monitored_id:
                        monitor.start(current_target_id, target_data["name"], target_data["hp"])
                        current_monitored_id = current_target_id
                        if BOT_SETTINGS['debug_mode']: print(f"--> Iniciando monitoramento em {target_data['name']} (ID: {current_target_id})")
                    else:
                        monitor.update(target_data["hp"])
                        if BOT_SETTINGS['debug_mode']: print(f"--> Atualizando monitoramento em {target_data['name']} (HP: {target_data['hp']})")
                else:
                    if BOT_SETTINGS['debug_mode']: print("-> Alvo inválido (morto/fora de alcance).")
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
                    
                    if last_target_data and switch_loot.get():
                        dx = last_target_data["abs_x"] - my_x
                        dy = last_target_data["abs_y"] - my_y
                        
                        if abs(dx) <= 1 and abs(dy) <= 1 and last_target_data["z"] == my_z:

                            # # 1. Descobre o ID do corpo pelo Nome do monstro morto
                            # monster_name = last_target_data["name"]
                            # corpse_id = corpses.get_corpse_id(monster_name)
                            
                            # if corpse_id > 0:
                            #     log(f"🔪 Abrindo corpo de {monster_name} (Packet ID: {corpse_id})...")
                                
                            #     # 2. Prepara a Posição Absoluta (Mundo)
                            #     target_pos = {
                            #         'x': last_target_data["abs_x"], 
                            #         'y': last_target_data["abs_y"], 
                            #         'z': last_target_data["z"]
                            #     }
                                
                            #     # 3. Envia o Pacote Use Item (0x82)
                            #     # stack_pos=1: Assume que o corpo é o primeiro item acima do chão (Stack 0 = Ground)
                            #     time.sleep(1.5)
                            #     packet.use_item(pm, target_pos, corpse_id, stack_pos=1)                              
                            #     # Pequena pausa para o servidor processar e abrir o container
                            #     # time.sleep(0.5)
                            #     # packet.use_item(pm, target_pos, corpse_id, stack_pos=2)
                            #     time.sleep(0.8)
                                
                            # else:
                            #     log(f"⚠️ ID do corpo de '{monster_name}' não configurado em corpses.py!")

                            gv = get_game_view(pm, base_addr)
                            if gv:
                                click_x, click_y = get_screen_coord(gv, dx, dy, hwnd)
                                log(f"🔪 Abrindo corpo em ({dx}, {dy})...")

                                acquire_mouse()
                                try:
                                    time.sleep(1.5)
                                    ctrl_right_click_at(hwnd, click_x, click_y)
                                finally:
                                    release_mouse()
                                time.sleep(0.8) 
                            else:
                                log("❌ Erro ao calcular GameView.")
                    
                    elif last_target_data and not switch_loot.get():
                        log("ℹ️ Auto Loot desligado. Ignorando corpo.")

                    monitor.stop_and_report()
                    current_monitored_id = 0
                    last_target_data = None 
                    should_attack_new = True

            # Cenário C: Não estou atacando ninguém
            else:
                if BOT_SETTINGS['debug_mode']: print("Não estou atacando ninguém.")
                if current_monitored_id != 0:
                    monitor.stop_and_report()
                    current_monitored_id = 0
                    if BOT_SETTINGS['debug_mode']: print("--> Monitoramento finalizado.")
                should_attack_new = True

            # 4. AÇÃO FINAL
            if should_attack_new:
                final_candidates = valid_candidates

                if BOT_SETTINGS['ignore_first']:
                    if len(valid_candidates) >= 2:
                        final_candidates = [valid_candidates[1]]
                    else:
                        final_candidates = []
                
                if BOT_SETTINGS['debug_mode']: print("Decidido: Atacar novo alvo.")
                if len(final_candidates) > 0:

                    if next_attack_time == 0:
                        delay = random.uniform(HUMAN_DELAY_MIN, HUMAN_DELAY_MAX) 
                        next_attack_time = time.time() + delay 
                        waiting_for_attack = True
                        log(f"⏳ Aguardando {delay:.2f}s para atacar...")   

                    if time.time() >= next_attack_time:
                        best = final_candidates[0]
                        if BOT_SETTINGS['debug_mode']: print(f"-> Melhor Candidato: {best['name']} (ID: {best['id']})")            
                        if best["id"] != current_target_id:
                            log(f"⚔️ ATACANDO (Packet): {best['name']}")
                            packet.attack(pm, base_addr, best["id"])
                            
                            current_target_id = best["id"]
                            next_attack_time = 0
                            waiting_for_attack = False
                            time.sleep(0.5)
                    #         log(f"⚔️ ATACANDO: {best['name']} (Linha {best['line']})")
                        pass

            if BOT_SETTINGS['debug_mode']: print("---- FIM DA ITERAÇÃO ----")
            time.sleep(SCAN_DELAY)

        except Exception as e:
            print(f"[ERRO LOOP] {e}")
            time.sleep(1)

def alarm_loop():
    global is_safe_to_bot, is_gm_detected, gm_found
    last_alert = 0
    
    while bot_running:
        if not is_connected:
            time.sleep(1)
            continue

        if not switch_alarm.get():
            if not is_safe_to_bot:
                log("🔔 Alarme desativado manualmente. Retomando rotinas.")
                is_gm_detected = False 
                is_safe_to_bot = True
            time.sleep(1)
            continue
            
        if pm is None:
            time.sleep(1); continue
            
        try:
            current_name = get_connected_char_name()
            first = base_addr + TARGET_ID_PTR + REL_FIRST_ID
            my_x, my_y, my_z = get_player_pos(pm, base_addr)
        
            danger = False
            d_name = ""
            
            for i in range(MAX_CREATURES):
                slot = first + (i * STEP_SIZE)
                try:
                    if pm.read_int(slot) > 0:
                        vis = pm.read_int(slot + OFFSET_VISIBLE)
                        cz = pm.read_int(slot + OFFSET_Z)

                        is_z_valid = False
                        if BOT_SETTINGS['alarm_floor'] == "Padrão":
                            is_z_valid = (cz == my_z)
                        elif BOT_SETTINGS['alarm_floor'] == "Superior (+1)":
                            is_z_valid = (cz == my_z or cz == my_z - 1)
                        elif BOT_SETTINGS['alarm_floor'] == "Inferior (-1)":
                            is_z_valid = (cz == my_z or cz == my_z + 1)
                        elif BOT_SETTINGS['alarm_floor'] == "Todos (Raio-X)":
                            is_z_valid = (abs(cz - my_z) <= 1)
                        else: 
                            is_z_valid = (cz == my_z)

                        if vis != 0 and is_z_valid:
                            raw = pm.read_string(slot + OFFSET_NAME, 32)
                            name = raw.split('\x00')[0].strip()
                            if name == current_name: continue

                            if name.startswith("GM ") or name.startswith("CM ") or name.startswith("God "):
                                danger = True
                                gm_found = True
                                d_name = f"GAMEMASTER {name}"
                                break 
                            
                            is_safe = any(s in name for s in BOT_SETTINGS['safe'])
                            
                            if not is_safe:
                                cx = pm.read_int(slot + OFFSET_X)
                                cy = pm.read_int(slot + OFFSET_Y)
                                dist = max(abs(my_x - cx), abs(my_y - cy))
                                
                                if dist <= BOT_SETTINGS['alarm_range']:
                                    danger = True
                                    d_name = f"{name} ({dist} SQM)"
                                    break 
                except: continue
                
            if danger:
                is_safe_to_bot = False 
                is_gm_detected = gm_found
                log(f"⚠️ PERIGO: {d_name}!")
                if gm_found: 
                    winsound.Beep(2000, 1000) 
                else:
                    winsound.Beep(1000, 500)
                
                if (time.time() - last_alert) > 60:
                    send_telegram(f"PERIGO! {d_name} aproximou-se!")
                    last_alert = time.time()
            else: 
                is_safe_to_bot = True 
                is_gm_detected = False

            time.sleep(0.5)
        except Exception as e: 
            print(f"Erro Alarm: {e}")
            time.sleep(1)

def regen_monitor_loop():
    global pm, base_addr, bot_running, is_connected
    global global_regen_seconds, global_is_hungry, global_is_synced, global_is_full
    
    print("[REGEN] Monitor Iniciado (Modo Híbrido com Validação Dupla)")
    
    last_hp = -1
    last_mana = -1
    last_check_time = time.time()
    seconds_no_hp_up = 0
    seconds_no_mana_up = 0
    last_mem_id = 0
    
    while bot_running:
        if not is_connected or pm is None:
            time.sleep(1)
            continue
            
        try:
            # 1. DETECÇÃO MANUAL DE CLIQUE (Sincronia por ação do usuário)
            curr_mem_id = pm.read_int(base_addr + OFFSET_LAST_USED_ITEM_ID)
            
            if curr_mem_id != 0:
                if curr_mem_id != last_mem_id:
                    if curr_mem_id in FOOD_IDS:
                        time.sleep(0.4) 
                        if is_player_full(pm, base_addr):
                            print(f"[REGEN] Clique ignorado (FULL).")
                        else:
                            print(f"[REGEN] Sincronizado por clique! ID: {curr_mem_id}")
                            register_food_eaten(curr_mem_id)
                        
                        pm.write_int(base_addr + OFFSET_LAST_USED_ITEM_ID, 0)
                        last_mem_id = 0
                    else:
                        last_mem_id = curr_mem_id
            elif curr_mem_id == 0:
                last_mem_id = 0

            # 2. LEITURA DE DADOS E ANÁLISE DE TICKS
            curr_hp = pm.read_int(base_addr + OFFSET_PLAYER_HP)
            max_hp = pm.read_int(base_addr + OFFSET_PLAYER_HP_MAX)
            curr_mana = pm.read_int(base_addr + OFFSET_PLAYER_MANA)
            max_mana = pm.read_int(base_addr + OFFSET_PLAYER_MANA_MAX)
            
            hp_tick, mana_tick = VOCATION_REGEN.get(BOT_SETTINGS['vocation'], (6, 12))
            threshold_mana = mana_tick + 2 

            now = time.time()
            if now - last_check_time >= 1.0:
                is_hp_full = (curr_hp >= max_hp)
                is_mana_full = (curr_mana >= max_mana)
                is_totally_full = is_hp_full and is_mana_full
                
                if curr_mana > last_mana:
                    seconds_no_mana_up = 0 
                elif not is_mana_full:
                    seconds_no_mana_up += 1 
                
                hungry_by_logic = (not is_mana_full and seconds_no_mana_up >= threshold_mana)
                
                # 3. LÓGICA DE ESTADO
                status_text = "--:--"
                color = "gray"
                final_is_hungry = False

                if global_is_synced:
                    if global_regen_seconds > 0:
                        global_regen_seconds -= 1
                        mins = int(global_regen_seconds // 60)
                        secs = int(global_regen_seconds % 60)
                        status_text = f"🍖 {mins:02d}:{secs:02d}"
                        color = "#00FF00"
                        final_is_hungry = False
                    else:
                        if is_mana_full:
                            status_text = "🔵 Full (Sync)"
                            color = "#4EA5F9"
                            final_is_hungry = False
                        elif hungry_by_logic:
                            status_text = "🔴 FAMINTO"
                            color = "#FF5555"
                            final_is_hungry = True
                        else:
                            status_text = "🟡 Validando..."
                            color = "#E0E000"
                            final_is_hungry = False
                        
                else:
                    if hungry_by_logic:
                         status_text = "🔴 FAMINTO (Not synced)"
                         color = "#FF5555"
                         final_is_hungry = True 
                    elif is_totally_full:
                        status_text = "🔵 Full"
                        color = "#4EA5F9"
                        final_is_hungry = False
                    else:
                        status_text = "🟡 Calc..." 
                        color = "gray"
                        final_is_hungry = False
                
                global_is_hungry = final_is_hungry
                global_is_full = is_totally_full
                
                if lbl_regen and lbl_regen.winfo_exists():
                    lbl_regen.configure(text=status_text, text_color=color)

                last_hp = curr_hp
                last_mana = curr_mana
                last_check_time = now
            
            time.sleep(0.1)
            
        except Exception as e:
            print(f"Erro Regen Loop: {e}")
            time.sleep(1)

def auto_loot_thread():
    """Thread dedicada para verificar, coletar loot e organizar."""
    hwnd = 0
    while bot_running:
        if not is_connected:
            time.sleep(1)
            continue

        if not switch_loot.get():
            time.sleep(1)
            continue

        if not is_safe_to_bot:
            time.sleep(1)
            continue

        if pm is None:
            time.sleep(1)
            continue
            
        if hwnd == 0:
            hwnd = win32gui.FindWindow("TibiaClient", None) or win32gui.FindWindow(None, "Tibia")
        
        try:
            # 1. Tenta Lootear
            did_loot = run_auto_loot(pm, base_addr, hwnd, 
                                   my_containers_count=BOT_SETTINGS['loot_containers'],
                                   dest_container_index=BOT_SETTINGS['loot_dest'])
            
            if did_loot:
                if isinstance(did_loot, tuple) and did_loot[0] == "EAT":
                    item_id = did_loot[1]
                    food_name = foods_db.get_food_name(item_id)
                    log(f"🍖 {food_name} comido(a) do corpo.")
                    register_food_eaten(item_id) 

                if isinstance(did_loot, tuple) and did_loot[0] == "LOOT":
                    _, item_id, count = did_loot
                    gold_tracker.add_loot(item_id, count)
                    log(f"💰 Loot: {count}x ID {item_id}")

                elif did_loot == "FULL_BP_ALARM":
                    log("⚠️ BACKPACKS CHEIAS! Loot pausado.")
                    time.sleep(2) 
                
                elif did_loot == "EAT":
                    log("🍖 Comida consumida.")
                
                elif did_loot == "EAT_FULL":
                    pass 
                
                elif did_loot == "DROP":
                    log("🗑️ Lixo jogado fora.")
                
                elif did_loot == "BAG":
                    log("🎒 Bag extra aberta.")
                
                time.sleep(0.5)
                continue
            
            # 2. Se não tiver loot para pegar, tenta organizar (Stack)
            did_stack = auto_stack_items(pm, base_addr, hwnd,
                                       my_containers_count=BOT_SETTINGS['loot_containers'])
            
            if did_stack:
                log("Stackou.")
                time.sleep(0.5)
            else:
                time.sleep(1.0)
                
        except Exception as e:
            print(f"Erro Loot/Stack: {e}")
            time.sleep(1)

def auto_fisher_thread():
    hwnd = 0
    def should_fish():
        return bot_running and is_connected and switch_fisher.get() and is_safe_to_bot

    while bot_running:
        if not should_fish():
            time.sleep(1)
            continue
            
        if pm is None:
            time.sleep(1)
            continue
            
        if hwnd == 0:
            hwnd = win32gui.FindWindow("TibiaClient", None) or win32gui.FindWindow(None, "Tibia")

        try:
            current_range = (BOT_SETTINGS['fisher_min'], BOT_SETTINGS['fisher_max'])
            
            fishing_loop(pm, base_addr, hwnd, 
                         check_running=should_fish, 
                         log_callback=log,
                         debug_hud_callback=update_fisher_hud,
                         max_attempts_range=current_range) 
            
            time.sleep(1)
            
        except Exception as e:
            print(f"Erro Fisher Thread: {e}")
            time.sleep(5)

def runemaker_thread():
    hwnd = 0
    
    def should_run():
        return bot_running and is_connected and switch_runemaker.get()
    
    def check_safety():
        return is_safe_to_bot

    def check_gm():
        return is_gm_detected
    
    def check_hunger_state():
        if not global_is_synced and not global_is_hungry:
            return False
        if global_is_full:
            return False
        if global_is_hungry:
            return True
        if global_regen_seconds < EAT_THRESHOLD:
            return True
        return False
    
    def on_eat_callback(item_id):
        register_food_eaten(item_id)

    while bot_running:
        if not should_run():
            time.sleep(1); continue
        if pm is None: time.sleep(1); continue
        if hwnd == 0: hwnd = win32gui.FindWindow("TibiaClient", None) or win32gui.FindWindow(None, "Tibia")

        try:
            from runemaker import runemaker_loop
            
            cfg = {
                'mana_req': BOT_SETTINGS['rune_mana'],
                'hotkey': BOT_SETTINGS['rune_hotkey'],
                'blank_id': BOT_SETTINGS['rune_blank_id'],
                'hand_mode': BOT_SETTINGS['rune_hand'],
                'work_pos': BOT_SETTINGS['rune_work_pos'],
                'safe_pos': BOT_SETTINGS['rune_safe_pos'],
                'return_delay': BOT_SETTINGS['rune_return_delay'],
                'flee_delay': BOT_SETTINGS['rune_flee_delay'],
                'auto_eat': BOT_SETTINGS['auto_eat'], 
                'check_hunger': check_hunger_state, 
                'mana_train': BOT_SETTINGS['mana_train'],
                'enable_movement': BOT_SETTINGS.get('rune_movement', False),
                'human_min': BOT_SETTINGS.get('rune_human_min', 0),
                'human_max': BOT_SETTINGS.get('rune_human_max', 0),
            }
            
            runemaker_loop(pm, base_addr, hwnd, 
                           check_running=should_run, 
                           config=cfg,
                           is_safe_callback=check_safety,
                           is_gm_callback=check_gm,
                           log_callback=log,
                           eat_callback=on_eat_callback) 
            
            time.sleep(1)
        except Exception as e:
            print(f"Erro Runemaker: {e}")
            time.sleep(5)

def skill_monitor_loop():
    """
    Thread RÁPIDA: Apenas lê memória e atualiza a lógica matemática.
    """
    while bot_running:
        if pm is not None:
            try:
                sw_pct = pm.read_int(base_addr + OFFSET_SKILL_SWORD_PCT)
                sh_pct = pm.read_int(base_addr + OFFSET_SKILL_SHIELD_PCT)
                ml_pct = pm.read_int(base_addr + OFFSET_MAGIC_PCT)
                ml_lvl = pm.read_int(base_addr + OFFSET_MAGIC_LEVEL)
                
                sword_tracker.update(sw_pct)
                shield_tracker.update(sh_pct)
                magic_tracker.update(ml_pct)

            except:
                pass
        time.sleep(1)

def cavebot_thread():
    global cavebot_manager
    while bot_running:
        if not is_connected: 
            time.sleep(1); continue
        
        # Inicializa se necessário
        if cavebot_manager is None and pm is not None:
            cavebot_manager = CavebotManager(pm, base_addr)
        
        # Executa ciclo se manager existir
        if cavebot_manager:
            # Se estiver gravando, roda mesmo com switch desligado
            if cavebot_manager.is_recording:
                try:
                    cavebot_manager.run_cycle()
                except: pass
            
            # Se switch ligado, roda walker
            elif switch_cavebot.get():
                try:
                    cavebot_manager.run_cycle()
                except Exception as e:
                    print(f"Cavebot: {e}")
                    
        time.sleep(0.1) # 100ms para resposta rápida

# ==============================================================================
# 6. FUNÇÕES DA INTERFACE (CALLBACKS E JANELAS)
# ==============================================================================

def gui_updater_loop():
    while bot_running:
        if not is_connected:
            lbl_sword_val.configure(text="--")
            lbl_shield_val.configure(text="--")
            time.sleep(1)
            continue
    
        sw_data = sword_tracker.get_display_data()
        sh_data = shield_tracker.get_display_data()
        ml_stats = magic_tracker.get_display_data()
        
        
        if pm is not None:
            try:
                curr_exp = pm.read_int(base_addr + OFFSET_EXP)
                char_lvl = pm.read_int(base_addr + OFFSET_LEVEL)
                
                exp_tracker.update(curr_exp)
                xp_stats = exp_tracker.get_stats(char_lvl)
                
                if lbl_exp_rate.winfo_exists():
                    if xp_stats['xp_hour'] > 0:
                        lbl_exp_rate.configure(text=f"{xp_stats['xp_hour']} x/h")
                        lbl_exp_eta.configure(text=f"⏳{xp_stats['eta']}")
                    else:
                        lbl_exp_rate.configure(text="-- xp/h")
                        lbl_exp_eta.configure(text="--")

                if lbl_exp_left.winfo_exists():
                    lbl_exp_left.configure(text=f"{xp_stats['left']} xp")

                # --- 3. NOVA LÓGICA: ATUALIZAÇÃO DE GOLD ---
                # Scaneia os containers para ver quanto dinheiro temos na bolsa agora
                current_containers = scan_containers(pm, base_addr)
                
                # A. ATUALIZA GOLD
                if 'gold_tracker' in globals() and gold_tracker:
                    gold_tracker.update_inventory(current_containers)
                    g_stats = gold_tracker.get_stats()
                    
                    if 'lbl_gold_total' in globals() and lbl_gold_total.winfo_exists():
                        lbl_gold_total.configure(text=f"🪙 {g_stats['inventory']} gp")
                    
                    if 'lbl_gold_rate' in globals() and lbl_gold_rate.winfo_exists():
                        lbl_gold_rate.configure(text=f"{g_stats['gp_h']} gp/h")

                # B. ATUALIZA REGEN STOCK (NOVO)
                if 'regen_tracker' in globals() and regen_tracker:
                    regen_tracker.update_inventory(current_containers)
                    r_str = regen_tracker.get_display_string()
                    
                    if 'lbl_regen_stock' in globals() and lbl_regen_stock.winfo_exists():
                        lbl_regen_stock.configure(text=f"🍖 Stock: {r_str}")

            except Exception as e:
                print(f"Erro GUI: {e}")

        if pm is not None and sw_data['pct'] != -1:
            try:              

                sw_lvl = pm.read_int(base_addr + OFFSET_SKILL_SWORD)
                sh_lvl = pm.read_int(base_addr + OFFSET_SKILL_SHIELD)
                ml_pct = pm.read_int(base_addr + OFFSET_MAGIC_PCT)
                ml_lvl = pm.read_int(base_addr + OFFSET_MAGIC_LEVEL)

                lbl_sword_val.configure(text=f"{sw_data['pct']}%")
                lbl_shield_val.configure(text=f"{sh_data['pct']}%")
                lbl_magic_val.configure(text=f"{ml_lvl} ({ml_stats['pct']}%)")

                bench_sw = get_benchmark_min_per_pct(sw_lvl, BOT_SETTINGS['vocation'], "Melee")
                real_sw = sw_data['speed'] 
                
                if ml_stats['speed'] > 0:
                    lbl_magic_rate.configure(text=f"{ml_stats['speed']:.1f}m/%")
                    pct_left = 100 - ml_stats['pct']
                    mins_left = pct_left * ml_stats['speed']
                    horas, minutos = divmod(int(mins_left), 60)
                    lbl_magic_time.configure(text=f"ETA {horas:02d}:{minutos:02d}")
                else:
                    lbl_magic_rate.configure(text="-- m/%")
                    lbl_magic_time.configure(text="ETA --")

                if real_sw > 0:
                    efficiency = (bench_sw / real_sw) * 100
                    if efficiency > 100: efficiency = 100
                    
                    color_sw = "#00FF00" if efficiency >= 90 else "#FFFF00" if efficiency >= 70 else "#FF5555"
                    
                    lbl_sword_rate.configure(text=f"{real_sw:.1f} m/% ({efficiency:.0f}%)", text_color=color_sw)
                    
                    pct_left = 100 - sw_data['pct']
                    mins_left_sw = pct_left * real_sw
                    total_minutos = int(mins_left_sw)
                    horas, minutos = divmod(total_minutos, 60)
                    lbl_sword_time.configure(text=f"ETA {horas:02d}:{minutos:02d}")
                else:
                    lbl_sword_rate.configure(text="-- m/%", text_color="gray")
                    lbl_sword_time.configure(text="--")

                bench_sh = get_benchmark_min_per_pct(sh_lvl, BOT_SETTINGS['vocation'], "Shield")
                real_sh = sh_data['speed']
                
                if real_sh > 0:
                    efficiency = (bench_sh / real_sh) * 100
                    if efficiency > 100: efficiency = 100
                    
                    color_sh = "#00FF00" if efficiency >= 90 else "#FFFF00" if efficiency >= 70 else "#FF5555"
                    
                    lbl_shield_rate.configure(text=f"{real_sh:.1f} m/% ({efficiency:.0f}%)", text_color=color_sh)
                    
                    pct_left = 100 - sh_data['pct']
                    mins_left_sh = pct_left * real_sh
                    horas_sh, minutos_sh = divmod(int(mins_left_sh), 60)
                    lbl_shield_time.configure(text=f"ETA {horas_sh:02d}:{minutos_sh:02d}")
                else:
                    lbl_shield_rate.configure(text="-- m/%", text_color="gray")
                    lbl_shield_time.configure(text="--")

            except Exception as e:
                print(f"Erro GUI: {e}")

        # --- ATUALIZAÇÃO DO GRÁFICO (Se estiver visível) ---
        if is_graph_visible:
            try:
                ax.clear() 
                
                sw_hist_speed = sword_tracker.get_display_data()['history']
                sw_eff_hist = []
                
                if len(sw_hist_speed) > 1:
                    bench_sw = get_benchmark_min_per_pct(sw_lvl, BOT_SETTINGS['vocation'], "Melee")
                    for s in sw_hist_speed:
                        if s > 0:
                            eff = (bench_sw / s) * 100
                            if eff > 100: eff = 100 
                            sw_eff_hist.append(eff)
                        else:
                            sw_eff_hist.append(0)

                    ax.plot(sw_eff_hist, color='#4EA5F9', linewidth=2, marker='.', markersize=5, label='Sword')
                    ax.fill_between(range(len(sw_eff_hist)), sw_eff_hist, color='#4EA5F9', alpha=0.1)

                sh_hist_speed = shield_tracker.get_display_data()['history']
                sh_eff_hist = []
                if len(sh_hist_speed) > 1:
                    bench_sh = get_benchmark_min_per_pct(sh_lvl, BOT_SETTINGS['vocation'], "Shield")
                    for s in sh_hist_speed:
                        if s > 0:
                            eff = (bench_sh / s) * 100
                            if eff > 100: eff = 100
                            sh_eff_hist.append(eff)
                        else:
                            sh_eff_hist.append(0)
                    ax.plot(sh_eff_hist, color='#F9A54E', linewidth=2, marker='.', markersize=5, label='Shield')

                ax.axhline(y=100, color='#00FF00', linestyle='--', linewidth=1, alpha=0.5, label='Meta')
                
                ax.set_title("Eficiência de Treino (%)", fontsize=7, color="gray", pad=5)
                ax.set_ylim(0, 110) 
                
                ax.grid(color='#303030', linestyle='--', linewidth=0.5)
                ax.set_facecolor('#202020')
                ax.tick_params(colors='gray', labelsize=8)
                ax.spines['top'].set_visible(False)
                ax.spines['right'].set_visible(False)
                ax.spines['bottom'].set_color('#404040')
                ax.spines['left'].set_color('#404040')
                
                ax.legend(facecolor='#202020', edgecolor='#404040', labelcolor='gray', fontsize=5, loc='lower right')
                
                canvas.draw()
                
            except Exception as e:
                print(f"Erro Plot: {e}")

        for _ in range(5):
            if not bot_running: break
            time.sleep(1)

def update_stats_visibility():
    """
    Ajusta a interface baseada na vocação:
    - Mages: Esconde Sword, Shield e o Gráfico de Melee.
    - Knights: Mostra tudo.
    """
    voc = BOT_SETTINGS['vocation']
    is_mage = any(x in voc for x in ["Druid", "Sorcerer", "Mage", "None"])
    
    # Precisamos da variável global para saber se o gráfico estava aberto
    global is_graph_visible

    if is_mage:
        # 1. Esconde Stats de Melee
        box_sword.grid_remove()
        frame_sw_det.grid_remove()
        box_shield.grid_remove()
        frame_sh_det.grid_remove()
        
        # 2. Se o gráfico estiver aberto, fecha ele primeiro para resetar o tamanho da janela
        if is_graph_visible:
            toggle_graph() 
        
        # 3. Esconde o Container do Botão de Gráfico (Remove da tela)
        frame_graphs_container.pack_forget()

    else:
        # 1. Mostra Stats de Melee
        box_sword.grid(row=4, column=0, padx=10, sticky="w")
        frame_sw_det.grid(row=4, column=1, padx=10, sticky="e")
        box_shield.grid(row=5, column=0, padx=10, sticky="w")
        frame_sh_det.grid(row=5, column=1, padx=10, sticky="e")

        # 2. Mostra o Container do Gráfico novamente
        # Usamos 'after=frame_stats' para garantir que ele volte para o lugar certo (abaixo dos stats)
        # Se ele já estiver visível, o pack apenas atualiza, sem duplicar.
        frame_graphs_container.pack(padx=10, pady=(5, 0), fill="x", after=frame_stats)
    
    auto_resize_window()

def auto_resize_window():
    """
    Calcula o tamanho necessário para o conteúdo e ajusta a janela.
    Mantém a largura fixa em 320.
    """
    # 1. Força a interface a processar as mudanças pendentes (esconder/mostrar widgets)
    app.update_idletasks()
    
    # 2. Pega a altura requisitada pelo Frame Principal
    # Adicionamos um pequeno buffer (+10 ou +20) para a borda da janela não colar no log
    needed_height = main_frame.winfo_reqheight() + 10
    
    # 3. Aplica a nova geometria
    app.geometry(f"320x{needed_height}")

def open_settings():
    global toplevel_settings, lbl_status
    
    if toplevel_settings is not None and toplevel_settings.winfo_exists():
        toplevel_settings.lift()
        toplevel_settings.focus()
        return

    toplevel_settings = ctk.CTkToplevel(app)
    toplevel_settings.title("Configurações")
    toplevel_settings.geometry("360x500") 
    toplevel_settings.attributes("-topmost", True)
    
    def on_settings_close():
        global lbl_status
        toplevel_settings.destroy()
        
    toplevel_settings.protocol("WM_DELETE_WINDOW", on_settings_close)

    tabview = ctk.CTkTabview(toplevel_settings)
    tabview.pack(fill="both", expand=True, padx=10, pady=10)
    
    tab_geral  = tabview.add("Geral")
    tab_alarm  = tabview.add("Alarme")
    tab_alvos  = tabview.add("Alvos") 
    tab_loot   = tabview.add("Loot")
    tab_fisher = tabview.add("Fisher")
    tab_rune   = tabview.add("Rune")
    tab_cavebot = tabview.add("Cavebot")

    def create_grid_frame(parent):
        f = ctk.CTkFrame(parent, fg_color="transparent")
        f.pack(pady=10, fill="x")
        f.grid_columnconfigure(0, weight=1) 
        f.grid_columnconfigure(1, weight=2) 
        return f

    # 1. ABA GERAL
    frame_geral = create_grid_frame(tab_geral)
    
    ctk.CTkLabel(frame_geral, text="Vocação (Regen):", text_color="gray").grid(row=0, column=0, sticky="e", padx=10, pady=5)
    combo_voc = ctk.CTkComboBox(frame_geral, values=list(VOCATION_REGEN.keys()), width=150, state="readonly")
    combo_voc.grid(row=0, column=1, sticky="w")
    combo_voc.set(BOT_SETTINGS['vocation'])

    ctk.CTkLabel(frame_geral, text="Telegram Chat ID:", text_color="gray").grid(row=1, column=0, sticky="e", padx=10, pady=5)
    entry_telegram = ctk.CTkEntry(frame_geral, width=150)
    entry_telegram.grid(row=1, column=1, sticky="w")
    entry_telegram.insert(0, str(BOT_SETTINGS['telegram_chat_id']))
    
    ctk.CTkLabel(frame_geral, text="↳ Recebe alertas de PK e Pausa no celular.", 
                 font=("Verdana", 8), text_color="#666").grid(row=2, column=0, columnspan=2, sticky="e", padx=60, pady=(0, 5))

    frame_switches = ctk.CTkFrame(tab_geral, fg_color="transparent")
    frame_switches.pack(pady=10)
    
    def on_debug_toggle():
        BOT_SETTINGS['debug_mode'] = bool(switch_debug.get())
        log(f"🔧 Debug: {BOT_SETTINGS['debug_mode']}")
    
    switch_debug = ctk.CTkSwitch(frame_switches, text="Debug Console", command=on_debug_toggle, progress_color="#FFA500")
    switch_debug.pack(anchor="w", pady=5)
    if BOT_SETTINGS['debug_mode']: switch_debug.select()

    def on_ignore_toggle():
        BOT_SETTINGS['ignore_first'] = bool(switch_ignore.get())
        log(f"🛡️ Ignorar 1º: {BOT_SETTINGS['ignore_first']}")

    switch_ignore = ctk.CTkSwitch(frame_switches, text="Ignorar 1º Monstro", command=on_ignore_toggle, progress_color="#FFA500")
    switch_ignore.pack(anchor="w", pady=5)
    if BOT_SETTINGS['ignore_first']: switch_ignore.select()

    ctk.CTkLabel(frame_switches, text="   ↳ Ignora o primeiro alvo do battle ao atacar.", 
                 font=("Verdana", 8), text_color="#777", justify="left").pack(anchor="w", pady=(0, 10))
    
    def on_light_toggle():
        global full_light_enabled
        full_light_enabled = bool(switch_light.get())
        apply_full_light(full_light_enabled)
        log(f"💡 Full Light: {full_light_enabled}")

    switch_light = ctk.CTkSwitch(frame_switches, text="Full Light", command=on_light_toggle, progress_color="#FFA500")
    switch_light.pack(anchor="w", pady=5)
    if full_light_enabled: switch_light.select()

    def save_geral():
        BOT_SETTINGS['vocation'] = combo_voc.get()
        BOT_SETTINGS['telegram_chat_id'] = entry_telegram.get()
        update_stats_visibility()
        save_config_file()
        log(f"⚙️ Geral salvo.")

    ctk.CTkButton(tab_geral, text="Salvar Geral", command=save_geral, fg_color="#2CC985").pack(side="bottom", pady=10, fill="x", padx=20)

    # 2. ABA ALARME
    frame_alarm = create_grid_frame(tab_alarm)

    ctk.CTkLabel(frame_alarm, text="Distância (SQM):", text_color="gray").grid(row=0, column=0, sticky="e", padx=10, pady=5)
    dist_vals = ["1 SQM", "3 SQM", "5 SQM", "8 SQM (Padrão)", "Tela Toda"]
    combo_alarm = ctk.CTkComboBox(frame_alarm, values=dist_vals, width=150, state="readonly")
    combo_alarm.grid(row=0, column=1, sticky="w")
    
    curr_vis = "Tela Toda" if BOT_SETTINGS['alarm_range'] >= 15 else f"{BOT_SETTINGS['alarm_range']} SQM" if BOT_SETTINGS['alarm_range'] in [1,3,5] else "8 SQM (Padrão)"
    combo_alarm.set(curr_vis)

    ctk.CTkLabel(frame_alarm, text="↳ Raio de detecção ao redor do personagem.", 
                 font=("Verdana", 8), text_color="#777").grid(row=1, column=0, columnspan=2, sticky="w", padx=40, pady=(0, 5))

    ctk.CTkLabel(frame_alarm, text="Monitorar Andares:", text_color="gray").grid(row=2, column=0, sticky="e", padx=10, pady=5)
    combo_floor = ctk.CTkComboBox(frame_alarm, values=["Padrão", "Superior (+1)", "Inferior (-1)", "Todos (Raio-X)"], width=150, state="readonly")
    combo_floor.grid(row=2, column=1, sticky="w")
    combo_floor.set(BOT_SETTINGS['alarm_floor'])

    frame_note = ctk.CTkFrame(tab_alarm, fg_color="transparent")
    frame_note.pack(pady=10)
    ctk.CTkLabel(frame_note, text="ℹ️ Nota: Para ignorar amigos/criaturas,", 
                 font=("Verdana", 9), text_color="#BBB").pack()
    ctk.CTkLabel(frame_note, text="adicione os nomes na 'Safe List' (Aba Alvos).", 
                 font=("Verdana", 9, "bold"), text_color="#BBB").pack()
                 
    def save_alarm():
        raw_range = combo_alarm.get()
        BOT_SETTINGS['alarm_range'] = 15 if "Tela" in raw_range else int(raw_range.split()[0])
        BOT_SETTINGS['alarm_floor'] = combo_floor.get()
        save_config_file()
        log(f"🔔 Alarme salvo.")

    ctk.CTkButton(tab_alarm, text="Salvar Alarme", command=save_alarm, fg_color="#2CC985").pack(side="bottom", pady=10, fill="x", padx=20)

    # 3. ABA ALVOS
    ctk.CTkLabel(tab_alvos, text="Alvos (Target List):", font=("Verdana", 11, "bold")).pack(pady=(5,0))
    txt_targets = ctk.CTkTextbox(tab_alvos, height=100)
    txt_targets.pack(fill="x", padx=5, pady=5)
    txt_targets.insert("0.0", "\n".join(BOT_SETTINGS['targets']))

    ctk.CTkLabel(tab_alvos, text="Segura (Safe List):", font=("Verdana", 11, "bold")).pack(pady=(5,0))
    txt_safe = ctk.CTkTextbox(tab_alvos, height=140)
    txt_safe.pack(fill="x", padx=5, pady=5)
    txt_safe.insert("0.0", "\n".join(BOT_SETTINGS['safe']))

    def save_lists():
        BOT_SETTINGS['targets'][:] = [line.strip() for line in txt_targets.get("0.0", "end").split('\n') if line.strip()]
        BOT_SETTINGS['safe'][:] = [line.strip() for line in txt_safe.get("0.0", "end").split('\n') if line.strip()]
        save_config_file()
        log(f"🎯 Listas salvas.")

    ctk.CTkButton(tab_alvos, text="Salvar Listas", command=save_lists, fg_color="#2CC985").pack(side="bottom", pady=10, fill="x", padx=20)

    # 4. ABA LOOT
    ctk.CTkLabel(tab_loot, text="Quantas BPs são suas?", text_color="gray", font=("Verdana", 10)).pack()
    entry_cont_count = ctk.CTkEntry(tab_loot, width=50)
    entry_cont_count.pack(pady=5)
    entry_cont_count.insert(0, str(BOT_SETTINGS['loot_containers'])) 
    
    ctk.CTkLabel(tab_loot, text="(O resto será considerado Corpo)", font=("Verdana", 9), text_color="#555555").pack(pady=(0, 10))

    ctk.CTkLabel(tab_loot, text="Índice da BP de Destino:", text_color="gray", font=("Verdana", 10)).pack()
    entry_dest_idx = ctk.CTkEntry(tab_loot, width=50)
    entry_dest_idx.pack(pady=5)
    entry_dest_idx.insert(0, str(BOT_SETTINGS['loot_dest'])) 
    
    ctk.CTkLabel(tab_loot, text="(0 = Primeira BP, 1 = Segunda...)", font=("Verdana", 9), text_color="#555555").pack(pady=(0, 20))

    def save_loot():
        try:
            BOT_SETTINGS['loot_containers'] = int(entry_cont_count.get())
            BOT_SETTINGS['loot_dest'] = int(entry_dest_idx.get())
            save_config_file()
            log(f"💰 Loot salvo: {BOT_SETTINGS['loot_containers']} BPs | Dest: {BOT_SETTINGS['loot_dest']}")
        except: log("❌ Use números inteiros.")

    ctk.CTkButton(tab_loot, text="Salvar Loot", command=save_loot, fg_color="#2CC985").pack(side="bottom", pady=10, fill="x", padx=20)

    # 5. ABA FISHER
    frame_fish = create_grid_frame(tab_fisher)

    ctk.CTkLabel(frame_fish, text="Min Tentativas:", text_color="gray").grid(row=0, column=0, sticky="e", padx=10, pady=5)
    entry_fish_min = ctk.CTkEntry(frame_fish, width=50, justify="center")
    entry_fish_min.grid(row=0, column=1, sticky="w")
    entry_fish_min.insert(0, str(BOT_SETTINGS['fisher_min']))

    ctk.CTkLabel(frame_fish, text="Max Tentativas:", text_color="gray").grid(row=1, column=0, sticky="e", padx=10, pady=5)
    entry_fish_max = ctk.CTkEntry(frame_fish, width=50, justify="center")
    entry_fish_max.grid(row=1, column=1, sticky="w")
    entry_fish_max.insert(0, str(BOT_SETTINGS['fisher_max']))

    lbl_hint_fish = ctk.CTkLabel(frame_fish, text="↳ O bot escolherá um número aleatório entre Min e Max\n para pescar em cada quadrado.", 
                                 font=("Verdana", 8), text_color="#777", justify="left")
    lbl_hint_fish.grid(row=2, column=0, columnspan=2, sticky="w", padx=(20,0), pady=(0,5))

    # --- NOVO: Configurações de CAP (Save Cap) ---
    ctk.CTkLabel(frame_fish, text="Min Cap (oz):", text_color="gray").grid(row=3, column=0, sticky="e", padx=10, pady=5)
    entry_fish_cap_val = ctk.CTkEntry(frame_fish, width=50, justify="center")
    entry_fish_cap_val.grid(row=3, column=1, sticky="w")
    # Usa .get() para evitar erro se a chave não existir em configs antigas
    entry_fish_cap_val.insert(0, str(BOT_SETTINGS.get('fisher_min_cap', 10.0)))

    # Frame auxiliar para o Switch ficar alinhado
    frame_fish_opts = ctk.CTkFrame(tab_fisher, fg_color="transparent")
    frame_fish_opts.pack(pady=10)

    def toggle_fish_cap():
        # Apenas visual ou log, o valor real é salvo no botão "Salvar Fisher"
        pass

    switch_fish_cap = ctk.CTkSwitch(frame_fish_opts, text="Pausar se Cap Baixa", command=toggle_fish_cap, 
                                    progress_color="#FFA500", font=("Verdana", 10))
    switch_fish_cap.grid(row=4, column=0, columnspan=2, sticky="w", padx=(20,0), pady=(0,5))
    switch_fish_cap.pack()
    
    # Carrega o estado atual
    if BOT_SETTINGS.get('fisher_check_cap', True):
        switch_fish_cap.select()
    else:
        switch_fish_cap.deselect()

    # Dica Visual
    # lbl_hint_fish = ctk.CTkLabel(tab_fisher, text="↳ Se ativado, o bot para de pescar quando\na Cap estiver abaixo do limite configurado.", 
    #                              font=("Verdana", 8), text_color="#777")
    # lbl_hint_fish.grid(row=5, column=0, columnspan=2, sticky="w", padx=(20,0), pady=(0,5))

    def save_fish():
        try:
            mn = int(entry_fish_min.get())
            mx = int(entry_fish_max.get())
            cap_val = float(entry_fish_cap_val.get().replace(',', '.')) # Aceita virgula ou ponto
            check_cap = bool(switch_fish_cap.get())
            if mn < 1: mn=1
            if mx < mn: mx=mn
            BOT_SETTINGS['fisher_min'] = mn
            BOT_SETTINGS['fisher_max'] = mx
            BOT_SETTINGS['fisher_min_cap'] = cap_val
            BOT_SETTINGS['fisher_check_cap'] = check_cap
            save_config_file()
            config.CHECK_MIN_CAP = check_cap
            config.MIN_CAP_VALUE = cap_val
            log(f"🎣 Fisher salvo: {mn} a {mx}")
        except: log("❌ Use números inteiros.")

    ctk.CTkButton(tab_fisher, text="Salvar Fisher", command=save_fish, fg_color="#2CC985").pack(side="bottom", pady=10, fill="x", padx=20)

    # ==============================================================================
    # 6. ABA RUNE (LAYOUT ULTRA-COMPACTO)
    # ==============================================================================
    
    # Helper para atualizar labels de posição (definido aqui para ter acesso aos widgets)
    def update_rune_pos_labels():
        lbl_work_pos.configure(text=str(BOT_SETTINGS.get('rune_work_pos', (0,0,0))))
        lbl_safe_pos.configure(text=str(BOT_SETTINGS.get('rune_safe_pos', (0,0,0))))

    def set_rune_pos(type_pos):
        # Pega posição atual do player e salva
        if pm:
            try:
                x = pm.read_int(base_addr + 0x1D16F0) # OFFSET_PLAYER_X
                y = pm.read_int(base_addr + 0x1D16EC) # OFFSET_PLAYER_Y
                z = pm.read_int(base_addr + 0x1D16E8) # OFFSET_PLAYER_Z
                
                key = 'rune_work_pos' if type_pos == "WORK" else 'rune_safe_pos'
                BOT_SETTINGS[key] = (x, y, z)
                update_rune_pos_labels()
                log(f"📍 {type_pos} definido: {x}, {y}, {z}")
            except:
                log("❌ Erro ao ler posição. Logue no char.")

    # --- SEÇÃO 1: CRAFT (Tudo em 2 linhas) ---
    frame_craft = ctk.CTkFrame(tab_rune, fg_color="#2b2b2b")
    frame_craft.pack(fill="x", padx=5, pady=2)
    
    ctk.CTkLabel(frame_craft, text="⚙️ Crafting", font=("Verdana", 11, "bold"), height=18).pack(anchor="w", padx=5, pady=(10,10))
    
    f_c1 = ctk.CTkFrame(frame_craft, fg_color="transparent")
    f_c1.pack(fill="x", padx=2, pady=2)
    
    # Linha compacta: Mana | Hotkey | Mão
    ctk.CTkLabel(f_c1, text="Mana:", font=("Verdana", 10)).pack(side="left", padx=5)
    entry_mana = ctk.CTkEntry(f_c1, width=45, height=22, font=("Verdana", 10), justify="center")
    entry_mana.pack(side="left", padx=5)
    entry_mana.insert(0, str(BOT_SETTINGS['rune_mana']))
    
    ctk.CTkLabel(f_c1, text="Key:", font=("Verdana", 10)).pack(side="left", padx=5)
    entry_hk = ctk.CTkEntry(f_c1, width=35, height=22, font=("Verdana", 10), justify="center")
    entry_hk.pack(side="left", padx=5)
    entry_hk.insert(0, BOT_SETTINGS['rune_hotkey'])
    
    ctk.CTkLabel(f_c1, text="Hand:", font=("Verdana", 10)).pack(side="left", padx=5)
    combo_hand = ctk.CTkComboBox(f_c1, values=["RIGHT", "LEFT", "BOTH"], width=65, height=22, font=("Verdana", 10), state="readonly")
    combo_hand.pack(side="left", padx=5)
    combo_hand.set(BOT_SETTINGS['rune_hand'])

    # --- SEÇÃO 2: HUMANIZAÇÃO ---
    frame_human = ctk.CTkFrame(tab_rune, fg_color="#2b2b2b")
    frame_human.pack(fill="x", padx=5, pady=2)
    
    f_h1 = ctk.CTkFrame(frame_human, fg_color="transparent")
    f_h1.pack(fill="x", padx=2, pady=2)
    
    ctk.CTkLabel(f_h1, text="Ao atingir mana, esperar de", font=("Verdana", 9)).pack(side="left", padx=5)
    
    entry_human_min = ctk.CTkEntry(f_h1, width=35, height=22, font=("Verdana", 10), justify="center")
    entry_human_min.pack(side="left", padx=2)
    entry_human_min.insert(0, str(BOT_SETTINGS.get('rune_human_min', 5)))
    
    ctk.CTkLabel(f_h1, text="até", font=("Verdana", 9)).pack(side="left", padx=5)
    
    entry_human_max = ctk.CTkEntry(f_h1, width=35, height=22, font=("Verdana", 10), justify="center")
    entry_human_max.pack(side="left", padx=2)
    entry_human_max.insert(0, str(BOT_SETTINGS.get('rune_human_max', 30)))

    ctk.CTkLabel(f_h1, text="segundos", font=("Verdana", 9)).pack(side="left", padx=2)

    # --- SEÇÃO 3: SEGURANÇA & MOVIMENTO ---
    frame_move = ctk.CTkFrame(tab_rune, fg_color="#2b2b2b")
    frame_move.pack(fill="x", padx=5, pady=10)
    
    ctk.CTkLabel(frame_move, text="🚨 Anti-PK / Movimento", font=("Verdana", 11, "bold"), height=18).pack(anchor="w", padx=5, pady=(10,10))

    # Toggle Flee + Delays
    f_m1 = ctk.CTkFrame(frame_move, fg_color="transparent")
    f_m1.pack(fill="x", padx=2, pady=5)
    
    switch_movement = ctk.CTkSwitch(f_m1, text="Fugir para safe (alarme)", font=("Verdana", 10), width=50, height=20)
    switch_movement.pack(side="left", padx=2)
    if BOT_SETTINGS.get('rune_movement', False): switch_movement.select()

    f_m2 = ctk.CTkFrame(frame_move, fg_color="transparent")
    f_m2.pack(fill="x", padx=2, pady=2)
    
    ctk.CTkLabel(f_m2, text="Reação(s):", font=("Verdana", 10)).pack(side="left", padx=(2,2))
    entry_flee = ctk.CTkEntry(f_m2, width=35, height=22, font=("Verdana", 10), justify="center")
    entry_flee.pack(side="left")
    entry_flee.insert(0, str(BOT_SETTINGS.get('rune_flee_delay', 0.5)))

    ctk.CTkLabel(f_m2, text="Retorno(s):", font=("Verdana", 10)).pack(side="left", padx=(10,2))
    entry_ret_delay = ctk.CTkEntry(f_m2, width=35, height=22, font=("Verdana", 10), justify="center")
    entry_ret_delay.pack(side="left")
    entry_ret_delay.insert(0, str(BOT_SETTINGS.get('rune_return_delay', 300)))

    # Coordenadas (Linhas finas)
    f_coords = ctk.CTkFrame(frame_move, fg_color="transparent")
    f_coords.pack(fill="x", padx=2, pady=2)
    
    # Work
    f_wk = ctk.CTkFrame(f_coords, fg_color="transparent", height=25)
    f_wk.pack(fill="x")
    ctk.CTkButton(f_wk, text="Set Work", width=60, height=20, font=("Verdana", 9), fg_color="#444", 
                  command=lambda: set_rune_pos("WORK")).pack(side="left", padx=2)
    lbl_work_pos = ctk.CTkLabel(f_wk, text=str(BOT_SETTINGS.get('rune_work_pos', (0,0,0))), font=("Verdana", 10), text_color="gray")
    lbl_work_pos.pack(side="left", padx=5)

    # Safe
    f_sf = ctk.CTkFrame(f_coords, fg_color="transparent", height=25)
    f_sf.pack(fill="x")
    ctk.CTkButton(f_sf, text="Set Safe", width=60, height=20, font=("Verdana", 9), fg_color="#444", 
                  command=lambda: set_rune_pos("SAFE")).pack(side="left", padx=2)
    lbl_safe_pos = ctk.CTkLabel(f_sf, text=str(BOT_SETTINGS.get('rune_safe_pos', (0,0,0))), font=("Verdana", 10), text_color="gray")
    lbl_safe_pos.pack(side="left", padx=5)

    # --- SEÇÃO 4: EXTRAS ---
    frame_extras = ctk.CTkFrame(tab_rune, fg_color="#2b2b2b")
    frame_extras.pack(fill="x", padx=5, pady=2)

    ctk.CTkLabel(frame_extras, text="Outros", font=("Verdana", 11, "bold"), height=18).pack(anchor="w", padx=5, pady=(10,10))
    
    f_ex = ctk.CTkFrame(frame_extras, fg_color="transparent")
    f_ex.pack(fill="x", padx=2, pady=5)
    
    switch_eat = ctk.CTkSwitch(f_ex, text="Auto Eat", font=("Verdana", 10), width=60, height=20)
    switch_eat.pack(side="left", padx=10)
    if BOT_SETTINGS['auto_eat']: switch_eat.select()

    switch_train = ctk.CTkSwitch(f_ex, text="Mana Train (No rune)", font=("Verdana", 10), width=60, height=20)
    switch_train.pack(side="left", padx=20)
    if BOT_SETTINGS['mana_train']: switch_train.select()

    # --- SAVE ---
    def save_rune():
        try:
            BOT_SETTINGS['rune_mana'] = int(entry_mana.get())
            BOT_SETTINGS['rune_hotkey'] = entry_hk.get().upper()
            BOT_SETTINGS['rune_hand'] = combo_hand.get()
            BOT_SETTINGS['rune_blank_id'] = 3147
            
            BOT_SETTINGS['rune_human_min'] = int(entry_human_min.get())
            BOT_SETTINGS['rune_human_max'] = int(entry_human_max.get())
            
            BOT_SETTINGS['rune_flee_delay'] = float(entry_flee.get())
            BOT_SETTINGS['rune_return_delay'] = int(entry_ret_delay.get())
            BOT_SETTINGS['rune_movement'] = bool(switch_movement.get())
            BOT_SETTINGS['auto_eat'] = bool(switch_eat.get())
            BOT_SETTINGS['mana_train'] = bool(switch_train.get())
            
            save_config_file()
            log("🔮 Rune Config salva!")
        except:
            log("❌ Erro ao salvar Rune.")

    ctk.CTkButton(tab_rune, text="Salvar Rune", command=save_rune, height=32, fg_color="#00A86B", hover_color="#008f5b").pack(side="bottom", fill="x", padx=20, pady=5)
    
    # ==========================================================================
    # 7. ABA CAVEBOT (INTERFACE COMPLETA)
    # ==========================================================================
    
    # --- 1. CONTROLES DE GRAVAÇÃO ---
    frame_cv_actions = ctk.CTkFrame(tab_cavebot, fg_color="transparent")
    frame_cv_actions.pack(fill="x", pady=(5, 0), padx=5)

    def refresh_waypoints_visual():
        if not cavebot_manager: return
        txt_waypoints.configure(state="normal")
        txt_waypoints.delete("0.0", "end")
        for i, wp in enumerate(cavebot_manager.waypoints):
            # Mostra o tipo e a coordenada
            line = f"{i:03d}: [{wp['type']}] {wp['x']}, {wp['y']}, {wp['z']}\n"
            txt_waypoints.insert("end", line)
        txt_waypoints.configure(state="disabled")
        txt_waypoints.see("end")

    def toggle_rec():
        if not cavebot_manager: return
        if cavebot_manager.is_recording:
            cavebot_manager.stop_recording()
            btn_rec.configure(text="● REC", fg_color="#303030", border_color="gray", border_width=1)
            refresh_waypoints_visual()
        else:
            cavebot_manager.start_recording()
            btn_rec.configure(text="■ STOP", fg_color="#FF5555", text_color="white", border_width=0)

    def clear_wp():
        if cavebot_manager:
            cavebot_manager.clear()
            refresh_waypoints_visual()
            
    # Botões Principais (REC / LIMPAR)
    btn_rec = ctk.CTkButton(frame_cv_actions, text="● REC", command=toggle_rec, 
                            width=60, fg_color="#303030", border_color="gray", border_width=1)
    btn_rec.pack(side="left", padx=2)

    ctk.CTkButton(frame_cv_actions, text="Limpar", command=clear_wp, 
                  width=50, fg_color="#404040").pack(side="right", padx=2)

    # --- 2. BOTÕES DE TIPOS ESPECIAIS (NOVO) ---
    frame_cv_types = ctk.CTkFrame(tab_cavebot, fg_color="transparent")
    frame_cv_types.pack(fill="x", pady=2, padx=5)

    def add_special_wp(wp_type):
        if not pm or not cavebot_manager: return
        x, y, z = get_player_pos(pm, base_addr)
        if x == 0: return
        
        # Adiciona o ponto na posição atual do jogador
        cavebot_manager.add_waypoint(wp_type, x, y, z)
        refresh_waypoints_visual()
        
        # Feedback visual rápido (pisca o botão ou log)
        log(f"➕ {wp_type} adicionado em {x},{y},{z}")

    # Botões pequenos para inserir ações manuais
    ctk.CTkButton(frame_cv_types, text="+ Node", width=60, height=20, fg_color="#404040", 
                  command=lambda: add_special_wp("NODE")).pack(side="left", padx=2)
                  
    ctk.CTkButton(frame_cv_types, text="+ Rope", width=60, height=20, fg_color="#A54EF9", 
                  command=lambda: add_special_wp("ROPE")).pack(side="left", padx=2)
                  
    ctk.CTkButton(frame_cv_types, text="+ Ladder", width=60, height=20, fg_color="#E0E000", text_color="black",
                  command=lambda: add_special_wp("LADDER")).pack(side="left", padx=2)

    # --- 3. LISTA VISUAL ---
    frame_list = ctk.CTkFrame(tab_cavebot)
    frame_list.pack(fill="both", expand=True, padx=5, pady=5)
    
    txt_waypoints = ctk.CTkTextbox(frame_list, font=("Consolas", 10), activate_scrollbars=True)
    txt_waypoints.pack(fill="both", expand=True)
    txt_waypoints.configure(state="disabled")

    # --- 4. GERENCIADOR DE ARQUIVOS ---
    ctk.CTkLabel(tab_cavebot, text="Salvar/Carregar", font=("Verdana", 9, "bold")).pack(pady=(5, 0))

    frame_cv_file = ctk.CTkFrame(tab_cavebot, fg_color="transparent")
    frame_cv_file.pack(fill="x", padx=5)

    entry_filename = ctk.CTkEntry(frame_cv_file, placeholder_text="nome_script", height=25)
    entry_filename.pack(side="left", fill="x", expand=True, padx=(0, 5))

    # Funções de Arquivo
    def refresh_script_list_ui():
        # Limpa lista visual de arquivos
        for widget in scroll_scripts.winfo_children():
            widget.destroy()
        
        # Cria pasta se não existir
        directory = "cavebot_scripts"
        if not os.path.exists(directory): os.makedirs(directory)
        
        files = [f for f in os.listdir(directory) if f.endswith(".json")]
        
        if not files:
            ctk.CTkLabel(scroll_scripts, text="Nenhum script salvo.", text_color="gray").pack(pady=5)
            return

        for f in files:
            display_name = f.replace(".json", "")
            # Botão para selecionar o script
            btn = ctk.CTkButton(scroll_scripts, text=f"📄 {display_name}", 
                                fg_color="#303030", hover_color="#404040",
                                height=25, anchor="w",
                                command=lambda name=display_name: select_script(name))
            btn.pack(fill="x", pady=1, padx=2)

    def select_script(name):
        entry_filename.delete(0, "end")
        entry_filename.insert(0, name)

    def save_cv():
        if not cavebot_manager: return
        fname = entry_filename.get().strip()
        if not fname: 
            log("⚠️ Digite um nome para salvar.")
            return
            
        if cavebot_manager.save_waypoints(fname):
            log(f"💾 Script '{fname}' salvo!")
            refresh_script_list_ui()

    def load_cv():
        if not cavebot_manager: return
        fname = entry_filename.get().strip()
        if not fname: return
        
        if cavebot_manager.load_waypoints(fname):
            refresh_waypoints_visual() # <--- Função que estava faltando, agora existe!
            log(f"📂 Carregado: {fname}")

    def delete_cv():
        fname = entry_filename.get().strip()
        if not fname: return
        path = os.path.join("cavebot_scripts", fname + ".json")
        try:
            if os.path.exists(path):
                os.remove(path)
                log(f"🗑️ Script '{fname}' deletado.")
                entry_filename.delete(0, "end")
                refresh_script_list_ui()
        except: pass

    # Botões Save/Load
    ctk.CTkButton(frame_cv_file, text="Salvar", command=save_cv, width=60, fg_color="#2CC985").pack(side="right", padx=2)
    ctk.CTkButton(frame_cv_file, text="Carregar", command=load_cv, width=60, fg_color="#4EA5F9").pack(side="right", padx=2)

    # --- 4. LISTA DE ARQUIVOS SALVOS ---
    ctk.CTkLabel(tab_cavebot, text="Scripts Disponíveis:", text_color="gray", font=("Verdana", 9)).pack(anchor="w", padx=5, pady=(5,0))
    
    scroll_scripts = ctk.CTkScrollableFrame(tab_cavebot, height=100, fg_color="#1A1A1A")
    scroll_scripts.pack(fill="x", padx=5, pady=5)

    # Botão Delete
    ctk.CTkButton(tab_cavebot, text="Apagar Selecionado", command=delete_cv, 
                  fg_color="#FF5555", hover_color="#990000", height=20, font=("Verdana", 9)).pack(pady=2)

    # Inicializa a lista de arquivos ao abrir a aba
    refresh_script_list_ui()

def toggle_graph():
    global is_graph_visible
    if is_graph_visible:
        frame_graph.pack_forget() 
        # frame_graphs_container.pack_forget() # Se você escondeu o container todo no passo anterior
        btn_graph.configure(text="Mostrar Gráfico 📈")
        is_graph_visible = False
    else:
        frame_graph.pack(side="top", fill="both", expand=True, pady=(0, 5))
        # frame_graphs_container.pack(...) # Se necessário restaurar o container
        btn_graph.configure(text="Esconder Gráfico 📉")
        is_graph_visible = True
        
    # >>> MÁGICA AQUI: Recalcula o tamanho automaticamente <<<
    auto_resize_window()

def toggle_xray():
    global xray_window
    
    if xray_window is not None:
        xray_window.destroy()
        xray_window = None
        btn_xray.configure(fg_color="#303030") 
        return

    btn_xray.configure(fg_color="#2CC985") 
    
    xray_window = ctk.CTkToplevel(app)
    xray_window.overrideredirect(True) 
    xray_window.attributes("-topmost", True)
    xray_window.attributes("-transparentcolor", "black") 
    xray_window.config(bg="black")
    
    def update_xray():
        if not xray_window or not xray_window.winfo_exists(): return
        
        try:
            hwnd = win32gui.FindWindow("TibiaClient", None) or win32gui.FindWindow(None, "Tibia")
            
            active_hwnd = win32gui.GetForegroundWindow()
            if hwnd and active_hwnd != hwnd:
                canvas.delete("all")
                xray_window.after(100, update_xray)
                return
            
            if hwnd:
                rect = win32gui.GetWindowRect(hwnd) 
                win_x, win_y = rect[0], rect[1]
                
                client_point = win32gui.ClientToScreen(hwnd, (0, 0))
                client_x, client_y = client_point

                offset_x = client_x - win_x
                offset_y = client_y - win_y

                w = rect[2] - rect[0]
                h = rect[3] - rect[1]
                xray_window.geometry(f"{w}x{h}+{rect[0]}+{rect[1]}")
                
                canvas.delete("all")
                
                if pm is not None:
                    gv = get_game_view(pm, base_addr)
                    my_x, my_y, my_z = get_player_pos(pm, base_addr)
                    
                    if hud_overlay_data and gv:
                        for item in hud_overlay_data:
                            dx = item.get('dx')
                            dy = item.get('dy')
                            color = item.get('color', '#FFFFFF')
                            text = item.get('text', '') 
                            
                            raw_cx = gv['center'][0] + (dx * gv['sqm'])
                            raw_cy = gv['center'][1] + (dy * gv['sqm'])
                            
                            cx = raw_cx + offset_x
                            cy = raw_cy + offset_y

                            size = gv['sqm'] / 2 
                            
                            canvas.create_rectangle(cx - size, cy - size, cx + size, cy + size, 
                                                  outline=color, width=2)
                            
                            if text:
                                canvas.create_text(cx+1, cy+1, text=text, fill="black", font=("Verdana", 8, "bold"))
                                canvas.create_text(cx, cy, text=text, fill=color, font=("Verdana", 8, "bold"))
                            else:
                                canvas.create_text(cx, cy - size - 12, text=f"FISHER\n({dx}, {dy})", 
                                                 fill=color, font=("Verdana", 7, "bold"))

                    current_name = get_connected_char_name()
                    first = base_addr + TARGET_ID_PTR + REL_FIRST_ID
                    
                    for i in range(MAX_CREATURES):
                        slot = first + (i * STEP_SIZE)
                        if pm.read_int(slot) > 0:
                            vis = pm.read_int(slot + OFFSET_VISIBLE)
                            if vis == 1:
                                cz = pm.read_int(slot + OFFSET_Z)
                                if cz != my_z: 
                                    name = pm.read_string(slot + OFFSET_NAME, 32).split('\x00')[0]
                                    if name == current_name: continue
                                    
                                    cx_creature = pm.read_int(slot + OFFSET_X)
                                    cy_creature = pm.read_int(slot + OFFSET_Y)
                                    
                                    dx_c = cx_creature - my_x
                                    dy_c = cy_creature - my_y
                                    
                                    if gv:
                                        raw_sx = gv['center'][0] + (dx_c * gv['sqm'])
                                        raw_sy = gv['center'][1] + (dy_c * gv['sqm'])
                                        
                                        sx = raw_sx + offset_x
                                        sy = raw_sy + offset_y
                                        
                                        color = COLOR_FLOOR_ABOVE if cz < my_z else COLOR_FLOOR_BELOW
                                        tag = "▲" if cz < my_z else "▼"
                                        zdiff = my_z - cz
                                        
                                        canvas.create_text(sx, sy - 40, text=f"{tag} {zdiff}\n{name}", fill=color, font=("Verdana", 10, "bold"))
                                        canvas.create_rectangle(sx-20, sy-20, sx+20, sy+20, outline=color, width=2)
        except: pass
        
        xray_window.after(50, update_xray)
    
    canvas = ctk.CTkCanvas(xray_window, bg="black", highlightthickness=0)
    canvas.pack(fill="both", expand=True)
    update_xray()

def on_close():
    global bot_running
    print("Encerrando bot e threads...")
    bot_running = False 
    
    try:
        if app:
            app.quit()
            app.destroy()
    except: pass
    
    import os
    os._exit(0)   

def on_fisher_toggle():
    """Limpa o HUD visual imediatamente ao desligar o Fisher."""
    if not switch_fisher.get():
        update_fisher_hud([])

# ==============================================================================
# 7. CONSTRUÇÃO DA INTERFACE GRÁFICA (GUI LAYOUT)
# ==============================================================================

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")
app = ctk.CTk()
app.title("Molodoy Bot Pro")
#app.geometry("320x450") 
app.resizable(True, True)
app.configure(fg_color="#202020")
try:
    app.iconbitmap("app.ico")
except:
    pass 

# MAIN FRAME
main_frame = ctk.CTkFrame(app, fg_color="transparent")
main_frame.pack(fill="both", expand=True)

# HEADER
frame_header = ctk.CTkFrame(main_frame, fg_color="transparent")
frame_header.pack(pady=(10, 5), fill="x", padx=10)

btn_xray = ctk.CTkButton(frame_header, text="Raio-X", command=toggle_xray, width=25, height=25, fg_color="#303030", font=("Verdana", 10))
btn_xray.pack(side="right", padx=5)

btn_settings = ctk.CTkButton(frame_header, text="⚙️ Config.", command=open_settings, 
                             width=100, height=30, fg_color="#303030", hover_color="#505050",
                             font=("Verdana", 11, "bold"))
btn_settings.pack(side="left")

lbl_connection = ctk.CTkLabel(frame_header, text="🔌 Procurando...", 
                              font=("Verdana", 11, "bold"), text_color="#FFA500")
lbl_connection.pack(side="right", padx=5)

# CONTROLES (TOGGLE)
frame_controls = ctk.CTkFrame(main_frame, fg_color="#303030")
frame_controls.pack(padx=10, pady=5, fill="x")

frame_controls.grid_columnconfigure(0, weight=1)
frame_controls.grid_columnconfigure(1, weight=1)

switch_trainer = ctk.CTkSwitch(frame_controls, text="Trainer", progress_color="#00C000", font=("Verdana", 11))
switch_trainer.grid(row=0, column=0, sticky="w", padx=(20, 0), pady=5)

switch_loot = ctk.CTkSwitch(frame_controls, text="Auto Loot", progress_color="#00C000", font=("Verdana", 11))
switch_loot.grid(row=1, column=0, sticky="w", padx=(20, 0), pady=5)

switch_alarm = ctk.CTkSwitch(frame_controls, text="Alarm", progress_color="#00C000", font=("Verdana", 11))
switch_alarm.grid(row=0, column=1, sticky="w", padx=(10, 0), pady=5)

switch_fisher = ctk.CTkSwitch(frame_controls, text="Auto Fisher", command=on_fisher_toggle, progress_color="#00C000", font=("Verdana", 11))
switch_fisher.grid(row=1, column=1, sticky="w", padx=(10, 0), pady=5)

switch_runemaker = ctk.CTkSwitch(frame_controls, text="Runemaker", progress_color="#A54EF9", font=("Verdana", 11))
switch_runemaker.grid(row=2, column=0, sticky="w", padx=(20, 0), pady=5)

switch_cavebot = ctk.CTkSwitch(frame_controls, text="Cavebot", progress_color="#00C000", font=("Verdana", 11))
switch_cavebot.grid(row=2, column=1, sticky="w", padx=(10, 0), pady=5)

# STATS
frame_stats = ctk.CTkFrame(main_frame, fg_color="transparent", border_color="#303030", border_width=1, corner_radius=6)
frame_stats.pack(padx=10, pady=5, fill="x")
frame_stats.grid_columnconfigure(1, weight=1)

# LINHA 2 EXP
frame_exp_det = ctk.CTkFrame(frame_stats, fg_color="transparent")
frame_exp_det.grid(row=2, column=1, sticky="e", padx=10)
lbl_exp_left = ctk.CTkLabel(frame_exp_det, text="--", font=("Verdana", 10), text_color="gray")
lbl_exp_left.pack(side="left", padx=5)
lbl_exp_rate = ctk.CTkLabel(frame_exp_det, text="-- xp/h", font=("Verdana", 10), text_color="gray")
lbl_exp_rate.pack(side="left", padx=5)
lbl_exp_eta = ctk.CTkLabel(frame_exp_det, text="--", font=("Verdana", 10), text_color="gray")
lbl_exp_eta.pack(side="left")

# Divisória
frame_div = ctk.CTkFrame(frame_stats, height=1, fg_color="#303030")
frame_div.grid(row=1, column=0, columnspan=2, sticky="ew", padx=10, pady=(0, 5))

# LINHA 2 REGEN
lbl_regen = ctk.CTkLabel(frame_stats, text="🍖 --:--", font=("Verdana", 11, "bold"), text_color="gray")
lbl_regen.grid(row=2, column=0, padx=5, pady=2, sticky="w")

# LINHA 3: RECURSOS (Gold + Regen Stock)
# Usamos um frame container para organizar Esquerda vs Direita
frame_resources = ctk.CTkFrame(frame_stats, fg_color="transparent")
frame_resources.grid(row=3, column=0, columnspan=2, sticky="ew", padx=10, pady=2)

# Coluna Esquerda: Regen Stock
lbl_regen_stock = ctk.CTkLabel(frame_resources, text="🍖 Stock --", font=("Verdana", 10))
lbl_regen_stock.pack(side="left", padx=(0, 10))

# Coluna Direita: Gold (Usamos um sub-frame ou pack side right para alinhar no fim)
# Para garantir que fique na direita, podemos usar pack(side="right") nos elementos de gold

lbl_gold_rate = ctk.CTkLabel(frame_resources, text="0 gp/h", font=("Verdana", 10), text_color="gray")
lbl_gold_rate.pack(side="right")

lbl_gold_total = ctk.CTkLabel(frame_resources, text="🪙 0 gp", font=("Verdana", 10), text_color="#FFD700")
lbl_gold_total.pack(side="right", padx=(10, 10))

# LINHA 4: SWORD
box_sword = ctk.CTkFrame(frame_stats, fg_color="transparent")
box_sword.grid(row=4, column=0, padx=10, sticky="w")
ctk.CTkLabel(box_sword, text="Sword:", font=("Verdana", 11)).pack(side="left")
lbl_sword_val = ctk.CTkLabel(box_sword, text="--", font=("Verdana", 11, "bold"), text_color="#4EA5F9")
lbl_sword_val.pack(side="left", padx=(5, 0)) 

frame_sw_det = ctk.CTkFrame(frame_stats, fg_color="transparent")
frame_sw_det.grid(row=4, column=1, padx=10, sticky="e")
lbl_sword_rate = ctk.CTkLabel(frame_sw_det, text="--m/%", font=("Verdana", 10), text_color="gray")
lbl_sword_rate.pack(side="left", padx=5)
lbl_sword_time = ctk.CTkLabel(frame_sw_det, text="ETA: --", font=("Verdana", 10), text_color="gray")
lbl_sword_time.pack(side="left")

# LINHA 5: SHIELD
box_shield = ctk.CTkFrame(frame_stats, fg_color="transparent")
box_shield.grid(row=5, column=0, padx=10, sticky="w")
ctk.CTkLabel(box_shield, text="Shield:", font=("Verdana", 11)).pack(side="left")
lbl_shield_val = ctk.CTkLabel(box_shield, text="--", font=("Verdana", 11, "bold"), text_color="#4EA5F9")
lbl_shield_val.pack(side="left", padx=(5, 0))

frame_sh_det = ctk.CTkFrame(frame_stats, fg_color="transparent")
frame_sh_det.grid(row=5, column=1, padx=10, sticky="e")
lbl_shield_rate = ctk.CTkLabel(frame_sh_det, text="--m/%", font=("Verdana", 10), text_color="gray")
lbl_shield_rate.pack(side="left", padx=5)
lbl_shield_time = ctk.CTkLabel(frame_sh_det, text="ETA: --", font=("Verdana", 10), text_color="gray")
lbl_shield_time.pack(side="left")

# LINHA 6: MAGIC
box_magic = ctk.CTkFrame(frame_stats, fg_color="transparent")
box_magic.grid(row=6, column=0, padx=10, sticky="w")
ctk.CTkLabel(box_magic, text="ML:", font=("Verdana", 11)).pack(side="left")
lbl_magic_val = ctk.CTkLabel(box_magic, text="--", font=("Verdana", 11, "bold"), text_color="#A54EF9") 
lbl_magic_val.pack(side="left", padx=(5, 0))

frame_ml_det = ctk.CTkFrame(frame_stats, fg_color="transparent")
frame_ml_det.grid(row=6, column=1, padx=10, sticky="e")
lbl_magic_rate = ctk.CTkLabel(frame_ml_det, text="--m/%", font=("Verdana", 10), text_color="gray")
lbl_magic_rate.pack(side="left", padx=5)
lbl_magic_time = ctk.CTkLabel(frame_ml_det, text="ETA: --", font=("Verdana", 10), text_color="gray")
lbl_magic_time.pack(side="left")

# GRAPH
frame_graphs_container = ctk.CTkFrame(main_frame, fg_color="transparent", 
                                      border_width=0, border_color="#303030", 
                                      corner_radius=0)
frame_graphs_container.pack(padx=10, pady=(5, 0), fill="x")

btn_graph = ctk.CTkButton(frame_graphs_container, text="Mostrar Gráfico 📈", command=toggle_graph, 
                          fg_color="#202020", hover_color="#303030", 
                          height=25, corner_radius=6, border_width=0)
btn_graph.pack(side="top", fill="x", padx=1, pady=0)

frame_graph = ctk.CTkFrame(frame_graphs_container, fg_color="transparent", corner_radius=6)

plt.style.use('dark_background')
fig, ax = plt.subplots(figsize=(4, 1.6), dpi=100, facecolor='#2B2B2B')
fig.patch.set_facecolor('#202020') 
ax.set_facecolor('#202020')
ax.tick_params(axis='x', colors='gray', labelsize=6, pad=2)
ax.tick_params(axis='y', colors='gray', labelsize=6, pad=2)    
ax.spines['top'].set_visible(False)
ax.spines['right'].set_visible(False)
ax.spines['bottom'].set_color('#404040')
ax.spines['left'].set_color('#404040')
ax.set_title("Eficiencia de Treino (%)", fontsize=8, color="gray")

canvas = FigureCanvasTkAgg(fig, master=frame_graph)
widget = canvas.get_tk_widget()
widget.pack(fill="both", expand=True, padx=1, pady=2)

# LOG
txt_log = ctk.CTkTextbox(main_frame, height=90, font=("Consolas", 11), fg_color="#151515", text_color="#00FF00", border_width=1)
txt_log.pack(side="bottom", fill="x", padx=5, pady=5, expand=True)

# ==============================================================================
# 8. EXECUÇÃO PRINCIPAL
# ==============================================================================

app.after(1000, attach_window)
app.protocol("WM_DELETE_WINDOW", on_close)

# Iniciar Threads
threading.Thread(target=trainer_loop, daemon=True).start()
threading.Thread(target=alarm_loop, daemon=True).start()
threading.Thread(target=auto_loot_thread, daemon=True).start()
threading.Thread(target=skill_monitor_loop, daemon=True).start()
threading.Thread(target=gui_updater_loop, daemon=True).start()
threading.Thread(target=regen_monitor_loop, daemon=True).start()
threading.Thread(target=auto_fisher_thread, daemon=True).start()
threading.Thread(target=runemaker_thread, daemon=True).start()
threading.Thread(target=connection_watchdog, daemon=True).start()
threading.Thread(target=cavebot_thread, daemon=True).start()

update_stats_visibility()

log("🚀 Iniciado.")
app.mainloop()
bot_running = False