import dearpygui.dearpygui as dpg
import math

# --- CONFIGURAÇÕES VISUAIS ---
WINDOW_WIDTH = 340
WINDOW_HEIGHT = 600 
APP_TITLE = "Molodoy Bot Pro"

# --- VARIÁVEIS PARA O ARRASTE (CORRIGIDAS) ---
is_dragging = False
initial_window_pos = [0, 0]
initial_mouse_pos = [0, 0]

def setup_theme():
    with dpg.theme() as global_theme:
        with dpg.theme_component(dpg.mvAll):
            dpg.add_theme_style(dpg.mvStyleVar_WindowPadding, 10, 10)
            dpg.add_theme_style(dpg.mvStyleVar_ItemSpacing, 8, 6)
            dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, 4)
            dpg.add_theme_color(dpg.mvThemeCol_WindowBg, (20, 20, 20))
            dpg.add_theme_color(dpg.mvThemeCol_Button, (45, 45, 45))
            dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, (60, 60, 60))
            dpg.add_theme_color(dpg.mvThemeCol_CheckMark, (0, 255, 0))
            dpg.add_theme_color(dpg.mvThemeCol_FrameBg, (30, 30, 30))
    dpg.bind_theme(global_theme)

# --- FUNÇÕES DE CONTROLE DA JANELA ---
def close_app():
    dpg.stop_dearpygui()

def minimize_app():
    dpg.minimize_viewport()

# === LÓGICA DE ARRASTE LISA (SEM BUG) ===
def mouse_down_handler():
    global is_dragging, initial_window_pos, initial_mouse_pos
    
    # Verifica se clicou na área do título (topo da janela)
    mx_local, my_local = dpg.get_mouse_pos(local=True)
    
    # Se clicou na faixa de 30px do topo
    if my_local < 30 and my_local >= 0:
        is_dragging = True
        # Memoriza onde a janela e o mouse estavam NO MOMENTO DO CLIQUE
        initial_window_pos = dpg.get_viewport_pos()
        initial_mouse_pos = dpg.get_mouse_pos(local=False) # Global (Tela do PC)

def mouse_drag_handler(sender, app_data):
    global is_dragging, initial_window_pos, initial_mouse_pos
    
    if is_dragging:
        # Pega a posição ATUAL do mouse na tela
        current_global_mouse = dpg.get_mouse_pos(local=False)
        
        # Calcula quanto o mouse andou (Delta)
        dx = current_global_mouse[0] - initial_mouse_pos[0]
        dy = current_global_mouse[1] - initial_mouse_pos[1]
        
        # Aplica esse deslocamento na posição ORIGINAL da janela
        new_x = initial_window_pos[0] + dx
        new_y = initial_window_pos[1] + dy
        
        # Move a janela com segurança
        dpg.configure_viewport(0, x_pos=int(new_x), y_pos=int(new_y))

def mouse_release_handler():
    global is_dragging
    is_dragging = False
# ========================================

# --- CALLBACKS DA GUI ---
def toggle_graph_callback(sender, app_data):
    is_visible = dpg.get_item_configuration("plot_container")["show"]
    dpg.configure_item("plot_container", show=not is_visible)
    label = "Esconder Gráfico 📉" if not is_visible else "Mostrar Gráfico 📈"
    dpg.configure_item("btn_toggle_graph", label=label)

def open_settings_callback():
    dpg.configure_item("settings_window", show=True)

def log(msg):
    dpg.add_text(f"[LOG] {msg}", parent="log_child")
    dpg.set_y_scroll("log_child", -1.0)

# --- JANELA DE CONFIGURAÇÕES ---
def create_settings_window():
    with dpg.window(label="Configurações", modal=True, show=False, tag="settings_window", width=300, height=450, no_collapse=True, no_title_bar=False):
        dpg.add_text("Configurações do Bot", color=(0, 255, 0))
        dpg.add_separator()
        with dpg.tab_bar():
            with dpg.tab(label="Geral"):
                dpg.add_combo(["Knight", "Paladin", "Druid", "Sorcerer"], default_value="Knight", width=150)
                dpg.add_checkbox(label="Debug Mode")
            with dpg.tab(label="Loot"):
                dpg.add_input_int(label="Backpacks", default_value=2, width=100)
        dpg.add_spacer(height=10)
        with dpg.group(horizontal=True):
            dpg.add_button(label="Salvar", width=120, callback=lambda: log("Config Salva!"))
            dpg.add_button(label="Fechar", width=120, callback=lambda: dpg.configure_item("settings_window", show=False))

# --- JANELA PRINCIPAL ---
def create_main_gui():
    create_settings_window()
    
    # no_title_bar=True remove a barra interna cinza do DPG
    with dpg.window(tag="Primary Window", no_title_bar=True):
        
        # === BARRA DE TÍTULO CUSTOMIZADA ===
        with dpg.group(horizontal=True):
            dpg.add_text(f"  {APP_TITLE}", color=(0, 255, 0))
            dpg.add_spacer(width=130)
            
            # Botões de janela
            dpg.add_button(label="_", width=30, height=20, callback=minimize_app)
            btn_close = dpg.add_button(label="X", width=30, height=20, callback=close_app)
            
            # Tema vermelho para o botão fechar
            with dpg.theme() as theme_close:
                with dpg.theme_component(dpg.mvButton):
                    dpg.add_theme_color(dpg.mvThemeCol_Button, (150, 0, 0, 255))
                    dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, (255, 0, 0, 255))
            dpg.bind_item_theme(btn_close, theme_close)

        dpg.add_separator()
        dpg.add_spacer(height=5)

        # === MENU E STATUS ===
        with dpg.group(horizontal=True):
            dpg.add_button(label="⚙️ Config.", width=100, callback=open_settings_callback)
            dpg.add_button(label="Raio-X", width=60, callback=lambda: log("Raio-X Toggled"))
            dpg.add_spacer(width=20)
            dpg.add_text("🔌 Procurando...", tag="status_conn", color=(255, 165, 0))

        dpg.add_separator()

        # === TOGGLES ===
        with dpg.table(header_row=False, borders_innerH=False, borders_innerV=False):
            dpg.add_table_column()
            dpg.add_table_column()
            with dpg.table_row():
                dpg.add_checkbox(label="Trainer", callback=lambda: log("Trainer Toggled"))
                dpg.add_checkbox(label="Alarm", callback=lambda: log("Alarm Toggled"))
            with dpg.table_row():
                dpg.add_checkbox(label="Auto Loot", callback=lambda: log("Loot Toggled"))
                dpg.add_checkbox(label="Auto Fisher", callback=lambda: log("Fisher Toggled"))
            with dpg.table_row():
                dpg.add_checkbox(label="Runemaker", callback=lambda: log("Rune Toggled"))

        dpg.add_separator()

        # === STATS ===
        with dpg.group(horizontal=True):
            dpg.add_text("EXP:", color=(150, 150, 150))
            dpg.add_text("-- xp/h", tag="lbl_xp")
            dpg.add_spacer(width=10)
            dpg.add_text("ETA: --", tag="lbl_eta", color=(150, 150, 150))
        dpg.add_text("🍖 --:--", tag="lbl_regen", color=(150, 150, 150))

        with dpg.table(header_row=False, borders_innerH=False, borders_innerV=False):
            dpg.add_table_column()
            dpg.add_table_column()
            dpg.add_table_column()
            with dpg.table_row():
                dpg.add_text("Sword: --", color=(78, 165, 249))
                dpg.add_text("-- m/%", color=(150, 150, 150))
                dpg.add_text("ETA: --", color=(150, 150, 150))
            with dpg.table_row():
                dpg.add_text("Shield: --", color=(78, 165, 249))
                dpg.add_text("-- m/%", color=(150, 150, 150))
                dpg.add_text("ETA: --", color=(150, 150, 150))

        dpg.add_separator()

        # === GRÁFICO ===
        dpg.add_button(label="Mostrar Gráfico 📈", tag="btn_toggle_graph", width=-1, callback=toggle_graph_callback)
        with dpg.group(tag="plot_container", show=False):
            with dpg.plot(label="XP Analyzer", height=150, width=-1, no_menus=True):
                dpg.add_plot_legend()
                dpg.add_plot_axis(dpg.mvXAxis, label="Time", no_tick_labels=True)
                y_axis = dpg.add_plot_axis(dpg.mvYAxis, label="%", lock_min=True, lock_max=True)
                dpg.set_axis_limits(y_axis, 0, 100)
                
                x = [float(i) for i in range(20)]
                y = [50 + 10*math.sin(i/2) for i in x]
                dpg.add_line_series(x, y, label="XP Flow", parent=y_axis)

        # === LOGS ===
        dpg.add_spacer(height=5)
        with dpg.child_window(tag="log_child", height=-1, width=-1, border=True):
            dpg.add_text("[SYSTEM] Bot iniciado (Smooth Drag)...", color=(0, 255, 0))

# --- INICIALIZAÇÃO ---
dpg.create_context()
create_main_gui()
setup_theme()

# Handlers para o Mouse
with dpg.handler_registry():
    dpg.add_mouse_down_handler(callback=mouse_down_handler)
    dpg.add_mouse_drag_handler(callback=mouse_drag_handler)
    dpg.add_mouse_release_handler(callback=mouse_release_handler)

# decorated=False (Sem barra do Windows)
dpg.create_viewport(title=APP_TITLE, width=WINDOW_WIDTH, height=WINDOW_HEIGHT, 
                    decorated=False, resizable=False, small_icon="app.ico")

dpg.setup_dearpygui()
dpg.show_viewport()
dpg.set_primary_window("Primary Window", True)

while dpg.is_dearpygui_running():
    dpg.render_dearpygui_frame()

dpg.destroy_context()