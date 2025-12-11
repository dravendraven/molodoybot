import heapq

# Deve bater com o map_reader
COST_BLOCKED = 999

class Node:
    def __init__(self, parent=None, position=None):
        self.parent = parent
        self.position = position
        self.g = 0 
        self.h = 0 
        self.f = 0 

    def __eq__(self, other):
        return self.position == other.position
    
    def __lt__(self, other):
        return self.f < other.f

def astar_search(cost_grid, start, end):
    print(f"[DEBUG A*] Iniciando busca: {start} -> {end}")
    
    # 1. Validações de Limites
    max_y = len(cost_grid)
    max_x = len(cost_grid[0])
    
    if not (0 <= end[0] < max_x and 0 <= end[1] < max_y):
        print(f"[DEBUG A*] FALHA: Destino fora da matriz {end}")
        return None

    # 2. Validação de Bloqueio no Destino
    dest_cost = cost_grid[end[1]][end[0]]
    if dest_cost >= COST_BLOCKED:
        print(f"[DEBUG A*] FALHA: O destino é uma PAREDE/BLOCK (Custo {dest_cost})")
        return None

    start_node = Node(None, start)
    end_node = Node(None, end)

    open_list = []
    closed_set = set()

    heapq.heappush(open_list, start_node)
    
    outer_iterations = 0
    max_iterations = (max_x * max_y) * 4 # Limite generoso

    NEIGHBORS = [
        (0, -1), (0, 1), (-1, 0), (1, 0),   # N, S, W, E
        (-1, -1), (1, -1), (-1, 1), (1, 1)  # Diagonais
    ]

    while len(open_list) > 0:
        outer_iterations += 1
        if outer_iterations > max_iterations:
            print(f"[DEBUG A*] FALHA: Timeout! Muitas iterações ({outer_iterations})")
            return None

        current_node = heapq.heappop(open_list)
        closed_set.add(current_node.position)

        # DEBUG: Printar progresso a cada 200 nós para não spammar
        # if outer_iterations % 200 == 0:
        #    print(f"[DEBUG A*] Analisando nó {current_node.position} (G={current_node.g})")

        # Chegou?
        if current_node == end_node:
            print(f"[DEBUG A*] SUCESSO! Caminho encontrado em {outer_iterations} iterações.")
            path = []
            current = current_node
            while current is not None:
                path.append(current.position)
                current = current.parent
            return path[::-1]

        for new_position in NEIGHBORS:
            node_position = (current_node.position[0] + new_position[0], 
                             current_node.position[1] + new_position[1])

            # Check Limites
            if (node_position[0] > (max_x - 1) or 
                node_position[0] < 0 or 
                node_position[1] > (max_y - 1) or 
                node_position[1] < 0):
                continue

            # Check Parede
            tile_cost = cost_grid[node_position[1]][node_position[0]]
            if tile_cost >= COST_BLOCKED:
                continue
            
            if node_position in closed_set:
                continue

            new_node = Node(current_node, node_position)

            # Penalidade Diagonal (Custo 3.0 para forçar linhas retas)
            is_diagonal = (abs(new_position[0]) + abs(new_position[1])) == 2
            penalty = 3.0 if is_diagonal else 0.0

            new_node.g = current_node.g + tile_cost + penalty
            
            # Heurística Manhattan
            new_node.h = abs(new_node.position[0] - end_node.position[0]) + \
                         abs(new_node.position[1] - end_node.position[1])
            new_node.f = new_node.g + new_node.h

            heapq.heappush(open_list, new_node)

    print("[DEBUG A*] FALHA: Open List vazia (Sem caminho possível)")
    return None