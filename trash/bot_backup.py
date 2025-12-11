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
from monitor import TrainingMonitor, SkillTracker, get_benchmark_min_per_pct, ExpTracker
from config import *
from auto_loot import run_auto_loot, is_player_full
from stacker import auto_stack_items
from mouse_lock import acquire_mouse, release_mouse
from map_core import get_game_view, get_screen_coord, get_player_pos
from input_core import ctrl_right_click_at, alt_right_click_at
from food_tracker import get_food_regen_time
from fisher import fishing_loop # Vamos usar essa função principal
import packet

# ==============================================================================
# CORREÇÃO DE DPI (WINDOWS SCALING)
# ==============================================================================
try:
    # Tenta definir Awareness para PER MONITOR (V2)
    # 0 = Unaware, 1 = System DPI Aware, 2 = Per Monitor DPI Aware
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
# 1. CONFIGURAÇÕES PADRÃO
# ==============================================================================
# CONFIGURAÇÕES GLOBAIS (Estado Atual)
# Variável global para guardar a referência da janela (para não abrir duplicada)

toplevel_settings = None
CONFIG_FILE = "bot_config.json"
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
    "mana_train": False
}

global_regen_seconds = 0
global_is_hungry = False
global_is_synced = False
global_is_full = False
SCAN_DELAY = 0.5  # Delay entre scans do trainer
HUMAN_DELAY_MIN = 1  # Segundos mínimos para "pensar"
HUMAN_DELAY_MAX = 4  # Segundos máximos para "pensar"
lbl_status = None # Adicione isso no topo
bot_running = True
pm = None 
base_addr = 0
is_safe_to_bot = True # True = Sem players por perto, pode atacar
is_connected = False # True apenas se: Processo Aberto + Logado no Char
is_gm_detected = False
is_graph_visible = False
gm_found = False
full_light_enabled = False # <--- NOVO

# --- CARREGAR CONFIGURAÇÕES (ANTES DA GUI) ---
if os.path.exists("bot_config.json"):
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            # A mágica: Atualiza o dicionário existente com o que veio do arquivo
            # Se houver chaves novas no código que não estão no arquivo, elas mantêm o padrão.
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
# FUNÇÕES BÁSICAS
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

def get_connected_char_name():
    """
    Lê o ID do jogador local e busca o nome correspondente na Battle List.
    """
    try:
        if pm is None: return ""
        
        # Lê o ID do jogador logado
        player_id = pm.read_int(base_addr + OFFSET_PLAYER_ID)
        
        if player_id == 0: return ""

        # Varre a Battle List para achar o nome desse ID
        list_start = base_addr + TARGET_ID_PTR + REL_FIRST_ID
        
        for i in range(MAX_CREATURES):
            slot = list_start + (i * STEP_SIZE)
            # Lê ID da criatura na lista
            c_id = pm.read_int(slot)
            
            if c_id == player_id:
                # Achou nosso char! Lê o nome.
                name = pm.read_string(slot + OFFSET_NAME, 32)
                return name.split('\x00')[0].strip()
                
    except: pass
    return ""

# Adicionar no escopo global ou utilitário
def register_food_eaten(item_id):
    """
    Chamado pelos módulos (Runemaker/AutoLoot/MonitorManual) quando comem algo.
    Só altera o Timer se já estivermos Sincronizados ou se estivermos Famintos (Sync Point).
    """
    global global_regen_seconds, global_is_synced, global_is_hungry
    
    # Busca o tempo no nosso database
    regen_time = get_food_regen_time(item_id)
    
    if regen_time > 0:
        # CENÁRIO 1: Já temos o controle do tempo (Sync Ativo)
        if global_is_synced:
            global_regen_seconds += regen_time
            
            # Trava no máximo permitido
            if global_regen_seconds > MAX_FOOD_TIME:
                global_regen_seconds = MAX_FOOD_TIME
                
            # Se comeu, garantimos que não está mais faminto
            global_is_hungry = False
            # log(f"🍖 +{regen_time}s (Total: {int(global_regen_seconds)}s)")

        # CENÁRIO 2: O personagem estava FAMINTO (Momento do Sync)
        # Se estava faminto, sabemos que o tempo era 0. Agora sabemos o novo tempo.
        elif global_is_hungry:
            log(f"🍽️ Sincronizado por Fome! Início: {regen_time}s")
            
            global_is_synced = True
            global_regen_seconds = regen_time
            global_is_hungry = False

        # CENÁRIO 3: Estado Desconhecido (Calc...)
        # O personagem está regenerando, mas não sabemos quanto tempo resta (X).
        # Comer agora vira (X + regen_time), que continua sendo uma incógnita.
        # Portanto, IGNORAMOS a soma e continuamos esperando a fome real chegar.
        else:
            log(f"🍖 Comeu durante 'Calc...' (Timer continua desconhecido)")
            pass
# ==============================================================================
# LOOP DE TREINO (INTEGRADO COM MONITOR)
# ==============================================================================
def trainer_loop():
    # global battle_pos
    hwnd = 0

    # Variáveis de Estado do Alvo
    current_monitored_id = 0
    last_target_data = None # Vai guardar a posição (X,Y) e o ID do alvo atual

    next_attack_time = 0       # Timestamp de quando posso atacar
    waiting_for_attack = False

    while bot_running:
        # if is_paused_global: 
        #     time.sleep(0.5)
        #     continue

        if not is_connected: time.sleep(1); continue
        if not switch_trainer.get(): time.sleep(1); continue
        if pm is None: time.sleep(1); continue
        if hwnd == 0: hwnd = win32gui.FindWindow("TibiaClient", None) or win32gui.FindWindow(None, "Tibia")
        if not is_safe_to_bot: time.sleep(0.5); continue # Pula o resto e volta pro inicio pra checar de novo

        try:  
            # 0. IDENTIFICA O JOGADOR ATUAL (NOVO)
            current_name = get_connected_char_name()
            if not current_name: # Se não achou nome, pula
                time.sleep(0.5); continue
            
            # Ponteiros
            target_addr = base_addr + TARGET_ID_PTR
            list_start = base_addr + TARGET_ID_PTR + REL_FIRST_ID
            
            # 1. DADOS DO JOGADOR (X, Y, Z)
            my_x, my_y, my_z = get_player_pos(pm, base_addr)
            if my_z == 0: # Leitura falhou
                time.sleep(0.2)
                continue

            # 2. SCAN: MAPEAR O CAMPO DE BATALHA
            # Cria uma lista apenas com criaturas que valem a pena atacar (Visíveis + Perto)
            valid_candidates = []
            visual_line_count = 0 # Conta linhas para saber onde clicar no Battle

            if BOT_SETTINGS['debug_mode']: print(f"\n--- INÍCIO DO SCAN (Meu Z: {my_z}) ---") # Debug
            
            for i in range(MAX_CREATURES):
                slot = list_start + (i * STEP_SIZE)
                try:
                    c_id = pm.read_int(slot)
                    if c_id > 0:
                        raw = pm.read_string(slot + OFFSET_NAME, 32)
                        name = raw.split('\x00')[0].strip()
                        vis = pm.read_int(slot + OFFSET_VISIBLE)
                        z = pm.read_int(slot + OFFSET_Z)
                        # Leitura de Posição e HP
                        cx = pm.read_int(slot + OFFSET_X)
                        cy = pm.read_int(slot + OFFSET_Y)
                        hp = pm.read_int(slot + OFFSET_HP)
                        
                        # Calcula Distância (Melee = 1 sqm)
                        dist_x = abs(my_x - cx)
                        dist_y = abs(my_y - cy)
                        is_melee = (dist_x <= 1 and dist_y <= 1)
                
                        if BOT_SETTINGS['debug_mode']: print(f"Slot {i}: {name} (Vis:{vis} Z:{z} HP:{hp} Dist:({dist_x},{dist_y}))")

                        if name == current_name: continue

                        # Filtro Visual Global (Para saber onde clicar na janela)
                        is_on_battle_list = (vis == 1 and z == my_z)

                        if is_on_battle_list:
                            if BOT_SETTINGS['debug_mode']: print(f"   [LINHA {visual_line_count}] -> {name} (ID: {c_id})")
                            current_line = visual_line_count
                            visual_line_count += 1 # Ocupa uma linha no battle
                            
                            # É um monstro alvo? (Ex: Troll)
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
                print(f"Candidato 3: {valid_candidates[2] if len(valid_candidates) > 2 else 'Nenhum'}")
                print("-------------------------")
                # 3. TOMADA DE DECISÃO
                print("---- TOMADA DE DECISÃO ----")

            current_target_id = pm.read_int(target_addr)
            should_attack_new = False

            # Cenário A: Já estou atacando alguém
            if current_target_id != 0:
                
                if BOT_SETTINGS['debug_mode']: print(f"Atacando ID: {current_target_id}")
                # Verifica se esse alvo ainda está na nossa lista de "Válidos" (Perto/Vivo)
                # Procuramos ele na lista 'valid_candidates' pelo ID
                target_data = next((c for c in valid_candidates if c["id"] == current_target_id), None)
                if BOT_SETTINGS['debug_mode']: print(f"-> Target Data: {target_data}")
                if target_data:
                    waiting_for_attack = False # Reseta espera se já atacou
                    next_attack_time = 0       # Reseta timer
                    last_target_data = target_data.copy()
                    # O alvo está ótimo (Perto e Vivo). Mantém ataque e monitora.
                    if current_target_id != current_monitored_id:
                        monitor.start(current_target_id, target_data["name"], target_data["hp"])
                        current_monitored_id = current_target_id
                        if BOT_SETTINGS['debug_mode']: print(f"--> Iniciando monitoramento em {target_data['name']} (ID: {current_target_id})")
                    else:
                        monitor.update(target_data["hp"])
                        if BOT_SETTINGS['debug_mode']: print(f"--> Atualizando monitoramento em {target_data['name']} (HP: {target_data['hp']})")
                else:
                    # O alvo sumiu da lista de válidos! 
                    # (Ou morreu, ou ficou invisível, ou andou pra longe).
                    if BOT_SETTINGS['debug_mode']: print("-> Alvo inválido (morto/fora de alcance).")
                    pass

           # --- CENÁRIO B: O ALVO SUMIU (MORREU OU PAREI DE ATACAR?) ---
            elif current_target_id == 0 and current_monitored_id != 0:
                
                # 1. VERIFICAÇÃO DE MORTE REAL (Correção solicitada)
                # Se o ID do monstro antigo ainda estiver na lista de 'valid_candidates',
                # significa que ele está vivo (HP > 0) e perto. 
                # Logo, eu apenas parei de atacar (ESC ou troca de target).
                target_still_alive = False
                if last_target_data:
                    for m in valid_candidates:
                        if m["id"] == last_target_data["id"]:
                            target_still_alive = True
                            break
                
                if target_still_alive:
                    log("🛑 Ataque interrompido (Monstro ainda vivo).")
                    # Apenas para de monitorar, não tenta abrir corpo
                    monitor.stop_and_report()
                    current_monitored_id = 0
                    last_target_data = None
                    should_attack_new = True # Ou False, se quiser que ele pare totalmente
                
                else:
                    # Se não está na lista de vivos, então MORREU (ou sumiu da tela).
                    log("💀 Alvo eliminado (Confirmado).")
                    
                    # 2. TENTA ABRIR CORPO (Condicional ao Toggle)
                    # Só entra aqui se tiver dados E se o botão Auto Loot estiver LIGADO
                    if last_target_data and switch_loot.get():
                        
                        dx = last_target_data["abs_x"] - my_x
                        dy = last_target_data["abs_y"] - my_y
                        
                        # Checa se morreu perto
                        if abs(dx) <= 1 and abs(dy) <= 1 and last_target_data["z"] == my_z:
                            
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

                    # Finaliza monitoramento
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
                        # Ignora o primeiro (índice 0) e foca no segundo (índice 1)
                        # Criamos uma lista contendo apenas o segundo monstro como prioridade
                        final_candidates = [valid_candidates[1]]
                    else:
                        # Se tem menos de 2 monstros, NÃO ATACA NINGUÉM
                        final_candidates = []
                        # Opcional: Log para saber pq não está atacando
                        # if len(valid_candidates) == 1: log("Aguardando 2º monstro...")
                
                if BOT_SETTINGS['debug_mode']: print("Decidido: Atacar novo alvo.")
                if len(final_candidates) > 0:

                    if next_attack_time == 0:
                        delay = random.uniform(HUMAN_DELAY_MIN, HUMAN_DELAY_MAX) # Define delay aleatório entre 1.5s e 4s
                        next_attack_time = time.time() + delay # Define o timestamp no futuro
                        waiting_for_attack = True
                        log(f"⏳ Aguardando {delay:.2f}s para atacar...")   

                    if time.time() >= next_attack_time:
                        # Ataca o PRIMEIRO da lista de válidos (Melhor opção)
                        best = final_candidates[0]
                        if BOT_SETTINGS['debug_mode']: print(f"-> Melhor Candidato: {best['name']} (ID: {best['id']})")            
                        # Só clica se for um ID diferente do anterior (pra não spamar clique se o char estiver andando)
                        if best["id"] != current_target_id:
                            # --- MUDANÇA: ATAQUE VIA PACOTE ---
                            log(f"⚔️ ATACANDO (Packet): {best['name']}")
                            
                            # 1. Envia o pacote para o servidor
                            # 2. Escreve na memória do cliente (Red Square)
                            packet.attack(pm, base_addr, best["id"])
                            
                            # Não precisamos mais mexer no mouse!
                            # acquire_mouse() ... release_mouse() -> REMOVIDOS
                            
                            # Atualiza estado local
                            current_target_id = best["id"]
                            next_attack_time = 0
                            waiting_for_attack = False
                            time.sleep(0.5)
                    #         log(f"⚔️ ATACANDO: {best['name']} (Linha {best['line']})")
                    #         # bx = int(battle_pos["x"])
                    #         # by = int(battle_pos["y"] + (best["line"] * SLOT_HEIGHT))   
                    #         dx = best["abs_x"] - my_x
                    #         dy = best["abs_y"] - my_y
                    #         gv = get_game_view(pm, base_addr)
                    #         if gv:
                    #             attack_x, attack_y = get_screen_coord(gv, dx, dy, hwnd)
                    #             acquire_mouse() # 1. Pede permissão (pausa o loot se precisar)
                    #             try:
                    #                 # background_click(hwnd, bx, by)
                    #                 alt_right_click_at(hwnd, attack_x, attack_y)
                    #             finally:
                    #                 release_mouse() # 2. Libera imediatamente
                    #             # -----------------------------
                    #             if BOT_SETTINGS['debug_mode']: print(f"--> Clicando em {best['line']}: ({attack_x}, {attack_y})")
                                
                    #             next_attack_time = 0
                    #             waiting_for_attack = False
                    #             time.sleep(0.5) # Tempo pro clique registrar
                    #         else:
                    #             log("❌ Erro: GameView não encontrado para ataque.")
                    # else:
                        pass

            if BOT_SETTINGS['debug_mode']: print("---- FIM DA ITERAÇÃO ----")
            time.sleep(SCAN_DELAY)

        except Exception as e:
            print(f"[ERRO LOOP] {e}")
            time.sleep(1)

# ==============================================================================

def alarm_loop():
    global is_safe_to_bot, is_gm_detected, gm_found
    last_alert = 0
    
    while bot_running:
        # if is_paused_global: 
        #     time.sleep(0.5)
        #     continue

        if not is_connected:
            time.sleep(1)
            continue

        if not switch_alarm.get():
            # Se o usuário desligou o alarme, assumimos que é seguro (Override)
            if not is_safe_to_bot:
                log("🔔 Alarme desativado manualmente. Retomando rotinas.")
                is_gm_detected = False # Resetar GM também
                is_safe_to_bot = True

            
            time.sleep(1)
            continue
            
        if pm is None:
            time.sleep(1); continue
            
        try:
            current_name = get_connected_char_name()
            # Ponteiros
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

                        # --- LÓGICA DE ANDARES (NOVO) ---
                        is_z_valid = False
                        
                        if BOT_SETTINGS['alarm_floor'] == "Padrão":
                            is_z_valid = (cz == my_z)
                            
                        elif BOT_SETTINGS['alarm_floor'] == "Superior (+1)":
                            # Superior no Tibia é Z menor (ex: 7 -> 6)
                            is_z_valid = (cz == my_z or cz == my_z - 1)
                            
                        elif BOT_SETTINGS['alarm_floor'] == "Inferior (-1)":
                            # Inferior no Tibia é Z maior (ex: 7 -> 8)
                            is_z_valid = (cz == my_z or cz == my_z + 1)
                            
                        elif BOT_SETTINGS['alarm_floor'] == "Todos (Raio-X)":
                            # Qualquer andar adjacente
                            is_z_valid = (abs(cz - my_z) <= 1)
                        
                        # Se a config estiver corrompida, usa padrão
                        else: 
                            is_z_valid = (cz == my_z)

                        # Filtro: Visível e Z Válido conforme config
                        if vis != 0 and is_z_valid:
                            
                            raw = pm.read_string(slot + OFFSET_NAME, 32)
                            name = raw.split('\x00')[0].strip()
                            if name == current_name: continue

                            if name.startswith("GM ") or name.startswith("CM ") or name.startswith("God "):
                                danger = True
                                gm_found = True
                                d_name = f"GAMEMASTER {name}"
                                break # Para o scan imediatamente
                            
                            # Verifica se é criatura perigosa (Não está na Safe List)
                            is_safe = any(s in name for s in BOT_SETTINGS['safe'])
                            
                            if not is_safe:
                                # --- NOVA LÓGICA DE DISTÂNCIA ---
                                cx = pm.read_int(slot + OFFSET_X)
                                cy = pm.read_int(slot + OFFSET_Y)
                                
                                # Calcula distância (Vetor Maior)
                                dist = max(abs(my_x - cx), abs(my_y - cy))
                                
                                # Só dispara se estiver DENTRO do raio configurado
                                if dist <= BOT_SETTINGS['alarm_range']:
                                    danger = True
                                    d_name = f"{name} ({dist} SQM)"
                                    break # Encontrou perigo, para o scan
                                
                except: continue
                
            if danger:
                is_safe_to_bot = False # PAUSA O TRAINER/LOOT
                is_gm_detected = gm_found
                log(f"⚠️ PERIGO: {d_name}!")
                if gm_found: 
                    winsound.Beep(2000, 1000) # Bip mais longo/agudo
                else:
                    winsound.Beep(1000, 500)
                
                if (time.time() - last_alert) > 60:
                    send_telegram(f"PERIGO! {d_name} aproximou-se!")
                    last_alert = time.time()
            else: 
                is_safe_to_bot = True # TUDO LIMPO
                is_gm_detected = False

            time.sleep(0.5)
        except Exception as e: 
            print(f"Erro Alarm: {e}")
            time.sleep(1)

# ==============================================================================

# def regen_monitor_loop():
#     global pm, base_addr, bot_running, is_connected
#     global global_regen_seconds, global_is_hungry, global_is_synced, global_is_full
    
#     print("[REGEN] Monitor Iniciado (Tracker de Stacks Ativado)")
    
#     # Variáveis de Tempo e Estado
#     regen_seconds_left = 0
#     is_synced = False 
    
#     last_hp = -1
#     last_mana = -1
#     last_check_time = time.time()
    
#     seconds_no_hp_up = 0
#     seconds_no_mana_up = 0
    
#     # AGORA RASTREAMOS O PAR (ID, COUNT)
#     last_interaction_id = 0
#     last_interaction_count = 0
    
#     # THRESHOLD_HP = 6 + 2
#     # THRESHOLD_MANA = 12 + 2
    
#     while bot_running:
#         if not is_connected or pm is None:
#             time.sleep(1)
#             continue
            
#         try:
#             hp_tick, mana_tick = VOCATION_REGEN.get(BOT_SETTINGS['vocation'], (6, 12))

#             threshold_hp = hp_tick + 2
#             threshold_mana = mana_tick + 2

#             # 1. LEITURA DE DADOS
#             curr_hp = pm.read_int(base_addr + OFFSET_PLAYER_HP)
#             max_hp = pm.read_int(base_addr + OFFSET_PLAYER_HP_MAX)
#             curr_mana = pm.read_int(base_addr + OFFSET_PLAYER_MANA)
#             max_mana = pm.read_int(base_addr + OFFSET_PLAYER_MANA_MAX)
            
#             # Lê ID e Count
#             curr_id = pm.read_int(base_addr + OFFSET_LAST_USED_ITEM_ID)
#             curr_count = pm.read_int(base_addr + OFFSET_LAST_USED_ITEM_COUNT)
            
#             # 2. DETECÇÃO DE CONSUMO (ID OU COUNT MUDARAM?)
#             # Se o ID mudou (comida diferente) OU a contagem mudou (mesma comida, pilha menor)
#             has_changed = (curr_id != last_interaction_id) or \
#                           (curr_id == last_interaction_id and curr_count != last_interaction_count)
            
#             if has_changed:
#                 food_time = get_food_regen_time(curr_id)
                
#                 if food_time > 0:
#                     # Debug para você ver funcionando
#                     # print(f"[REGEN] Click detectado! ID: {curr_id} | Count: {curr_count} (Antigo: {last_interaction_count})")
                    
#                     time.sleep(0.2)
#                     if is_player_full(pm, base_addr):
#                         pass
#                     else:
#                         # Reseta fome imediatamente ao tentar comer
#                         seconds_no_hp_up = 0
#                         seconds_no_mana_up = 0
                        
#                         if is_synced:
#                             if regen_seconds_left == 0:
#                                 log(f"🍖 Regen iniciado: +{food_time}s")
#                             regen_seconds_left += food_time
#                             if regen_seconds_left > MAX_FOOD_TIME:
#                                 regen_seconds_left = MAX_FOOD_TIME
                
#                 # Atualiza a referência para o estado atual
#                 last_interaction_id = curr_id
#                 last_interaction_count = curr_count

#             # 3. LÓGICA DE ESTADO (Igual ao anterior)
#             now = time.time()
#             if now - last_check_time >= 1.0:
                
#                 is_hp_full = (curr_hp >= max_hp)
#                 if curr_hp > last_hp:
#                     seconds_no_hp_up = 0
#                 elif not is_hp_full:
#                     seconds_no_hp_up += 1
                
#                 is_mana_full = (curr_mana >= max_mana)
#                 if curr_mana > last_mana:
#                     seconds_no_mana_up = 0
#                 elif not is_mana_full:
#                     seconds_no_mana_up += 1
                
#                 hungry_by_hp = (not is_hp_full and seconds_no_hp_up >= threshold_hp)
#                 hungry_by_mana = (not is_mana_full and seconds_no_mana_up >= threshold_mana)
#                 is_hungry = hungry_by_mana
#                 is_totally_full = is_hp_full and is_mana_full

#                 status_text = "--:--"
#                 color = "gray"

#                 if is_hungry:
#                     if is_synced and regen_seconds_left > 120:
#                         regen_seconds_left -= 1
#                         mins = int(regen_seconds_left // 60)
#                         secs = int(regen_seconds_left % 60)
#                         status_text = f"🍖 {mins:02d}:{secs:02d}"
#                         color = "#00FF00"
#                     else:
#                         if not is_synced: log("🍽️ Sincronizado: Fome detectada.")
#                         is_synced = True
#                         regen_seconds_left = 0
#                         status_text = "FAMINTO"
#                         color = "#FF5555"
                
#                 elif is_synced and regen_seconds_left > 0:
#                     regen_seconds_left -= 1
#                     mins = int(regen_seconds_left // 60)
#                     secs = int(regen_seconds_left % 60)
#                     status_text = f"🍖 {mins:02d}:{secs:02d}"
#                     color = "#00FF00"
                    
#                 else:
#                     if is_totally_full:
#                         status_text = "🔵 Full"
#                         color = "#4EA5F9"
#                         # Se está full, assumimos que o regen pode estar pausado ou ativo, 
#                         # mas não decrementamos para não gerar falso negativo.
#                     else:
#                         status_text = "🟡 Calculando..." 
#                         color = "#E0E000"
                    
#                 global_regen_seconds = regen_seconds_left
#                 global_is_hungry = (regen_seconds_left == 0 and is_synced) or (status_text == "🍽️ FAMINTO")
#                 global_is_synced = is_synced
#                 global_is_full = is_totally_full

#                 if lbl_regen and lbl_regen.winfo_exists():
#                     lbl_regen.configure(text=status_text, text_color=color)

#                 last_hp = curr_hp
#                 last_mana = curr_mana
#                 last_check_time = now
            
#             time.sleep(0.1)
#         except Exception as e:
#             print(f"Erro Regen: {e}")
#             time.sleep(1)

def regen_monitor_loop():
    global pm, base_addr, bot_running, is_connected
    global global_regen_seconds, global_is_hungry, global_is_synced, global_is_full
    
    print("[REGEN] Monitor Iniciado (Modo Híbrido com Validação Dupla)")
    
    # Variáveis de Estado
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
            # -----------------------------------------------------------
            # 1. DETECÇÃO MANUAL DE CLIQUE (Sincronia por ação do usuário)
            # -----------------------------------------------------------
            curr_mem_id = pm.read_int(base_addr + OFFSET_LAST_USED_ITEM_ID)
            
            if curr_mem_id != 0:
                if curr_mem_id != last_mem_id:
                    if curr_mem_id in FOOD_IDS:
                        time.sleep(0.4) # Wait ping
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

            # -----------------------------------------------------------
            # 2. LEITURA DE DADOS E ANÁLISE DE TICKS
            # -----------------------------------------------------------
            curr_hp = pm.read_int(base_addr + OFFSET_PLAYER_HP)
            max_hp = pm.read_int(base_addr + OFFSET_PLAYER_HP_MAX)
            curr_mana = pm.read_int(base_addr + OFFSET_PLAYER_MANA)
            max_mana = pm.read_int(base_addr + OFFSET_PLAYER_MANA_MAX)
            
            hp_tick, mana_tick = VOCATION_REGEN.get(BOT_SETTINGS['vocation'], (6, 12))
            # Damos uma margem de segurança maior (2x o tick) para evitar falsos positivos
            threshold_mana = mana_tick + 2 

            now = time.time()
            if now - last_check_time >= 1.0:
                
                # --- Verifica se está CHEIO ---
                is_hp_full = (curr_hp >= max_hp)
                is_mana_full = (curr_mana >= max_mana)
                is_totally_full = is_hp_full and is_mana_full
                
                # --- Verifica Ticks (Mana subiu?) ---
                if curr_mana > last_mana:
                    seconds_no_mana_up = 0 # Mana subiu, reseta contador
                elif not is_mana_full:
                    seconds_no_mana_up += 1 # Mana não subiu e não tá cheia, conta tempo
                
                # "Fome Lógica": Passou do tempo de tick e a mana não subiu (e não tá cheia)
                hungry_by_logic = (not is_mana_full and seconds_no_mana_up >= threshold_mana)
                
                # -----------------------------------------------------------
                # 3. LÓGICA DE ESTADO (CORREÇÃO APLICADA AQUI)
                # -----------------------------------------------------------
                status_text = "--:--"
                color = "gray"
                final_is_hungry = False

                if global_is_synced:
                    # MODO SINCRONIZADO
                    if global_regen_seconds > 0:
                        # TEMPO DE SOBRA: Apenas decrementa
                        global_regen_seconds -= 1
                        mins = int(global_regen_seconds // 60)
                        secs = int(global_regen_seconds % 60)
                        status_text = f"🍖 {mins:02d}:{secs:02d}"
                        color = "#00FF00"
                        final_is_hungry = False
                    else:
                        # TEMPO ACABOU: Validação Dupla
                        # O timer diz que acabou, mas vamos checar se a mana parou mesmo.
                        
                        if is_mana_full:
                            # Se está cheio, não dá pra saber se acabou o regen. 
                            # Assume que NÃO está faminto para não desperdiçar comida.
                            # O timer fica zerado esperando gastar mana.
                            status_text = "🔵 Full (Sync)"
                            color = "#4EA5F9"
                            final_is_hungry = False
                            
                        elif hungry_by_logic:
                            # Timer zerado E Mana parou de subir -> CONFIRMADO
                            status_text = "🔴 FAMINTO"
                            color = "#FF5555"
                            final_is_hungry = True
                            
                        else:
                            # Timer zerado MAS Mana ainda está subindo (Timer estava adiantado)
                            # Mantém em espera até parar de subir
                            status_text = "🟡 Validando..."
                            color = "#E0E000"
                            final_is_hungry = False
                        
                else:
                    # MODO NÃO SINCRONIZADO (Busca inicial)
                    if hungry_by_logic:
                         status_text = "🔴 FAMINTO"
                         color = "#FF5555"
                         final_is_hungry = True # Força comer para sincronizar
                    elif is_totally_full:
                        status_text = "🔵 Full"
                        color = "#4EA5F9"
                        final_is_hungry = False
                    else:
                        status_text = "🟡 Calc..." 
                        color = "gray"
                        final_is_hungry = False
                
                # Atualiza Globais
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

# ==============================================================================
# GUI E MONITORAMENTO DE SKILLS
# ==============================================================================

def skill_monitor_loop():
    """
    Thread RÁPIDA: Apenas lê memória e atualiza a lógica matemática.
    Não mexe na interface gráfica.
    """
    while bot_running:
        if pm is not None:
            try:
                # Leitura da Memória
                sw_pct = pm.read_int(base_addr + OFFSET_SKILL_SWORD_PCT)
                sh_pct = pm.read_int(base_addr + OFFSET_SKILL_SHIELD_PCT)
                ml_pct = pm.read_int(base_addr + OFFSET_MAGIC_PCT)
                ml_lvl = pm.read_int(base_addr + OFFSET_MAGIC_LEVEL)
                
                # Atualiza os Trackers (O Tracker agora cuida do cronômetro)
                sword_tracker.update(sw_pct)
                shield_tracker.update(sh_pct)
                magic_tracker.update(ml_pct)

            except:
                pass
        
        # Monitora a cada 0.1s para alta precisão no tempo
        time.sleep(1)

def gui_updater_loop():
    while bot_running:
        if not is_connected:
            # Zera os labels se desconectar
            lbl_sword_val.configure(text="--")
            lbl_shield_val.configure(text="--")
            time.sleep(1)
            continue
    
        # ATUALIZAÇÃO DE PAUSE
        # if is_paused_global:
        #      # Se quiser que o gráfico pare de atualizar, coloque continue aqui. 
        #      # Mas geralmente queremos ver stats mesmo pausado.
        #      pass

        # # 0. ATUALIZA NOME (Se mudou)
        # char_name = get_connected_char_name()
        # # Se não tiver imagem, usa um emoji de fallback no texto
        # display_text = char_name if img_icon else f"🧙‍♂️ {char_name}"
        
        # if lbl_char_name.cget("text") != display_text:
        #     lbl_char_name.configure(text=display_text)

        # Pega os dados mais recentes dos trackers
        sw_data = sword_tracker.get_display_data()
        sh_data = shield_tracker.get_display_data()
        ml_stats = magic_tracker.get_display_data()
        
        # Só atualiza se tivermos leitura válida
        if pm is not None and sw_data['pct'] != -1:
            try:
                # EXP (Novo)
                curr_exp = pm.read_int(base_addr + OFFSET_EXP)
                char_lvl = pm.read_int(base_addr + OFFSET_LEVEL)
                # O OFFSET_EXP pode ser int ou long (64bit). Se der erro, tente read_longlong.
                # No Tibia antigo (32bit) é int mesmo.
                
                exp_tracker.update(curr_exp)
                xp_stats = exp_tracker.get_stats(char_lvl)
                
                #lbl_level_val.configure(text=f"Lvl: {char_lvl}")
                if xp_stats['xp_hour'] > 0:
                    xp_h = xp_stats['xp_hour']
                    lbl_exp_rate.configure(text=f"{xp_h} exp/h")
                    lbl_exp_eta.configure(text=f"ETA: {xp_stats['eta']}")
                else:
                    lbl_exp_rate.configure(text="-- xp/h")
                    lbl_exp_eta.configure(text="ETA: --")

                # --- LEITURA DE NÍVEIS (Para o Benchmark) ---
                sw_lvl = pm.read_int(base_addr + OFFSET_SKILL_SWORD)
                sh_lvl = pm.read_int(base_addr + OFFSET_SKILL_SHIELD)
                ml_pct = pm.read_int(base_addr + OFFSET_MAGIC_PCT)
                ml_lvl = pm.read_int(base_addr + OFFSET_MAGIC_LEVEL)

                # --- ATUALIZA LABELS VISUAIS (PCT) ---
                lbl_sword_val.configure(text=f"{sw_data['pct']}%")
                lbl_shield_val.configure(text=f"{sh_data['pct']}%")
                lbl_magic_val.configure(text=f"{ml_lvl} ({ml_stats['pct']}%)")

                # --- CÁLCULO DE EFICIÊNCIA (SWORD) ---
                bench_sw = get_benchmark_min_per_pct(sw_lvl, BOT_SETTINGS['vocation'], "Melee")
                real_sw = sw_data['speed'] # Pega a velocidade gravada no último avanço
                
                # Mostra Velocidade (Minutos por %)
                if ml_stats['speed'] > 0:
                    lbl_magic_rate.configure(text=f"{ml_stats['speed']:.1f}m/%")
                    
                    # Calcula ETA (Tempo Restante)
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
                    
                    # Definição de Cores
                    color_sw = "#00FF00" if efficiency >= 90 else "#FFFF00" if efficiency >= 70 else "#FF5555"
                    
                    lbl_sword_rate.configure(text=f"{real_sw:.1f} m/% ({efficiency:.0f}%)", text_color=color_sw)
                    
                    # Estimativa de Tempo para o próximo nível (Baseado na velocidade real)
                    pct_left = 100 - sw_data['pct']
                    mins_left_sw = pct_left * real_sw
                    # Converte o total de minutos (float) para inteiro
                    total_minutos = int(mins_left_sw)
                    horas, minutos = divmod(total_minutos, 60)
                    lbl_sword_time.configure(text=f"ETA {horas:02d}:{minutos:02d}")
                else:
                    lbl_sword_rate.configure(text="-- m/%", text_color="gray")
                    lbl_sword_time.configure(text="--")

                # --- CÁLCULO DE EFICIÊNCIA (SHIELD) ---
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
                ax.clear() # Limpa o gráfico anterior
                
                # --- PREPARAÇÃO DOS DADOS SWORD ---
                sw_hist_speed = sword_tracker.get_display_data()['history']
                sw_eff_hist = []
                
                # Só calcula se tiver dados
                if len(sw_hist_speed) > 1:
                    # Pega o benchmark atual (meta de velocidade)
                    bench_sw = get_benchmark_min_per_pct(sw_lvl, BOT_SETTINGS['vocation'], "Melee")
                    
                    # Converte cada velocidade do histórico em % de Eficiência
                    # Fórmula: (Meta / Real) * 100
                    for s in sw_hist_speed:
                        if s > 0:
                            eff = (bench_sw / s) * 100
                            if eff > 100: eff = 100 # Trava em 100% como solicitado
                            sw_eff_hist.append(eff)
                        else:
                            sw_eff_hist.append(0)

                    # Plota a linha de Eficiência (Azul)
                    ax.plot(sw_eff_hist, color='#4EA5F9', linewidth=2, marker='.', markersize=5, label='Sword')
                    
                    # Preenche a área embaixo da linha (Efeito visual bonito)
                    ax.fill_between(range(len(sw_eff_hist)), sw_eff_hist, color='#4EA5F9', alpha=0.1)

                # --- (OPCIONAL) PREPARAÇÃO DOS DADOS SHIELD ---
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

                # --- CONFIGURAÇÃO VISUAL DO GRÁFICO ---
                
                # Linha de Referência (Meta 100%)
                ax.axhline(y=100, color='#00FF00', linestyle='--', linewidth=1, alpha=0.5, label='Meta')
                
                # Título e Eixos
                ax.set_title("Eficiência de Treino (%)", fontsize=7, color="gray", pad=5)
                ax.set_ylim(0, 110) # Fixa o topo em 110% para o 100% não ficar colado no teto
                
                # Estilização Dark Mode
                ax.grid(color='#303030', linestyle='--', linewidth=0.5)
                ax.set_facecolor('#202020')
                ax.tick_params(colors='gray', labelsize=8)
                ax.spines['top'].set_visible(False)
                ax.spines['right'].set_visible(False)
                ax.spines['bottom'].set_color('#404040')
                ax.spines['left'].set_color('#404040')
                
                # Legenda
                ax.legend(facecolor='#202020', edgecolor='#404040', labelcolor='gray', fontsize=5, loc='lower right')
                
                # --- CORREÇÃO AQUI ---
                # Força uma margem inferior de 20% da altura total para caber o texto
                # bottom=0.20 (ou 0.25 se ainda cortar)
                # fig.subplots_adjust(bottom=0.30, left=0.12, right=0.95, top=0.70)
                # ---------------------

                canvas.draw()
                
            except Exception as e:
                print(f"Erro Plot: {e}")

        # Aguarda 60 segundos antes de atualizar a tela novamente
        # (Usa um loop pequeno de 1s para permitir fechar o bot rapidamente se precisar)
        for _ in range(60):
            if not bot_running: break
            time.sleep(1)

def attach_window():
    try:
        hwnd_tibia = win32gui.FindWindow("TibiaClient", None)
        if not hwnd_tibia: hwnd_tibia = win32gui.FindWindow(None, "Tibia")
        hwnd_bot = win32gui.GetParent(app.winfo_id())
        if hwnd_tibia and hwnd_bot:
            win32gui.SetWindowLong(hwnd_bot, -8, hwnd_tibia)
            app.attributes("-topmost", False)
    except: pass

def auto_loot_thread():
    """Thread dedicada para verificar, coletar loot e organizar."""
    hwnd = 0
    while bot_running:
        # if is_paused_global: 
        #     time.sleep(0.5)
        #     continue
        
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
            # 1. Tenta Lootear (Prioridade Máxima)
            did_loot = run_auto_loot(pm, base_addr, hwnd, 
                                   my_containers_count=BOT_SETTINGS['loot_containers'],
                                   dest_container_index=BOT_SETTINGS['loot_dest'])
            
            if did_loot:

                if isinstance(did_loot, tuple) and did_loot[0] == "EAT":
                    item_id = did_loot[1]
                    log(f"🍖 Comida {item_id} comida do corpo.")
                    register_food_eaten(item_id) # <--- Atualiza Regen
                    # LOGS ESPECÍFICOS BASEADOS NO RETORNO

                if did_loot == "LOOT":
                    log("💰 Loot guardado!")
                    time.sleep(0.5) # Pequena pausa extra para loot

                elif did_loot == "FULL_BP_ALARM":
                    # Toca alarme e avisa
                    log("⚠️ BACKPACKS CHEIAS! Loot pausado.")
                    # winsound.Beep(500, 1000) # Som grave e longo
                    # send_telegram("Backpack Cheia! Bot pausado de lootear.")
                    time.sleep(2) # Espera um tempo antes de spammar de novo
                
                elif did_loot == "EAT":
                    log("🍖 Comida consumida.")
                
                elif did_loot == "EAT_FULL":
                    # Opcional: Não logar se estiver cheio para não spammar
                    pass 
                
                elif did_loot == "DROP":
                    log("🗑️ Lixo jogado fora.")
                
                elif did_loot == "BAG":
                    log("🎒 Bag extra aberta.")
                
                # Continua o loop imediatamente para pegar o próximo item
                time.sleep(0.5)
                continue
            
            # 2. Se não tiver loot para pegar, tenta organizar (Stack)
            # Só executa se switch_auto_stack estiver ligado (opcional) ou sempre.
            # Vamos assumir que sempre queremos organizar se estiver ocioso.
            
            did_stack = auto_stack_items(pm, base_addr, hwnd,
                                       my_containers_count=BOT_SETTINGS['loot_containers'])
            
            if did_stack:
                log("Stackou.")
                # Se organizou algo, espera um pouco e repete
                time.sleep(0.5)
            else:
                # Se não fez nada (nem loot, nem stack), descansa
                time.sleep(1.0)
                
        except Exception as e:
            print(f"Erro Loot/Stack: {e}")
            time.sleep(1)

def update_fisher_hud(data_list):
    """
    Recebe uma lista de dados para desenhar no HUD.
    Formato esperado: [{'dx': int, 'dy': int, 'color': str, 'text': str|None}, ...]
    """
    global hud_overlay_data
    hud_overlay_data = data_list if data_list else []

def auto_fisher_thread():
    """
    Gerencia o ciclo de vida do Pescador.
    """
    hwnd = 0
    
    # Função lambda para o fisher saber se deve continuar
    # Ele só roda se o Bot estiver ligado, Conectado e o Switch estiver ATIVO
    def should_fish():
        return bot_running and is_connected and switch_fisher.get() and is_safe_to_bot

    while bot_running:
        # if is_paused_global: 
        #     time.sleep(0.5)
        #     continue
        
        # Verificações de estado
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
                         max_attempts_range=current_range) # <--- Passa aqui
            
            time.sleep(1)
            
        except Exception as e:
            print(f"Erro Fisher Thread: {e}")
            time.sleep(5)

def runemaker_thread():
    hwnd = 0
    
    def should_run():
        # IMPORTANTE: Removemos 'is_safe_to_bot' daqui.
        # O Runemaker PRECISA rodar mesmo quando 'is_safe_to_bot' for False,
        # para que ele possa executar a lógica de fuga (HIDING).
        return bot_running and is_connected and switch_runemaker.get()
    
    def check_safety():
        # Essa função será chamada de dentro do loop para saber se tem perigo
        return is_safe_to_bot

    def check_gm():
        return is_gm_detected
    
    def check_hunger_state():
        # 1. TRAVA ABSOLUTA: Se não sincronizou (não sabe o regen), não come.
        if not global_is_synced:
            return False
            
        # 2. Se está cheio, não come
        if global_is_full:
            return False

        # 3. Se estiver faminto OU tempo de refgen baixo, come
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
                # Passamos as coordenadas globais atuais
                'work_pos': BOT_SETTINGS['rune_work_pos'],
                'safe_pos': BOT_SETTINGS['rune_safe_pos'],
                'return_delay': BOT_SETTINGS['rune_return_delay'],
                'flee_delay': BOT_SETTINGS['rune_flee_delay'],
                'auto_eat': BOT_SETTINGS['auto_eat'], # Variável do switch
                'check_hunger': check_hunger_state, # Função de callback
                'mana_train': BOT_SETTINGS['mana_train'],
            }
            
            runemaker_loop(pm, base_addr, hwnd, 
                           check_running=should_run, 
                           config=cfg,
                           is_safe_callback=check_safety,
                           is_gm_callback=check_gm,
                           log_callback=log,
                           eat_callback=on_eat_callback) # <--- Callback conectado
            
            time.sleep(1)
        except Exception as e:
            print(f"Erro Runemaker: {e}")
            time.sleep(5)

def save_config_file():
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            # Salva o dicionário inteiro direto!
            json.dump(BOT_SETTINGS, f, indent=4)
        print(f"[CONFIG] Salvo com sucesso.")
    except Exception as e:
        print(f"[CONFIG] Erro ao salvar: {e}")

def open_settings():
    global toplevel_settings, lbl_status
    
    # Traz para frente se já estiver aberta
    if toplevel_settings is not None and toplevel_settings.winfo_exists():
        toplevel_settings.lift()
        toplevel_settings.focus()
        return

    # Criação da Janela
    toplevel_settings = ctk.CTkToplevel(app)
    toplevel_settings.title("Configurações")
    toplevel_settings.geometry("320x520") # Um pouco mais alta para caber tudo confortavelmente
    toplevel_settings.attributes("-topmost", True)
    
    # Protocolo de Fechamento
    def on_settings_close():
        global lbl_status
        toplevel_settings.destroy()
        
    toplevel_settings.protocol("WM_DELETE_WINDOW", on_settings_close)

    # --- SISTEMA DE ABAS (6 ABAS) ---
    tabview = ctk.CTkTabview(toplevel_settings)
    tabview.pack(fill="both", expand=True, padx=10, pady=10)
    
    tab_geral  = tabview.add("Geral")
    tab_alarm  = tabview.add("Alarme")
    tab_alvos  = tabview.add("Alvos") # Antiga Listas
    tab_loot   = tabview.add("Loot")
    tab_fisher = tabview.add("Fisher")
    tab_rune   = tabview.add("Rune")

    # Helper para criar Grids bonitos (Padronização)
    def create_grid_frame(parent):
        f = ctk.CTkFrame(parent, fg_color="transparent")
        f.pack(pady=10, fill="x")
        f.grid_columnconfigure(0, weight=1) # Coluna Label (Direita)
        f.grid_columnconfigure(1, weight=2) # Coluna Input (Esquerda)
        return f

    # ==========================================================================
    # 1. ABA GERAL
    # ==========================================================================
    frame_geral = create_grid_frame(tab_geral)
    
    # Vocação
    ctk.CTkLabel(frame_geral, text="Vocação (Regen):", text_color="gray").grid(row=0, column=0, sticky="e", padx=10, pady=5)
    combo_voc = ctk.CTkComboBox(frame_geral, values=list(VOCATION_REGEN.keys()), width=150, state="readonly")
    combo_voc.grid(row=0, column=1, sticky="w")
    combo_voc.set(BOT_SETTINGS['vocation'])

    # Telegram
    ctk.CTkLabel(frame_geral, text="Telegram Chat ID:", text_color="gray").grid(row=1, column=0, sticky="e", padx=10, pady=5)
    entry_telegram = ctk.CTkEntry(frame_geral, width=150)
    entry_telegram.grid(row=1, column=1, sticky="w")
    entry_telegram.insert(0, str(BOT_SETTINGS['telegram_chat_id']))
    
    # UX: Dica Telegram
    ctk.CTkLabel(frame_geral, text="↳ Recebe alertas de PK e Pausa no celular.", 
                 font=("Verdana", 8), text_color="#666").grid(row=2, column=0, columnspan=2, sticky="e", padx=60, pady=(0, 5))

    # Switches
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

    # UX: Explicação Ignorar
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
        save_config_file()
        log(f"⚙️ Geral salvo.")

    ctk.CTkButton(tab_geral, text="Salvar Geral", command=save_geral, fg_color="#2CC985").pack(side="bottom", pady=10, fill="x", padx=20)

    # ==========================================================================
    # 2. ABA ALARME
    # ==========================================================================
    frame_alarm = create_grid_frame(tab_alarm)

    # Distância
    ctk.CTkLabel(frame_alarm, text="Distância (SQM):", text_color="gray").grid(row=0, column=0, sticky="e", padx=10, pady=5)
    dist_vals = ["1 SQM", "3 SQM", "5 SQM", "8 SQM (Padrão)", "Tela Toda"]
    combo_alarm = ctk.CTkComboBox(frame_alarm, values=dist_vals, width=150, state="readonly")
    combo_alarm.grid(row=0, column=1, sticky="w")
    
    curr_vis = "Tela Toda" if BOT_SETTINGS['alarm_range'] >= 15 else f"{BOT_SETTINGS['alarm_range']} SQM" if BOT_SETTINGS['alarm_range'] in [1,3,5] else "8 SQM (Padrão)"
    combo_alarm.set(curr_vis)

    # UX: Hint Distância
    ctk.CTkLabel(frame_alarm, text="↳ Raio de detecção ao redor do personagem.", 
                 font=("Verdana", 8), text_color="#777").grid(row=1, column=0, columnspan=2, sticky="w", padx=40, pady=(0, 5))

    # Andares
    ctk.CTkLabel(frame_alarm, text="Monitorar Andares:", text_color="gray").grid(row=2, column=0, sticky="e", padx=10, pady=5)
    combo_floor = ctk.CTkComboBox(frame_alarm, values=["Padrão", "Superior (+1)", "Inferior (-1)", "Todos (Raio-X)"], width=150, state="readonly")
    combo_floor.grid(row=2, column=1, sticky="w")
    combo_floor.set(BOT_SETTINGS['alarm_floor'])

    # UX: Aviso Safe List (No rodapé da aba, antes do botão salvar)
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

    # ==========================================================================
    # 3. ABA ALVOS (LISTAS)
    # ==========================================================================
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

    # ==========================================================================
    # 4. ABA LOOT (Esta estava faltando!)
    # ==========================================================================
    # frame_loot = create_grid_frame(tab_loot)

    # ctk.CTkLabel(frame_loot, text="Quantas BPs são suas?", text_color="gray").grid(row=0, column=0, sticky="e", padx=10, pady=(5,0))
    # entry_cont_count = ctk.CTkEntry(frame_loot, width=50, justify="center")
    # entry_cont_count.grid(row=1, column=0, sticky="w")
    # entry_cont_count.insert(0, str(loot_containers_count))

    # ctk.CTkLabel(frame_loot, text="(O resto será considerado Corpo).", 
    #              font=("Verdana", 9), text_color="gray").grid(row=, sticky="e", padx=(10,0), pady=(0,5), column=0)
    
    # ctk.CTkLabel(frame_loot, text="Índice da BP de Destino:", text_color="gray").grid(row=2, column=0, sticky="e", padx=10, pady=(5,0))
    # entry_dest_idx = ctk.CTkEntry(frame_loot, width=50, justify="center")
    # entry_dest_idx.grid(row=2, column=1, sticky="w")
    # entry_dest_idx.insert(0, str(loot_dest_index))

    # ctk.CTkLabel(frame_loot, text="(0 = Primeira BP, 1 = Segunda...).", 
    #              font=("Verdana", 9), text_color="gray").grid(row=3, column=0, sticky="e", padx=10, pady=5)
    
    ctk.CTkLabel(tab_loot, text="Quantas BPs são suas?", text_color="gray", font=("Verdana", 10)).pack()
    # Spinbox ou Entry para número
    entry_cont_count = ctk.CTkEntry(tab_loot, width=50)
    entry_cont_count.pack(pady=5)
    entry_cont_count.insert(0, str(BOT_SETTINGS['loot_containers'])) # Valor atual
    
    ctk.CTkLabel(tab_loot, text="(O resto será considerado Corpo)", font=("Verdana", 9), text_color="#555555").pack(pady=(0, 10))

    # 2. Destino do Loot
    ctk.CTkLabel(tab_loot, text="Índice da BP de Destino:", text_color="gray", font=("Verdana", 10)).pack()
    entry_dest_idx = ctk.CTkEntry(tab_loot, width=50)
    entry_dest_idx.pack(pady=5)
    entry_dest_idx.insert(0, str(BOT_SETTINGS['loot_dest'])) # Valor atual
    
    ctk.CTkLabel(tab_loot, text="(0 = Primeira BP, 1 = Segunda...)", font=("Verdana", 9), text_color="#555555").pack(pady=(0, 20))

    # ctk.CTkLabel(tab_loot, text="* BPs Pessoais: Quantas mochilas são suas.\n* Índice Destino: 0 = Primeira BP, 1 = Segunda...", 
    #              font=("Verdana", 9), text_color="gray").pack(pady=10)
    
    #     # 1. Meus Containers


    def save_loot():
        try:
            BOT_SETTINGS['loot_containers'] = int(entry_cont_count.get())
            BOT_SETTINGS['loot_dest'] = int(entry_dest_idx.get())
            save_config_file()
            log(f"💰 Loot salvo: {BOT_SETTINGS['loot_containers']} BPs | Dest: {BOT_SETTINGS['loot_dest']}")
        except: log("❌ Use números inteiros.")

    ctk.CTkButton(tab_loot, text="Salvar Loot", command=save_loot, fg_color="#2CC985").pack(side="bottom", pady=10, fill="x", padx=20)

    # ==========================================================================
    # 5. ABA FISHER (Esta estava faltando!)
    # ==========================================================================
    frame_fish = create_grid_frame(tab_fisher)

    ctk.CTkLabel(frame_fish, text="Min Tentativas:", text_color="gray").grid(row=0, column=0, sticky="e", padx=10, pady=5)
    entry_fish_min = ctk.CTkEntry(frame_fish, width=50, justify="center")
    entry_fish_min.grid(row=0, column=1, sticky="w")
    entry_fish_min.insert(0, str(BOT_SETTINGS['fisher_min']))

    ctk.CTkLabel(frame_fish, text="Max Tentativas:", text_color="gray").grid(row=1, column=0, sticky="e", padx=10, pady=5)
    entry_fish_max = ctk.CTkEntry(frame_fish, width=50, justify="center")
    entry_fish_max.grid(row=1, column=1, sticky="w")
    entry_fish_max.insert(0, str(BOT_SETTINGS['fisher_max']))

    # UX: Explicação Fisher
    lbl_hint_fish = ctk.CTkLabel(frame_fish, text="↳ O bot escolherá um número aleatório entre Min e Max\n para pescar em cada quadrado.", 
                                 font=("Verdana", 8), text_color="#777", justify="left")
    lbl_hint_fish.grid(row=2, column=0, columnspan=2, sticky="w", padx=(20,0), pady=(0,5))

    def save_fish():
        try:
            mn = int(entry_fish_min.get())
            mx = int(entry_fish_max.get())
            if mn < 1: mn=1
            if mx < mn: mx=mn
            BOT_SETTINGS['fisher_min'] = mn
            BOT_SETTINGS['fisher_max'] = mx
            save_config_file()
            log(f"🎣 Fisher salvo: {mn} a {mx}")
        except: log("❌ Use números inteiros.")

    ctk.CTkButton(tab_fisher, text="Salvar Fisher", command=save_fish, fg_color="#2CC985").pack(side="bottom", pady=10, fill="x", padx=20)

    # ==========================================================================
    # 6. ABA RUNE
    # ==========================================================================
    frame_rune = create_grid_frame(tab_rune)

    # Mana
    ctk.CTkLabel(frame_rune, text="Mana Req:", text_color="gray").grid(row=0, column=0, sticky="e", padx=10, pady=5)
    entry_mana = ctk.CTkEntry(frame_rune, width=60, justify="center")
    entry_mana.grid(row=0, column=1, sticky="w")
    entry_mana.insert(0, str(BOT_SETTINGS['rune_mana']))

    # Hotkey
    ctk.CTkLabel(frame_rune, text="Hotkey:", text_color="gray").grid(row=1, column=0, sticky="e", padx=10, pady=5)
    entry_hk = ctk.CTkEntry(frame_rune, width=60, justify="center")
    entry_hk.grid(row=1, column=1, sticky="w")
    entry_hk.insert(0, BOT_SETTINGS['rune_hotkey'])

    # Mão
    ctk.CTkLabel(frame_rune, text="Mão:", text_color="gray").grid(row=2, column=0, sticky="e", padx=10, pady=5)
    combo_hand = ctk.CTkComboBox(frame_rune, values=["RIGHT", "LEFT", "BOTH"], width=80, state="readonly")
    combo_hand.grid(row=2, column=1, sticky="w")
    combo_hand.set(BOT_SETTINGS['rune_hand'])

    # --- LINHA 4: OPÇÕES EXTRAS (Auto Eat e Mana Train) ---
    # Vamos criar um frame para agrupar os switches
    frame_rune_opts = ctk.CTkFrame(tab_rune, fg_color="transparent")
    frame_rune_opts.pack(pady=10)

    # Switch Auto Eat (Já existia, mova para cá)
    def toggle_eat():
        BOT_SETTINGS['auto_eat'] = bool(switch_eat.get())
        
    switch_eat = ctk.CTkSwitch(frame_rune_opts, text="Auto Eat", command=toggle_eat, progress_color="#00C000", font=("Verdana", 10))
    switch_eat.pack(side="left", padx=10)
    if BOT_SETTINGS['auto_eat']: switch_eat.select()

    # Switch Mana Train (NOVO)
    def toggle_train():
        BOT_SETTINGS['mana_train'] = bool(switch_train.get())
        
    switch_train = ctk.CTkSwitch(frame_rune_opts, text="Mana Train Only (No Runes)", command=toggle_train, progress_color="#A54EF9", font=("Verdana", 10))
    switch_train.pack(side="left", padx=10)
    if BOT_SETTINGS['mana_train']: switch_train.select()

    # Divisória Segurança
    ctk.CTkLabel(tab_rune, text="Segurança (Anti-PK)", font=("Verdana", 10, "bold")).pack(pady=(0, 0))
    
    frame_rune_safe = create_grid_frame(tab_rune)

    # --- Delay de Fuga (Reaction Time) ---
    ctk.CTkLabel(frame_rune_safe, text="Delay Fuga (s):", text_color="gray").grid(row=0, column=0, sticky="e", padx=10)
    
    entry_flee = ctk.CTkEntry(frame_rune_safe, width=50, justify="center")
    entry_flee.grid(row=0, column=1, sticky="w")
    entry_flee.insert(0, str(BOT_SETTINGS['rune_flee_delay']))
    
    # UX: Explicação Fuga
    lbl_hint_flee = ctk.CTkLabel(frame_rune_safe, text="↳ Tempo de reação simulado antes de correr (Humanização).", 
                                 font=("Verdana", 8), text_color="#888888")
    lbl_hint_flee.grid(row=1, column=0, columnspan=2, sticky="w", padx=20, pady=(0, 5))

    # --- Delay de Retorno (Cooldown) ---
    ctk.CTkLabel(frame_rune_safe, text="Delay Retorno (s):", text_color="gray").grid(row=2, column=0, sticky="e", padx=10)
    
    entry_ret_delay = ctk.CTkEntry(frame_rune_safe, width=50, justify="center")
    entry_ret_delay.grid(row=2, column=1, sticky="w")
    entry_ret_delay.insert(0, str(BOT_SETTINGS['rune_return_delay']))

    # UX: Explicação Retorno
    lbl_hint_ret = ctk.CTkLabel(frame_rune_safe, text="↳ Tempo esperando no Safe Spot após o perigo sumir.", 
                                font=("Verdana", 8), text_color="#888888")
    lbl_hint_ret.grid(row=3, column=0, columnspan=2, sticky="w", padx=20)

    # Posições
    frame_pos = ctk.CTkFrame(tab_rune, fg_color="transparent")
    frame_pos.pack(pady=0)
    
    lbl_work_pos = ctk.CTkLabel(frame_pos, text=f"Work: {BOT_SETTINGS['rune_work_pos']}", font=("Verdana", 9))
    lbl_work_pos.grid(row=0, column=0, padx=5)
    lbl_safe_pos = ctk.CTkLabel(frame_pos, text=f"Safe: {BOT_SETTINGS['rune_safe_pos']}", font=("Verdana", 9))
    lbl_safe_pos.grid(row=0, column=1, padx=5)

    def set_pos(tipo):
        try:
            x, y, z = get_player_pos(pm, base_addr)
            if x == 0: return
            
            if tipo == "WORK":
                BOT_SETTINGS['rune_work_pos'] = (x, y, z)
                lbl_work_pos.configure(text=f"Work: {x},{y},{z}")
            else:
                BOT_SETTINGS['rune_safe_pos'] = (x, y, z)
                lbl_safe_pos.configure(text=f"Safe: {x},{y},{z}")
            save_config_file()
        except: pass

    ctk.CTkButton(frame_pos, text="Set Work", command=lambda: set_pos("WORK"), width=70, height=25, fg_color="#404040").grid(row=1, column=0, padx=5, pady=2)
    ctk.CTkButton(frame_pos, text="Set Safe", command=lambda: set_pos("SAFE"), width=70, height=25, fg_color="#404040").grid(row=1, column=1, padx=5, pady=2)

    def save_rune():
        try:
            BOT_SETTINGS['rune_mana'] = int(entry_mana.get())
            BOT_SETTINGS['rune_hotkey'] = entry_hk.get().upper()
            BOT_SETTINGS['rune_hand'] = combo_hand.get()
            BOT_SETTINGS['rune_return_delay'] = int(entry_ret_delay.get())
            BOT_SETTINGS['rune_flee_delay'] = float(entry_flee.get())
            save_config_file()
            log("🔮 Rune Config salva!")
        except: log("❌ Erro valores Rune.")

    ctk.CTkButton(tab_rune, text="Salvar Rune", command=save_rune, fg_color="#2CC985").pack(side="bottom", pady=10, fill="x", padx=20)
    
    # Botão Fechar Janela
    ctk.CTkButton(toplevel_settings, text="Fechar", command=on_settings_close, 
                  fg_color="#202020", border_width=1, border_color="#404040", height=25).pack(side="bottom", pady=10)

def toggle_graph():
    global is_graph_visible
    if is_graph_visible:
        # ESCONDER
        frame_graph.pack_forget() # Remove o gráfico do container
        
        btn_graph.configure(text="Mostrar Gráfico 📈")
        app.geometry("320x450") # Volta ao tamanho compacto
        is_graph_visible = False
    else:
        # MOSTRARd
        # side="top", fill="both", expand=True
        # Como o botão está em 'bottom' e as abas em 'top', 
        # o gráfico vai preencher o espaço entre eles.
        frame_graph.pack(side="top", fill="both", expand=True, pady=(0, 5))
        
        btn_graph.configure(text="Esconder Gráfico 📉")
        app.geometry("320x560") # Aumenta a janela para caber o container expandido
        is_graph_visible = True

xray_window = None
hud_overlay_data = [] # Lista de dicionários: {'dx': 0, 'dy': 0, 'color': '#Red', 'text': '10m'}

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
    
    canvas = ctk.CTkCanvas(xray_window, bg="black", highlightthickness=0)
    canvas.pack(fill="both", expand=True)
    
    def update_xray():
        if not xray_window or not xray_window.winfo_exists(): return
        
        try:
            hwnd = win32gui.FindWindow("TibiaClient", None) or win32gui.FindWindow(None, "Tibia")
            
            # Checagem de Foco
            active_hwnd = win32gui.GetForegroundWindow()
            if hwnd and active_hwnd != hwnd:
                canvas.delete("all")
                xray_window.after(100, update_xray)
                return
            
            if hwnd:
                # 1. Pega Geometria da Janela (Com bordas)
                rect = win32gui.GetWindowRect(hwnd) 
                win_x, win_y = rect[0], rect[1]
                
                # 2. Pega Geometria do Conteúdo (Sem bordas) em relação à tela
                client_point = win32gui.ClientToScreen(hwnd, (0, 0))
                client_x, client_y = client_point

                # 3. Calcula a "Grossura" das bordas/barra de título
                offset_x = client_x - win_x
                offset_y = client_y - win_y

                # Posiciona o Overlay sobre a janela inteira
                w = rect[2] - rect[0]
                h = rect[3] - rect[1]
                xray_window.geometry(f"{w}x{h}+{rect[0]}+{rect[1]}")
                
                canvas.delete("all")
                
                if pm is not None:
                    gv = get_game_view(pm, base_addr)
                    my_x, my_y, my_z = get_player_pos(pm, base_addr)
                    
                    # ---------------- HUD FISHER ----------------
                    if hud_overlay_data and gv:
                        for item in hud_overlay_data:
                            dx = item.get('dx')
                            dy = item.get('dy')
                            color = item.get('color', '#FFFFFF')
                            text = item.get('text', '') # Texto do Timer (Ex: "10m")
                            
                            # Coordenada 'crua' da memória (Area do Cliente)
                            raw_cx = gv['center'][0] + (dx * gv['sqm'])
                            raw_cy = gv['center'][1] + (dy * gv['sqm'])
                            
                            # --- APLICA A CORREÇÃO DE OFFSET ---
                            cx = raw_cx + offset_x
                            cy = raw_cy + offset_y
                            # -----------------------------------

                            size = gv['sqm'] / 2 
                            
                            # Desenha o Quadrado (Box)
                            canvas.create_rectangle(cx - size, cy - size, cx + size, cy + size, 
                                                  outline=color, width=2)
                            
                            # Lógica de Texto:
                            if text:
                                # Se tem timer, desenha centralizado com sombra preta
                                canvas.create_text(cx+1, cy+1, text=text, fill="black", font=("Verdana", 8, "bold"))
                                canvas.create_text(cx, cy, text=text, fill=color, font=("Verdana", 8, "bold"))
                            else:
                                # Se NÃO tem texto, desenha a coordenada (Cursor Ativo)
                                canvas.create_text(cx, cy - size - 12, text=f"FISHER\n({dx}, {dy})", 
                                                 fill=color, font=("Verdana", 7, "bold"))

                    # ---------------- X-RAY CRIATURAS ----------------
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
                                        
                                        # --- APLICA A CORREÇÃO DE OFFSET AQUI TAMBÉM ---
                                        sx = raw_sx + offset_x
                                        sy = raw_sy + offset_y
                                        # -----------------------------------------------
                                        
                                        color = COLOR_FLOOR_ABOVE if cz < my_z else COLOR_FLOOR_BELOW
                                        tag = "▲" if cz < my_z else "▼"
                                        zdiff = my_z - cz
                                        
                                        canvas.create_text(sx, sy - 40, text=f"{tag} {zdiff}\n{name}", fill=color, font=("Verdana", 10, "bold"))
                                        canvas.create_rectangle(sx-20, sy-20, sx+20, sy+20, outline=color, width=2)
        except: pass
        
        xray_window.after(50, update_xray)
        
    update_xray()

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
                    # Processo não encontrado
                    is_connected = False
                    lbl_connection.configure(text="Cliente Fechado ❌", text_color="#FF5555")
                    time.sleep(2)
                    continue

            # 2. Se o processo existe, verifica se está LOGADO
            # Tenta ler o status de conexão
            try:
                status = pm.read_int(base_addr + OFFSET_CONNECTION)
                
                if status == 8: # 8 geralmente é "In Game" nas versões antigas
                    if not is_connected:
                        log("🟢 Conectado ao mundo!")
                        # --- REAPLICA FULL LIGHT SE ESTIVER ATIVO ---
                        if full_light_enabled:
                            time.sleep(1) # Espera memória estabilizar
                            apply_full_light(True)
                        # --------------------------------------------
                    is_connected = True
                    was_connected_once = True
                    lbl_connection.configure(text="Conectado 🟢", text_color="#00FF00")
                else:
                    is_connected = False
                    lbl_connection.configure(text="Desconectado ⚠️", text_color="#FFFF00")
                    
            except Exception:
                # Se der erro ao ler (ex: cliente fechou abruptamente), reseta o pm
                pm = None
                is_connected = False
                if was_connected_once:
                    os._exit(0) # Mata o bot
                lbl_connection.configure(text="Cliente Fechado ❌", text_color="#FF5555")

        except Exception as e:
            print(f"Erro Watchdog: {e}")
        
        time.sleep(1)

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

#----------------------------------------------------------#

############################################################
#######                    GUI                    ##########
############################################################

monitor = TrainingMonitor(log_callback=log)
sword_tracker = SkillTracker("Sword")
shield_tracker = SkillTracker("Shield")
magic_tracker = SkillTracker("Magic") # <--- NOVO
exp_tracker = ExpTracker()

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")
app = ctk.CTk()
app.title("Molodoy Bot Pro")
app.geometry("320x450") 
app.resizable(True, True)
app.configure(fg_color="#202020")
try:
    app.iconbitmap("app.ico")
except:
    pass # Se não achar o ícone, usa o padrão

############################################################
####                    MAIN FRAME                  ########
############################################################

main_frame = ctk.CTkFrame(app, fg_color="transparent")
main_frame.pack(fill="both", expand=True)

############################################################
####                    HEADER                      ########
############################################################

frame_header = ctk.CTkFrame(main_frame, fg_color="transparent")
frame_header.pack(pady=(10, 5), fill="x", padx=10)

# BOTÃO XRAY (DIREITA)
btn_xray = ctk.CTkButton(frame_header, text="Raio-X", command=toggle_xray, width=25, height=25, fg_color="#303030", font=("Verdana", 10))
btn_xray.pack(side="right", padx=5)

# Botão Config (Mais curto)
btn_settings = ctk.CTkButton(frame_header, text="⚙️ Config.", command=open_settings, 
                             width=100, height=30, fg_color="#303030", hover_color="#505050",
                             font=("Verdana", 11, "bold"))
btn_settings.pack(side="left")

# Status Conexão (Apenas Conexão agora)
lbl_connection = ctk.CTkLabel(frame_header, text="🔌 Procurando...", 
                              font=("Verdana", 11, "bold"), text_color="#FFA500")
lbl_connection.pack(side="right", padx=5)

############################################################
####                CONTROLES (TOGGLE)              ########
############################################################

frame_controls = ctk.CTkFrame(main_frame, fg_color="#303030")
frame_controls.pack(padx=10, pady=5, fill="x")

frame_controls.grid_columnconfigure(0, weight=1)
frame_controls.grid_columnconfigure(1, weight=1)

switch_trainer = ctk.CTkSwitch(frame_controls, text="Trainer", progress_color="#00C000", font=("Verdana", 11))
switch_trainer.grid(row=0, column=0, sticky="w", padx=(20, 0), pady=5)

switch_loot = ctk.CTkSwitch(frame_controls, text="Auto Loot", progress_color="#00C000", font=("Verdana", 11))
switch_loot.grid(row=1, column=0, sticky="w", padx=(20, 0), pady=5)

def on_fisher_toggle():
    """Limpa o HUD visual imediatamente ao desligar o Fisher."""
    if not switch_fisher.get():
        # Se desligou, limpa a variável global do HUD
        update_fisher_hud([])

switch_alarm = ctk.CTkSwitch(frame_controls, text="Alarm", progress_color="#00C000", font=("Verdana", 11))
switch_alarm.grid(row=0, column=1, sticky="w", padx=(10, 0), pady=5)

switch_fisher = ctk.CTkSwitch(frame_controls, text="Auto Fisher", command=on_fisher_toggle, progress_color="#00C000", font=("Verdana", 11))
switch_fisher.grid(row=1, column=1, sticky="w", padx=(10, 0), pady=5)

# Exemplo: Colocando abaixo do Auto Loot
switch_runemaker = ctk.CTkSwitch(frame_controls, text="Runemaker", progress_color="#A54EF9", font=("Verdana", 11))
switch_runemaker.grid(row=2, column=0, sticky="w", padx=(20, 0), pady=5)

############################################################
#######                    STATS                    ########
############################################################

frame_stats = ctk.CTkFrame(main_frame, fg_color="transparent", border_color="#303030", border_width=1, corner_radius=6)
frame_stats.pack(padx=10, pady=5, fill="x")

# Configura Grid: 2 Colunas
# Coluna 0: Auto-ajustável (Conteúdo)
# Coluna 1: Expansível (Empurra o conteúdo para a direita)
frame_stats.grid_columnconfigure(1, weight=1)

# LINHA 2 EXP
frame_exp_det = ctk.CTkFrame(frame_stats, fg_color="transparent")
frame_exp_det.grid(row=2, column=1, sticky="e", padx=10)
lbl_exp_rate = ctk.CTkLabel(frame_exp_det, text="-- xp/h", font=("Verdana", 10), text_color="gray")
lbl_exp_rate.pack(side="left", padx=5)
lbl_exp_eta = ctk.CTkLabel(frame_exp_det, text="ETA: --", font=("Verdana", 10), text_color="gray")
lbl_exp_eta.pack(side="left")

# Divisória
frame_div = ctk.CTkFrame(frame_stats, height=1, fg_color="#303030")
frame_div.grid(row=1, column=0, columnspan=2, sticky="ew", padx=10, pady=(0, 5))

# LINHA 2 REGEN
lbl_regen = ctk.CTkLabel(frame_stats, text="🍖 --:--", font=("Verdana", 11, "bold"), text_color="gray")
lbl_regen.grid(row=2, column=0, padx=10, pady=2, sticky="w")

# --- LINHA 3: SWORD (Agrupado) ---
# Container para juntar "Sword:" e o Valor na mesma célula
box_sword = ctk.CTkFrame(frame_stats, fg_color="transparent")
box_sword.grid(row=3, column=0, padx=10, sticky="w")

ctk.CTkLabel(box_sword, text="Sword:", font=("Verdana", 11)).pack(side="left")
lbl_sword_val = ctk.CTkLabel(box_sword, text="--", font=("Verdana", 11, "bold"), text_color="#4EA5F9")
lbl_sword_val.pack(side="left", padx=(5, 0)) # padx=5 separa o titulo do valor

# LINHA 3 : SWORD Detalhes (Direita)
frame_sw_det = ctk.CTkFrame(frame_stats, fg_color="transparent")
frame_sw_det.grid(row=3, column=1, padx=10, sticky="e")
lbl_sword_rate = ctk.CTkLabel(frame_sw_det, text="--m/%", font=("Verdana", 10), text_color="gray")
lbl_sword_rate.pack(side="left", padx=5)
lbl_sword_time = ctk.CTkLabel(frame_sw_det, text="ETA: --", font=("Verdana", 10), text_color="gray")
lbl_sword_time.pack(side="left")

# --- LINHA 4: SHIELD (Agrupado) ---
box_shield = ctk.CTkFrame(frame_stats, fg_color="transparent")
box_shield.grid(row=4, column=0, padx=10, sticky="w")

ctk.CTkLabel(box_shield, text="Shield:", font=("Verdana", 11)).pack(side="left")
lbl_shield_val = ctk.CTkLabel(box_shield, text="--", font=("Verdana", 11, "bold"), text_color="#4EA5F9")
lbl_shield_val.pack(side="left", padx=(5, 0))

# LINHA 4 : SHIELD Detalhes (Direita)
frame_sh_det = ctk.CTkFrame(frame_stats, fg_color="transparent")
frame_sh_det.grid(row=4, column=1, padx=10, sticky="e")
lbl_shield_rate = ctk.CTkLabel(frame_sh_det, text="--m/%", font=("Verdana", 10), text_color="gray")
lbl_shield_rate.pack(side="left", padx=5)
lbl_shield_time = ctk.CTkLabel(frame_sh_det, text="ETA: --", font=("Verdana", 10), text_color="gray")
lbl_shield_time.pack(side="left")

# --- LINHA 5: MAGIC (Agrupado) ---
box_magic = ctk.CTkFrame(frame_stats, fg_color="transparent")
box_magic.grid(row=5, column=0, padx=10, sticky="w")

ctk.CTkLabel(box_magic, text="Magic:", font=("Verdana", 11)).pack(side="left")
lbl_magic_val = ctk.CTkLabel(box_magic, text="--", font=("Verdana", 11, "bold"), text_color="#A54EF9") # Roxo para diferenciar
lbl_magic_val.pack(side="left", padx=(5, 0))

# --- LINHA 5: MAGIC DETALHES  ---
frame_ml_det = ctk.CTkFrame(frame_stats, fg_color="transparent")
frame_ml_det.grid(row=5, column=1, padx=10, sticky="e")

lbl_magic_rate = ctk.CTkLabel(frame_ml_det, text="--m/%", font=("Verdana", 10), text_color="gray")
lbl_magic_rate.pack(side="left", padx=5)

lbl_magic_time = ctk.CTkLabel(frame_ml_det, text="ETA: --", font=("Verdana", 10), text_color="gray")
lbl_magic_time.pack(side="left")

############################################################
#######                    GRAPH                    ########
############################################################

# 1. CONTAINER MESTRE
frame_graphs_container = ctk.CTkFrame(main_frame, fg_color="transparent", 
                                      border_width=0, border_color="#303030", 
                                      corner_radius=0)
frame_graphs_container.pack(padx=10, pady=(5, 0), fill="x")

# 2. Abas (Topo do Container)
# tab_graphs = ctk.CTkTabview(frame_graphs_container, height=70, 
#                             fg_color="#2B2B2B", border_width=1, corner_radius=6)
# tab_graphs.pack(side="top", fill="x", padx=2, pady=0)

# tab_graphs.add("Skills")
# tab_graphs.add("Exp")
# tab_graphs.set("Skills")

# 3. Botão (Rodapé do Container)
# Usamos side="bottom" para garantir que ele fique sempre no fim da caixa
btn_graph = ctk.CTkButton(frame_graphs_container, text="Mostrar Gráfico 📈", command=toggle_graph, 
                          fg_color="#202020", hover_color="#303030", 
                          height=25, corner_radius=6, border_width=0)
btn_graph.pack(side="top", fill="x", padx=1, pady=0)

# 4. Frame do Gráfico (Recheio do Container)
# Note que o master agora é 'frame_graphs_container', não 'main_frame'
frame_graph = ctk.CTkFrame(frame_graphs_container, fg_color="transparent", corner_radius=6)

# Configuração do Matplotlib (Tema Escuro)
plt.style.use('dark_background')
fig, ax = plt.subplots(figsize=(4, 1.6), dpi=100, facecolor='#2B2B2B')
fig.patch.set_facecolor('#202020') # Cor de fundo igual ao App
#fig.subplots_adjust(bottom=0.15, top=0.85)
ax.set_facecolor('#202020')

# Ajustes visuais do gráfico
ax.tick_params(axis='x', colors='gray', labelsize=6, pad=2)
ax.tick_params(axis='y', colors='gray', labelsize=6, pad=2)    
ax.spines['top'].set_visible(False)
ax.spines['right'].set_visible(False)
ax.spines['bottom'].set_color('#404040')
ax.spines['left'].set_color('#404040')
ax.set_title("Eficiencia de Treino (%)", fontsize=8, color="gray")

# Canvas que conecta o Matplotlib ao Tkinter
canvas = FigureCanvasTkAgg(fig, master=frame_graph)
widget = canvas.get_tk_widget()
widget.pack(fill="both", expand=True, padx=1, pady=2)


############################################################
#######                  LOG                        ########
############################################################

txt_log = ctk.CTkTextbox(main_frame, height=80, font=("Consolas", 11), fg_color="#151515", text_color="#00FF00", border_width=1)
txt_log.pack(pady=5, fill="both", expand=True)

app.after(1000, attach_window)

############################################################
#######                    THREADS                  ########
############################################################

threading.Thread(target=trainer_loop, daemon=True).start()
threading.Thread(target=alarm_loop, daemon=True).start()
threading.Thread(target=auto_loot_thread, daemon=True).start()
threading.Thread(target=skill_monitor_loop, daemon=True).start()
threading.Thread(target=gui_updater_loop, daemon=True).start()
threading.Thread(target=regen_monitor_loop, daemon=True).start()
threading.Thread(target=auto_fisher_thread, daemon=True).start()
threading.Thread(target=runemaker_thread, daemon=True).start()
threading.Thread(target=connection_watchdog, daemon=True).start()
log("🚀 Iniciado.")


def on_close():
    global bot_running
    print("Encerrando bot e threads...")
    bot_running = False 
    
    # 1. Tenta destruir a janela visualmente
    try:
        if app:
            app.quit()
            app.destroy()
    except: pass
    
    # 2. O SEGREDO: Hard Kill do Processo
    # sys.exit(0) # <-- Isso é fraco
    import os
    os._exit(0)   # <-- Isso mata o processo imediatamente no Windows

# Conecta o botão "X" da janela à função acima
app.protocol("WM_DELETE_WINDOW", on_close)
app.mainloop()
bot_running = False