# core/map_analyzer.py
from database.tiles_config import BLOCKING_IDS, AVOID_IDS, get_special_type
from config import DEBUG_PATHFINDING

class MapAnalyzer:
    def __init__(self, memory_map):
        self.mm = memory_map

    def get_tile_properties(self, rel_x, rel_y):
        tile = self.mm.get_tile(rel_x, rel_y)

        # 1. VALIDAÇÃO DE EXISTÊNCIA (O "VAZIO")
        # Se o tile é None ou a lista de itens está vazia, não tem chão.
        # Isso evita que o bot tente andar no "preto" do mapa.
        if not tile or not tile.items:
            if DEBUG_PATHFINDING:
                print(f"[MapAnalyzer] get_tile_properties({rel_x}, {rel_y}) -> BLOQUEADO (tile=None ou vazio)")
            return {'walkable': False, 'type': 'BLOCK', 'cost': 999}

        properties = {
            'walkable': True,
            'type': 'GROUND',
            'cost': 1, # Custo base (Grama, Terra, etc)
            'special_id': None
        }

        has_avoid = False

        # Varre a pilha de itens do tile (Do chão até o topo)
        for item_id in tile.items:
            
            # 2. VERIFICAÇÃO DE BLOQUEIO ABSOLUTO (Paredes, Pedras, Players)
            if item_id in BLOCKING_IDS:
                if item_id == 99 and rel_x == 0 and rel_y == 0:
                    continue
                return self._make_block()

            # 3. VERIFICAÇÃO DE "AVOID" (Fields, Lava, Buracos)
            # Usuário optou por tratar como BLOQUEIO TOTAL
            if item_id in AVOID_IDS:
                # Exceção: Se for um buraco/escada que o Cavebot precisa usar,
                # a verificação de 'special' abaixo cuidaria disso?
                # Cuidado: Escadas muitas vezes tem flag 'Avoid' ou 'Unpass'.
                # Para garantir que o bot suba escadas, precisamos checar se é ESPECIAL antes de bloquear.
                
                if get_special_type(item_id): 
                    pass # Se é escada/buraco de acesso, deixa passar para a checagem abaixo
                else:
                    return self._make_block()

            # 4. ITENS ESPECIAIS (Escadas, Buracos de Acesso, Corda)
            special = get_special_type(item_id)
            if special:
                properties['type'] = special
                properties['special_id'] = item_id
                # Custo médio para evitar pisar à toa em escadas, 
                # mas permite que o Cavebot force a entrada se for o destino.
                properties['cost'] = 20 
                # Não retorna imediatamente, continua checando se tem algo bloqueando em cima
                continue 

        return properties
    
    def _make_block(self):
        return {'walkable': False, 'type': 'BLOCK', 'cost': 999}

    def scan_for_floor_change(self, target_z, current_z, range_sqm=7):
        """Busca escadas/buracos ao redor."""
        required_dir = 'UP' if target_z < current_z else 'DOWN'
        
        # Define quais tipos de tiles servem para o objetivo
        valid_types = []
        if required_dir == 'UP':
            valid_types = ['UP_WALK', 'UP_USE', 'ROPE']
        else:
            valid_types = ['DOWN', 'SHOVEL']

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
