import time
from config import *
from map_core import get_game_view, get_screen_coord
from input_core import shift_click_at
from mouse_lock import acquire_mouse, release_mouse

def scan_fishing_spots(pm, base_addr, hwnd, radius=3):
    """
    Sonda a área usando Shift+Click (Look) para encontrar água.
    Retorna lista de coordenadas (dx, dy).
    """
    valid_spots = []
    
    gv = get_game_view(pm, base_addr)
    if not gv:
        print("Erro no GameView.")
        return []

    print(f"Iniciando Sonar (Raio {radius})...")
    
    # Varre uma área quadrada ao redor do char
    for dy in range(-radius, radius + 1):
        for dx in range(-radius, radius + 1):
            
            # Ignora o próprio char
            if dx == 0 and dy == 0: continue
            
            # Calcula onde clicar na tela
            screen_x, screen_y = get_screen_coord(gv, dx, dy, hwnd)
            
            # --- AÇÃO DE SONAR ---
            acquire_mouse()
            try:
                # Usa Shift+Click (Look) - Não move o char!
                shift_click_at(hwnd, screen_x, screen_y)
            finally:
                release_mouse()
            
            # Delay para a memória atualizar (Ping dependent)
            time.sleep(0.15)
            
            # Lê o ID resultante
            found_id = pm.read_int(base_addr + OFFSET_LAST_INTERACTION_ID)
            
            # Verifica se é água
            if found_id in WATER_IDS:
                print(f"🎣 Água em ({dx}, {dy}) - ID: {found_id}")
                valid_spots.append((dx, dy))
            
            # Pequena pausa para não sobrecarregar inputs
            time.sleep(0.05)
            
    print(f"Sonar finalizado. {len(valid_spots)} locais encontrados.")
    return valid_spots