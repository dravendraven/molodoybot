import time
import pymem
from config import *
from map_core import get_screen_coord
from input_core import shift_click_at
from mouse_lock import acquire_mouse, release_mouse

def scan_tile(pm, base_addr, hwnd, gv, rel_x, rel_y):
    """
    Realiza um 'Look' (Shift+Click) no tile relativo (dx, dy)
    e retorna o ID do item que apareceu na memória (Last Interaction).
    
    Retorna: (int) ItemID ou 0 se falhar.
    """
    try:
        # 1. Calcula onde clicar na tela
        tx, ty = get_screen_coord(gv, rel_x, rel_y, hwnd)
        
        # 2. Executa o clique físico com segurança (Mouse Lock)
        acquire_mouse()
        try:
            shift_click_at(hwnd, tx, ty)
        finally:
            release_mouse()
        
        # 3. Aguarda o cliente processar e atualizar a memória
        # (Ajustável conforme o ping, 350ms é seguro para maioria)
        time.sleep(0.35) 
        
        # 4. Lê o ID da memória "Last Interaction"
        # Garante que lê o offset correto definido no config ou usa padrão
        offset = globals().get('OFFSET_LAST_INTERACTION_ID', 0x31C630)
        item_id = pm.read_int(base_addr + offset)
        
        return item_id
        
    except Exception as e:
        print(f"[SCANNER] Erro ao escanear {rel_x},{rel_y}: {e}")
        return 0