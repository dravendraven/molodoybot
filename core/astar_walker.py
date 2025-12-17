# core/astar_walker.py
import heapq
import math

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
    def __init__(self, map_analyzer, max_depth=100):
        self.analyzer = map_analyzer
        self.max_depth = max_depth

    def get_next_step(self, target_rel_x, target_rel_y):
        """
        Calcula o PRIMEIRO passo (dx, dy) para chegar no destino relativo.
        """
        if target_rel_x == 0 and target_rel_y == 0:
            return None

        start_node = Node(0, 0)
        open_list = []
        closed_set = set()
        heapq.heappush(open_list, start_node)
        
        iterations = 0

        while open_list:
            current_node = heapq.heappop(open_list)
            iterations += 1

            if iterations > self.max_depth:
                break # Evita travar se não achar caminho

            # Se chegamos ao destino
            if current_node.x == target_rel_x and current_node.y == target_rel_y:
                return self._reconstruct_first_step(current_node)

            if (current_node.x, current_node.y) in closed_set:
                continue
            
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
                
                if not props['walkable']:
                    continue
                
                # --- CORREÇÃO DE CUSTO (LÓGICA TIBIA) ---
                is_diagonal = (dx != 0 and dy != 0)
                
                if is_diagonal:
                    # Custo 25 faz com que o bot prefira andar 2 tiles retos (10+10=20)
                    # do que 1 diagonal, evitando o delay de "exhaust" do char.
                    # Ele só usará diagonal se os vizinhos retos estiverem bloqueados.
                    move_cost = 40 
                else:
                    move_cost = 10
                
                # Se for o destino final, ignoramos o custo extra de "Special Tile" (Ex: Escada)
                is_target = (nx == target_rel_x and ny == target_rel_y)
                tile_cost = 0 if is_target else props['cost']
                
                if tile_cost >= 999: continue 

                total_cost = move_cost + tile_cost
                new_g = current_node.g + total_cost
                new_h = math.sqrt((nx - target_rel_x)**2 + (ny - target_rel_y)**2) * 10
                
                new_node = Node(nx, ny, current_node, new_g, new_h)
                heapq.heappush(open_list, new_node)

        return None

    def _reconstruct_first_step(self, node):
        curr = node
        path = []
        while curr.parent:
            path.append(curr)
            curr = curr.parent
        
        if not path: return None
        # O último da lista é o filho direto do start (o primeiro passo)
        first = path[-1]
        return (first.x, first.y)