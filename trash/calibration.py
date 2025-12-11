import pymem
import struct
import os
import time

# ==============================================================================
# CONFIGURAÇÃO INICIAL (Ajuste aqui até o X bater com seu char)
# ==============================================================================
# Tentativa calculada: X=10 (8+2), Y=6 (Mantido)
OFF_X = 10 
OFF_Y = 6

# ==============================================================================
# DADOS DO SISTEMA
# ==============================================================================
MAP_POINTER_ADDR = 0x005D4C20 
PLAYER_Z_ADDR    = 0x005D16E8
MAP_WIDTH   = 18
MAP_HEIGHT  = 14
SIZEOF_TILE = 172
FLOOR_SIZE  = MAP_WIDTH * MAP_HEIGHT * SIZEOF_TILE

def print_calibration_grid(pm):
    try:
        base_map = pm.read_int(MAP_POINTER_ADDR)
        pz = pm.read_int(PLAYER_Z_ADDR)
        
        # Converte Z Global para Layer de Memória (Z=8 -> Layer 2)
        layer = pz - 6 
        if layer < 0: layer = 0
        if layer > 7: layer = 7
        
        layer_addr = base_map + (layer * FLOOR_SIZE)
        
        os.system('cls' if os.name == 'nt' else 'clear')
        print(f"--- CALIBRAGEM DE CENTRO ---")
        print(f"Z Player: {pz} | Layer Memória: {layer}")
        print(f"Testando Centro: X={OFF_X}, Y={OFF_Y}")
        print(f"O '[ ]' deve estar no ID do chão onde você pisa.\n")

        # Cabeçalho das Colunas
        header = "    " + "".join([f"{x:^5}" for x in range(MAP_WIDTH)])
        print(header)

        for y in range(MAP_HEIGHT):
            row_str = f"{y:2} |"
            
            for x in range(MAP_WIDTH):
                # Leitura do Tile
                idx = (y * MAP_WIDTH) + x
                addr = layer_addr + (idx * SIZEOF_TILE)
                
                try:
                    buff = pm.read_bytes(addr, 8)
                    amount = struct.unpack_from('<I', buff, 0)[0]
                    tid = struct.unpack_from('<I', buff, 4)[0] if amount > 0 else 0
                except:
                    tid = 0
                
                # Formatação Visual
                if x == OFF_X and y == OFF_Y:
                    # ESTE É O CENTRO CALCULADO - DESTAQUE TOTAL
                    cell = f"[{tid}]"
                else:
                    cell = f" {tid} "
                
                row_str += f"{cell:^5}"
            
            print(row_str)
            
    except Exception as e:
        print(f"Erro: {e}")

if __name__ == "__main__":
    pm = pymem.Pymem("Tibia.exe")
    while True:
        print_calibration_grid(pm)
        print("\nSe o ID entre [colchetes] não for o seu chão:")
        print("1. Olhe na matriz onde está o seu ID verdadeiro.")
        print("2. Veja o número da COLUNA (topo) e LINHA (esquerda).")
        print("3. Altere OFF_X e OFF_Y no script.")
        time.sleep(1)