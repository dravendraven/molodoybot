import pymem
import win32gui
from config import *

def get_player_pos(pm, base_addr):
    """
    Lê a posição GLOBAL (X, Y, Z) do jogador diretamente da memória estática.
    Muito mais rápido que varrer a BattleList.
    """
    try:
        # Offsets relativos baseados no Version.cs (0x05D16F0 - 0x400000)
        # Adicione ao config.py se quiser: OFFSET_PLAYER_X_STATIC = 0x1D16F0
        
        x = pm.read_int(base_addr + 0x1D16F0)
        y = pm.read_int(base_addr + 0x1D16EC)
        z = pm.read_int(base_addr + 0x1D16E8)
        return x, y, z
    except:
        return 0, 0, 0

def get_game_view(pm, base_addr):
    """
    Lê a memória para descobrir onde o quadrado do jogo está na tela.
    Retorna dicionário com dimensões e centro (em Coordenadas de CLIENTE).
    """
    try:
        gui_ptr = pm.read_int(base_addr + OFFSET_GUI_POINTER)
        ptr = pm.read_int(gui_ptr + OFFSET_GAME_VIEW_1)
        map_struct = pm.read_int(ptr + OFFSET_GAME_VIEW_2)
        
        view_x = pm.read_int(map_struct + OFFSET_VIEW_X)
        view_y = pm.read_int(map_struct + OFFSET_VIEW_Y)
        view_w = pm.read_int(map_struct + OFFSET_VIEW_W)
        view_h = pm.read_int(map_struct + OFFSET_VIEW_H)
        
        if view_w < 100 or view_h < 100:
            return None

        sqm_size = view_w / 15
        center_x = view_x + (view_w / 2)
        center_y = view_y + (view_h / 2)
        
        return {
            "rect": (view_x, view_y, view_w, view_h),
            "sqm": sqm_size,
            "center": (center_x, center_y)
        }
        
    except Exception as e:
        print(f"Erro GameView: {e}")
        return None

def get_screen_coord(game_view, rel_x, rel_y, hwnd):
    """
    Converte coordenada relativa (Ex: +1, -1) para Pixel REAL na tela.
    Usa o HWND para compensar a Barra de Título e Bordas.
    """
    # 1. Calcula a posição no "Mundo do Cliente" (Sem barra de título)
    client_x = game_view["center"][0] + (rel_x * game_view["sqm"])
    client_y = game_view["center"][1] + (rel_y * game_view["sqm"])
    
    # 2. A Mágica: Converte Cliente -> Tela
    # O Windows calcula onde esse ponto interno cai no seu Monitor.
    screen_point = win32gui.ClientToScreen(hwnd, (int(client_x), int(client_y)))
    
    return screen_point[0], screen_point[1]