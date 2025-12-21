# core/map_analyzer.py
from database.tiles_config import BLOCKING_IDS, AVOID_IDS, MOVE_IDS, get_special_type
from config import DEBUG_PATHFINDING

class MapAnalyzer:
    def __init__(self, memory_map):
        self.mm = memory_map

    def get_tile_properties(self, rel_x, rel_y, debug_reason=False):
        """
        Analisa propriedades de um tile.

        Args:
            rel_x, rel_y: Posição relativa ao player
            debug_reason: Se True, retorna também o motivo de bloqueio
        """
        tile = self.mm.get_tile_visible(rel_x, rel_y)

        # 1. VALIDAÇÃO DE EXISTÊNCIA (O "VAZIO")
        if not tile or not tile.items:
            result = {'walkable': False, 'type': 'BLOCK', 'cost': 999}
            if debug_reason:
                result['block_reason'] = 'TILE_VAZIO' if not tile else 'SEM_ITENS'
                result['items'] = []
            return result

        properties = {
            'walkable': True,
            'type': 'GROUND',
            'cost': 1,
            'special_id': None
        }

        if debug_reason:
            properties['items'] = list(tile.items)  # Cópia da lista de IDs

        # Varre a pilha de itens do tile (Do chão até o topo)
        for item_id in tile.items:

            # 2. VERIFICAÇÃO DE BLOQUEIO ABSOLUTO (Paredes, Pedras, Players)
            if item_id in BLOCKING_IDS:
                if item_id == 99 and rel_x == 0 and rel_y == 0:
                    continue
                result = self._make_block()
                if debug_reason:
                    result['block_reason'] = 'BLOCKING_ID'
                    result['blocking_item_id'] = item_id
                    result['items'] = list(tile.items)
                return result

            # 3. VERIFICAÇÃO DE "AVOID" (Fields, Lava, Buracos)
            if item_id in AVOID_IDS:
                special_type = get_special_type(item_id)

                if special_type:
                    # CASO CRÍTICO: É um buraco/escada (Avoid + Special)
                    # Ação: Marcamos como NÃO ANDÁVEL para o A* não traçar rota por cima,
                    # mas definimos o 'type' correto para que o scan_for_floor_change encontre.
                    
                    properties['walkable'] = False  # <--- O SEGREDO: A* vê como parede
                    properties['type'] = special_type # <--- O SEGREDO: Scanner vê como escada
                    properties['special_id'] = item_id
                    properties['cost'] = 1000 # Custo proibitivo
                    
                    if debug_reason:
                        properties['block_reason'] = 'AVOID_SPECIAL' # Para debug saber que é escada
                        properties['blocking_item_id'] = item_id
                        properties['items'] = list(tile.items)
                    
                    # Retornamos imediatamente. 
                    # Assim ele não é tratado como 'GROUND' nas próximas linhas.
                    return properties
                else:
                    result = self._make_block()
                    if debug_reason:
                        result['block_reason'] = 'AVOID_ID'
                        result['blocking_item_id'] = item_id
                        result['items'] = list(tile.items)
                    return result

            # 4. ITENS ESPECIAIS (Escadas, Buracos de Acesso, Corda)
            special = get_special_type(item_id)
            if special:
                properties['type'] = special
                properties['special_id'] = item_id
                properties['cost'] = 20
                continue

        return properties
    
    def _make_block(self):
        return {'walkable': False, 'type': 'BLOCK', 'cost': 999}

    def get_obstacle_type(self, rel_x, rel_y):
        """
        Analisa um tile bloqueado e retorna o tipo de obstáculo.
        Usado pelo sistema de Obstacle Clearing do Cavebot.

        Returns:
            dict: {
                'type': 'BLOCK' | 'MOVE' | 'CREATURE' | 'NONE',
                'item_id': int or None,
                'stack_pos': int (posição na pilha),
                'clearable': bool
            }
        """
        tile = self.mm.get_tile_visible(rel_x, rel_y)

        if not tile or not tile.items:
            return {'type': 'NONE', 'item_id': None, 'clearable': False}

        # Varre do topo para baixo (reversed) para pegar o item mais superficial primeiro
        for i, item_id in enumerate(reversed(tile.items)):
            stack_pos = len(tile.items) - 1 - i

            # Criatura/Player - não pode mover
            if item_id == 99:
                return {
                    'type': 'CREATURE',
                    'item_id': 99,
                    'stack_pos': stack_pos,
                    'clearable': False
                }

            # Item movível (mesa, cadeira, estátua)
            if item_id in MOVE_IDS:
                return {
                    'type': 'MOVE',
                    'item_id': item_id,
                    'stack_pos': stack_pos,
                    'clearable': True
                }

            # Bloqueio fixo (parede, água, etc)
            if item_id in BLOCKING_IDS:
                return {
                    'type': 'BLOCK',
                    'item_id': item_id,
                    'stack_pos': stack_pos,
                    'clearable': False
                }

        return {'type': 'NONE', 'item_id': None, 'clearable': False}

    def scan_for_floor_change(self, target_z, current_z, range_sqm=7):
        """Busca escadas/buracos ao redor."""
        required_dir = 'UP' if target_z < current_z else 'DOWN'

        # Define quais tipos de tiles servem para o objetivo
        valid_types = []
        if required_dir == 'UP':
            valid_types = ['UP_WALK', 'UP_USE', 'ROPE']
        else:
            valid_types = ['DOWN', 'DOWN_USE', 'SHOVEL']

        best_option = None
        min_dist = 999

        for x in range(-range_sqm, range_sqm + 1):
            for y in range(-range_sqm, range_sqm + 1):
                props = self.get_tile_properties(x, y)
                
                if props['type'] in valid_types:
                    dist = (x**2 + y**2) ** 0.5
                    if dist < min_dist:
                        min_dist = dist
                        # Retorna (rel_x, rel_y, tipo, id_especial)
                        # Precisamos do ID especial (props['special_id']) para checar Rope Spot
                        best_option = (x, y, props['type'], props['special_id'])
        
        return best_option
