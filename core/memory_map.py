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
        
        # Cache da matriz de tiles (indices 0 a 2015)
        self.tiles = [None] * TOTAL_TILES
        
        # Offsets de calibração (onde estou na matriz?)
        self.center_index = -1
        self.offset_x = 0
        self.offset_y = 0
        self.offset_z = 0
        
        # Última atualização
        self.last_update = 0

    def read_full_map(self, player_id):
        """
        Lê a matriz inteira do mapa da memória e calibra a posição do jogador.
        Deve ser chamado a cada frame ou a cada X ms.
        """
        try:
            # 1. Ler o ponteiro do mapa
            map_start_addr = self.pm.read_int(self.base_addr + MAP_POINTER_ADDR)
            
            # 2. Ler o bloco inteiro de dados (346kb) de uma vez
            # Isso é muito mais rápido do que ler tile por tile
            raw_data = self.pm.read_bytes(map_start_addr, MAP_DATA_SIZE)
            
            # 3. Processar os dados brutos
            self._parse_map_data(raw_data, player_id)
            
            self.last_update = time.time()
            return True
        except Exception as e:
            print(f"[MemoryMap] Erro ao ler mapa: {e}")
            return False

    def _parse_map_data(self, raw_data, player_id):
        """Transforma bytes brutos em objetos MemoryTile e encontra o jogador."""
        self.center_index = -1
        
        # Estrutura do Tile (Tibia 7.72 - MapTileOld):
        # Count (4 bytes) + 10x Items (12 bytes cada) + ... resto ignoramos por enquanto
        
        for i in range(TOTAL_TILES):
            offset = i * TILE_SIZE
            
            # Lê a contagem de itens
            # 'I' = unsigned int (4 bytes)
            count = struct.unpack_from('<I', raw_data, offset)[0]
            
            # Sanitização (as vezes a memória tem lixo se count > 10)
            if count > 10: count = 10
            
            items = []
            player_found_in_tile = False
            
            # Lê os itens da pilha
            # Offset dos itens começa em offset + 4
            for j in range(count):
                item_offset = offset + 4 + (j * 12)
                
                # Cada item tem 12 bytes: ID (4), Data1 (4), Data2 (4)
                item_id, data1, data2 = struct.unpack_from('<III', raw_data, item_offset)
                
                items.append(item_id)
                
                # Checa se este item é o próprio jogador
                # ID 99 (0x63) é padrão para criaturas/players
                if item_id == 99 and data1 == player_id:
                    player_found_in_tile = True

            self.tiles[i] = MemoryTile(items)

            # Se achamos o jogador neste tile, salvamos o índice para calibração
            if player_found_in_tile:
                self.center_index = i
                self._calibrate_center(i)

    def _calibrate_center(self, index):
        """
        Calcula os offsets X, Y, Z baseados no índice linear onde o player foi encontrado.
        Lógica portada do modTibiaMap.bas (GetPlayerCenter)
        """
        # A matriz é [Z][Y][X] (8 andares, 14 linhas, 18 colunas)
        # Índice = x + (y * 18) + (z * 18 * 14)
        
        # Engenharia reversa do índice para (x, y, z) na matriz
        z = index // (18 * 14)
        remainder = index % (18 * 14)
        y = remainder // 18
        x = remainder % 18
        
        # O "Centro" da tela do Tibia é fixo na grade visual (8, 6)
        # Offset = Posição Real na Matriz - Centro Visual
        self.offset_x = x - 8
        self.offset_y = y - 6
        self.offset_z = z # Simplificação (o Blackd faz um calculo de Z complexo, vamos testar assim primeiro)

    def get_tile(self, rel_x, rel_y):
        """
        Retorna o objeto MemoryTile na posição relativa ao jogador.
        (0, 0) = Jogador
        (1, 0) = Leste
        (-1, -1) = Noroeste
        """
        if self.center_index == -1:
            return None # Jogador não encontrado na memória ainda

        # Calcula a posição na matriz interna
        # Precisamos aplicar a "geometria toroidal" (wrap around) que o Tibia usa na memória
        # Se x > 17, volta para 0.
        
        target_x = (8 + rel_x + self.offset_x) 
        target_y = (6 + rel_y + self.offset_y)
        
        # Ajuste de bordas (Wrap around 18x14)
        # O Blackd faz: If (PosX > 17) Then PosX = PosX - 18
        # O Python operador % resolve isso elegantemente
        final_x = target_x % 18
        final_y = target_y % 14
        
        # Assume mesmo andar por enquanto (Z)
        final_z = self.offset_z 
        
        # Recalcula o índice linear
        index = final_x + (final_y * 18) + (final_z * 18 * 14)
        
        if 0 <= index < TOTAL_TILES:
            return self.tiles[index]
        return None