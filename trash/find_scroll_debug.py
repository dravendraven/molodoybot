import pymem
import pymem.process
import time
from config import *
from auto_loot import get_gui_panels

# Offsets
OFF_PARENT = 0x0C
OFF_CHILD  = 0x24
OFF_NEXT   = 0x10
OFF_ID     = 0x2C

def get_family_tree(pm, root_addr):
    """Mapeia a família e guarda o Pai de cada um para rastreamento reverso."""
    family = {} # {filho: pai}
    
    # Adiciona a raiz
    family[root_addr] = 0 
    
    queue = [root_addr]
    visited = set()
    
    while queue:
        curr = queue.pop(0)
        if curr in visited: continue
        visited.add(curr)
        
        try:
            # Filhos
            child = pm.read_int(curr + OFF_CHILD)
            while child != 0:
                if child not in family:
                    family[child] = curr # Registra quem é o pai
                    queue.append(child)
                child = pm.read_int(child + OFF_NEXT)
        except: pass
        
    return family

def trace_path(family_map, target_addr, root_addr):
    """Reconstrói o caminho do Root até o Target."""
    path = []
    curr = target_addr
    while curr != 0 and curr != root_addr:
        parent = family_map.get(curr, 0)
        if parent == 0: break
        
        # Descobre qual 'filho' ou 'irmão' ele é
        # (Simplificação: Apenas dizemos que é um descendente)
        path.append(hex(curr))
        curr = parent
        
    if curr == root_addr:
        path.append("BACKPACK_ROOT")
        return " -> ".join(reversed(path))
    return "Caminho desconhecido"

def get_snapshot(pm, family_map):
    snap = {}
    for addr in family_map.keys():
        try:
            # Lê 0x50 bytes (cobre até o offset 0x44)
            snap[addr] = pm.read_bytes(addr, 0x50)
        except: pass
    return snap

def compare_triangular(snap_top1, snap_down, snap_top2):
    print("\n--- ANÁLISE TRIANGULAR (TOPO -> BAIXO -> TOPO) ---")
    found_candidates = []
    
    for addr in snap_top1:
        if addr not in snap_down or addr not in snap_top2: continue
        
        b_top1 = snap_top1[addr]
        b_down = snap_down[addr]
        b_top2 = snap_top2[addr]
        
        for i in range(0, 0x50, 4):
            val_top1 = int.from_bytes(b_top1[i:i+4], 'little', signed=True)
            val_down = int.from_bytes(b_down[i:i+4], 'little', signed=True)
            val_top2 = int.from_bytes(b_top2[i:i+4], 'little', signed=True)
            
            # Lógica: Valor mudou ao descer, e voltou ao original (ou quase) ao subir
            if val_top1 != val_down:
                # Verifica se voltou ao valor original (tolerância de 1)
                if abs(val_top1 - val_top2) <= 1:
                    print(f"🔥 CANDIDATO PERFEITO: {hex(addr)} | Offset {hex(i)}")
                    print(f"   Topo1: {val_top1} -> Baixo: {val_down} -> Topo2: {val_top2}")
                    found_candidates.append((addr, i))
                elif i == 0x30: # Destaque especial para o 0x30 que suspeitamos
                    print(f"⚠️ Mudança em 0x30 (mas não voltou exato?): {val_top1} -> {val_down} -> {val_top2}")

    return found_candidates

def main():
    try:
        pm = pymem.Pymem(PROCESS_NAME)
        base_addr = pymem.process.module_from_name(pm.process_handle, PROCESS_NAME).lpBaseOfDll
    except: return

    # 1. Acha Backpack
    panels = get_gui_panels(pm, base_addr)
    bp_addr = 0
    for p in reversed(panels):
        try:
            parent = pm.read_int(p['addr'] + 0x0C)
            pid = pm.read_int(parent + 0x2C)
            if pid >= 64:
                bp_addr = parent
                break
        except: pass
        
    if bp_addr == 0:
        print("❌ Abra uma Backpack.")
        return

    print(f"✅ Backpack: {hex(bp_addr)}")
    
    # 2. Mapeia Família
    family_map = get_family_tree(pm, bp_addr)
    print(f"Monitorando {len(family_map)} objetos...")

    # 3. Sequência de Teste
    print("\n1️⃣  Coloque o Scroll no TOPO. (Enter)")
    input()
    snap_1 = get_snapshot(pm, family_map)
    
    print("\n2️⃣  Role TUDO para BAIXO. (Enter)")
    input()
    snap_2 = get_snapshot(pm, family_map)
    
    print("\n3️⃣  Volte o Scroll para o TOPO. (Enter)")
    input()
    snap_3 = get_snapshot(pm, family_map)
    
    # 4. Análise
    candidates = compare_triangular(snap_1, snap_2, snap_3)
    
    if candidates:
        print("\n--- RASTREAMENTO DE PONTEIRO ---")
        for addr, offset in candidates:
            path = trace_path(family_map, addr, bp_addr)
            print(f"Objeto {hex(addr)} (Offset {hex(offset)})")
            print(f"Caminho: {path}")
            
            # Tenta identificar qual filho ele é (Index)
            # Se for filho direto da BP:
            if family_map.get(addr) == bp_addr:
                # Descobre qual índice de filho ele é
                child = pm.read_int(bp_addr + OFF_CHILD)
                idx = 0
                while child != 0:
                    if child == addr:
                        print(f"📌 LOCALIZAÇÃO: Ele é o FILHO #{idx} da Backpack!")
                        break
                    child = pm.read_int(child + OFF_NEXT)
                    idx += 1
    else:
        print("Nenhum candidato perfeito encontrado.")

if __name__ == "__main__":
    main()