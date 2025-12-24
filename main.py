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
from utils.timing import gauss_wait
from datetime import datetime
from PIL import Image # Import necessário para imagens
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import matplotlib
matplotlib.use("TkAgg") # Define o backend para funcionar com Tkinter
import sys
import traceback
import ctypes
import tkinter as tk
from tkinter import filedialog # Para salvar/abrir arquivos
from pathlib import Path

# arquivos do bot
from config import *
import config
from utils.monitor import *
from modules.auto_loot import *
from modules.fisher import fishing_loop # Vamos usar essa função principal
from modules.runemaker import runemaker_loop
from core.mouse_lock import acquire_mouse, release_mouse
from core.map_core import get_game_view, get_screen_coord, get_player_pos
from core.input_core import ctrl_right_click_at
from core import packet
from database import foods_db
from modules.trainer import trainer_loop
from modules.alarm import alarm_loop
from modules.cavebot import Cavebot
from core.player_core import get_connected_char_name
from core.bot_state import state
#import corpses

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

# Estado Global do Bot
BOT_SETTINGS = {
    # Geral
    "telegram_chat_id": TELEGRAM_CHAT_ID, # Do config.py
    "vocation": "Knight",
    "debug_mode": False,
    "hit_log_enabled": HIT_LOG_ENABLED,

    #trainer
    "ignore_first": False,
    "trainer_min_delay": 1.0,
    "trainer_max_delay": 2.0,
    "trainer_range": 1, # 1 = Melee, 3+ = Distance
    
    # Listas
    "targets": list(TARGET_MONSTERS),
    "safe": list(SAFE_CREATURES),
    
    # Alarme
    "alarm_range": 8,
    "alarm_floor": "Padrão",
    "alarm_hp_enabled": False,
    "alarm_hp_percent": 50,
    "alarm_visual_enabled": True,   # <--- NOVO
    "alarm_chat_enabled": True,    # <--- NOVO
    "alarm_chat_gm": True,          # <--- NOVO
    
    # Loot
    "loot_containers": 2,
    "loot_dest": 0,
    "loot_drop_food": False,
    
    # Fisher
    "fisher_min": 4,
    "fisher_max": 6,
    "fisher_check_cap": True,   # Ativa/Desativa checagem
    "fisher_min_cap": 6.0,     # Valor da Cap mínima
    "fisher_fatigue": True,
    
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
    "rune_human_max": 300,  # Segundos máximos de espera

    # KS Prevention
    "ks_prevention_enabled": True,

    # Console Log
    "console_log_visible": True
}

_cached_player_name = ""

# Variáveis de Controle de Execução
is_attacking = False
is_looting = False
# bot_running movido para state.is_running (bot_state.py)
pm = None 
base_addr = 0
state.is_connected = False # True apenas se: Processo Aberto + Logado no Char
is_graph_visible = False
gm_found = False
full_light_enabled = False # <--- NOVO
xray_window = None
hud_overlay_data = [] # Lista de dicionários para Fisher HUD
lbl_status = None 

# ### CAVEBOT: Globais ###
cavebot_instance = None
current_waypoints_ui = []
current_waypoints_filename = ""
label_cavebot_status = None  # Label para mostrar posição atual e waypoint
txt_waypoints_settings = None
entry_waypoint_name = None
combo_cavebot_scripts = None

# NOVAS VARIÁVEIS PARA O RECORDER
is_recording_waypoints = False
last_recorded_pos = (0, 0, 0)

# Waypoint Editor
_waypoint_editor_window = None

# Variáveis de Controle de Retorno (Segurança)
#resume_actions_timestamp = 0
# last_alarm_was_gm = False
#resume_type = "NONE" # "NORMAL" ou "GM"

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

            # Sincroniza console_log_visible com valor padrão se não existir
            if "console_log_visible" not in BOT_SETTINGS:
                BOT_SETTINGS["console_log_visible"] = True

        print("Configurações carregadas.")
    except Exception as e:
        print(f"Erro ao carregar: {e}")

# ==============================================================================
# 3. OBJETOS DE MONITORAMENTO (INSTANCIAS)
# ==============================================================================
monitor = TrainingMonitor(
    log_callback=lambda msg: log(msg),
    log_hits=BOT_SETTINGS.get("hit_log_enabled", True)
) # Lambda para resolver escopo se necessário, ou direto
# Nota: Definido como direto no original, ajustado abaixo para uso nas funções
sword_tracker = SkillTracker("Sword")
shield_tracker = SkillTracker("Shield")
magic_tracker = SkillTracker("Magic")
exp_tracker = ExpTracker()
gold_tracker = GoldTracker()
regen_tracker = RegenTracker()

# ==============================================================================
# MINIMAP VISUALIZATION (REALTIME)
# ==============================================================================
minimap_visualizer = None
minimap_container = None  # Frame container do minimap (para show/hide automático)
minimap_label = None
minimap_title_label = None
minimap_status_label = None
minimap_image_ref = None

# Log visibility toggle (inicializado após load_config)
log_visible = True  # Será atualizado por BOT_SETTINGS['console_log_visible']

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

def get_player_name():
    """
    Retorna o nome do personagem logado.
    Usa cache pois o nome não muda durante a sessão.
    Reseta o cache quando desconecta.
    """
    global _cached_player_name, pm, base_addr
    
    # Se desconectou, limpa o cache
    if pm is None:
        _cached_player_name = ""
        return ""
    
    # Se não tem cache, busca
    if not _cached_player_name:
        _cached_player_name = get_connected_char_name(pm, base_addr)
    
    return _cached_player_name

def clear_player_name_cache():
    """Chamado quando desconecta para limpar o cache."""
    global _cached_player_name
    _cached_player_name = ""

# ==============================================================================
# ### CAVEBOT: FUNÇÕES DA GUI ###
# ==============================================================================

def update_waypoint_display():
    """Atualiza a lista visual de waypoints na janela de Settings (Thread-Safe)."""

    def _refresh_ui():
        global txt_waypoints_settings

        # Se a janela de settings não estiver aberta ou o widget não existir, ignora
        if txt_waypoints_settings is None:
            return
        try:
            if not txt_waypoints_settings.winfo_exists():
                return
        except:
            return # Widget destruído

        # Atualiza o conteúdo
        txt_waypoints_settings.configure(state="normal")
        txt_waypoints_settings.delete("1.0", "end")

        # Header com contador
        total = len(current_waypoints_ui)
        header = f"═══ WAYPOINTS (Total: {total}) ═══\n\n"
        txt_waypoints_settings.insert("end", header)

        if not current_waypoints_ui:
            txt_waypoints_settings.insert("end", "Lista vazia.\n")
        else:
            for idx, wp in enumerate(current_waypoints_ui):
                act = wp.get('action', 'WALK').upper()
                # Formatação: 1. [WALK] 32300, 32100, 7
                line = f"{idx+1}. [{act}] {wp['x']}, {wp['y']}, {wp['z']}\n"
                txt_waypoints_settings.insert("end", line)

        txt_waypoints_settings.configure(state="disabled")
        txt_waypoints_settings.see("end")

    # Agenda a atualização para rodar na Thread Principal do app
    if 'app' in globals() and app:
        app.after(0, _refresh_ui)

def _set_waypoint_name_field(name):
    """Atualiza o campo de nome do arquivo e o estado global do nome atual."""
    global current_waypoints_filename, entry_waypoint_name
    current_waypoints_filename = name or ""
    if entry_waypoint_name and entry_waypoint_name.winfo_exists():
        entry_waypoint_name.delete(0, "end")
        if name:
            entry_waypoint_name.insert(0, name)

def list_cavebot_scripts():
    """Retorna nomes (sem .json) dos scripts em /cavebot_scripts."""
    folder = Path("cavebot_scripts")
    if not folder.exists():
        return []
    return sorted([p.stem for p in folder.glob("*.json")])

def refresh_cavebot_scripts_combo(selected=None):
    """Atualiza a combo de scripts salvos."""
    if combo_cavebot_scripts is None or not combo_cavebot_scripts.winfo_exists():
        return
    names = list_cavebot_scripts()
    combo_cavebot_scripts.configure(values=names)
    if selected and selected in names:
        combo_cavebot_scripts.set(selected)
    elif names:
        combo_cavebot_scripts.set(names[0])
    else:
        combo_cavebot_scripts.set("")

def add_waypoint_entry(action, x, y, z):
    """Função central para adicionar waypoint e atualizar UI e Backend."""
    global current_waypoints_ui, cavebot_instance

    # Cria o dicionário do waypoint
    new_wp = {'action': action, 'x': x, 'y': y, 'z': z}
    current_waypoints_ui.append(new_wp)

    # Atualiza o Cavebot em tempo real se ele estiver rodando
    if cavebot_instance:
        cavebot_instance.load_waypoints(current_waypoints_ui)

    # Atualiza a tela
    update_waypoint_display()

    # Log mais informativo
    log(f"✅ WP #{len(current_waypoints_ui)} adicionado: ({x}, {y}, {z})")

def add_manual_waypoint(dx, dy, action_type):
    """
    Calcula a posição baseada no clique da matriz (dx, dy) relativo ao player.
    dx, dy: -1, 0, ou 1
    """
    if not state.is_connected or pm is None:
        log("❌ Conecte no Tibia primeiro.")
        return

    try:
        px, py, pz = get_player_pos(pm, base_addr)
        target_x = px + dx
        target_y = py + dy

        add_waypoint_entry(action_type, target_x, target_y, pz)

    except Exception as e:
        log(f"Erro ao adicionar WP manual: {e}")

def open_insert_coords_dialog():
    """Abre janela para inserir coordenadas X, Y, Z manualmente."""
    dialog = ctk.CTkToplevel(app)
    dialog.title("Inserir Waypoint")
    dialog.geometry("300x220")
    dialog.resizable(False, False)
    dialog.transient(app)  # Modal
    dialog.grab_set()
    dialog.attributes('-topmost', True)  # Sempre no topo
    dialog.lift()  # Traz para o topo
    dialog.focus()

    # Título
    ctk.CTkLabel(dialog, text="Inserir Coordenadas", font=("Verdana", 12, "bold")).pack(pady=(10, 15))

    # Frame de inputs
    frame_inputs = ctk.CTkFrame(dialog, fg_color="transparent")
    frame_inputs.pack(pady=5, padx=20, fill="x")

    # X
    ctk.CTkLabel(frame_inputs, text="X:", font=("Verdana", 10)).grid(row=0, column=0, sticky="w", pady=5)
    entry_x = ctk.CTkEntry(frame_inputs, width=180, font=("Verdana", 10))
    entry_x.grid(row=0, column=1, padx=(10, 0), pady=5)

    # Y
    ctk.CTkLabel(frame_inputs, text="Y:", font=("Verdana", 10)).grid(row=1, column=0, sticky="w", pady=5)
    entry_y = ctk.CTkEntry(frame_inputs, width=180, font=("Verdana", 10))
    entry_y.grid(row=1, column=1, padx=(10, 0), pady=5)

    # Z
    ctk.CTkLabel(frame_inputs, text="Z:", font=("Verdana", 10)).grid(row=2, column=0, sticky="w", pady=5)
    entry_z = ctk.CTkEntry(frame_inputs, width=180, font=("Verdana", 10))
    entry_z.grid(row=2, column=1, padx=(10, 0), pady=5)

    # Função de confirmação
    def confirm_coords():
        try:
            x = int(entry_x.get().strip())
            y = int(entry_y.get().strip())
            z = int(entry_z.get().strip())

            add_waypoint_entry("walk", x, y, z)
            log(f"✅ Waypoint inserido: ({x}, {y}, {z})")
            dialog.destroy()
        except ValueError:
            log("❌ Coordenadas inválidas! Use apenas números inteiros.")

    # Botões
    frame_buttons = ctk.CTkFrame(dialog, fg_color="transparent")
    frame_buttons.pack(pady=(10, 10), fill="x", padx=20)

    ctk.CTkButton(frame_buttons, text="✅ Adicionar", command=confirm_coords,
                 fg_color="#2CC985", hover_color="#1FA86E", width=120).pack(side="left", padx=5)

    ctk.CTkButton(frame_buttons, text="❌ Cancelar", command=dialog.destroy,
                 fg_color="#FF5555", hover_color="#CC4444", width=120).pack(side="right", padx=5)

    # Foco no primeiro campo
    entry_x.focus()

def remove_last_waypoint():
    """Remove o último waypoint da lista."""
    global current_waypoints_ui, cavebot_instance

    if not current_waypoints_ui:
        log("⚠️ Lista de waypoints já está vazia.")
        return

    removed_wp = current_waypoints_ui.pop()  # Remove último

    if cavebot_instance:
        cavebot_instance.load_waypoints(current_waypoints_ui)

    update_waypoint_display()
    log(f"🗑️ Removido WP #{len(current_waypoints_ui) + 1}: ({removed_wp['x']}, {removed_wp['y']}, {removed_wp['z']})")

def open_remove_specific_dialog():
    """Abre janela para inserir o número do waypoint a ser removido."""
    if not current_waypoints_ui:
        log("⚠️ Lista de waypoints está vazia.")
        return

    dialog = ctk.CTkToplevel(app)
    dialog.title("Remover Waypoint")
    dialog.geometry("320x160")
    dialog.resizable(False, False)
    dialog.transient(app)
    dialog.grab_set()
    dialog.attributes('-topmost', True)  # Sempre no topo
    dialog.lift()  # Traz para o topo
    dialog.focus()

    # Título
    ctk.CTkLabel(dialog, text="Remover Waypoint Específico", font=("Verdana", 12, "bold")).pack(pady=(10, 10))

    # Frame de input
    frame_input = ctk.CTkFrame(dialog, fg_color="transparent")
    frame_input.pack(pady=5, padx=20, fill="x")

    ctk.CTkLabel(frame_input, text=f"Digite o número (1-{len(current_waypoints_ui)}):",
                font=("Verdana", 10)).pack(anchor="w", pady=(0, 5))

    entry_index = ctk.CTkEntry(frame_input, width=260, font=("Verdana", 11))
    entry_index.pack(fill="x")

    # Função de confirmação
    def confirm_remove():
        try:
            index = int(entry_index.get().strip())

            if index < 1 or index > len(current_waypoints_ui):
                log(f"❌ Número inválido! Escolha entre 1 e {len(current_waypoints_ui)}.")
                return

            # Remove waypoint (índice 1-based → 0-based)
            removed_wp = current_waypoints_ui.pop(index - 1)

            if cavebot_instance:
                cavebot_instance.load_waypoints(current_waypoints_ui)

            update_waypoint_display()
            log(f"🗑️ Removido WP #{index}: ({removed_wp['x']}, {removed_wp['y']}, {removed_wp['z']})")
            dialog.destroy()
        except ValueError:
            log("❌ Entrada inválida! Use apenas números inteiros.")

    # Botões
    frame_buttons = ctk.CTkFrame(dialog, fg_color="transparent")
    frame_buttons.pack(pady=(10, 10), fill="x", padx=20)

    ctk.CTkButton(frame_buttons, text="🗑️ Remover", command=confirm_remove,
                 fg_color="#FF5555", hover_color="#CC4444", width=120).pack(side="left", padx=5)

    ctk.CTkButton(frame_buttons, text="❌ Cancelar", command=dialog.destroy,
                 fg_color="#808080", hover_color="#606060", width=120).pack(side="right", padx=5)

    entry_index.focus()

def generate_route_visualization():
    """Gera visualização da rota completa dos waypoints carregados."""
    global current_waypoints_ui

    if not current_waypoints_ui:
        log("⚠️ Nenhum waypoint carregado. Carregue um script primeiro.")
        return

    try:
        from utils.visualize_path import create_route_visualization
        from config import MAPS_DIRECTORY

        log(f"🎨 Gerando visualização de {len(current_waypoints_ui)} waypoints...")

        # Gera imagens
        output_dir = Path("cavebot_maps")
        output_dir.mkdir(exist_ok=True)

        prefix = output_dir / "rota"
        files = create_route_visualization(MAPS_DIRECTORY, current_waypoints_ui, str(prefix))

        if files:
            log(f"✅ {len(files)} imagens geradas!")
            # Abre todas as imagens geradas
            import os
            for filepath in files:
                try:
                    os.startfile(filepath)
                except Exception as e:
                    log(f"⚠️ Erro ao abrir {filepath}: {e}")
        else:
            log("❌ Nenhuma imagem foi gerada.")

    except Exception as e:
        log(f"❌ Erro ao gerar visualização: {e}")
        import traceback
        traceback.print_exc()

def open_waypoint_editor_window():
    """Abre a janela do editor visual de waypoints."""
    global current_waypoints_ui, cavebot_instance, app, pm, base_addr, _waypoint_editor_window

    try:
        from utils.waypoint_editor import WaypointEditorWindow
        from config import MAPS_DIRECTORY

        # Callback para quando o usuário salva no editor
        def on_editor_save(new_waypoints):
            global current_waypoints_ui, cavebot_instance
            current_waypoints_ui = new_waypoints
            if cavebot_instance:
                cavebot_instance.load_waypoints(new_waypoints)
            update_waypoint_display()
            log(f"✅ Editor: {len(new_waypoints)} waypoints atualizados.")

        # Determine initial position for editor
        # Priority: 1) First waypoint if loaded, 2) Current player position
        current_pos = None
        if current_waypoints_ui and len(current_waypoints_ui) > 0:
            # Use first waypoint position if waypoints are loaded
            first_wp = current_waypoints_ui[0]
            current_pos = (first_wp['x'], first_wp['y'], first_wp['z'])
        elif state.is_connected and pm:
            # Otherwise use current player position if connected
            try:
                current_pos = get_player_pos(pm, base_addr)
            except:
                current_pos = None

        # Abre a janela do editor (armazena globalmente para manter viva)
        _waypoint_editor_window = WaypointEditorWindow(
            parent_window=app,
            maps_directory=MAPS_DIRECTORY,
            current_waypoints=current_waypoints_ui.copy() if current_waypoints_ui else [],
            on_save_callback=on_editor_save,
            current_pos=current_pos
        )

        log("🗺️ Editor Visual de Waypoints aberto.")

    except ImportError as e:
        log(f"❌ Erro ao importar editor: {e}")
    except Exception as e:
        log(f"❌ Erro ao abrir editor: {e}")
        import traceback
        traceback.print_exc()

def auto_recorder_loop():
    """Thread que monitora movimento e grava waypoints."""
    global last_recorded_pos, is_recording_waypoints, pm, base_addr
    
    print("Gravador Automático Iniciado.")

    while state.is_running:
        # Verifica condições: Gravação Ligada + Conectado + PM válido
        if is_recording_waypoints and state.is_connected and pm:
            try:
                px, py, pz = get_player_pos(pm, base_addr)
                
                # Se a leitura falhar (ex: retornou 0,0,0), ignora
                if px == 0 and py == 0:
                    time.sleep(0.1)
                    continue

                curr_pos = (px, py, pz)
                
                # Se mudou de posição
                if curr_pos != last_recorded_pos:
                    # Se for o primeiro registro (reset), apenas atualiza last_pos
                    if last_recorded_pos == (0, 0, 0):
                        last_recorded_pos = curr_pos
                    else:
                        # Adiciona o WP
                        add_waypoint_entry("walk", px, py, pz)
                        last_recorded_pos = curr_pos
                        
            except Exception as e:
                print(f"Erro Recorder: {e}")
                
        time.sleep(0.2) # Verifica 5x por segundo

def toggle_recording_func(switch_val):
    global is_recording_waypoints, last_recorded_pos
    is_recording_waypoints = bool(switch_val)
    if is_recording_waypoints:
        # Reseta a última posição para forçar gravação do primeiro passo
        last_recorded_pos = (0, 0, 0)
        log("⏺️ Gravação Automática INICIADA.")
    else:
        log("⏹️ Gravação Automática PARADA.")

def record_current_pos():
    """Pega a posição atual do char e adiciona na lista."""
    global cavebot_instance
    if not state.is_connected or pm is None:
        log("Erro: Conecte no Tibia primeiro.")
        return

    try:
        x, y, z = get_player_pos(pm, base_addr)
        new_wp = {'x': x, 'y': y, 'z': z, 'action': 'walk'}
        current_waypoints_ui.append(new_wp)
        
        # Atualiza o backend se existir
        if cavebot_instance:
            cavebot_instance.load_waypoints(current_waypoints_ui)
            
        update_waypoint_display()
        log(f"📍 Waypoint gravado: {x}, {y}, {z}")
    except Exception as e:
        log(f"Erro ao gravar waypoint: {e}")

def save_waypoints_file():
    """Salva a lista atual usando o nome informado no campo (pasta /cavebot_scripts)."""
    name = entry_waypoint_name.get().strip() if entry_waypoint_name else ""
    if not name:
        log("⚠️ Informe um nome para salvar o script.")
        return

    folder = Path("cavebot_scripts")
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        log(f"Erro ao preparar pasta cavebot_scripts: {e}")
        return

    filename = folder / f"{name}.json"
    try:
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(current_waypoints_ui, f, indent=4)
        _set_waypoint_name_field(name)
        refresh_cavebot_scripts_combo(selected=name)
        log(f"💾 Waypoints salvos: {filename.name}")
    except Exception as e:
        log(f"Erro ao salvar: {e}")

def load_waypoints_file():
    """Carrega um script selecionado na combo de /cavebot_scripts."""
    global current_waypoints_ui, cavebot_instance
    name = combo_cavebot_scripts.get().strip() if combo_cavebot_scripts else ""
    if not name:
        log("⚠️ Selecione um script na lista para carregar.")
        return
    filename = Path("cavebot_scripts") / f"{name}.json"
    if not filename.exists():
        log(f"Erro: arquivo {filename} não encontrado.")
        refresh_cavebot_scripts_combo()
        return
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            loaded_data = json.load(f)
            if isinstance(loaded_data, list):
                current_waypoints_ui = loaded_data
                if cavebot_instance:
                    cavebot_instance.load_waypoints(current_waypoints_ui)
                _set_waypoint_name_field(name)
                refresh_cavebot_scripts_combo(selected=name)
                update_waypoint_display()
                log(f"📂 Carregados {len(loaded_data)} waypoints de {filename.name}.")
            else:
                log("Erro: Formato de arquivo inválido.")
    except Exception as e:
        log(f"Erro ao carregar: {e}")

def clear_waypoints():
    global current_waypoints_ui, cavebot_instance
    current_waypoints_ui = []
    if cavebot_instance:
        cavebot_instance.load_waypoints([])
    update_waypoint_display()
    _set_waypoint_name_field("")
    log("🗑️ Lista de waypoints limpa.")

def toggle_cavebot_func():
    """Callback do Switch do Cavebot."""
    global cavebot_instance
    if not cavebot_instance:
        log("Aguarde a conexão com o Tibia...")
        switch_cavebot_var.set(0)
        return

    if switch_cavebot_var.get() == 1:
        if not current_waypoints_ui:
            log("⚠️ AVISO: Carregue waypoints antes de ativar!")
            switch_cavebot_var.set(0)
            return
        # Garante que os WPs estão carregados
        cavebot_instance.load_waypoints(current_waypoints_ui)
        cavebot_instance.start()
        show_minimap_panel()
        log("🚀 CAVEBOT: ATIVADO")
    else:
        cavebot_instance.stop()
        hide_minimap_panel()
        log("⏸️ CAVEBOT: PAUSADO")

# ==============================================================================
# 5. THREADS DE LÓGICA DO BOT (WORKERS)
# ==============================================================================

def connection_watchdog():
    global pm, base_addr
    was_connected_once = False
    while state.is_running:
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
                        clear_player_name_cache() 
                        os._exit(0) # Mata o bot
                    state.is_connected = False
                    lbl_connection.configure(text="Cliente Fechado ❌", text_color="#FF5555")
                    time.sleep(2)
                    continue

            # 2. Se o processo existe, verifica se está LOGADO
            try:
                status = pm.read_int(base_addr + OFFSET_CONNECTION)
                
                if status == 8: # 8 geralmente é "In Game"
                    if not state.is_connected:
                        log("🟢 Conectado ao mundo!")
                        if full_light_enabled:
                            time.sleep(1) 
                            apply_full_light(True)
                    state.is_connected = True
                    was_connected_once = True
                    lbl_connection.configure(text="Conectado 🟢", text_color="#00FF00")
                else:
                    state.is_connected = False
                    lbl_connection.configure(text="Desconectado ⚠️", text_color="#FFFF00")
                    clear_player_name_cache() 
                    
            except Exception:
                pm = None
                state.is_connected = False
                if was_connected_once:
                    os._exit(0)
                lbl_connection.configure(text="Cliente Fechado ❌", text_color="#FF5555")
                clear_player_name_cache() 

        except Exception as e:
            print(f"Erro Watchdog: {e}")
        
        time.sleep(1)

def start_cavebot_thread():
    """Gerencia a inicialização e o loop do Cavebot."""
    global cavebot_instance, pm, base_addr
    print("Thread Cavebot iniciada.")

    while state.is_running:
        # 1. Inicialização Lazy (Só cria quando o PM existir)
        if pm is not None and cavebot_instance is None and state.is_connected:
            try:
                print("Inicializando instância do Cavebot...")
                cavebot_instance = Cavebot(pm, base_addr)
                # Se já tiver waypoints na UI, carrega eles
                if current_waypoints_ui:
                    cavebot_instance.load_waypoints(current_waypoints_ui)
            except Exception as e:
                print(f"Erro init cavebot: {e}")

        # 2. Execução do Ciclo
        if cavebot_instance and state.is_connected:
            try:
                # O método run_cycle verifica internamente se está enabled
                if cavebot_instance.enabled:
                    cavebot_instance.run_cycle()

                # 3. Atualizar Label de Status na UI (a cada ciclo)
                if pm and label_cavebot_status and label_cavebot_status.winfo_exists():
                    try:
                        px, py, pz = get_player_pos(pm, base_addr)
                        #wp_list = cavebot_instance._waypoints if cavebot_instance._waypoints else []
                        #wp_idx = cavebot_instance._current_index if cavebot_instance._waypoints else -1
                        label_text = f"📍Pos: ({px}, {py}, {pz})"

                        label_cavebot_status.configure(text=label_text)
                    except:
                        pass  # Silencia erros de UI
            except Exception as e:
                print(f"Erro Cavebot Loop: {e}")
                time.sleep(1)

        time.sleep(0.1)

def start_trainer_thread():
    """
    Thread Wrapper para o Trainer.
    Cria a ponte de configuração em tempo real entre o Main e o Módulo.
    """
    hwnd = 0
    
    # --- CONFIG PROVIDER ---
    # Essa função é executada pelo trainer.py a cada ciclo.
    # Ela captura o estado ATUAL dos botões e variáveis globais.
    config_provider = lambda: {
        # Lê o estado do botão (Switch) em tempo real
        'enabled': switch_trainer.get(),
        
        # Lê a variável de segurança controlada pelo Alarme
        'is_safe': state.is_safe(),
        
        # Lê as configurações salvas/editadas no menu
        'targets': BOT_SETTINGS['targets'],
        'ignore_first': BOT_SETTINGS['ignore_first'],
        'debug_mode': BOT_SETTINGS['debug_mode'],
        
        # Lê o botão de loot para saber se deve abrir corpos
        'loot_enabled': switch_loot.get(),
        
        # Passa a função de log da interface
        'log_callback': log,

        'min_delay': BOT_SETTINGS.get('trainer_min_delay', 1.0),
        'max_delay': BOT_SETTINGS.get('trainer_max_delay', 2.0),
        'range': BOT_SETTINGS.get('trainer_range', 1)
    }

    # Função para checar se o bot ainda deve rodar (stop kill)
    check_running = lambda: state.is_running and state.is_connected

    while state.is_running:
        if not check_running(): 
            time.sleep(1)
            continue
            
        if pm is None: 
            time.sleep(1)
            continue
            
        if hwnd == 0: 
            hwnd = win32gui.FindWindow("TibiaClient", None) or win32gui.FindWindow(None, "Tibia")

        try:
            # Chama a função principal do módulo novo
            trainer_loop(pm, base_addr, hwnd, monitor, check_running, config_provider)
            
            # Se a função retornar (ex: desconectou), espera um pouco antes de tentar de novo
            time.sleep(1)
            
        except Exception as e:
            print(f"Trainer Thread Crash: {e}")
            time.sleep(5)

def start_alarm_thread():
    """
    Thread Wrapper para o Alarme.
    Gerencia transições de Seguro/Perigo e Timers de Retorno.
    """
    
    def set_safe(val): 
        """
        Callback chamado pelo alarm.py quando estado de segurança muda.
        Usa state para gerenciar transições de forma thread-safe.
        """
        # Detecta transição: PERIGO (False) -> SEGURO (True)
        if val is True and not state.is_safe_raw():
            if state.is_gm_detected:
                # Caso GM: Delay Longo (Pânico)
                delay = random.uniform(*config.RESUME_DELAY_GM)
                log(f"👮 GM sumiu. Modo Pânico: Aguardando {int(delay)}s...")
            else:
                # Caso Normal: Delay Curto (Humano)
                delay = random.uniform(*config.RESUME_DELAY_NORMAL)
                log(f"🛡️ Perigo passou. Aguardando {int(delay)}s para retomar...")
            
            # clear_alarm faz: is_safe=True, is_gm=False, define cooldown
            state.clear_alarm(cooldown_seconds=delay)
        
        elif val is False:
            # Transição para PERIGO
            # Nota: set_gm() é chamado antes se for GM, então aqui só marcamos perigo genérico
            if not state.is_gm_detected:  # Só dispara se não foi GM (evita sobrescrever)
                state.trigger_alarm(is_gm=False, reason="DANGER")
        
    def set_gm(val): 
        """
        Callback chamado pelo alarm.py quando GM é detectado/liberado.
        """
        if val:
            # Dispara alarme marcando como GM
            state.trigger_alarm(is_gm=True, reason="GM")
        # Se val=False, o set_safe(True) já vai limpar via clear_alarm
    
    callbacks = {
        'set_safe': set_safe,
        'set_gm': set_gm,
        'telegram': send_telegram,
        'log': log
    }

    # Config Provider
    alarm_cfg = lambda: {
        'enabled': switch_alarm.get(),
        'safe_list': BOT_SETTINGS['safe'],
        'range': BOT_SETTINGS['alarm_range'],
        'floor': BOT_SETTINGS['alarm_floor'],
        'hp_enabled': BOT_SETTINGS['alarm_hp_enabled'],
        'hp_percent': BOT_SETTINGS['alarm_hp_percent'],
        'visual_enabled': BOT_SETTINGS['alarm_visual_enabled'],
        'chat_enabled': BOT_SETTINGS['alarm_chat_enabled'],
        'chat_gm': BOT_SETTINGS['alarm_chat_gm'],
        'debug_mode': BOT_SETTINGS['debug_mode']
    }

    check_run = lambda: state.is_running and state.is_connected

    while state.is_running:
        if not check_run(): time.sleep(1); continue
        if pm is None: time.sleep(1); continue

        try:
            alarm_loop(pm, base_addr, check_run, alarm_cfg, callbacks)
        except Exception as e:
            print(f"Alarm Thread Crash: {e}")
            time.sleep(5)

def regen_monitor_loop():
    global pm, base_addr
    global global_regen_seconds, global_is_hungry, global_is_synced, global_is_full
    
    print("[REGEN] Monitor Iniciado (Modo Híbrido com Validação Dupla)")
    
    last_hp = -1
    last_mana = -1
    last_check_time = time.time()
    seconds_no_hp_up = 0
    seconds_no_mana_up = 0
    last_mem_id = 0

    while state.is_running:
        if not state.is_connected or pm is None:
            time.sleep(1)
            continue
            
        try:
            # 1. DETECÇÃO MANUAL DE CLIQUE (Sincronia por ação do usuário)
            curr_mem_id = pm.read_int(base_addr + OFFSET_LAST_USED_ITEM_ID)
            
            if curr_mem_id != 0:
                if curr_mem_id != last_mem_id:
                    if curr_mem_id in FOOD_IDS:
                        gauss_wait(0.4, 20)
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
                            status_text = "🔴 Hungry"
                            color = "#FF5555"
                            final_is_hungry = True
                        else:
                            status_text = "🟡 Validando..."
                            color = "#E0E000"
                            final_is_hungry = False
                        
                else:
                    if hungry_by_logic:
                         status_text = "🔴 Hungry"
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

    config_provider = lambda: {
        'loot_containers': BOT_SETTINGS['loot_containers'],
        'loot_dest': BOT_SETTINGS['loot_dest'],
        'loot_drop_food': BOT_SETTINGS.get('loot_drop_food', False)
    }

    while state.is_running:
        if not state.is_connected: time.sleep(1); continue
        if not switch_loot.get(): time.sleep(1); continue
        if not state.is_safe(): time.sleep(1); continue
        if pm is None: time.sleep(1); continue   
        if hwnd == 0: hwnd = win32gui.FindWindow("TibiaClient", None) or win32gui.FindWindow(None, "Tibia")
        
        try:
            # 1. Tenta Lootear
            did_loot = run_auto_loot(pm, base_addr, hwnd, config=config_provider)
            
            if did_loot:
                # --- CASOS COM DADOS (TUPLAS) ---
                if isinstance(did_loot, tuple):
                    action = did_loot[0]
                    
                    if action == "EAT":
                        item_id = did_loot[1]
                        food_name = foods_db.get_food_name(item_id)
                        log(f"🍖 {food_name} comido(a) do corpo.")
                        register_food_eaten(item_id)

                    elif action == "DROP_FOOD":
                        # 🔥 LÓGICA NOVA AQUI
                        item_id = did_loot[1]
                        food_name = foods_db.get_food_name(item_id)
                        log(f"🗑️ Joguei {food_name} no chão (Full).")

                    elif action == "LOOT":
                        _, item_id, count = did_loot
                        gold_tracker.add_loot(item_id, count)
                        log(f"💰 Loot: {count}x ID {item_id}")

                # --- CASOS DE STATUS (STRINGS) ---
                elif did_loot == "FULL_BP_ALARM":
                    log("⚠️ BACKPACKS CHEIAS! Loot pausado.")
                    time.sleep(2) 
                
                elif did_loot == "EAT_FULL":
                    pass # Já tratado pelo DROP_FOOD, mas mantemos por segurança
                
                elif did_loot == "DROP":
                    log("🗑️ Item dropado no chão.")
                
                # elif did_loot == "BAG":
                #     log("🎒 Bag extra aberta.")

                gauss_wait(0.5, 20)
                continue

            # 2. REMOVIDO: Stacker agora é chamado DENTRO do AutoLoot (após cada item coletado)
            # O loop aguarda 1.0s se nenhum loot foi coletado
            time.sleep(1.0)

        except Exception as e:
            print(f"Erro Loot/Stack: {e}")
            time.sleep(1)

def combat_loot_monitor_thread():
    """
    Thread dedicada para monitorar estado de combate.
    Atualiza bot_state.py para coordenação entre módulos a cada 300ms.

    NOTA: state.has_open_loot é gerenciado DENTRO de auto_loot.py
    (não é responsabilidade deste monitor thread)
    """
    log("🔍 Combat Monitor iniciado")

    while state.is_running:
        if not state.is_connected or pm is None:
            state.set_combat_state(False)
            time.sleep(1)
            continue

        try:
            # Verifica combate (lê TARGET_ID_PTR da memória)
            target_id = pm.read_int(base_addr + TARGET_ID_PTR)
            in_combat = (target_id != 0)
            state.set_combat_state(in_combat)

        except Exception as e:
            # Silencioso para não poluir logs
            pass

        gauss_wait(0.3, 20)  # ~3 verificações por segundo

def auto_fisher_thread():
    hwnd = 0
    def should_fish():
        # state.is_safe() já verifica a flag E o cooldown internamente
        return state.is_running and state.is_connected and switch_fisher.get() and state.is_safe()

    # --- CONFIG PROVIDER (O SEGREDO) ---
    # Essa função "empacota" as configurações atuais do BOT_SETTINGS.
    # O Fisher vai chamar ela a cada ciclo para saber se você mudou algo.
    config_provider = lambda: {
        'min_attempts': BOT_SETTINGS.get('fisher_min', 4),
        'max_attempts': BOT_SETTINGS.get('fisher_max', 6),
        'check_cap': BOT_SETTINGS.get('fisher_check_cap', True),
        'min_cap_val': BOT_SETTINGS.get('fisher_min_cap', 6.0),
        'fatigue': BOT_SETTINGS.get('fisher_fatigue', True)
    }

    while state.is_running:
        if not should_fish():
            time.sleep(1)
            continue
            
        if pm is None:
            time.sleep(1)
            continue
            
        if hwnd == 0:
            hwnd = win32gui.FindWindow("TibiaClient", None) or win32gui.FindWindow(None, "Tibia")

        try:
            # Chamamos o loop passando o provider em vez dos valores fixos
            fishing_loop(pm, base_addr, hwnd, 
                         check_running=should_fish, 
                         log_callback=log,
                         debug_hud_callback=update_fisher_hud,
                         config=config_provider) # <--- AQUI
            
            time.sleep(1)
            
        except Exception as e:
            print(f"Erro Fisher Thread: {e}")
            time.sleep(5)

def runemaker_thread():
    hwnd = 0

    def should_run():
        return state.is_running and state.is_connected and switch_runemaker.get()
    
    def check_safety():
        return state.is_safe_raw()

    def check_gm():
        return state.is_gm_detected
    
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

    config_provider = lambda: {
        'mana_req': BOT_SETTINGS['rune_mana'],
        'hotkey': BOT_SETTINGS['rune_hotkey'],
        'blank_id': BOT_SETTINGS['rune_blank_id'],
        'hand_mode': BOT_SETTINGS['rune_hand'],
        'work_pos': BOT_SETTINGS['rune_work_pos'],
        'safe_pos': BOT_SETTINGS['rune_safe_pos'],
        'return_delay': BOT_SETTINGS['rune_return_delay'],
        'flee_delay': BOT_SETTINGS['rune_flee_delay'],
        'auto_eat': BOT_SETTINGS['auto_eat'], 
        'check_hunger': check_hunger_state, # Função passada dentro da config
        'mana_train': BOT_SETTINGS['mana_train'],
        'enable_movement': BOT_SETTINGS.get('rune_movement', False),
        'human_min': BOT_SETTINGS.get('rune_human_min', 0),
        'human_max': BOT_SETTINGS.get('rune_human_max', 0),

        'can_perform_actions': (
            # Se movimento ligado E alarme NÃO foi GM -> Ignora timer (True)
            (BOT_SETTINGS.get('rune_movement', False) and not state.is_gm_detected) 
            or 
            # Caso contrário (GM ou Sem Movimento) -> Respeita cooldown
            (state.cooldown_remaining <= 0)
        )
    }

    while state.is_running:
        if not should_run():
            time.sleep(1); continue
        if pm is None: time.sleep(1); continue
        if hwnd == 0: hwnd = win32gui.FindWindow("TibiaClient", None) or win32gui.FindWindow(None, "Tibia")

        try:           
            runemaker_loop(pm, base_addr, hwnd, 
                           check_running=should_run, 
                           config=config_provider, # <--- MUDANÇA AQUI
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
    while state.is_running:
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

# ==============================================================================
# 6. FUNÇÕES DA INTERFACE (CALLBACKS E JANELAS)
# ==============================================================================

def gui_updater_loop():
    while state.is_running:
        if not state.is_connected:
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
                        lbl_exp_rate.configure(text=f"{xp_stats['xp_hour']} xp/h")
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
                        lbl_regen_stock.configure(text=f"🍖 Food: {r_str}")

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
                    lbl_magic_time.configure(text=f"⏳ {horas:02d}:{minutos:02d}")
                else:
                    lbl_magic_rate.configure(text="-- m/%")
                    lbl_magic_time.configure(text="⏳ --")

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
            if not state.is_running: break
            time.sleep(1)

def update_stats_visibility():
    """
    Ajusta a interface baseada na vocação:
    - Mages: Esconde Sword, Shield e o Gráfico de Melee.
    - Knights: Mostra tudo.
    """
    voc = BOT_SETTINGS['vocation']
    is_mage = any(x in voc for x in ["Elder", "Master", "Druid", "Sorcerer", "Mage", "None"])
    
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
        # Se ele já estiver visível, o pack apenas atualiza, sem duplicar
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

def toggle_log_visibility():
    """Toggle log console visibility."""
    global log_visible, txt_log

    log_visible = not log_visible
    BOT_SETTINGS['console_log_visible'] = log_visible

    if log_visible:
        txt_log.pack(side="bottom", fill="x", padx=5, pady=5, expand=True)
        log("📝 Log console mostrado")
    else:
        txt_log.pack_forget()
        # Mensagem será logada quando a visibilidade for ativada novamente

def open_settings():
    global toplevel_settings, lbl_status, txt_waypoints_settings, entry_waypoint_name, combo_cavebot_scripts, current_waypoints_filename, label_cavebot_status
    
    if toplevel_settings is not None and toplevel_settings.winfo_exists():
        toplevel_settings.lift()
        toplevel_settings.focus()
        return

    # ==========================================================================
    # 🎨 SISTEMA DE ESTILOS (CSS-LIKE)
    # ==========================================================================
    UI = {
        # --- TIPOGRAFIA & CORES ---
        'H1': { # Títulos de Seção
            'font': ("Verdana", 11, "bold"),
            'text_color': "#FFFFFF" 
        },
        'BODY': { # Texto padrão (Toggles, Labels de input)
            'font': ("Verdana", 10),
            'text_color': "#CCCCCC" # Cinza claro
        },
        'HINT': { # Dicas pequenas (setinhas)
            'font': ("Verdana", 8),
            'text_color': "#555555" # Cinza escuro (quase bg)
        },
        
        # --- INPUTS & DROPDOWNS ---
        'INPUT': {
            'width': 50,
            'height': 24,
            'font': ("Verdana", 10),
            'justify': "center"
        },
        'INPUT_MED': {
            'width': 80,
            'height': 24,
            'font': ("Verdana", 10),
            'justify': "center"
        },
        'COMBO': {
            'width': 130,
            'height': 24,
            'font': ("Verdana", 10),
            'state': "readonly"
        },
        'COMBO_MED': {
            'width': 80,
            'height': 24,
            'font': ("Verdana", 10),
            'state': "readonly"
        },
        'BUTTON_SM': {
            'height': 24,
            'font': ("Verdana", 10),
        },
        'BTN_GRID': {
            'width': 35,
            'height': 35,
            'font': ("Verdana", 10, "bold"),
        },
        
        # --- PADDINGS & LAYOUT ---
        'PAD_SECTION': (10, 5),  # Espaço entre grupos grandes (Top, Bot)
        'PAD_ITEM':    2,        # Espaço entre itens compactos
        'PAD_INDENT':  20,       # Indentação para itens filhos
    }

    # ==========================================================================
    # JANELA
    # ==========================================================================
    toplevel_settings = ctk.CTkToplevel(app)
    toplevel_settings.title("Configurações")
    toplevel_settings.geometry("390x520") 
    toplevel_settings.attributes("-topmost", True)
    
    def on_settings_close():
        global lbl_status
        toplevel_settings.destroy()
        
    toplevel_settings.protocol("WM_DELETE_WINDOW", on_settings_close)

    tabview = ctk.CTkTabview(toplevel_settings)
    tabview.pack(fill="both", expand=True, padx=10, pady=10)
    
    # Criação das Abas
    tab_geral  = tabview.add("Geral")
    tab_trainer = tabview.add("Trainer")
    tab_alarm  = tabview.add("Alarme")
    tab_alvos  = tabview.add("Alvos") 
    tab_loot   = tabview.add("Loot")
    tab_fisher = tabview.add("Fisher")
    tab_rune   = tabview.add("Rune")
    tab_cavebot = tabview.add("Cavebot")

    # Helper para criar frames de grid (Label Esq | Input Dir)
    def create_grid_frame(parent):
        f = ctk.CTkFrame(parent, fg_color="transparent")
        f.pack(pady=UI['PAD_SECTION'][0], fill="x")
        f.grid_columnconfigure(0, weight=1) 
        f.grid_columnconfigure(1, weight=2) 
        return f

    # ==========================================================================
    # 1. ABA GERAL
    # ==========================================================================
    frame_geral = create_grid_frame(tab_geral)
    
    # Vocação
    ctk.CTkLabel(frame_geral, text="Vocação (Regen):", **UI['BODY']).grid(row=0, column=0, sticky="e", padx=10, pady=UI['PAD_ITEM'])
    combo_voc = ctk.CTkComboBox(frame_geral, values=list(VOCATION_REGEN.keys()), **UI['COMBO'])
    combo_voc.grid(row=0, column=1, sticky="w")
    combo_voc.set(BOT_SETTINGS['vocation'])

    # Telegram
    ctk.CTkLabel(frame_geral, text="Telegram Chat ID:", **UI['BODY']).grid(row=1, column=0, sticky="e", padx=10, pady=UI['PAD_ITEM'])
    entry_telegram = ctk.CTkEntry(frame_geral, width=150, height=24, font=UI['BODY']['font'])
    entry_telegram.grid(row=1, column=1, sticky="w")
    entry_telegram.insert(0, str(BOT_SETTINGS['telegram_chat_id']))
    
    ctk.CTkLabel(frame_geral, text="↳ Recebe alertas de PK e Pausa no celular.", **UI['HINT']).grid(row=2, column=0, columnspan=2, sticky="e", padx=60, pady=(0, 5))

    # Switches
    frame_switches = ctk.CTkFrame(tab_geral, fg_color="transparent")
    frame_switches.pack(pady=10)
    
    def on_debug_toggle():
        BOT_SETTINGS['debug_mode'] = bool(switch_debug.get())
        log(f"🔧 Debug: {BOT_SETTINGS['debug_mode']}")
    
    switch_debug = ctk.CTkSwitch(frame_switches, text="Debug Console", command=on_debug_toggle, progress_color="#FFA500", **UI['BODY'])
    switch_debug.pack(anchor="w", pady=UI['PAD_ITEM'])
    if BOT_SETTINGS['debug_mode']: switch_debug.select()
    
    def on_light_toggle():
        global full_light_enabled
        full_light_enabled = bool(switch_light.get())
        apply_full_light(full_light_enabled)
        log(f"💡 Full Light: {full_light_enabled}")

    switch_light = ctk.CTkSwitch(frame_switches, text="Full Light (Hack)", command=on_light_toggle, progress_color="#FFA500", **UI['BODY'])
    switch_light.pack(anchor="w", pady=UI['PAD_ITEM'])
    if full_light_enabled: switch_light.select()

    def on_log_toggle():
        global log_visible
        toggle_log_visibility()

    switch_log = ctk.CTkSwitch(frame_switches, text="Console Log", command=on_log_toggle, progress_color="#00FF00", **UI['BODY'])
    switch_log.pack(anchor="w", pady=UI['PAD_ITEM'])
    if BOT_SETTINGS.get('console_log_visible', True): switch_log.select()

    def save_geral():
        BOT_SETTINGS['vocation'] = combo_voc.get()
        BOT_SETTINGS['telegram_chat_id'] = entry_telegram.get()
        update_stats_visibility()
        save_config_file()
        log(f"⚙️ Geral salvo.")

    ctk.CTkButton(tab_geral, text="Salvar Geral", command=save_geral, fg_color="#2CC985", height=32).pack(side="bottom", pady=10, fill="x", padx=20)

    # ==========================================================================
    # 2. ABA TRAINER
    # ==========================================================================
    frame_tr = ctk.CTkFrame(tab_trainer, fg_color="transparent")
    frame_tr.pack(fill="x", pady=UI['PAD_SECTION'][0])
    
    # Delay
    ctk.CTkLabel(frame_tr, text="Delay de Ataque (s):", **UI['H1']).pack(anchor="w", padx=10)
    
    f_dely = ctk.CTkFrame(frame_tr, fg_color="transparent")
    f_dely.pack(fill="x", padx=10, pady=UI['PAD_ITEM'])
    
    ctk.CTkLabel(f_dely, text="Min:", **UI['BODY']).pack(side="left")
    entry_tr_min = ctk.CTkEntry(f_dely, **UI['INPUT'])
    entry_tr_min.pack(side="left", padx=5)
    entry_tr_min.insert(0, str(BOT_SETTINGS.get('trainer_min_delay', 1.0)))
    
    ctk.CTkLabel(f_dely, text="Max:", **UI['BODY']).pack(side="left", padx=(10,0))
    entry_tr_max = ctk.CTkEntry(f_dely, **UI['INPUT'])
    entry_tr_max.pack(side="left", padx=5)
    entry_tr_max.insert(0, str(BOT_SETTINGS.get('trainer_max_delay', 2.0)))
    
    # Range
    ctk.CTkLabel(frame_tr, text="Distância (SQM):", **UI['H1']).pack(anchor="w", padx=10, pady=(15,0))
    
    f_rng = ctk.CTkFrame(frame_tr, fg_color="transparent")
    f_rng.pack(fill="x", padx=10, pady=UI['PAD_ITEM'])
    
    entry_tr_range = ctk.CTkEntry(f_rng, **UI['INPUT'])
    entry_tr_range.pack(side="left")
    entry_tr_range.insert(0, str(BOT_SETTINGS.get('trainer_range', 1)))
    
    ctk.CTkLabel(f_rng, text="(1 = Melee / 3+ = Distance)", **UI['HINT']).pack(side="left", padx=10)

    # Lógica de Alvo
    ctk.CTkLabel(frame_tr, text="Lógica de Alvo:", **UI['H1']).pack(anchor="w", padx=10, pady=(15,0))
    
    frame_tr_ignore = ctk.CTkFrame(tab_trainer, fg_color="transparent")
    frame_tr_ignore.pack(fill="x", padx=10, pady=5)

    def on_ignore_toggle():
        BOT_SETTINGS['ignore_first'] = bool(switch_ignore.get())
        log(f"🛡️ Ignorar 1º: {BOT_SETTINGS['ignore_first']}")

    switch_ignore = ctk.CTkSwitch(frame_tr_ignore, text="Ignorar 1º Monstro", command=on_ignore_toggle, progress_color="#FFA500", **UI['BODY'])
    switch_ignore.pack(anchor="w")
    if BOT_SETTINGS.get('ignore_first', False): switch_ignore.select()

    ctk.CTkLabel(frame_tr_ignore, text="↳ Ignora o primeiro alvo (útil para Monk).", **UI['HINT']).pack(anchor="w", padx=40)

    # Anti Kill-Steal Prevention
    frame_tr_ks = ctk.CTkFrame(tab_trainer, fg_color="transparent")
    frame_tr_ks.pack(fill="x", padx=10, pady=5)

    def on_ks_toggle():
        BOT_SETTINGS['ks_prevention_enabled'] = bool(switch_ks.get())
        log(f"🛡️ Anti Kill-Steal: {'Ativado' if BOT_SETTINGS['ks_prevention_enabled'] else 'Desativado'}")

    switch_ks = ctk.CTkSwitch(frame_tr_ks, text="Ativar Anti Kill-Steal", command=on_ks_toggle, progress_color="#FF6B6B", **UI['BODY'])
    switch_ks.pack(anchor="w")
    if BOT_SETTINGS.get('ks_prevention_enabled', True): switch_ks.select()

    ctk.CTkLabel(frame_tr_ks, text="↳ Evita atacar criaturas mais próximas de outros players.", **UI['HINT']).pack(anchor="w", padx=40)

    def save_trainer():
        try:
            BOT_SETTINGS['trainer_min_delay'] = float(entry_tr_min.get().replace(',', '.'))
            BOT_SETTINGS['trainer_max_delay'] = float(entry_tr_max.get().replace(',', '.'))
            BOT_SETTINGS['trainer_range'] = int(entry_tr_range.get())
            save_config_file()
            log("⚔️ Trainer salvo!")
        except: log("❌ Erro nos valores.")

    ctk.CTkButton(tab_trainer, text="Salvar Trainer", command=save_trainer, fg_color="#2CC985", height=32).pack(side="bottom", pady=10, fill="x", padx=20)

    # ==========================================================================
    # 3. ABA ALARME
    # ==========================================================================
    frame_alarm = create_grid_frame(tab_alarm)

    # --- VISUAL ALARM ---
    ctk.CTkLabel(tab_alarm, text="Monitorar Criaturas (Visual):", **UI['H1']).pack(anchor="w", padx=10, pady=(0,5))

    switch_visual = ctk.CTkSwitch(tab_alarm, text="Alarme Visual", command=lambda: None, progress_color="#00D9FF", **UI['BODY'])
    switch_visual.pack(anchor="w", padx=UI['PAD_INDENT'], pady=2)
    if BOT_SETTINGS.get('alarm_visual_enabled', True): switch_visual.select()

    ctk.CTkLabel(tab_alarm, text="↳ Detecta criaturas/players não-seguros na tela.", **UI['HINT']).pack(anchor="w", padx=45)

    # Distância
    ctk.CTkLabel(frame_alarm, text="Distância (SQM):", **UI['BODY']).grid(row=0, column=0, sticky="e", padx=10, pady=UI['PAD_ITEM'])
    dist_vals = ["1 SQM", "3 SQM", "5 SQM", "8 SQM (Padrão)", "Tela Toda"]
    combo_alarm = ctk.CTkComboBox(frame_alarm, values=dist_vals, **UI['COMBO'])
    combo_alarm.grid(row=0, column=1, sticky="w")
    
    curr_vis = "Tela Toda" if BOT_SETTINGS['alarm_range'] >= 15 else f"{BOT_SETTINGS['alarm_range']} SQM" if BOT_SETTINGS['alarm_range'] in [1,3,5] else "8 SQM (Padrão)"
    combo_alarm.set(curr_vis)

    # Andares
    ctk.CTkLabel(frame_alarm, text="Monitorar Andares:", **UI['BODY']).grid(row=2, column=0, sticky="e", padx=10, pady=UI['PAD_ITEM'])
    combo_floor = ctk.CTkComboBox(frame_alarm, values=["Padrão", "Superior (+1)", "Inferior (-1)", "Todos (Raio-X)"], **UI['COMBO'])
    combo_floor.grid(row=2, column=1, sticky="w")
    combo_floor.set(BOT_SETTINGS['alarm_floor'])

    # Divisória
    #ctk.CTkFrame(tab_alarm, height=1, fg_color="#444").pack(fill="x", padx=10, pady=10)

    # --- HP ALARM ---
    frame_hp = ctk.CTkFrame(tab_alarm, fg_color="transparent")
    frame_hp.pack(fill="x", padx=5)

    ctk.CTkLabel(frame_hp, text="Monitorar Vida (HP):", **UI['H1']).pack(anchor="w", padx=10, pady=(0,5))

    entry_hp_pct = None 
    def toggle_hp_alarm():
        state = "normal" if switch_hp_alarm.get() else "disabled"
        if entry_hp_pct: entry_hp_pct.configure(state=state)

    switch_hp_alarm = ctk.CTkSwitch(frame_hp, text="Alarme de HP Baixo", command=toggle_hp_alarm, progress_color="#FF5555", **UI['BODY'])
    switch_hp_alarm.pack(anchor="w", padx=UI['PAD_INDENT'])
    if BOT_SETTINGS.get('alarm_hp_enabled', False): switch_hp_alarm.select()

    f_hp_val = ctk.CTkFrame(frame_hp, fg_color="transparent")
    f_hp_val.pack(fill="x", padx=UI['PAD_INDENT'], pady=2)
    
    ctk.CTkLabel(f_hp_val, text="Disparar se <", **UI['BODY']).pack(side="left")
    entry_hp_pct = ctk.CTkEntry(f_hp_val, **UI['INPUT'])
    entry_hp_pct.pack(side="left", padx=5)
    entry_hp_pct.insert(0, str(BOT_SETTINGS.get('alarm_hp_percent', 50)))
    ctk.CTkLabel(f_hp_val, text="%", **UI['BODY']).pack(side="left")
    
    toggle_hp_alarm() # Aplica estado inicial

    # Divisória
    #ctk.CTkFrame(tab_alarm, height=1, fg_color="#444").pack(fill="x", padx=10, pady=10)

    

    # Divisória
    #ctk.CTkFrame(tab_alarm, height=1, fg_color="#444").pack(fill="x", padx=10, pady=10)

    # --- CHAT ALARM ---
    ctk.CTkLabel(tab_alarm, text="Monitorar Chat (Default):", **UI['H1']).pack(anchor="w", padx=10, pady=(0,5))

    def toggle_chat_opts(): pass

    switch_chat = ctk.CTkSwitch(tab_alarm, text="Alarme de Msg Nova", command=toggle_chat_opts, progress_color="#FFA500", **UI['BODY'])
    switch_chat.pack(anchor="w", padx=UI['PAD_INDENT'], pady=2)
    if BOT_SETTINGS.get('alarm_chat_enabled', False): switch_chat.select()

    switch_gm_chat = ctk.CTkSwitch(tab_alarm, text="Pausar se GM falar", command=toggle_chat_opts, progress_color="#FF0000", **UI['BODY'])
    switch_gm_chat.pack(anchor="w", padx=UI['PAD_INDENT'], pady=2)
    if BOT_SETTINGS.get('alarm_chat_gm', True): switch_gm_chat.select()

    def save_alarm():
        try:
            # Range
            raw_range = combo_alarm.get()
            BOT_SETTINGS['alarm_range'] = 15 if "Tela" in raw_range else int(raw_range.split()[0])
            BOT_SETTINGS['alarm_floor'] = combo_floor.get()
            
            # HP
            BOT_SETTINGS['alarm_hp_enabled'] = bool(switch_hp_alarm.get())
            hp_val = int(entry_hp_pct.get())
            BOT_SETTINGS['alarm_hp_percent'] = hp_val

            # Visual
            BOT_SETTINGS['alarm_visual_enabled'] = bool(switch_visual.get())

            # Chat
            BOT_SETTINGS['alarm_chat_enabled'] = bool(switch_chat.get())
            BOT_SETTINGS['alarm_chat_gm'] = bool(switch_gm_chat.get())

            save_config_file()
            log(f"🔔 Alarme salvo.")
        except: log("❌ Erro nos valores.")

    ctk.CTkButton(tab_alarm, text="Salvar Alarme", command=save_alarm, fg_color="#2CC985", height=32).pack(side="bottom", pady=10, fill="x", padx=20)

    # ==========================================================================
    # 4. ABA ALVOS
    # ==========================================================================
    ctk.CTkLabel(tab_alvos, text="Alvos (Target List):", **UI['H1']).pack(pady=(5,0))
    txt_targets = ctk.CTkTextbox(tab_alvos, height=100, font=("Consolas", 10))
    txt_targets.pack(fill="x", padx=5, pady=5)
    txt_targets.insert("0.0", "\n".join(BOT_SETTINGS['targets']))

    ctk.CTkLabel(tab_alvos, text="Segura (Safe List):", **UI['H1']).pack(pady=(5,0))
    txt_safe = ctk.CTkTextbox(tab_alvos, height=140, font=("Consolas", 10))
    txt_safe.pack(fill="x", padx=5, pady=5)
    txt_safe.insert("0.0", "\n".join(BOT_SETTINGS['safe']))

    def save_lists():
        BOT_SETTINGS['targets'][:] = [line.strip() for line in txt_targets.get("0.0", "end").split('\n') if line.strip()]
        BOT_SETTINGS['safe'][:] = [line.strip() for line in txt_safe.get("0.0", "end").split('\n') if line.strip()]
        save_config_file()
        log(f"🎯 Listas salvas.")

    ctk.CTkButton(tab_alvos, text="Salvar Listas", command=save_lists, fg_color="#2CC985", height=32).pack(side="bottom", pady=10, fill="x", padx=20)

    # ==========================================================================
    # 5. ABA LOOT
    # ==========================================================================
    ctk.CTkLabel(tab_loot, text="Configuração de BPs:", **UI['H1']).pack(pady=(10,5))
    
    ctk.CTkLabel(tab_loot, text="Minhas BPs (Não lootear):", **UI['BODY']).pack()
    entry_cont_count = ctk.CTkEntry(tab_loot, **UI['INPUT'])
    entry_cont_count.pack(pady=2)
    entry_cont_count.insert(0, str(BOT_SETTINGS['loot_containers'])) 
    
    ctk.CTkLabel(tab_loot, text="Índice Destino (0=Primeira):", **UI['BODY']).pack(pady=(10,0))
    entry_dest_idx = ctk.CTkEntry(tab_loot, **UI['INPUT'])
    entry_dest_idx.pack(pady=2)
    entry_dest_idx.insert(0, str(BOT_SETTINGS['loot_dest'])) 

    # Options
    frame_loot_opts = ctk.CTkFrame(tab_loot, fg_color="transparent")
    frame_loot_opts.pack(fill="x", padx=10, pady=15)

    def toggle_drop_food(): pass
    
    switch_drop_food = ctk.CTkSwitch(frame_loot_opts, text="Jogar Food no chão se Full", command=toggle_drop_food, progress_color="#FFA500", **UI['BODY'])
    switch_drop_food.pack(anchor="center")
    if BOT_SETTINGS.get('loot_drop_food', False): switch_drop_food.select()

    def save_loot():
        try:
            BOT_SETTINGS['loot_containers'] = int(entry_cont_count.get())
            BOT_SETTINGS['loot_dest'] = int(entry_dest_idx.get())
            BOT_SETTINGS['loot_drop_food'] = bool(switch_drop_food.get())
            save_config_file()
            log(f"💰 Loot salvo.")
        except: log("❌ Use números inteiros.")

    ctk.CTkButton(tab_loot, text="Salvar Loot", command=save_loot, fg_color="#2CC985", height=32).pack(side="bottom", pady=10, fill="x", padx=20)

    # ==========================================================================
    # 6. ABA FISHER
    # ==========================================================================
    frame_fish = create_grid_frame(tab_fisher)

    ctk.CTkLabel(frame_fish, text="Tentativas:", **UI['BODY']).grid(row=0, column=0, sticky="e", padx=10, pady=2)
    f_att = ctk.CTkFrame(frame_fish, fg_color="transparent")
    f_att.grid(row=0, column=1, sticky="w")
    
    entry_fish_min = ctk.CTkEntry(f_att, **UI['INPUT'])
    entry_fish_min.pack(side="left")
    entry_fish_min.insert(0, str(BOT_SETTINGS['fisher_min']))
    
    ctk.CTkLabel(f_att, text="a", **UI['BODY']).pack(side="left", padx=5)
    
    entry_fish_max = ctk.CTkEntry(f_att, **UI['INPUT'])
    entry_fish_max.pack(side="left")
    entry_fish_max.insert(0, str(BOT_SETTINGS['fisher_max']))

    # Cap Control
    ctk.CTkLabel(frame_fish, text="Min Cap:", **UI['BODY']).grid(row=1, column=0, sticky="e", padx=10, pady=5)
    entry_fish_cap_val = ctk.CTkEntry(frame_fish, **UI['INPUT'])
    entry_fish_cap_val.grid(row=1, column=1, sticky="w")
    entry_fish_cap_val.insert(0, str(BOT_SETTINGS.get('fisher_min_cap', 10.0)))

    # Switches Fisher
    frame_fish_opts = ctk.CTkFrame(tab_fisher, fg_color="transparent")
    frame_fish_opts.pack(pady=10)

    def toggle_dummy(): pass

    switch_fish_cap = ctk.CTkSwitch(frame_fish_opts, text="Pausar se Cap Baixa", command=toggle_dummy, progress_color="#FFA500", **UI['BODY'])
    switch_fish_cap.pack(anchor="w", padx=UI['PAD_INDENT'], pady=2)
    if BOT_SETTINGS.get('fisher_check_cap', True): switch_fish_cap.select()

    switch_fatigue = ctk.CTkSwitch(frame_fish_opts, text="Simular Fadiga Humana", command=toggle_dummy, progress_color="#FFA500", **UI['BODY'])
    switch_fatigue.pack(anchor="w", padx=UI['PAD_INDENT'], pady=2)
    if BOT_SETTINGS.get('fisher_fatigue', True): switch_fatigue.select()
    
    ctk.CTkLabel(frame_fish_opts, text="↳ Cria pausas e lentidão progressiva.", **UI['HINT']).pack(anchor="w", padx=45)

    def save_fish():
        try:
            mn = int(entry_fish_min.get())
            mx = int(entry_fish_max.get())
            cap_val = float(entry_fish_cap_val.get().replace(',', '.'))
            check_cap = bool(switch_fish_cap.get())
            fatigue_enabled = bool(switch_fatigue.get())
            
            if mn < 1: mn=1
            if mx < mn: mx=mn
            
            BOT_SETTINGS['fisher_min'] = mn
            BOT_SETTINGS['fisher_max'] = mx
            BOT_SETTINGS['fisher_min_cap'] = cap_val
            BOT_SETTINGS['fisher_check_cap'] = check_cap
            BOT_SETTINGS['fisher_fatigue'] = fatigue_enabled
            save_config_file()
            config.CHECK_MIN_CAP = check_cap
            config.MIN_CAP_VALUE = cap_val
            log(f"🎣 Fisher salvo.")
        except: log("❌ Erro nos valores.")

    ctk.CTkButton(tab_fisher, text="Salvar Fisher", command=save_fish, fg_color="#2CC985", height=32).pack(side="bottom", pady=10, fill="x", padx=20)

    # ==========================================================================
    # 7. ABA RUNE (ESTILO COMPACTO)
    # ==========================================================================
    
    # Helper Label Update
    def update_rune_pos_labels():
        lbl_work_pos.configure(text=str(BOT_SETTINGS.get('rune_work_pos', (0,0,0))))
        lbl_safe_pos.configure(text=str(BOT_SETTINGS.get('rune_safe_pos', (0,0,0))))

    def set_rune_pos(type_pos):
        if pm:
            try:
                x = pm.read_int(base_addr + 0x1D16F0) # OFFSET_PLAYER_X
                y = pm.read_int(base_addr + 0x1D16EC) # OFFSET_PLAYER_Y
                z = pm.read_int(base_addr + 0x1D16E8) # OFFSET_PLAYER_Z
                
                key = 'rune_work_pos' if type_pos == "WORK" else 'rune_safe_pos'
                BOT_SETTINGS[key] = (x, y, z)
                update_rune_pos_labels()
                log(f"📍 {type_pos} definido: {x}, {y}, {z}")
            except: log("❌ Logue no char.")

    # Frame Craft
    frame_craft = ctk.CTkFrame(tab_rune, fg_color="#2b2b2b")
    frame_craft.pack(fill="x", padx=5, pady=2)
    
    ctk.CTkLabel(frame_craft, text="⚙️ Crafting", **UI['H1']).pack(anchor="w", padx=5, pady=(5,5))
    
    f_c1 = ctk.CTkFrame(frame_craft, fg_color="transparent")
    f_c1.pack(fill="x", padx=2, pady=2)
    
    ctk.CTkLabel(f_c1, text="Mana:", **UI['BODY']).pack(side="left", padx=5)
    entry_mana = ctk.CTkEntry(f_c1, **UI['INPUT'])
    entry_mana.configure(width=45)
    entry_mana.pack(side="left", padx=2)
    entry_mana.insert(0, str(BOT_SETTINGS['rune_mana']))
    
    ctk.CTkLabel(f_c1, text="Key:", **UI['BODY']).pack(side="left", padx=5)
    entry_hk = ctk.CTkEntry(f_c1, **UI['INPUT'])
    entry_hk.configure(width=35)
    entry_hk.pack(side="left", padx=2)
    entry_hk.insert(0, BOT_SETTINGS['rune_hotkey'])
    
    ctk.CTkLabel(f_c1, text="Hand:", **UI['BODY']).pack(side="left", padx=5)
    combo_hand = ctk.CTkComboBox(f_c1, values=["RIGHT", "LEFT", "BOTH"], **UI['COMBO'])
    combo_hand.configure(width=70)
    combo_hand.pack(side="left", padx=2)
    combo_hand.set(BOT_SETTINGS['rune_hand'])

    # Frame Human
    frame_human = ctk.CTkFrame(tab_rune, fg_color="#2b2b2b")
    frame_human.pack(fill="x", padx=5, pady=2)
    
    f_h1 = ctk.CTkFrame(frame_human, fg_color="transparent")
    f_h1.pack(fill="x", padx=2, pady=5)
    
    ctk.CTkLabel(f_h1, text="Wait:", **UI['BODY']).pack(side="left", padx=5)
    entry_human_min = ctk.CTkEntry(f_h1, **UI['INPUT'])
    entry_human_min.configure(width=35)
    entry_human_min.pack(side="left", padx=2)
    entry_human_min.insert(0, str(BOT_SETTINGS.get('rune_human_min', 5)))
    
    ctk.CTkLabel(f_h1, text="to", **UI['BODY']).pack(side="left", padx=2)
    entry_human_max = ctk.CTkEntry(f_h1, **UI['INPUT'])
    entry_human_max.configure(width=35)
    entry_human_max.pack(side="left", padx=2)
    entry_human_max.insert(0, str(BOT_SETTINGS.get('rune_human_max', 30)))
    ctk.CTkLabel(f_h1, text="sec (action)", **UI['BODY']).pack(side="left", padx=2)

    # Frame Move
    frame_move = ctk.CTkFrame(tab_rune, fg_color="#2b2b2b")
    frame_move.pack(fill="x", padx=5, pady=5)
    ctk.CTkLabel(frame_move, text="🚨 Anti-PK / Movimento", **UI['H1']).pack(anchor="w", padx=5, pady=(5,5))

    # Toggle
    f_m1 = ctk.CTkFrame(frame_move, fg_color="transparent")
    f_m1.pack(fill="x", padx=2, pady=2)
    switch_movement = ctk.CTkSwitch(f_m1, text="Fugir para Safe", width=50, height=20, font=UI['BODY']['font'])
    switch_movement.pack(side="left", padx=5)
    if BOT_SETTINGS.get('rune_movement', False): switch_movement.select()

    # Coords
    f_wk = ctk.CTkFrame(frame_move, fg_color="transparent")
    f_wk.pack(fill="x", pady=2)
    ctk.CTkButton(f_wk, text="Set Work", width=60, height=20, font=("Verdana", 9), fg_color="#444", command=lambda: set_rune_pos("WORK")).pack(side="left", padx=5)
    lbl_work_pos = ctk.CTkLabel(f_wk, text=str(BOT_SETTINGS.get('rune_work_pos', (0,0,0))), **UI['HINT'])
    lbl_work_pos.pack(side="left", padx=5)

    f_sf = ctk.CTkFrame(frame_move, fg_color="transparent")
    f_sf.pack(fill="x", pady=2)
    ctk.CTkButton(f_sf, text="Set Safe", width=60, height=20, font=("Verdana", 9), fg_color="#444", command=lambda: set_rune_pos("SAFE")).pack(side="left", padx=5)
    lbl_safe_pos = ctk.CTkLabel(f_sf, text=str(BOT_SETTINGS.get('rune_safe_pos', (0,0,0))), **UI['HINT'])
    lbl_safe_pos.pack(side="left", padx=5)

    # Delays
    f_m2 = ctk.CTkFrame(frame_move, fg_color="transparent")
    f_m2.pack(fill="x", padx=5, pady=5)
    ctk.CTkLabel(f_m2, text="React:", **UI['BODY']).pack(side="left")
    entry_flee = ctk.CTkEntry(f_m2, **UI['INPUT'])
    entry_flee.configure(width=35)
    entry_flee.pack(side="left", padx=2)
    entry_flee.insert(0, str(BOT_SETTINGS.get('rune_flee_delay', 0.5)))
    
    ctk.CTkLabel(f_m2, text="Ret:", **UI['BODY']).pack(side="left", padx=5)
    entry_ret_delay = ctk.CTkEntry(f_m2, **UI['INPUT'])
    entry_ret_delay.configure(width=35)
    entry_ret_delay.pack(side="left", padx=2)
    entry_ret_delay.insert(0, str(BOT_SETTINGS.get('rune_return_delay', 300)))

    # Frame Extras
    frame_extras = ctk.CTkFrame(tab_rune, fg_color="#2b2b2b")
    frame_extras.pack(fill="x", padx=5, pady=2)
    ctk.CTkLabel(frame_extras, text="Outros", **UI['H1']).pack(anchor="w", padx=5, pady=5)
    
    switch_eat = ctk.CTkSwitch(frame_extras, text="Auto Eat", width=60, height=20, font=UI['BODY']['font'])
    switch_eat.pack(anchor="w", padx=10, pady=2)
    if BOT_SETTINGS['auto_eat']: switch_eat.select()

    switch_train = ctk.CTkSwitch(frame_extras, text="Mana Train (No rune)", width=60, height=20, font=UI['BODY']['font'])
    switch_train.pack(anchor="w", padx=10, pady=2)
    if BOT_SETTINGS['mana_train']: switch_train.select()

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
        except: log("❌ Erro Rune.")

    ctk.CTkButton(tab_rune, text="Salvar Rune", command=save_rune, height=32, fg_color="#00A86B", hover_color="#008f5b").pack(side="bottom", fill="x", padx=20, pady=5)

    # ==========================================================================
    # 8. ABA CAVEBOT (REFORMULADA - ESTILO ZION)
    # ==========================================================================
    
    # Container para compactar a aba Cavebot
    frame_cb_root = ctk.CTkFrame(tab_cavebot, fg_color="transparent")
    frame_cb_root.pack(fill="both", expand=True, padx=4, pady=4)
    frame_cb_root.grid_columnconfigure(0, weight=1)
    frame_cb_root.grid_columnconfigure(1, weight=2)

    # --- COLUNA ESQUERDA: CONTROLES E MATRIZ ---
    frame_cb_left = ctk.CTkFrame(frame_cb_root, fg_color="transparent")
    frame_cb_left.grid(row=0, column=0, sticky="nsew", padx=(0, 3), pady=2)

    # 0. Status do Cavebot (Posição Atual + Waypoint Alvo)
    label_cavebot_status = ctk.CTkLabel(frame_cb_left, text="📍 Posição: ---", **UI['BODY'])
    label_cavebot_status.pack(anchor="w", pady=(0, 10), fill="x")

    ctk.CTkFrame(frame_cb_left, height=1, fg_color="#555").pack(fill="x", pady=5)

    # 1. Gravação Automática
    ctk.CTkLabel(frame_cb_left, text="Gravação Automática", **UI['H1']).pack(anchor="w", pady=(0,2))
    
    switch_rec_var = ctk.IntVar(value=1 if is_recording_waypoints else 0)
    def on_rec_toggle(): toggle_recording_func(switch_rec_var.get())
    
    btn_rec_toggle = ctk.CTkSwitch(frame_cb_left, text="Gravar Waypoints", 
                                  command=on_rec_toggle, variable=switch_rec_var,
                                  progress_color="#FF5555", **UI['BODY'])
    btn_rec_toggle.pack(anchor="w", pady=4)
    
    ctk.CTkFrame(frame_cb_left, height=2, fg_color="#444").pack(fill="x", pady=10)

    # 2. Adição Manual - SIMPLIFICADO
    ctk.CTkLabel(frame_cb_left, text="Adição Manual", **UI['H1']).pack(anchor="w", pady=(0,2))

    ctk.CTkLabel(frame_cb_left, text="Clique no botão ou insira coordenadas:",
                **UI['HINT']).pack(anchor="w", pady=(0, 5))

    # Botão: Adicionar WP na posição atual
    btn_add_here = ctk.CTkButton(
        frame_cb_left,
        text="Adicionar WP",
        command=lambda: add_manual_waypoint(0, 0, "walk"),  # dx=0, dy=0 = posição atual
        fg_color="#2CC985",
        hover_color="#1FA86E",
        **UI['BUTTON_SM']
    )
    btn_add_here.pack(fill="x", padx=20, pady=5)

    # Botão: Inserir coordenadas manualmente
    btn_add_coords = ctk.CTkButton(
        frame_cb_left,
        text="Inserir Coords (X, Y, Z)",
        command=open_insert_coords_dialog,
        fg_color="#3B8ED0",
        hover_color="#2B6EA0",
        **UI['BUTTON_SM']
    )
    btn_add_coords.pack(fill="x", padx=20, pady=(5, 0))

    # --- COLUNA DIREITA: LISTA E ARQUIVOS ---
    frame_cb_right = ctk.CTkFrame(frame_cb_root, fg_color="transparent")
    frame_cb_right.grid(row=0, column=1, sticky="nsew", padx=(3, 0), pady=2)
    
    ctk.CTkLabel(frame_cb_right, text="Lista de Waypoints", **UI['H1']).pack(anchor="w")
    
    # Botões de Arquivo (Topo da lista)
    frame_files = ctk.CTkFrame(frame_cb_right, fg_color="transparent")
    frame_files.pack(fill="x", pady=5)

    # Linha 1: Nome do script + salvar
    frame_file_row1 = ctk.CTkFrame(frame_files, fg_color="transparent")
    frame_file_row1.pack(fill="x", pady=2)

    #ctk.CTkLabel(frame_file_row1, text="Nome:", **UI['BODY']).pack(side="left", padx=2)
    entry_waypoint_name = ctk.CTkEntry(frame_file_row1, **UI['INPUT_MED'])
    entry_waypoint_name.pack(side="left", padx=4, fill="x", expand=True)
    if current_waypoints_filename:
        entry_waypoint_name.insert(0, current_waypoints_filename)

    ctk.CTkButton(frame_file_row1, text="💾", command=save_waypoints_file, width=25, **UI['BUTTON_SM']).pack(side="left", padx=2)
    ctk.CTkButton(frame_file_row1, text="🧹", command=clear_waypoints, width=25, fg_color="#e74c3c", **UI['BUTTON_SM']).pack(side="left", padx=2)

    # Linha 2: Lista de scripts existentes + carregar
    frame_file_row2 = ctk.CTkFrame(frame_files, fg_color="transparent")
    frame_file_row2.pack(fill="x", pady=2)

    #ctk.CTkLabel(frame_file_row2, text="Scripts:", **UI['BODY']).pack(side="left", padx=4)
    combo_cavebot_scripts = ctk.CTkComboBox(frame_file_row2, values=[], **UI['COMBO_MED'])
    combo_cavebot_scripts.pack(side="left", padx=4, fill="x", expand=True)

    ctk.CTkButton(frame_file_row2, text="📂", command=load_waypoints_file, width=25, **UI['BUTTON_SM']).pack(side="left", padx=2)
    ctk.CTkButton(frame_file_row2, text="🔄", command=lambda: refresh_cavebot_scripts_combo(selected=current_waypoints_filename), width=25, **UI['BUTTON_SM']).pack(side="left", padx=2)

    # Inicializa combo e campo de nome
    refresh_cavebot_scripts_combo(selected=current_waypoints_filename or None)
    if not current_waypoints_filename and combo_cavebot_scripts.winfo_exists():
        # Se não houver nome corrente mas houver scripts, pré-seleciona o primeiro
        current = combo_cavebot_scripts.get()
        if current:
            _set_waypoint_name_field(current)

    # Lista (Log)
    txt_waypoints_settings = ctk.CTkTextbox(frame_cb_right, font=("Consolas", 10), state="disabled")
    txt_waypoints_settings.pack(fill="both", expand=True, pady=5)

    # Frame para botões de remoção (lado a lado)
    frame_remove_buttons = ctk.CTkFrame(frame_cb_right, fg_color="transparent")
    frame_remove_buttons.pack(fill="x", pady=(5, 0))
    frame_remove_buttons.grid_columnconfigure(0, weight=1)
    frame_remove_buttons.grid_columnconfigure(1, weight=1)

    # Botão: Remover Último WP
    btn_remove_last = ctk.CTkButton(
        frame_remove_buttons,
        text="Remover Último",
        command=remove_last_waypoint,
        fg_color="#FF5555",
        hover_color="#CC4444",
        height=30,
        font=("Verdana", 9)
    )
    btn_remove_last.grid(row=0, column=0, padx=(0, 5), sticky="ew")

    # Botão: Remover Específico (com input)
    btn_remove_specific = ctk.CTkButton(
        frame_remove_buttons,
        text="❌Remover WP #",
        command=open_remove_specific_dialog,
        fg_color="#D95050",
        hover_color="#B03030",
        height=30,
        font=("Verdana", 9)
    )
    btn_remove_specific.grid(row=0, column=1, padx=(5, 0), sticky="ew")

    # Botão: Gerar Visualização da Rota
    btn_visualize = ctk.CTkButton(
        frame_remove_buttons,
        text="🗺️ Gerar Imagem da Rota",
        command=generate_route_visualization,
        fg_color="#4A90E2",
        hover_color="#357ABD",
        height=30,
        font=("Verdana", 9)
    )
    btn_visualize.grid(row=1, column=0, columnspan=2, padx=(0, 0), sticky="ew", pady=(5, 0))

    # Botão: Editor Visual de Waypoints
    btn_editor = ctk.CTkButton(
        frame_remove_buttons,
        text="🗺️ Editor Visual de Waypoints",
        command=open_waypoint_editor_window,
        fg_color="#2E8B57",
        hover_color="#228B45",
        height=30,
        font=("Verdana", 9)
    )
    btn_editor.grid(row=2, column=0, columnspan=2, padx=(0, 0), sticky="ew", pady=(5, 0))

    # Inicializa lista visual
    update_waypoint_display()

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

    print("[XRAY] toggle_xray() chamado")

    if xray_window is not None:
        print("[XRAY] Fechando janela existente")
        xray_window.destroy()
        xray_window = None
        btn_xray.configure(fg_color="#303030")
        return

    print("[XRAY] Criando nova janela X-Ray")
    btn_xray.configure(fg_color="#2CC985")

    xray_window = ctk.CTkToplevel(app)
    xray_window.overrideredirect(True)
    xray_window.attributes("-topmost", True)
    xray_window.attributes("-transparentcolor", "black")
    xray_window.config(bg="black")
    print("[XRAY] Janela criada com sucesso")

    def update_xray():
        if not xray_window or not xray_window.winfo_exists():
            print("[XRAY] Janela não existe mais, saindo")
            return

        try:
            hwnd = win32gui.FindWindow("TibiaClient", None) or win32gui.FindWindow(None, "Tibia")
            #print(f"[XRAY] hwnd={hwnd}")

            if not hwnd:
                #print("[XRAY] Tibia não encontrado")
                xray_window.after(100, update_xray)
                return

            active_hwnd = win32gui.GetForegroundWindow()
            if hwnd and active_hwnd != hwnd:
                canvas.delete("all")
                xray_window.after(100, update_xray)
                return

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

            #print(f"[XRAY] pm={pm}, base_addr={base_addr}")

            if pm is not None:
                gv = get_game_view(pm, base_addr)
                my_x, my_y, my_z = get_player_pos(pm, base_addr)
                #print(f"[XRAY] gv={gv}, pos=({my_x},{my_y},{my_z})")

                if hud_overlay_data and gv:
                    #print(f"[XRAY] HUD overlay: {len(hud_overlay_data)} itens")
                    for item in hud_overlay_data:
                        dx = item.get('dx')
                        dy = item.get('dy')
                        raw_color = item.get('color', '#FFFFFF')
                        text = item.get('text', '')

                        color = raw_color[:7] if len(raw_color) > 7 else raw_color
                        is_transparent = len(raw_color) > 7

                        raw_cx = gv['center'][0] + (dx * gv['sqm'])
                        raw_cy = gv['center'][1] + (dy * gv['sqm'])

                        cx = raw_cx + offset_x
                        cy = raw_cy + offset_y

                        size = gv['sqm'] / 2

                        stipple_val = 'gray50' if is_transparent else ''
                        width_val = 1 if is_transparent else 2

                        canvas.create_rectangle(cx - size, cy - size, cx + size, cy + size,
                                              outline=color, width=width_val, stipple=stipple_val)

                        if text:
                            canvas.create_text(cx+1, cy+1, text=text, fill="black", font=("Verdana", 8, "bold"))
                            canvas.create_text(cx, cy, text=text, fill=color, font=("Verdana", 8, "bold"))

                current_name = get_player_name()
                first = base_addr + TARGET_ID_PTR + REL_FIRST_ID

                creatures_found = 0
                creatures_other_floor = 0

                for i in range(MAX_CREATURES):
                    slot = first + (i * STEP_SIZE)
                    creature_id = pm.read_int(slot)
                    if creature_id > 0:
                        creatures_found += 1
                        vis = pm.read_int(slot + OFFSET_VISIBLE)
                        cz = pm.read_int(slot + OFFSET_Z)
                        name_bytes = pm.read_bytes(slot + OFFSET_NAME, 32)
                        name = name_bytes.split(b'\x00')[0].decode('latin-1', errors='ignore')

                        # Debug: mostrar todas as criaturas (descomente para debug)
                        # if i < 5:
                        #     print(f"[XRAY] Slot {i}: {name} vis={vis} z={cz} (my_z={my_z})")

                        # Apenas criaturas visíveis (vis=1) e em outros andares
                        if vis == 1 and cz != my_z:
                            creatures_other_floor += 1
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

                                #print(f"[XRAY] DESENHANDO: {name} em ({sx},{sy}) cor={color}")
                                canvas.create_text(sx, sy - 40, text=f"{tag} {zdiff}\n{name}", fill=color, font=("Verdana", 10, "bold"))
                                canvas.create_rectangle(sx-20, sy-20, sx+20, sy+20, outline=color, width=2)

                #wprint(f"[XRAY] Total: {creatures_found} criaturas, {creatures_other_floor} em outros andares")
            else:
                print("[XRAY] pm is None!")

        except Exception as e:
            print(f"[XRAY] ERRO: {e}")
            import traceback
            traceback.print_exc()

        xray_window.after(500, update_xray)  # 500ms para não spammar logs

    print("[XRAY] Criando canvas")
    canvas = tk.Canvas(xray_window, bg="black", highlightthickness=0)
    canvas.pack(fill="both", expand=True)
    print("[XRAY] Canvas criado, iniciando update_xray()")
    update_xray()

def on_reload():
    """Reload: Fecha o bot e reinicia o main.py com código atualizado."""
    print("🔄 Iniciando reload...")
    state.stop()
    clear_player_name_cache()

    try:
        if app:
            app.quit()
            app.destroy()
    except: pass

    import subprocess
    import sys
    import os

    # Reinicia o processo main.py com caminho absoluto
    script_path = os.path.abspath(__file__)
    subprocess.Popen([sys.executable, script_path])
    os._exit(0)

def on_close():
    print("Encerrando bot e threads...")
    state.stop()
    clear_player_name_cache()

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
# MINIMAP VISUALIZATION FUNCTIONS
# ==============================================================================

def create_minimap_panel():
    """Create minimap panel (shown automatically when cavebot is active)."""
    global minimap_container, minimap_label, minimap_title_label, minimap_status_label, minimap_visualizer

    # Container frame (NÃO empacotado - será mostrado quando cavebot ligar)
    minimap_container = ctk.CTkFrame(
        main_frame,
        fg_color="#1a1a1a",
        border_color="#303030",
        border_width=1,
        corner_radius=6
    )
    # NÃO chamar pack() aqui - minimap começa escondido

    # Title label (waypoint info)
    minimap_title_label = ctk.CTkLabel(
        minimap_container,
        text="",
        font=("Verdana", 11, "bold"),
        text_color="#FFFFFF"
    )
    minimap_title_label.pack(pady=(8, 0))

    # Label to display minimap image
    minimap_label = ctk.CTkLabel(
        minimap_container,
        text="⏳ Aguardando Cavebot...",
        font=("Verdana", 10),
        text_color="#888888"
    )
    minimap_label.pack(padx=10, pady=5)

    # Status label (below image)
    minimap_status_label = ctk.CTkLabel(
        minimap_container,
        text="",
        font=("Verdana", 10),
        text_color="#AAAAAA"
    )
    minimap_status_label.pack(pady=(0, 8))

    # Initialize visualizer
    from utils.realtime_minimap import RealtimeMinimapVisualizer
    from utils.color_palette import COLOR_PALETTE
    minimap_visualizer = RealtimeMinimapVisualizer(
        MAPS_DIRECTORY,
        WALKABLE_COLORS,
        COLOR_PALETTE
    )

def show_minimap_panel():
    """Show minimap panel and resize GUI."""
    global minimap_container
    if minimap_container and not minimap_container.winfo_ismapped():
        minimap_container.pack(fill="x", padx=10, pady=5)
        app.after(100, auto_resize_window)

def hide_minimap_panel():
    """Hide minimap panel and resize GUI."""
    global minimap_container
    if minimap_container and minimap_container.winfo_ismapped():
        minimap_container.pack_forget()
        app.after(100, auto_resize_window)

def update_minimap_loop():
    """Auto-scheduled loop to update minimap every 3 seconds."""
    global minimap_label, minimap_image_ref, minimap_visualizer, cavebot_instance

    # Check if widget exists
    if not minimap_label or not minimap_label.winfo_exists():
        return

    try:
        # Check if Cavebot is active (panel is hidden when inactive, just reschedule)
        if not cavebot_instance or not switch_cavebot.get():
            app.after(1000, update_minimap_loop)
            return

        # Collect Cavebot data (thread-safe)
        try:
            player_pos = get_player_pos(pm, base_addr)

            with cavebot_instance._waypoints_lock:
                all_waypoints = cavebot_instance._waypoints.copy()
                current_idx = cavebot_instance._current_index

            # Collect cavebot status (thread-safe string read)
            cavebot_status = cavebot_instance.state_message

            if not all_waypoints:
                minimap_label.configure(
                    image=None,
                    text="📍 Nenhum Waypoint Configurado"
                )
                app.after(3000, update_minimap_loop)
                return

            target_wp = all_waypoints[current_idx]
            global_route = cavebot_instance.current_global_path.copy() if cavebot_instance.current_global_path else None
            local_cache = cavebot_instance.local_path_cache.copy() if cavebot_instance.local_path_cache else None

        except Exception as e:
            print(f"[Minimap] Erro ao coletar dados: {e}")
            app.after(3000, update_minimap_loop)
            return

        # Generate minimap image
        pil_img = minimap_visualizer.generate_minimap(
            player_pos,
            target_wp,
            all_waypoints,
            global_route,
            local_cache,
            current_wp_index=current_idx,
            enable_dynamic_zoom=True
        )

        # Limit max size to prevent breaking layout
        max_width = 600
        max_height = 400
        if pil_img.width > max_width or pil_img.height > max_height:
            ratio = min(max_width / pil_img.width, max_height / pil_img.height)
            new_size = (int(pil_img.width * ratio), int(pil_img.height * ratio))
            pil_img = pil_img.resize(new_size, Image.LANCZOS)

        # Create CTkImage
        ctk_img = ctk.CTkImage(
            light_image=pil_img,
            dark_image=pil_img,
            size=(pil_img.width, pil_img.height)
        )

        # Update widgets
        minimap_label.configure(image=ctk_img, text="")
        minimap_image_ref = ctk_img  # Keep reference for garbage collection

        # Update title label
        wp_num = current_idx + 1
        minimap_title_label.configure(text=f"Indo até Waypoint #{wp_num}/{len(all_waypoints)}")

        # Update status label with color coding
        status_text = cavebot_status if cavebot_status else ""
        status_color = "#FFFFFF"  # Default white

        if "Stuck" in status_text or "⚠️" in status_text or "🧱" in status_text:
            status_color = "#FF6464"  # Red for warnings/stuck
        elif "✅" in status_text or "alcançado" in status_text:
            status_color = "#64FF64"  # Green for success
        elif "Recalculando" in status_text or "🔄" in status_text:
            status_color = "#FFC864"  # Yellow for processing
        elif "Pausado" in status_text or "⏸️" in status_text:
            status_color = "#C8C8C8"  # Gray for paused
        elif "Cooldown" in status_text or "⏰" in status_text:
            status_color = "#9696FF"  # Light blue for cooldown

        minimap_status_label.configure(text=status_text, text_color=status_color)

        # Auto-resize GUI to fit minimap content
        app.after(50, auto_resize_window)

    except Exception as e:
        print(f"[Minimap] Erro ao atualizar: {e}")
        minimap_label.configure(
            image=None,
            text=f"❌ Erro: {str(e)[:50]}"
        )

    # Schedule next update
    app.after(3000, update_minimap_loop)

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

# Botão de Reload (visível apenas se RELOAD_BUTTON = True em config.py)
if config.RELOAD_BUTTON:
    btn_reload = ctk.CTkButton(frame_header, text="🔄", command=on_reload, width=35, height=25, fg_color="#303030", hover_color="#505050", font=("Verdana", 10))
    btn_reload.pack(side="right", padx=5)

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

switch_cavebot_var = ctk.IntVar(value=0)
switch_cavebot = ctk.CTkSwitch(frame_controls, text="Cavebot", 
                              variable=switch_cavebot_var, 
                              command=toggle_cavebot_func,
                              progress_color="#2CC985", 
                              font=("Verdana", 11))
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
lbl_regen = ctk.CTkLabel(frame_stats, text="🍖 --:--", font=("Verdana", 10, "bold"), text_color="gray")
lbl_regen.grid(row=2, column=0, padx=10, pady=2, sticky="w")

# LINHA 3: RECURSOS (Gold + Regen Stock)
# Usamos um frame container para organizar Esquerda vs Direita
frame_resources = ctk.CTkFrame(frame_stats, fg_color="transparent")
frame_resources.grid(row=3, column=0, columnspan=2, sticky="ew", padx=10, pady=2)

# Coluna Esquerda: Regen Stock
lbl_regen_stock = ctk.CTkLabel(frame_resources, text="🍖 --", font=("Verdana", 10))
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

# MINIMAP PANEL
create_minimap_panel()

# LOG
# Sincroniza log_visible com BOT_SETTINGS
log_visible = BOT_SETTINGS.get('console_log_visible', True)
txt_log = ctk.CTkTextbox(main_frame, height=120, font=("Consolas", 11), fg_color="#151515", text_color="#00FF00", border_width=1)
if log_visible:
    txt_log.pack(side="bottom", fill="x", padx=5, pady=5, expand=True)

# ==============================================================================
# 8. EXECUÇÃO PRINCIPAL
# ==============================================================================

app.after(1000, attach_window)
app.protocol("WM_DELETE_WINDOW", on_close)

# Iniciar Threads
threading.Thread(target=start_trainer_thread, daemon=True).start()
threading.Thread(target=start_alarm_thread, daemon=True).start()
threading.Thread(target=combat_loot_monitor_thread, daemon=True).start()
threading.Thread(target=auto_loot_thread, daemon=True).start()
threading.Thread(target=skill_monitor_loop, daemon=True).start()
threading.Thread(target=gui_updater_loop, daemon=True).start()
threading.Thread(target=regen_monitor_loop, daemon=True).start()
threading.Thread(target=auto_fisher_thread, daemon=True).start()
threading.Thread(target=runemaker_thread, daemon=True).start()
threading.Thread(target=connection_watchdog, daemon=True).start()
threading.Thread(target=start_cavebot_thread, daemon=True).start()
threading.Thread(target=auto_recorder_loop, daemon=True).start()

update_stats_visibility()

# Iniciar loop de atualização do minimap
app.after(1000, update_minimap_loop)

log("🚀 Iniciado.")
app.mainloop()
state.stop()  # Garante que todas as threads encerrem ao fechar
