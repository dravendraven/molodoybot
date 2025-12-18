# config.py
from database import foods_db

# ==============================================================================
# 1. GERAIS E CONEXÃO
# ==============================================================================
# PROCESS_NAME = "Tibia.exe"
# MY_PLAYER_NAME = "It is Molodoy"

OFFSET_CONNECTION = 0x31C588

# Integração Telegram
# TELEGRAM_TOKEN = "YOUR_TELEGRAM_TOKEN"
# TELEGRAM_CHAT_ID = "YOUR_TELEGRAM_CHAT_ID"

# ==============================================================================
# 1. CONFIGURAÇÕES PADRÃO
# ==============================================================================

PROCESS_NAME = "Tibia.exe"
MY_PLAYER_NAME = "It is Molodoy"
TELEGRAM_TOKEN = "7238077578:AAELH9lr8dLGJqOE5mZlXmYkpH4fIHDAGAM"
TELEGRAM_CHAT_ID = "452514119"

TARGET_MONSTERS = ["Rotworm", "Minotaur"]
SAFE_CREATURES = ["Minotaur", "Rotworm", "Troll", "Wolf", "Deer", "Rabbit", "Spider", "Poison Spider", "Bug", "Rat", "Bear", "Wasp", "Orc"]
HIT_LOG_ENABLED = False  # Controls writing hits to hits_monitor.txt

OFFSET_PLAYER_ID = 0x1C684C
OFFSET_PLAYER_HP = 0x1C6848
OFFSET_PLAYER_HP_MAX = 0x1C6844
OFFSET_PLAYER_MANA = 0x1C682C
OFFSET_PLAYER_MANA_MAX = 0x1C6828

OFFSET_MAGIC_LEVEL = 0x1C6838
OFFSET_MAGIC_PCT   = 0x1C6830
OFFSET_LEVEL       = 0x1C683C
OFFSET_EXP         = 0x1C6840

OFFSET_MAP_POINTER = 0x1D4C20

PLAYER_X_ADDRESS = 0x005D16F0
PLAYER_Y_ADDRESS = 0x005D16EC
PLAYER_Z_ADDRESS = 0x005D16E8

TARGET_ID_PTR = 0x1C681C 
REL_FIRST_ID = 0x94
STEP_SIZE = 156
OFFSET_ID = 0
OFFSET_NAME = 4
OFFSET_X = 0x24       # 36
OFFSET_Y = 0x28       # 40
OFFSET_Z = 0x2C       
OFFSET_HP = 0x84      
OFFSET_VISIBLE = 0x8C
MAX_CREATURES = 250

OFFSET_SKILL_SWORD_PCT = 0x1C67E4
OFFSET_SKILL_SWORD = 0x1C6800
OFFSET_SKILL_SHIELD_PCT = 0x1C67F0
OFFSET_SKILL_SHIELD = 0x1C680C
CURRENT_VOCATION = "Knight"
OFFSET_CONNECTION = 0x31C588

# ==============================================================================
# OFFSETS DE CONTAINER E LOOT (Versão < 3)
# Fonte: Version(2).cs
# ==============================================================================

# Endereço inicial da lista de containers (RELATIVO)
# Cálculo: 0x05CEDD8 (C#) - 0x400000 (Base) = 0x1CEDD8
OFFSET_CONTAINER_START = 0x1CEDD8 

# Distância em bytes de um container para o próximo
STEP_CONTAINER = 492 

# Número máximo de containers abertos
MAX_CONTAINERS = 16

# Offsets INTERNOS do Container
OFFSET_CNT_IS_OPEN = 0      
OFFSET_CNT_NAME    = 16     
OFFSET_CNT_VOLUME  = 48     
OFFSET_CNT_AMOUNT  = 56     

# Offsets dos ITENS dentro do Container
OFFSET_CNT_ITEM_ID    = 60  
OFFSET_CNT_ITEM_COUNT = 64  

# Distância entre itens (Slot)
STEP_SLOT = 12

# ==============================================================================
# GUI POINTERS (Cálculo de Posição na Tela)
# Fonte: Client.GuiPointer em Version(2).cs
# ==============================================================================

# Endereço base da GUI (Relativo)
OFFSET_GUI_POINTER = 0x1D16B0 

# Offsets para navegar na estrutura de janelas (LinkedList)
# Baseados na função GetItemPosition do CrystalBot
GUI_OFFSET_1 = 0x24
GUI_OFFSET_2 = 0x24
GUI_OFFSET_NEXT_WINDOW = 0x10
GUI_OFFSET_WINDOW_STRUCT = 0x44
GUI_OFFSET_WINDOW_HEIGHT = 0x20

# Ajuste fino da posição Y (Título da janela + borda)
# O CrystalBot usa += 15, mas pode variar conforme a skin/versão. Vamos começar com 15.
GUI_HEADER_HEIGHT = 15 

# Largura e Altura de um Slot em pixels
SLOT_SIZE = 36  # Padrão 32x32 + 1px de borda

# Coordenada X,Y onde começa a área cinza escura dos containers (Painel Direito)
# Valores calibrados pelo usuário:
BASE_PANEL_X = 1750
BASE_PANEL_Y = 355

# ==============================================================================
# GUI STRUCTURE (Baseado em uitibia.h)
# ==============================================================================
# Offsets da classe GUIItem
OFFSET_UI_PARENT    = 0x0C  # m_parent
OFFSET_UI_NEXT      = 0x10  # m_nextItem
OFFSET_UI_OFFSET_X  = 0x14  # m_offsetx
OFFSET_UI_OFFSET_Y  = 0x18  # m_offsety
OFFSET_UI_WIDTH     = 0x1C  # m_width
OFFSET_UI_HEIGHT    = 0x20  # m_height

# Offsets da classe GUIHolder / GUIContainer
OFFSET_UI_CHILD     = 0x24  # m_child (primeiro elemento dentro da janela)
OFFSET_UI_ID        = 0x30  # m_id (Identifica se é Battle, VIP ou Container)

# IDs de Janelas Conhecidas (uitibia.h)
UI_ID_BATTLE = 7
UI_ID_CONTAINER_START = 64 # IDs acima de 64 são containers reais

OFFSET_UI_ID_CORRECT = 0x2C # Baseado na soma das classes (GUIItem 0x24 + GUIHolder 0x8)
OFFSET_UI_PARENT = 0x0C

# ==============================================================================
# AUTO LOOT CONFIG
# ==============================================================================

# # Quantos containers SEUS ficam abertos?
MY_CONTAINERS_COUNT = 2

# # Índice do Container de Destino (Para onde vai o loot?)
# # 0 = Primeira Backpack aberta
DEST_CONTAINER_INDEX = 0 

LOOT_IDS = [3031, 3035, 3043, 3578] # Gold, Plat, Crystal, Peixe
FOOD_IDS = foods_db.get_food_ids()
DROP_IDS = [3286, 3264, 3358, 3354, 3410] # Mace, Sword, Chain Armor, Brass Helmet, Plate Shield
LOOT_CONTAINER_IDS = [2853]

# ==============================================================================
# ROPE SPOT EXCEPTIONS (Items que NÃO precisam ser removidos do rope spot)
# ==============================================================================
# Lista de item IDs que não bloqueiam o uso da rope no rope spot.
# Exemplo: poças de sangue, pools de slime, etc.
# Formato: [ID1, ID2, ID3, ...]
# Adicione manualmente os IDs dos items que descobrir que não precisam ser limpos.
ROPE_SPOT_IGNORE_IDS = [
    2886, 2887, 2888, 2889, 2890, 2891, 2895, 2896, 2897, 2898, 2899, 2900
]

# ==============================================================================
# GAME VIEW (Cálculo Automático do Mapa)
# Fonte: Version(2).cs e Client(2).cs
# ==============================================================================
# Esses offsets são para navegar dentro do GuiPointer até achar o "MapBox"
OFFSET_GAME_VIEW_1 = 0x2C
OFFSET_GAME_VIEW_2 = 0x24

# Offsets dentro da estrutura do MapBox
OFFSET_VIEW_X = 0x14
OFFSET_VIEW_Y = 0x18
OFFSET_VIEW_W = 0x1C
OFFSET_VIEW_H = 0x20

# ==============================================================================
# STATUS BAR CONFIG (Mensagens do Jogo)
# Fonte: Cheat Engine (0x071DBE0 e 0x071DBDC)
# ==============================================================================
OFFSET_STATUS_TEXT  = 0x31DBE0 # String: "You are full.", "You look at...", etc.
OFFSET_STATUS_TIMER = 0x31DBDC # Int: Tempo restante da mensagem na tela

# ==============================================================================
# Pesca
# ==============================================================================
OFFSET_LAST_INTERACTION_ID = 0x31C630
OFFSET_LAST_USED_ITEM_ID = 0x31C630
OFFSET_LAST_USED_ITEM_COUNT = 0x31C634

VISUAL_FISH_IDS = list(range(4597, 4609)) + [618, 619]

# IDs onde visualmente NÃO tem peixe (Água vazia/Cooldown)
VISUAL_EMPTY_IDS = list(range(4609, 4615)) + [620]

WATER_IDS = VISUAL_FISH_IDS + VISUAL_EMPTY_IDS
FISH_CAUGHT_VALIDATION_BY_ID = True

# Tempo máximo de regeneração acumulada (20 minutos = 1200 segundos)
MAX_FOOD_TIME = 1200

ROD_ID = 3483           # Fishing Rod comum
FISH_ID = 3578          # Peixe (para comer/contar)
FISH_WEIGHT = 5.2       # Peso para detectar sucesso

# Offsets de Equipamento (const.h: 0x5CED90 - 0x400000 = 0x1CED90)
OFFSET_SLOT_RIGHT = 0x1CED90
OFFSET_SLOT_LEFT  = 0x1CED9C
OFFSET_SLOT_AMMO  = 0x1CEDCC

# Índices de Slot de Equipamento (para packets/UI)
SLOT_RIGHT = 5
SLOT_LEFT = 6
SLOT_AMMO = 7

OFFSET_PLAYER_CAP = 0x1C6820  # Capacidade (Oz) 

# Cooldown do peixe (em segundos)
# 32 minutos = 1920 segundos
FISH_RESPAWN_TIME = 2200
FISH_FAIL_COOLDOWN = 600   # 10 min (Falha/Vazio) <--- ADICIONE ISSO

# Quantidade máxima de tentativas em um mesmo SQM antes de desistir
MAX_FISHING_ATTEMPTS = (4, 6)

# --- CONTROLE DE CAPACIDADE (CAP) ---
CHECK_MIN_CAP = True      # Se True, o bot para de pescar se a cap estiver baixa
MIN_CAP_VALUE = 6.0       # Valor mínimo de cap (oz) para permitir a pesca

# Define quantos arremessos o bot aguenta antes de precisar descansar
FATIGUE_ACTIONS_RANGE = (10, 30)  
# Define quanto tempo (segundos) ele descansa quando atinge o limite
FATIGUE_REST_RANGE = (10, 50)     
# Porcentagem extra de delay motor quando estiver cansado (Ex: 0.3 = 30% mais lento)
FATIGUE_MOTOR_PENALTY = 0.4

BASE_REACTION_MIN = 0.8
BASE_REACTION_MAX = 1.2
TRAVEL_SPEED_MIN = 0.02
TRAVEL_SPEED_MAX = 0.08



# ==============================================================================
# X-RAY
# ==============================================================================
COLOR_FLOOR_ABOVE = "#FFFF00" # Amarelo (Andar de Cima)
COLOR_FLOOR_BELOW = "#A52A2A" # Marrom (Andar de Baixo)
COLOR_SAME_FLOOR  = "#FF0000" # Vermelho (Mesmo andar - Alarme visual)

# ==============================================================================
# VOCATION & REGEN CONFIG
# ==============================================================================
# Tabela de Regeneração: (HP Tick Secs, Mana Tick Secs)
VOCATION_REGEN = {
    "Knight":          (6, 12),
    "Elite Knight":    (4, 12),
    "Paladin":         (8, 8),
    "Royal Paladin":   (6, 6),
    "Druid/Sorcerer":  (12, 6),
    "Elder/Master":    (12, 4),
    "None":            (6, 6) # Fallback
}

# ==============================================================================
# AUTO EATER CONFIG
# ==============================================================================
EAT_THRESHOLD = 480 # Comer quando faltar 5 minutos (300s)  

# ==============================================================================
# FULL LIGHT CONFIG
# ==============================================================================
# Endereço da instrução de comparação de luz (Para NOP)
OFFSET_LIGHT_NOP = 0xBF94B

# Endereço do valor de intensidade da luz
OFFSET_LIGHT_AMOUNT = 0xBF94E

# Bytes originais para restaurar (Jump if Less or Equal)
LIGHT_DEFAULT_BYTES = b'\x7E\x05'

# ==============================================================================
# MEMORY MAP CONFIGURATION (TIBIA 7.72)
# ==============================================================================
# Endereço onde fica o ponteiro para a matriz do mapa
# Blackd: 0x5D4C20 -> Offset: 0x1D4C20
MAP_POINTER_ADDR = 0x1D4C20      

# Ponteiro para calcular offsets extras
# Blackd: 0x5D4C3C -> Offset: 0x1D4C3C
OFFSET_POINTER_ADDR = 0x1D4C3C   

# Andar do personagem (Z)
# Blackd: 0x5D16E8 -> Offset: 0x1D16E8
PLAYER_Z_ADDR = 0x1D16E8         

# Constantes da Estrutura de Dados
TILE_SIZE = 172 # 168 ou 172 dependendo da versão exata, vamos testar
MAP_WIDTH = 18
MAP_HEIGHT = 14
MAP_FLOORS = 8
TOTAL_TILES = MAP_WIDTH * MAP_HEIGHT * MAP_FLOORS
MAP_DATA_SIZE = TOTAL_TILES * TILE_SIZE

# ==============================================================================
# ALARME DE CHAT (CONSOLE)
# ==============================================================================
# Endereço base do console (Calculado: 0x0071DD18 - 0x400000)
OFFSET_CONSOLE_PTR = 0x31DD18 

# Offsets relativos ao ponteiro do console
OFFSET_CONSOLE_MSG = 0x118    # A mensagem em si
OFFSET_CONSOLE_AUTHOR = 0xF0  # O log/autor ("Fulano says:")

# ==============================================================================
# SEGURANÇA: RETORNO HUMANIZADO (COOL-OFF)
# ==============================================================================
# Tempo de espera (segundos) para voltar a agir após um alarme comum (Monstro/PK)
RESUME_DELAY_NORMAL = (10, 25)

# Tempo de espera (segundos) para voltar a agir após detecção de GM (Visual ou Chat)
RESUME_DELAY_GM = (120, 300) 

# Intervalo entre alertas no Telegram (Segundos)
TELEGRAM_INTERVAL_NORMAL = 60
TELEGRAM_INTERVAL_GM = 10  # Alerta frenético se for GM

# ==============================================================================
# CONSTANTES DE DETECÇÃO (ALARM)
# ==============================================================================
# Prefixos de GM/Staff detectados no chat e na tela
GM_PREFIXES = ("GM ", "CM ", "God ")

# ==============================================================================
# ENUMS E CONSTANTES DE EQUIPAMENTO
# ==============================================================================
class HandSlot:
    """Enumeração de slots de mão (para Runemaker/Fisher)"""
    RIGHT = 0
    LEFT = 1
    AMMO = 2

class AlertType:
    """Tipos de alerta do sistema de Alarm"""
    MONSTER = "MONSTER"
    PLAYER = "PLAYER"
    GM = "GM"
    MANUAL = "MANUAL"
    HP_LOW = "HP_LOW"
    CHAT = "CHAT"

# ==============================================================================
# PACKET OPCODES
# ==============================================================================
OP_CLOSE_CONTAINER = 0x87  # Packet para fechar containers de loot

# ==============================================================================
# DEBUG CONFIG (PATHFINDING)
# ==============================================================================
# Ativa logs detalhados do A* quando não encontra caminho
DEBUG_PATHFINDING = True