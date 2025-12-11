import pymem
import pymem.process
from config import *

# --- ATUALIZE AQUI COM OS VALORES DO SEU CHEAT ENGINE ---
# Endereço da Janela da Backpack (Container Pai)
BP_ADDR_TARGET = 0x2c0be00  
# Endereço do Objeto de Scroll (onde o offset 0x30 funciona)
SCROLL_ADDR_TARGET = 0x2c3aa90
# --------------------------------------------------------

OFF_CHILD = 0x24
OFF_NEXT  = 0x10

def find_path_indices_safe(pm, current_addr, target_addr, path=[], visited=None):
    if visited is None: visited = set()
    
    # Evita loops e endereços inválidos
    if current_addr == 0 or current_addr in visited: return None
    visited.add(current_addr)
    
    # Achou!
    if current_addr == target_addr:
        return path
    
    try:
        # Varre filhos (Lista Encadeada Horizontal)
        child = pm.read_int(current_addr + OFF_CHILD)
        idx = 0
        
        # Limite de segurança para não travar em listas infinitas
        while child != 0 and idx < 100:
            if child not in visited:
                # Tenta descer neste filho
                result = find_path_indices_safe(pm, child, target_addr, path + [idx], visited)
                if result: return result
            
            # Próximo irmão
            child = pm.read_int(child + OFF_NEXT)
            idx += 1
            
    except Exception as e:
        # Se der erro de leitura, apenas ignora este ramo e continua
        return None
        
    return None

def main():
    print("--- RASTREADOR DE CAMINHO (SEGURO) ---")
    try:
        pm = pymem.Pymem(PROCESS_NAME)
    except: 
        print("Tibia não encontrado.")
        return

    print(f"Buscando caminho de {hex(BP_ADDR_TARGET)} até {hex(SCROLL_ADDR_TARGET)}...")
    
    # Aumenta o limite de recursão para garantir
    import sys
    sys.setrecursionlimit(2000)
    
    path = find_path_indices_safe(pm, BP_ADDR_TARGET, SCROLL_ADDR_TARGET)
    
    if path:
        print(f"\n✅ CAMINHO ENCONTRADO: {path}")
        print(f"Significado: A partir da BP, pegue o filho {path} sequencialmente.")
        
        print("\nExemplo de Código para resetar o scroll:")
        print("current = bp_addr")
        for i, idx in enumerate(path):
            print(f"# Passo {i+1}: Pegar Filho índice {idx}")
            print(f"current = get_child_at_index(pm, current, {idx})")
        print("pm.write_int(current + 0x30, 0) # Resetar Scroll")
        
    else:
        print("❌ Caminho não encontrado. Verifique se os endereços estão corretos e se a janela ainda está aberta.")

if __name__ == "__main__":
    main()