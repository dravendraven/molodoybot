import win32gui
import win32api
import win32con
import time
from core.mouse_lock import acquire_mouse, release_mouse

# ==============================================================================
# CONFIGURAÇÃO DE INPUT
# ==============================================================================
# Para uso com VMs, PostMessage (False) costuma ser melhor pois não trava
# se a janela estiver 'congelada' em background.
USE_SEND_MESSAGE = False

# Constantes Virtuais
VK_CONTROL = 0x11 
VK_SHIFT = 0x10
VK_MENU = 0x12 # Tecla ALT
VK_RETURN = 0x0D

# Flags de Mouse (Virtual)
MK_LBUTTON = 0x0001
MK_RBUTTON = 0x0002
MK_SHIFT   = 0x0004
MK_CONTROL = 0x0008

def make_lparam(x, y):
    """Cria o parâmetro long (32-bit) com as coordenadas X e Y."""
    return (y << 16) | (x & 0xFFFF)

def _send_win_msg(hwnd, msg, wparam, lparam):
    """Wrapper para alternar entre SendMessage e PostMessage."""
    if USE_SEND_MESSAGE:
        win32gui.SendMessage(hwnd, msg, wparam, lparam)
    else:
        win32api.PostMessage(hwnd, msg, wparam, lparam)

def reset_state(hwnd):
    """
    Limpeza de Estado Crítica.
    Garante que o Tibia não ache que você está segurando Shift/Ctrl 
    por causa do foco da VM.
    """
    # Solta modificadores explicitamente
    win32api.PostMessage(hwnd, win32con.WM_KEYUP, VK_SHIFT, 0)
    win32api.PostMessage(hwnd, win32con.WM_KEYUP, VK_CONTROL, 0)
    # Solta mouse fantasma
    win32api.PostMessage(hwnd, win32con.WM_LBUTTONUP, 0, 0)
    win32api.PostMessage(hwnd, win32con.WM_RBUTTONUP, 0, 0)
    time.sleep(0.02)

# ==============================================================================
# FUNÇÕES DE AÇÃO
# ==============================================================================

def drag_item(hwnd, from_x, from_y, to_x, to_y, hold_ctrl=False):
    """
    Arrasta um item. Inclui limpeza de estado antes da ação.
    """
    try:
        client_point_from = win32gui.ScreenToClient(hwnd, (int(from_x), int(from_y)))
        client_point_to = win32gui.ScreenToClient(hwnd, (int(to_x), int(to_y)))
    except Exception as e:
        print(f"Erro coordenadas: {e}")
        return

    lparam_from = make_lparam(client_point_from[0], client_point_from[1])
    lparam_to = make_lparam(client_point_to[0], client_point_to[1])

    acquire_mouse()
    try:
        # 1. LIMPEZA DE ESTADO (O Segredo)
        reset_state(hwnd)
        
        original_pos = win32api.GetCursorPos()
        
        # Acorda Janela
        win32api.PostMessage(hwnd, win32con.WM_ACTIVATE, win32con.WA_ACTIVE, 0)

        # A. Pressiona CTRL se solicitado (agora com certeza que estava limpo antes)
        if hold_ctrl:
            _send_win_msg(hwnd, win32con.WM_KEYDOWN, VK_CONTROL, 0)
            time.sleep(0.05)
        
        # B. Clica e Segura
        _send_win_msg(hwnd, win32con.WM_LBUTTONDOWN, 1, lparam_from)
        
        # C. Nudge Físico (Necessário para Hybrid Drag)
        win32api.SetCursorPos((original_pos[0] + 1, original_pos[1] + 1))
        
        # D. Move
        _send_win_msg(hwnd, win32con.WM_MOUSEMOVE, 0, lparam_to)
        time.sleep(0.15)
        
        # E. Solta
        _send_win_msg(hwnd, win32con.WM_LBUTTONUP, 0, lparam_to)
        
        # F. Solta CTRL
        if hold_ctrl:
            time.sleep(0.05)
            _send_win_msg(hwnd, win32con.WM_KEYUP, VK_CONTROL, 0)
        
        # G. Restaura Mouse
        win32api.SetCursorPos(original_pos)
    finally:
        release_mouse()

def right_click_at(hwnd, x, y):
    try:
        client_point = win32gui.ScreenToClient(hwnd, (int(x), int(y)))
    except: return
    lparam = make_lparam(client_point[0], client_point[1])
    
    acquire_mouse()
    try:
        reset_state(hwnd) # Limpeza
        
        _send_win_msg(hwnd, win32con.WM_RBUTTONDOWN, 0, lparam)
        time.sleep(0.05)
        _send_win_msg(hwnd, win32con.WM_RBUTTONUP, 0, lparam)
    finally:
        release_mouse()

def ctrl_right_click_at(hwnd, x, y):
    try:
        client_point = win32gui.ScreenToClient(hwnd, (int(x), int(y)))
    except: return
    lparam = make_lparam(client_point[0], client_point[1])
    
    reset_state(hwnd) # Garante que shift não está preso
    
    _send_win_msg(hwnd, win32con.WM_KEYDOWN, VK_CONTROL, 0)
    time.sleep(0.05)
    _send_win_msg(hwnd, win32con.WM_RBUTTONDOWN, 0, lparam)
    time.sleep(0.05)
    _send_win_msg(hwnd, win32con.WM_RBUTTONUP, 0, lparam)
    time.sleep(0.05)
    _send_win_msg(hwnd, win32con.WM_KEYUP, VK_CONTROL, 0)

def shift_click_at(hwnd, x, y):
    try:
        client_point = win32gui.ScreenToClient(hwnd, (int(x), int(y)))
    except: return
    lparam = make_lparam(client_point[0], client_point[1])
    
    reset_state(hwnd)
    
    _send_win_msg(hwnd, win32con.WM_KEYDOWN, VK_SHIFT, 0)
    _send_win_msg(hwnd, win32con.WM_LBUTTONDOWN, 1, lparam)
    time.sleep(0.05)
    _send_win_msg(hwnd, win32con.WM_LBUTTONUP, 0, lparam)
    _send_win_msg(hwnd, win32con.WM_KEYUP, VK_SHIFT, 0)

def alt_right_click_at(hwnd, x, y):
    try:
        client_point = win32gui.ScreenToClient(hwnd, (int(x), int(y)))
    except: return
    lparam = make_lparam(client_point[0], client_point[1])
    
    reset_state(hwnd)
    
    _send_win_msg(hwnd, win32con.WM_KEYDOWN, VK_MENU, 0)
    time.sleep(0.05)
    _send_win_msg(hwnd, win32con.WM_RBUTTONDOWN, 0, lparam)
    time.sleep(0.05)
    _send_win_msg(hwnd, win32con.WM_RBUTTONUP, 0, lparam)
    time.sleep(0.05)
    _send_win_msg(hwnd, win32con.WM_KEYUP, VK_MENU, 0)

# Adicionando funções auxiliares que faltavam no seu código anterior
def left_click_at(hwnd, x, y):
    """Clique Esquerdo Simples."""
    try:
        client_point = win32gui.ScreenToClient(hwnd, (int(x), int(y)))
    except: return
    lparam = make_lparam(client_point[0], client_point[1])
    
    acquire_mouse()
    try:
        reset_state(hwnd)
        _send_win_msg(hwnd, win32con.WM_LBUTTONDOWN, 1, lparam)
        time.sleep(0.05)
        _send_win_msg(hwnd, win32con.WM_LBUTTONUP, 0, lparam)
    finally:
        release_mouse()

def press_hotkey(hwnd, vk_key):
    # Não usamos reset_state aqui pra ser rápido, mas garantimos KeyUp
    _send_win_msg(hwnd, win32con.WM_KEYDOWN, vk_key, 0)
    time.sleep(0.05)
    _send_win_msg(hwnd, win32con.WM_KEYUP, vk_key, 0)