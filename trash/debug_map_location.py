import pymem
import pymem.process
from config import *

# Candidatos a Endereço Base do Mapa (Relativos)
CANDIDATES = {
    "CONST_H (0x1D4C20)": 0x1D4C20,
    "ZION_GAMEMAP (0x146E74)": 0x146E74,
    "ZION_MINIMAP (0x147110)": 0x147110
}

# Estrutura
UNORDERED_MAP_SIZE = 0x18

def get_block_index(x, y, block_size):
    return int((y // block_size) * (65536 // block_size)) + int(x // block_size)

def check_address(pm, base_addr, name, offset, player_pos):
    print(f"\n🔍 Testando {name} no endereço relativo {hex(offset)}...")
    
    map_root = base_addr + offset
    
    # Calcula chaves esperadas para a posição do player
    px, py, pz = player_pos
    key_64 = get_block_index(px, py, 64)
    key_32 = get_block_index(px, py, 32)
    
    valid_floors = 0
    found_key = False
    
    # Varre os 16 andares possíveis
    for i in range(16):
        floor_addr = map_root + (i * UNORDERED_MAP_SIZE)
        try:
            # Lê cabeçalho do Hash Map
            size = pm.read_int(floor_addr + 0x4)
            buffer_ptr = pm.read_int(floor_addr + 0x14)
            
            if size > 0 and size < 100000 and buffer_ptr > 0x10000:
                valid_floors += 1
                
                # Tenta achar a chave do player neste andar
                # Varre os primeiros 50 buckets só pra ver
                for b in range(min(size, 50)):
                    node = pm.read_int(buffer_ptr + (b * 4))
                    while node != 0:
                        k = pm.read_int(node + 0x4)
                        if k == key_64:
                            print(f"   🎉 BINGO! Chave MINIMAP ({key_64}) encontrada no Andar {i}!")
                            found_key = True
                        if k == key_32:
                            print(f"   🎉 BINGO! Chave GAMEMAP ({key_32}) encontrada no Andar {i}!")
                            found_key = True
                        node = pm.read_int(node) # Next
                        
        except: pass
        
    if valid_floors > 0:
        print(f"   ✅ Estrutura válida detectada! ({valid_floors} andares com dados)")
        if found_key:
            print("   🌟 ESTE É O ENDEREÇO CORRETO! 🌟")
            return True
    else:
        print("   ❌ Endereço parece inválido ou vazio.")
        
    return False

def main():
    print("--- CAÇADOR DE ENDEREÇO DE MAPA ---")
    try:
        pm = pymem.Pymem(PROCESS_NAME)
        base_addr = pymem.process.module_from_name(pm.process_handle, PROCESS_NAME).lpBaseOfDll
    except: return

    # Pega Posição
    px = pm.read_int(base_addr + 0x1D16F0)
    py = pm.read_int(base_addr + 0x1D16EC)
    pz = pm.read_int(base_addr + 0x1D16E8)
    print(f"Player: {px}, {py}, {pz}")
    
    for name, off in CANDIDATES.items():
        if check_address(pm, base_addr, name, off, (px, py, pz)):
            print(f"\n>>> ATUALIZE SEU CONFIG.PY COM: OFFSET_MAP_POINTER = {hex(off)}")
            break

if __name__ == "__main__":
    main()