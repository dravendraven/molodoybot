import pymem
import pymem.process
import win32gui
import win32api
from config import *
from auto_loot import get_gui_panels # Reutiliza o scanner inteligente

def main():
    print("--- CALIBRADOR DE EQUIPAMENTOS ---")
    try:
        pm = pymem.Pymem(PROCESS_NAME)
        base_addr = pymem.process.module_from_name(pm.process_handle, PROCESS_NAME).lpBaseOfDll
    except:
        print("Erro: Tibia não encontrado.")
        return

    hwnd = win32gui.FindWindow("TibiaClient", None)
    if not hwnd: hwnd = win32gui.FindWindow(None, "Tibia")

    # 1. Acha a janela de Equipamentos
    panels = get_gui_panels(pm, base_addr)
    equip_window = None
    for p in panels:
        if 170 <= p['w'] <= 176 and 145 <= p['h'] <= 160:
            equip_window = p
            break
    
    if not equip_window:
        print("❌ Janela de Equipamentos não encontrada (W~172, H~151).")
        return

    # Calcula posição da janela na tela
    wx = equip_window['x']
    wy = equip_window['y']
    win_screen = win32gui.ClientToScreen(hwnd, (wx, wy))
    print(f"✅ Equipamentos detectados em Tela: {win_screen}")
    
    print("\nINSTRUÇÕES:")
    print("1. Coloque o mouse NO CENTRO DO SLOT solicitado.")
    print("2. Pressione ENTER aqui no terminal para capturar.")
    print("-" * 30)

    # --- LEFT HAND ---
    input("Posicione o mouse na MÃO ESQUERDA (Left) e dê Enter...")
    mx, my = win32api.GetCursorPos()
    off_x = mx - win_screen[0]
    off_y = my - win_screen[1]
    print(f"CAPTURED LEFT: ({off_x}, {off_y})")
    val_left = (off_x, off_y)

    # --- RIGHT HAND ---
    input("\nPosicione o mouse na MÃO DIREITA (Right) e dê Enter...")
    mx, my = win32api.GetCursorPos()
    off_x = mx - win_screen[0]
    off_y = my - win_screen[1]
    print(f"CAPTURED RIGHT: ({off_x}, {off_y})")
    val_right = (off_x, off_y)

    # --- AMMO ---
    input("\nPosicione o mouse na AMMO (Flecha) e dê Enter...")
    mx, my = win32api.GetCursorPos()
    off_x = mx - win_screen[0]
    off_y = my - win_screen[1]
    print(f"CAPTURED AMMO: ({off_x}, {off_y})")
    val_ammo = (off_x, off_y)

    print("\n" + "="*30)
    print("COPIE E COLE NO SEU INVENTORY_CORE.PY:")
    print("coords = {")
    print(f'    "left":  {val_left},')
    print(f'    "right": {val_right},')
    print(f'    "ammo":  {val_ammo}')
    print("}")
    print("="*30)

if __name__ == "__main__":
    main()
    