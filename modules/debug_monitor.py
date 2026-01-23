# modules/debug_monitor.py
"""
Debug Monitor - Janela com abas para monitorar bot_state e módulos.

Abas:
- Bot State: Estado geral do bot
- Trainer: Variáveis do módulo de combate
- Spear Picker: Variáveis do coletor de spears
"""

import time
import threading
import customtkinter as ctk
from core.bot_state import state
import config


class DebugMonitorWindow:
    """Janela de debug com abas para diferentes módulos."""

    def __init__(self, parent_app):
        self.parent_app = parent_app
        self.window = None
        self.labels = {}  # {tab_name: {field_name: label_widget}}
        self.is_running = False
        self.update_thread = None

    def create_window(self):
        """Cria janela com sistema de abas."""
        if self.window is not None and self.window.winfo_exists():
            self.window.lift()
            self.window.focus()
            return

        # Janela principal
        self.window = ctk.CTkToplevel(self.parent_app)
        self.window.title("Debug Monitor")
        self.window.geometry("350x450+50+50")
        self.window.attributes("-topmost", True)
        self.window.configure(fg_color="#1a1a1a")

        # Sistema de abas
        tabview = ctk.CTkTabview(self.window, fg_color="#1a1a1a")
        tabview.pack(fill="both", expand=True, padx=5, pady=5)

        # Cria abas
        tab_bot_state = tabview.add("Bot State")
        tab_trainer = tabview.add("Trainer")
        tab_spear = tabview.add("Spear Picker")

        # Inicializa dicionários de labels
        self.labels["bot_state"] = {}
        self.labels["trainer"] = {}
        self.labels["spear"] = {}

        # ===== ABA BOT STATE =====
        self._create_tab_bot_state(tab_bot_state)

        # ===== ABA TRAINER =====
        self._create_tab_trainer(tab_trainer)

        # ===== ABA SPEAR PICKER =====
        self._create_tab_spear_picker(tab_spear)

        self.window.protocol("WM_DELETE_WINDOW", self.close_window)
        print("[DEBUG_MONITOR] Janela criada com abas")

    def _create_tab_bot_state(self, parent):
        """Cria aba de Bot State."""
        scroll = ctk.CTkScrollableFrame(parent, fg_color="#1a1a1a")
        scroll.pack(fill="both", expand=True, padx=5, pady=5)

        fields = [
            "is_connected",
            "is_running",
            "is_safe",
            "is_gm_detected",
            "pause_reason",
            "cooldown_remaining",
            "char_name",
            "char_id",
            "is_in_combat",
            "has_open_loot",
            "is_processing_loot",
            "last_combat_time",
            "is_runemaking",
            "is_chat_paused",
            "chat_pause_until",
            "cavebot_active"
        ]

        for field in fields:
            self._create_field(scroll, "bot_state", field)

    def _create_tab_trainer(self, parent):
        """Cria aba de Trainer."""
        scroll = ctk.CTkScrollableFrame(parent, fg_color="#1a1a1a")
        scroll.pack(fill="both", expand=True, padx=5, pady=5)

        # Nota explicativa
        note = ctk.CTkLabel(
            scroll,
            text="Variáveis do módulo Trainer\n(em combate)",
            font=("Consolas", 9, "italic"),
            text_color="#888888"
        )
        note.pack(pady=(5, 10))

        fields = [
            "is_in_combat",
            "has_open_loot",
            "is_processing_loot",
            "last_combat_time",
        ]

        for field in fields:
            self._create_field(scroll, "trainer", field)

        # Placeholder para expansão futura
        separator = ctk.CTkFrame(scroll, height=2, fg_color="#333333")
        separator.pack(fill="x", pady=10)

        future_label = ctk.CTkLabel(
            scroll,
            text="Variáveis internas do trainer_loop:\n(requerem exposição via módulo)",
            font=("Consolas", 8, "italic"),
            text_color="#666666",
            justify="left"
        )
        future_label.pack(pady=5)

        # Campos futuros (mostram N/A por enquanto)
        future_fields = [
            "current_target_id",
            "current_target_name",
            "current_target_hp",
            "death_state",
            "became_unreachable",
            "next_attack_time"
        ]

        for field in future_fields:
            self._create_field(scroll, "trainer", field, show_na=True)

    def _create_tab_spear_picker(self, parent):
        """Cria aba de Spear Picker."""
        scroll = ctk.CTkScrollableFrame(parent, fg_color="#1a1a1a")
        scroll.pack(fill="both", expand=True, padx=5, pady=5)

        # Nota explicativa
        note = ctk.CTkLabel(
            scroll,
            text="Variáveis do Spear Picker\n(coleta automática)",
            font=("Consolas", 9, "italic"),
            text_color="#888888"
        )
        note.pack(pady=(5, 10))

        # Campos futuros (mostram N/A por enquanto)
        future_fields = [
            "last_spear_count",
            "needs_spears",
            "max_spears",
            "monitor_running",
            "action_running",
            "last_pickup_time"
        ]

        for field in future_fields:
            self._create_field(scroll, "spear", field, show_na=True)

        # Nota de instrução
        separator = ctk.CTkFrame(scroll, height=2, fg_color="#333333")
        separator.pack(fill="x", pady=10)

        info_label = ctk.CTkLabel(
            scroll,
            text="Para mostrar dados reais,\nos módulos precisam exportar\nseu estado via sistema global.",
            font=("Consolas", 8, "italic"),
            text_color="#666666",
            justify="left"
        )
        info_label.pack(pady=5)

    def _create_field(self, parent, tab_name, field_name, show_na=False):
        """Cria um campo de variável."""
        frame = ctk.CTkFrame(parent, fg_color="transparent", height=20)
        frame.pack(fill="x", pady=1)
        frame.pack_propagate(False)

        # Nome da variável
        name_label = ctk.CTkLabel(
            frame,
            text=field_name,
            font=("Consolas", 9),
            text_color="#888888",
            anchor="w",
            width=150
        )
        name_label.pack(side="left", padx=(5, 2))

        # Valor
        initial_value = "N/A" if show_na else "---"
        value_label = ctk.CTkLabel(
            frame,
            text=initial_value,
            font=("Consolas", 9, "bold"),
            text_color="#666666" if show_na else "#FFFFFF",
            anchor="w"
        )
        value_label.pack(side="left", fill="x", expand=True, padx=(2, 5))

        # Armazena referência
        self.labels[tab_name][field_name] = value_label

    def update_values(self):
        """Atualiza todos os valores das abas."""
        if not self.window or not self.window.winfo_exists():
            return

        try:
            status = state.get_status()

            # ===== ABA BOT STATE =====
            self._update_bot_state(status)

            # ===== ABA TRAINER =====
            self._update_trainer(status)

            # ===== ABA SPEAR PICKER =====
            self._update_spear_picker(status)

        except Exception as e:
            print(f"[DEBUG_MONITOR] Erro: {e}")

    def _update_bot_state(self, status):
        """Atualiza aba Bot State."""
        tab = "bot_state"

        # is_connected
        self._update_field(tab, "is_connected",
                          "Yes" if status['is_connected'] else "No",
                          "#00FFFF" if status['is_connected'] else "#FF0000")

        # is_running
        self._update_field(tab, "is_running",
                          "Yes" if status['is_running'] else "No",
                          "#00FF00" if status['is_running'] else "#FF0000")

        # is_safe
        self._update_field(tab, "is_safe",
                          "Yes" if status['is_safe'] else "No",
                          "#00FF00" if status['is_safe'] else "#FF0000")

        # is_gm_detected
        self._update_field(tab, "is_gm_detected",
                          "ALERT!" if status['is_gm_detected'] else "Clear",
                          "#FF00FF" if status['is_gm_detected'] else "#808080")

        # pause_reason
        reason = status['pause_reason'] if status['pause_reason'] else "---"
        self._update_field(tab, "pause_reason", reason,
                          "#FF0000" if status['pause_reason'] else "#808080")

        # cooldown_remaining
        cd = status['cooldown_remaining']
        self._update_field(tab, "cooldown_remaining",
                          f"{cd:.1f}s" if cd > 0 else "0",
                          "#FFFF00" if cd > 0 else "#808080")

        # char_name
        self._update_field(tab, "char_name",
                          status['char_name'] if status['char_name'] else "---",
                          "#CCCCCC")

        # char_id
        self._update_field(tab, "char_id",
                          str(status['char_id']) if status['char_id'] else "0",
                          "#CCCCCC")

        # is_in_combat
        self._update_field(tab, "is_in_combat",
                          "Yes" if status['is_in_combat'] else "No",
                          "#FFFF00" if status['is_in_combat'] else "#808080")

        # has_open_loot
        self._update_field(tab, "has_open_loot",
                          "Yes" if status['has_open_loot'] else "No",
                          "#FFFF00" if status['has_open_loot'] else "#808080")

        # is_processing_loot
        self._update_field(tab, "is_processing_loot",
                          "Yes" if status['is_processing_loot'] else "No",
                          "#FFFF00" if status['is_processing_loot'] else "#808080")

        # last_combat_time
        last_combat = status['last_combat_time']
        if last_combat > 0:
            ago = int(time.time() - last_combat)
            self._update_field(tab, "last_combat_time", f"{ago}s", "#CCCCCC")
        else:
            self._update_field(tab, "last_combat_time", "Never", "#808080")

        # is_runemaking
        self._update_field(tab, "is_runemaking",
                          "Yes" if status['is_runemaking'] else "No",
                          "#FFFF00" if status['is_runemaking'] else "#808080")

        # is_chat_paused
        self._update_field(tab, "is_chat_paused",
                          "Yes" if status['is_chat_paused'] else "No",
                          "#FFFF00" if status['is_chat_paused'] else "#808080")

        # chat_pause_until
        if status['is_chat_paused']:
            remaining = status['chat_pause_until'] - time.time()
            self._update_field(tab, "chat_pause_until",
                              f"{remaining:.1f}s" if remaining > 0 else "0",
                              "#FFFF00")
        else:
            self._update_field(tab, "chat_pause_until", "---", "#808080")

        # cavebot_active
        self._update_field(tab, "cavebot_active",
                          "Yes" if state.cavebot_active else "No",
                          "#FFFF00" if state.cavebot_active else "#808080")

    def _update_trainer(self, status):
        """Atualiza aba Trainer."""
        tab = "trainer"

        # Variáveis disponíveis via bot_state
        self._update_field(tab, "is_in_combat",
                          "Yes" if status['is_in_combat'] else "No",
                          "#FFFF00" if status['is_in_combat'] else "#808080")

        self._update_field(tab, "has_open_loot",
                          "Yes" if status['has_open_loot'] else "No",
                          "#FFFF00" if status['has_open_loot'] else "#808080")

        self._update_field(tab, "is_processing_loot",
                          "Yes" if status['is_processing_loot'] else "No",
                          "#FFFF00" if status['is_processing_loot'] else "#808080")

        last_combat = status['last_combat_time']
        if last_combat > 0:
            ago = int(time.time() - last_combat)
            self._update_field(tab, "last_combat_time", f"{ago}s", "#CCCCCC")
        else:
            self._update_field(tab, "last_combat_time", "Never", "#808080")

        # Variáveis internas (N/A por enquanto)
        # Esses campos foram criados como placeholders
        # Para mostrar dados reais, o trainer.py precisa exportar essas variáveis

    def _update_spear_picker(self, status):
        """Atualiza aba Spear Picker."""
        # Por enquanto, todos os campos mostram N/A
        # Para mostrar dados reais, o spear_picker.py precisa exportar seu estado
        pass

    def _update_field(self, tab, field, text, color):
        """Atualiza um campo específico."""
        if tab in self.labels and field in self.labels[tab]:
            self.labels[tab][field].configure(text=str(text), text_color=color)

    def close_window(self):
        """Fecha janela."""
        if self.window:
            self.window.destroy()
            self.window = None
            print("[DEBUG_MONITOR] Fechado")

    def start_update_loop(self):
        """Inicia loop de atualização."""
        self.is_running = True

        def update_loop():
            print("[DEBUG_MONITOR] Loop iniciado")
            while self.is_running and state.is_running:
                if not getattr(config, 'DEBUG_BOT_STATE', False):
                    time.sleep(1)
                    continue

                if self.window and self.window.winfo_exists():
                    try:
                        self.window.after(0, self.update_values)
                    except:
                        pass

                interval = getattr(config, 'DEBUG_BOT_STATE_INTERVAL', 0.1)
                time.sleep(interval)

            print("[DEBUG_MONITOR] Loop encerrado")

        self.update_thread = threading.Thread(target=update_loop, daemon=True)
        self.update_thread.start()

    def stop(self):
        """Para monitor."""
        self.is_running = False
        self.close_window()


# =============================================================================
# API GLOBAL
# =============================================================================

_monitor_instance = None


def init_debug_monitor(parent_app):
    """Inicializa monitor."""
    global _monitor_instance
    if _monitor_instance is None:
        _monitor_instance = DebugMonitorWindow(parent_app)
        print("[DEBUG_MONITOR] Inicializado")
    return _monitor_instance


def show_debug_monitor():
    """Mostra janela."""
    global _monitor_instance
    if _monitor_instance is None:
        print("[DEBUG_MONITOR] ERRO: Não inicializado")
        return

    if not getattr(config, 'DEBUG_BOT_STATE', False):
        print("[DEBUG_MONITOR] Desabilitado em config.py")
        return

    _monitor_instance.create_window()
    if not _monitor_instance.is_running:
        _monitor_instance.start_update_loop()


def close_debug_monitor():
    """Fecha janela."""
    global _monitor_instance
    if _monitor_instance:
        _monitor_instance.stop()
