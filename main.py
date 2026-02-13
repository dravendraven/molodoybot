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
import psutil # Para monitoramento de CPU e RAM
from utils.timing import gauss_wait
from datetime import datetime
from PIL import Image # Import necessário para imagens
# matplotlib será carregado sob demanda (lazy loading) para acelerar o startup
plt = None
FigureCanvasTkAgg = None

def setup_matplotlib():
    """Carrega matplotlib apenas quando necessário (lazy loading)"""
    global plt, FigureCanvasTkAgg
    if plt is None:
        import matplotlib
        matplotlib.use("TkAgg")
        import matplotlib.pyplot as plt_module
        from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg as Canvas
        plt = plt_module
        FigureCanvasTkAgg = Canvas
    return plt, FigureCanvasTkAgg
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
from modules.spear_picker import spear_picker_loop
from modules.aimbot import AimbotModule
from modules.debug_monitor import init_debug_monitor, show_debug_monitor
from core.player_core import get_connected_char_name
from core.bot_state import state
from core.action_scheduler import init_scheduler, get_scheduler, stop_scheduler
from core.game_state import game_state, init_game_state, shutdown_game_state
from core.overlay_renderer import renderer as overlay_renderer
from core.chat_handler import ChatHandler
from gui.settings_window import SettingsWindow, SettingsCallbacks
from gui.main_window import MainWindow, MainWindowCallbacks
#import corpses

# Sniffer de pacotes (opcional - requer Npcap e execução como Admin)
try:
    from core.sniffer import start_sniffer, stop_sniffer, get_sniffer
    SNIFFER_AVAILABLE = True
except ImportError:
    SNIFFER_AVAILABLE = False
    def start_sniffer(*args, **kwargs): return None
    def stop_sniffer(): pass
    def get_sniffer(): return None


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

toplevel_settings = None  # DEPRECATED - usar settings_window
settings_window = None  # Nova instância da janela de settings (SettingsWindow)
main_window = None  # Nova instância da janela principal (MainWindow)
CONFIG_FILE = "bot_config.json"

# Estado Global do Bot
BOT_SETTINGS = {
    # Geral
    "telegram_chat_id": TELEGRAM_CHAT_ID, # Do config.py
    "vocation": "Knight",
    "debug_mode": config.DEBUG_MODE,  # Controlado via config.py
    "hit_log_enabled": HIT_LOG_ENABLED,
    "client_path": "",  # Caminho da pasta do cliente (para GlobalMap)
    "lookid_enabled": False,  # Exibir ID dos items ao dar look
    "spear_picker_enabled": False,  # Pegar spears do chao automaticamente (Paladin)
    "spear_max_count": 3,  # Maximo de spears para manter na mao
    "follow_before_attack_enabled": False,  # Follow antes de atacar (para spear users com range > 1)

    #trainer
    "ignore_first": False,
    "trainer_min_delay": 1.0,
    "trainer_max_delay": 2.0,
    "trainer_range": 6, # 1 = Melee, 3+ = Distance
    
    # Listas
    "targets": list(TARGET_MONSTERS),
    "safe": list(SAFE_CREATURES),
    
    # Alarme
    "alarm_range": 8,
    "alarm_floor": "Padrão",
    "alarm_hp_enabled": False,
    "alarm_hp_percent": 50,
    "alarm_chat_enabled": False,
    "alarm_players": True,          # Disparar alarme para players (detecta por outfit)
    "alarm_creatures": True,        # Disparar alarme para criaturas fora da safe list
    "ai_chat_enabled": False,        # Resposta automática via IA quando alguém fala

    # Loot
    "loot_containers": 2,
    "loot_dest": 0,
    "loot_drop_food": False,
    "loot_auto_eat": True,  # Auto-comer food do loot
    "loot_names": ["coin", "fish"],  # NOVO - Sistema configurável
    "drop_names": ["a mace", "a sword", "chain armor", "brass helmet"],        # NOVO - Sistema configurável

    # Fisher
    "fisher_min": 4,
    "fisher_max": 6,
    "fisher_check_cap": True,   # Ativa/Desativa checagem
    "fisher_min_cap": 6.0,     # Valor da Cap mínima
    "fisher_fatigue": False,
    "fisher_auto_eat": False,  # Auto-comer durante pesca

    # Runemaker
    "rune_mana": 100,
    "rune_hotkey": "F3",
    "rune_blank_id": 3147,
    "rune_hand": "DIREITA",
    "rune_work_pos": (0,0,0),
    "rune_safe_pos": (0,0,0),
    "rune_return_delay": 300,
    "rune_flee_delay": 2.0,
    "auto_eat": False,
    "mana_train": False,
    "rune_movement": False,
    "rune_human_min": 15,   # Segundos mínimos de espera
    "rune_human_max": 300,  # Segundos máximos de espera

    # KS Prevention
    "ks_prevention_enabled": True,

    # Console Log
    "console_log_visible": False,  # Default: Status Panel visível, Console Log escondido

    # AFK Humanization (Cavebot)
    "afk_pause_enabled": False,     # Pausar AFK aleatórias durante rota
    "afk_pause_duration": 30,       # Duração total do AFK (segundos) - mínimo 5s
    "afk_pause_interval": 10,       # Intervalo máximo entre pausas (minutos) - mínimo 5min

    # Auto-Explore
    "auto_explore_radius": 50,      # Raio de busca de spawns (tiles)
    "auto_explore_cooldown": 120,   # Cooldown de revisita (segundos)
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

# ### AI CHAT HANDLER: Globais ###
chat_handler = None
current_waypoints_filename = ""
label_cavebot_status = None  # Label para mostrar posição atual e waypoint
txt_waypoints_settings = None  # DEPRECATED - substituído por waypoint_listbox
waypoint_listbox = None  # Listbox para exibir e selecionar waypoints
lbl_wp_header = None  # Label com contador de waypoints
entry_waypoint_name = None
combo_cavebot_scripts = None

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

            # DEBUG_MODE do config.py tem prioridade sobre o JSON
            BOT_SETTINGS["debug_mode"] = config.DEBUG_MODE

            # Correção específica para Tuplas (JSON salva como lista)
            if "rune_work_pos" in BOT_SETTINGS:
                BOT_SETTINGS["rune_work_pos"] = tuple(BOT_SETTINGS["rune_work_pos"])
            if "rune_safe_pos" in BOT_SETTINGS:
                BOT_SETTINGS["rune_safe_pos"] = tuple(BOT_SETTINGS["rune_safe_pos"])

            # Sincroniza console_log_visible com valor padrão se não existir
            if "console_log_visible" not in BOT_SETTINGS:
                BOT_SETTINGS["console_log_visible"] = True

            # NOVO: Converter nomes → IDs ao carregar (só se flag ativa)
            if USE_CONFIGURABLE_LOOT_SYSTEM:
                from database import lootables_db

                if 'loot_names' in BOT_SETTINGS:
                    loot_ids = []
                    for name in BOT_SETTINGS['loot_names']:
                        loot_ids.extend(lootables_db.find_loot_by_name(name))
                    BOT_SETTINGS['loot_ids'] = list(set(loot_ids))

                if 'drop_names' in BOT_SETTINGS:
                    drop_ids = []
                    for name in BOT_SETTINGS['drop_names']:
                        drop_ids.extend(lootables_db.find_loot_by_name(name))
                    BOT_SETTINGS['drop_ids'] = list(set(drop_ids))

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
txt_log = None  # Inicializado na criação da GUI

# ==============================================================================
# STATUS PANEL - Status em tempo real por módulo
# ==============================================================================
MODULE_STATUS = {
    'trainer': "",      # Atualizado por trainer_loop via callback
    'runemaker': "",    # Atualizado por runemaker_loop via callback
    'fisher': "",       # Atualizado por fishing_loop via callback
    'cavebot': "",      # Lido de cavebot_instance.state_message
    'alarm': "",        # Atualizado por alarm_loop via callback
}

MODULE_ICONS = {
    'trainer': "🎯",
    'runemaker': "🔮",
    'fisher': "🎣",
    'cavebot': "🤖",
    'alarm': "🔔",
}

# Widgets do Status Panel (inicializados na criação da GUI)
frame_status_panel = None
status_labels = {}

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
        global waypoint_listbox, lbl_wp_header

        # === NOVO: Usa Listbox se disponível ===
        if waypoint_listbox is not None:
            try:
                if not waypoint_listbox.winfo_exists():
                    return
            except:
                return

            # Salva seleção atual para restaurar depois
            current_selection = waypoint_listbox.curselection()
            saved_idx = current_selection[0] if current_selection else None

            # Limpa e repopula o listbox
            waypoint_listbox.delete(0, tk.END)

            for idx, wp in enumerate(current_waypoints_ui):
                act = wp.get('action', 'WALK').upper()
                line = f"{idx+1}. [{act}] {wp['x']}, {wp['y']}, {wp['z']}"
                waypoint_listbox.insert(tk.END, line)

            # Atualiza header com contador
            if lbl_wp_header is not None:
                try:
                    if lbl_wp_header.winfo_exists():
                        lbl_wp_header.configure(text=f"Waypoints ({len(current_waypoints_ui)})")
                except:
                    pass

            # Restaura seleção se ainda válida
            if saved_idx is not None and saved_idx < len(current_waypoints_ui):
                waypoint_listbox.selection_set(saved_idx)
            return

        # === FALLBACK: Textbox antigo (compatibilidade) ===
        global txt_waypoints_settings
        if txt_waypoints_settings is None:
            return
        try:
            if not txt_waypoints_settings.winfo_exists():
                return
        except:
            return

        txt_waypoints_settings.configure(state="normal")
        txt_waypoints_settings.delete("1.0", "end")

        total = len(current_waypoints_ui)
        header = f"═══ WAYPOINTS (Total: {total}) ═══\n\n"
        txt_waypoints_settings.insert("end", header)

        if not current_waypoints_ui:
            txt_waypoints_settings.insert("end", "Lista vazia.\n")
        else:
            for idx, wp in enumerate(current_waypoints_ui):
                act = wp.get('action', 'WALK').upper()
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

def move_waypoint_up():
    """Move o waypoint selecionado para cima na lista."""
    global current_waypoints_ui, cavebot_instance, waypoint_listbox

    if waypoint_listbox is None:
        return

    selection = waypoint_listbox.curselection()
    if not selection or selection[0] == 0:
        return

    idx = selection[0]
    # Swap
    current_waypoints_ui[idx], current_waypoints_ui[idx-1] = \
        current_waypoints_ui[idx-1], current_waypoints_ui[idx]

    # Atualiza backend
    if cavebot_instance:
        cavebot_instance.load_waypoints(current_waypoints_ui)

    # Atualiza display e mantém seleção
    update_waypoint_display()
    waypoint_listbox.selection_clear(0, tk.END)
    waypoint_listbox.selection_set(idx - 1)
    waypoint_listbox.see(idx - 1)

def move_waypoint_down():
    """Move o waypoint selecionado para baixo na lista."""
    global current_waypoints_ui, cavebot_instance, waypoint_listbox

    if waypoint_listbox is None:
        return

    selection = waypoint_listbox.curselection()
    if not selection or selection[0] >= len(current_waypoints_ui) - 1:
        return

    idx = selection[0]
    # Swap
    current_waypoints_ui[idx], current_waypoints_ui[idx+1] = \
        current_waypoints_ui[idx+1], current_waypoints_ui[idx]

    if cavebot_instance:
        cavebot_instance.load_waypoints(current_waypoints_ui)

    update_waypoint_display()
    waypoint_listbox.selection_clear(0, tk.END)
    waypoint_listbox.selection_set(idx + 1)
    waypoint_listbox.see(idx + 1)

def remove_selected_waypoint():
    """Remove o waypoint selecionado."""
    global current_waypoints_ui, cavebot_instance, waypoint_listbox

    if waypoint_listbox is None:
        return

    selection = waypoint_listbox.curselection()
    if not selection:
        log("⚠️ Selecione um waypoint para remover.")
        return

    idx = selection[0]
    removed = current_waypoints_ui.pop(idx)

    if cavebot_instance:
        cavebot_instance.load_waypoints(current_waypoints_ui)

    update_waypoint_display()
    log(f"🗑️ Removido WP #{idx+1}: ({removed['x']}, {removed['y']}, {removed['z']})")

    # Seleciona o próximo item (ou anterior se era o último)
    if current_waypoints_ui:
        new_idx = min(idx, len(current_waypoints_ui) - 1)
        waypoint_listbox.selection_set(new_idx)

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

        # Usa client_path configurado na GUI, ou fallback para MAPS_DIRECTORY
        maps_dir = BOT_SETTINGS.get('client_path') or MAPS_DIRECTORY

        # Abre a janela do editor (armazena globalmente para manter viva)
        _waypoint_editor_window = WaypointEditorWindow(
            parent_window=app,
            maps_directory=maps_dir,
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

def on_auto_explore_toggle(enabled, search_radius, revisit_cooldown):
    """Callback do toggle de auto-explore na GUI."""
    global cavebot_instance
    if not cavebot_instance:
        log("Aguarde a conexao com o Tibia...")
        return
    if enabled:
        # XML embutido na pasta do bot
        import os, sys
        if getattr(sys, 'frozen', False):
            base_dir = sys._MEIPASS  # PyInstaller extrai recursos bundled aqui
        else:
            base_dir = os.path.dirname(os.path.abspath(__file__))
        xml_path = os.path.join(base_dir, "world-spawn.xml")
        if not os.path.exists(xml_path):
            log(f"[AutoExplore] world-spawn.xml nao encontrado em {base_dir}")
            return

        # Usa lista de targets da aba Alvos como filtro de monstros
        target_monsters = list(BOT_SETTINGS.get('targets', []))

        cavebot_instance.init_auto_explore(xml_path, target_monsters, search_radius, revisit_cooldown)
        cavebot_instance.auto_explore_enabled = True
        log(f"[AutoExplore] Ativado - raio={search_radius}, cooldown={revisit_cooldown}s, alvos={target_monsters or 'todos'}")
    else:
        cavebot_instance.auto_explore_enabled = False
        cavebot_instance._current_spawn_target = None
        cavebot_instance._explore_initialized = False
        log("[AutoExplore] Desativado")

def toggle_cavebot_func():
    """Callback do Switch do Cavebot."""
    global cavebot_instance
    if not cavebot_instance:
        log("Aguarde a conexão com o Tibia...")
        switch_cavebot_var.set(0)
        return

    if switch_cavebot_var.get() == 1:
        # Restaurar auto-explore de BOT_SETTINGS se estava salvo
        if BOT_SETTINGS.get('auto_explore_enabled', False) and not cavebot_instance.auto_explore_enabled:
            search_radius = BOT_SETTINGS.get('auto_explore_radius', 50)
            revisit_cooldown = BOT_SETTINGS.get('auto_explore_cooldown', 600)
            on_auto_explore_toggle(True, search_radius, revisit_cooldown)

        if not current_waypoints_ui and not cavebot_instance.auto_explore_enabled:
            log("⚠️ AVISO: Carregue waypoints ou ative Auto-Explore antes de ativar!")
            switch_cavebot_var.set(0)
            return
        # Garante que os WPs estão carregados
        if current_waypoints_ui:
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

                    # Initialize game state (Eyes - memory scanner at 20Hz)
                    try:
                        init_game_state(pm, base_addr)
                        log("✅ Game State inicializado (20Hz polling).")
                    except Exception as e:
                        print(f"Aviso: Falha ao inicializar Game State: {e}")

                    # Initialize action scheduler
                    try:
                        scheduler = init_scheduler(pm, base_addr)
                        scheduler.set_state_checker(
                            can_send_mouse=game_state.can_send_mouse_action,
                            can_send_keyboard=game_state.can_send_keyboard_action
                        )
                        log("✅ Action Scheduler inicializado.")

                        # Initialize eater module (Phase 2 - new implementation)
                        from modules.eater import init_eater_module
                        eater_mod = init_eater_module(pm, base_addr, log_callback=log)
                        eater_mod.enable()
                        log("✅ Eater Module inicializado.")

                        # Initialize stacker module (Phase 3 - new implementation)
                        from modules.stacker import init_stacker_module
                        stacker_mod = init_stacker_module(
                            pm, base_addr,
                            config_getter=lambda k, d=None: BOT_SETTINGS.get(k, d),
                            log_callback=log
                        )
                        stacker_mod.enable()
                        log("✅ Stacker Module inicializado.")
                    except Exception as e:
                        print(f"Aviso: Falha ao inicializar Action Scheduler: {e}")
                except:
                    # Depois:
                
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

                        # Atualiza GUI baseado na vocação configurada
                        if main_window:
                            app.after(0, main_window.update_stats_visibility)

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
                # Usa client_path configurado na GUI, ou fallback para MAPS_DIRECTORY do config.py
                maps_dir = BOT_SETTINGS.get('client_path') or None
                cavebot_instance = Cavebot(
                    pm,
                    base_addr,
                    maps_directory=maps_dir,
                    spear_picker_enabled_callback=lambda: BOT_SETTINGS.get('spear_picker_enabled', False),
                    afk_settings_callback=lambda: {
                        'enabled': BOT_SETTINGS.get('afk_pause_enabled', False),
                        'duration': BOT_SETTINGS.get('afk_pause_duration', 30),
                        'interval': BOT_SETTINGS.get('afk_pause_interval', 10)
                    }
                )
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

        time.sleep(0.05)

def start_spear_picker_thread():
    """
    Thread para o Spear Picker.
    Pega spears do chao automaticamente (funcionalidade para Paladinos).
    """
    global pm, base_addr

    print("[SpearPicker] Thread iniciada.")

    # Funcoes de callback
    check_running = lambda: state.is_running and state.is_connected
    get_enabled = lambda: BOT_SETTINGS.get('spear_picker_enabled', False) and state.is_safe()
    get_max_spears = lambda: BOT_SETTINGS.get('spear_max_count', 3)

    while state.is_running:
        if pm is None or not state.is_connected:
            time.sleep(1)
            continue

        try:
            spear_picker_loop(pm, base_addr, check_running, get_enabled, get_max_spears, log_func=log)
        except Exception as e:
            print(f"[SpearPicker] Erro: {e}")
            import traceback
            traceback.print_exc()
            time.sleep(1)


def start_aimbot_thread():
    """
    Thread para o Aimbot.
    Usa runas via hotkey (F5 por padrao) no alvo atual.
    """
    global pm, base_addr

    print("[Aimbot] Thread iniciada.")

    # Config getter que le do config.py ou BOT_SETTINGS
    def aimbot_config(key, default=None):
        # Primeiro tenta BOT_SETTINGS (GUI), depois config.py
        if key == "AIMBOT_ENABLED":
            return BOT_SETTINGS.get('aimbot_enabled', getattr(config, 'AIMBOT_ENABLED', False))
        elif key == "AIMBOT_HOTKEY":
            return BOT_SETTINGS.get('aimbot_hotkey', getattr(config, 'AIMBOT_HOTKEY', 'F5'))
        elif key == "AIMBOT_RUNE_TYPE":
            return BOT_SETTINGS.get('aimbot_rune_type', getattr(config, 'AIMBOT_RUNE_TYPE', 'SD'))
        return default

    aimbot = None

    while state.is_running:
        if pm is None or not state.is_connected:
            time.sleep(1)
            continue

        try:
            # Cria instancia se ainda nao existe
            if aimbot is None:
                aimbot = AimbotModule(pm, base_addr, aimbot_config, log)
                aimbot.start()

            time.sleep(1)  # Loop de monitoramento

        except Exception as e:
            print(f"[Aimbot] Erro: {e}")
            import traceback
            traceback.print_exc()
            time.sleep(1)

    # Cleanup ao sair
    if aimbot:
        aimbot.stop()


def auto_torch_thread():
    """Thread para o Auto Torch - mantém tocha acesa no ammo slot."""
    global pm, base_addr
    from modules.auto_torch import auto_torch_loop

    check_running = lambda: state.is_running and state.is_connected
    get_enabled = lambda: BOT_SETTINGS.get('auto_torch_enabled', False)

    while state.is_running:
        if pm is None or not state.is_connected:
            time.sleep(1)
            continue
        try:
            auto_torch_loop(pm, base_addr, check_running, get_enabled, log_func=log)
        except Exception as e:
            print(f"[AutoTorch] Erro: {e}")
            time.sleep(5)


def start_chat_handler_thread():
    """
    Thread para o AI Chat Handler.
    Monitora mensagens do chat e responde de forma humanizada.
    """
    global chat_handler, pm, base_addr

    print("[ChatHandler] Thread iniciada.")

    while state.is_running:
        # 1. Inicialização Lazy (só cria quando PM existir e conectado)
        if pm is not None and chat_handler is None and state.is_connected:
            try:
                print("[ChatHandler] Inicializando instância...")
                # Cria PacketManager para enviar mensagens
                pkt = packet.PacketManager(pm, base_addr)
                chat_handler = ChatHandler(pm, base_addr, pkt)
                # Aplica estado inicial do BOT_SETTINGS
                if BOT_SETTINGS.get('ai_chat_enabled', False):
                    chat_handler.enable()
                else:
                    chat_handler.disable()
                print("[ChatHandler] Instância criada com sucesso.")
            except Exception as e:
                print(f"[ChatHandler] Erro ao inicializar: {e}")
                import traceback
                traceback.print_exc()

        # 2. Execução do Ciclo
        if chat_handler and state.is_connected:
            try:
                # Verifica se deve pausar outros módulos
                should_pause = chat_handler.tick()

                # Atualiza estado global se necessário
                if should_pause and not state.is_chat_paused:
                    from config import CHAT_PAUSE_DURATION
                    state.set_chat_pause(True, CHAT_PAUSE_DURATION)

            except Exception as e:
                print(f"[ChatHandler] Erro no loop: {e}")
                import traceback
                traceback.print_exc()
                time.sleep(1)

        time.sleep(0.2)  # Check a cada 200ms

def start_trainer_thread():
    """
    Thread Wrapper para o Trainer.
    Cria a ponte de configuração em tempo real entre o Main e o Módulo.
    """
    hwnd = 0
    
    # --- CONFIG PROVIDER ---
    # Essa função é executada pelo trainer.py a cada ciclo.
    # Ela captura o estado ATUAL dos botões e variáveis globais.
    _debug_range_last = [None]  # Mutável para closure detectar mudanças
    def config_provider():
        cfg = {
            # Lê o estado do botão (Switch) em tempo real
            'enabled': switch_trainer.get(),

            # Lê a variável de segurança controlada pelo Alarme
            'is_safe': state.is_safe(),

            # Lê as configurações salvas/editadas no menu
            'targets': BOT_SETTINGS['targets'],
            'ignore_first': BOT_SETTINGS['ignore_first'],
            'debug_mode': BOT_SETTINGS['debug_mode'],
            'debug_mode_decisions_only': BOT_SETTINGS.get('debug_mode_decisions_only', TRAINER_DEBUG_DECISIONS_ONLY),

            # Lê o botão de loot para saber se deve abrir corpos
            'loot_enabled': switch_loot.get(),

            # Passa a função de log da interface
            'log_callback': log,

            'min_delay': BOT_SETTINGS.get('trainer_min_delay', 1.0),
            'max_delay': BOT_SETTINGS.get('trainer_max_delay', 2.0),
            'range': BOT_SETTINGS.get('trainer_range', 1),

            # Anti Kill-Steal e Spear Picker (antes faltavam - usavam default fixo)
            'ks_prevention_enabled': BOT_SETTINGS.get('ks_prevention_enabled', True),
            'spear_picker_enabled': BOT_SETTINGS.get('spear_picker_enabled', False),
            'follow_before_attack_enabled': BOT_SETTINGS.get('follow_before_attack_enabled', False),
        }
        # DEBUG: Loga quando range muda (ou primeira leitura)
        if cfg['range'] != _debug_range_last[0]:
            print(f"[DEBUG CFG] range mudou: {_debug_range_last[0]} -> {cfg['range']} | id(BOT_SETTINGS)={id(BOT_SETTINGS)}")
            _debug_range_last[0] = cfg['range']
        return cfg

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
            # Callback para atualizar status do trainer
            def update_trainer_status(status):
                MODULE_STATUS['trainer'] = status

            # Chama a função principal do módulo novo
            trainer_loop(pm, base_addr, hwnd, monitor, check_running, config_provider,
                        status_callback=update_trainer_status)

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

    def do_logout():
        """Callback para executar logout via packet."""
        if pm is not None:
            try:
                pkt = packet.PacketManager(pm, base_addr)
                pkt.quit_game()
                log("🚪 LOGOUT: Alarme acionado - deslogando...")
            except Exception as e:
                print(f"Erro logout: {e}")

    def update_alarm_status(status):
        """Callback para atualizar status do alarme na GUI."""
        MODULE_STATUS['alarm'] = status

    callbacks = {
        'set_safe': set_safe,
        'set_gm': set_gm,
        'telegram': send_telegram,
        'log': log,
        'logout': do_logout
    }

    # Config Provider
    alarm_cfg = lambda: {
        'enabled': switch_alarm.get(),
        'safe_list': BOT_SETTINGS['safe'],
        'range': BOT_SETTINGS['alarm_range'],
        'floor': BOT_SETTINGS['alarm_floor'],
        'hp_enabled': BOT_SETTINGS['alarm_hp_enabled'],
        'hp_percent': BOT_SETTINGS['alarm_hp_percent'],
        'visual_enabled': True,  # Sempre ativo - controlado por alarm_players/alarm_creatures
        'chat_enabled': BOT_SETTINGS['alarm_chat_enabled'],
        'chat_gm': True,  # Sempre ativo - GM no chat sempre pausa
        'debug_mode': BOT_SETTINGS['debug_mode'],
        'alarm_players': BOT_SETTINGS.get('alarm_players', True),
        'alarm_creatures': BOT_SETTINGS.get('alarm_creatures', True),
        'targets_list': BOT_SETTINGS.get('targets', []),
        'movement_enabled': BOT_SETTINGS.get('alarm_movement_enabled', False),
        'keep_position': BOT_SETTINGS.get('alarm_keep_position', False),
        'runemaker_return_safe': BOT_SETTINGS.get('rune_movement', False),
        'mana_gm_enabled': BOT_SETTINGS.get('alarm_mana_gm_enabled', False),
        'mana_gm_threshold': BOT_SETTINGS.get('alarm_mana_gm_threshold', 10),
    }

    check_run = lambda: state.is_running and state.is_connected

    while state.is_running:
        if not check_run(): time.sleep(1); continue
        if pm is None: time.sleep(1); continue

        try:
            alarm_loop(pm, base_addr, check_run, alarm_cfg, callbacks,
                      status_callback=update_alarm_status)
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


# ==============================================================================
# CONTAINER EVENT TRACKING (EventBus Integration)
# ==============================================================================
# Rastreia containers de loot via eventos do sniffer ao invés de polling
# ==============================================================================
_open_loot_containers: set = set()  # Container IDs que são containers de loot
_loot_containers_lock = threading.Lock()
_container_listener_setup = False
_loot_container_was_opened_event = False


def _is_loot_container_name(name: str) -> bool:
    """Determina se o nome do container indica um corpo (loot container)."""
    lower = name.lower()
    return lower.startswith("dead ") or lower.startswith("slain ")


def _handle_container_open(event):
    """Processa evento de container aberto do sniffer."""
    global _loot_container_was_opened_event

    # DEBUG: Mostra TODOS os containers abertos (para diagnóstico)
    if BOT_SETTINGS.get('debug_mode', False):
        print(f"[CONTAINER EVENT] Opened: {event.name} (id:{event.container_id}, items:{event.item_count})")

    is_loot = _is_loot_container_name(event.name)

    with _loot_containers_lock:
        if is_loot:
            # Novo corpo aberto
            _open_loot_containers.add(event.container_id)
            _loot_container_was_opened_event = True
            state.set_loot_state(True)
            if BOT_SETTINGS.get('debug_mode', False):
                print(f"[CONTAINER] Loot opened: {event.name} (id:{event.container_id}, items:{event.item_count})")
        elif event.container_id in _open_loot_containers:
            # Bag aberta DENTRO do corpo - substitui mesmo slot, continua rastreando
            if BOT_SETTINGS.get('debug_mode', False):
                print(f"[CONTAINER] Bag in loot slot: {event.name} (id:{event.container_id})")


def _handle_container_close(event):
    """Processa evento de container fechado do sniffer."""
    # DEBUG: Mostra TODOS os containers fechados (para diagnóstico)
    if BOT_SETTINGS.get('debug_mode', False):
        print(f"[CONTAINER EVENT] Closed: id:{event.container_id}")

    with _loot_containers_lock:
        if event.container_id in _open_loot_containers:
            _open_loot_containers.discard(event.container_id)
            if BOT_SETTINGS.get('debug_mode', False):
                print(f"[CONTAINER] Loot closed: id:{event.container_id}")

            if len(_open_loot_containers) == 0:
                state.set_loot_state(False)


def _setup_container_event_listener():
    """Configura listener para eventos de container do sniffer."""
    global _container_listener_setup
    if _container_listener_setup:
        return

    try:
        from core.event_bus import EventBus, EVENT_CONTAINER_OPEN, EVENT_CONTAINER_CLOSE

        event_bus = EventBus.get_instance()
        event_bus.subscribe(EVENT_CONTAINER_OPEN, _handle_container_open)
        event_bus.subscribe(EVENT_CONTAINER_CLOSE, _handle_container_close)
        _container_listener_setup = True
        if BOT_SETTINGS.get('debug_mode', False):
            print("[LOOT] Container event listener configured (EventBus)")
    except ImportError:
        if BOT_SETTINGS.get('debug_mode', False):
            print("[LOOT] EventBus not available - using memory detection")


def has_open_loot_containers() -> bool:
    """Verifica thread-safe se há containers de loot abertos."""
    with _loot_containers_lock:
        return len(_open_loot_containers) > 0


def reset_loot_cycle_flags():
    """Reseta flags para o próximo ciclo de loot."""
    global _loot_container_was_opened_event
    with _loot_containers_lock:
        _loot_container_was_opened_event = False
        _open_loot_containers.clear()


def _use_event_based_detection() -> bool:
    """Verifica se detecção baseada em eventos está disponível."""
    if not _container_listener_setup:
        return False
    try:
        sniffer = get_sniffer()
        return sniffer is not None and sniffer.is_connected()
    except:
        return False


# ==============================================================================


def auto_loot_thread():
    """Thread dedicada para verificar, coletar loot e organizar."""

    # ===== SETUP: Configura listener de eventos de container (EventBus) =====
    _setup_container_event_listener()
    # ========================================================================

    hwnd = 0
    last_stack_time = 0       # Controla intervalo do stacker periódico
    STACK_INTERVAL = 5        # Intervalo em segundos

    # Detecção de movimento por posição
    last_pos = (0, 0, 0)
    last_pos_time = 0
    MOVE_COOLDOWN = 1.5       # Segundos sem mover para considerar "parado" (> loop interval)

    # ===== FALLBACK: Para quando sniffer não está disponível =====
    # Usado como fallback quando EventBus não está disponível
    loot_container_was_opened_memory = False
    # =============================================================

    # Montar config provider com base na flag
    if USE_CONFIGURABLE_LOOT_SYSTEM:
        config_provider = lambda: {
            'loot_containers': BOT_SETTINGS['loot_containers'],
            'loot_dest': BOT_SETTINGS['loot_dest'],
            'loot_drop_food': BOT_SETTINGS.get('loot_drop_food', False),
            'loot_auto_eat': BOT_SETTINGS.get('loot_auto_eat', True),
            'loot_ids': BOT_SETTINGS.get('loot_ids', []),  # NOVO - da GUI
            'drop_ids': BOT_SETTINGS.get('drop_ids', [])   # NOVO - da GUI
        }
    else:
        # Modo antigo: não precisa passar loot_ids/drop_ids
        # O auto_loot.py vai usar LOOT_IDS/DROP_IDS do config.py
        config_provider = lambda: {
            'loot_containers': BOT_SETTINGS['loot_containers'],
            'loot_dest': BOT_SETTINGS['loot_dest'],
            'loot_drop_food': BOT_SETTINGS.get('loot_drop_food', False),
            'loot_auto_eat': BOT_SETTINGS.get('loot_auto_eat', True)
        }

    # ===== SAFETY NET: Limpa ciclo de loot travado (TIME-BASED) =====
    stuck_loot_cycle_start = None  # Timestamp quando detectamos ciclo travado
    STUCK_LOOT_TIMEOUT = 3.0        # 3 segundos (menor que container timeout, pega ciclos travados)

    def check_stuck_loot_cycle():
        """
        Finaliza ciclo de loot se estiver travado por mais de 2 segundos.
        Previne race condition: só força cleanup se is_processing_loot=True
        mas has_open_loot=False por tempo prolongado (não instantâneo).

        Cenários protegidos:
        - Usuário desabilita Auto Loot durante ciclo
        - Alarme dispara durante ciclo
        - Container nunca abre após trainer iniciar ciclo
        """
        nonlocal stuck_loot_cycle_start

        # Verifica se ciclo está em estado suspeito
        is_stuck = state.is_processing_loot and not state.has_open_loot

        if is_stuck:
            # Primeira vez detectando? Marca timestamp
            if stuck_loot_cycle_start is None:
                stuck_loot_cycle_start = time.time()

            # Verifica se já passou tempo suficiente
            elapsed = time.time() - stuck_loot_cycle_start
            if elapsed >= STUCK_LOOT_TIMEOUT:
                # Handoff para spear_picker antes de liberar cavebot
                if BOT_SETTINGS.get('spear_picker_enabled', False):
                    state.set_spear_pickup_pending(True)
                state.end_loot_cycle()
                if BOT_SETTINGS.get('debug_mode', False):
                    print(f"[LOOT SAFETY] Ciclo de loot finalizado após {elapsed:.1f}s travado (sem containers)")
                stuck_loot_cycle_start = None  # Reset
        else:
            # Condição normalizada, reseta timer
            stuck_loot_cycle_start = None
    # ================================================================

    while state.is_running:
        if not state.is_connected:
            check_stuck_loot_cycle()
            time.sleep(1); continue
        if not switch_loot.get():
            check_stuck_loot_cycle()
            time.sleep(1); continue
        if not state.is_safe():
            check_stuck_loot_cycle()
            time.sleep(1); continue
        if pm is None:
            check_stuck_loot_cycle()
            time.sleep(1); continue
        if hwnd == 0: hwnd = win32gui.FindWindow("TibiaClient", None) or win32gui.FindWindow(None, "Tibia")
        
        try:
            # Atualiza detecção de movimento
            current_pos = get_player_pos(pm, base_addr)
            current_time = time.time()

            if current_pos != last_pos:
                last_pos = current_pos
                last_pos_time = current_time

            is_moving = (current_time - last_pos_time) < MOVE_COOLDOWN

            # 1. Tenta Lootear
            did_loot = run_auto_loot(pm, base_addr, hwnd, config=config_provider)

            # ===== TRACKING: Verifica modo de detecção (EventBus vs Memory) =====
            use_events = _use_event_based_detection()

            # FALLBACK: Para quando sniffer não está disponível
            if not use_events and state.has_open_loot:
                loot_container_was_opened_memory = True
            # ====================================================================

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

            # ===== FIM DO CICLO DE LOOT (EVENT-BASED vs MEMORY) =====
            if use_events:
                # EVENT-BASED: Container foi aberto E todos estão fechados agora
                if _loot_container_was_opened_event and not has_open_loot_containers():
                    if state.is_processing_loot:
                        # Handoff para spear_picker antes de liberar cavebot
                        if BOT_SETTINGS.get('spear_picker_enabled', False):
                            state.set_spear_pickup_pending(True)
                        state.end_loot_cycle()
                        if BOT_SETTINGS.get('debug_mode', False):
                            print("[LOOT] Ciclo finalizado (EventBus - containers fechados)")
                    reset_loot_cycle_flags()
            else:
                # FALLBACK: Detecção via memória (quando sniffer indisponível)
                if loot_container_was_opened_memory and not state.has_open_loot:
                    if state.is_processing_loot:
                        # Handoff para spear_picker antes de liberar cavebot
                        if BOT_SETTINGS.get('spear_picker_enabled', False):
                            state.set_spear_pickup_pending(True)
                        state.end_loot_cycle()
                        if BOT_SETTINGS.get('debug_mode', False):
                            print("[LOOT] Ciclo finalizado (memory scan)")
                    loot_container_was_opened_memory = False
            # ============================================================

            # ===== SAFETY NET: Verifica ciclo travado =====
            check_stuck_loot_cycle()
            # ==============================================

            # 2. Stacker periódico (a cada 5 segundos)
            # Só roda se NÃO estiver em movimento e sem conflitos
            # Usa detecção de loot baseada em eventos se disponível
            loot_open = has_open_loot_containers() if use_events else state.has_open_loot
            can_stack = (
                current_time - last_stack_time >= STACK_INTERVAL and
                # not is_moving and               # Não está andando
                not loot_open and               # Não está processando loot
                not state.is_runemaking         # Não está fazendo runa
            )
            # Nota: OK stackar em combate (não conflita com ataques)

            if can_stack:
                from modules.stacker import auto_stack_items
                did_stack = auto_stack_items(pm, base_addr, hwnd)
                if did_stack:
                    # Se stackou algo, tenta novamente para agrupar mais
                    while auto_stack_items(pm, base_addr, hwnd):
                        gauss_wait(0.3, 20)
                last_stack_time = current_time

            time.sleep(1.0)

        except Exception as e:
            print(f"Erro Loot/Stack: {e}")
            time.sleep(1)

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
        'fatigue': BOT_SETTINGS.get('fisher_fatigue', True),
        'auto_eat': BOT_SETTINGS.get('fisher_auto_eat', False)
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
            # Callback para atualizar status do fisher
            def update_fisher_status(status):
                MODULE_STATUS['fisher'] = status

            # Chamamos o loop passando o provider em vez dos valores fixos
            fishing_loop(pm, base_addr, hwnd,
                         check_running=should_fish,
                         log_callback=log,
                         debug_hud_callback=update_fisher_hud,
                         config=config_provider,
                         status_callback=update_fisher_status)
            
            time.sleep(1)

        except Exception as e:
            print(f"Erro Fisher Thread: {e}")
            time.sleep(5)

def auto_eater_thread():
    """Thread for automatic eating using the new EaterModule (action scheduler)."""
    from modules.eater import get_eater_module, USE_ACTION_SCHEDULER

    while state.is_running:
        try:
            # Only run if action scheduler is enabled for eater
            if not USE_ACTION_SCHEDULER:
                time.sleep(1)
                continue

            if not state.is_connected:
                time.sleep(1)
                continue

            eater_mod = get_eater_module()
            if eater_mod is None:
                time.sleep(1)
                continue

            # Run cycle (will submit actions to scheduler)
            eater_mod.run_cycle()

            # Sleep to avoid excessive CPU usage
            time.sleep(0.5)

        except Exception as e:
            print(f"Erro Eater Thread: {e}")
            time.sleep(2)

def auto_stacker_thread():
    """Thread for automatic item stacking using the new StackerModule (action scheduler)."""
    from modules.stacker import get_stacker_module, USE_ACTION_SCHEDULER

    while state.is_running:
        try:
            # Only run if action scheduler is enabled for stacker
            if not USE_ACTION_SCHEDULER:
                time.sleep(1)
                continue

            if not state.is_connected:
                time.sleep(1)
                continue

            stacker_mod = get_stacker_module()
            if stacker_mod is None:
                time.sleep(1)
                continue

            # Run cycle (will submit actions to scheduler)
            stacker_mod.run_cycle()

            # Sleep to avoid excessive CPU usage (stacking is low priority)
            time.sleep(0.3)

        except Exception as e:
            print(f"Erro Stacker Thread: {e}")
            time.sleep(2)

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
            # Callback para atualizar status do runemaker
            def update_runemaker_status(status):
                MODULE_STATUS['runemaker'] = status

            runemaker_loop(pm, base_addr, hwnd,
                           check_running=should_run,
                           config=config_provider,
                           is_safe_callback=check_safety,
                           is_gm_callback=check_gm,
                           log_callback=log,
                           eat_callback=on_eat_callback,
                           status_callback=update_runemaker_status)

            time.sleep(1)
        except Exception as e:
            print(f"Erro Runemaker: {e}")
            time.sleep(5)

def lookid_monitor_loop():
    """
    Thread que monitora o ID do item/creature ao dar Look e exibe na status bar.
    """
    last_id = 0
    while state.is_running:
        if not BOT_SETTINGS.get('lookid_enabled', False) or pm is None:
            time.sleep(0.5)
            continue

        try:
            current_id = pm.read_int(base_addr + OFFSET_LOOK_ID)

            if current_id != last_id and current_id > 0:
                # Limpa a mensagem anterior
                empty_buffer = b'\x00' * 100
                pm.write_bytes(base_addr + OFFSET_STATUS_TEXT, empty_buffer, len(empty_buffer))

                # Escreve o novo ID
                text_to_show = f"ID: {current_id}"
                pm.write_string(base_addr + OFFSET_STATUS_TEXT, text_to_show)
                pm.write_int(base_addr + OFFSET_STATUS_TIMER, 50)

                last_id = current_id
        except:
            pass

        time.sleep(0.1)

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

def resource_monitor_loop():
    """Thread que monitora e loga consumo de CPU e RAM."""
    if not RESOURCE_LOG_ENABLED:
        return

    process = psutil.Process()
    process.cpu_percent()  # primeira chamada retorna 0, descartamos
    time.sleep(1)

    while state.is_running:
        try:
            cpu = process.cpu_percent()
            ram_mb = process.memory_info().rss / (1024 * 1024)
            log(f"CPU: {cpu:.1f}% | RAM: {ram_mb:.1f} MB")
        except:
            pass
        time.sleep(RESOURCE_LOG_INTERVAL)

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
                # Usa game_state cache (20Hz) com fallback para scan direto
                current_containers = game_state.get_containers()

                # Fallback: se game_state ainda não populou, usa scan direto
                if not current_containers:
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

        # --- ATUALIZAÇÃO DO STATUS PANEL (se compact UI ativo) ---
        try:
            if 'update_status_panel' in dir() or 'update_status_panel' in globals():
                update_status_panel()
        except Exception as e:
            pass  # Status panel ainda não criado

        # Atualização mais frequente (0.5s) para status em tempo real
        if not state.is_running:
            break
        time.sleep(2)

def update_stats_visibility():
    """
    Ajusta a interface baseada na vocação.
    Delega para main_window se disponível.
    """
    global main_window
    if main_window is not None:
        main_window.update_stats_visibility()
        return

    # Fallback (não deve ser chamado após a refatoração)
    voc = BOT_SETTINGS['vocation']
    is_mage = any(x in voc for x in ["Elder", "Master", "Druid", "Sorcerer", "Mage", "None"])
    global is_graph_visible

    if is_mage:
        box_sword.grid_remove()
        frame_sw_det.grid_remove()
        box_shield.grid_remove()
        frame_sh_det.grid_remove()
        if is_graph_visible:
            toggle_graph()
        frame_graphs_container.pack_forget()
    else:
        box_sword.grid(row=4, column=0, padx=10, sticky="w")
        frame_sw_det.grid(row=4, column=1, padx=10, sticky="e")
        box_shield.grid(row=5, column=0, padx=10, sticky="w")
        frame_sh_det.grid(row=5, column=1, padx=10, sticky="e")
        frame_graphs_container.pack(padx=10, pady=(5, 0), fill="x", after=frame_stats)

    auto_resize_window()

def auto_resize_window():
    """
    Calcula o tamanho necessário para o conteúdo e ajusta a janela.
    Delega para main_window se disponível.
    """
    global main_window
    if main_window is not None:
        main_window.auto_resize_window()
        return

    # Fallback
    def do_resize():
        app.update_idletasks()
        h = main_frame.winfo_reqheight() + 12
        app.geometry(f"320x{h}")

    app.after(10, do_resize)

def toggle_log_visibility():
    """
    Toggle entre Console Log e Status Panel.
    Delega para main_window se disponível.
    """
    global main_window, log_visible
    if main_window is not None:
        main_window.toggle_log_visibility()
        log_visible = main_window.log_visible  # Sync global
        return

    # Fallback
    global txt_log, frame_status_panel
    log_visible = not log_visible
    BOT_SETTINGS['console_log_visible'] = log_visible

    if log_visible:
        if frame_status_panel:
            frame_status_panel.pack_forget()
        txt_log.pack(side="bottom", fill="x", padx=5, pady=5, expand=True)
        log("📝 Console Log ativado")
    else:
        txt_log.pack_forget()
        if frame_status_panel:
            frame_status_panel.pack(side="bottom", fill="x", padx=8, pady=3)
            update_status_panel()

    auto_resize_window()

def update_status_panel():
    """
    Atualiza os labels do Status Panel baseado nos módulos ativos.
    Delega para main_window se disponível.
    """
    global main_window
    if main_window is not None:
        main_window.update_status_panel()
        return

    # Fallback
    global frame_status_panel, status_labels, cavebot_instance

    if log_visible or not frame_status_panel:
        return

    if cavebot_instance and hasattr(cavebot_instance, 'state_message'):
        MODULE_STATUS['cavebot'] = cavebot_instance.state_message or ""

    active_modules = []
    try:
        if switch_trainer.get():
            active_modules.append('trainer')
        if switch_runemaker.get():
            active_modules.append('runemaker')
        if switch_fisher.get():
            active_modules.append('fisher')
        if switch_cavebot_var.get():
            active_modules.append('cavebot')
        if switch_alarm.get():
            active_modules.append('alarm')
    except:
        pass

    for module, label in status_labels.items():
        label.pack_forget()

    shown = False
    for module in active_modules:
        status = MODULE_STATUS.get(module, "")
        if status:
            icon = MODULE_ICONS.get(module, "•")
            if len(status) > 45:
                status = status[:42] + "..."
            status_labels[module].configure(text=f"{icon} {module.capitalize()}: {status}")
            status_labels[module].pack(fill="x", padx=8, pady=1, anchor="w")
            shown = True

    if not shown:
        if active_modules:
            status_labels['trainer'].configure(text="⏳ Aguardando atividade...")
        else:
            status_labels['trainer'].configure(text="💤 Nenhum módulo ativo")
        status_labels['trainer'].pack(fill="x", padx=8, pady=2, anchor="w")

    auto_resize_window()

# ==============================================================================
# SETTINGS WINDOW - CALLBACKS E INTEGRAÇÃO
# ==============================================================================

# === Utility Toggle Functions (usadas por MainWindow e SettingsWindow) ===

def on_light_toggle(enabled: bool):
    """Toggle Full Light hack."""
    global full_light_enabled
    full_light_enabled = enabled
    apply_full_light(enabled)
    log(f"💡 Full Light: {enabled}")

def on_spear_picker_toggle(enabled: bool):
    """Toggle Spear Picker."""
    BOT_SETTINGS['spear_picker_enabled'] = enabled
    status = "ativado" if enabled else "desativado"
    log(f"🎯 Pegar Spear: {status}")

def on_auto_torch_toggle(enabled: bool):
    """Toggle Auto Torch."""
    BOT_SETTINGS['auto_torch_enabled'] = enabled
    status = "ativado" if enabled else "desativado"
    log(f"🔦 Auto Torch: {status}")


def create_settings_callbacks() -> SettingsCallbacks:
    """
    Cria o objeto de callbacks para a janela de Settings.
    Todos os callbacks acessam variáveis globais de main.py.
    """
    global full_light_enabled, log_visible, txt_log, frame_status_panel, chat_handler

    def on_lookid_toggle(enabled: bool):
        BOT_SETTINGS['lookid_enabled'] = enabled
        status = "ativado" if enabled else "desativado"
        log(f"🔍 Look ID: {status}")

    def on_ai_chat_toggle(enabled: bool):
        BOT_SETTINGS['ai_chat_enabled'] = enabled
        if chat_handler:
            if enabled:
                chat_handler.enable()
            else:
                chat_handler.disable()
        status = "ativado" if enabled else "desativado"
        log(f"🤖 Resposta via IA: {status}")

    def on_console_log_toggle(enabled: bool):
        global log_visible
        log_visible = enabled
        BOT_SETTINGS['console_log_visible'] = enabled
        if enabled:
            if frame_status_panel:
                frame_status_panel.pack_forget()
            if txt_log:
                txt_log.pack(side="bottom", fill="x", padx=5, pady=5, expand=True)
        else:
            if txt_log:
                txt_log.pack_forget()
            if frame_status_panel:
                frame_status_panel.pack(side="bottom", fill="x", padx=8, pady=3)
        log(f"📊 Console Log: {'Visível' if enabled else 'Oculto'}")

    def on_ignore_toggle(enabled: bool):
        BOT_SETTINGS['ignore_first'] = enabled
        log(f"🛡️ Ignorar 1º: {enabled}")

    def on_ks_toggle(enabled: bool):
        BOT_SETTINGS['ks_prevention_enabled'] = enabled
        log(f"🛡️ Anti Kill-Steal: {'Ativado' if enabled else 'Desativado'}")

    def set_rune_pos_callback(type_pos: str):
        if pm:
            try:
                x, y, z = get_player_pos(pm, base_addr)
                key = 'rune_work_pos' if type_pos == "WORK" else 'rune_safe_pos'
                BOT_SETTINGS[key] = (x, y, z)
                if settings_window:
                    settings_window.update_rune_pos_labels_ui()
                log(f"📍 {type_pos} definido: {x}, {y}, {z}")
            except Exception as e:
                log(f"❌ Erro ao definir posicao: {e}")

    def refresh_scripts_callback(selected=None):
        scripts = list_cavebot_scripts()
        if settings_window:
            settings_window.refresh_scripts_combo_ui(scripts, selected)
        return scripts

    return SettingsCallbacks(
        # State providers
        get_bot_settings=lambda: BOT_SETTINGS,
        get_vocation_options=lambda: list(VOCATION_REGEN.keys()),
        get_pm=lambda: pm,
        get_base_addr=lambda: base_addr,
        get_current_waypoints=lambda: current_waypoints_ui,
        get_current_waypoints_filename=lambda: current_waypoints_filename,
        get_full_light_enabled=lambda: full_light_enabled,
        get_log_visible=lambda: log_visible,
        get_chat_handler=lambda: chat_handler,

        # Save
        save_config_file=save_config_file,

        # Tab Geral
        on_light_toggle=on_light_toggle,
        on_lookid_toggle=on_lookid_toggle,
        on_spear_picker_toggle=on_spear_picker_toggle,
        on_auto_torch_toggle=on_auto_torch_toggle,
        on_ai_chat_toggle=on_ai_chat_toggle,
        on_console_log_toggle=on_console_log_toggle,
        update_stats_visibility=update_stats_visibility,

        # Tab Trainer
        on_ignore_toggle=on_ignore_toggle,
        on_ks_toggle=on_ks_toggle,

        # Tab Rune
        set_rune_pos=set_rune_pos_callback,

        # Tab Cavebot
        on_auto_explore_toggle=on_auto_explore_toggle,
        load_waypoints_file=load_waypoints_file,
        save_waypoints_file=save_waypoints_file,
        refresh_scripts_combo=refresh_scripts_callback,
        record_current_pos=record_current_pos,
        move_waypoint_up=move_waypoint_up,
        move_waypoint_down=move_waypoint_down,
        remove_selected_waypoint=remove_selected_waypoint,
        clear_waypoints=clear_waypoints,
        update_waypoint_display=update_waypoint_display,
        open_waypoint_editor=open_waypoint_editor_window,

        # Logging
        log=log,

        # Feature flags
        use_configurable_loot=USE_CONFIGURABLE_LOOT_SYSTEM,
        use_auto_container_detection=USE_AUTO_CONTAINER_DETECTION,
    )


def open_settings():
    """Abre a janela de configurações usando a nova classe SettingsWindow."""
    global settings_window, toplevel_settings, waypoint_listbox, lbl_wp_header
    global entry_waypoint_name, combo_cavebot_scripts, label_cavebot_status

    # Cria a instância se não existir
    if settings_window is None:
        callbacks = create_settings_callbacks()
        settings_window = SettingsWindow(app, callbacks)

    # Abre a janela
    settings_window.open()

    # Atualiza referências globais para compatibilidade com código existente
    toplevel_settings = settings_window.window
    waypoint_listbox = settings_window.waypoint_listbox
    lbl_wp_header = settings_window.lbl_wp_header
    entry_waypoint_name = settings_window.entry_waypoint_name
    combo_cavebot_scripts = settings_window.combo_cavebot_scripts
    label_cavebot_status = settings_window.label_cavebot_status


# ==============================================================================
# MAIN WINDOW - CALLBACKS E INTEGRAÇÃO
# ==============================================================================

def create_main_window_callbacks() -> MainWindowCallbacks:
    """
    Cria o objeto de callbacks para a janela principal.
    Todos os callbacks acessam variáveis globais de main.py.
    """
    return MainWindowCallbacks(
        # State Providers
        get_bot_settings=lambda: BOT_SETTINGS,
        get_state=lambda: state,
        get_pm=lambda: pm,
        get_base_addr=lambda: base_addr,

        # Module Status
        get_module_status=lambda: MODULE_STATUS,
        get_module_icons=lambda: MODULE_ICONS,
        get_cavebot_instance=lambda: cavebot_instance,

        # Action Callbacks
        open_settings=open_settings,
        on_close=on_close,
        on_reload=on_reload,
        toggle_xray=toggle_xray,
        toggle_cavebot=toggle_cavebot_func,
        on_fisher_toggle=on_fisher_toggle,
        on_pause_toggle=on_pause_toggle,

        # Utility Toggles
        on_light_toggle=on_light_toggle,
        on_spear_picker_toggle=on_spear_picker_toggle,
        on_auto_torch_toggle=on_auto_torch_toggle,

        # Trackers
        get_sword_tracker=lambda: sword_tracker,
        get_shield_tracker=lambda: shield_tracker,
        get_magic_tracker=lambda: magic_tracker,
        get_exp_tracker=lambda: exp_tracker,
        get_gold_tracker=lambda: gold_tracker,
        get_regen_tracker=lambda: regen_tracker,

        # Config
        reload_button_enabled=config.RELOAD_BUTTON,
        maps_directory=MAPS_DIRECTORY,
        walkable_colors=WALKABLE_COLORS,
    )


# ==============================================================================
# FUNÇÃO ANTIGA open_settings() - CÓDIGO REMOVIDO
# A implementação foi movida para gui/settings_window.py
# ==============================================================================

def toggle_graph():
    """Delega para main_window se disponível."""
    global main_window
    if main_window is not None:
        main_window.toggle_graph()
        return

    # Fallback (não deve ser chamado após a refatoração)
    global is_graph_visible
    if is_graph_visible:
        frame_graph.pack_forget()
        btn_graph.configure(text="Mostrar Gráfico 📈")
        is_graph_visible = False
    else:
        frame_graph.pack(side="top", fill="both", expand=True, pady=(0, 5))
        btn_graph.configure(text="Esconder Gráfico 📉")
        is_graph_visible = True
    auto_resize_window()


# [CÓDIGO ANTIGO REMOVIDO]
# A função open_settings() (~960 linhas) foi movida para gui/settings_window.py
# Ver classe SettingsWindow para a implementação completa.
# [FIM DO CÓDIGO REMOVIDO]

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

                # Atualiza o renderer com informações do viewport
                if gv:
                    overlay_renderer.update_game_view(gv, (offset_x, offset_y))

                # Renderiza todos os layers registrados no renderer
                if gv:
                    all_layers = overlay_renderer.get_all_layers()
                for layer_id, items in all_layers.items():
                        for item in items:
                            item_type = item.get('type', 'tile')
                            dx = item.get('dx', 0)
                            dy = item.get('dy', 0)
                            raw_color = item.get('color', '#FFFFFF')
                            text = item.get('text', '')
                            offset_y_px = item.get('offset_y', 0)

                            color = raw_color[:7] if len(raw_color) > 7 else raw_color

                            raw_cx = gv['center'][0] + (dx * gv['sqm'])
                            raw_cy = gv['center'][1] + (dy * gv['sqm'])

                            cx = raw_cx + offset_x
                            cy = raw_cy + offset_y + offset_y_px

                            if item_type == 'creature_info' and text:
                                # Texto com sombra para legibilidade
                                canvas.create_text(cx+1, cy+1, text=text, fill="black", font=("Verdana", 8, "bold"))
                                canvas.create_text(cx, cy, text=text, fill=color, font=("Verdana", 8, "bold"))
                            elif item_type == 'tile':
                                size = gv['sqm'] / 2
                                canvas.create_rectangle(cx - size, cy - size, cx + size, cy + size,
                                                      outline=color, width=2)
                                if text:
                                    canvas.create_text(cx+1, cy+1, text=text, fill="black", font=("Verdana", 8, "bold"))
                                    canvas.create_text(cx, cy, text=text, fill=color, font=("Verdana", 8, "bold"))

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
    shutdown_game_state()  # Para o game state polling
    stop_scheduler()  # Para o action scheduler
    stop_sniffer()  # Para o sniffer de pacotes
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


def on_pause_toggle(is_pausing: bool):
    """
    Callback chamado quando o botão de pause/resume é clicado.
    Salva e restaura estados de: full_light, spear_picker, auto_torch, ai_chat.

    Args:
        is_pausing: True se está pausando, False se está resumindo
    """
    global full_light_enabled, chat_handler

    if is_pausing:
        # Salvar estados atuais no main_window
        saved_states = {
            'full_light': full_light_enabled,
            'spear_picker': BOT_SETTINGS.get('spear_picker_enabled', False),
            'auto_torch': BOT_SETTINGS.get('auto_torch_enabled', False),
            'ai_chat': BOT_SETTINGS.get('ai_chat_enabled', False),
        }
        main_window.paused_settings_states = saved_states

        # Desativar full light
        if full_light_enabled:
            apply_full_light(False)
            full_light_enabled = False

        # Desativar settings
        BOT_SETTINGS['spear_picker_enabled'] = False
        BOT_SETTINGS['auto_torch_enabled'] = False
        BOT_SETTINGS['ai_chat_enabled'] = False

        # Desativar chat handler
        if chat_handler:
            chat_handler.disable()

        log("⏸️ Bot pausado - todos os módulos desativados")

    else:
        # Restaurar estados salvos
        saved = main_window.paused_settings_states

        # Restaurar full light
        if saved.get('full_light', False):
            apply_full_light(True)
            full_light_enabled = True

        # Restaurar settings
        BOT_SETTINGS['spear_picker_enabled'] = saved.get('spear_picker', False)
        BOT_SETTINGS['auto_torch_enabled'] = saved.get('auto_torch', False)
        BOT_SETTINGS['ai_chat_enabled'] = saved.get('ai_chat', False)

        # Restaurar chat handler
        if saved.get('ai_chat', False) and chat_handler:
            chat_handler.enable()

        log("▶️ Bot resumido - módulos restaurados")


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
        font=("Verdana", 9),
        text_color="#888888"
    )
    minimap_label.pack(padx=10, pady=5)

    # Status label (below image)
    # minimap_status_label = ctk.CTkLabel(
    #     minimap_container,
    #     text="",
    #     font=("Verdana", 10),
    #     text_color="#AAAAAA"
    # )
    #minimap_status_label.pack(pady=(0, 8))

    # Initialize visualizer
    from utils.realtime_minimap import RealtimeMinimapVisualizer
    from utils.color_palette import COLOR_PALETTE
    maps_dir = BOT_SETTINGS.get('client_path') or MAPS_DIRECTORY
    minimap_visualizer = RealtimeMinimapVisualizer(
        maps_dir,
        WALKABLE_COLORS,
        COLOR_PALETTE
    )

def show_minimap_panel():
    """Show minimap panel and resize GUI. Delega para main_window se disponível."""
    global main_window
    if main_window is not None:
        main_window.show_minimap_panel()
        return

    # Fallback
    global minimap_container
    if minimap_container and not minimap_container.winfo_ismapped():
        minimap_container.pack(fill="x", padx=10, pady=5)
        app.after(100, auto_resize_window)

def hide_minimap_panel():
    """Hide minimap panel and resize GUI. Delega para main_window se disponível."""
    global main_window
    if main_window is not None:
        main_window.hide_minimap_panel()
        return

    # Fallback
    global minimap_container
    if minimap_container and minimap_container.winfo_ismapped():
        minimap_container.pack_forget()
        app.after(100, auto_resize_window)

def update_minimap_loop():
    """Auto-scheduled loop to update minimap every 3 seconds."""
    global minimap_label, minimap_image_ref, minimap_visualizer, cavebot_instance, main_window

    # Check if widget exists
    if not minimap_label or not minimap_label.winfo_exists():
        return

    try:
        # Check if Cavebot is active (panel is hidden when inactive, just reschedule)
        if not cavebot_instance or not switch_cavebot.get():
            app.after(1000, update_minimap_loop)
            return

        # Lazy load: obter minimap_visualizer de main_window se ainda não disponível
        if minimap_visualizer is None and main_window is not None:
            if main_window.minimap_visualizer is None:
                main_window._init_minimap_visualizer()
            minimap_visualizer = main_window.minimap_visualizer

        # Se ainda não conseguiu inicializar, reagendar
        if minimap_visualizer is None:
            app.after(1000, update_minimap_loop)
            return

        # Collect Cavebot data (thread-safe)
        try:
            player_pos = get_player_pos(pm, base_addr)

            # Auto-Explore mode: spawns viram waypoints virtuais
            if cavebot_instance.auto_explore_enabled and cavebot_instance._spawn_selector and cavebot_instance._spawn_selector.active_spawns:
                active_spawns = cavebot_instance._spawn_selector.active_spawns
                now = time.time()
                cooldown = cavebot_instance._spawn_selector.revisit_cooldown
                all_waypoints = [
                    {'x': s.cx, 'y': s.cy, 'z': s.cz,
                     'in_cooldown': (now - s.last_visited) < cooldown and s.last_visited > 0}
                    for s in active_spawns
                ]

                # Target atual
                spawn_target = cavebot_instance._current_spawn_target
                if spawn_target:
                    target_wp = {'x': spawn_target.cx, 'y': spawn_target.cy, 'z': spawn_target.cz}
                    # Encontra indice do target na lista
                    current_idx = 0
                    for i, s in enumerate(active_spawns):
                        if s is spawn_target:
                            current_idx = i
                            break
                else:
                    target_wp = all_waypoints[0] if all_waypoints else {'x': player_pos[0], 'y': player_pos[1], 'z': player_pos[2]}
                    current_idx = 0
            else:
                # Modo waypoints normal
                with cavebot_instance._waypoints_lock:
                    all_waypoints = cavebot_instance._waypoints.copy()
                    current_idx = cavebot_instance._current_index

                if not all_waypoints:
                    minimap_label.configure(
                        image=None,
                        text="📍 Nenhum Waypoint Configurado"
                    )
                    app.after(3000, update_minimap_loop)
                    return

                target_wp = all_waypoints[current_idx]

            # Collect cavebot status (thread-safe string read)
            cavebot_status = cavebot_instance.state_message

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
        max_width = 150
        max_height = 100
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
        if cavebot_instance.auto_explore_enabled and cavebot_instance._current_spawn_target:
            spawn = cavebot_instance._current_spawn_target
            names = ', '.join(sorted(spawn.monster_names())[:2])
            minimap_title_label.configure(text=f"Auto-Explore: {names}")
        else:
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

        #minimap_status_label.configure(text=status_text, text_color=status_color)

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

if __name__ == "__main__":
    # Cria a janela principal usando MainWindow
    # Nota: Atribuições dentro de `if __name__ == "__main__"` são
    # automaticamente module-level, não precisam de `global`.
    mw_callbacks = create_main_window_callbacks()
    main_window = MainWindow(mw_callbacks)
    app = main_window.create()

    # =========================================================================
    # COMPATIBILIDADE: Referências globais para código existente
    # As threads e funções usam essas variáveis globais.
    # Apontamos para os widgets do main_window para manter tudo funcionando.
    # =========================================================================
    main_frame = main_window.main_frame

    # Header
    btn_xray = main_window.btn_xray
    lbl_connection = main_window.lbl_connection

    # Switches
    switch_trainer = main_window.switch_trainer
    switch_loot = main_window.switch_loot
    switch_alarm = main_window.switch_alarm
    def _on_alarm_toggle():
        if switch_alarm.get():
            try:
                if pm:
                    pos = get_player_pos(pm, base_addr)
                    if pos and pos[0] > 0:
                        state.alarm_origin_pos = pos
                        log(f"📍 Posição de origem do alarme: {pos}")
            except Exception:
                pass
        else:
            state.alarm_origin_pos = None
    switch_alarm.configure(command=_on_alarm_toggle)
    switch_fisher = main_window.switch_fisher
    switch_runemaker = main_window.switch_runemaker
    switch_cavebot = main_window.switch_cavebot
    switch_cavebot_var = main_window.switch_cavebot_var

    # Stats Labels
    lbl_exp_left = main_window.lbl_exp_left
    lbl_exp_rate = main_window.lbl_exp_rate
    lbl_exp_eta = main_window.lbl_exp_eta
    lbl_regen = main_window.lbl_regen
    lbl_regen_stock = main_window.lbl_regen_stock
    lbl_gold_total = main_window.lbl_gold_total
    lbl_gold_rate = main_window.lbl_gold_rate
    lbl_sword_val = main_window.lbl_sword_val
    lbl_sword_rate = main_window.lbl_sword_rate
    lbl_sword_time = main_window.lbl_sword_time
    lbl_shield_val = main_window.lbl_shield_val
    lbl_shield_rate = main_window.lbl_shield_rate
    lbl_shield_time = main_window.lbl_shield_time
    lbl_magic_val = main_window.lbl_magic_val
    lbl_magic_rate = main_window.lbl_magic_rate
    lbl_magic_time = main_window.lbl_magic_time

    # Stats Frames (para update_stats_visibility)
    box_sword = main_window.box_sword
    frame_sw_det = main_window.frame_sw_det
    box_shield = main_window.box_shield
    frame_sh_det = main_window.frame_sh_det
    frame_stats = main_window.frame_stats

    # Graph
    frame_graphs_container = main_window.frame_graphs_container
    frame_graph = main_window.frame_graph
    btn_graph = main_window.btn_graph
    fig = main_window.fig
    ax = main_window.ax
    canvas = main_window.canvas

    # Minimap
    minimap_container = main_window.minimap_container
    minimap_label = main_window.minimap_label
    minimap_title_label = main_window.minimap_title_label
    minimap_visualizer = main_window.minimap_visualizer

    # Status Panel
    frame_status_panel = main_window.frame_status_panel
    status_labels = main_window.status_labels

    # Log
    txt_log = main_window.txt_log
    log_visible = main_window.log_visible

    # ==============================================================================
    # 8. EXECUÇÃO PRINCIPAL
    # ==============================================================================

    app.after(1000, attach_window)
    app.protocol("WM_DELETE_WINDOW", on_close)

    # Iniciar Sniffer de Pacotes (se habilitado)
    if SNIFFER_AVAILABLE and getattr(config, 'SNIFFER_ENABLED', False):
        server_ip = getattr(config, 'SNIFFER_SERVER_IP', '135.148.27.135')
        log(f"🔌 Iniciando Sniffer de Pacotes ({server_ip})...")
        start_sniffer(server_ip, PROCESS_NAME)

    # Iniciar Threads
    threading.Thread(target=start_trainer_thread, daemon=True).start()
    threading.Thread(target=start_alarm_thread, daemon=True).start()
    threading.Thread(target=auto_loot_thread, daemon=True).start()
    threading.Thread(target=skill_monitor_loop, daemon=True).start()
    threading.Thread(target=gui_updater_loop, daemon=True).start()
    threading.Thread(target=regen_monitor_loop, daemon=True).start()
    threading.Thread(target=auto_fisher_thread, daemon=True).start()
    threading.Thread(target=auto_eater_thread, daemon=True).start()
    threading.Thread(target=auto_stacker_thread, daemon=True).start()
    threading.Thread(target=runemaker_thread, daemon=True).start()
    threading.Thread(target=connection_watchdog, daemon=True).start()
    threading.Thread(target=start_cavebot_thread, daemon=True).start()
    threading.Thread(target=lookid_monitor_loop, daemon=True).start()
    threading.Thread(target=start_chat_handler_thread, daemon=True).start()
    threading.Thread(target=start_spear_picker_thread, daemon=True).start()
    threading.Thread(target=start_aimbot_thread, daemon=True).start()
    threading.Thread(target=auto_torch_thread, daemon=True).start()
    threading.Thread(target=resource_monitor_loop, daemon=True).start()

    # Atualiza visibilidade baseada na vocação
    main_window.update_stats_visibility()

    # Inicializar Debug Monitor
    init_debug_monitor(app)

    # Abrir Debug Monitor automaticamente se habilitado
    if getattr(config, 'DEBUG_BOT_STATE', False):
        app.after(500, show_debug_monitor)

    # Iniciar loop de atualização do minimap
    app.after(1000, update_minimap_loop)

    # Forçar resize inicial para eliminar espaço vazio
    app.update_idletasks()
    h = main_frame.winfo_reqheight() + 12
    app.geometry(f"320x{h}")
    main_window.update_status_panel()

    log("🚀 Iniciado.")
    app.mainloop()
    state.stop()  # Garante que todas as threads encerrem ao fechar
