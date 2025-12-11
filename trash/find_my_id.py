import pymem
import struct
from config import *

# Geometria
MAP_WIDTH = 18
MAP_HEIGHT = 14
SIZEOF_TILE = 172
FLOOR_SIZE = 43344

# O ID que você está pisando (Terra)
TARGET_ID = 103

def find_id_everywhere(pm):
    base_map = pm.read_int(MAP_POINTER_ADDR)
    
    print(f"--- CAÇANDO ID {TARGET_ID} NA MEMÓRIA ---")
    print("Isso vai verificar cada tile de cada andar carregado.\n")
    
    found = False
    
    for layer in range(8):
        layer_addr = base_map + (layer * FLOOR_SIZE)
        
        for y in range(MAP_HEIGHT):
            for x in range(MAP_WIDTH):
                
                # Offset do Tile
                idx = (y * MAP_WIDTH) + x
                tile_addr = layer_addr + (idx * SIZEOF_TILE)
                
                try:
                    # Lê Amount e ID
                    buff = pm.read_bytes(tile_addr, 8)
                    amount = struct.unpack_from('<I', buff, 0)[0]
                    
                    if amount > 0:
                        tid = struct.unpack_from('<I', buff, 4)[0]
                        
                        if tid == TARGET_ID:
                            print(f"[ACHEI!] Layer: {layer} | Grid X: {x} | Grid Y: {y}")
                            found = True
                            # Não damos break para ver se aparece em mais lugares (ex: chao em volta)
                            
                except:
                    pass
    
    if not found:
        print("❌ Não encontrei o ID 103 em lugar nenhum. Tem certeza que é 103?")
        print("Tente usar o 'Look' no chão para confirmar o ID.")

if __name__ == "__main__":
    try:
        pm = pymem.Pymem("Tibia.exe")
        find_id_everywhere(pm)
    except Exception as e:
        print(f"Erro: {e}")