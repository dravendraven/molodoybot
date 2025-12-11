import struct
from config import *
from items_db import ITEMS 

# ==============================================================================
# CONFIGURAÇÃO DE MEMÓRIA (Confirmada pelo Scanner)
# ==============================================================================
CENTER_X_GRID = 8
CENTER_Y_GRID = 11
MAP_WIDTH = 18
MAP_HEIGHT = 14
SIZEOF_TILE = 172
FLOOR_SIZE = 43344

# Custos para o Pathfinding
COST_WALKABLE = 1
COST_STACK    = 8   # Parcels (Possível limpar)
COST_MOVE     = 25  # Mesas (Trabalhoso mover)
COST_BLOCKED  = 999 # Paredes

# Roles (Vindos do items_db)
ROLE_WALK  = 0
ROLE_BLOCK = 1
ROLE_STACK = 2
ROLE_MOVE  = 3

class MapReader:
    def __init__(self, pymem_instance):
        self.pm = pymem_instance
        try:
            self.base_map_addr = self.pm.read_int(MAP_POINTER_ADDR)
        except:
            self.base_map_addr = 0

    def get_layer_index(self, player_z):
        # Se Z=7 e Layer=0, então a fórmula é Z - 7.
        # Ajuste conforme necessário se você subir escadas.
        layer = player_z - 7 
        
        # Proteção: O Tibia guarda alguns andares acima e abaixo.
        # Vamos garantir que fique entre 0 e 7.
        return max(0, min(layer, 7))

    def get_tile_cost(self, tile_data):
        """
        Recebe os bytes brutos de um tile e decide se é andável.
        """
        try:
            # 1. Quantos itens tem no tile?
            item_count = struct.unpack_from('<I', tile_data, 0)[0]
            
            # Tile vazio/preto na memória = Bloqueio
            if item_count == 0: 
                return COST_BLOCKED

            # Ler IDs da stack
            safe_count = min(item_count, 14)
            items = []
            offset = 4
            for _ in range(safe_count):
                tid = struct.unpack_from('<I', tile_data, offset)[0]
                items.append(tid)
                offset += 12

            # 2. Analisa o Chão (Index 0)
            ground_id = items[0]
            
            # Se o ID do chão for 0 ou 99, geralmente é bug visual ou borda de mapa
            if ground_id <= 100 and ground_id != 0: 
                # (Opcional) Tratamento para IDs baixos se necessário
                pass

            # Verifica se o chão em si é marcado como BLOCK no items_db (Lava, Água, Void)
            # Se o ID não estiver no DB, assume que é WALK (0)
            ground_role = ITEMS.get(ground_id, ROLE_WALK)
            
            if ground_role == ROLE_BLOCK:
                return COST_BLOCKED

            # 3. Analisa Objetos em Cima (Index 1+)
            if len(items) == 1:
                return COST_WALKABLE

            current_cost = COST_WALKABLE
            parcel_count = 0

            for item_id in items[1:]:
                role = ITEMS.get(item_id, ROLE_WALK)

                if role == ROLE_BLOCK:
                    return COST_BLOCKED # Parede/Pedra/Árvore
                
                elif role == ROLE_MOVE:
                    current_cost += COST_MOVE # Mesa/Cadeira
                
                elif role == ROLE_STACK:
                    parcel_count += 1
            
            # Se tiver muitos parcels empilhados, aumenta o custo
            if parcel_count >= 2:
                current_cost += COST_STACK

            # Retorna o custo final (limitado para não quebrar heurística)
            return min(current_cost, 200)

        except Exception as e:
            # Em caso de erro de leitura, bloqueia por segurança
            return COST_BLOCKED

    def get_cost_grid(self, player_z):
        """Lê a memória e retorna matriz 18x14 de custos."""
        if self.base_map_addr == 0: return None
        
        layer = self.get_layer_index(player_z)
        layer_addr = self.base_map_addr + (layer * FLOOR_SIZE)
        
        grid = []
        for y in range(MAP_HEIGHT):
            row = []
            for x in range(MAP_WIDTH):
                # Cálculo exato do Matrix Scanner
                idx = (y * MAP_WIDTH) + x
                tile_addr = layer_addr + (idx * SIZEOF_TILE)
                
                # Lê buffer do tile
                buff = self.pm.read_bytes(tile_addr, SIZEOF_TILE)
                
                # Calcula custo
                cost = self.get_tile_cost(buff)
                row.append(cost)
            grid.append(row)
            
        return grid