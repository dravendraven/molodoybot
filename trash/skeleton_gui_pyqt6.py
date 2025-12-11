import sys
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QGridLayout, QLabel, QPushButton, 
                             QCheckBox, QFrame, QTabWidget, QTextEdit, QDialog,
                             QSizePolicy, QComboBox, QLineEdit)
from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QFont, QIcon

# ==============================================================================
# ESTILO (CSS) - IMITANDO O DARK MODE
# ==============================================================================
DARK_STYLESHEET = """
QMainWindow { background-color: #202020; }
QWidget { color: #E0E0E0; font-family: 'Verdana'; font-size: 11px; }

/* Frames e Containers */
QFrame#StatsFrame { 
    background-color: transparent; 
    border: 1px solid #303030; 
    border-radius: 6px; 
}
QFrame#GraphContainer {
    background-color: #2B2B2B; 
    border: 1px solid #303030; 
    border-radius: 6px;
}

/* Botões */
QPushButton {
    background-color: #303030;
    border: 1px solid #404040;
    border-radius: 4px;
    padding: 5px;
    font-weight: bold;
}
QPushButton:hover { background-color: #404040; }
QPushButton:pressed { background-color: #505050; }

/* Abas */
QTabWidget::pane { border: 0; }
QTabBar::tab {
    background: #2B2B2B;
    color: #808080;
    padding: 8px 12px;
    border-bottom: 2px solid #303030;
}
QTabBar::tab:selected {
    color: #E0E0E0;
    border-bottom: 2px solid #4EA5F9;
}

/* Logs */
QTextEdit {
    background-color: #151515;
    border: 1px solid #303030;
    color: #00FF00;
    font-family: 'Consolas';
}

/* Checkbox como Switch (Simples) */
QCheckBox { spacing: 8px; }
QCheckBox::indicator { width: 18px; height: 18px; border-radius: 9px; border: 2px solid #555; }
QCheckBox::indicator:checked { background-color: #00C000; border-color: #00C000; }
"""

# ==============================================================================
# JANELA DE CONFIGURAÇÕES (POPUP)
# ==============================================================================
class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Configurações")
        self.resize(300, 400)
        self.setStyleSheet("background-color: #202020; color: white;")
        
        layout = QVBoxLayout(self)
        
        # Exemplo de Abas no Settings
        tabs = QTabWidget()
        tabs.addTab(QWidget(), "Geral")
        tabs.addTab(QWidget(), "Listas")
        
        # Conteúdo da Aba Loot (Exemplo)
        loot_tab = QWidget()
        loot_layout = QVBoxLayout(loot_tab)
        loot_layout.addWidget(QLabel("Configuração de Containers"))
        loot_layout.addWidget(QLabel("Quantas BPs são suas?"))
        loot_layout.addWidget(QLineEdit("2"))
        loot_layout.addStretch()
        loot_tab.setLayout(loot_layout)
        
        tabs.addTab(loot_tab, "Loot")
        
        layout.addWidget(tabs)
        
        btn_close = QPushButton("Fechar")
        btn_close.clicked.connect(self.close)
        layout.addWidget(btn_close)

# ==============================================================================
# JANELA PRINCIPAL
# ==============================================================================
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        
        self.setWindowTitle("Molodoy Bot Pro (PyQt6 Skeleton)")
        self.resize(320, 450)
        
        # Widget Central (Container Principal)
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # Layout Principal (Vertical)
        self.main_layout = QVBoxLayout(central_widget)
        self.main_layout.setContentsMargins(10, 10, 10, 10) # Margens da janela
        self.main_layout.setSpacing(10) # Espaço entre elementos

        # 1. HEADER
        self.create_header()
        
        # 2. CONTROLES (Toggles)
        self.create_controls()
        
        # 3. STATS (Tabela)
        self.create_stats_panel()
        
        # 4. GRÁFICOS E ABAS
        self.create_graph_area()
        
        # 5. LOGS
        self.create_log_box()

    def create_header(self):
        header_layout = QHBoxLayout()
        
        # Botão Config
        self.btn_settings = QPushButton("⚙️ Config.")
        self.btn_settings.setFixedWidth(100)
        self.btn_settings.clicked.connect(self.open_settings)
        
        # Status Label
        self.lbl_status = QLabel("🔌 Procurando...")
        self.lbl_status.setStyleSheet("color: #FFA500; font-weight: bold;")
        self.lbl_status.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        
        header_layout.addWidget(self.btn_settings)
        header_layout.addStretch() # Mola para empurrar
        header_layout.addWidget(self.lbl_status)
        
        self.main_layout.addLayout(header_layout)

    def create_controls(self):
        # Grid 2x2
        grid = QGridLayout()
        grid.setSpacing(10)
        
        # Em PyQt, não temos Switch nativo bonito, usamos CheckBox
        self.chk_trainer = QCheckBox("Smart Trainer")
        self.chk_loot = QCheckBox("Auto Loot")
        self.chk_alarm = QCheckBox("Player Alarm")
        self.chk_fisher = QCheckBox("Auto Fisher")
        
        # Adiciona na Grade (Widget, Linha, Coluna)
        grid.addWidget(self.chk_trainer, 0, 0)
        grid.addWidget(self.chk_alarm,   0, 1)
        grid.addWidget(self.chk_loot,    1, 0)
        grid.addWidget(self.chk_fisher,  1, 1)
        
        self.main_layout.addLayout(grid)

    def create_stats_panel(self):
        # Frame com borda
        self.frame_stats = QFrame()
        self.frame_stats.setObjectName("StatsFrame") # ID para o CSS
        
        # Layout Interno do Frame (Grid)
        stats_layout = QGridLayout(self.frame_stats)
        stats_layout.setContentsMargins(10, 10, 10, 10)
        
        # --- Linha 0: Título ---
        lbl_name = QLabel("🧙‍♂️ It is Molodoy")
        lbl_name.setStyleSheet("color: #E0E0E0; font-weight: bold; font-size: 12px;")
        # addWidget(widget, row, col, rowspan, colspan)
        stats_layout.addWidget(lbl_name, 0, 0, 1, 3) 
        
        # Divisória (Linha Horizontal)
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("color: #404040;")
        stats_layout.addWidget(line, 1, 0, 1, 3)

        # --- Linha 2: Regen ---
        stats_layout.addWidget(QLabel("🍖 --:--"), 2, 0)
        lbl_lvl = QLabel("Lvl: 150")
        lbl_lvl.setAlignment(Qt.AlignmentFlag.AlignRight)
        stats_layout.addWidget(lbl_lvl, 2, 2)

        # --- Helper para criar linhas de Skill ---
        def add_skill_row(row, name, color):
            stats_layout.addWidget(QLabel(f"{name}:"), row, 0)
            
            val = QLabel("10")
            val.setStyleSheet(f"color: {color}; font-weight: bold;")
            stats_layout.addWidget(val, row, 1)
            
            det = QLabel("--%/h ETA: --")
            det.setStyleSheet("color: gray;")
            det.setAlignment(Qt.AlignmentFlag.AlignRight)
            stats_layout.addWidget(det, row, 2)

        add_skill_row(3, "Sword", "#4EA5F9")
        add_skill_row(4, "Shield", "#4EA5F9")
        add_skill_row(5, "Magic", "#A54EF9")
        
        self.main_layout.addWidget(self.frame_stats)

    def create_graph_area(self):
        # Container Cinza para Abas e Botão
        self.graph_container = QFrame()
        self.graph_container.setObjectName("GraphContainer")
        
        container_layout = QVBoxLayout(self.graph_container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(0)
        
        # Abas
        self.tabs = QTabWidget()
        self.tabs.addTab(QWidget(), "Melee")
        self.tabs.addTab(QWidget(), "Magic")
        self.tabs.addTab(QWidget(), "Exp")
        self.tabs.setFixedHeight(60) # Altura fixa das abas
        
        container_layout.addWidget(self.tabs)
        
        # Botão Mostrar Gráfico
        self.btn_graph = QPushButton("Mostrar Gráfico 📈")
        self.btn_graph.setStyleSheet("border-radius: 0px; border-top: 0px;") # Cola no tab
        self.btn_graph.clicked.connect(self.toggle_graph)
        
        container_layout.addWidget(self.btn_graph)
        
        # Área do Gráfico (Escondida inicialmente)
        self.graph_view = QLabel(" [ AQUI FICARIA O GRÁFICO MATPLOTLIB ] ")
        self.graph_view.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.graph_view.setStyleSheet("background-color: #151515; color: #555;")
        self.graph_view.setFixedHeight(100)
        self.graph_view.setVisible(False) # Começa invisível
        
        container_layout.addWidget(self.graph_view)
        
        self.main_layout.addWidget(self.graph_container)

    def create_log_box(self):
        self.txt_log = QTextEdit()
        self.txt_log.setReadOnly(True)
        self.txt_log.setFixedHeight(100)
        self.txt_log.append("[SYSTEM] Interface Skeleton Carregada.")
        self.txt_log.append("[SYSTEM] Backend desconectado.")
        
        self.main_layout.addWidget(self.txt_log)

    # ==========================================================================
    # LÓGICA VISUAL (SIMULAÇÃO)
    # ==============================================================================
    def open_settings(self):
        dialog = SettingsDialog(self)
        dialog.exec() # Abre modal (bloqueia a janela principal)

    def toggle_graph(self):
        if self.graph_view.isVisible():
            self.graph_view.setVisible(False)
            self.btn_graph.setText("Mostrar Gráfico 📈")
            self.resize(320, 450)
        else:
            self.graph_view.setVisible(True)
            self.btn_graph.setText("Esconder Gráfico 📉")
            self.resize(320, 550)

# ==============================================================================
# EXECUÇÃO
# ==============================================================================
if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion") # Estilo moderno padrão do Qt
    
    # Aplica o CSS global
    app.setStyleSheet(DARK_STYLESHEET)
    
    window = MainWindow()
    window.show()
    
    sys.exit(app.exec())