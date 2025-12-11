import pymem
import pymem.process
import struct
import sys

# --- CONFIGURAÇÃO ---
PROCESS_NAME = "Tibia.exe"

# ATUALIZE COM SUAS COORDENADAS E ENDEREÇO SE MUDOU
CURRENT_X = 32598
CURRENT_Y = 31720
CURRENT_Z = 7
KNOWN_TILE_ADDR = 0x2791114  # Endereço do tile onde você está (Count > 1)

# Estrutura
TILE_SIZE = 172
MAX_X = 18
MAX_Y = 14
MAX_Z = 8

def main():
    print(f"🕵️ CAÇADOR DE PONTEIRO FINAL")
    print(f"---------------------------")
    print(f"Alvo: Tile {hex(KNOWN_TILE_ADDR)} em {CURRENT_X},{CURRENT_Y},{CURRENT_Z}")
    
    try:
        pm = pymem.Pymem(PROCESS_NAME)
        mod = pymem.process.module_from_name(pm.process_handle, PROCESS_NAME)
        base_addr = mod.lpBaseOfDll
        exe_size = mod.SizeOfImage
        print(f"Base Module: {hex(base_addr)} | Size: {hex(exe_size)}")
    except:
        print("❌ Erro: Tibia não encontrado.")
        return

    # Lê toda a memória do executável para buscar rápido
    print("Lendo memória do executável...")
    try:
        exe_data = pm.read_bytes(base_addr, exe_size)
    except:
        print("Erro de leitura.")
        return

    # Índices parciais (X e Y)
    # Confirmamos Y Invertido: (13 - (y%14))
    idx_x = CURRENT_X % 18
    idx_y_inv = 13 - (CURRENT_Y % 14)
    
    print("\nTestando todas as rotações de Z...")
    
    found = False
    
    # Testa os 8 andares possíveis
    for z_shift in range(8):
        # Calcula qual seria o índice Z na memória para este shift
        # Ex: Se shift=0, global 7 vira mem 7. Se shift=7, global 7 vira mem 0 (comum).
        mem_z = (CURRENT_Z + z_shift) % 8
        
        # Fórmula: (Z_Mem * 252) + (Y_Inv * 18) + X
        tile_index = (mem_z * 252) + (idx_y_inv * 18) + idx_x
        
        # Calcula onde seria o início do mapa
        calculated_base = KNOWN_TILE_ADDR - (tile_index * TILE_SIZE)
        
        # Cria padrão de busca
        pat = struct.pack("<I", calculated_base)
        
        # Busca no dump
        try:
            offset_loc = exe_data.index(pat)
            pointer_addr = base_addr + offset_loc
            
            print("\n" + "█" * 60)
            print(f"🎉 PONTEIRO ENCONTRADO com Z-Shift={z_shift}!")
            print(f"   Base do Mapa: {hex(calculated_base)}")
            print(f"   Endereço do Ponteiro: {hex(pointer_addr)}")
            print(f"   >>> OFFSET FINAL: {hex(offset_loc)} <<<")
            print("█" * 60)
            
            # Salva a fórmula correta
            print("\n📝 Atualize seu map_core.py com esta fórmula:")
            print(f"def get_map_index(x, y, z):")
            print(f"    # Fórmula Y-Invertido com Z-Shift {z_shift}")
            print(f"    mem_z = (z + {z_shift}) % 8")
            print(f"    mem_y = 13 - (y % 14)")
            print(f"    mem_x = x % 18")
            print(f"    return (mem_z * 252) + (mem_y * 18) + mem_x")
            
            found = True
            # Não damos break pois pode haver múltiplos matches, mas geralmente o primeiro é o estático
            
        except ValueError:
            pass
            
    if not found:
        print("\n❌ Ainda nada. O endereço do tile pode ter mudado ou o ponteiro é multinível.")
        print("Se você tiver o Cheat Engine, procure por este valor agora:")
        # Calcula o valor mais provável (Shift 0 ou 7)
        # Vamos chutar Shift 0 para o log
        idx_guess = ((CURRENT_Z % 8) * 252) + (idx_y_inv * 18) + idx_x
        guess_base = KNOWN_TILE_ADDR - (idx_guess * TILE_SIZE)
        print(f"-> {hex(guess_base)}")

if __name__ == "__main__":
    main()