# core/map_analyzer.py
from database.tiles_config import BLOCKING_IDS, AVOID_IDS, MOVE_IDS, STACK_IDS, get_special_type
from config import DEBUG_PATHFINDING, DEBUG_OBSTACLE_CLEARING, DEBUG_STACK_CLEARING, PLAYER_AVOIDANCE_MULTIPLIER

class MapAnalyzer:
    def __init__(self, memory_map):
        self.mm = memory_map
        # Sistema de player avoidance - penaliza tiles próximos de players
        self._player_avoidance = {}  # {(abs_x, abs_y): multiplier}
        self._my_abs_pos = None      # Posição absoluta do player para conversão rel -> abs

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

        # 1.5 VERIFICAÇÃO DE HEIGHT (Stack items - parcels, boxes)
        # Um tile com height >= 2 é bloqueado, EXCETO se o player também tem height
        # Fórmula: walkable = (tile_height - player_height) <= 1
        tile_height = 0
        for item_id in tile.items:
            if item_id in STACK_IDS:
                tile_height += 1

        if tile_height >= 2:
            player_height = self.get_tile_height(0, 0)  # Height do tile do player
            height_diff = tile_height - player_height
            if height_diff > 1:
                # Bloqueado por altura excessiva
                result = self._make_block()
                if debug_reason:
                    result['block_reason'] = 'HEIGHT_DIFF'
                    result['height_diff'] = height_diff
                    result['player_height'] = player_height
                    result['tile_height'] = tile_height
                    result['items'] = list(tile.items)
                return result

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

        # 5. PENALIDADE DE PLAYER AVOIDANCE
        # Aplica custo extra em tiles próximos de players (para desviar)
        if self._player_avoidance and self._my_abs_pos:
            abs_x = self._my_abs_pos[0] + rel_x
            abs_y = self._my_abs_pos[1] + rel_y
            if (abs_x, abs_y) in self._player_avoidance:
                multiplier = self._player_avoidance[(abs_x, abs_y)]
                properties['cost'] = int(properties['cost'] * multiplier)

        return properties
    
    def _make_block(self):
        return {'walkable': False, 'type': 'BLOCK', 'cost': 999}

    # =========================================================================
    # PLAYER AVOIDANCE - Penaliza tiles próximos de players
    # =========================================================================

    def set_player_reference(self, my_x, my_y):
        """
        Define a posição absoluta do player para conversão rel -> abs.
        Deve ser chamado antes de usar player avoidance.
        """
        self._my_abs_pos = (my_x, my_y)

    def set_player_avoidance(self, player_abs_x, player_abs_y, multiplier=None):
        """
        Define tiles a evitar próximos de um player.

        Args:
            player_abs_x, player_abs_y: Posição absoluta do player a evitar
            multiplier: Multiplicador de custo (default: PLAYER_AVOIDANCE_MULTIPLIER)
        """
        if multiplier is None:
            multiplier = PLAYER_AVOIDANCE_MULTIPLIER

        self._player_avoidance = {}

        # Tile do player e adjacentes (3x3)
        for dx in [-1, 0, 1]:
            for dy in [-1, 0, 1]:
                self._player_avoidance[(player_abs_x + dx, player_abs_y + dy)] = multiplier

    def clear_player_avoidance(self):
        """Limpa penalidades de player."""
        self._player_avoidance = {}

    def get_tile_height(self, rel_x, rel_y):
        """
        Calcula a altura (height) de um tile baseado em items STACK.
        Cada item STACK (parcel, box, furniture package) contribui com height=1.

        Returns:
            int: Altura total do tile (0 se não tem STACK items)
        """
        tile = self.mm.get_tile_visible(rel_x, rel_y)
        if not tile or not tile.items:
            return 0

        height = 0
        for item_id in tile.items:
            if item_id in STACK_IDS:
                height += 1
        return height

    def get_item_stackpos(self, rel_x, rel_y, item_id):
        """
        Retorna o stack_pos de um item específico em um tile.
        Procura do TOPO para BAIXO (retorna a primeira ocorrência mais alta).

        Args:
            rel_x, rel_y: Posição relativa ao player
            item_id: ID do item a procurar

        Returns:
            int: Stack position ou -1 se não encontrado
        """
        tile = self.mm.get_tile_visible(rel_x, rel_y)

        if not tile or not tile.items:
            return -1

        # Procura do topo para baixo (mais comum querer o item mais acessível)
        for i in range(len(tile.items) - 1, -1, -1):
            if tile.items[i] == item_id:
                return i

        return -1

    def get_top_movable_stackpos(self, rel_x, rel_y):
        """
        Retorna (item_id, stack_pos) do item movível no topo.
        Ignora ground (stackpos 0) e criaturas (ID 99).

        Args:
            rel_x, rel_y: Posição relativa ao player

        Returns:
            tuple: (item_id, stack_pos) ou (None, -1) se não encontrado
        """
        from database.movable_items_db import is_movable

        tile = self.mm.get_tile_visible(rel_x, rel_y)

        if not tile or not tile.items:
            return (None, -1)

        # Do topo para baixo, ignora ground (index 0)
        for i in range(len(tile.items) - 1, 0, -1):
            item_id = tile.items[i]
            # Ignora criaturas (ID 99) e verifica se é movível
            if item_id != 99 and is_movable(item_id):
                return (item_id, i)

        return (None, -1)

    def get_ground_speed(self, rel_x, rel_y):
        """
        Retorna o ground speed do tile em posição relativa.
        Usado pelo A* para calcular custos baseados no tempo real de travessia.

        Args:
            rel_x, rel_y: Posição relativa ao player

        Returns:
            int: Ground speed do tile (1-200). Fallback para 150 (grass) se não encontrado.
        """
        from database.tiles_config import get_ground_speed as get_speed_from_id

        tile = self.mm.get_tile_visible(rel_x, rel_y)

        if not tile or not tile.items:
            return 150  # Fallback padrão (grass)

        # O ground é sempre o primeiro item da pilha
        ground_id = tile.items[0]

        return get_speed_from_id(ground_id)

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
        if DEBUG_OBSTACLE_CLEARING:
            print(f"[ObstacleClear] get_obstacle_type({rel_x},{rel_y}) chamado")
        tile = self.mm.get_tile_visible(rel_x, rel_y)

        if not tile:
            if DEBUG_OBSTACLE_CLEARING:
                print(f"[ObstacleClear] get_obstacle_type: tile é None")
            return {'type': 'NONE', 'item_id': None, 'clearable': False}

        if not tile.items:
            if DEBUG_OBSTACLE_CLEARING:
                print(f"[ObstacleClear] get_obstacle_type: tile.items está vazio")
            return {'type': 'NONE', 'item_id': None, 'clearable': False}

        if DEBUG_OBSTACLE_CLEARING:
            print(f"[ObstacleClear] get_obstacle_type: tile.items = {list(tile.items)}")

        # Varre do topo para baixo (reversed) para pegar o item mais superficial primeiro
        for i, item_id in enumerate(reversed(tile.items)):
            stack_pos = len(tile.items) - 1 - i

            # Criatura/Player - não pode mover
            if item_id == 99:
                if DEBUG_OBSTACLE_CLEARING:
                    print(f"[ObstacleClear] get_obstacle_type: Encontrou CREATURE (99) stack_pos={stack_pos}")
                return {
                    'type': 'CREATURE',
                    'item_id': 99,
                    'stack_pos': stack_pos,
                    'clearable': False
                }

            # Item movível (mesa, cadeira, estátua)
            if item_id in MOVE_IDS:
                if DEBUG_OBSTACLE_CLEARING:
                    print(f"[ObstacleClear] get_obstacle_type: Encontrou MOVE item {item_id} stack_pos={stack_pos}")
                return {
                    'type': 'MOVE',
                    'item_id': item_id,
                    'stack_pos': stack_pos,
                    'clearable': True
                }

            # Item stackável (parcel, box, furniture package)
            if item_id in STACK_IDS:
                # Verificar se height_diff realmente bloqueia (>1)
                # Se height_diff <= 1, o tile é walkable e não precisa limpar
                tile_height = self.get_tile_height(rel_x, rel_y)
                player_height = self.get_tile_height(0, 0)
                height_diff = tile_height - player_height

                is_blocked = height_diff > 1

                if DEBUG_STACK_CLEARING:
                    print(f"[StackClear] get_obstacle_type: Encontrou STACK item {item_id} stack_pos={stack_pos}")
                    print(f"[StackClear]   tile_height={tile_height}, player_height={player_height}, height_diff={height_diff}, blocked={is_blocked}")

                return {
                    'type': 'STACK',
                    'item_id': item_id,
                    'stack_pos': stack_pos,
                    'clearable': is_blocked  # Só clearable se height_diff > 1
                }

            # Bloqueio fixo (parede, água, etc)
            if item_id in BLOCKING_IDS:
                if DEBUG_OBSTACLE_CLEARING:
                    print(f"[ObstacleClear] get_obstacle_type: Encontrou BLOCK item {item_id} stack_pos={stack_pos}")
                return {
                    'type': 'BLOCK',
                    'item_id': item_id,
                    'stack_pos': stack_pos,
                    'clearable': False
                }

        if DEBUG_OBSTACLE_CLEARING:
            print(f"[ObstacleClear] get_obstacle_type: Nenhum obstáculo encontrado, retornando NONE")
        return {'type': 'NONE', 'item_id': None, 'clearable': False}

    def scan_for_floor_change(self, target_z, current_z, range_sqm=7,
                              player_abs_x=None, player_abs_y=None,
                              dest_x=None, dest_y=None,
                              transitions_by_floor=None):
        """Busca escadas/buracos ao redor.

        Se dest_x/dest_y forem fornecidos, prioriza a escada mais próxima do destino
        ao invés da mais próxima do player. Se transitions_by_floor estiver disponível,
        verifica para onde cada escada realmente leva e prioriza pela distância do
        destino da transição ao waypoint final.
        """
        required_dir = 'UP' if target_z < current_z else 'DOWN'

        # Define quais tipos de tiles servem para o objetivo
        valid_types = []
        if required_dir == 'UP':
            valid_types = ['UP_WALK', 'UP_USE', 'ROPE']
        else:
            valid_types = ['DOWN', 'DOWN_USE', 'SHOVEL']

        # Coleta TODAS as escadas visíveis válidas
        candidates = []

        for x in range(-range_sqm, range_sqm + 1):
            for y in range(-range_sqm, range_sqm + 1):
                props = self.get_tile_properties(x, y)

                if props['type'] in valid_types:
                    candidates.append((x, y, props['type'], props['special_id']))

        if not candidates:
            return None

        # Sem info de destino: retorna a mais próxima do player (comportamento original)
        if dest_x is None or dest_y is None or player_abs_x is None or player_abs_y is None:
            best = None
            min_dist = 999
            for x, y, ftype, fid in candidates:
                dist = (x**2 + y**2) ** 0.5
                if dist < min_dist:
                    min_dist = dist
                    best = (x, y, ftype, fid)
            return best

        # Validar cada escada contra transitions_by_floor e/ou distância ao destino
        best_option = None
        best_score = float('inf')

        for x, y, ftype, fid in candidates:
            abs_x = player_abs_x + x
            abs_y = player_abs_y + y

            # Se temos transitions_by_floor, APENAS aceitar escadas registradas
            if transitions_by_floor:
                transitions = transitions_by_floor.get(current_z, [])
                matched = False
                for tx, ty, tz_to in transitions:
                    if abs(tx - abs_x) <= 1 and abs(ty - abs_y) <= 1:
                        # Score = distância XY do destino da transição ao waypoint
                        score = abs(tx - dest_x) + abs(ty - dest_y)
                        if score < best_score:
                            best_score = score
                            best_option = (x, y, ftype, fid)
                        matched = True
                        break
                if not matched:
                    # Escada não registrada nas transições - ignorar (provavelmente casa/dead end)
                    print(f"[FloorChange] Escada em ({abs_x}, {abs_y}) ignorada: não registrada em transitions")
                continue

            # Sem transitions: fallback por distância XY da escada ao waypoint destino
            score = abs(abs_x - dest_x) + abs(abs_y - dest_y)
            if score < best_score:
                best_score = score
                best_option = (x, y, ftype, fid)

        # best_option pode ser None se nenhuma escada visível é válida
        return best_option
