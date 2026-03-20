"""
MainWindow - Janela principal do bot (GUI separada do main.py)

Padrão: Dependency Injection via MainWindowCallbacks dataclass.
Threads em main.py acessam widgets via referências expostas.
"""

import customtkinter as ctk
import tkinter as tk
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from auto_update import CURRENT_VERSION


# ==============================================================================
# CALLBACKS DATACLASS
# ==============================================================================

@dataclass
class MainWindowCallbacks:
    """
    Todos os callbacks e state providers que a MainWindow precisa.
    Injetados por main.py para evitar circular imports.
    """
    # === State Providers ===
    get_bot_settings: Callable[[], Dict[str, Any]]
    get_state: Callable[[], Any]  # BotState
    get_pm: Callable[[], Any]
    get_base_addr: Callable[[], int]

    # === Module Status ===
    get_module_status: Callable[[], Dict[str, str]]
    get_module_icons: Callable[[], Dict[str, str]]
    get_cavebot_instance: Callable[[], Any]

    # === Action Callbacks ===
    open_settings: Callable[[], None]
    on_close: Callable[[], None]
    on_reload: Callable[[], None]
    toggle_xray: Callable[[], None]
    toggle_cavebot: Callable[[], None]
    on_fisher_toggle: Callable[[], None]
    on_pause_toggle: Callable[[bool], None]  # Called with is_pausing=True/False

    # === Utility Toggles ===
    on_light_toggle: Callable[[bool], None]
    on_spear_picker_toggle: Callable[[bool], None]
    on_auto_torch_toggle: Callable[[bool], None]

    # === Trackers ===
    get_sword_tracker: Callable[[], Any]
    get_shield_tracker: Callable[[], Any]
    get_magic_tracker: Callable[[], Any]
    get_exp_tracker: Callable[[], Any]
    get_gold_tracker: Callable[[], Any]
    get_regen_tracker: Callable[[], Any]

    # === Config ===
    reload_button_enabled: bool = False
    maps_directory: str = ""
    walkable_colors: List[int] = None

    # === Mini HUD ===
    get_tibia_hwnd: Callable[[], int] = None  # Retorna hwnd da janela do Tibia


# ==============================================================================
# MAIN WINDOW CLASS
# ==============================================================================

class MainWindow:
    """
    Janela principal do bot.
    Cria todos os widgets e expõe referências para threads.
    """

    def __init__(self, callbacks: MainWindowCallbacks):
        """
        Inicializa a janela principal.

        Args:
            callbacks: Objeto com todos os callbacks e providers necessários
        """
        self.callbacks = callbacks
        self.app: ctk.CTk = None

        # === Estado Interno ===
        self.log_visible = False
        self.is_paused = False
        self.paused_switch_states = {}  # {switch_name: bool}
        self.paused_settings_states = {}  # {setting_name: value}

        # === Performance Optimization State ===
        self._resize_job = None  # Debounce para auto_resize
        self._last_status_hash = None  # Cache para update_status_panel

        # === Stats Collapsible State ===
        self.stats_expanded = False

        # === Mini HUD State ===
        self.mini_hud = None
        self.mini_hud_visible = False
        self._mini_drag_data = {"x": 0, "y": 0}

        # === Widgets Expostos (threads precisam acessar) ===
        # Header
        self.btn_xray: ctk.CTkButton = None
        self.btn_settings: ctk.CTkButton = None
        self.btn_pause: ctk.CTkButton = None
        self.btn_reload: ctk.CTkButton = None
        self.lbl_connection: ctk.CTkLabel = None

        # Controls (Switches)
        self.switch_trainer: ctk.CTkSwitch = None
        self.switch_loot: ctk.CTkSwitch = None
        self.switch_alarm: ctk.CTkSwitch = None
        self.switch_fisher: ctk.CTkSwitch = None
        self.switch_runemaker: ctk.CTkSwitch = None
        self.switch_cavebot: ctk.CTkSwitch = None
        self.switch_cavebot_var: ctk.IntVar = None
        self.switch_healer: ctk.CTkSwitch = None

        # Utility Toggles
        self.switch_torch: ctk.CTkSwitch = None
        self.switch_light: ctk.CTkSwitch = None
        self.switch_spear: ctk.CTkSwitch = None

        # Stats Labels
        self.lbl_exp_left_summary: ctk.CTkLabel = None
        self.lbl_exp_rate: ctk.CTkLabel = None
        self.lbl_exp_eta_summary: ctk.CTkLabel = None
        self.lbl_regen: ctk.CTkLabel = None
        self.lbl_regen_stock: ctk.CTkLabel = None
        self.lbl_gold_total: ctk.CTkLabel = None
        self.lbl_gold_rate: ctk.CTkLabel = None
        self.lbl_primary_skill_name: ctk.CTkLabel = None  # Label dinâmico (Sword/Club/Axe/Distance)
        self.lbl_sword_val: ctk.CTkLabel = None
        self.lbl_sword_rate: ctk.CTkLabel = None
        self.lbl_sword_time: ctk.CTkLabel = None
        self.lbl_shield_val: ctk.CTkLabel = None
        self.lbl_shield_rate: ctk.CTkLabel = None
        self.lbl_shield_time: ctk.CTkLabel = None
        self.lbl_magic_val: ctk.CTkLabel = None
        self.lbl_magic_rate: ctk.CTkLabel = None
        self.lbl_magic_time: ctk.CTkLabel = None

        # Stats Frames (para show/hide por vocação)
        self.box_sword: ctk.CTkFrame = None
        self.frame_sw_det: ctk.CTkFrame = None
        self.box_shield: ctk.CTkFrame = None
        self.frame_sh_det: ctk.CTkFrame = None
        self.frame_stats: ctk.CTkFrame = None

        # Minimap
        self.minimap_container: ctk.CTkFrame = None
        self.minimap_label: ctk.CTkLabel = None
        self.minimap_title_label: ctk.CTkLabel = None
        self.minimap_status_label: ctk.CTkLabel = None
        self.minimap_visualizer = None
        self.minimap_image_ref = None

        # Status Panel
        self.frame_status_panel: ctk.CTkFrame = None
        self.status_labels: Dict[str, ctk.CTkLabel] = {}

        # Log
        self.txt_log: ctk.CTkTextbox = None

        # Main frame reference
        self.main_frame: ctk.CTkFrame = None

    def create(self) -> ctk.CTk:
        """
        Cria a janela principal e todos os widgets.

        Returns:
            A instância CTk da aplicação
        """
        ctk.set_appearance_mode("Dark")
        ctk.set_default_color_theme("blue")

        self.app = ctk.CTk()
        self.app.title(f"Molodoy Bot Pro v{CURRENT_VERSION}")
        self.app.resizable(True, True)
        self.app.configure(fg_color="#202020")

        try:
            self.app.iconbitmap("app.ico")
        except:
            pass

        # Main Frame
        self.main_frame = ctk.CTkFrame(self.app, fg_color="transparent")
        self.main_frame.pack(fill="both", expand=True)

        # Criar componentes
        self._create_header()
        self._create_controls()
        self._create_utility_toggles()
        self._create_stats()  # Stats colapsável (sem gráfico)
        self._create_minimap_panel()
        self._create_status_panel()
        self._create_log()

        # Sincroniza log_visible com BOT_SETTINGS
        settings = self.callbacks.get_bot_settings()
        self.log_visible = settings.get('console_log_visible', False)

        if self.log_visible:
            self.txt_log.pack(side="bottom", fill="x", padx=5, pady=5, expand=True)
        else:
            self.frame_status_panel.pack(side="bottom", fill="x", padx=8, pady=3)

        return self.app

    def _create_header(self):
        """Cria o header com status de conexão e botões em uma linha."""
        frame_header = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        frame_header.pack(pady=(5, 3), fill="x", padx=10)

        # Connection status (esquerda, largura limitada para não empurrar botões)
        self.lbl_connection = ctk.CTkLabel(
            frame_header, text="🔌 Procurando...",
            font=("Verdana", 10),
            text_color="#FFA500",
            width=70, anchor="w"
        )
        self.lbl_connection.pack(side="left")

        # X-Ray Button (direita - primeiro para ficar mais à direita)
        self.btn_xray = ctk.CTkButton(
            frame_header, text="Raio-X",
            command=self.callbacks.toggle_xray,
            width=50, height=25, fg_color="#303030",
            font=("Verdana", 10)
        )
        self.btn_xray.pack(side="right")

        # Pause/Resume Button (direita)
        self.btn_pause = ctk.CTkButton(
            frame_header, text="⏸️ Pausar",
            command=self.toggle_pause,
            width=60, height=25,
            fg_color="#303030", hover_color="#505050",
            font=("Verdana", 10)
        )
        self.btn_pause.pack(side="right", padx=3)

        # Settings Button (direita)
        self.btn_settings = ctk.CTkButton(
            frame_header, text="⚙️ Config.",
            command=self.callbacks.open_settings,
            width=60, height=25,
            fg_color="#303030", hover_color="#505050",
            font=("Verdana", 10, "bold")
        )
        self.btn_settings.pack(side="right")

        # Reload Button (opcional, direita)
        if self.callbacks.reload_button_enabled:
            self.btn_reload = ctk.CTkButton(
                frame_header, text="🔄",
                command=self.callbacks.on_reload,
                width=30, height=25,
                fg_color="#303030", hover_color="#505050",
                font=("Verdana", 10)
            )
            self.btn_reload.pack(side="right", padx=2)

    def _create_controls(self):
        """Cria os switches de controle dos módulos."""
        frame_controls = ctk.CTkFrame(
            self.main_frame, fg_color="#303030", corner_radius=6
        )
        frame_controls.pack(padx=10, pady=3, fill="x")
        frame_controls.grid_columnconfigure(0, weight=1)
        frame_controls.grid_columnconfigure(1, weight=1)

        # Trainer
        self.switch_trainer = ctk.CTkSwitch(
            frame_controls, text="Trainer",
            progress_color="#00C000", font=("Verdana", 11)
        )
        self.switch_trainer.grid(row=0, column=0, sticky="w", padx=(20, 0), pady=2)

        # Auto Loot
        self.switch_loot = ctk.CTkSwitch(
            frame_controls, text="Auto Loot",
            progress_color="#00C000", font=("Verdana", 11)
        )
        self.switch_loot.grid(row=1, column=0, sticky="w", padx=(20, 0), pady=2)

        # Alarm
        self.switch_alarm = ctk.CTkSwitch(
            frame_controls, text="Alarm",
            progress_color="#00C000", font=("Verdana", 11)
        )
        self.switch_alarm.grid(row=0, column=1, sticky="w", padx=(10, 0), pady=2)

        # Fisher
        self.switch_fisher = ctk.CTkSwitch(
            frame_controls, text="Auto Fisher",
            command=self.callbacks.on_fisher_toggle,
            progress_color="#00C000", font=("Verdana", 11)
        )
        self.switch_fisher.grid(row=1, column=1, sticky="w", padx=(10, 0), pady=2)

        # Runemaker
        self.switch_runemaker = ctk.CTkSwitch(
            frame_controls, text="Runemaker",
            progress_color="#A54EF9", font=("Verdana", 11)
        )
        self.switch_runemaker.grid(row=2, column=0, sticky="w", padx=(20, 0), pady=2)

        # Cavebot
        self.switch_cavebot_var = ctk.IntVar(value=0)
        self.switch_cavebot = ctk.CTkSwitch(
            frame_controls, text="Cavebot",
            variable=self.switch_cavebot_var,
            command=self.callbacks.toggle_cavebot,
            progress_color="#2CC985", font=("Verdana", 11)
        )
        self.switch_cavebot.grid(row=2, column=1, sticky="w", padx=(10, 0), pady=2)

        # Healer
        self.switch_healer = ctk.CTkSwitch(
            frame_controls, text="Healer",
            progress_color="#FF6B6B", font=("Verdana", 11)
        )
        self.switch_healer.grid(row=3, column=0, sticky="w", padx=(20, 0), pady=2)

    def _create_utility_toggles(self):
        """Cria a linha de toggles utilitários (Tocha, Light, Spear)."""
        settings = self.callbacks.get_bot_settings()

        frame_utils = ctk.CTkFrame(
            self.main_frame, fg_color="#252525", corner_radius=6
        )
        frame_utils.pack(padx=10, pady=(0, 3), fill="x")
        frame_utils.grid_columnconfigure(0, weight=1)
        frame_utils.grid_columnconfigure(1, weight=1)
        frame_utils.grid_columnconfigure(2, weight=0)

        # Auto Torch
        self.switch_torch = ctk.CTkSwitch(
            frame_utils, text="Tocha", width=35,
            command=lambda: self.callbacks.on_auto_torch_toggle(bool(self.switch_torch.get())),
            progress_color="#F39C12", font=("Verdana", 10)
        )
        self.switch_torch.grid(row=0, column=0, sticky="w", padx=(10, 0), pady=2)
        if settings.get('auto_torch_enabled', False):
            self.switch_torch.select()

        # Full Light
        self.switch_light = ctk.CTkSwitch(
            frame_utils, text="Light", width=35,
            command=lambda: self.callbacks.on_light_toggle(bool(self.switch_light.get())),
            progress_color="#FFA500", font=("Verdana", 10)
        )
        self.switch_light.grid(row=0, column=1, sticky="w", padx=(5, 0), pady=2)
        if settings.get('full_light_enabled', False):
            self.switch_light.select()

        # Spear Picker + Count
        frame_spear = ctk.CTkFrame(frame_utils, fg_color="transparent")
        frame_spear.grid(row=0, column=2, sticky="w", padx=(0, 0), pady=2)

        self.switch_spear = ctk.CTkSwitch(
            frame_spear, text="Spear", width=35,
            command=lambda: self.callbacks.on_spear_picker_toggle(bool(self.switch_spear.get())),
            progress_color="#E67E22", font=("Verdana", 10)
        )
        self.switch_spear.pack(side="left")
        if settings.get('spear_picker_enabled', False):
            self.switch_spear.select()

        self.entry_spear_count = ctk.CTkEntry(frame_spear, width=30, height=20, font=("Verdana", 9), justify="center")
        self.entry_spear_count.pack(side="left", padx=(2, 0))
        self.entry_spear_count.insert(0, str(settings.get('spear_max_count', 3)))

        def on_spear_count_change(event=None):
            try:
                val = int(self.entry_spear_count.get())
                val = max(1, min(100, val))
                self.callbacks.get_bot_settings()['spear_max_count'] = val
            except ValueError:
                pass

        self.entry_spear_count.bind("<FocusOut>", on_spear_count_change)
        self.entry_spear_count.bind("<Return>", on_spear_count_change)

    def _create_stats(self):
        """Cria o painel de estatísticas colapsável."""
        # === CONFIGURAÇÃO DE FONTE (mudar aqui para alterar todos) ===
        FONT_SUMMARY = 10  # Fonte do título/summary
        FONT_DETAILS = 11  # Fonte dos detalhes expandidos
        FONT_RATE = 9      # Fonte dos rates (m/%)

        self.frame_stats = ctk.CTkFrame(
            self.main_frame, fg_color="transparent",
            border_color="#303030", border_width=1, corner_radius=6
        )
        self.frame_stats.pack(padx=10, pady=3, fill="x")

        # === SUMMARY (sempre visível - 1 linha compacta) ===
        self.stats_summary_frame = ctk.CTkFrame(self.frame_stats, fg_color="transparent")
        self.stats_summary_frame.pack(fill="x", padx=10, pady=2)

        # Botão expand/collapse (PRIMEIRO para garantir espaço)
        self.btn_stats_toggle = ctk.CTkButton(
            self.stats_summary_frame, text="▼", width=24, height=24,
            fg_color="transparent", hover_color="#303030",
            font=("Verdana", FONT_SUMMARY), command=self.toggle_stats
        )
        self.btn_stats_toggle.pack(side="right")

        # XP Rate
        self.lbl_exp_rate = ctk.CTkLabel(
            self.stats_summary_frame, text="-- xp/h",
            font=("Verdana", FONT_SUMMARY, "bold"), text_color="#FFFFFF"
        )
        self.lbl_exp_rate.pack(side="left")

        ctk.CTkLabel(
            self.stats_summary_frame, text="|",
            font=("Verdana", FONT_SUMMARY), text_color="#555555"
        ).pack(side="left", padx=2)

        # XP Left (no summary)
        self.lbl_exp_left_summary = ctk.CTkLabel(
            self.stats_summary_frame, text="-- left",
            font=("Verdana", FONT_SUMMARY), text_color="gray"
        )
        self.lbl_exp_left_summary.pack(side="left")

        ctk.CTkLabel(
            self.stats_summary_frame, text="|",
            font=("Verdana", FONT_SUMMARY), text_color="#555555"
        ).pack(side="left", padx=2)

        # ETA Next Level (no summary)
        self.lbl_exp_eta_summary = ctk.CTkLabel(
            self.stats_summary_frame, text="⏳ --",
            font=("Verdana", FONT_SUMMARY), text_color="gray"
        )
        self.lbl_exp_eta_summary.pack(side="left")

        ctk.CTkLabel(
            self.stats_summary_frame, text="|",
            font=("Verdana", FONT_SUMMARY), text_color="#555555"
        ).pack(side="left", padx=2)

        # Regen Status (compacto)
        self.lbl_regen = ctk.CTkLabel(
            self.stats_summary_frame, text="Regen --",
            font=("Verdana", FONT_SUMMARY), text_color="#2CC985"
        )
        self.lbl_regen.pack(side="left")

        # === DETAILS (oculto por padrão) ===
        self.stats_details_frame = ctk.CTkFrame(self.frame_stats, fg_color="transparent")
        # NÃO pack - começa oculto

        # Divisória
        ctk.CTkFrame(self.stats_details_frame, height=1, fg_color="#303030").pack(
            fill="x", padx=0, pady=(0, 0)
        )

        # Food + Gold (primeira linha do details)
        frame_resources = ctk.CTkFrame(self.stats_details_frame, fg_color="transparent", height=20)
        frame_resources.pack(fill="x", pady=(0, 2))
        frame_resources.pack_propagate(False)

        # Food (esquerda)
        self.lbl_regen_stock = ctk.CTkLabel(
            frame_resources, text="🍖 --",
            font=("Verdana", FONT_DETAILS)
        )
        self.lbl_regen_stock.pack(side="left")

        # Gold rate (direita)
        self.lbl_gold_rate = ctk.CTkLabel(
            frame_resources, text="(0/h)",
            font=("Verdana", FONT_DETAILS), text_color="gray"
        )
        self.lbl_gold_rate.pack(side="right")

        # Gold total (direita, antes do rate)
        self.lbl_gold_total = ctk.CTkLabel(
            frame_resources, text="0 gp",
            font=("Verdana", FONT_DETAILS, "bold"), text_color="#FFD700"
        )
        self.lbl_gold_total.pack(side="right", padx=(0, 5))

        # PRIMARY SKILL (Sword/Club/Axe/Distance)
        self.box_sword = ctk.CTkFrame(self.stats_details_frame, fg_color="transparent", height=20)
        self.box_sword.pack(fill="x")
        self.box_sword.pack_propagate(False)

        # Emoji separado (atualizado dinamicamente)
        self.lbl_primary_skill_emoji = ctk.CTkLabel(
            self.box_sword, text="⚔",
            font=("Verdana", FONT_DETAILS)
        )
        self.lbl_primary_skill_emoji.pack(side="left")

        self.lbl_sword_val = ctk.CTkLabel(
            self.box_sword, text="--",
            font=("Verdana", FONT_DETAILS, "bold"), text_color="#4EA5F9"
        )
        self.lbl_sword_val.pack(side="left", padx=(5, 0))

        self.lbl_sword_time = ctk.CTkLabel(
            self.box_sword, text="⏳ --",
            font=("Verdana", FONT_DETAILS), text_color="gray"
        )
        self.lbl_sword_time.pack(side="right")

        self.lbl_sword_rate = ctk.CTkLabel(
            self.box_sword, text="--m/%",
            font=("Verdana", FONT_RATE), text_color="gray"
        )
        self.lbl_sword_rate.pack(side="right", padx=(0, 10))

        # Frame containers para compatibilidade (usado em update_stats_visibility)
        self.frame_sw_det = self.box_sword

        # SHIELD
        self.box_shield = ctk.CTkFrame(self.stats_details_frame, fg_color="transparent", height=20)
        self.box_shield.pack(fill="x")
        self.box_shield.pack_propagate(False)

        ctk.CTkLabel(self.box_shield, text="🛡", font=("Verdana", FONT_DETAILS)).pack(side="left")

        self.lbl_shield_val = ctk.CTkLabel(
            self.box_shield, text="--",
            font=("Verdana", FONT_DETAILS, "bold"), text_color="#4EA5F9"
        )
        self.lbl_shield_val.pack(side="left", padx=(5, 0))

        self.lbl_shield_time = ctk.CTkLabel(
            self.box_shield, text="⏳ --",
            font=("Verdana", FONT_DETAILS), text_color="gray"
        )
        self.lbl_shield_time.pack(side="right")

        self.lbl_shield_rate = ctk.CTkLabel(
            self.box_shield, text="--m/%",
            font=("Verdana", FONT_RATE), text_color="gray"
        )
        self.lbl_shield_rate.pack(side="right", padx=(0, 10))

        self.frame_sh_det = self.box_shield

        # MAGIC LEVEL
        box_magic = ctk.CTkFrame(self.stats_details_frame, fg_color="transparent", height=20)
        box_magic.pack(fill="x")
        box_magic.pack_propagate(False)

        ctk.CTkLabel(box_magic, text="🪄", font=("Verdana", FONT_DETAILS)).pack(side="left")

        self.lbl_magic_val = ctk.CTkLabel(
            box_magic, text="--",
            font=("Verdana", FONT_DETAILS, "bold"), text_color="#A54EF9"
        )
        self.lbl_magic_val.pack(side="left", padx=(5, 0))

        self.lbl_magic_time = ctk.CTkLabel(
            box_magic, text="⏳ --",
            font=("Verdana", FONT_DETAILS), text_color="gray"
        )
        self.lbl_magic_time.pack(side="right")

        self.lbl_magic_rate = ctk.CTkLabel(
            box_magic, text="--m/%",
            font=("Verdana", FONT_RATE), text_color="gray"
        )
        self.lbl_magic_rate.pack(side="right", padx=(0, 10))

    def toggle_stats(self):
        """Alterna entre stats expandido e colapsado."""
        self.stats_expanded = not self.stats_expanded

        if self.stats_expanded:
            self.stats_details_frame.pack(fill="x", padx=10, pady=(0, 3))
            self.btn_stats_toggle.configure(text="▲")
        else:
            self.stats_details_frame.pack_forget()
            self.btn_stats_toggle.configure(text="▼")

        self.auto_resize_window()

    def _create_minimap_panel(self):
        """Cria o painel do minimap (mostrado quando cavebot está ativo)."""
        # Container frame (NÃO empacotado - será mostrado quando cavebot ligar)
        self.minimap_container = ctk.CTkFrame(
            self.main_frame,
            fg_color="#1a1a1a",
            border_color="#303030",
            border_width=1,
            corner_radius=6
        )
        # NÃO chamar pack() aqui - minimap começa escondido

        # Title label
        self.minimap_title_label = ctk.CTkLabel(
            self.minimap_container,
            text="",
            font=("Verdana", 11, "bold"),
            text_color="#FFFFFF"
        )
        self.minimap_title_label.pack(pady=(8, 0))

        # Label to display minimap image
        self.minimap_label = ctk.CTkLabel(
            self.minimap_container,
            text="⏳ Aguardando Cavebot...",
            font=("Verdana", 11),
            text_color="#888888"
        )
        self.minimap_label.pack(padx=10, pady=5)
        # minimap_visualizer será inicializado em show_minimap_panel() (lazy loading)

    def _init_minimap_visualizer(self):
        """Inicializa o visualizador de minimap."""
        try:
            from utils.realtime_minimap import RealtimeMinimapVisualizer
            from utils.color_palette import COLOR_PALETTE

            settings = self.callbacks.get_bot_settings()
            maps_dir = settings.get('client_path') or self.callbacks.maps_directory
            walkable = self.callbacks.walkable_colors or []

            self.minimap_visualizer = RealtimeMinimapVisualizer(
                maps_dir,
                walkable,
                COLOR_PALETTE
            )
        except Exception as e:
            print(f"[MainWindow] Erro ao inicializar minimap visualizer: {e}")

    def _create_status_panel(self):
        """Cria o painel de status dos módulos."""
        self.frame_status_panel = ctk.CTkFrame(
            self.main_frame, fg_color="#1a1a1a",
            border_color="#303030", border_width=1,
            corner_radius=6
        )
        # NÃO pack() aqui - visibilidade controlada por toggle

        # Criar labels para cada módulo
        for module in ['trainer', 'runemaker', 'fisher', 'cavebot', 'alarm']:
            self.status_labels[module] = ctk.CTkLabel(
                self.frame_status_panel,
                text="",
                font=("Consolas", 11),
                text_color="#AAAAAA",
                anchor="w"
            )
            # NÃO pack() - visibilidade controlada por update_status_panel()

    def _create_log(self):
        """Cria a textbox de log."""
        self.txt_log = ctk.CTkTextbox(
            self.main_frame, height=80,
            font=("Consolas", 11),
            fg_color="#151515", text_color="#00FF00",
            border_width=1
        )
        # NÃO pack() aqui - controlado por toggle

    # ==========================================================================
    # MÉTODOS PÚBLICOS
    # ==========================================================================

    def toggle_pause(self):
        """
        Alterna entre pausar e resumir todos os módulos.
        Ao pausar: salva estado atual, desliga tudo, mostra "Pausado".
        Ao resumir: restaura estados anteriores.
        """
        if not self.is_paused:
            # === PAUSANDO ===
            # Salvar estado atual dos switches
            self.paused_switch_states = {
                'trainer': self.switch_trainer.get() if self.switch_trainer else False,
                'loot': self.switch_loot.get() if self.switch_loot else False,
                'alarm': self.switch_alarm.get() if self.switch_alarm else False,
                'fisher': self.switch_fisher.get() if self.switch_fisher else False,
                'runemaker': self.switch_runemaker.get() if self.switch_runemaker else False,
                'cavebot': self.switch_cavebot_var.get() if self.switch_cavebot_var else 0,
                'healer': self.switch_healer.get() if self.switch_healer else False,
            }

            # Chamar callback para salvar e desativar settings (light, spear, torch, ai)
            if hasattr(self.callbacks, 'on_pause_toggle'):
                self.callbacks.on_pause_toggle(True)

            # Desligar todos os switches visualmente
            if self.switch_trainer:
                self.switch_trainer.deselect()
            if self.switch_loot:
                self.switch_loot.deselect()
            if self.switch_alarm:
                self.switch_alarm.deselect()
            if self.switch_fisher:
                self.switch_fisher.deselect()
            if self.switch_runemaker:
                self.switch_runemaker.deselect()
            if self.switch_healer:
                self.switch_healer.deselect()

            # Cavebot precisa chamar toggle se estava ligado
            if self.paused_switch_states.get('cavebot', 0):
                self.switch_cavebot_var.set(0)
                if hasattr(self.callbacks, 'toggle_cavebot'):
                    self.callbacks.toggle_cavebot()

            # Atualizar UI
            self.btn_pause.configure(text="▶️ Retomar", fg_color="#FF6600")
            self.set_connection_status("⏸️ Pausado", "#FFA500")
            self.is_paused = True

        else:
            # === RESUMINDO ===
            # Restaurar switches para estado anterior
            if self.paused_switch_states.get('trainer', False) and self.switch_trainer:
                self.switch_trainer.select()
            if self.paused_switch_states.get('loot', False) and self.switch_loot:
                self.switch_loot.select()
            if self.paused_switch_states.get('alarm', False) and self.switch_alarm:
                self.switch_alarm.select()
            if self.paused_switch_states.get('fisher', False) and self.switch_fisher:
                self.switch_fisher.select()
            if self.paused_switch_states.get('runemaker', False) and self.switch_runemaker:
                self.switch_runemaker.select()
            if self.paused_switch_states.get('healer', False) and self.switch_healer:
                self.switch_healer.select()

            # Cavebot precisa chamar toggle se estava ligado antes
            if self.paused_switch_states.get('cavebot', 0):
                self.switch_cavebot_var.set(1)
                if hasattr(self.callbacks, 'toggle_cavebot'):
                    self.callbacks.toggle_cavebot()

            # Chamar callback para restaurar settings
            if hasattr(self.callbacks, 'on_pause_toggle'):
                self.callbacks.on_pause_toggle(False)

            # Atualizar UI
            self.btn_pause.configure(text="⏸️ Pausar", fg_color="#303030")
            # Connection status será atualizado pelo watchdog automaticamente
            self.is_paused = False

    def update_stats_visibility(self):
        """
        Ajusta a interface baseada na vocação:
        - Mages: Esconde Sword e Shield (stats de melee)
        - Knights/Paladins: Mostra tudo
        """
        settings = self.callbacks.get_bot_settings()
        voc = settings.get('vocation', 'Knight')
        is_mage = any(x in voc for x in ["Elder", "Master", "Druid", "Sorcerer", "Mage", "None"])

        if is_mage:
            # Esconde Stats de Melee (dentro do details_frame)
            self.box_sword.pack_forget()
            self.box_shield.pack_forget()
        else:
            # Mostra Stats de Melee (sem padding extra - altura fixa de 18px)
            self.box_sword.pack(fill="x")
            self.box_shield.pack(fill="x")

        self.auto_resize_window()

    def update_status_panel(self):
        """
        Atualiza os labels do Status Panel baseado nos módulos ativos.
        Chamada periodicamente pelo gui_updater_loop.
        Usa cache hash para evitar atualizações desnecessárias.
        """
        # Se console log está ativo ou status panel não existe, não atualiza
        if self.log_visible or not self.frame_status_panel:
            return

        module_status = self.callbacks.get_module_status()
        module_icons = self.callbacks.get_module_icons()
        cavebot = self.callbacks.get_cavebot_instance()

        # Atualizar status do cavebot da instância
        if cavebot and hasattr(cavebot, 'state_message'):
            module_status['cavebot'] = cavebot.state_message or ""

        # Verificar quais módulos estão ativos
        active_modules = []
        try:
            if self.switch_trainer.get():
                active_modules.append('trainer')
            if self.switch_runemaker.get():
                active_modules.append('runemaker')
            if self.switch_fisher.get():
                active_modules.append('fisher')
            if self.switch_cavebot_var.get():
                active_modules.append('cavebot')
            if self.switch_alarm.get():
                active_modules.append('alarm')
            if self.switch_healer and self.switch_healer.get():
                active_modules.append('healer')
        except:
            pass

        # Cache: só atualiza se estado mudou
        status_tuple = tuple((m, module_status.get(m, "")) for m in active_modules)
        current_hash = hash((tuple(active_modules), status_tuple))
        if current_hash == self._last_status_hash:
            return  # Nada mudou, skip update
        self._last_status_hash = current_hash

        # Esconder todos os labels primeiro
        for module, label in self.status_labels.items():
            label.pack_forget()

        # Mostrar apenas os ativos com status
        shown = False
        for module in active_modules:
            status = module_status.get(module, "")
            if status:
                icon = module_icons.get(module, "•")
                # Truncar status se muito longo
                if len(status) > 45:
                    status = status[:42] + "..."
                self.status_labels[module].configure(
                    text=f"{icon} {module.capitalize()}: {status}"
                )
                self.status_labels[module].pack(fill="x", padx=8, pady=1, anchor="w")
                shown = True

        # Se nenhum módulo ativo ou sem status, mostrar mensagem padrão
        if not shown:
            if active_modules:
                self.status_labels['trainer'].configure(text="⏳ Aguardando atividade...")
            else:
                self.status_labels['trainer'].configure(text="💤 Nenhum módulo ativo")
            self.status_labels['trainer'].pack(fill="x", padx=8, pady=2, anchor="w")

        self.auto_resize_window()

    def toggle_log_visibility(self):
        """
        Toggle entre Console Log e Status Panel.
        - Console Log ON: Mostra log tradicional, esconde status panel
        - Console Log OFF: Mostra status panel, esconde log
        """
        self.log_visible = not self.log_visible

        settings = self.callbacks.get_bot_settings()
        settings['console_log_visible'] = self.log_visible

        if self.log_visible:
            # Console Log ativo - esconder status panel
            if self.frame_status_panel:
                self.frame_status_panel.pack_forget()
            if self.txt_log:
                self.txt_log.pack(side="bottom", fill="x", padx=5, pady=5, expand=True)
        else:
            # Status Panel ativo - esconder console log
            if self.txt_log:
                self.txt_log.pack_forget()
            if self.frame_status_panel:
                self.frame_status_panel.pack(side="bottom", fill="x", padx=8, pady=3)
                # Usar after() para garantir que o pack seja processado antes de atualizar
                self.app.after(20, self.update_status_panel)
                return  # auto_resize será chamado por update_status_panel

        self.auto_resize_window()

    def show_minimap_panel(self):
        """Mostra o painel do minimap e redimensiona a GUI."""
        if self.minimap_container and not self.minimap_container.winfo_ismapped():
            # Lazy load do visualizer na primeira vez
            if self.minimap_visualizer is None:
                self._init_minimap_visualizer()
            self.minimap_container.pack(fill="x", padx=10, pady=3)
            self.app.after(100, self.auto_resize_window)

    def hide_minimap_panel(self):
        """Esconde o painel do minimap e redimensiona a GUI."""
        if self.minimap_container and self.minimap_container.winfo_ismapped():
            self.minimap_container.pack_forget()
            self.app.after(100, self.auto_resize_window)

    def auto_resize_window(self):
        """
        Calcula o tamanho necessário para o conteúdo e ajusta a janela.
        Mantém a largura fixa em 320. Usa debounce para evitar múltiplas execuções.
        """
        # Cancelar job pendente (debounce)
        if self._resize_job:
            try:
                self.app.after_cancel(self._resize_job)
            except:
                pass

        def do_resize():
            self._resize_job = None
            self.app.update_idletasks()
            h = self.main_frame.winfo_reqheight() + 12
            self.app.geometry(f"300x{h}")

        self._resize_job = self.app.after(50, do_resize)  # 50ms debounce

    def log(self, msg: str):
        """Adiciona mensagem ao log."""
        try:
            from datetime import datetime
            now = datetime.now().strftime("%H:%M:%S")
            final_msg = f"[{now}] {msg}\n"
            self.txt_log.insert("end", final_msg)
            self.txt_log.see("end")
        except:
            pass

    def set_connection_status(self, text: str, color: str):
        """Atualiza o label de status de conexão."""
        if self.lbl_connection:
            self.lbl_connection.configure(text=text, text_color=color)

    def set_xray_button_color(self, color: str):
        """Atualiza a cor do botão X-Ray."""
        if self.btn_xray:
            self.btn_xray.configure(fg_color=color)

    def update_primary_skill_label(self, skill_name: str):
        """Atualiza o emoji do skill principal (Sword/Club/Axe/Distance)."""
        if hasattr(self, 'lbl_primary_skill_emoji') and self.lbl_primary_skill_emoji:
            # Emojis para cada tipo de skill
            skill_emojis = {
                "Distance": "🏹",
                "Sword": "⚔",
                "Club": "🔨",
                "Axe": "🪓"
            }
            emoji = skill_emojis.get(skill_name, "⚔")
            self.lbl_primary_skill_emoji.configure(text=emoji)

    # ==========================================================================
    # MINI HUD MODE
    # ==========================================================================

    def _create_mini_hud(self):
        """
        Cria a Mini HUD - janela compacta flutuante que aparece quando o bot é minimizado.
        Mostra stats essenciais e permite restaurar a janela principal.
        """
        self.mini_hud = ctk.CTkToplevel(self.app)
        self.mini_hud.title("MolodoyBot")
        self.mini_hud.geometry("280x58")
        self.mini_hud.resizable(False, False)
        self.mini_hud.configure(fg_color="#1a1a1a")

        # Sempre no topo, sem taskbar
        self.mini_hud.attributes("-topmost", True)
        self.mini_hud.overrideredirect(True)  # Remove bordas do Windows

        # Frame principal com borda
        frame = ctk.CTkFrame(
            self.mini_hud, fg_color="#1a1a1a",
            border_color="#404040", border_width=1, corner_radius=8
        )
        frame.pack(fill="both", expand=True, padx=2, pady=2)

        # Linha 1: Status + XP Rate
        row1 = ctk.CTkFrame(frame, fg_color="transparent")
        row1.pack(fill="x", padx=8, pady=(5, 0))

        self.mini_status = ctk.CTkLabel(
            row1, text="●", font=("Verdana", 10),
            text_color="#00FF00", width=15
        )
        self.mini_status.pack(side="left")

        self.mini_xp_rate = ctk.CTkLabel(
            row1, text="-- xp/h",
            font=("Verdana", 10, "bold"), text_color="#FFFFFF"
        )
        self.mini_xp_rate.pack(side="left", padx=(5, 0))

        self.mini_eta = ctk.CTkLabel(
            row1, text="",
            font=("Verdana", 9), text_color="#888888"
        )
        self.mini_eta.pack(side="right")

        # Linha 2: Botões de módulos (toggle rápido) + restaurar
        row2 = ctk.CTkFrame(frame, fg_color="transparent")
        row2.pack(fill="x", padx=4, pady=(2, 4))

        # Fonte com suporte a emoji (Segoe UI Emoji no Windows)
        emoji_font = ("Segoe UI Emoji", 9)
        btn_style = {"height": 22, "fg_color": "#303030", "hover_color": "#454545", "corner_radius": 4}

        self.mini_btn_trainer = ctk.CTkButton(
            row2, text="⚔T", width=36, font=emoji_font,
            command=lambda: self._mini_toggle_module("trainer"), **btn_style
        )
        self.mini_btn_trainer.pack(side="left", padx=1)

        self.mini_btn_loot = ctk.CTkButton(
            row2, text="🪙L", width=36, font=emoji_font,
            command=lambda: self._mini_toggle_module("loot"), **btn_style
        )
        self.mini_btn_loot.pack(side="left", padx=1)

        self.mini_btn_cavebot = ctk.CTkButton(
            row2, text="🚶C", width=36, font=emoji_font,
            command=lambda: self._mini_toggle_module("cavebot"), **btn_style
        )
        self.mini_btn_cavebot.pack(side="left", padx=1)

        self.mini_btn_healer = ctk.CTkButton(
            row2, text="❤H", width=36, font=emoji_font,
            command=lambda: self._mini_toggle_module("healer"), **btn_style
        )
        self.mini_btn_healer.pack(side="left", padx=1)

        self.mini_btn_alarm = ctk.CTkButton(
            row2, text="🔔A", width=36, font=emoji_font,
            command=lambda: self._mini_toggle_module("alarm"), **btn_style
        )
        self.mini_btn_alarm.pack(side="left", padx=1)

        self.mini_btn_runemaker = ctk.CTkButton(
            row2, text="✨R", width=36, font=emoji_font,
            command=lambda: self._mini_toggle_module("runemaker"), **btn_style
        )
        self.mini_btn_runemaker.pack(side="left", padx=1)

        btn_restore = ctk.CTkButton(
            row2, text="↗", width=26, height=22,
            font=("Segoe UI Emoji", 11), fg_color="#505050",
            hover_color="#606060", corner_radius=4, command=self._restore_from_mini
        )
        btn_restore.pack(side="right")

        # Permitir arrastar a mini HUD
        frame.bind("<Button-1>", self._mini_start_drag)
        frame.bind("<B1-Motion>", self._mini_do_drag)
        frame.bind("<Double-Button-1>", lambda e: self._restore_from_mini())

        # Começa escondida
        self.mini_hud.withdraw()
        self.mini_hud_visible = False

    def _mini_start_drag(self, event):
        """Inicia arrasto da mini HUD."""
        self._mini_drag_data["x"] = event.x
        self._mini_drag_data["y"] = event.y

    def _mini_do_drag(self, event):
        """Move a mini HUD durante arrasto."""
        x = self.mini_hud.winfo_x() + (event.x - self._mini_drag_data["x"])
        y = self.mini_hud.winfo_y() + (event.y - self._mini_drag_data["y"])
        self.mini_hud.geometry(f"+{x}+{y}")

    def _mini_toggle_module(self, module: str):
        """Toggle um módulo diretamente da Mini HUD."""
        switch_map = {
            "trainer": self.switch_trainer,
            "loot": self.switch_loot,
            "healer": self.switch_healer,
            "alarm": self.switch_alarm,
            "runemaker": self.switch_runemaker,
        }

        if module == "cavebot":
            # Cavebot usa IntVar e callback especial
            if self.switch_cavebot_var:
                new_val = 0 if self.switch_cavebot_var.get() else 1
                self.switch_cavebot_var.set(new_val)
                if self.callbacks.toggle_cavebot:
                    self.callbacks.toggle_cavebot()
        elif module in switch_map:
            switch = switch_map[module]
            if switch:
                if switch.get():
                    switch.deselect()
                else:
                    switch.select()
                # Dispara o command do switch se existir
                if module == "alarm" and hasattr(switch, 'cget'):
                    cmd = switch.cget('command')
                    if cmd:
                        cmd()

        # Atualiza visual imediatamente
        self._update_mini_hud()

    def _restore_from_mini(self):
        """Restaura janela principal e esconde mini HUD."""
        self.mini_hud.withdraw()
        self.mini_hud_visible = False
        self.app.deiconify()
        self.app.lift()
        self.app.focus_force()

    def _on_minimize(self, event=None):
        """Chamado quando a janela principal é minimizada."""
        # Salva posição da janela principal ANTES de minimizar
        try:
            self._last_main_pos = (self.app.winfo_x(), self.app.winfo_y())
        except:
            self._last_main_pos = (10, 10)

        # Verifica se realmente minimizou (estado iconic)
        if self.app.state() == 'iconic':
            # Verifica se mini_hud está habilitada nas settings
            settings = self.callbacks.get_bot_settings()
            if settings.get('mini_hud_enabled', True):
                self._show_mini_hud()

    def _show_mini_hud(self):
        """Mostra a mini HUD e atualiza seus dados."""
        if not self.mini_hud:
            return

        # Posiciona baseado na janela do Tibia (ou última posição conhecida)
        self._update_mini_hud_position()

        self.mini_hud.deiconify()
        self.mini_hud_visible = True
        self._update_mini_hud()

    def _update_mini_hud_position(self):
        """Atualiza a posição da Mini HUD para seguir a janela do Tibia."""
        try:
            # Tenta pegar hwnd do Tibia via callback
            hwnd = None
            if self.callbacks.get_tibia_hwnd:
                hwnd = self.callbacks.get_tibia_hwnd()

            if hwnd:
                try:
                    import win32gui
                    # Pega posição da janela do Tibia
                    rect = win32gui.GetWindowRect(hwnd)
                    tibia_x, tibia_y = rect[0], rect[1]

                    # Posiciona Mini HUD no canto superior esquerdo da janela do Tibia
                    new_x = tibia_x + 5
                    new_y = tibia_y + 25

                    # Atualiza posição apenas se mudou significativamente
                    current_x = self.mini_hud.winfo_x()
                    current_y = self.mini_hud.winfo_y()

                    if abs(current_x - new_x) > 5 or abs(current_y - new_y) > 5:
                        self.mini_hud.geometry(f"+{new_x}+{new_y}")
                    return
                except ImportError:
                    pass  # win32gui não disponível

            # Fallback: usa última posição da janela do bot
            if hasattr(self, '_last_main_pos'):
                x, y = self._last_main_pos
                self.mini_hud.geometry(f"+{x}+{y}")

        except Exception:
            pass  # Ignora erros silenciosamente

    def _update_mini_hud(self):
        """Atualiza os dados exibidos na mini HUD."""
        if not self.mini_hud_visible:
            return

        try:
            # Status indicator (verde = conectado, laranja = pausado)
            if self.is_paused:
                self.mini_status.configure(text="⏸", text_color="#FFA500")
            else:
                self.mini_status.configure(text="●", text_color="#00FF00")

            # XP Rate - pega do label existente
            if self.lbl_exp_rate:
                xp_text = self.lbl_exp_rate.cget("text")
                self.mini_xp_rate.configure(text=xp_text)

            # ETA
            if self.lbl_exp_eta_summary:
                eta_text = self.lbl_exp_eta_summary.cget("text")
                self.mini_eta.configure(text=eta_text)

            # Atualiza cores dos botões de módulos (verde = ativo, cinza = inativo)
            COLOR_ON = "#00AA00"
            COLOR_OFF = "#303030"

            if self.switch_trainer:
                self.mini_btn_trainer.configure(
                    fg_color=COLOR_ON if self.switch_trainer.get() else COLOR_OFF
                )
            if self.switch_loot:
                self.mini_btn_loot.configure(
                    fg_color=COLOR_ON if self.switch_loot.get() else COLOR_OFF
                )
            if self.switch_cavebot_var:
                self.mini_btn_cavebot.configure(
                    fg_color=COLOR_ON if self.switch_cavebot_var.get() else COLOR_OFF
                )
            if self.switch_healer:
                self.mini_btn_healer.configure(
                    fg_color=COLOR_ON if self.switch_healer.get() else COLOR_OFF
                )
            if self.switch_alarm:
                self.mini_btn_alarm.configure(
                    fg_color=COLOR_ON if self.switch_alarm.get() else COLOR_OFF
                )
            if self.switch_runemaker:
                self.mini_btn_runemaker.configure(
                    fg_color=COLOR_ON if self.switch_runemaker.get() else COLOR_OFF
                )

        except Exception:
            pass

        # Continua atualizando enquanto visível
        if self.mini_hud_visible:
            self.app.after(1000, self._update_mini_hud)

    def setup_mini_hud(self):
        """
        Configura a Mini HUD e os bindings de minimize.
        Chamar APÓS create() da janela principal.
        """
        self._create_mini_hud()

        # Bind para detectar minimize
        self.app.bind("<Unmap>", self._on_minimize)

        # Quando restaurar, esconder mini HUD
        def on_restore(event):
            if self.app.state() == 'normal':
                if self.mini_hud and self.mini_hud_visible:
                    self.mini_hud.withdraw()
                    self.mini_hud_visible = False

        self.app.bind("<Map>", on_restore)
