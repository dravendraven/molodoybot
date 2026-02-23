"""
Mock Visual - GUI usando tkinter puro (sem customtkinter)
Execute: python gui/mock_tkinter_gui.py

Visual otimizado para parecer moderno mesmo sem customtkinter.
Requer: pip install pillow (para anti-aliasing nos toggles)
"""

import tkinter as tk
from tkinter import ttk

# PIL para anti-aliasing
try:
    from PIL import Image, ImageDraw, ImageTk
    HAS_PIL = True
except ImportError:
    HAS_PIL = False
    print("[AVISO] PIL não encontrado. Toggles sem anti-aliasing.")
    print("        Instale com: pip install pillow")


# =============================================================================
# CORES DO TEMA
# =============================================================================
COLORS = {
    'bg_dark': '#1a1a1a',
    'bg_main': '#202020',
    'bg_panel': '#2b2b2b',
    'bg_input': '#333333',
    'bg_hover': '#3a3a3a',
    'border': '#404040',
    'text': '#FFFFFF',
    'text_dim': '#888888',
    'text_hint': '#555555',
    'accent_green': '#2CC985',
    'accent_blue': '#4EA5F9',
    'accent_purple': '#A54EF9',
    'accent_orange': '#F39C12',
    'accent_red': '#FF6B6B',
    'accent_gold': '#FFD700',
    'switch_off': '#555555',
}


# =============================================================================
# CUSTOM SWITCH WIDGET (com anti-aliasing via PIL)
# =============================================================================
class ToggleSwitch(tk.Canvas):
    """Switch toggle customizado com anti-aliasing."""

    # Cache de imagens para performance (evita re-render)
    _image_cache = {}

    def __init__(self, parent, text="", command=None, color="#2CC985", **kwargs):
        self.width = 44
        self.height = 22
        self.scale = 4 if HAS_PIL else 1  # Supersampling 4x para AA
        self.text = text
        self.command = command
        self.color_on = color
        self.color_off = COLORS['switch_off']
        self.bg_color = parent.cget('bg')
        self.state = False
        self._photo = None  # Referência para evitar garbage collection

        # Frame container
        self.container = tk.Frame(parent, bg=self.bg_color)

        super().__init__(
            self.container,
            width=self.width,
            height=self.height,
            bg=self.bg_color,
            highlightthickness=0,
            **kwargs
        )

        # Empacota o Canvas dentro do container
        tk.Canvas.pack(self, side="left")

        # Label do texto
        if text:
            self.label = tk.Label(
                self.container, text=text,
                bg=self.bg_color, fg=COLORS['text'],
                font=("Segoe UI", 10)
            )
            self.label.pack(side="left", padx=(8, 0))
            self.label.bind("<Button-1>", self._toggle)

        self._draw()
        self.bind("<Button-1>", self._toggle)

    def pack(self, **kwargs):
        """Empacota o container (que contém Canvas + Label)."""
        self.container.pack(**kwargs)

    def grid(self, **kwargs):
        """Posiciona o container via grid."""
        self.container.grid(**kwargs)

    def place(self, **kwargs):
        """Posiciona o container via place."""
        self.container.place(**kwargs)

    def _get_cache_key(self):
        """Gera chave única para cache baseada no estado visual."""
        return (self.width, self.height, self.state, self.color_on, self.color_off, self.bg_color)

    def _draw(self):
        """Desenha o toggle com anti-aliasing via PIL."""
        self.delete("all")

        if HAS_PIL:
            self._draw_pil()
        else:
            self._draw_canvas()

    def _draw_pil(self):
        """Renderiza com PIL + supersampling para anti-aliasing suave."""
        cache_key = self._get_cache_key()

        # Verifica cache
        if cache_key in ToggleSwitch._image_cache:
            self._photo = ToggleSwitch._image_cache[cache_key]
            self.create_image(0, 0, anchor="nw", image=self._photo)
            return

        # Dimensões em alta resolução (4x)
        w, h = self.width * self.scale, self.height * self.scale
        padding = 3 * self.scale
        knob_size = h - padding * 2

        # Cria imagem RGBA (transparente)
        img = Image.new('RGBA', (w, h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        # Cor do fundo do toggle
        color = self.color_on if self.state else self.color_off

        # Desenha fundo arredondado (pill shape)
        # Círculo esquerdo
        draw.ellipse([0, 0, h, h], fill=color)
        # Círculo direito
        draw.ellipse([w - h, 0, w, h], fill=color)
        # Retângulo central
        draw.rectangle([h // 2, 0, w - h // 2, h], fill=color)

        # Posição do knob
        if self.state:
            knob_x = w - h + padding
        else:
            knob_x = padding

        # Desenha knob (círculo branco) com sombra sutil
        # Sombra
        shadow_offset = self.scale
        draw.ellipse(
            [knob_x + shadow_offset, padding + shadow_offset,
             knob_x + knob_size + shadow_offset, padding + knob_size + shadow_offset],
            fill=(0, 0, 0, 40)
        )
        # Knob
        draw.ellipse(
            [knob_x, padding, knob_x + knob_size, padding + knob_size],
            fill="#FFFFFF"
        )

        # Reduz para tamanho final com anti-aliasing (LANCZOS = melhor qualidade)
        img = img.resize((self.width, self.height), Image.LANCZOS)

        # Converte para PhotoImage
        self._photo = ImageTk.PhotoImage(img)

        # Salva no cache
        ToggleSwitch._image_cache[cache_key] = self._photo

        # Desenha no canvas
        self.create_image(0, 0, anchor="nw", image=self._photo)

    def _draw_canvas(self):
        """Fallback: desenha sem anti-aliasing (quando PIL não está disponível)."""
        color = self.color_on if self.state else self.color_off

        # Fundo arredondado
        self.create_oval(0, 0, self.height, self.height, fill=color, outline="")
        self.create_oval(self.width - self.height, 0, self.width, self.height, fill=color, outline="")
        self.create_rectangle(self.height // 2, 0, self.width - self.height // 2, self.height, fill=color, outline="")

        # Knob
        padding = 3
        knob_size = self.height - padding * 2
        if self.state:
            x = self.width - self.height + padding
        else:
            x = padding

        self.create_oval(x, padding, x + knob_size, padding + knob_size, fill="#FFFFFF", outline="")

    def _toggle(self, event=None):
        self.state = not self.state
        self._draw()
        if self.command:
            self.command()

    def get(self):
        return 1 if self.state else 0

    def select(self):
        self.state = True
        self._draw()

    def deselect(self):
        self.state = False
        self._draw()


# =============================================================================
# CUSTOM BUTTON
# =============================================================================
class ModernButton(tk.Label):
    """Botão moderno com hover effect."""

    def __init__(self, parent, text="", command=None, bg="#303030", fg="#FFFFFF",
                 hover_bg="#404040", font=("Segoe UI", 10), width=None, height=32, **kwargs):
        self.command = command
        self.bg_normal = bg
        self.bg_hover = hover_bg

        super().__init__(
            parent, text=text,
            bg=bg, fg=fg,
            font=font,
            cursor="hand2",
            **kwargs
        )

        if width:
            self.configure(width=width)

        # Padding interno
        self.configure(pady=6, padx=12)

        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Button-1>", self._on_click)

    def _on_enter(self, e):
        self.configure(bg=self.bg_hover)

    def _on_leave(self, e):
        self.configure(bg=self.bg_normal)

    def _on_click(self, e):
        if self.command:
            self.command()


# =============================================================================
# CUSTOM ENTRY
# =============================================================================
class ModernEntry(tk.Entry):
    """Entry estilizado."""

    def __init__(self, parent, width=10, **kwargs):
        super().__init__(
            parent,
            width=width,
            bg=COLORS['bg_input'],
            fg=COLORS['text'],
            insertbackground=COLORS['text'],
            font=("Segoe UI", 10),
            relief="flat",
            highlightthickness=1,
            highlightcolor=COLORS['accent_blue'],
            highlightbackground=COLORS['border'],
            **kwargs
        )
        self.configure(insertwidth=2)


# =============================================================================
# SEPARATOR
# =============================================================================
class Separator(tk.Frame):
    """Linha separadora horizontal."""

    def __init__(self, parent, **kwargs):
        super().__init__(parent, height=1, bg=COLORS['border'], **kwargs)


# =============================================================================
# CUSTOM TABVIEW (visual similar ao CTkTabview)
# =============================================================================
class CustomTabview(tk.Frame):
    """Tabview customizado com visual moderno similar ao CTkTabview."""

    def __init__(self, parent, command=None, **kwargs):
        super().__init__(parent, bg=COLORS['bg_main'], **kwargs)

        self.tabs = {}  # nome -> frame de conteúdo
        self.tab_buttons = {}  # nome -> botão da tab
        self.current_tab = None
        self.on_tab_change = command  # Callback quando tab muda

        # Frame para os botões das tabs (header)
        self.header_frame = tk.Frame(self, bg=COLORS['bg_main'])
        self.header_frame.pack(fill="x", padx=5, pady=(5, 0))

        # Container interno para os botões (permite scrolling visual se muitas tabs)
        self.buttons_container = tk.Frame(self.header_frame, bg=COLORS['bg_panel'])
        self.buttons_container.pack(fill="x")

        # Frame para o conteúdo das tabs
        self.content_frame = tk.Frame(self, bg=COLORS['bg_panel'])
        self.content_frame.pack(fill="both", expand=True, padx=5, pady=5)

    def add(self, name):
        """Adiciona uma nova tab e retorna o frame de conteúdo."""
        # Cria frame de conteúdo (inicialmente escondido)
        content = tk.Frame(self.content_frame, bg=COLORS['bg_main'])
        self.tabs[name] = content

        # Cria botão da tab
        btn = tk.Label(
            self.buttons_container,
            text=name,
            bg=COLORS['bg_panel'],
            fg=COLORS['text_dim'],
            font=("Verdana", 10),
            padx=12,
            pady=6,
            cursor="hand2"
        )
        btn.pack(side="left", padx=(0, 2))

        # Bind eventos
        btn.bind("<Button-1>", lambda e, n=name: self._select_tab(n))
        btn.bind("<Enter>", lambda e, b=btn, n=name: self._on_hover(b, n, True))
        btn.bind("<Leave>", lambda e, b=btn, n=name: self._on_hover(b, n, False))

        self.tab_buttons[name] = btn

        # Se for a primeira tab, seleciona ela
        if self.current_tab is None:
            self._select_tab(name)

        return content

    def _select_tab(self, name):
        """Seleciona uma tab pelo nome."""
        if name not in self.tabs:
            return

        # Esconde tab atual
        if self.current_tab and self.current_tab in self.tabs:
            self.tabs[self.current_tab].pack_forget()
            self.tab_buttons[self.current_tab].configure(
                bg=COLORS['bg_panel'],
                fg=COLORS['text_dim']
            )

        # Mostra nova tab
        self.current_tab = name
        self.tabs[name].pack(fill="both", expand=True, padx=10, pady=10)
        self.tab_buttons[name].configure(
            bg=COLORS['accent_blue'],
            fg="#FFFFFF"
        )

        # Callback para ajuste de altura
        if self.on_tab_change:
            # Agenda para próximo ciclo do event loop (após layout ser calculado)
            self.after(10, self.on_tab_change)

    def _on_hover(self, btn, name, entering):
        """Efeito hover nos botões de tab."""
        if name == self.current_tab:
            return  # Não muda se for a tab ativa

        if entering:
            btn.configure(bg=COLORS['bg_hover'], fg=COLORS['text'])
        else:
            btn.configure(bg=COLORS['bg_panel'], fg=COLORS['text_dim'])

    def get(self):
        """Retorna o nome da tab atual."""
        return self.current_tab

    def set(self, name):
        """Define a tab ativa pelo nome."""
        self._select_tab(name)

    def tab(self, name):
        """Retorna o frame de conteúdo de uma tab."""
        return self.tabs.get(name)


# =============================================================================
# COLLAPSIBLE STATS WIDGET
# =============================================================================
class CollapsibleStats(tk.Frame):
    """Widget de stats colapsável - mostra resumo compacto, expande para detalhes."""

    def __init__(self, parent, **kwargs):
        super().__init__(parent, bg=COLORS['bg_main'], highlightbackground=COLORS['border'],
                         highlightthickness=1, **kwargs)
        self.is_expanded = False

        # === SUMMARY (sempre visível) ===
        self.summary_frame = tk.Frame(self, bg=COLORS['bg_main'])
        self.summary_frame.pack(fill="x", padx=10, pady=6)

        # Stats compactos
        self.lbl_xp = tk.Label(self.summary_frame, text="45.2k xp/h",
                               bg=COLORS['bg_main'], fg=COLORS['text'],
                               font=("Segoe UI", 10, "bold"))
        self.lbl_xp.pack(side="left")

        tk.Label(self.summary_frame, text="•", bg=COLORS['bg_main'],
                 fg=COLORS['text_hint'], font=("Segoe UI", 10)).pack(side="left", padx=8)

        self.lbl_gold = tk.Label(self.summary_frame, text="15.4k gp",
                                 bg=COLORS['bg_main'], fg=COLORS['accent_gold'],
                                 font=("Segoe UI", 10, "bold"))
        self.lbl_gold.pack(side="left")

        tk.Label(self.summary_frame, text="•", bg=COLORS['bg_main'],
                 fg=COLORS['text_hint'], font=("Segoe UI", 10)).pack(side="left", padx=8)

        self.lbl_regen = tk.Label(self.summary_frame, text="Regen OK",
                                  bg=COLORS['bg_main'], fg=COLORS['accent_green'],
                                  font=("Segoe UI", 10))
        self.lbl_regen.pack(side="left")

        # Botão expand/collapse
        self.btn_toggle = tk.Label(self.summary_frame, text="▼",
                                   bg=COLORS['bg_main'], fg=COLORS['text_dim'],
                                   font=("Segoe UI", 10), cursor="hand2")
        self.btn_toggle.pack(side="right", padx=(10, 0))
        self.btn_toggle.bind("<Button-1>", self._toggle)
        self.btn_toggle.bind("<Enter>", lambda e: self.btn_toggle.configure(fg=COLORS['text']))
        self.btn_toggle.bind("<Leave>", lambda e: self.btn_toggle.configure(fg=COLORS['text_dim']))

        # === DETAILS (oculto por padrão) ===
        self.details_frame = tk.Frame(self, bg=COLORS['bg_main'])
        # NÃO pack - começa oculto

        self._build_details()

    def _build_details(self):
        """Constrói o conteúdo expandido."""
        inner = self.details_frame

        # Separador
        Separator(inner).pack(fill="x", padx=10, pady=(0, 8))

        # EXP detalhado
        exp_frame = tk.Frame(inner, bg=COLORS['bg_main'])
        exp_frame.pack(fill="x", padx=10)

        tk.Label(exp_frame, text="12.5k left", bg=COLORS['bg_main'], fg=COLORS['text_dim'],
                 font=("Segoe UI", 10)).pack(side="left")
        tk.Label(exp_frame, text="•", bg=COLORS['bg_main'], fg=COLORS['text_hint'],
                 font=("Segoe UI", 10)).pack(side="left", padx=8)
        tk.Label(exp_frame, text="ETA 00:16", bg=COLORS['bg_main'], fg=COLORS['text_dim'],
                 font=("Segoe UI", 10)).pack(side="left")

        # Regen + Food
        res_frame = tk.Frame(inner, bg=COLORS['bg_main'])
        res_frame.pack(fill="x", padx=10, pady=(6, 0))

        tk.Label(res_frame, text="🍖 02:45", bg=COLORS['bg_main'], fg=COLORS['text'],
                 font=("Segoe UI", 10, "bold")).pack(side="left")
        tk.Label(res_frame, text="Food: 127", bg=COLORS['bg_main'], fg=COLORS['text_dim'],
                 font=("Segoe UI", 10)).pack(side="left", padx=(12, 0))

        tk.Label(res_frame, text="1.2k gp/h", bg=COLORS['bg_main'], fg=COLORS['text_dim'],
                 font=("Segoe UI", 10)).pack(side="right")

        # Skills
        skills_data = [
            ("Sword", "85", "12m/%", "ETA 01:42", COLORS['accent_blue']),
            ("Shield", "72", "8m/%", "ETA 02:15", COLORS['accent_blue']),
            ("ML", "45", "25m/%", "ETA 04:30", COLORS['accent_purple']),
        ]

        for name, val, rate, eta, color in skills_data:
            skill_frame = tk.Frame(inner, bg=COLORS['bg_main'])
            skill_frame.pack(fill="x", padx=10, pady=(6, 0))

            tk.Label(skill_frame, text=f"{name}:", bg=COLORS['bg_main'], fg=COLORS['text'],
                     font=("Segoe UI", 10)).pack(side="left")
            tk.Label(skill_frame, text=val, bg=COLORS['bg_main'], fg=color,
                     font=("Segoe UI", 10, "bold")).pack(side="left", padx=(6, 0))

            tk.Label(skill_frame, text=eta, bg=COLORS['bg_main'], fg=COLORS['text_dim'],
                     font=("Segoe UI", 9)).pack(side="right")
            tk.Label(skill_frame, text=rate, bg=COLORS['bg_main'], fg=COLORS['text_dim'],
                     font=("Segoe UI", 9)).pack(side="right", padx=(0, 12))

        # Padding inferior
        tk.Frame(inner, bg=COLORS['bg_main'], height=6).pack(fill="x")

    def _toggle(self, event=None):
        """Alterna entre expandido e colapsado."""
        self.is_expanded = not self.is_expanded

        if self.is_expanded:
            self.details_frame.pack(fill="x")
            self.btn_toggle.configure(text="▲")
        else:
            self.details_frame.pack_forget()
            self.btn_toggle.configure(text="▼")

        # Callback para resize da janela (se existir)
        if hasattr(self, 'on_toggle') and self.on_toggle:
            self.on_toggle()

    def set_values(self, xp_rate="--", gold="--", regen_status="--"):
        """Atualiza os valores do resumo."""
        self.lbl_xp.configure(text=xp_rate)
        self.lbl_gold.configure(text=gold)
        self.lbl_regen.configure(text=regen_status)


# =============================================================================
# MAIN WINDOW
# =============================================================================
class MockMainWindow:
    """Janela principal com visual moderno."""

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Molodoy Bot Pro")
        self.root.geometry("320x320")  # Menor altura inicial (stats compacto)
        self.root.configure(bg=COLORS['bg_main'])
        self.root.resizable(True, True)

        # Configura estilo ttk
        self._configure_styles()
        self._create_widgets()

    def _configure_styles(self):
        style = ttk.Style()
        style.theme_use('clam')

        # Combobox
        style.configure("Modern.TCombobox",
                        fieldbackground=COLORS['bg_input'],
                        background=COLORS['bg_panel'],
                        foreground=COLORS['text'],
                        arrowcolor=COLORS['text'],
                        borderwidth=0)
        style.map("Modern.TCombobox",
                  fieldbackground=[("readonly", COLORS['bg_input'])],
                  selectbackground=[("readonly", COLORS['bg_input'])],
                  selectforeground=[("readonly", COLORS['text'])])

    def _create_widgets(self):
        # Main container com padding
        main = tk.Frame(self.root, bg=COLORS['bg_main'])
        main.pack(fill="both", expand=True, padx=12, pady=8)

        self._create_header(main)
        self._create_controls(main)
        self._create_utility_toggles(main)

        # Stats colapsável (substitui _create_stats + _create_graph_button)
        self.stats_widget = CollapsibleStats(main)
        self.stats_widget.pack(fill="x", pady=(0, 8))
        self.stats_widget.on_toggle = self._auto_resize

        self._create_status_panel(main)

    def _create_header(self, parent):
        """Header com status + botões em linhas separadas."""
        frame = tk.Frame(parent, bg=COLORS['bg_main'])
        frame.pack(fill="x", pady=(0, 8))

        # === LINHA 1: Status de conexão ===
        status_line = tk.Frame(frame, bg=COLORS['bg_main'])
        status_line.pack(fill="x", pady=(0, 6))

        self.lbl_connection = tk.Label(
            status_line, text="● Conectado",
            bg=COLORS['bg_main'], fg=COLORS['accent_green'],
            font=("Segoe UI", 11, "bold")
        )
        self.lbl_connection.pack(side="left")

        # === LINHA 2: Botões ===
        btn_line = tk.Frame(frame, bg=COLORS['bg_main'])
        btn_line.pack(fill="x")

        # Config button
        ModernButton(
            btn_line, text="⚙ Config",
            bg=COLORS['bg_panel'],
            hover_bg=COLORS['bg_hover'],
            font=("Segoe UI", 10, "bold"),
            command=self._open_settings
        ).pack(side="left")

        # Pause button
        ModernButton(
            btn_line, text="⏸ Pausar",
            bg=COLORS['bg_panel'],
            hover_bg=COLORS['bg_hover'],
            font=("Segoe UI", 10)
        ).pack(side="left", padx=(6, 0))

        # Raio-X button (right)
        ModernButton(
            btn_line, text="👁 Raio-X",
            bg=COLORS['bg_panel'],
            hover_bg=COLORS['accent_blue'],
            font=("Segoe UI", 10)
        ).pack(side="right")

    def _create_controls(self, parent):
        """Painel de switches dos módulos."""
        frame = tk.Frame(parent, bg=COLORS['bg_panel'])
        frame.pack(fill="x", pady=(0, 8))

        # Padding interno
        inner = tk.Frame(frame, bg=COLORS['bg_panel'])
        inner.pack(fill="x", padx=16, pady=12)

        # Grid 2x4
        inner.grid_columnconfigure(0, weight=1)
        inner.grid_columnconfigure(1, weight=1)

        switches_data = [
            ("Trainer", True, COLORS['accent_green'], 0, 0),
            ("Alarm", False, COLORS['accent_green'], 0, 1),
            ("Auto Loot", True, COLORS['accent_green'], 1, 0),
            ("Auto Fisher", False, COLORS['accent_green'], 1, 1),
            ("Runemaker", False, COLORS['accent_purple'], 2, 0),
            ("Cavebot", False, COLORS['accent_green'], 2, 1),
            ("Healer", True, COLORS['accent_red'], 3, 0),
        ]

        self.switches = {}
        for text, state, color, row, col in switches_data:
            container = tk.Frame(inner, bg=COLORS['bg_panel'])
            container.grid(row=row, column=col, sticky="w", pady=4)

            switch = ToggleSwitch(container, text=text, color=color)
            switch.pack(side="left")
            if state:
                switch.select()
            self.switches[text.lower().replace(" ", "_")] = switch

    def _create_utility_toggles(self, parent):
        """Toggles utilitários."""
        frame = tk.Frame(parent, bg=COLORS['bg_dark'])
        frame.pack(fill="x", pady=(0, 8))

        inner = tk.Frame(frame, bg=COLORS['bg_dark'])
        inner.pack(fill="x", padx=16, pady=8)

        # Tocha
        switch_torch = ToggleSwitch(inner, text="Tocha", color=COLORS['accent_orange'])
        switch_torch.pack(side="left")

        # Light
        switch_light = ToggleSwitch(inner, text="Light", color=COLORS['accent_orange'])
        switch_light.pack(side="left", padx=(20, 0))
        switch_light.select()

        # Spear + Entry
        spear_frame = tk.Frame(inner, bg=COLORS['bg_dark'])
        spear_frame.pack(side="left", padx=(20, 0))

        switch_spear = ToggleSwitch(spear_frame, text="Spear", color=COLORS['accent_orange'])
        switch_spear.pack(side="left")

        entry_spear = ModernEntry(spear_frame, width=3)
        entry_spear.pack(side="left", padx=(8, 0), ipady=2)
        entry_spear.insert(0, "3")

    def _create_status_panel(self, parent):
        """Painel de status."""
        frame = tk.Frame(parent, bg=COLORS['bg_dark'], highlightbackground=COLORS['border'],
                         highlightthickness=1)
        frame.pack(side="bottom", fill="x")

        inner = tk.Frame(frame, bg=COLORS['bg_dark'])
        inner.pack(fill="x", padx=10, pady=8)

        # Status items
        statuses = [
            ("⚔️", "Trainer", "Attacking Rat", "2.3s"),
            ("💚", "Healer", "Monitoring HP", "92%"),
        ]

        for icon, module, action, detail in statuses:
            row = tk.Frame(inner, bg=COLORS['bg_dark'])
            row.pack(fill="x", pady=2)

            tk.Label(row, text=f"{icon} {module}:", bg=COLORS['bg_dark'], fg=COLORS['text_dim'],
                     font=("Consolas", 10)).pack(side="left")
            tk.Label(row, text=action, bg=COLORS['bg_dark'], fg=COLORS['text'],
                     font=("Consolas", 10)).pack(side="left", padx=(6, 0))
            tk.Label(row, text=f"({detail})", bg=COLORS['bg_dark'], fg=COLORS['text_hint'],
                     font=("Consolas", 9)).pack(side="left", padx=(6, 0))

    def _auto_resize(self):
        """Redimensiona a janela baseado no conteúdo."""
        self.root.update_idletasks()
        # Calcula altura necessária
        height = self.root.winfo_reqheight()
        self.root.geometry(f"320x{height}")

    def _open_settings(self):
        MockSettingsWindow(self.root)

    def run(self):
        self.root.mainloop()


# =============================================================================
# ESTILOS UI (correspondente ao settings_window.py original)
# =============================================================================
UI_STYLES = {
    'H1': {'font': ("Verdana", 11, "bold"), 'fg': "#FFFFFF"},
    'BODY': {'font': ("Verdana", 10), 'fg': "#CCCCCC"},
    'HINT': {'font': ("Verdana", 8), 'fg': "#555555"},
    'INPUT_WIDTH': 50,
    'COMBO_WIDTH': 130,
    'PAD_SECTION': 10,
    'PAD_ITEM': 2,
    'PAD_INDENT': 20,
}


# =============================================================================
# SETTINGS WINDOW
# =============================================================================
class MockSettingsWindow:
    """Janela de configurações - réplica fiel do settings_window.py."""

    def __init__(self, parent):
        self.window = tk.Toplevel(parent)
        self.window.title("Configurações")
        self.window.geometry("480x520")
        self.window.configure(bg=COLORS['bg_main'])
        self.window.attributes("-topmost", True)
        self.window.minsize(480, 520)
        self._create_widgets()

    def _create_widgets(self):
        # Usando CustomTabview ao invés de ttk.Notebook
        self.tabview = CustomTabview(self.window, command=self._adjust_window_height)
        self.tabview.pack(fill="both", expand=True, padx=5, pady=5)

        # Tabs na mesma ordem do original
        tab_names = ["Geral", "Trainer", "Alarme", "Alvos", "Loot", "Fisher", "Rune", "Healer", "Cavebot"]

        self.tabs = {}
        for name in tab_names:
            self.tabs[name] = self.tabview.add(name)

        # Builders
        builders = {
            "Geral": self._build_tab_geral,
            "Trainer": self._build_tab_trainer,
            "Alarme": self._build_tab_alarme,
            "Alvos": self._build_tab_alvos,
            "Loot": self._build_tab_loot,
            "Fisher": self._build_tab_fisher,
            "Rune": self._build_tab_rune,
            "Healer": self._build_tab_healer,
            "Cavebot": self._build_tab_cavebot,
        }

        for name, builder in builders.items():
            builder(self.tabs[name])

        # Ajusta altura inicial após construir todas as tabs
        self.window.after(50, self._adjust_window_height)

    def _adjust_window_height(self):
        """Ajusta a altura da janela baseado no conteúdo da tab atual."""
        current_tab = self.tabview.get()
        if not current_tab or current_tab not in self.tabs:
            return

        # Força atualização do layout
        self.window.update_idletasks()

        # Obtém o frame de conteúdo da tab atual
        tab_frame = self.tabs[current_tab]

        # Calcula altura necessária do conteúdo
        tab_frame.update_idletasks()
        content_height = tab_frame.winfo_reqheight()

        # Altura do header das tabs (botões)
        header_height = self.tabview.header_frame.winfo_reqheight()

        # Margens e padding extras
        padding = 60  # Margem para bordas e padding do tabview

        # Altura total necessária
        total_height = content_height + header_height + padding

        # Define limites min/max
        min_height = 400
        max_height = 700
        final_height = max(min_height, min(total_height, max_height))

        # Obtém largura atual
        current_width = self.window.winfo_width()
        if current_width < 480:
            current_width = 480

        # Aplica nova geometria
        self.window.geometry(f"{current_width}x{final_height}")

    def _create_section(self, parent, title):
        """Cria uma seção com título (H1 style)."""
        frame = tk.Frame(parent, bg=COLORS['bg_main'])
        frame.pack(fill="x", pady=(UI_STYLES['PAD_SECTION'], 5))

        tk.Label(frame, text=title, bg=COLORS['bg_main'],
                 **UI_STYLES['H1']).pack(anchor="w", padx=10)

        return frame

    def _create_grid_frame(self, parent):
        """Cria frame com grid 2 colunas (Label | Input)."""
        f = tk.Frame(parent, bg=COLORS['bg_main'])
        f.pack(fill="x", pady=UI_STYLES['PAD_SECTION'], padx=10)
        f.grid_columnconfigure(0, weight=1)
        f.grid_columnconfigure(1, weight=2)
        return f

    def _create_field_row(self, parent, label, widget_type="entry", width=15, values=None, row=0):
        """Cria uma linha de campo em grid."""
        tk.Label(parent, text=label, bg=COLORS['bg_main'],
                 **UI_STYLES['BODY']).grid(row=row, column=0, sticky="e", padx=10, pady=UI_STYLES['PAD_ITEM'])

        if widget_type == "entry":
            widget = ModernEntry(parent, width=width)
            widget.grid(row=row, column=1, sticky="w", pady=UI_STYLES['PAD_ITEM'])
        elif widget_type == "combo":
            widget = ttk.Combobox(parent, values=values, state="readonly", width=width,
                                   font=UI_STYLES['BODY']['font'])
            widget.grid(row=row, column=1, sticky="w", pady=UI_STYLES['PAD_ITEM'])
            if values:
                widget.set(values[0])
        else:
            widget = None

        return widget

    def _create_hint(self, parent, text):
        """Cria texto de dica (HINT style)."""
        tk.Label(parent, text=f"↳ {text}", bg=COLORS['bg_main'],
                 **UI_STYLES['HINT']).pack(anchor="w", padx=UI_STYLES['PAD_INDENT'])

    def _create_save_button(self, parent, text="Salvar"):
        """Botão de salvar no rodapé."""
        btn = tk.Label(
            parent, text=text,
            bg=COLORS['accent_green'], fg=COLORS['text'],
            font=("Verdana", 11, "bold"),
            cursor="hand2", pady=8
        )
        btn.pack(side="bottom", fill="x", padx=20, pady=10)

        btn.bind("<Enter>", lambda e: btn.configure(bg="#25A873"))
        btn.bind("<Leave>", lambda e: btn.configure(bg=COLORS['accent_green']))

    def _build_tab_geral(self, tab):
        """Aba Geral - réplica do original."""
        # Grid frame para campos
        grid = self._create_grid_frame(tab)

        # Vocação
        self._create_field_row(grid, "Vocação (Regen):", "combo",
                               values=["Knight", "Paladin", "Sorcerer", "Druid", "None"], row=0)

        # Telegram
        self._create_field_row(grid, "Telegram Chat ID:", "entry", width=18, row=1)

        # Hint
        tk.Label(grid, text="↳ Recebe alertas de PK e Pausa no celular.",
                 bg=COLORS['bg_main'], **UI_STYLES['HINT']).grid(
            row=2, column=0, columnspan=2, sticky="e", padx=60, pady=(0, 5))

        # Pasta do Cliente
        tk.Label(grid, text="Pasta do Cliente:", bg=COLORS['bg_main'],
                 **UI_STYLES['BODY']).grid(row=3, column=0, sticky="e", padx=10)

        path_frame = tk.Frame(grid, bg=COLORS['bg_main'])
        path_frame.grid(row=3, column=1, sticky="w")

        entry_path = ModernEntry(path_frame, width=22)
        entry_path.pack(side="left", ipady=2)
        entry_path.insert(0, "C:/Tibia")

        ModernButton(path_frame, text="...", bg=COLORS['bg_panel'],
                     hover_bg=COLORS['bg_hover'], font=("Verdana", 10)).pack(side="left", padx=5)

        # Opções
        self._create_section(tab, "Opções")

        switches_frame = tk.Frame(tab, bg=COLORS['bg_main'])
        switches_frame.pack(fill="x", padx=UI_STYLES['PAD_INDENT'])

        for text, state, hint in [
            ("Exibir ID ao dar Look", False, None),
            ("Responder via IA", False, None),
            ("Mostrar Console Log", True, None),
            ("Ativar Logging Detalhado", False, "Desabilitar melhora performance em VPS.")
        ]:
            row = tk.Frame(switches_frame, bg=COLORS['bg_main'])
            row.pack(fill="x", pady=3)
            switch = ToggleSwitch(row, text=text, color=COLORS['accent_blue'])
            switch.pack(side="left")
            if state:
                switch.select()
            if hint:
                tk.Label(switches_frame, text=f"    ↳ ⚠️ {hint}",
                         bg=COLORS['bg_main'], **UI_STYLES['HINT']).pack(anchor="w")

        # Pausas AFK
        self._create_section(tab, "Pausas AFK Aleatórias")

        afk_frame = tk.Frame(tab, bg=COLORS['bg_main'])
        afk_frame.pack(fill="x", padx=UI_STYLES['PAD_INDENT'])

        switch_afk = ToggleSwitch(afk_frame, text="Ativar Pausas AFK", color=COLORS['accent_purple'])
        switch_afk.pack(anchor="w")

        afk_opts = tk.Frame(tab, bg=COLORS['bg_main'])
        afk_opts.pack(fill="x", padx=30, pady=5)

        tk.Label(afk_opts, text="Intervalo (min):", bg=COLORS['bg_main'],
                 **UI_STYLES['BODY']).pack(side="left")
        entry_interval = ModernEntry(afk_opts, width=5)
        entry_interval.pack(side="left", padx=5, ipady=2)
        entry_interval.insert(0, "10")

        tk.Label(afk_opts, text="Duração (seg):", bg=COLORS['bg_main'],
                 **UI_STYLES['BODY']).pack(side="left", padx=(15, 0))
        entry_duration = ModernEntry(afk_opts, width=5)
        entry_duration.pack(side="left", padx=5, ipady=2)
        entry_duration.insert(0, "30")

        self._create_hint(tab, "Pausa todos os módulos com 50% de variância.")

        self._create_save_button(tab, "Salvar Geral")

    def _build_tab_trainer(self, tab):
        """Aba Trainer - réplica do original."""
        # Delay de Ataque
        self._create_section(tab, "Delay de Ataque (s)")

        delay_frame = tk.Frame(tab, bg=COLORS['bg_main'])
        delay_frame.pack(fill="x", padx=10, pady=5)

        tk.Label(delay_frame, text="Min:", bg=COLORS['bg_main'],
                 **UI_STYLES['BODY']).pack(side="left")
        entry_min = ModernEntry(delay_frame, width=5)
        entry_min.pack(side="left", padx=5, ipady=2)
        entry_min.insert(0, "1.0")

        tk.Label(delay_frame, text="Max:", bg=COLORS['bg_main'],
                 **UI_STYLES['BODY']).pack(side="left", padx=(15, 0))
        entry_max = ModernEntry(delay_frame, width=5)
        entry_max.pack(side="left", padx=5, ipady=2)
        entry_max.insert(0, "2.0")

        self._create_hint(tab, "Tempo de reação para começar a atacar")

        # Distância
        self._create_section(tab, "Distância (SQM)")

        range_frame = tk.Frame(tab, bg=COLORS['bg_main'])
        range_frame.pack(fill="x", padx=10, pady=5)

        entry_range = ModernEntry(range_frame, width=5)
        entry_range.pack(side="left", ipady=2)
        entry_range.insert(0, "1")

        tk.Label(range_frame, text="(Distância mínima para começar a atacar alvos)",
                 bg=COLORS['bg_main'], **UI_STYLES['HINT']).pack(side="left", padx=10)

        # Lógica de Alvo
        self._create_section(tab, "Lógica de Alvo")

        logic_frame = tk.Frame(tab, bg=COLORS['bg_main'])
        logic_frame.pack(fill="x", padx=10)

        switch_ignore = ToggleSwitch(logic_frame, text="Ignorar 1º Monstro",
                                      color=COLORS['accent_orange'])
        switch_ignore.pack(anchor="w", pady=3)

        switch_ks = ToggleSwitch(logic_frame, text="Ativar Anti Kill-Steal",
                                  color=COLORS['accent_red'])
        switch_ks.pack(anchor="w", pady=3)
        switch_ks.select()
        self._create_hint(tab, "Evita atacar criaturas mais próximas de outros players.")

        switch_chase = ToggleSwitch(logic_frame, text="Walker Chase Mode",
                                     color=COLORS['accent_blue'])
        switch_chase.pack(anchor="w", pady=3)
        self._create_hint(tab, "Usa walker A* para perseguir alvos.")

        # Aimbot
        self._create_section(tab, "Aimbot (Runas)")

        aimbot_frame = tk.Frame(tab, bg=COLORS['bg_main'])
        aimbot_frame.pack(fill="x", padx=10)

        switch_aimbot = ToggleSwitch(aimbot_frame, text="Ativar Aimbot",
                                      color=COLORS['accent_red'])
        switch_aimbot.pack(anchor="w", pady=3)

        aimbot_opts = tk.Frame(tab, bg=COLORS['bg_main'])
        aimbot_opts.pack(fill="x", padx=UI_STYLES['PAD_INDENT'], pady=5)

        tk.Label(aimbot_opts, text="Runa:", bg=COLORS['bg_main'],
                 **UI_STYLES['BODY']).pack(side="left")
        combo_rune = ttk.Combobox(aimbot_opts, values=["SD", "HMM", "GFB", "EXPLO"],
                                   width=6, state="readonly", font=("Verdana", 9))
        combo_rune.pack(side="left", padx=5)
        combo_rune.set("SD")

        tk.Label(aimbot_opts, text="Hotkey:", bg=COLORS['bg_main'],
                 **UI_STYLES['BODY']).pack(side="left", padx=(15, 0))
        combo_hk = ttk.Combobox(aimbot_opts, values=["F5", "F6", "F7", "F8", "F9"],
                                 width=5, state="readonly", font=("Verdana", 9))
        combo_hk.pack(side="left", padx=5)
        combo_hk.set("F5")

        self._create_save_button(tab, "Salvar Trainer")

    def _build_tab_alarme(self, tab):
        """Aba Alarme - réplica do original."""
        # Detecção Visual
        self._create_section(tab, "Detecção Visual")

        vis_frame = tk.Frame(tab, bg=COLORS['bg_main'])
        vis_frame.pack(fill="x", padx=UI_STYLES['PAD_INDENT'])

        switch_players = ToggleSwitch(vis_frame, text="Alarme para Players",
                                       color=COLORS['accent_red'])
        switch_players.pack(anchor="w", pady=2)
        switch_players.select()

        switch_creatures = ToggleSwitch(vis_frame, text="Alarme para Criaturas",
                                         color=COLORS['accent_orange'])
        switch_creatures.pack(anchor="w", pady=2)
        switch_creatures.select()

        # Distância
        grid = self._create_grid_frame(tab)

        tk.Label(grid, text="Distância (SQM):", bg=COLORS['bg_main'],
                 **UI_STYLES['BODY']).grid(row=0, column=0, sticky="e", padx=10)
        combo_dist = ttk.Combobox(grid, values=["1 SQM", "3 SQM", "5 SQM", "8 SQM (Padrão)", "Tela Toda"],
                                   width=15, state="readonly", font=("Verdana", 10))
        combo_dist.grid(row=0, column=1, sticky="w")
        combo_dist.set("8 SQM (Padrão)")

        tk.Label(grid, text="Monitorar Andares:", bg=COLORS['bg_main'],
                 **UI_STYLES['BODY']).grid(row=1, column=0, sticky="e", padx=10)
        combo_floor = ttk.Combobox(grid, values=["Padrão", "Superior (+1)", "Inferior (-1)", "Todos (Raio-X)"],
                                    width=15, state="readonly", font=("Verdana", 10))
        combo_floor.grid(row=1, column=1, sticky="w")
        combo_floor.set("Padrão")

        # HP Alarm
        self._create_section(tab, "Monitorar Vida (HP)")

        hp_frame = tk.Frame(tab, bg=COLORS['bg_main'])
        hp_frame.pack(fill="x", padx=UI_STYLES['PAD_INDENT'])

        switch_hp = ToggleSwitch(hp_frame, text="Alarme HP Baixo", color=COLORS['accent_red'])
        switch_hp.pack(side="left")

        tk.Label(hp_frame, text="dispara se <", bg=COLORS['bg_main'],
                 **UI_STYLES['BODY']).pack(side="left", padx=(15, 0))
        entry_hp = ModernEntry(hp_frame, width=4)
        entry_hp.pack(side="left", padx=5, ipady=2)
        entry_hp.insert(0, "50")
        tk.Label(hp_frame, text="%", bg=COLORS['bg_main'],
                 **UI_STYLES['BODY']).pack(side="left")

        # Mana GM Detection
        self._create_section(tab, "Detecção de Mana GM")

        gm_frame = tk.Frame(tab, bg=COLORS['bg_main'])
        gm_frame.pack(fill="x", padx=UI_STYLES['PAD_INDENT'])

        switch_gm = ToggleSwitch(gm_frame, text="Detectar mana artificial (GM test)",
                                  color=COLORS['accent_purple'])
        switch_gm.pack(anchor="w")

        # Chat
        self._create_section(tab, "Mensagens (Chat)")

        chat_frame = tk.Frame(tab, bg=COLORS['bg_main'])
        chat_frame.pack(fill="x", padx=UI_STYLES['PAD_INDENT'])

        switch_chat = ToggleSwitch(chat_frame, text="Alarme de Msg Nova",
                                    color=COLORS['accent_orange'])
        switch_chat.pack(anchor="w")

        # Movimento
        self._create_section(tab, "Movimento Inesperado")

        mov_frame = tk.Frame(tab, bg=COLORS['bg_main'])
        mov_frame.pack(fill="x", padx=UI_STYLES['PAD_INDENT'])

        switch_mov = ToggleSwitch(mov_frame, text="Alarme de Movimento",
                                   color=COLORS['accent_red'])
        switch_mov.pack(anchor="w", pady=2)

        switch_keep = ToggleSwitch(mov_frame, text="Manter Posição (retornar ao ponto)",
                                    color=COLORS['accent_orange'])
        switch_keep.pack(anchor="w", pady=2)

        self._create_save_button(tab, "Salvar Alarme")

    def _build_tab_alvos(self, tab):
        """Aba Alvos - listas de targets e safe."""
        # Targets
        self._create_section(tab, "Alvos (Target List)")

        txt_targets = tk.Text(tab, height=5, bg=COLORS['bg_input'], fg=COLORS['text'],
                              font=("Consolas", 10), relief="flat", highlightthickness=1,
                              highlightbackground=COLORS['border'], insertbackground=COLORS['text'])
        txt_targets.pack(fill="x", padx=10, pady=5)
        txt_targets.insert("1.0", "Rat\nCave Rat\nRotworm")

        # Safe List
        self._create_section(tab, "Segura (Safe List)")

        txt_safe = tk.Text(tab, height=7, bg=COLORS['bg_input'], fg=COLORS['text'],
                           font=("Consolas", 10), relief="flat", highlightthickness=1,
                           highlightbackground=COLORS['border'], insertbackground=COLORS['text'])
        txt_safe.pack(fill="x", padx=10, pady=5)
        txt_safe.insert("1.0", "Deer\nRabbit\nBug\nWasp\nSnake")

        self._create_save_button(tab, "Salvar Listas")

    def _build_tab_loot(self, tab):
        """Aba Loot - configuração de auto loot."""
        self._create_section(tab, "Configuração de BPs")

        grid = self._create_grid_frame(tab)

        # Minhas BPs
        tk.Label(grid, text="Minhas BPs (Não lootear):", bg=COLORS['bg_main'],
                 **UI_STYLES['BODY']).grid(row=0, column=0, sticky="e", padx=10)
        entry_bps = ModernEntry(grid, width=5)
        entry_bps.grid(row=0, column=1, sticky="w")
        entry_bps.insert(0, "2")

        # Índice Destino
        tk.Label(grid, text="Índice Destino:", bg=COLORS['bg_main'],
                 **UI_STYLES['BODY']).grid(row=1, column=0, sticky="e", padx=10)

        dest_frame = tk.Frame(grid, bg=COLORS['bg_main'])
        dest_frame.grid(row=1, column=1, sticky="w")

        entry_dest = ModernEntry(dest_frame, width=5)
        entry_dest.pack(side="left", ipady=2)
        entry_dest.insert(0, "0")

        tk.Label(dest_frame, text="(0=primeira BP, 1=segunda, etc)",
                 bg=COLORS['bg_main'], **UI_STYLES['HINT']).pack(side="left", padx=10)

        # Opções
        opts_frame = tk.Frame(tab, bg=COLORS['bg_main'])
        opts_frame.pack(fill="x", padx=10, pady=10)

        switch_drop = ToggleSwitch(opts_frame, text="Jogar Food no chão se Full",
                                    color=COLORS['accent_orange'])
        switch_drop.pack(anchor="center", pady=3)

        switch_eat = ToggleSwitch(opts_frame, text="Comer Food automaticamente",
                                   color=COLORS['accent_green'])
        switch_eat.pack(anchor="center", pady=3)
        switch_eat.select()

        self._create_save_button(tab, "Salvar Loot")

    def _build_tab_fisher(self, tab):
        """Aba Fisher - configuração de pesca."""
        grid = self._create_grid_frame(tab)

        # Min Cap
        tk.Label(grid, text="Min Cap:", bg=COLORS['bg_main'],
                 **UI_STYLES['BODY']).grid(row=0, column=0, sticky="e", padx=10)
        entry_cap = ModernEntry(grid, width=6)
        entry_cap.grid(row=0, column=1, sticky="w")
        entry_cap.insert(0, "10.0")

        # Switches
        switches_frame = tk.Frame(tab, bg=COLORS['bg_main'])
        switches_frame.pack(fill="x", padx=UI_STYLES['PAD_INDENT'], pady=10)

        switch_cap = ToggleSwitch(switches_frame, text="Pausar se Cap Baixa",
                                   color=COLORS['accent_orange'])
        switch_cap.pack(anchor="w", pady=3)
        switch_cap.select()

        switch_fatigue = ToggleSwitch(switches_frame, text="Simular Fadiga Humana",
                                       color=COLORS['accent_orange'])
        switch_fatigue.pack(anchor="w", pady=3)
        switch_fatigue.select()
        self._create_hint(tab, "Cria pausas e lentidão progressiva.")

        switch_eat = ToggleSwitch(switches_frame, text="Auto-Comer (Fishing)",
                                   color=COLORS['accent_orange'])
        switch_eat.pack(anchor="w", pady=3)
        self._create_hint(tab, "Tenta comer a cada 2s até ficar full.")

        self._create_save_button(tab, "Salvar Fisher")

    def _build_tab_rune(self, tab):
        """Aba Rune - configuração de runemaker."""
        # Crafting
        craft_frame = tk.Frame(tab, bg=COLORS['bg_panel'])
        craft_frame.pack(fill="x", padx=5, pady=5)

        tk.Label(craft_frame, text="⚙️ Crafting", bg=COLORS['bg_panel'],
                 **UI_STYLES['H1']).pack(anchor="w", padx=10, pady=5)

        craft_opts = tk.Frame(craft_frame, bg=COLORS['bg_panel'])
        craft_opts.pack(fill="x", padx=10, pady=5)

        tk.Label(craft_opts, text="Mana:", bg=COLORS['bg_panel'],
                 **UI_STYLES['BODY']).pack(side="left")
        entry_mana = ModernEntry(craft_opts, width=5)
        entry_mana.pack(side="left", padx=5, ipady=2)
        entry_mana.insert(0, "300")

        tk.Label(craft_opts, text="Key:", bg=COLORS['bg_panel'],
                 **UI_STYLES['BODY']).pack(side="left", padx=(15, 0))
        entry_key = ModernEntry(craft_opts, width=4)
        entry_key.pack(side="left", padx=5, ipady=2)
        entry_key.insert(0, "F1")

        tk.Label(craft_opts, text="Mão:", bg=COLORS['bg_panel'],
                 **UI_STYLES['BODY']).pack(side="left", padx=(15, 0))
        combo_hand = ttk.Combobox(craft_opts, values=["DIREITA", "ESQUERDA", "AMBAS"],
                                   width=9, state="readonly", font=("Verdana", 9))
        combo_hand.pack(side="left", padx=5)
        combo_hand.set("DIREITA")

        # Anti-PK
        move_frame = tk.Frame(tab, bg=COLORS['bg_panel'])
        move_frame.pack(fill="x", padx=5, pady=5)

        tk.Label(move_frame, text="🚨 Anti-PK / Movimento", bg=COLORS['bg_panel'],
                 **UI_STYLES['H1']).pack(anchor="w", padx=10, pady=5)

        move_opts = tk.Frame(move_frame, bg=COLORS['bg_panel'])
        move_opts.pack(fill="x", padx=10, pady=5)

        switch_flee = ToggleSwitch(move_opts, text="Fugir para Safe", color=COLORS['accent_red'])
        switch_flee.pack(anchor="w")

        # Posições
        pos_frame = tk.Frame(move_frame, bg=COLORS['bg_panel'])
        pos_frame.pack(fill="x", padx=10, pady=5)

        ModernButton(pos_frame, text="Set Work", bg=COLORS['bg_input'],
                     hover_bg=COLORS['bg_hover'], font=("Verdana", 9)).pack(side="left")
        tk.Label(pos_frame, text="(0, 0, 0)", bg=COLORS['bg_panel'],
                 **UI_STYLES['HINT']).pack(side="left", padx=10)

        ModernButton(pos_frame, text="Set Safe", bg=COLORS['bg_input'],
                     hover_bg=COLORS['bg_hover'], font=("Verdana", 9)).pack(side="left", padx=(20, 0))
        tk.Label(pos_frame, text="(0, 0, 0)", bg=COLORS['bg_panel'],
                 **UI_STYLES['HINT']).pack(side="left", padx=10)

        # Extras
        extras_frame = tk.Frame(tab, bg=COLORS['bg_panel'])
        extras_frame.pack(fill="x", padx=5, pady=5)

        tk.Label(extras_frame, text="Outros", bg=COLORS['bg_panel'],
                 **UI_STYLES['H1']).pack(anchor="w", padx=10, pady=5)

        extras_opts = tk.Frame(extras_frame, bg=COLORS['bg_panel'])
        extras_opts.pack(fill="x", padx=10, pady=5)

        switch_eat = ToggleSwitch(extras_opts, text="Auto Eat", color=COLORS['accent_green'])
        switch_eat.pack(anchor="w", pady=2)
        switch_eat.select()

        switch_train = ToggleSwitch(extras_opts, text="Mana Train (No rune)",
                                     color=COLORS['accent_purple'])
        switch_train.pack(anchor="w", pady=2)

        switch_logout = ToggleSwitch(extras_opts, text="Logout se sem Blanks",
                                      color=COLORS['accent_red'])
        switch_logout.pack(anchor="w", pady=2)

        self._create_save_button(tab, "Salvar Rune")

    def _build_tab_healer(self, tab):
        """Aba Healer."""
        content = tk.Frame(tab, bg=COLORS['bg_main'])
        content.pack(fill="both", expand=True, padx=16)

        self._create_section(content, "Cooldown Global")

        cd_frame = tk.Frame(content, bg=COLORS['bg_main'])
        cd_frame.pack(fill="x", pady=4)

        tk.Label(cd_frame, text="Cooldown entre heals:", bg=COLORS['bg_main'], fg=COLORS['text_dim'],
                 font=("Segoe UI", 10)).pack(side="left")
        entry_cd = ModernEntry(cd_frame, width=6)
        entry_cd.pack(side="left", padx=(12, 0), ipady=3)
        entry_cd.insert(0, "2000")
        tk.Label(cd_frame, text="ms", bg=COLORS['bg_main'], fg=COLORS['text_hint'],
                 font=("Segoe UI", 9)).pack(side="left", padx=(6, 0))

        self._create_section(content, "Regras de Cura")

        # Header
        header = tk.Frame(content, bg=COLORS['bg_main'])
        header.pack(fill="x", pady=(0, 4))

        for text, w in [("Prio", 4), ("Alvo", 8), ("HP%", 4), ("Método", 10)]:
            tk.Label(header, text=text, bg=COLORS['bg_main'], fg=COLORS['text_hint'],
                     font=("Segoe UI", 9), width=w).pack(side="left", padx=4)

        # Regras existentes
        rules_frame = tk.Frame(content, bg=COLORS['bg_panel'])
        rules_frame.pack(fill="x")

        for prio, target, hp, method in [("1", "self", "30", "UH"),
                                          ("2", "self", "60", "Exura")]:
            row = tk.Frame(rules_frame, bg=COLORS['bg_panel'])
            row.pack(fill="x", pady=4, padx=8)

            ModernEntry(row, width=3).pack(side="left", padx=2, ipady=2)
            ttk.Combobox(row, values=["self", "friend"], width=7, state="readonly",
                         font=("Segoe UI", 9)).pack(side="left", padx=2)
            ModernEntry(row, width=3).pack(side="left", padx=2, ipady=2)
            ttk.Combobox(row, values=["UH", "IH", "Exura", "Exura Vita"], width=9, state="readonly",
                         font=("Segoe UI", 9)).pack(side="left", padx=2)

            # X button
            tk.Label(row, text="✕", bg=COLORS['bg_panel'], fg=COLORS['accent_red'],
                     font=("Segoe UI", 10, "bold"), cursor="hand2").pack(side="left", padx=(8, 0))

        # Add button
        add_btn = tk.Label(content, text="+ Adicionar Regra", bg=COLORS['accent_blue'],
                           fg=COLORS['text'], font=("Segoe UI", 10), cursor="hand2", pady=6)
        add_btn.pack(fill="x", pady=(12, 0))

        self._create_save_button(tab, "Salvar Healer")

    def _build_tab_cavebot(self, tab):
        """Aba Cavebot."""
        content = tk.Frame(tab, bg=COLORS['bg_main'])
        content.pack(fill="both", expand=True, padx=16)

        # Status
        tk.Label(content, text="📍 Posição: 32000, 32000, 7", bg=COLORS['bg_main'],
                 fg=COLORS['text'], font=("Segoe UI", 10)).pack(anchor="w", pady=(12, 8))

        # Arquivo
        self._create_section(content, "Arquivo de Waypoints")

        file_frame = tk.Frame(content, bg=COLORS['bg_main'])
        file_frame.pack(fill="x", pady=4)

        ttk.Combobox(file_frame, values=["thais_rats.json", "venore_dragons.json"],
                     width=20, state="readonly", font=("Segoe UI", 10)).pack(side="left")

        ModernButton(file_frame, text="📂 Carregar", bg=COLORS['bg_panel'],
                     hover_bg=COLORS['bg_hover'], font=("Segoe UI", 9)).pack(side="left", padx=(8, 0))
        ModernButton(file_frame, text="💾 Salvar", bg=COLORS['bg_panel'],
                     hover_bg=COLORS['bg_hover'], font=("Segoe UI", 9)).pack(side="left", padx=(4, 0))

        # Waypoints
        self._create_section(content, "Waypoints (5)")

        wp_frame = tk.Frame(content, bg=COLORS['bg_panel'])
        wp_frame.pack(fill="x")

        # Listbox simulada
        listbox = tk.Listbox(wp_frame, bg=COLORS['bg_panel'], fg=COLORS['text'],
                              font=("Consolas", 9), height=6, selectbackground=COLORS['accent_blue'],
                              highlightthickness=0, bd=0)
        listbox.pack(fill="x", padx=8, pady=8)

        for i, wp in enumerate(["[WALK] 32000, 32000, 7",
                                "[WALK] 32001, 32000, 7",
                                "[LOOT] 32002, 32000, 7",
                                "[WALK] 32003, 32000, 7",
                                "[ROPE] 32003, 32001, 7"]):
            listbox.insert(tk.END, f"  {i+1}. {wp}")

        # Botões
        btn_frame = tk.Frame(content, bg=COLORS['bg_main'])
        btn_frame.pack(fill="x", pady=8)

        ModernButton(btn_frame, text="+ Add WP", bg=COLORS['accent_green'],
                     hover_bg="#25A873", font=("Segoe UI", 9)).pack(side="left")
        ModernButton(btn_frame, text="▲", bg=COLORS['bg_panel'],
                     hover_bg=COLORS['bg_hover'], font=("Segoe UI", 9)).pack(side="left", padx=(8, 0))
        ModernButton(btn_frame, text="▼", bg=COLORS['bg_panel'],
                     hover_bg=COLORS['bg_hover'], font=("Segoe UI", 9)).pack(side="left", padx=(4, 0))
        ModernButton(btn_frame, text="✕ Remover", bg=COLORS['accent_red'],
                     hover_bg="#CC5555", font=("Segoe UI", 9)).pack(side="right")

        self._create_save_button(tab, "Salvar Cavebot")


# =============================================================================
# MAIN
# =============================================================================
def main():
    print("=" * 50)
    print("Mock Visual - tkinter puro (otimizado)")
    print("=" * 50)
    print()
    print("Performance estimada:")
    print("  RAM: ~15-20 MB (vs ~50 MB customtkinter)")
    print("  Load: ~80ms (vs ~300ms customtkinter)")
    print()
    print("Clique em 'Config' para abrir Settings")
    print("=" * 50)

    app = MockMainWindow()
    app.run()


if __name__ == "__main__":
    main()
