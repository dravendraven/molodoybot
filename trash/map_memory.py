import pymem
from config import *

# Estrutura do Tibia Map (Hash Map)
# Baseado em Map.cs e Minimap.cs do ZionBot
MINIMAP_BLOCK_SIZE = 64
UNORDERED_MAP_SIZE = 0x18 # Tamanho da struct de cada andar
VALUE_OFFSET = 0x10       # Onde estão os dados do tile dentro do nó (Minimap.cs diz VALUE_OFFSET = 0x10)

def get_map_start_addr(pm, base_addr):
    """
    Lê o ponteiro mestre que aponta para o início do array de mapas.
    Esta foi a peça que faltava!
    """
    return pm.read_int(base_addr + OFFSET_MAP_POINTER)

def get_floor_map_addr(map_start_addr, z):
    """
    O mapa é um array de 16 andares (0 a 15).
    Retorna o endereço da estrutura do andar Z.
    """
    # O Z do Tibia (0-15) mapeia diretamente para o array.
    return map_start_addr + (z * UNORDERED_MAP_SIZE)

def get_block_index(x, y):
    """Calcula o ID do Bloco 64x64 (Lógica do Map.cs)."""
    return int((y // MINIMAP_BLOCK_SIZE) * (65536 // MINIMAP_BLOCK_SIZE)) + int(x // MINIMAP_BLOCK_SIZE)

def get_tile_index(x, y):
    """Calcula o índice do tile (0-4095) dentro do bloco."""
    return int(((y % MINIMAP_BLOCK_SIZE) * MINIMAP_BLOCK_SIZE) + (x % MINIMAP_BLOCK_SIZE))

def get_tile_block_address(pm, floor_map_addr, block_index):
    """
    Navega na Hash Table do andar para encontrar o Bloco de Tiles.
    Traduzido de Map.cs -> GetTileBlock
    """
    try:
        # 1. Lê Tamanho e Buffer do Hash Map
        buffer_size = pm.read_int(floor_map_addr + 0x4)
        buffer_address = pm.read_int(floor_map_addr + 0x14)
        
        if buffer_size == 0 or buffer_address == 0:
            return 0
            
        # 2. Hash Function (Modulo)
        bucket_index = block_index % buffer_size
        array_offset = bucket_index * 4 # Cada ponteiro tem 4 bytes
        
        # 3. Pega o primeiro nó da lista encadeada neste bucket
        node_address = pm.read_int(buffer_address + array_offset)
        
        # 4. Percorre a lista procurando a chave (Block Index)
        loops = 0
        while node_address != 0 and loops < 50:
            node_key = pm.read_int(node_address + 0x4) # Key fica no 0x4
            
            if node_key == block_index:
                # Achou! O endereço dos dados do tile é Node + VALUE_OFFSET
                return node_address + VALUE_OFFSET
                
            # Vai para o próximo nó (primeiros 4 bytes são o ponteiro Next)
            node_address = pm.read_int(node_address)
            loops += 1
            
        return 0
    except:
        return 0

def get_tile_flags(pm, base_addr, x, y, z):
    """
    Lê os dados do tile na coordenada global X,Y,Z.
    Retorna: {is_walkable, speed, color, is_stairs}
    """
    try:
        # 1. Pega o endereço base do mapa (Dinâmico)
        map_start = get_map_start_addr(pm, base_addr)
        if map_start == 0: return None
        
        # 2. Pega a estrutura do andar
        floor_addr = get_floor_map_addr(map_start, z)
        
        # 3. Busca o Bloco 64x64
        block_idx = get_block_index(x, y)
        block_addr = get_tile_block_address(pm, floor_addr, block_idx)
        
        if block_addr == 0:
            return None # Área não explorada (Preto)
            
        # 4. Lê o Tile específico
        # Estrutura do Tile (Minimap.cs): [Flags][Color][Speed] (3 bytes)
        tile_idx = get_tile_index(x, y)
        final_addr = block_addr + (tile_idx * 3)
        
        data = pm.read_bytes(final_addr, 3)
        flags = data[0]
        color = data[1]
        speed = data[2]
        
        # Lógica do ZionBot (Minimap.cs):
        # isWalkable = !((Flags & 4) == 4)
        is_walkable = not ((flags & 4) == 4)
        
        # isStairs = (Color == 210)
        is_stairs = (color == 210)
        
        return {
            "is_walkable": is_walkable,
            "is_stairs": is_stairs,
            "speed": speed,
            "color": color,
            "flags": flags
        }
    except:
        return None