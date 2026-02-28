"""
Settings Window - Janela de configurações extraída do main.py

Este módulo contém a classe SettingsWindow que gerencia toda a
interface de configurações do bot, usando dependency injection
para receber callbacks do main.py.
"""

import customtkinter as ctk
import tkinter as tk
from tkinter import filedialog
from dataclasses import dataclass, field
from typing import Callable, Optional, Dict, Any, List


@dataclass
class SettingsCallbacks:
    """
    Todos os callbacks e state providers injetados pelo main.py.

    Este dataclass define o contrato entre main.py e SettingsWindow.
    Todos os acessos a estado global ou funções do main são feitos
    através destes callbacks.
    """

    # === STATE PROVIDERS (funções que retornam estado atual) ===
    get_bot_settings: Callable[[], Dict[str, Any]]
    get_vocation_options: Callable[[], List[str]]
    get_pm: Callable[[], Any]  # Retorna pymem instance ou None
    get_base_addr: Callable[[], int]
    get_current_waypoints: Callable[[], List[dict]]
    get_current_waypoints_filename: Callable[[], str]
    get_full_light_enabled: Callable[[], bool]
    get_log_visible: Callable[[], bool]
    get_chat_handler: Callable[[], Any]  # Retorna chat_handler instance ou None

    # === CONFIG SAVE ===
    save_config_file: Callable[[], None]

    # === TAB GERAL CALLBACKS ===
    on_light_toggle: Callable[[bool], None]
    on_lookid_toggle: Callable[[bool], None]
    on_spear_picker_toggle: Callable[[bool], None]
    on_auto_torch_toggle: Callable[[bool], None]
    on_ai_chat_toggle: Callable[[bool], None]
    on_console_log_toggle: Callable[[bool], None]
    on_logging_toggle: Callable[[bool], None]
    update_stats_visibility: Callable[[], None]

    # === TAB TRAINER CALLBACKS ===
    on_ignore_toggle: Callable[[bool], None]
    on_ks_toggle: Callable[[bool], None]
    on_chase_mode_toggle: Callable[[bool], None]
    on_combat_movement_toggle: Callable[[bool], None]

    # === TAB RUNE CALLBACKS ===
    set_rune_pos: Callable[[str], None]  # "WORK" ou "SAFE"

    # === TAB CAVEBOT CALLBACKS ===
    on_auto_explore_toggle: Callable[[bool, int, int], None]  # (enabled, search_radius, revisit_cooldown)
    load_waypoints_file: Callable[[], None]
    save_waypoints_file: Callable[[], None]
    refresh_scripts_combo: Callable[[Optional[str]], List[str]]
    record_current_pos: Callable[[], None]
    move_waypoint_up: Callable[[], None]
    move_waypoint_down: Callable[[], None]
    remove_selected_waypoint: Callable[[], None]
    clear_waypoints: Callable[[], None]
    update_waypoint_display: Callable[[], None]
    open_waypoint_editor: Callable[[], None]

    # === LOGGING ===
    log: Callable[[str], None]

    # === FEATURE FLAGS ===
    use_configurable_loot: bool = False
    use_auto_container_detection: bool = False


class SettingsWindow:
    """
    Janela de configurações do bot.

    Extraída do main.py para separação de concerns.
    Recebe todos os callbacks via SettingsCallbacks dataclass.
    """

    def __init__(self, parent: ctk.CTk, callbacks: SettingsCallbacks):
        self.parent = parent
        self.cb = callbacks
        self.window: Optional[ctk.CTkToplevel] = None

        # === Variáveis de toggle (expostas para main.py) ===
        self._auto_explore_var: Optional[ctk.IntVar] = None
        self._afk_pause_var: Optional[ctk.IntVar] = None

        # === Widget references que main.py precisa acessar ===
        self.waypoint_listbox: Optional[tk.Listbox] = None
        self.lbl_wp_header: Optional[ctk.CTkLabel] = None
        self.entry_waypoint_name: Optional[ctk.CTkEntry] = None
        self.combo_cavebot_scripts: Optional[ctk.CTkComboBox] = None
        self.label_cavebot_status: Optional[ctk.CTkLabel] = None
        self.lbl_work_pos: Optional[ctk.CTkLabel] = None
        self.lbl_safe_pos: Optional[ctk.CTkLabel] = None

        # === Lazy Tab Building (performance) ===
        self._tabs: Dict[str, ctk.CTkFrame] = {}  # nome -> frame da tab
        self._tabs_built: set = set()  # tabs já construídas
        self._tabview: Optional[ctk.CTkTabview] = None
        self._tab_display_to_key: Dict[str, str] = {}  # display_name -> key

        # === Estilos UI (CSS-like) ===
        self.UI = {
            'H1': {
                'font': ("Verdana", 11, "bold"),
                'text_color': "#FFFFFF"
            },
            'BODY': {
                'font': ("Verdana", 10),
                'text_color': "#CCCCCC"
            },
            'HINT': {
                'font': ("Verdana", 8),
                'text_color': "#555555"
            },
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
            'PAD_SECTION': (6, 3),
            'PAD_ITEM': 1,
            'PAD_INDENT': 15,
        }

    def open(self) -> bool:
        """
        Abre a janela de settings.

        Returns:
            True se abriu nova janela, False se já estava aberta
        """
        if self.window is not None and self.window.winfo_exists():
            self.window.lift()
            self.window.focus()
            return False

        self._create_window()
        return True

    def close(self) -> None:
        """Fecha a janela de settings se estiver aberta."""
        if self.window is not None and self.window.winfo_exists():
            self.window.destroy()
        self.window = None

    def is_open(self) -> bool:
        """Verifica se a janela está aberta."""
        return self.window is not None and self.window.winfo_exists()

    # === MÉTODOS DE ATUALIZAÇÃO (chamados por main.py) ===

    def update_waypoint_display_ui(self, waypoints: List[dict]) -> None:
        """Atualiza a listbox de waypoints com nova lista."""
        if self.waypoint_listbox is None:
            return
        try:
            if not self.waypoint_listbox.winfo_exists():
                return
        except:
            return

        # Salva seleção atual
        current_selection = self.waypoint_listbox.curselection()
        saved_idx = current_selection[0] if current_selection else None

        # Limpa e repopula
        self.waypoint_listbox.delete(0, tk.END)

        for idx, wp in enumerate(waypoints):
            act = wp.get('action', 'WALK').upper()
            line = f"{idx+1}. [{act}] {wp['x']}, {wp['y']}, {wp['z']}"
            self.waypoint_listbox.insert(tk.END, line)

        # Atualiza header
        if self.lbl_wp_header is not None:
            try:
                if self.lbl_wp_header.winfo_exists():
                    self.lbl_wp_header.configure(text=f"Waypoints ({len(waypoints)})")
            except:
                pass

        # Restaura seleção
        if saved_idx is not None and saved_idx < len(waypoints):
            self.waypoint_listbox.selection_set(saved_idx)

    def update_rune_pos_labels_ui(self) -> None:
        """Atualiza os labels de posição do runemaker."""
        settings = self.cb.get_bot_settings()
        if self.lbl_work_pos and self.lbl_work_pos.winfo_exists():
            self.lbl_work_pos.configure(text=str(settings.get('rune_work_pos', (0, 0, 0))))
        if self.lbl_safe_pos and self.lbl_safe_pos.winfo_exists():
            self.lbl_safe_pos.configure(text=str(settings.get('rune_safe_pos', (0, 0, 0))))

    def set_waypoint_name_field(self, name: str) -> None:
        """Define o nome no campo de arquivo de waypoints."""
        if self.entry_waypoint_name and self.entry_waypoint_name.winfo_exists():
            self.entry_waypoint_name.delete(0, "end")
            if name:
                self.entry_waypoint_name.insert(0, name)

    def get_selected_waypoint_index(self) -> Optional[int]:
        """Retorna o índice do waypoint selecionado ou None."""
        if self.waypoint_listbox is None:
            return None
        selection = self.waypoint_listbox.curselection()
        return selection[0] if selection else None

    def refresh_scripts_combo_ui(self, scripts: List[str], selected: Optional[str] = None) -> None:
        """Atualiza a combo de scripts com nova lista."""
        if self.combo_cavebot_scripts is None or not self.combo_cavebot_scripts.winfo_exists():
            return
        self.combo_cavebot_scripts.configure(values=scripts)
        if selected and selected in scripts:
            self.combo_cavebot_scripts.set(selected)
        elif scripts:
            self.combo_cavebot_scripts.set(scripts[0])
        else:
            self.combo_cavebot_scripts.set("")

    # === CRIAÇÃO DA JANELA ===

    def _create_window(self) -> None:
        """Cria a janela principal com lazy tab building para performance."""
        self.window = ctk.CTkToplevel(self.parent)
        self.window.title("Configurações")
        self._min_width = 450
        self._min_height = 400
        self.window.geometry(f"{self._min_width}x{self._min_height}")
        self.window.attributes("-topmost", True)

        self.window.protocol("WM_DELETE_WINDOW", self._on_close)

        tabview = ctk.CTkTabview(self.window)
        tabview.pack(fill="both", expand=True, padx=10, pady=10)
        self._tabview = tabview

        # Cria tabs vazias (lazy loading - conteúdo construído sob demanda)
        self._tabs = {}
        self._tabs_built = set()
        # Tuplas: (nome_exibido, chave_interna)
        tab_defs = [
            ("Geral", "Geral"),
            ("Trainer", "Trainer"),
            ("Alarme", "Alarme"),
            ("Alvos", "Alvos"),
            ("Loot", "Loot"),
            ("Fisher", "Fisher"),
            ("Rune", "Rune"),
            ("Healer", "Healer"),
            ("Cavebot", "Cavebot"),
        ]
        self._tab_display_to_key = {}
        for display_name, key in tab_defs:
            self._tabs[key] = tabview.add(display_name)
            self._tab_display_to_key[display_name] = key

        # Constrói apenas a primeira tab (Geral) imediatamente
        self._build_tab("Geral")

        # Lazy build: constrói outras tabs quando selecionadas
        tabview.configure(command=self._on_tab_change)
        self.window.after(100, lambda: self._adjust_window_height(tabview))

    def _on_tab_change(self) -> None:
        """Callback quando usuário muda de tab - faz lazy build se necessário."""
        if not self._tabview:
            return
        display_name = self._tabview.get()
        # Converte nome exibido para chave interna
        tab_key = self._tab_display_to_key.get(display_name, display_name)
        if tab_key not in self._tabs_built:
            self._build_tab(tab_key)
        self._adjust_window_height(self._tabview)

    def _build_tab(self, name: str) -> None:
        """Constrói o conteúdo de uma tab específica (lazy loading)."""
        if name in self._tabs_built:
            return

        tab_frame = self._tabs.get(name)
        if not tab_frame:
            return

        builders = {
            "Geral": self._build_tab_geral,
            "Trainer": self._build_tab_trainer,
            "Alarme": self._build_tab_alarm,
            "Alvos": self._build_tab_alvos,
            "Loot": self._build_tab_loot,
            "Fisher": self._build_tab_fisher,
            "Rune": self._build_tab_rune,
            "Healer": self._build_tab_healer,
            "Cavebot": self._build_tab_cavebot,
        }

        builder = builders.get(name)
        if builder:
            builder(tab_frame)
            self._tabs_built.add(name)

    def _on_close(self) -> None:
        """Handler de fechamento da janela."""
        if self.window:
            self.window.destroy()
        self.window = None
        # Limpar estado de lazy building para próxima abertura
        self._tabs = {}
        self._tabs_built = set()
        self._tabview = None
        self._tab_display_to_key = {}

    def _adjust_window_height(self, tabview) -> None:
        """Ajusta a altura da janela para caber o conteúdo da aba ativa, sem diminuir abaixo do mínimo."""
        if not self.window or not self.window.winfo_exists():
            return
        try:
            tab_name = tabview.get()
            tab_frame = tabview.tab(tab_name)
            self.window.update_idletasks()
            content_h = tab_frame.winfo_reqheight()
            # Overhead: tab buttons (~40px) + tabview padding (~40px) + window padding (~20px)
            overhead = 100
            needed = content_h + overhead
            new_height = max(self._min_height, needed)
            self.window.geometry(f"{self._min_width}x{new_height}")
        except Exception:
            pass

    def _create_grid_frame(self, parent) -> ctk.CTkFrame:
        """Helper para criar frames de grid (Label Esq | Input Dir)."""
        f = ctk.CTkFrame(parent, fg_color="transparent")
        f.pack(pady=self.UI['PAD_SECTION'][0], fill="x")
        f.grid_columnconfigure(0, weight=1)
        f.grid_columnconfigure(1, weight=2)
        return f

    def _create_switch_grid(self, parent, switches: list, cols: int = 2, settings: dict = None) -> dict:
        """
        Cria grid de switches compacto.

        Args:
            parent: Frame pai
            switches: Lista de tuplas (text, setting_key, color)
            cols: Numero de colunas (default 2)
            settings: Dict de settings para pre-selecionar switches

        Returns:
            dict de {setting_key: switch_widget}
        """
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        frame.pack(fill="x", padx=10, pady=3)

        for i in range(cols):
            frame.grid_columnconfigure(i, weight=1)

        widgets = {}
        for idx, (text, key, color) in enumerate(switches):
            row, col = divmod(idx, cols)
            sw = ctk.CTkSwitch(frame, text=text, progress_color=color, **self.UI['BODY'])
            sw.grid(row=row, column=col, sticky="w", pady=1, padx=2)
            if settings and settings.get(key, False):
                sw.select()
            widgets[key] = sw

        return widgets

    # === TAB BUILDERS ===

    def _build_tab_geral(self, tab: ctk.CTkFrame) -> None:
        """Constrói a aba Geral."""
        settings = self.cb.get_bot_settings()

        frame_geral = self._create_grid_frame(tab)

        # Vocação
        ctk.CTkLabel(frame_geral, text="Vocação (Regen):", **self.UI['BODY']).grid(
            row=0, column=0, sticky="e", padx=10, pady=self.UI['PAD_ITEM'])
        combo_voc = ctk.CTkComboBox(frame_geral, values=self.cb.get_vocation_options(), **self.UI['COMBO'])
        combo_voc.grid(row=0, column=1, sticky="w")
        combo_voc.set(settings['vocation'])

        # Telegram
        ctk.CTkLabel(frame_geral, text="Telegram Chat ID:", **self.UI['BODY']).grid(
            row=1, column=0, sticky="e", padx=10, pady=self.UI['PAD_ITEM'])
        entry_telegram = ctk.CTkEntry(frame_geral, width=150, height=24, font=self.UI['BODY']['font'])
        entry_telegram.grid(row=1, column=1, sticky="w")
        entry_telegram.insert(0, str(settings['telegram_chat_id']))

        ctk.CTkLabel(frame_geral, text="↳ Recebe alertas de PK e Pausa no celular.", **self.UI['HINT']).grid(
            row=2, column=0, columnspan=2, sticky="e", padx=60, pady=(0, 5))

        # Pasta do Cliente
        ctk.CTkLabel(frame_geral, text="Pasta do Cliente:", **self.UI['BODY']).grid(
            row=3, column=0, sticky="e", padx=10, pady=self.UI['PAD_ITEM'])

        frame_client_path = ctk.CTkFrame(frame_geral, fg_color="transparent")
        frame_client_path.grid(row=3, column=1, sticky="w")

        entry_client_path = ctk.CTkEntry(frame_client_path, width=180, height=24,
                                         font=self.UI['BODY']['font'], state="disabled")
        entry_client_path.pack(side="left")

        def select_client_folder():
            folder = filedialog.askdirectory(title="Selecione a pasta do cliente Tibia")
            if folder:
                entry_client_path.configure(state="normal")
                entry_client_path.delete(0, "end")
                entry_client_path.insert(0, folder)
                entry_client_path.configure(state="disabled")

        ctk.CTkButton(frame_client_path, text="...", width=30, height=24,
                     command=select_client_folder).pack(side="left", padx=5)

        if settings.get('client_path'):
            entry_client_path.configure(state="normal")
            entry_client_path.insert(0, settings['client_path'])
            entry_client_path.configure(state="disabled")

        # === OPÇÕES (Grid 2x2) ===
        ctk.CTkLabel(tab, text="Opções", **self.UI['H1']).pack(anchor="w", padx=10, pady=(5, 2))

        f_opts_grid = ctk.CTkFrame(tab, fg_color="transparent")
        f_opts_grid.pack(fill="x", padx=10, pady=2)
        f_opts_grid.grid_columnconfigure(0, weight=1)
        f_opts_grid.grid_columnconfigure(1, weight=1)

        switch_lookid = ctk.CTkSwitch(f_opts_grid, text="Exibir ID Look",
                                      command=lambda: self.cb.on_lookid_toggle(bool(switch_lookid.get())),
                                      progress_color="#3B8ED0", **self.UI['BODY'])
        switch_lookid.grid(row=0, column=0, sticky="w", pady=1)
        if settings.get('lookid_enabled', False):
            switch_lookid.select()

        switch_ai_chat = ctk.CTkSwitch(f_opts_grid, text="Responder IA",
                                       command=lambda: self.cb.on_ai_chat_toggle(bool(switch_ai_chat.get())),
                                       progress_color="#9B59B6", **self.UI['BODY'])
        switch_ai_chat.grid(row=0, column=1, sticky="w", pady=1)
        if settings.get('ai_chat_enabled', False):
            switch_ai_chat.select()

        switch_console_log = ctk.CTkSwitch(f_opts_grid, text="Console Log",
                                           command=lambda: self.cb.on_console_log_toggle(bool(switch_console_log.get())),
                                           progress_color="#3498DB", **self.UI['BODY'])
        switch_console_log.grid(row=1, column=0, sticky="w", pady=1)
        if settings.get('console_log_visible', True):
            switch_console_log.select()

        switch_logging = ctk.CTkSwitch(f_opts_grid, text="Logging",
                                       command=lambda: self.cb.on_logging_toggle(bool(switch_logging.get())),
                                       progress_color="#E74C3C", **self.UI['BODY'])
        switch_logging.grid(row=1, column=1, sticky="w", pady=1)
        if settings.get('logging_enabled', False):
            switch_logging.select()

        ctk.CTkLabel(tab, text="↳ Logging: desabilitar melhora performance. Crash logs sempre ativos.",
                    **self.UI['HINT']).pack(anchor="w", padx=15)

        # === PAUSAS AFK (compacto) ===
        ctk.CTkLabel(tab, text="Pausas AFK", **self.UI['H1']).pack(anchor="w", padx=10, pady=(8, 2))

        f_afk = ctk.CTkFrame(tab, fg_color="transparent")
        f_afk.pack(fill="x", padx=10, pady=2)

        switch_afk_pause = ctk.CTkSwitch(f_afk, text="Ativar",
                                          progress_color="#9B59B6", **self.UI['BODY'])
        switch_afk_pause.pack(side="left", padx=(5, 10))
        if settings.get('afk_pause_enabled', False):
            switch_afk_pause.select()

        ctk.CTkLabel(f_afk, text="Int:", **self.UI['BODY']).pack(side="left")
        entry_afk_interval = ctk.CTkEntry(f_afk, width=40, height=24, font=self.UI['BODY']['font'], justify="center")
        entry_afk_interval.pack(side="left", padx=2)
        entry_afk_interval.insert(0, str(settings.get('afk_pause_interval', 10)))
        ctk.CTkLabel(f_afk, text="min", **self.UI['BODY']).pack(side="left", padx=(0, 8))

        ctk.CTkLabel(f_afk, text="Dur:", **self.UI['BODY']).pack(side="left")
        entry_afk_duration = ctk.CTkEntry(f_afk, width=40, height=24, font=self.UI['BODY']['font'], justify="center")
        entry_afk_duration.pack(side="left", padx=2)
        entry_afk_duration.insert(0, str(settings.get('afk_pause_duration', 30)))
        ctk.CTkLabel(f_afk, text="seg", **self.UI['BODY']).pack(side="left")

        ctk.CTkLabel(tab, text="↳ Pausa todos os módulos (exceto Alarme) com 50% variância.",
                    **self.UI['HINT']).pack(anchor="w", padx=15)

        # Botão Salvar
        def save_geral():
            s = self.cb.get_bot_settings()
            s['vocation'] = combo_voc.get()
            s['telegram_chat_id'] = entry_telegram.get()
            entry_client_path.configure(state="normal")
            s['client_path'] = entry_client_path.get()
            entry_client_path.configure(state="disabled")
            s['ai_chat_enabled'] = bool(switch_ai_chat.get())
            s['console_log_visible'] = bool(switch_console_log.get())
            s['logging_enabled'] = bool(switch_logging.get())
            # AFK Pauses
            s['afk_pause_enabled'] = bool(switch_afk_pause.get())
            try:
                s['afk_pause_interval'] = max(1, int(entry_afk_interval.get()))
            except:
                pass
            try:
                s['afk_pause_duration'] = max(5, int(entry_afk_duration.get()))
            except:
                pass
            self.cb.update_stats_visibility()
            self.cb.save_config_file()
            self.cb.log("⚙️ Geral salvo.")

        ctk.CTkButton(tab, text="Salvar Geral", command=save_geral,
                     fg_color="#2CC985", height=32).pack(side="bottom", pady=10, fill="x", padx=20)

    def _build_tab_trainer(self, tab: ctk.CTkFrame) -> None:
        """Constrói a aba Trainer."""
        settings = self.cb.get_bot_settings()

        frame_tr = ctk.CTkFrame(tab, fg_color="transparent")
        frame_tr.pack(fill="x", pady=self.UI['PAD_SECTION'][0])

        # Delay
        ctk.CTkLabel(frame_tr, text="Delay de Ataque (s):", **self.UI['H1']).pack(anchor="w", padx=10)

        f_dely = ctk.CTkFrame(frame_tr, fg_color="transparent")
        f_dely.pack(fill="x", padx=10, pady=self.UI['PAD_ITEM'])

        ctk.CTkLabel(f_dely, text="Min:", **self.UI['BODY']).pack(side="left")
        entry_tr_min = ctk.CTkEntry(f_dely, **self.UI['INPUT'])
        entry_tr_min.pack(side="left", padx=5)
        entry_tr_min.insert(0, str(settings.get('trainer_min_delay', 1.0)))

        ctk.CTkLabel(f_dely, text="Max:", **self.UI['BODY']).pack(side="left", padx=(10, 0))
        entry_tr_max = ctk.CTkEntry(f_dely, **self.UI['INPUT'])
        entry_tr_max.pack(side="left", padx=5)
        entry_tr_max.insert(0, str(settings.get('trainer_max_delay', 2.0)))

        # Switch em linha própria (abaixo do Min/Max)
        switch_pause_modules = ctk.CTkSwitch(
            frame_tr,
            text="Treino: Pausar módulos durante delay (pausa AFK)",
            progress_color="#9B59B6",
            **self.UI['BODY']
        )
        switch_pause_modules.pack(anchor="w", padx=10, pady=(3, 0))
        if settings.get('pause_modules_during_delay', False):
            switch_pause_modules.select()

        # Range
        ctk.CTkLabel(frame_tr, text="Distância (SQM):", **self.UI['H1']).pack(anchor="w", padx=10, pady=(15, 0))

        f_rng = ctk.CTkFrame(frame_tr, fg_color="transparent")
        f_rng.pack(fill="x", padx=10, pady=self.UI['PAD_ITEM'])

        entry_tr_range = ctk.CTkEntry(f_rng, **self.UI['INPUT'])
        entry_tr_range.pack(side="left")
        entry_tr_range.insert(0, str(settings.get('trainer_range', 1)))

        ctk.CTkLabel(f_rng, text="(Distancia mínima para começar a atacar alvos)",
                    **self.UI['HINT']).pack(side="left", padx=10)

        # Lógica de Alvo (linha horizontal)
        ctk.CTkLabel(frame_tr, text="Lógica de Alvo:", **self.UI['H1']).pack(anchor="w", padx=10, pady=(10, 0))

        f_logic = ctk.CTkFrame(tab, fg_color="transparent")
        f_logic.pack(fill="x", padx=10, pady=3)

        switch_ignore = ctk.CTkSwitch(f_logic, text="Ignorar 1º",
                                      command=lambda: self.cb.on_ignore_toggle(bool(switch_ignore.get())),
                                      progress_color="#FFA500", **self.UI['BODY'])
        switch_ignore.pack(side="left", padx=(5, 10))
        if settings.get('ignore_first', False):
            switch_ignore.select()

        switch_ks = ctk.CTkSwitch(f_logic, text="Anti KS",
                                  command=lambda: self.cb.on_ks_toggle(bool(switch_ks.get())),
                                  progress_color="#FF6B6B", **self.UI['BODY'])
        switch_ks.pack(side="left", padx=(0, 10))
        if settings.get('ks_prevention_enabled', True):
            switch_ks.select()

        switch_chase = ctk.CTkSwitch(f_logic, text="A* Chase Mode",
                                      command=lambda: self.cb.on_chase_mode_toggle(bool(switch_chase.get())),
                                      progress_color="#3498DB", **self.UI['BODY'])
        switch_chase.pack(side="left")
        if settings.get('chase_mode_enabled', False):
            switch_chase.select()

        ctk.CTkLabel(tab, text="↳ Anti KS: evita criaturas perto de players. Chase: A* pathfinding.",
                    **self.UI['HINT']).pack(anchor="w", padx=15)

        # === COMBAT MOVEMENT (EXPERIMENTAL) ===
        ctk.CTkLabel(tab, text="Combat Movement (Experimental):", **self.UI['H1']).pack(anchor="w", padx=10, pady=(15, 0))

        switch_combat_movement = ctk.CTkSwitch(
            tab,
            text="Movimentação humanizada em combate",
            command=lambda: self.cb.on_combat_movement_toggle(bool(switch_combat_movement.get())),
            progress_color="#E67E22",  # Laranja para indicar experimental
            **self.UI['BODY']
        )
        switch_combat_movement.pack(anchor="w", padx=10, pady=(3, 0))
        if settings.get('combat_movement_enabled', False):
            switch_combat_movement.select()

        ctk.CTkLabel(tab, text="↳ Move na direção do waypoint durante combate, mantendo adjacência ao alvo.",
                    **self.UI['HINT']).pack(anchor="w", padx=15)

        # === AIMBOT ===
        ctk.CTkLabel(tab, text="Aimbot (Runas):", **self.UI['H1']).pack(anchor="w", padx=10, pady=(15, 0))

        frame_aimbot = ctk.CTkFrame(tab, fg_color="transparent")
        frame_aimbot.pack(fill="x", padx=10, pady=5)

        switch_aimbot = ctk.CTkSwitch(frame_aimbot, text="Ativar Aimbot",
                                      command=lambda: None,
                                      progress_color="#E74C3C", **self.UI['BODY'])
        switch_aimbot.pack(anchor="w")
        if settings.get('aimbot_enabled', False):
            switch_aimbot.select()

        # Aimbot Rune + Hotkey
        f_aimbot_opts = ctk.CTkFrame(tab, fg_color="transparent")
        f_aimbot_opts.pack(fill="x", padx=20, pady=5)

        ctk.CTkLabel(f_aimbot_opts, text="Runa:", **self.UI['BODY']).pack(side="left")
        combo_aimbot_rune = ctk.CTkComboBox(f_aimbot_opts, values=["SD", "HMM", "GFB", "EXPLO"],
                                            width=70, **self.UI['BODY'])
        combo_aimbot_rune.pack(side="left", padx=5)
        combo_aimbot_rune.set(settings.get('aimbot_rune_type', 'SD'))

        ctk.CTkLabel(f_aimbot_opts, text="Hotkey:", **self.UI['BODY']).pack(side="left", padx=(15, 0))
        combo_aimbot_hotkey = ctk.CTkComboBox(f_aimbot_opts,
                                              values=["F5", "F6", "F7", "F8", "F9", "F10", "F11", "F12", "MOUSE4", "MOUSE5"],
                                              width=90, **self.UI['BODY'])
        combo_aimbot_hotkey.pack(side="left", padx=5)
        combo_aimbot_hotkey.set(settings.get('aimbot_hotkey', 'F5'))

        # Botão Salvar
        def save_trainer():
            try:
                s = self.cb.get_bot_settings()
                s['trainer_min_delay'] = float(entry_tr_min.get().replace(',', '.'))
                s['trainer_max_delay'] = float(entry_tr_max.get().replace(',', '.'))
                s['trainer_range'] = int(entry_tr_range.get())
                # Pause modules during delay
                s['pause_modules_during_delay'] = bool(switch_pause_modules.get())
                # Aimbot settings
                s['aimbot_enabled'] = bool(switch_aimbot.get())
                s['aimbot_rune_type'] = combo_aimbot_rune.get()
                s['aimbot_hotkey'] = combo_aimbot_hotkey.get()
                # Combat Movement settings
                s['combat_movement_enabled'] = bool(switch_combat_movement.get())
                self.cb.save_config_file()
                self.cb.log("⚔️ Trainer salvo!")
                # DEBUG: Confirma que o valor foi gravado no dict correto
                print(f"[DEBUG SAVE] trainer_range={s['trainer_range']} | id(dict)={id(s)}")
            except Exception as e:
                self.cb.log("❌ Erro nos valores.")
                print(f"[DEBUG SAVE] EXCEPTION: {e}")

        ctk.CTkButton(tab, text="Salvar Trainer", command=save_trainer,
                     fg_color="#2CC985", height=32).pack(side="bottom", pady=10, fill="x", padx=20)

    def _build_tab_alarm(self, tab: ctk.CTkFrame) -> None:
        """Constrói a aba Alarme (layout compacto)."""
        settings = self.cb.get_bot_settings()

        # === DETECÇÃO VISUAL ===
        ctk.CTkLabel(tab, text="Detecção Visual", **self.UI['H1']).pack(anchor="w", padx=10, pady=(5, 3))

        # Linha 1: Players + Creatures lado a lado
        f_detection = ctk.CTkFrame(tab, fg_color="transparent")
        f_detection.pack(fill="x", padx=10, pady=2)

        switch_alarm_players = ctk.CTkSwitch(f_detection, text="Alarme para Players",
                                             progress_color="#FF5555", **self.UI['BODY'])
        switch_alarm_players.pack(side="left", padx=(5, 15))
        if settings.get('alarm_players', True):
            switch_alarm_players.select()

        switch_alarm_creatures = ctk.CTkSwitch(f_detection, text="Alarme para Criaturas",
                                               progress_color="#FFA500", **self.UI['BODY'])
        switch_alarm_creatures.pack(side="left", padx=(0, 15))
        if settings.get('alarm_creatures', True):
            switch_alarm_creatures.select()

        # Linha 2: Distância + Andares na mesma linha
        f_options = ctk.CTkFrame(tab, fg_color="transparent")
        f_options.pack(fill="x", padx=10, pady=2)

        ctk.CTkLabel(f_options, text="Distância (SQM):", **self.UI['BODY']).pack(side="left", padx=(5, 2))
        dist_vals = ["1", "3", "5", "8", "Tela"]
        combo_alarm = ctk.CTkComboBox(f_options, values=dist_vals, width=60, height=24,
                                      font=self.UI['BODY']['font'], state="readonly")
        combo_alarm.pack(side="left", padx=(0, 10))
        alarm_range = settings['alarm_range']
        combo_alarm.set("Tela" if alarm_range >= 15 else str(alarm_range) if alarm_range in [1, 3, 5, 8] else "8")

        ctk.CTkLabel(f_options, text="Monitorar Andar:", **self.UI['BODY']).pack(side="left", padx=(0, 2))
        combo_floor = ctk.CTkComboBox(f_options, values=["Padrão", "+1", "-1", "Raio-X"],
                                      width=70, height=24, font=self.UI['BODY']['font'], state="readonly")
        combo_floor.pack(side="left")
        floor_map = {"Padrão": "Padrão", "Superior (+1)": "+1", "Inferior (-1)": "-1", "Todos (Raio-X)": "Raio-X"}
        floor_rev = {v: k for k, v in floor_map.items()}
        combo_floor.set(floor_map.get(settings['alarm_floor'], "Padrão"))

        # === ALARMES ===
        ctk.CTkLabel(tab, text="Alarmes", **self.UI['H1']).pack(anchor="w", padx=10, pady=(8, 3))

        # Linha HP: switch + entry inline
        f_hp = ctk.CTkFrame(tab, fg_color="transparent")
        f_hp.pack(fill="x", padx=10, pady=2)

        switch_hp_alarm = ctk.CTkSwitch(f_hp, text="Alarme HP Baixo", progress_color="#FF5555", **self.UI['BODY'])
        switch_hp_alarm.pack(side="left", padx=(5, 5))
        if settings.get('alarm_hp_enabled', False):
            switch_hp_alarm.select()

        ctk.CTkLabel(f_hp, text="dispara se <", **self.UI['BODY']).pack(side="left")
        entry_hp_pct = ctk.CTkEntry(f_hp, width=40, height=24, font=self.UI['BODY']['font'], justify="center")
        entry_hp_pct.pack(side="left", padx=3)
        entry_hp_pct.insert(0, str(settings.get('alarm_hp_percent', 50)))
        ctk.CTkLabel(f_hp, text="%", **self.UI['BODY']).pack(side="left")

        # Switches individuais em linhas separadas
        f_mana = ctk.CTkFrame(tab, fg_color="transparent")
        f_mana.pack(fill="x", padx=10, pady=2)
        switch_mana_gm = ctk.CTkSwitch(f_mana, text="Detectar mana artificial (GM)",
                                       progress_color="#AA55FF", **self.UI['BODY'])
        switch_mana_gm.pack(side="left", padx=5)
        if settings.get('alarm_mana_gm_enabled', False):
            switch_mana_gm.select()

        f_chat = ctk.CTkFrame(tab, fg_color="transparent")
        f_chat.pack(fill="x", padx=10, pady=2)
        switch_chat = ctk.CTkSwitch(f_chat, text="Alarme de Msg Nova",
                                    progress_color="#FFA500", **self.UI['BODY'])
        switch_chat.pack(side="left", padx=5)
        if settings.get('alarm_chat_enabled', False):
            switch_chat.select()

        f_stuck = ctk.CTkFrame(tab, fg_color="transparent")
        f_stuck.pack(fill="x", padx=10, pady=2)
        switch_stuck_detection = ctk.CTkSwitch(f_stuck, text="Alarme Cavebot Parado (3s+)",
                                               progress_color="#FFA500", **self.UI['BODY'])
        switch_stuck_detection.pack(side="left", padx=5)
        if settings.get('alarm_stuck_detection_enabled', False):
            switch_stuck_detection.select()

        # Movimento + Manter Posição agrupados (relacionados)
        f_movimento = ctk.CTkFrame(tab, fg_color="transparent")
        f_movimento.pack(fill="x", padx=10, pady=2)

        switch_movement = ctk.CTkSwitch(f_movimento, text="Alarme de Movimento",
                                        progress_color="#FF5555", **self.UI['BODY'])
        switch_movement.pack(side="left", padx=5)
        if settings.get('alarm_movement_enabled', False):
            switch_movement.select()

        ctk.CTkLabel(f_movimento, text="→", **self.UI['BODY']).pack(side="left", padx=3)

        switch_keep_pos = ctk.CTkSwitch(f_movimento, text="Manter Posição",
                                        progress_color="#FFA500", **self.UI['BODY'])
        switch_keep_pos.pack(side="left")
        if settings.get('alarm_keep_position', False):
            switch_keep_pos.select()

        ctk.CTkLabel(f_movimento, text="(retorna ao ponto)",
                    **self.UI['HINT']).pack(side="left", padx=5)

        # Botão Salvar
        def save_alarm():
            try:
                s = self.cb.get_bot_settings()
                raw_range = combo_alarm.get()
                s['alarm_range'] = 15 if raw_range == "Tela" else int(raw_range)
                s['alarm_floor'] = floor_rev.get(combo_floor.get(), "Padrão")
                s['alarm_hp_enabled'] = bool(switch_hp_alarm.get())
                s['alarm_hp_percent'] = int(entry_hp_pct.get())
                s['alarm_players'] = bool(switch_alarm_players.get())
                s['alarm_creatures'] = bool(switch_alarm_creatures.get())
                s['alarm_chat_enabled'] = bool(switch_chat.get())
                s['alarm_movement_enabled'] = bool(switch_movement.get())
                s['alarm_keep_position'] = bool(switch_keep_pos.get())
                s['alarm_mana_gm_enabled'] = bool(switch_mana_gm.get())
                s['alarm_stuck_detection_enabled'] = bool(switch_stuck_detection.get())
                self.cb.save_config_file()
                self.cb.log("🔔 Alarme salvo.")
            except:
                self.cb.log("❌ Erro nos valores.")

        ctk.CTkButton(tab, text="Salvar Alarme", command=save_alarm,
                     fg_color="#2CC985", height=32).pack(side="bottom", pady=10, fill="x", padx=20)

    def _build_tab_alvos(self, tab: ctk.CTkFrame) -> None:
        """Constrói a aba Alvos."""
        settings = self.cb.get_bot_settings()

        ctk.CTkLabel(tab, text="Alvos (Target List):", **self.UI['H1']).pack(pady=(5, 0))
        txt_targets = ctk.CTkTextbox(tab, height=100, font=("Consolas", 10))
        txt_targets.pack(fill="x", padx=5, pady=5)
        txt_targets.insert("0.0", "\n".join(settings['targets']))

        ctk.CTkLabel(tab, text="Safe List (Não irá disparar o alarme):", **self.UI['H1']).pack(pady=(5, 0))
        txt_safe = ctk.CTkTextbox(tab, height=140, font=("Consolas", 10))
        txt_safe.pack(fill="x", padx=5, pady=5)
        txt_safe.insert("0.0", "\n".join(settings['safe']))

        def save_lists():
            s = self.cb.get_bot_settings()
            s['targets'][:] = [line.strip() for line in txt_targets.get("0.0", "end").split('\n') if line.strip()]
            s['safe'][:] = [line.strip() for line in txt_safe.get("0.0", "end").split('\n') if line.strip()]
            self.cb.save_config_file()
            self.cb.log("🎯 Listas salvas.")

        ctk.CTkButton(tab, text="Salvar Listas", command=save_lists,
                     fg_color="#2CC985", height=32).pack(side="bottom", pady=10, fill="x", padx=20)

    def _build_tab_loot(self, tab: ctk.CTkFrame) -> None:
        """Constrói a aba Loot."""
        settings = self.cb.get_bot_settings()

        ctk.CTkLabel(tab, text="Configuração de BPs:", **self.UI['H1']).pack(pady=(5, 2))

        entry_cont_count = None
        if not self.cb.use_auto_container_detection:
            ctk.CTkLabel(tab, text="Minhas BPs (Não lootear):", **self.UI['BODY']).pack()
            entry_cont_count = ctk.CTkEntry(tab, **self.UI['INPUT'])
            entry_cont_count.pack(pady=1)
            entry_cont_count.insert(0, str(settings['loot_containers']))

        # Frame Índice Destino
        frame_dest = ctk.CTkFrame(tab, fg_color="transparent")
        frame_dest.pack(fill="x", padx=10, pady=(5, 2))

        ctk.CTkLabel(frame_dest, text="Índice Destino:", **self.UI['BODY']).pack(side="left", padx=(0, 5))
        entry_style = {**self.UI['INPUT'], 'width': 60}
        entry_dest_idx = ctk.CTkEntry(frame_dest, **entry_style)
        entry_dest_idx.pack(side="left")
        entry_dest_idx.insert(0, str(settings['loot_dest']))
        ctk.CTkLabel(frame_dest, text="(0=primeira BP, 1=segunda, etc)",
                    **self.UI['HINT']).pack(side="left", padx=(5, 0))

        # Options (lado a lado)
        frame_loot_opts = ctk.CTkFrame(tab, fg_color="transparent")
        frame_loot_opts.pack(fill="x", padx=10, pady=3)

        switch_drop_food = ctk.CTkSwitch(frame_loot_opts, text="Dropar food no chão se full",
                                         progress_color="#FFA500", **self.UI['BODY'])
        switch_drop_food.pack(side="left", padx=(5, 15))
        if settings.get('loot_drop_food', False):
            switch_drop_food.select()

        switch_auto_eat = ctk.CTkSwitch(frame_loot_opts, text="Auto comer food",
                                         progress_color="#32CD32", **self.UI['BODY'])
        switch_auto_eat.pack(side="left")
        if settings.get('loot_auto_eat', True):
            switch_auto_eat.select()

        # Sistema configurável de loot
        txt_loot_names = None
        txt_drop_names = None

        if self.cb.use_configurable_loot:
            ctk.CTkLabel(tab, text="Items para Lotar:", **self.UI['H1']).pack(pady=(8, 0))
            ctk.CTkLabel(tab, text="↳ Um item por linha. Ex: 'gold coins', 'plate armor'",
                        **self.UI['HINT']).pack(pady=(0, 2))

            txt_loot_names = ctk.CTkTextbox(tab, height=70, font=("Consolas", 10))
            txt_loot_names.pack(fill="x", padx=10, pady=2)
            txt_loot_names.insert("0.0", "\n".join(settings.get('loot_names', [])))

            ctk.CTkLabel(tab, text="Items para Dropar no chão:", **self.UI['H1']).pack(pady=(5, 0))
            ctk.CTkLabel(tab, text="↳ Um item por linha. Ex: 'a mace', 'leather helmet'",
                        **self.UI['HINT']).pack(pady=(0, 2))

            txt_drop_names = ctk.CTkTextbox(tab, height=70, font=("Consolas", 10))
            txt_drop_names.pack(fill="x", padx=10, pady=2)
            txt_drop_names.insert("0.0", "\n".join(settings.get('drop_names', [])))
        else:
            ctk.CTkLabel(tab, text="⚠️ Sistema de loot configurável DESABILITADO",
                        text_color="orange", **self.UI['H1']).pack(pady=(8, 2))
            ctk.CTkLabel(tab, text="↳ Usando LOOT_IDS/DROP_IDS do config.py",
                        **self.UI['HINT']).pack(pady=(0, 2))

        def save_loot():
            try:
                s = self.cb.get_bot_settings()
                if entry_cont_count is not None:
                    s['loot_containers'] = int(entry_cont_count.get())
                s['loot_dest'] = int(entry_dest_idx.get())
                s['loot_drop_food'] = bool(switch_drop_food.get())
                s['loot_auto_eat'] = bool(switch_auto_eat.get())

                if self.cb.use_configurable_loot and txt_loot_names and txt_drop_names:
                    loot_lines = [line.strip() for line in txt_loot_names.get("0.0", "end").split('\n') if line.strip()]
                    drop_lines = [line.strip() for line in txt_drop_names.get("0.0", "end").split('\n') if line.strip()]

                    s['loot_names'] = loot_lines
                    s['drop_names'] = drop_lines

                    # Converter nomes para IDs
                    try:
                        from database import lootables_db

                        loot_ids = []
                        for name in loot_lines:
                            matches = lootables_db.find_loot_by_name(name)
                            if matches:
                                loot_ids.extend(matches)
                                if len(matches) > 1:
                                    self.cb.log(f"⚠️ '{name}' → {len(matches)} items encontrados")
                            else:
                                self.cb.log(f"❌ '{name}' não encontrado no database")

                        drop_ids = []
                        for name in drop_lines:
                            matches = lootables_db.find_loot_by_name(name)
                            if matches:
                                drop_ids.extend(matches)
                            else:
                                self.cb.log(f"❌ DROP: '{name}' não encontrado")

                        s['loot_ids'] = list(set(loot_ids))
                        s['drop_ids'] = list(set(drop_ids))

                        self.cb.log(f"💰 Loot salvo: {len(loot_ids)} items para lotar, {len(drop_ids)} para dropar")
                    except ImportError:
                        self.cb.log("💰 Loot salvo (database não disponível)")
                else:
                    self.cb.log("💰 Loot salvo (modo antigo - usando config.py)")

                self.cb.save_config_file()

            except Exception as e:
                self.cb.log(f"❌ Erro ao salvar loot: {e}")

        ctk.CTkButton(tab, text="Salvar Loot", command=save_loot,
                     fg_color="#2CC985", height=32).pack(side="bottom", pady=10, fill="x", padx=20)

    def _build_tab_fisher(self, tab: ctk.CTkFrame) -> None:
        """Constrói a aba Fisher."""
        settings = self.cb.get_bot_settings()

        # === CAPACIDADE ===
        ctk.CTkLabel(tab, text="Capacidade (Cap):", **self.UI['H1']).pack(anchor="w", padx=10, pady=(10, 3))

        f_cap = ctk.CTkFrame(tab, fg_color="transparent")
        f_cap.pack(fill="x", padx=10, pady=2)

        ctk.CTkLabel(f_cap, text="Min Cap:", **self.UI['BODY']).pack(side="left", padx=(5, 2))
        entry_fish_cap_val = ctk.CTkEntry(f_cap, width=50, height=24, font=self.UI['BODY']['font'], justify="center")
        entry_fish_cap_val.pack(side="left", padx=(0, 15))
        entry_fish_cap_val.insert(0, str(settings.get('fisher_min_cap', 10.0)))

        switch_fish_cap = ctk.CTkSwitch(f_cap, text="Pausar se cap baixa",
                                        progress_color="#FFA500", **self.UI['BODY'])
        switch_fish_cap.pack(side="left")
        if settings.get('fisher_check_cap', True):
            switch_fish_cap.select()

        ctk.CTkLabel(tab, text="↳ Pausa pesca quando capacidade < valor definido",
                    **self.UI['HINT']).pack(anchor="w", padx=15)

        # === HUMANIZAÇÃO ===
        ctk.CTkLabel(tab, text="Humanização:", **self.UI['H1']).pack(anchor="w", padx=10, pady=(15, 3))

        switch_fatigue = ctk.CTkSwitch(tab, text="Fadiga Humana",
                                       progress_color="#FFA500", **self.UI['BODY'])
        switch_fatigue.pack(anchor="w", padx=15, pady=2)
        if settings.get('fisher_fatigue', True):
            switch_fatigue.select()

        ctk.CTkLabel(tab, text="↳ Simula cansaço: pausas progressivas que aumentam com o tempo",
                    **self.UI['HINT']).pack(anchor="w", padx=20)

        # === AUTO-COMER ===
        ctk.CTkLabel(tab, text="Alimentação:", **self.UI['H1']).pack(anchor="w", padx=10, pady=(15, 3))

        switch_fisher_eat = ctk.CTkSwitch(tab, text="Auto-Comer",
                                          progress_color="#32CD32", **self.UI['BODY'])
        switch_fisher_eat.pack(anchor="w", padx=15, pady=2)
        if settings.get('fisher_auto_eat', False):
            switch_fisher_eat.select()

        ctk.CTkLabel(tab, text="↳ Come comida automaticamente a cada 2s até ficar full",
                    **self.UI['HINT']).pack(anchor="w", padx=20)

        def save_fish():
            try:
                s = self.cb.get_bot_settings()
                cap_val = float(entry_fish_cap_val.get().replace(',', '.'))
                s['fisher_min_cap'] = cap_val
                s['fisher_check_cap'] = bool(switch_fish_cap.get())
                s['fisher_fatigue'] = bool(switch_fatigue.get())
                s['fisher_auto_eat'] = bool(switch_fisher_eat.get())
                self.cb.save_config_file()
                self.cb.log("🎣 Fisher salvo.")
            except:
                self.cb.log("❌ Erro nos valores.")

        ctk.CTkButton(tab, text="Salvar Fisher", command=save_fish,
                     fg_color="#2CC985", height=32).pack(side="bottom", pady=10, fill="x", padx=20)

    def _build_tab_rune(self, tab: ctk.CTkFrame) -> None:
        """Constrói a aba Rune."""
        settings = self.cb.get_bot_settings()

        # Frame Craft
        frame_craft = ctk.CTkFrame(tab, fg_color="#2b2b2b")
        frame_craft.pack(fill="x", padx=5, pady=2)

        ctk.CTkLabel(frame_craft, text="⚙️ Crafting", **self.UI['H1']).pack(anchor="w", padx=5, pady=(5, 5))

        f_c1 = ctk.CTkFrame(frame_craft, fg_color="transparent")
        f_c1.pack(fill="x", padx=2, pady=2)

        ctk.CTkLabel(f_c1, text="Mana:", **self.UI['BODY']).pack(side="left", padx=5)
        entry_mana = ctk.CTkEntry(f_c1, **self.UI['INPUT'])
        entry_mana.configure(width=45)
        entry_mana.pack(side="left", padx=2)
        entry_mana.insert(0, str(settings['rune_mana']))

        ctk.CTkLabel(f_c1, text="Key:", **self.UI['BODY']).pack(side="left", padx=5)
        entry_hk = ctk.CTkEntry(f_c1, **self.UI['INPUT'])
        entry_hk.configure(width=35)
        entry_hk.pack(side="left", padx=2)
        entry_hk.insert(0, settings['rune_hotkey'])

        # Quantidade de runas (controla opções do combo Mão)
        ctk.CTkLabel(f_c1, text="Qtd:", **self.UI['BODY']).pack(side="left", padx=5)
        combo_rune_count = ctk.CTkComboBox(f_c1, values=["1", "2", "3", "4"], **self.UI['COMBO'])
        combo_rune_count.configure(width=45)
        combo_rune_count.pack(side="left", padx=2)
        combo_rune_count.set(str(settings.get('rune_count', 1)))

        # Mão (valores condicionais baseados em Qtd)
        ctk.CTkLabel(f_c1, text="Mão:", **self.UI['BODY']).pack(side="left", padx=5)
        combo_hand = ctk.CTkComboBox(f_c1, values=["DIREITA", "ESQUERDA"], **self.UI['COMBO'])
        combo_hand.configure(width=80)
        combo_hand.pack(side="left", padx=2)
        combo_hand.set(settings.get('rune_hand', 'DIREITA'))

        def on_rune_count_change(choice):
            """Atualiza opções do combo Mão baseado na quantidade de runas."""
            count = int(choice)
            current = combo_hand.get()
            if count == 1:
                # 1 runa: escolhe esquerda ou direita
                combo_hand.configure(values=["DIREITA", "ESQUERDA"])
                if current == "AMBAS":
                    combo_hand.set("DIREITA")
            elif count == 2:
                # 2 runas: sempre ambas
                combo_hand.configure(values=["AMBAS"])
                combo_hand.set("AMBAS")
            elif count == 3:
                # 3 runas: ambas + escolhe mão extra (esquerda ou direita)
                combo_hand.configure(values=["ESQUERDA", "DIREITA"])
                if current == "AMBAS":
                    combo_hand.set("ESQUERDA")
            elif count == 4:
                # 4 runas: sempre ambas × 2
                combo_hand.configure(values=["AMBAS"])
                combo_hand.set("AMBAS")

        combo_rune_count.configure(command=on_rune_count_change)
        # Aplicar estado inicial
        on_rune_count_change(combo_rune_count.get())

        # Hint explicativo sobre quantidade de runas
        ctk.CTkLabel(frame_craft, text="↳ 1: mão única | 2: ambas | 3: ambas + mão | 4: ambas × 2",
                    **self.UI['HINT']).pack(anchor="w", padx=10)

        # Frame Human
        frame_human = ctk.CTkFrame(tab, fg_color="#2b2b2b")
        frame_human.pack(fill="x", padx=5, pady=2)

        f_h1 = ctk.CTkFrame(frame_human, fg_color="transparent")
        f_h1.pack(fill="x", padx=2, pady=5)

        ctk.CTkLabel(f_h1, text="Esperar de:", **self.UI['BODY']).pack(side="left", padx=5)
        entry_human_min = ctk.CTkEntry(f_h1, **self.UI['INPUT'])
        entry_human_min.configure(width=35)
        entry_human_min.pack(side="left", padx=2)
        entry_human_min.insert(0, str(settings.get('rune_human_min', 5)))

        ctk.CTkLabel(f_h1, text="a", **self.UI['BODY']).pack(side="left", padx=2)
        entry_human_max = ctk.CTkEntry(f_h1, **self.UI['INPUT'])
        entry_human_max.configure(width=35)
        entry_human_max.pack(side="left", padx=2)
        entry_human_max.insert(0, str(settings.get('rune_human_max', 30)))
        ctk.CTkLabel(f_h1, text="segundos antes de castar", **self.UI['BODY']).pack(side="left", padx=2)

        # Frame Move
        frame_move = ctk.CTkFrame(tab, fg_color="#2b2b2b")
        frame_move.pack(fill="x", padx=5, pady=5)
        ctk.CTkLabel(frame_move, text="🚨 Anti-PK / Movimento", **self.UI['H1']).pack(anchor="w", padx=5, pady=(5, 5))

        # Toggle
        f_m1 = ctk.CTkFrame(frame_move, fg_color="transparent")
        f_m1.pack(fill="x", padx=2, pady=2)
        switch_movement = ctk.CTkSwitch(f_m1, text="Fugir para Safe", width=50, height=20,
                                        font=self.UI['BODY']['font'])
        switch_movement.pack(side="left", padx=5)
        if settings.get('rune_movement', False):
            switch_movement.select()

        # Coords - Work
        f_wk = ctk.CTkFrame(frame_move, fg_color="transparent")
        f_wk.pack(fill="x", pady=2)
        ctk.CTkButton(f_wk, text="Set Work", width=60, height=20, font=("Verdana", 9),
                     fg_color="#444", command=lambda: self.cb.set_rune_pos("WORK")).pack(side="left", padx=5)
        self.lbl_work_pos = ctk.CTkLabel(f_wk, text=str(settings.get('rune_work_pos', (0, 0, 0))),
                                         **self.UI['HINT'])
        self.lbl_work_pos.pack(side="left", padx=5)

        # Coords - Safe
        f_sf = ctk.CTkFrame(frame_move, fg_color="transparent")
        f_sf.pack(fill="x", pady=2)
        ctk.CTkButton(f_sf, text="Set Safe", width=60, height=20, font=("Verdana", 9),
                     fg_color="#444", command=lambda: self.cb.set_rune_pos("SAFE")).pack(side="left", padx=5)
        self.lbl_safe_pos = ctk.CTkLabel(f_sf, text=str(settings.get('rune_safe_pos', (0, 0, 0))),
                                         **self.UI['HINT'])
        self.lbl_safe_pos.pack(side="left", padx=5)

        # Delays
        f_m2 = ctk.CTkFrame(frame_move, fg_color="transparent")
        f_m2.pack(fill="x", padx=5, pady=5)
        ctk.CTkLabel(f_m2, text="Reagir em:", **self.UI['BODY']).pack(side="left")
        entry_flee = ctk.CTkEntry(f_m2, **self.UI['INPUT'])
        entry_flee.configure(width=35)
        entry_flee.pack(side="left", padx=2)
        entry_flee.insert(0, str(settings.get('rune_flee_delay', 0.5)))

        ctk.CTkLabel(f_m2, text="Retornar após:", **self.UI['BODY']).pack(side="left", padx=5)
        entry_ret_delay = ctk.CTkEntry(f_m2, **self.UI['INPUT'])
        entry_ret_delay.configure(width=35)
        entry_ret_delay.pack(side="left", padx=2)
        entry_ret_delay.insert(0, str(settings.get('rune_return_delay', 300)))

        # Frame Extras
        frame_extras = ctk.CTkFrame(tab, fg_color="#2b2b2b")
        frame_extras.pack(fill="x", padx=5, pady=2)
        ctk.CTkLabel(frame_extras, text="Outros", **self.UI['H1']).pack(anchor="w", padx=5, pady=5)

        switch_eat = ctk.CTkSwitch(frame_extras, text="Auto Eat", width=60, height=20,
                                   font=self.UI['BODY']['font'])
        switch_eat.pack(anchor="w", padx=10, pady=2)
        if settings['auto_eat']:
            switch_eat.select()

        switch_train = ctk.CTkSwitch(frame_extras, text="Mana Train (No rune)", width=60, height=20,
                                     font=self.UI['BODY']['font'])
        switch_train.pack(anchor="w", padx=10, pady=2)
        if settings['mana_train']:
            switch_train.select()

        switch_logout_blanks = ctk.CTkSwitch(frame_extras, text="Logout se sem Blanks", width=60, height=20,
                                             font=self.UI['BODY']['font'])
        switch_logout_blanks.pack(anchor="w", padx=10, pady=2)
        if settings.get('logout_on_no_blanks', False):
            switch_logout_blanks.select()

        ctk.CTkLabel(frame_extras, text="↳ Desloga após 15s parado sem blanks",
                    **self.UI['HINT']).pack(anchor="w", padx=45)

        def save_rune():
            try:
                s = self.cb.get_bot_settings()
                s['rune_mana'] = int(entry_mana.get())
                s['rune_hotkey'] = entry_hk.get().upper()
                s['rune_hand'] = combo_hand.get()
                s['rune_count'] = int(combo_rune_count.get())
                s['rune_blank_id'] = 3147
                s['rune_human_min'] = int(entry_human_min.get())
                s['rune_human_max'] = int(entry_human_max.get())
                s['rune_flee_delay'] = float(entry_flee.get())
                s['rune_return_delay'] = int(entry_ret_delay.get())
                s['rune_movement'] = bool(switch_movement.get())
                s['auto_eat'] = bool(switch_eat.get())
                s['mana_train'] = bool(switch_train.get())
                s['logout_on_no_blanks'] = bool(switch_logout_blanks.get())
                self.cb.save_config_file()
                self.cb.log("🔮 Rune Config salva!")
            except:
                self.cb.log("❌ Erro Rune.")

        ctk.CTkButton(tab, text="Salvar Rune", command=save_rune, height=32,
                     fg_color="#00A86B", hover_color="#008f5b").pack(side="bottom", fill="x", padx=20, pady=5)

    def _build_tab_healer(self, tab: ctk.CTkFrame) -> None:
        """Constrói a aba Healer."""
        settings = self.cb.get_bot_settings()

        # Store rule row widgets for collection on save
        healer_rule_rows = []

        # Cooldown inline
        f_cooldown = ctk.CTkFrame(tab, fg_color="transparent")
        f_cooldown.pack(fill="x", padx=10, pady=(8, 3))
        ctk.CTkLabel(f_cooldown, text="Cooldown:", **self.UI['BODY']).pack(side="left", padx=(5, 2))
        entry_cooldown = ctk.CTkEntry(f_cooldown, width=60, height=24, font=self.UI['BODY']['font'], justify="center")
        entry_cooldown.pack(side="left", padx=2)
        entry_cooldown.insert(0, str(settings.get('healer_cooldown_ms', 2000)))
        ctk.CTkLabel(f_cooldown, text="ms entre heals", **self.UI['BODY']).pack(side="left", padx=2)

        # === RULES SECTION ===
        ctk.CTkLabel(tab, text="Regras de Cura", **self.UI['H1']).pack(anchor="w", padx=10, pady=(8, 3))
        ctk.CTkLabel(tab, text="Menor prioridade = executa primeiro",
                    **self.UI['HINT']).pack(anchor="w", padx=20, pady=2)

        # Rules container
        f_rules_container = ctk.CTkFrame(tab, fg_color="transparent")
        f_rules_container.pack(fill="both", expand=True, padx=10, pady=5)

        # Healing options based on target type
        HEAL_OPTIONS_SELF = ["UH", "IH", "Exura Vita", "Exura Gran", "Exura"]
        HEAL_OPTIONS_OTHER = ["UH", "IH", "Exura Sio"]

        # Header row
        f_header = ctk.CTkFrame(f_rules_container, fg_color="transparent")
        f_header.pack(fill="x", pady=(0, 3))
        ctk.CTkLabel(f_header, text="Prio", width=35, **self.UI['HINT']).pack(side="left", padx=2)
        ctk.CTkLabel(f_header, text="Alvo", width=75, **self.UI['HINT']).pack(side="left", padx=2)
        ctk.CTkLabel(f_header, text="Nome", width=70, **self.UI['HINT']).pack(side="left", padx=2)
        ctk.CTkLabel(f_header, text="HP%", width=35, **self.UI['HINT']).pack(side="left", padx=2)
        ctk.CTkLabel(f_header, text="Cura", width=90, **self.UI['HINT']).pack(side="left", padx=2)

        # Frame for rule rows
        f_rules_list = ctk.CTkFrame(f_rules_container, fg_color="#2b2b2b")
        f_rules_list.pack(fill="both", expand=True)

        def create_rule_row(rule_data=None):
            """Create a single rule row with widgets."""
            row_frame = ctk.CTkFrame(f_rules_list, fg_color="transparent")
            row_frame.pack(fill="x", pady=2, padx=5)

            # Priority
            entry_prio = ctk.CTkEntry(row_frame, width=35, height=24, font=("Verdana", 9), justify="center")
            entry_prio.pack(side="left", padx=2)
            default_prio = rule_data.get('priority', 1) if rule_data else len(healer_rule_rows) + 1
            entry_prio.insert(0, str(default_prio))

            # Target type
            combo_target = ctk.CTkComboBox(row_frame, values=["self", "friend", "creature"],
                                            width=75, height=24, font=("Verdana", 9), state="readonly")
            combo_target.pack(side="left", padx=2)
            combo_target.set(rule_data.get('target_type', 'self') if rule_data else "self")

            # Target name
            entry_name = ctk.CTkEntry(row_frame, width=70, height=24, font=("Verdana", 9))
            entry_name.pack(side="left", padx=2)
            if rule_data and rule_data.get('target_name'):
                entry_name.insert(0, rule_data['target_name'])

            # HP%
            entry_hp = ctk.CTkEntry(row_frame, width=35, height=24, font=("Verdana", 9), justify="center")
            entry_hp.pack(side="left", padx=2)
            entry_hp.insert(0, str(rule_data.get('hp_below_percent', 50) if rule_data else 50))

            # Heal option (single combobox for spell/rune)
            combo_heal = ctk.CTkComboBox(row_frame, values=HEAL_OPTIONS_SELF,
                                          width=90, height=24, font=("Verdana", 9), state="readonly")
            combo_heal.pack(side="left", padx=2)

            # Set initial value from rule_data
            if rule_data:
                heal_value = rule_data.get('spell_or_rune', 'UH').upper()
                # Normalize spell names for display
                spell_map = {'EXURA': 'Exura', 'EXURA VITA': 'Exura Vita',
                             'EXURA GRAN': 'Exura Gran', 'EXURA SIO': 'Exura Sio'}
                heal_value = spell_map.get(heal_value, heal_value)
                combo_heal.set(heal_value)
            else:
                combo_heal.set("UH")

            # Remove button
            def remove_row():
                row_frame.destroy()
                # Clean up list
                for i, r in enumerate(healer_rule_rows):
                    if r['frame'] == row_frame:
                        healer_rule_rows.pop(i)
                        break

            btn_remove = ctk.CTkButton(row_frame, text="X", width=25, height=24,
                                       fg_color="#FF5555", hover_color="#CC4444",
                                       font=("Verdana", 9, "bold"), command=remove_row)
            btn_remove.pack(side="left", padx=5)

            # Update fields based on target type
            def on_target_change(choice):
                current_heal = combo_heal.get()
                if choice == "self":
                    entry_name.delete(0, "end")
                    entry_name.configure(state="disabled", fg_color="#1a1a1a")
                    combo_heal.configure(values=HEAL_OPTIONS_SELF)
                    # Keep current value if valid, otherwise default
                    if current_heal not in HEAL_OPTIONS_SELF:
                        combo_heal.set("UH")
                else:
                    entry_name.configure(state="normal", fg_color="#343638")
                    combo_heal.configure(values=HEAL_OPTIONS_OTHER)
                    # Keep current value if valid, otherwise default
                    if current_heal not in HEAL_OPTIONS_OTHER:
                        combo_heal.set("UH")

            combo_target.configure(command=on_target_change)
            on_target_change(combo_target.get())  # Initial state

            # Store widgets reference
            row_data = {
                'frame': row_frame,
                'priority': entry_prio,
                'target_type': combo_target,
                'target_name': entry_name,
                'hp_percent': entry_hp,
                'heal': combo_heal
            }
            healer_rule_rows.append(row_data)
            return row_data

        # Load existing rules
        for rule in settings.get('healer_rules', []):
            if isinstance(rule, dict):
                create_rule_row(rule)

        # Add rule button
        def add_rule():
            create_rule_row()

        ctk.CTkButton(f_rules_container, text="+ Adicionar Regra", command=add_rule,
                     fg_color="#4A90E2", hover_color="#3A7BC8", height=28,
                     font=("Verdana", 10)).pack(pady=(10, 5))

        # === SAVE BUTTON ===
        def save_healer():
            try:
                s = self.cb.get_bot_settings()
                s['healer_cooldown_ms'] = int(entry_cooldown.get())

                # Collect rules from widgets
                parsed_rules = []
                for row in healer_rule_rows:
                    if not row['frame'].winfo_exists():
                        continue

                    target_type = row['target_type'].get()
                    target_name = row['target_name'].get().strip() if target_type != "self" else ""

                    try:
                        priority = int(row['priority'].get())
                        hp_pct = int(row['hp_percent'].get())
                    except ValueError:
                        self.cb.log("❌ Prioridade e HP% devem ser números")
                        continue

                    heal_option = row['heal'].get()
                    if not heal_option:
                        continue

                    # Parse heal option into method and spell_or_rune
                    if heal_option in ["UH", "IH"]:
                        method = "rune"
                        spell_or_rune = heal_option
                    else:
                        method = "spell"
                        # Convert display name to spell words
                        spell_map = {
                            "Exura": "exura",
                            "Exura Vita": "exura vita",
                            "Exura Gran": "exura gran",
                            "Exura Sio": "exura sio"
                        }
                        spell_or_rune = spell_map.get(heal_option, heal_option.lower())

                    parsed_rules.append({
                        'priority': priority,
                        'enabled': True,
                        'target_type': target_type,
                        'target_name': target_name,
                        'hp_below_percent': hp_pct,
                        'method': method,
                        'spell_or_rune': spell_or_rune,
                    })

                # Sort by priority
                parsed_rules.sort(key=lambda r: r['priority'])
                s['healer_rules'] = parsed_rules

                self.cb.save_config_file()
                self.cb.log(f"💚 Healer salvo: {len(parsed_rules)} regras")

                # Notify healer module to reload rules
                try:
                    from modules.healer import get_healer_module
                    healer = get_healer_module()
                    if healer:
                        healer.mark_rules_dirty()
                except:
                    pass

            except Exception as e:
                self.cb.log(f"❌ Erro ao salvar Healer: {e}")

        ctk.CTkButton(tab, text="Salvar Healer", command=save_healer,
                     fg_color="#2CC985", height=32).pack(side="bottom", pady=10, fill="x", padx=20)

    def _build_tab_cavebot(self, tab: ctk.CTkFrame) -> None:
        """Constrói a aba Cavebot."""
        settings = self.cb.get_bot_settings()

        # Container principal
        frame_cb_root = ctk.CTkFrame(tab, fg_color="transparent")
        frame_cb_root.pack(fill="both", expand=True, padx=8, pady=8)

        # Status
        self.label_cavebot_status = ctk.CTkLabel(frame_cb_root, text="📍 Posição: ---", **self.UI['BODY'])
        self.label_cavebot_status.pack(anchor="w", pady=(0, 8))

        # Seção Arquivo
        frame_arquivo = ctk.CTkFrame(frame_cb_root)
        frame_arquivo.pack(fill="x", pady=(0, 8))

        # Linha Carregar
        frame_load = ctk.CTkFrame(frame_arquivo, fg_color="transparent")
        frame_load.pack(fill="x", padx=10, pady=5)

        ctk.CTkLabel(frame_load, text="Carregar:", width=60, **self.UI['BODY']).pack(side="left")
        self.combo_cavebot_scripts = ctk.CTkComboBox(frame_load, values=[], width=140,
                                                     state="readonly", **self.UI['BODY'])
        self.combo_cavebot_scripts.pack(side="left", padx=5)
        ctk.CTkButton(frame_load, text="📂 Carregar", width=90, command=self.cb.load_waypoints_file,
                     **self.UI['BUTTON_SM']).pack(side="left")

        # Linha Salvar
        frame_save = ctk.CTkFrame(frame_arquivo, fg_color="transparent")
        frame_save.pack(fill="x", padx=10, pady=5)

        ctk.CTkLabel(frame_save, text="Salvar:", width=60, **self.UI['BODY']).pack(side="left")
        self.entry_waypoint_name = ctk.CTkEntry(frame_save, width=140, **self.UI['BODY'])
        self.entry_waypoint_name.pack(side="left", padx=5)

        ctk.CTkButton(frame_save, text="💾 Salvar", width=70, command=self.cb.save_waypoints_file,
                     **self.UI['BUTTON_SM']).pack(side="left")

        def refresh_combo():
            scripts = self.cb.refresh_scripts_combo(self.cb.get_current_waypoints_filename() or None)
            self.refresh_scripts_combo_ui(scripts, self.cb.get_current_waypoints_filename())

        ctk.CTkButton(frame_save, text="🔄", width=30, command=refresh_combo,
                     **self.UI['BUTTON_SM']).pack(side="left", padx=5)

        # Inicializa combo
        scripts = self.cb.refresh_scripts_combo(self.cb.get_current_waypoints_filename() or None)
        self.refresh_scripts_combo_ui(scripts, self.cb.get_current_waypoints_filename())

        # Seção Waypoints
        frame_waypoints = ctk.CTkFrame(frame_cb_root, fg_color="#3a3a3a")
        frame_waypoints.pack(fill="x", expand=True, pady=(0, 2))

        self.lbl_wp_header = ctk.CTkLabel(frame_waypoints, text="Waypoints (0)", **self.UI['H1'])
        self.lbl_wp_header.pack(anchor="w", padx=10, pady=5)

        frame_wp_content = ctk.CTkFrame(frame_waypoints, fg_color="transparent")
        frame_wp_content.pack(fill="x", expand=True, padx=10, pady=(0, 10))

        # Coluna Botões (compacto mas funcional)
        frame_buttons = ctk.CTkFrame(frame_wp_content, fg_color="transparent")
        frame_buttons.pack(side="left", fill="y", padx=(0, 5))

        # Botão principal
        ctk.CTkButton(frame_buttons, text="+ Adicionar", fg_color="#2CC985", width=80,
                     hover_color="#1FA86E", command=self.cb.record_current_pos, height=28,
                     font=("Verdana", 9)).pack(fill="x", pady=(0, 3))

        # Botões de navegação em linha
        f_nav = ctk.CTkFrame(frame_buttons, fg_color="transparent")
        f_nav.pack(fill="x", pady=2)
        ctk.CTkButton(f_nav, text="▲", width=38, height=22, command=self.cb.move_waypoint_up,
                     font=("Verdana", 9)).pack(side="left", padx=(0, 2))
        ctk.CTkButton(f_nav, text="▼", width=38, height=22, command=self.cb.move_waypoint_down,
                     font=("Verdana", 9)).pack(side="left")

        # Botões de ação em linha
        f_act = ctk.CTkFrame(frame_buttons, fg_color="transparent")
        f_act.pack(fill="x", pady=2)
        ctk.CTkButton(f_act, text="Rem", width=38, height=22, fg_color="#FF5555",
                     command=self.cb.remove_selected_waypoint, font=("Verdana", 8)).pack(side="left", padx=(0, 2))
        ctk.CTkButton(f_act, text="Limpar", width=38, height=22, fg_color="#e74c3c",
                     command=self.cb.clear_waypoints, font=("Verdana", 8)).pack(side="left")

        # Coluna Listbox
        frame_listbox = ctk.CTkFrame(frame_wp_content, fg_color="transparent")
        frame_listbox.pack(side="left", fill="both", expand=True)

        scrollbar_wp = tk.Scrollbar(frame_listbox)
        scrollbar_wp.pack(side="right", fill="y")

        self.waypoint_listbox = tk.Listbox(
            frame_listbox,
            selectmode=tk.SINGLE,
            font=("Consolas", 8),
            bg="#2b2b2b",
            fg="#ffffff",
            selectbackground="#4A90E2",
            selectforeground="#ffffff",
            highlightthickness=0,
            borderwidth=0,
            height=1,
            yscrollcommand=scrollbar_wp.set
        )
        self.waypoint_listbox.pack(side="left", fill="both", expand=True)
        scrollbar_wp.config(command=self.waypoint_listbox.yview)

        # Editor Visual button
        ctk.CTkButton(frame_waypoints, text="🗺️ Editor Visual",
                     fg_color="#2E8B57", hover_color="#228B45",
                     command=self.cb.open_waypoint_editor,
                     **self.UI['BUTTON_SM']).pack(fill="x", padx=10, pady=(0, 5))

        # === OPÇÕES (Auto-Explore + AFK) ===
        frame_options = ctk.CTkFrame(frame_cb_root, fg_color="#3a3a3a")
        frame_options.pack(fill="x", pady=(0, 5))

        self._auto_explore_var = ctk.IntVar(value=1 if settings.get('auto_explore_enabled', False) else 0)

        # Linha 1: Auto-explore + Raio
        frame_row1 = ctk.CTkFrame(frame_options, fg_color="transparent")
        frame_row1.pack(fill="x", padx=10, pady=5)

        def toggle_auto_explore():
            enabled = self._auto_explore_var.get() == 1
            try:
                radius = int(self._entry_explore_radius.get())
            except ValueError:
                radius = 50
            self.cb.on_auto_explore_toggle(enabled, radius, 600)

        switch_auto_explore = ctk.CTkSwitch(frame_row1, text="Auto-Explore",
                                            variable=self._auto_explore_var, command=toggle_auto_explore,
                                            **self.UI['BODY'])
        switch_auto_explore.pack(side="left")

        ctk.CTkLabel(frame_row1, text="Raio:", **self.UI['BODY']).pack(side="left", padx=(15, 5))
        self._entry_explore_radius = ctk.CTkEntry(frame_row1, width=45, **self.UI['BODY'])
        self._entry_explore_radius.pack(side="left")
        self._entry_explore_radius.insert(0, str(settings.get('auto_explore_radius', 50)))

        # === BOTÃO SALVAR CAVEBOT (salva tudo) ===
        def save_cavebot():
            try:
                s = self.cb.get_bot_settings()
                # Auto-Explore
                s['auto_explore_enabled'] = self._auto_explore_var.get() == 1
                s['auto_explore_radius'] = max(10, int(self._entry_explore_radius.get()))
                s['auto_explore_cooldown'] = 600
                self.cb.save_config_file()
                self.cb.log("🤖 Cavebot salvo!")
            except Exception:
                self.cb.log("❌ Erro ao salvar Cavebot.")

        ctk.CTkButton(frame_cb_root, text="Salvar Cavebot", command=save_cavebot,
                      fg_color="#2CC985", height=32).pack(fill="x", pady=(0, 5))

        # Inicializa lista visual
        self.update_waypoint_display_ui(self.cb.get_current_waypoints())
