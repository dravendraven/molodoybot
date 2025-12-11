import pymem
import struct
import os
import time
from config import * # Seus endereços (MAP_POINTER_ADDR, etc)

# ==============================================================================
# CONFIGURAÇÃO DE CENTRO (Confirmada por você)
# ==============================================================================
CENTER_X = 10
CENTER_Y = 6

# Geometria da Memória
MAP_WIDTH   = 18
SIZEOF_TILE = 172
FLOOR_SIZE  = 43344

def inspect_center_stack(pm):
    # 1. Ler Base Address
    try:
        base_map = pm.read_int(MAP_POINTER_ADDR)
        pz = pm.read_int(PLAYER_Z_ADDRESS)
    except:
        print("Erro ao ler ponteiros básicos. Tibia fechado?")
        return

    # 2. Calcular Layer da Memória
    layer = pz - 6
    if layer < 0: layer = 0
    if layer > 7: layer = 7

    # 3. Calcular Endereço do Tile Central
    # Offset do Andar
    layer_offset = layer * FLOOR_SIZE
    
    # Offset do Tile (Row-Major: Y * Width + X)
    tile_index = (CENTER_Y * MAP_WIDTH) + CENTER_X
    tile_offset = tile_index * SIZEOF_TILE
    
    final_addr = base_map + layer_offset + tile_offset

    # 4. Ler o Tile Completo (172 Bytes)
    try:
        buff = pm.read_bytes(final_addr, SIZEOF_TILE)
    except Exception as e:
        print(f"Erro ao ler memória: {e}")
        return

    # 5. Decodificar a Stack
    # Primeiros 4 bytes = Quantidade de itens
    amount = struct.unpack_from('<I', buff, 0)[0]

    print("-" * 50)
    print(f"🔍 INSPEÇÃO DE TILE (Centro X:{CENTER_X}, Y:{CENTER_Y} | Z:{pz})")
    print(f"📍 Endereço Memória: {hex(final_addr)}")
    print(f"📦 Itens na Stack: {amount}")
    print("-" * 50)

    if amount == 0:
        print("⚠️  Tile vazio (Amount = 0). Isso é estranho se você estiver pisando nele.")
        return

    # O jogo guarda até ~14 itens na struct fixa
    safe_count = min(amount, 14)
    read_offset = 4 # Começa após o 'amount'

    for i in range(safe_count):
        # Cada objeto tem 12 bytes: [ID (4b)] [Data (4b)] [DataEx (4b)]
        item_id = struct.unpack_from('<I', buff, read_offset)[0]
        item_data = struct.unpack_from('<I', buff, read_offset + 4)[0]
        
        # Formatação
        tipo = "TERRENO (CHÃO)" if i == 0 else f"OBJETO (Stack {i})"
        obs = ""
        
        # Dicas automáticas
        if item_id in [2595, 2596]: obs = " <- PARCEL?"
        if item_id == 352: obs = " <- CAVERNA"
        
        print(f"[{i}] {tipo:<15} | ID: {item_id:<5} | Data: {item_data} {obs}")

        read_offset += 12 # Pula para o próximo item

    print("-" * 50)
    print("DICA: Adicione os IDs de 'OBJETO' na lista OBSTACLE_IDS do map_reader.py")

if __name__ == "__main__":
    try:
        pm = pymem.Pymem("Tibia.exe")
        print("Conectado! Pressione ENTER para ler o tile atual.")
        
        while True:
            inspect_center_stack(pm)
            input("\n[ENTER] Atualizar leitura...")
            os.system('cls' if os.name == 'nt' else 'clear')
            
    except Exception as e:
        print(f"Erro crítico: {e}")