import struct
import time
from config import *

class MemoryTile:
    """Representa um único quadrado (Tile) lido da memória."""
    def __init__(self, item_ids, items_debug=None):
        self.items = item_ids  # Lista de IDs
        self.count = len(item_ids)
        self.items_debug = items_debug or []  # DEBUG: (id, data1, data2, raw_id_block)

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
        self.is_calibrated = False  # Flag para validar se calibração foi bem-sucedida

    def read_full_map(self, player_id):
        # Reseta flag de calibração antes de cada leitura
        self.is_calibrated = False

        try:
            map_start_addr = self.pm.read_int(self.base_addr + MAP_POINTER_ADDR)
            raw_data = self.pm.read_bytes(map_start_addr, MAP_DATA_SIZE)
            self._parse_map_data(raw_data, player_id)
            self.last_update = time.time()

            # Só marca como calibrado se encontrou o player no mapa
            if self.center_index != -1:
                self.is_calibrated = True
                return True
            else:
                print(f"[MemoryMap] ⚠️ Calibração falhou: Player ID {player_id} não encontrado no mapa")
                return False

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
            items_debug = []  # DEBUG: armazena info completa
            player_found_in_tile = False

            for j in range(count):
                item_offset = offset + 4 + (j * 12)

                # Lê 12 bytes: ID(4), Data1(4), Data2(4)
                # O ID real são apenas os primeiros 2 bytes (u16)
                raw_id_block, data1, data2 = struct.unpack_from('<III', raw_data, item_offset)

                # CORREÇÃO: Limpa o ID aplicando máscara de 16 bits
                real_id = raw_id_block & 0xFFFF

                items.append(real_id)
                items_debug.append((real_id, data1, data2, raw_id_block))
                
                # ID 99 (0x63) é o padrão para criaturas
                if real_id == 99 and data1 == player_id:
                    player_found_in_tile = True

            self.tiles[i] = MemoryTile(items, items_debug)

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
        if not self.is_calibrated or self.center_index == -1:
            return None

        target_x = 8 + rel_x + self.offset_x
        target_y = 6 + rel_y + self.offset_y

        if not (0 <= target_x < 18 and 0 <= target_y < 14):
            return None

        index = target_x + (target_y * 18) + (self.offset_z * 252)

        if 0 <= index < TOTAL_TILES:
            return self.tiles[index]
        return None

    def get_tile_visible(self, rel_x, rel_y):
        """
        Retorna o tile na posição relativa (rel_x, rel_y) ao player, com suporte a chunks adjacentes.

        IMPORTANTE: Leituras confiáveis apenas para |rel_x| <= 7 e |rel_y| <= 7.
        Tiles além desse range podem ser lidos incorretamente devido a wrap-around.

        Retorna None apenas se dados de memória não forem válidos.
        """
        from config import DEBUG_MEMORY_MAP

        # Validação de calibração
        if not self.is_calibrated or self.center_index == -1:
            return None

        # ===== NOVO: VALIDAÇÃO DE RANGE =====
        # Tiles visíveis na tela: -7 a +7 (15x15 aprox)
        # Além disso, wrap-around pode ler tiles errados
        MAX_RELIABLE_RANGE = 7

        if abs(rel_x) > MAX_RELIABLE_RANGE or abs(rel_y) > MAX_RELIABLE_RANGE:
            if DEBUG_MEMORY_MAP:
                print(f"[MemoryMap] ⚠️ AVISO: Leitura de tile FORA DO RANGE CONFIÁVEL!")
                print(f"[MemoryMap]   Coordenada relativa: ({rel_x}, {rel_y})")
                print(f"[MemoryMap]   Range confiável: ±{MAX_RELIABLE_RANGE} SQM")
                print(f"[MemoryMap]   Retornando: None (não confiável)")
            return None  # Retorna None para indicar que tile não é confiável

        # Cálcula a posição no chunk atual
        target_x = 8 + rel_x + self.offset_x
        target_y = 6 + rel_y + self.offset_y

        # ===== NOVO: LOG DE DEBUG =====
        if DEBUG_MEMORY_MAP and (abs(rel_x) > 5 or abs(rel_y) > 5):
            print(f"[MemoryMap] Leitura de tile distante:")
            print(f"[MemoryMap]   rel=({rel_x}, {rel_y})")
            print(f"[MemoryMap]   offset=({self.offset_x}, {self.offset_y})")
            print(f"[MemoryMap]   target=({target_x}, {target_y})")

        # Usa wrap-around para cobrir chunks adjacentes
        # Tiles visíveis na tela podem estar em chunks diferentes
        final_x = target_x % 18
        final_y = target_y % 14
        final_z = self.offset_z

        # ===== NOVO: LOG DE WRAP-AROUND =====
        if DEBUG_MEMORY_MAP and (abs(rel_x) > 5 or abs(rel_y) > 5):
            print(f"[MemoryMap]   final=({final_x}, {final_y}) [após wrap]")

        # Cálcula índice com wrap-around
        index = final_x + (final_y * 18) + (final_z * 18 * 14)

        if 0 <= index < TOTAL_TILES and self.tiles[index]:
            tile = self.tiles[index]

            # ===== NOVO: LOG DA PILHA DE ITEMS =====
            if DEBUG_MEMORY_MAP and (abs(rel_x) > 5 or abs(rel_y) > 5):
                print(f"[MemoryMap]   index={index}")
                print(f"[MemoryMap]   items={tile.items if tile else 'None'}")

            return tile

        return None