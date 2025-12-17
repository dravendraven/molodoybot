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
    def __init__(self, map_analyzer, max_depth=100, debug=False):
        self.analyzer = map_analyzer
        self.max_depth = max_depth
        self.debug = debug

    def get_next_step(self, target_rel_x, target_rel_y):
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
                    blocked_count += 1
                    continue

                walkable_count += 1

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

        # DEBUG: Log quando não encontra caminho
        if self.debug and walkable_count == 0:
            print(f"[A*] ⚠️ DEBUG: Nenhum tile walkable encontrado ao redor! Target: ({target_rel_x}, {target_rel_y})")
            print(f"[A*] Tiles analisados: {blocked_count} bloqueados, {walkable_count} walkable")

        # FALLBACK: Se A* não encontrou caminho, tenta dar um passo em direção ao waypoint
        # (Útil quando o target está fora do chunk visível)
        if walkable_count > 0:
            return self._get_fallback_step(target_rel_x, target_rel_y)

        return None

    def _get_fallback_step(self, target_rel_x, target_rel_y):
        """
        FALLBACK: Se A* não conseguir planejar até o destino (porque está fora do chunk),
        tenta dar um passo na direção mais próxima do destino.

        Isso é crucial para cruzar limites de chunk: damos um passo em direção ao waypoint,
        então o próximo ciclo lê a nova chunk e continua.
        """
        neighbors = [
            (0, -1), (0, 1), (-1, 0), (1, 0),
            (-1, -1), (-1, 1), (1, -1), (1, 1)
        ]

        best_step = None
        best_distance = float('inf')

        for dx, dy in neighbors:
            # Verifica se o tile é walkable
            props = self.analyzer.get_tile_properties(dx, dy)
            if not props['walkable']:
                continue

            # Calcula distância até o destino se der este passo
            # (Simula dar um passo e mede quantos tiles faltam)
            new_x = dx
            new_y = dy
            distance = math.sqrt((new_x - target_rel_x)**2 + (new_y - target_rel_y)**2)

            if distance < best_distance:
                best_distance = distance
                best_step = (dx, dy)

        if best_step and self.debug:
            print(f"[A*] 💡 FALLBACK: Dando um passo em direção ao target ({target_rel_x}, {target_rel_y})")
            print(f"[A*] Step: {best_step}, distância: {best_distance:.2f}")

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