# core/astar_walker.py
import heapq

class Node:
    def __init__(self, x, y, parent=None, g=0, h=0):
        self.x = x
        self.y = y
        self.parent = parent
        self.g = g
        self.h = h
        self.f = g + h

    def __lt__(self, other):
        return self.f < other.f

class AStarWalker:
    def __init__(self, map_analyzer, max_depth=500, debug=False):
        self.analyzer = map_analyzer
        self.max_depth = max_depth
        self.debug = debug

    def get_next_step(self, target_rel_x, target_rel_y, activate_fallback=True):
        """
        Calcula o PRIMEIRO passo (dx, dy) para chegar no destino relativo.
        Se não encontrar caminho completo, tenta fallback para passo na direção correta.
        """
        if target_rel_x == 0 and target_rel_y == 0:
            return None

        start_node = Node(0, 0)
        open_list = []
        closed_set = set()
        heapq.heappush(open_list, start_node)

        iterations = 0
        walkable_count = 0
        blocked_count = 0

        while open_list:
            current_node = heapq.heappop(open_list)

            # Se chegamos ao destino
            if current_node.x == target_rel_x and current_node.y == target_rel_y:
                return self._reconstruct_first_step(current_node)

            if (current_node.x, current_node.y) in closed_set:
                continue

            # Conta apenas nós únicos processados (não duplicatas)
            iterations += 1
            if iterations > self.max_depth:
                break # Evita travar se não achar caminho

            closed_set.add((current_node.x, current_node.y))

            # Vizinhos (8 direções: N, S, E, W + Diagonais)
            neighbors = [
                (0, -1), (0, 1), (-1, 0), (1, 0),
                (-1, -1), (-1, 1), (1, -1), (1, 1)
            ]

            for dx, dy in neighbors:
                nx, ny = current_node.x + dx, current_node.y + dy

                if (nx, ny) in closed_set:
                    continue

                # --- ANÁLISE DO TILE ---
                props = self.analyzer.get_tile_properties(nx, ny)

                is_target_node = (nx == target_rel_x and ny == target_rel_y)

                if not props['walkable'] and not is_target_node:
                    blocked_count += 1
                    continue

                walkable_count += 1

                # --- CORREÇÃO DE CUSTO (LÓGICA TIBIA) ---
                is_diagonal = (dx != 0 and dy != 0)

                if is_diagonal:
                    # Custo 25 faz com que o bot prefira andar 2 tiles retos (10+10=20)
                    # do que 1 diagonal, evitando o delay de "exhaust" do char.
                    # Ele só usará diagonal se os vizinhos retos estiverem bloqueados.
                    move_cost = 30
                else:
                    move_cost = 10

                # Se for o destino final, ignoramos o custo extra de "Special Tile" (Ex: Escada)
                is_target = (nx == target_rel_x and ny == target_rel_y)
                tile_cost = 0 if is_target else props['cost']

                if tile_cost >= 999: continue

                total_cost = move_cost + tile_cost
                new_g = current_node.g + total_cost
                # Heurística Manhattan para grid-based pathfinding (Tibia)
                # Manhattan distance é mais apropriado que Euclidiano para movimento em tiles
                new_h = (abs(nx - target_rel_x) + abs(ny - target_rel_y)) * 10

                new_node = Node(nx, ny, current_node, new_g, new_h)
                heapq.heappush(open_list, new_node)

        # DEBUG: Log quando não encontra caminho (COM MOTIVO)
        if self.debug:
            # Verifica se o target é walkable COM MOTIVO detalhado
            target_props = self.analyzer.get_tile_properties(target_rel_x, target_rel_y, debug_reason=True)
            target_walkable = target_props['walkable']

            if iterations > self.max_depth:
                print(f"[A*] ⚠️ TIMEOUT: Atingiu max_depth ({self.max_depth}) sem encontrar target ({target_rel_x}, {target_rel_y})")
                print(f"[A*]   Explored {iterations} nodes, closed_set size: {len(closed_set)}")
            elif walkable_count == 0:
                print(f"[A*] ⚠️ DEBUG: Nenhum tile walkable encontrado ao redor! Target: ({target_rel_x}, {target_rel_y})")
                print(f"[A*] Tiles analisados: {blocked_count} bloqueados, {walkable_count} walkable")
            elif not target_walkable:
                # Mostra MOTIVO detalhado do bloqueio
                reason = target_props.get('block_reason', 'UNKNOWN')
                items = target_props.get('items', [])

                print(f"[A*] ⚠️ TARGET BLOQUEADO: O tile de destino ({target_rel_x}, {target_rel_y}) é NÃO-WALKABLE!")
                print(f"[A*]   Explored {len(closed_set)} reachable nodes antes de descobrir isso")

                if reason == 'BLOCKING_ID':
                    blocking_id = target_props.get('blocking_item_id', '?')
                    print(f"[A*]   🚫 MOTIVO: Item bloqueador ID {blocking_id}")
                    print(f"[A*]   📦 Pilha de itens no tile: {items}")
                elif reason == 'AVOID_ID':
                    blocking_id = target_props.get('blocking_item_id', '?')
                    print(f"[A*]   ⚠️ MOTIVO: Item 'AVOID' ID {blocking_id}")
                    print(f"[A*]   📦 Pilha de itens no tile: {items}")
                elif reason == 'TILE_VAZIO':
                    print(f"[A*]   🕳️ MOTIVO: Tile não existe na memória (fora do alcance de leitura)")
                elif reason == 'SEM_ITENS':
                    print(f"[A*]   🕳️ MOTIVO: Tile existe mas lista de itens está vazia")
                else:
                    print(f"[A*]   Target properties: {target_props}")
            else:
                print(f"[A*] ⚠️ FAILED: Fim do open_list sem encontrar target ({target_rel_x}, {target_rel_y})")
                print(f"[A*]   Iterations: {iterations}, closed_set size: {len(closed_set)}, walkable_count: {walkable_count}")

        # FALLBACK: Se A* não encontrou caminho, tenta dar um passo em direção ao waypoint
        # (Útil quando o target está fora do chunk visível - ex: Cavebot)
        if activate_fallback and walkable_count > 0:
            if self.debug:
                print(f"[A*] ⚠️ Usando fallback step (destino possivelmente fora do chunk)")
            return self._get_fallback_step(target_rel_x, target_rel_y)

        if self.debug and not activate_fallback and walkable_count > 0:
            print(f"[A*] ⚠️ FALLBACK DESABILITADO por parâmetro (activate_fallback=False)")

        return None

    def _get_fallback_step(self, target_rel_x, target_rel_y):
        """
        FALLBACK: Se A* não conseguir planejar até o destino (porque está fora do chunk),
        tenta dar um passo na direção mais próxima do destino.

        IMPORTANTE: Prioritiza passos que reduzem a distância ao target (não andam para trás).
        """
        neighbors = [
            (0, -1), (0, 1), (-1, 0), (1, 0),
            (-1, -1), (-1, 1), (1, -1), (1, 1)
        ]

        # Distância atual até o target usando Manhattan distance (grid-based)
        current_distance = abs(target_rel_x) + abs(target_rel_y)

        best_step = None
        best_distance = float('inf')

        for dx, dy in neighbors:
            # Verifica se o tile é walkable
            props = self.analyzer.get_tile_properties(dx, dy)
            if not props['walkable']:
                continue

            # Calcula distância até o destino SE der este passo usando Manhattan distance
            # (dx, dy) é a posição após o passo
            new_x = dx
            new_y = dy
            new_distance = abs(new_x - target_rel_x) + abs(new_y - target_rel_y)

            # CRÍTICO: SÓ considera passos que reduzem a distância
            # (evita andar para trás ou ficar no mesmo lugar)
            if new_distance >= current_distance:
                continue

            if new_distance < best_distance:
                best_distance = new_distance
                best_step = (dx, dy)

        # Fallback silencioso - log apenas se falhar completamente
        return best_step

    def _reconstruct_first_step(self, node):
        """Reconstrói o primeiro passo da rota planejada pelo A*."""
        curr = node
        path = []
        while curr.parent:
            path.append(curr)
            curr = curr.parent

        if not path:
            return None
        # O último da lista é o filho direto do start (o primeiro passo)
        first = path[-1]
        return (first.x, first.y)
    

    # Adicione dentro da classe AStarWalker em core/astar_walker.py
    
    def get_full_path(self, target_rel_x, target_rel_y):
        """
        Retorna a lista completa de passos [(dx, dy), (dx, dy)...] até o destino.
        """
        if target_rel_x == 0 and target_rel_y == 0:
            return []

        # Usa uma lista aberta de prioridade
        start_node = Node(0, 0)
        open_list = []
        heapq.heappush(open_list, start_node)
        
        # Dicionário para rastrear nós visitados e reconstruir caminho
        # Key: (x,y), Value: Node
        visited = {(0,0): start_node}
        
        # Limite de segurança para não travar o bot em rotas impossíveis
        iterations = 0

        while open_list and iterations < self.max_depth:
            current_node = heapq.heappop(open_list)
            iterations += 1

            # Chegou no destino?
            if current_node.x == target_rel_x and current_node.y == target_rel_y:
                return self._reconstruct_path_list(current_node)

            # Só expande vizinhos se não estourou o limite de custo (G)
            if current_node.g > 200: # Exemplo de limite de custo
                continue

            # Expande vizinhos (use self.neighbors que deve incluir diagonais)
            # IMPORTANTE: Garanta que self.neighbors tenha diagonais no __init__
            for dx, dy in [(-1,0),(1,0),(0,-1),(0,1), (-1,-1),(1,-1),(-1,1),(1,1)]:
                nx, ny = current_node.x + dx, current_node.y + dy
                is_target_node = (nx == target_rel_x and ny == target_rel_y)
                # Verifica colisão
                props = self.analyzer.get_tile_properties(nx, ny)
                if not props['walkable'] and not is_target_node:
                    continue

                # Custo: 10 para reto, 14 para diagonal
                move_cost = 30 if dx != 0 and dy != 0 else 10
                new_g = current_node.g + move_cost
                
                if (nx, ny) not in visited or new_g < visited[(nx, ny)].g:
                    # Heurística Manhattan para grid-based pathfinding
                    dist_x = abs(target_rel_x - nx)
                    dist_y = abs(target_rel_y - ny)
                    h = (dist_x + dist_y) * 10
                    neighbor = Node(nx, ny, parent=current_node, g=new_g, h=h)
                    
                    visited[(nx, ny)] = neighbor
                    heapq.heappush(open_list, neighbor)

        return []

    def _reconstruct_path_list(self, node):
        path = []
        curr = node
        while curr.parent:
            dx = curr.x - curr.parent.x
            dy = curr.y - curr.parent.y
            path.append((dx, dy))
            curr = curr.parent
        path.reverse()
        return path