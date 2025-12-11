import pymem
import pymem.process
import time
from config import *
from auto_loot import scan_containers, get_gui_panels, find_scrollbar_recursive, OFFSET_UI_PARENT

def main():
    print("--- DIAGNÓSTICO DE SCROLL ANINHADO ---")
    try:
        pm = pymem.Pymem(PROCESS_NAME)
        base_addr = pymem.process.module_from_name(pm.process_handle, PROCESS_NAME).lpBaseOfDll
    except:
        print("Erro: Tibia não encontrado.")
        return

    # 1. Dados Lógicos (O que o Runemaker usa para achar o item)
    logical_containers = scan_containers(pm, base_addr)
    print(f"\n[1] CONTAINERS LÓGICOS (Memória do Inventário): {len(logical_containers)}")
    for cont in logical_containers:
        print(f"   Index {cont.index}: '{cont.name}' ({cont.amount} itens)")

    # 2. Dados Visuais (O que o Auto Loot usa para clicar/scrollar)
    gui_panels = get_gui_panels(pm, base_addr)
    
    # Filtra apenas containers reais (ID >= 64)
    valid_windows = []
    for p in gui_panels:
        try:
            parent_addr = pm.read_int(p['addr'] + OFFSET_UI_PARENT)
            parent_id = pm.read_int(parent_addr + 0x2C) 
            if parent_id >= 64:
                valid_windows.append(p)
        except: pass
        
    print(f"\n[2] JANELAS VISUAIS (GUI): {len(valid_windows)}")
    for i, win in enumerate(valid_windows):
        print(f"   Visual #{i}: Y={win['y']} | H={win['h']} | Addr={hex(win['addr'])}")

    # 3. Simulação do Mapeamento
    print("\n[3] TESTE DE MAPEAMENTO & SCROLL")
    
    if len(logical_containers) == 0 or len(valid_windows) == 0:
        print("❌ Dados insuficientes para mapear.")
        return

    # A lógica do bot é: Containers Lógicos são os ÚLTIMOS da lista Visual
    num_logical = len(logical_containers)
    num_visual = len(valid_windows)
    start_index = num_visual - num_logical
    
    print(f"   Offset de Mapeamento: {start_index}")
    
    for cont in logical_containers:
        # Qual janela visual corresponde a este container?
        target_gui_idx = start_index + cont.index
        
        print(f"\n   👉 Analisando Container {cont.index} ('{cont.name}'):")
        
        if 0 <= target_gui_idx < num_visual:
            target_win = valid_windows[target_gui_idx]
            print(f"      -> Mapeado para Janela Visual #{target_gui_idx} (Y={target_win['y']})")
            
            # Tenta achar o Scrollbar desta janela específica
            parent_addr = pm.read_int(target_win['addr'] + OFFSET_UI_PARENT)
            first_child = pm.read_int(parent_addr + 0x24)
            
            scroll_addr = find_scrollbar_recursive(pm, first_child)
            
            if scroll_addr != 0:
                scroll_val = pm.read_int(scroll_addr + 0x30)
                print(f"      ✅ SCROLLBAR ENCONTRADA! Addr: {hex(scroll_addr)}")
                print(f"         Valor Atual: {scroll_val}")
                
                # Teste de sanidade das dimensões
                w = pm.read_int(scroll_addr + 0x1C)
                h = pm.read_int(scroll_addr + 0x20)
                print(f"         Dimensões: {w}x{h}")
            else:
                print(f"      ❌ ERRO: Scrollbar NÃO encontrada nesta janela.")
                print(f"         (O bot não conseguirá rolar esta janela)")
        else:
            print(f"      ❌ ERRO DE MAPEAMENTO: Índice {target_gui_idx} não existe na lista visual!")

if __name__ == "__main__":
    main()