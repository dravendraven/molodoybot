import pymem
import struct
from config import *

# Geometria
MAP_WIDTH = 18
SIZEOF_TILE = 172
FLOOR_SIZE = 43344

# Use o centro que definimos como correto na última conversa
# Se você não atualizou o config.py, altere aqui manualmente para testar
SCAN_X = 10
SCAN_Y = 6

def scan_layers():
    try:
        pm = pymem.Pymem("Tibia.exe")
        base_map = pm.read_int(MAP_POINTER_ADDR)
        player_z = pm.read_int(PLAYER_Z_ADDRESS)
        
        print(f"--- DIAGNÓSTICO DE CAMADAS (Z Player: {player_z}) ---")
        print(f"Lendo o tile central [{SCAN_X}, {SCAN_Y}] em todas as camadas...\n")
        
        for layer in range(8):
            # Calcula endereço do tile central nesta camada
            layer_offset = layer * FLOOR_SIZE
            tile_offset = ((SCAN_Y * MAP_WIDTH) + SCAN_X) * SIZEOF_TILE
            addr = base_map + layer_offset + tile_offset
            
            try:
                # Lê o ID do chão
                buff = pm.read_bytes(addr, 8)
                amount = struct.unpack_from('<I', buff, 0)[0]
                
                if amount > 0:
                    tid = struct.unpack_from('<I', buff, 4)[0]
                    print(f"[Layer {layer}] ID Encontrado: {tid} (Amount: {amount})")
                else:
                    print(f"[Layer {layer}] Vazio (0)")
                    
            except Exception as e:
                print(f"[Layer {layer}] Erro de leitura")

        print("\nCONCLUSÃO:")
        print("Procure na lista acima o ID do chão onde seu char está pisando.")
        print("O número da [Layer X] é o que precisamos usar no map_reader.")

    except Exception as e:
        print(f"Erro ao conectar: {e}")

if __name__ == "__main__":
    scan_layers()