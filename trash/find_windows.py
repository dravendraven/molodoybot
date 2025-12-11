import pymem
import pymem.process
import win32gui
from config import *

# Offsets baseados em GUIItem e GUIHolder do uitibia.h
OFFSET_UI_CHILD  = 0x24
OFFSET_UI_NEXT   = 0x10
OFFSET_UI_ID     = 0x30
OFFSET_UI_OFFSET_X = 0x14
OFFSET_UI_OFFSET_Y = 0x18

def get_absolute_position(pm, item_addr):
    """Calcula posição absoluta para ajudar a identificar visualmente."""
    abs_x, abs_y = 0, 0
    curr = item_addr
    for _ in range(20):
        if curr == 0: break
        abs_x += pm.read_int(curr + OFFSET_UI_OFFSET_X)
        abs_y += pm.read_int(curr + OFFSET_UI_OFFSET_Y)
        curr = pm.read_int(curr + 0x0C) # Parent
    return abs_x, abs_y

def scan_branch(pm, start_node, path_name, depth=0):
    """
    Varre recursivamente uma árvore de GUI procurando Battle ou BPs.
    """
    if start_node == 0 or depth > 10: return

    current = start_node
    count = 0
    
    # Itera sobre os irmãos (Linked List)
    while current != 0 and count < 50:
        try:
            # Lê ID
            ui_id = pm.read_int(current + OFFSET_UI_ID)
            
            # Lê Dimensões (para filtrar lixo)
            w = pm.read_int(current + 0x1C)
            h = pm.read_int(current + 0x20)
            
            # --- FILTRO DE OURO ---
            is_interesting = False
            label = ""
            
            if ui_id == 7:
                is_interesting = True
                label = "✅ BATTLE LIST ENCONTRADA!"
            elif ui_id >= 64 and w > 100: # W > 100 filtra ícones pequenos
                is_interesting = True
                label = f"✅ CONTAINER (BP) ENCONTRADO! (ID: {ui_id})"
            
            if is_interesting:
                abs_x, abs_y = get_absolute_position(pm, current)
                print(f"\n{label}")
                print(f"   Caminho: {path_name} -> Node {count}")
                print(f"   Endereço: {hex(current)}")
                print(f"   Posição: X={abs_x}, Y={abs_y} | Tamanho: {w}x{h}")
                print("   ------------------------------------------------")

            # Recursão: Verifica filhos deste nó
            child = pm.read_int(current + OFFSET_UI_CHILD)
            if child != 0:
                # Otimização: Só aprofunda se o objeto parecer um container/painel
                scan_branch(pm, child, f"{path_name} -> Node{count}", depth + 1)

            # Próximo irmão
            current = pm.read_int(current + OFFSET_UI_NEXT)
            count += 1
            
        except:
            break

def main():
    print("--- CAÇADOR DE JANELAS (BATTLE & BP) ---")
    try:
        pm = pymem.Pymem(PROCESS_NAME)
        base_addr = pymem.process.module_from_name(pm.process_handle, PROCESS_NAME).lpBaseOfDll
    except:
        print("Tibia não encontrado.")
        return

    gui_ptr = pm.read_int(base_addr + OFFSET_GUI_POINTER)
    print(f"GUI Pointer: {hex(gui_ptr)}")
    print("Iniciando varredura profunda...")

    # Lista de Offsets para testar na raiz do GUI
    # 0x30 (Game), 0x34 (Player?), 0x38 (Static), 0x3C (FirstChild?), 0x40 (Chat)
    # E também 0x24 (Filhos diretos do GUI)
    potential_roots = {
        0x24: "GUI->m_child",
        0x30: "GUI->m_game",
        0x34: "GUI->m_player",
        0x38: "GUI->m_container (Static)",
        0x3C: "GUI->m_0x3C (Unknown)",
        0x40: "GUI->m_chat",
        0x44: "GUI->m_resize"
    }

    for offset, name in potential_roots.items():
        root_addr = pm.read_int(gui_ptr + offset)
        if root_addr != 0:
            # print(f"Varrendo raiz: {name} ({hex(root_addr)})")
            scan_branch(pm, root_addr, name)

    print("\nVarredura concluída.")

if __name__ == "__main__":
    main()