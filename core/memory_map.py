import struct
import time
from config import *

class MemoryTile:
    """Representa um único quadrado (Tile) lido da memória."""
    def __init__(self, item_ids):
        self.items = item_ids  # Lista de IDs (do fundo para o topo)
        self.count = len(item_ids)

    def get_top_item(self):
        """Retorna o ID do item no topo (último da lista), ou 0 se vazio."""
        if self.items:
            return self.items[-1]
        return 0
    
    def has_id(self, target_id):
        return target_id in self.items

class MemoryMap:
    def __init__(self, pm, base_addr):
        self.pm = pm
        self.base_addr = base_addr
        
        self.tiles = [None] * TOTAL_TILES
        
        self.center_index = -1
        self.offset_x = 0
        self.offset_y = 0
        self.offset_z = 0
        self.last_update = 0

    def read_full_map(self, player_id):
        try:
            map_start_addr = self.pm.read_int(self.base_addr + MAP_POINTER_ADDR)
            raw_data = self.pm.read_bytes(map_start_addr, MAP_DATA_SIZE)
            self._parse_map_data(raw_data, player_id)
            self.last_update = time.time()
            return True
        except Exception as e:
            print(f"[MemoryMap] Erro ao ler mapa: {e}")
            return False

    def _parse_map_data(self, raw_data, player_id):
        self.center_index = -1
        
        for i in range(TOTAL_TILES):
            offset = i * TILE_SIZE
            count = struct.unpack_from('<I', raw_data, offset)[0]
            
            if count > 10: count = 10
            
            items = []
            player_found_in_tile = False
            
            for j in range(count):
                item_offset = offset + 4 + (j * 12)
                
                # Lê 12 bytes: ID(4), Data1(4), Data2(4)
                # O ID real são apenas os primeiros 2 bytes (u16)
                raw_id_block, data1, data2 = struct.unpack_from('<III', raw_data, item_offset)
                
                # CORREÇÃO: Limpa o ID aplicando máscara de 16 bits
                real_id = raw_id_block & 0xFFFF
                
                items.append(real_id)
                
                # ID 99 (0x63) é o padrão para criaturas
                if real_id == 99 and data1 == player_id:
                    player_found_in_tile = True

            self.tiles[i] = MemoryTile(items)

            if player_found_in_tile:
                self.center_index = i
                self._calibrate_center(i)

    def _calibrate_center(self, index):
        z = index // (18 * 14)
        remainder = index % (18 * 14)
        y = remainder // 18
        x = remainder % 18
        
        self.offset_x = x - 8
        self.offset_y = y - 6
        self.offset_z = z

    def get_tile(self, rel_x, rel_y):
        if self.center_index == -1: return None 

        target_x = (8 + rel_x + self.offset_x) 
        target_y = (6 + rel_y + self.offset_y)
        
        final_x = target_x % 18
        final_y = target_y % 14
        final_z = self.offset_z 
        
        index = final_x + (final_y * 18) + (final_z * 18 * 14)
        
        if 0 <= index < TOTAL_TILES:
            return self.tiles[index]
        return None