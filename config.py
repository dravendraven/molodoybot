# config.py
from database import foods_db

# ==============================================================================
# DEBUG FLAGS (Centralizadas para fácil acesso durante testes)
# ==============================================================================
DEBUG_MODE = False    # Modo debug geral - ativa logs extras em diversos módulos
HIT_LOG_ENABLED = False  # Controls writing hits to hits_monitor.txt
XRAY_TRAINER_DEBUG = True    # True = mostra overlay de debug do trainer

# Bot State Debugger HUD
DEBUG_BOT_STATE = False                      # Master toggle - mostra/esconde HUD
DEBUG_BOT_STATE_INTERVAL = 0.1              # Intervalo de atualização (segundos) - 100ms = 10 FPS
DEBUG_BOT_STATE_AUTO_DISABLE_ON_ALARM = False # Desabilitar HUD automaticamente com alarme

# Pathfinding & Navigation
DEBUG_PATHFINDING = False  # Ativa logs detalhados do A* quando não encontra caminho
DEBUG_MEMORY_MAP = False  # Caro de performance, ativar apenas quando necessário
DEBUG_GLOBAL_MAP = False  # Ativa logs quando GlobalMap tenta encontrar rotas

# Obstacle & Stack Clearing
DEBUG_OBSTACLE_CLEARING = False   # Ativa logs detalhados do obstacle clearing
DEBUG_STACK_CLEARING = False      # Ativa logs detalhados do stack clearing

# Advancement & Chat
DEBUG_ADVANCEMENT = True             # Logs detalhados de detecção de progresso
DEBUG_CHAT_HANDLER = True           # Logs detalhados do sistema de chat

# Trainer
TRAINER_DEBUG_DECISIONS_ONLY = False  # Loga apenas decisões: atacar, retarget, morte, etc.

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
TELEGRAM_CHAT_ID = ""  # Vazio por padrão - configurar no bot para receber alertas

# Configuração do Sniffer de Pacotes
SNIFFER_ENABLED = True         # Ativa captura de pacotes (requer Npcap + Admin)
SNIFFER_SERVER_IP = "135.148.27.135"  # IP do servidor OT

# ==============================================================================
# GUI SETTINGS
# ==============================================================================
RELOAD_BUTTON = True  # Exibe botão de reload na interface (desabilitar para release)

TARGET_MONSTERS = ["Rotworm", "Minotaur"]
SAFE_CREATURES = ["Minotaur", "Rotworm", "Troll", "Wolf", "Deer", "Rabbit", "Spider", "Poison Spider", "Bug", "Rat", "Bear", "Wasp", "Orc"]

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

BATTLELIST_BEGIN_ADDRESS = 0x1C68B0
TARGET_ID_PTR = 0x1C681C
REL_FIRST_ID = 0x94
STEP_SIZE = 156
OFFSET_ID = 0
OFFSET_NAME = 4
OFFSET_X = 0x24       # 36
OFFSET_Y = 0x28       # 40
OFFSET_Z = 0x2C
OFFSET_HP = 0x84
OFFSET_SPEED = 0x88
OFFSET_VISIBLE = 0x8C
OFFSET_MOVEMENT_STATUS = 0x4C    # 0=parado, 1=andando
OFFSET_FACING_DIRECTION = 0x50  # 0=Norte, 1=Este, 2=Sul, 3=Oeste

# Offsets de Outfit (para diferenciar players de criaturas)
# Players tem cores > 0, criaturas tem cores = 0
OFFSET_OUTFIT_TYPE = 0x60   # 96 - LookType (sprite base)
OFFSET_OUTFIT_HEAD = 0x64   # 100 - Cor da cabeça
OFFSET_OUTFIT_BODY = 0x68   # 104 - Cor do corpo
OFFSET_OUTFIT_LEGS = 0x6C   # 108 - Cor das pernas
OFFSET_OUTFIT_FEET = 0x70   # 112 - Cor dos pés
OFFSET_LIGHT = 0x74         # 116 - Light level emitted
OFFSET_LIGHT_COLOR = 0x78   # 120 - Light color
OFFSET_BLACKSQUARE = 0x80   # 128 - Blacksquare indicator (4 bytes uint32, GetTickCount timestamp when creature attacks player)

MAX_CREATURES = 250

# Constantes de direção para legibilidade
DIR_NORTH = 0
DIR_EAST = 1
DIR_SOUTH = 2
DIR_WEST = 3

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

# Offset para detectar se container é filho de outro
OFFSET_CNT_HAS_PARENT = 52    # 0 = raiz, 1 = filho de outro container

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

# ==============================================================================
# AUTO LOOT DELAYS (em segundos)
# ==============================================================================
# Ajuste estes valores para controlar a velocidade do loot.
# Valores menores = mais rápido, maior risco de detecção.
# Formato: (tempo_base, variacao_percentual)

LOOT_DELAY_OPEN_BAG = (0.25, 15)          # Após abrir bag dentro do corpo
LOOT_DELAY_EAT_FOOD = (0.25, 20)         # Após comer comida
LOOT_DELAY_MOVE_ITEM = (0.25, 30)         # Após mover item para backpack
LOOT_DELAY_DROP_ITEM = (0.3, 20)         # Após dropar item no chão
LOOT_DELAY_CLOSE_CONTAINER = (0.5, 30)  # Após fechar container de loot

# ==============================================================================
# FEATURE FLAGS
# ==============================================================================
# Flag para habilitar sistema de loot configurável
# Se False, usa LOOT_IDS/DROP_IDS hardcoded (comportamento antigo)
# Se True, usa sistema configurável via GUI com nomes de items
USE_CONFIGURABLE_LOOT_SYSTEM = True

# ==============================================================================
# LOOT CONFIGURATION
# ==============================================================================

# MODO ANTIGO (quando USE_CONFIGURABLE_LOOT_SYSTEM = False)
LOOT_IDS = [3031, 3035, 3043, 3578, 3054] # Gold, Plat, Crystal, Peixe, Silver Amuleto
DROP_IDS = [3286, 3264, 3358, 3354, 3410] # Mace, Sword, Chain Armor, Brass Helmet, Plate Shield

# MODO NOVO (quando USE_CONFIGURABLE_LOOT_SYSTEM = True)
# Valores padrão para primeira execução
DEFAULT_LOOT_NAMES = ["coin", "a fish"]
DEFAULT_DROP_NAMES = ["a mace", "a sword", "chain armor", "brass helmet", "plate shield"]

# Constantes sempre ativas (independente da flag)
FOOD_IDS = foods_db.get_food_ids()
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

# Criaturas que não devem ter o loot aberto (não possuem loot)
NO_LOOT_CREATURES = ["Snake", "Wasp"]

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
OFFSET_LOOK_ID      = 0x31C63C # Int: ID do item/creature ao dar "Look"

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
# Estrutura: ID(4 bytes) + Count(4 bytes) + Extra(4 bytes) = 12 bytes por slot
OFFSET_SLOT_RIGHT = 0x1CED90
OFFSET_SLOT_RIGHT_COUNT = 0x1CED94
OFFSET_SLOT_LEFT  = 0x1CED9C
OFFSET_SLOT_LEFT_COUNT = 0x1CEDA0
OFFSET_SLOT_AMMO  = 0x1CEDCC
OFFSET_SLOT_AMMO_COUNT = 0x1CEDD0

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
FATIGUE_ACTIONS_RANGE = (8, 22)
# Define quanto tempo (segundos) ele descansa quando atinge o limite
FATIGUE_REST_RANGE = (10, 50)
# Porcentagem extra de delay motor quando estiver cansado (Ex: 0.3 = 30% mais lento)
FATIGUE_MOTOR_PENALTY = 0.4

BASE_REACTION_MIN = 0.5
BASE_REACTION_MAX = 0.9
TRAVEL_SPEED_MIN = 0.02
TRAVEL_SPEED_MAX = 0.09

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
EAT_THRESHOLD = 600 # Comer quando faltar x segundos

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
OFFSET_CONSOLE_PTR = 0x31DD18
# Offsets relativos ao ponteiro do console
OFFSET_CONSOLE_MSG = 0x31DE30    # A mensagem em si
OFFSET_CONSOLE_AUTHOR = 0x31DE08  # O log/autor ("Fulano says:")

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
# KILL-STEAL (KS) PREVENTION
# ==============================================================================
KS_PREVENTION_ENABLED = True          # Master toggle para evitar atacar criaturas já engajadas
KS_HP_LOSS_THRESHOLD = 15             # % HP loss em 5s que indica combate com outro player
KS_HISTORY_DURATION = 5.0             # Segundos de histórico de HP a manter
# NOTA: Detecção usa comparação RELATIVA de distâncias:
# Se dist(criatura → player) < dist(criatura → bot), então skip

# Blacksquare Detection (criatura atacando o player)
# Se (GetTickCount() - blacksquare) < threshold, criatura está nos atacando
# Nota: Ataques ocorrem a cada ~2 segundos, usamos 5s para garantir detecção entre ciclos de scan
BLACKSQUARE_THRESHOLD_MS = 5000       # Considerar criatura atacando se atacou há menos de 5 segundos

# ==============================================================================
### GLOBAL MAP

WALKABLE_COLORS = [24, 129, 121, 210] # Grama, Chão Padrão cinza, Chão de Dirt/Caverna, #Amarelo: escada, buraco, etc
MAPS_DIRECTORY = r"c:\Users\vitor\Downloads\amera-client-latest"

# ==============================================================================
# PATHFINDING CONFIG
# ==============================================================================
# True = calcula próximo passo em tempo real (mais preciso, evita obstáculos fantasmas)
# False = usa cache de caminho completo (mais fluido, pode dessincronizar)
REALTIME_PATHING_ENABLED = True

# ==============================================================================
# OBSTACLE CLEARING CONFIG
# ==============================================================================
OBSTACLE_CLEARING_ENABLED = True  # Master toggle - mover mesas/cadeiras do caminho

# Máximo de tentativas de limpar o mesmo tile antes de desistir
MAX_CLEAR_ATTEMPTS_PER_TILE = 3

# Cooldown entre tentativas de limpeza (segundos)
CLEAR_ATTEMPT_COOLDOWN = 2.0

# ==============================================================================
# STACK CLEARING CONFIG (Parcels, Boxes, Furniture Packages)
# ==============================================================================
STACK_CLEARING_ENABLED = True     # Master toggle - mover parcels/boxes do caminho

# ==============================================================================
# HUMANIZAÇÃO - DETECÇÃO DE FALTA DE PROGRESSO
# ==============================================================================
# Detecta quando o bot está andando mas não avançando ao waypoint (ping-pong, etc)
ADVANCEMENT_TRACKING_ENABLED = True
ADVANCEMENT_WINDOW_SECONDS = 3.0      # Janela de medição (segundos)
ADVANCEMENT_MIN_RATIO = 0.3           # Mínimo 30% do avanço esperado
ADVANCEMENT_EXPECTED_SPEED = 2.0      # SQM/segundo esperado em caminhada normal

# Respostas quando player bloqueando
PLAYER_BLOCK_WAIT_RANGE = (1.0, 4.0)  # Range de espera (segundos) - gaussiano
PLAYER_AVOIDANCE_MULTIPLIER = 2       # Custo 2x nos tiles do player no A*

# ==============================================================================
# AI CHAT RESPONDER CONFIG
# ==============================================================================
# Sistema de resposta inteligente a mensagens de chat usando IA (OpenAI GPT)
AI_CHAT_ENABLED = False              # Master toggle - habilita/desabilita sistema
AI_MODEL = "gpt-4o-mini"            # Modelo OpenAI (~$0.15/1M tokens input)

# Delays humanizados para resposta (parecer humano)
CHAT_RESPONSE_DELAY_MIN = 1.5       # Delay mínimo antes de responder (segundos)
CHAT_RESPONSE_DELAY_MAX = 4.0       # Delay máximo antes de responder (segundos)

# Cooldown entre respostas (evita spam/flood)
CHAT_RESPONSE_COOLDOWN = 5.0        # Segundos entre respostas

# Pausa o bot enquanto em "conversa"
CHAT_PAUSE_BOT = True               # Se True, pausa cavebot/trainer durante conversa
CHAT_PAUSE_DURATION = 10.0          # Segundos de pausa após última mensagem

# ==============================================================================
# FOLLOW-THEN-ATTACK CONFIG (TRAINER)
# ==============================================================================
# Modo de combate: seguir criatura até dist<=1, depois atacar
# Independente do spear_picker - útil para testes e combate melee
FOLLOW_THEN_ATTACK = True  # True = segue antes de atacar
