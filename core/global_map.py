import os
import json
import heapq
import time
import re
from collections import defaultdict

# Custos de movimento (Tibia: diagonal = 3x cardinal)
COST_CARDINAL = 10
COST_DIAGONAL = 30
COST_TRANSITION = 20
LEVEL_PENALTY = 80

class GlobalMap:
    def __init__(self, maps_dir, walkable_ids, transitions_file=None, archway_files=None):
        self.maps_dir = maps_dir
        self.walkable_ids = set(walkable_ids) # Ex: {186, 121} - IDs que são chão
        self.cache = {} # Cache de arquivos carregados
        self._filename_cache = {} # (chunk_x, chunk_y, z) -> filename or None
        self.temporary_obstacles = {} # (x, y, z) -> timestamp

        # Transições entre andares: z -> [(x, y, z_to), ...]
        self._transitions_by_floor = defaultdict(list)
        # Lookup rápido: (x, y, z) -> [z_to, ...]
        self._transition_lookup = defaultdict(list)
        # Tiles de transição para bloquear no pathfinding same-floor
        # (evita que o A* roteie por cima de buracos/escadas acidentalmente)
        self._transition_tiles = set()
        if transitions_file and os.path.isfile(transitions_file):
            self._load_transitions(transitions_file)

        # Overrides de tiles walkables (ex: stone archways que aparecem como montanha)
        self._walkable_overrides = set()
        if archway_files:
            self._load_archways(archway_files)

    def _load_transitions(self, filepath):
        with open(filepath, 'r') as f:
            data = json.load(f)
        for t in data.get("transitions", []):
            self._transitions_by_floor[t["z_from"]].append(
                (t["x"], t["y"], t["z_to"])
            )
            self._transition_lookup[(t["x"], t["y"], t["z_from"])].append(t["z_to"])
            self._transition_tiles.add((t["x"], t["y"], t["z_from"]))

    def _load_archways(self, filepaths):
        """Carrega coordenadas de stone archways dos arquivos (tiles forçados como walkable)."""
        for filepath in filepaths:
            if not os.path.isfile(filepath):
                continue
            with open(filepath, 'r') as f:
                for line in f:
                    # Formato: "stone archway (x,y,z)"
                    match = re.search(r'\((\d+),(\d+),(\d+)\)', line)
                    if match:
                        x, y, z = int(match.group(1)), int(match.group(2)), int(match.group(3))
                        self._walkable_overrides.add((x, y, z))

    def _resolve_filename(self, chunk_x, chunk_y, abs_z):
        """Resolve e cacheia o nome do arquivo .map para um chunk."""
        key = (chunk_x, chunk_y, abs_z)
        if key in self._filename_cache:
            return self._filename_cache[key]

        for f in (f"{chunk_x}{chunk_y}{abs_z:02}.map",
                  f"{chunk_x:03}{chunk_y:03}{abs_z:02}.map"):
            if os.path.exists(os.path.join(self.maps_dir, f)):
                self._filename_cache[key] = f
                return f

        self._filename_cache[key] = None
        return None

    def get_color_id(self, abs_x, abs_y, abs_z):
        """Lê o byte do arquivo .map correto."""
        chunk_x = abs_x // 256
        chunk_y = abs_y // 256

        filename = self._resolve_filename(chunk_x, chunk_y, abs_z)
        if not filename:
            return 0

        if filename not in self.cache:
            try:
                with open(os.path.join(self.maps_dir, filename), "rb") as f:
                    self.cache[filename] = f.read()
            except:
                return 0

        rel_x = abs_x % 256
        rel_y = abs_y % 256
        index = (rel_x * 256) + rel_y

        data = self.cache[filename]
        if index < len(data):
            return data[index]
        return 0

    def is_walkable(self, x, y, z, ignore_transitions=False):
        # 1. Verifica bloqueio temporário
        if (x, y, z) in self.temporary_obstacles:
            if time.time() < self.temporary_obstacles[(x, y, z)]:
                return False
            else:
                del self.temporary_obstacles[(x, y, z)] # Expire

        # 2. Verifica se é tile de transição (buraco/escada) — evitar roteamento acidental
        if not ignore_transitions and (x, y, z) in self._transition_tiles:
            return False

        # 3. Verifica se é override walkable (stone archways)
        if (x, y, z) in self._walkable_overrides:
            return True

        # 4. Verifica cor do mapa
        color = self.get_color_id(x, y, z)
        return color in self.walkable_ids

    def is_walkable_offline(self, x, y, z, ignore_transitions=False):
        """Versão sem temp obstacles/time.time() para geração offline."""
        if not ignore_transitions and (x, y, z) in self._transition_tiles:
            return False
        if (x, y, z) in self._walkable_overrides:
            return True
        return self.get_color_id(x, y, z) in self.walkable_ids

    def add_temp_block(self, x, y, z, duration=10):
        """Bloqueia um tile temporariamente (ex: player trapando)."""
        self.temporary_obstacles[(x, y, z)] = time.time() + duration

    def clear_temp_blocks(self):
        self.temporary_obstacles.clear()

    def get_path(self, start_pos, end_pos, max_dist=5000, max_iter=0, offline=False):
        """
        A* Global com suporte a diagonais.
        Retorna lista [(x,y,z), (x,y,z)...] do início ao fim.
        """
        sx, sy, sz = start_pos
        ex, ey, ez = end_pos
        _walkable = self.is_walkable_offline if offline else self.is_walkable

        if sz != ez: return None # Apenas mesmo andar

        # Otimização: Se destino for parede, tenta vizinho
        if not _walkable(ex, ey, ez):
            found = False
            # Procura vizinho andável (incluindo diagonais agora)
            for dx in [-1, 0, 1]:
                for dy in [-1, 0, 1]:
                    if dx == 0 and dy == 0: continue
                    if _walkable(ex+dx, ey+dy, ez):
                        ex, ey = ex+dx, ey+dy
                        found = True
                        break
                if found: break
            if not found: return None

        # Definição dos movimentos: (dx, dy, custo)
        # Cardinais = 10, Diagonais = 14 (aprox raiz de 2)
        moves = [
            (0, 1, 10), (0, -1, 10), (1, 0, 10), (-1, 0, 10),      # Cardinais
            (1, 1, 35), (1, -1, 35), (-1, 1, 35), (-1, -1, 35)     # Diagonais
        ]

        open_list = []
        # Heap armazena: (F-Score, H-Score, x, y)
        # Usamos H-Score no tie-break para preferir caminhos mais próximos do destino
        heapq.heappush(open_list, (0, 0, sx, sy))
        
        came_from = {}
        cost_so_far = {(sx, sy): 0}
        
        iterations = 0
        while open_list:
            if max_iter and iterations >= max_iter:
                break
            iterations += 1
            _, _, cx, cy = heapq.heappop(open_list)

            if (cx, cy) == (ex, ey):
                break

            current_cost = cost_so_far[(cx, cy)]
            if current_cost > max_dist * 10: # Ajuste do limite pelo custo base
                continue

            for dx, dy, move_cost in moves:
                nx, ny = cx + dx, cy + dy
                
                # Verifica se o tile destino é andável
                if _walkable(nx, ny, sz):

                    # CUSTO EXTRA: Se for diagonal, verificar se não está "cortando parede" (opcional mas recomendado)
                    # No Tibia, você não pode andar diagonal se os dois cardinais adjacentes forem bloqueados.
                    # Para o GlobalMap (Macro), geralmente ignoramos isso para performance, 
                    # mas se o bot travar muito em quinas, podemos adicionar a verificação aqui.
                    
                    new_cost = current_cost + move_cost
                    
                    if (nx, ny) not in cost_so_far or new_cost < cost_so_far[(nx, ny)]:
                        cost_so_far[(nx, ny)] = new_cost
                        
                        # Heurística Manhattan para grid-based pathfinding
                        # Manhattan distance é mais apropriado para movimento em tiles (Tibia)

                        h_cost = (abs(ex - nx) + abs(ey - ny)) * 10
                        priority = new_cost + h_cost
                        
                        heapq.heappush(open_list, (priority, h_cost, nx, ny))
                        came_from[(nx, ny)] = (cx, cy)
        
        if (ex, ey) not in came_from:
            return None
        
        # Reconstrói caminho
        path = []
        curr = (ex, ey)
        while curr != (sx, sy):
            path.append((curr[0], curr[1], sz))
            curr = came_from[curr]
        path.reverse()
        return path

    def get_path_with_fallback(self, start_pos, end_pos, max_offset=2):
        """
        Tenta calcular caminho para o destino.
        Se falhar, tenta tiles adjacentes (fallback inteligente).

        Args:
            start_pos: (x, y, z)
            end_pos: (x, y, z) - waypoint desejado
            max_offset: Raio de busca de tiles adjacentes (padrão: 2)

        Returns:
            Lista de (x, y, z) ou None se nenhum caminho for achado
        """
        from config import DEBUG_GLOBAL_MAP

        ex, ey, ez = end_pos

        # Tentativa 1: Rota direta para o waypoint
        path = self.get_path(start_pos, end_pos)
        if path:
            if DEBUG_GLOBAL_MAP:
                print(f"[GlobalMap] [OK] Rota direta encontrada para waypoint {end_pos}")
            return path

        # Tentativa 2: Buscar tile adjacente walkable
        if DEBUG_GLOBAL_MAP:
            print(f"[GlobalMap] 🔍 Rota direta falhou. Buscando tiles adjacentes...")

        # Busca em espiral: tiles mais próximos primeiro
        candidates = []
        for dist in range(1, max_offset + 1):
            for dx in range(-dist, dist + 1):
                for dy in range(-dist, dist + 1):
                    if abs(dx) == dist or abs(dy) == dist:  # Apenas borda do quadrado
                        nx, ny = ex + dx, ey + dy
                        candidates.append((nx, ny, ez, abs(dx) + abs(dy), dx, dy))

        # Ordena por distância Manhattan (tiles mais próximos primeiro)
        candidates.sort(key=lambda c: c[3])

        # Tenta cada candidato
        for nx, ny, nz, dist, dx, dy in candidates:
            # Verifica se tile é walkable no mapa global
            if not self.is_walkable(nx, ny, nz):
                continue

            # Tenta calcular rota ate esse tile vizinho
            neighbor_end = (nx, ny, nz)
            path = self.get_path(start_pos, neighbor_end)

            if path:
                if DEBUG_GLOBAL_MAP:
                    print(f"[GlobalMap] [OK] Rota alternativa encontrada!")
                    print(f"[GlobalMap]   Waypoint original: ({ex}, {ey}, {ez})")
                    print(f"[GlobalMap]   Tile alternativo: ({nx}, {ny}, {nz}) [offset: ({dx:+d}, {dy:+d})]")
                    print(f"[GlobalMap]   Distância ao waypoint: {dist} sqm")
                return path

        # Nenhum tile adjacente funcionou
        if DEBUG_GLOBAL_MAP:
            print(f"[GlobalMap] [X] FALHA COMPLETA: Nem waypoint nem tiles adjacentes (raio {max_offset}) têm rota")

        #self.diagnose_path_failure(start_pos, end_pos)

        return None
    
    # ── A* 3D Multi-Nível ──────────────────────────────────────────

    def _heuristic_3d(self, pos, goal):
        dx = abs(pos[0] - goal[0])
        dy = abs(pos[1] - goal[1])
        dz = abs(pos[2] - goal[2])
        # Octile 2D (admissível com cardinal=10, diagonal=30)
        h_2d = 10 * max(dx, dy) + 20 * min(dx, dy)
        h_z = dz * LEVEL_PENALTY
        return h_2d + h_z

    def _get_neighbors_3d(self, x, y, z, _walkable=None):
        if _walkable is None:
            _walkable = self.is_walkable
        neighbors = []
        # 8 direções no mesmo andar
        for dx, dy, cost in (
            (0, 1, COST_CARDINAL), (0, -1, COST_CARDINAL),
            (1, 0, COST_CARDINAL), (-1, 0, COST_CARDINAL),
            (1, 1, COST_DIAGONAL), (1, -1, COST_DIAGONAL),
            (-1, 1, COST_DIAGONAL), (-1, -1, COST_DIAGONAL),
        ):
            nx, ny = x + dx, y + dy
            if not _walkable(nx, ny, z, ignore_transitions=True):
                continue
            # Diagonal: checar corner-cutting
            if dx != 0 and dy != 0:
                if not _walkable(x + dx, y, z, ignore_transitions=True) or not _walkable(x, y + dy, z, ignore_transitions=True):
                    continue
            neighbors.append(((nx, ny, z), cost))

        # Transições de andar
        for z_to in self._transition_lookup.get((x, y, z), []):
            neighbors.append(((x, y, z_to), COST_TRANSITION))

        return neighbors

    def get_path_multilevel(self, start_pos, end_pos, max_iter=150000, debug=False, offline=False):
        sx, sy, sz = start_pos
        ex, ey, ez = end_pos
        _walkable = self.is_walkable_offline if offline else self.is_walkable

        def _dbg(msg):
            if debug:
                print(f"  [DEBUG] {msg}")

        _dbg(f"start=({sx},{sy},{sz}) end=({ex},{ey},{ez})")

        # Se destino não é walkable, buscar vizinho
        if not _walkable(ex, ey, ez):
            _dbg(f"Destino nao walkable (cor={self.get_color_id(ex, ey, ez)}), buscando vizinho...")
            found = False
            for dx in range(-1, 2):
                for dy in range(-1, 2):
                    if dx == 0 and dy == 0:
                        continue
                    if _walkable(ex + dx, ey + dy, ez):
                        _dbg(f"Vizinho walkable: ({ex+dx},{ey+dy},{ez})")
                        ex, ey = ex + dx, ey + dy
                        found = True
                        break
                if found:
                    break
            if not found:
                _dbg("Nenhum vizinho walkable encontrado - abortando")
                return None

        goal = (ex, ey, ez)
        start = (sx, sy, sz)

        # Checar transições disponíveis nos andares envolvidos
        if debug:
            floors_needed = set(range(min(sz, ez), max(sz, ez) + 1))
            for fl in sorted(floors_needed):
                count = len(self._transitions_by_floor.get(fl, []))
                _dbg(f"Transicoes no andar {fl}: {count}")
                if count <= 10:
                    for t in self._transitions_by_floor.get(fl, []):
                        _dbg(f"  ({t[0]},{t[1]}) -> z={t[2]}")

        g_score = {start: 0}
        came_from = {}
        h_start = self._heuristic_3d(start, goal)
        open_list = [(h_start, h_start, sx, sy, sz)]

        iterations = 0
        floors_visited = set()
        transitions_used = 0
        closest_dist = float('inf')
        closest_node = start

        while open_list and iterations < max_iter:
            iterations += 1
            _, _, cx, cy, cz = heapq.heappop(open_list)
            current = (cx, cy, cz)

            floors_visited.add(cz)

            # Rastrear nó mais próximo do goal
            dist = abs(cx - goal[0]) + abs(cy - goal[1]) + abs(cz - goal[2]) * 50
            if dist < closest_dist:
                closest_dist = dist
                closest_node = current

            if current == goal:
                _dbg(f"Rota encontrada! iterations={iterations} floors_visited={sorted(floors_visited)}")
                path = []
                node = goal
                while node != start:
                    path.append(node)
                    node = came_from[node]
                path.reverse()
                return path

            current_g = g_score.get(current)
            if current_g is None:
                continue

            for neighbor, move_cost in self._get_neighbors_3d(cx, cy, cz, _walkable=_walkable):
                if debug and neighbor[2] != cz:
                    transitions_used += 1
                    if transitions_used <= 20:
                        _dbg(f"Transicao: ({cx},{cy},{cz}) -> ({neighbor[0]},{neighbor[1]},{neighbor[2]}) cost={move_cost}")
                new_g = current_g + move_cost
                if new_g < g_score.get(neighbor, float('inf')):
                    g_score[neighbor] = new_g
                    came_from[neighbor] = current
                    h = self._heuristic_3d(neighbor, goal)
                    heapq.heappush(open_list, (new_g + h, h, neighbor[0], neighbor[1], neighbor[2]))

            if debug and iterations % 30000 == 0:
                _dbg(f"... {iterations} iteracoes, {len(g_score)} nos visitados, "
                     f"floors={sorted(floors_visited)}, closest={closest_node} (dist={closest_dist})")

        if debug:
            _dbg(f"FALHOU: {iterations} iteracoes, {len(g_score)} nos visitados")
            _dbg(f"  Floors visitados: {sorted(floors_visited)}")
            _dbg(f"  Transicoes expandidas: {transitions_used}")
            _dbg(f"  No mais proximo do goal: {closest_node} (dist_manhattan={closest_dist})")
            _dbg(f"  Open list restante: {len(open_list)}")
            if closest_node[2] == sz:
                _dbg(f"  !! Nunca mudou de andar - pode ser problema nas transicoes")
            self._last_debug = {
                'closest_node': closest_node,
                'floors_visited': sorted(floors_visited),
                'visited_count': len(g_score),
            }

        return None

    # ── Debug / Diagnóstico ──────────────────────────────────────

    def diagnose_path_failure(self, start_pos, end_pos):
        """
        Retorna dados de diagnóstico para visualização (caminho parcial e barreiras).
        """
        print("\n--- 🔍 DIAGNÓSTICO DE BLOQUEIO 🔍 ---")
        sx, sy, sz = start_pos
        ex, ey, ez = end_pos
        
        # 1. Checagem Básica
        start_color = self.get_color_id(sx, sy, sz)
        end_color = self.get_color_id(ex, ey, ez)
        
        if start_color not in self.walkable_ids:
            print(f"[X] ERRO: A origem é parede (Cor {start_color}).")
        if end_color not in self.walkable_ids:
            print(f"[X] ERRO: O destino é parede (Cor {end_color}).")

        # 2. Flood Fill (Busca o caminho mais próximo possível)
        print("🌊 Executando Flood Fill para mapear obstáculos...")
        result = self._debug_flood_fill(start_pos, end_pos)
        
        closest_point = result['closest_point']
        barriers = result['barrier_colors']
        
        dist_remaining = abs(ex - closest_point[0]) + abs(ey - closest_point[1])
        print(f"[X] O bot travou a {dist_remaining:.1f} sqm do destino.")
        print(f"📍 Ponto mais próximo alcançado: {closest_point}")
        print(f"🎨 Cores das barreiras encontradas: {list(barriers)}")
        print("------------------------------------------------\n")
        
        return result

    def _debug_flood_fill(self, start, end, limit=30000):
        """
        Expande a partir da origem usando BFS para achar o caminho parcial.
        Retorna dicionário com dados para visualização.
        """
        sx, sy, sz = start
        ex, ey, ez = end
        
        queue = [(sx, sy)]
        came_from = {(sx, sy): None} # Rastreia o caminho para reconstrução
        barriers_coords = set()      # Onde bateu na parede
        barrier_colors = set()
        
        closest_dist = float('inf')
        closest_point = (sx, sy)
        
        steps = 0
        
        while queue and steps < limit:
            cx, cy = queue.pop(0)
            steps += 1
            
            # Atualiza o ponto mais próximo do destino que conseguimos chegar (Manhattan distance)
            dist = abs(ex - cx) + abs(ey - cy)
            if dist < closest_dist:
                closest_dist = dist
                closest_point = (cx, cy)
            
            if (cx, cy) == (ex, ey):
                break # Milagrosamente achou (não deveria acontecer se o A* falhou)
            
            # Checa vizinhos
            for dx, dy in [(0,1), (0,-1), (1,0), (-1,0)]:
                nx, ny = cx + dx, cy + dy
                
                if (nx, ny) in came_from:
                    continue
                
                color = self.get_color_id(nx, ny, sz)
                
                if color in self.walkable_ids:
                    came_from[(nx, ny)] = (cx, cy)
                    queue.append((nx, ny))
                else:
                    # É uma barreira
                    barriers_coords.add((nx, ny))
                    barrier_colors.add(color)

        # Reconstrói o caminho parcial ate o ponto mais próximo
        partial_path = []
        curr = closest_point
        while curr:
            partial_path.append((curr[0], curr[1], sz))
            curr = came_from.get(curr)
        partial_path.reverse()

        return {
            'visited_coords': set(came_from.keys()), # Onde a "água" tocou (azul)
            'partial_path': partial_path,            # Caminho laranja ate o travamento
            'barrier_coords': barriers_coords,       # Paredes vermelhas que tocaram na água
            'barrier_colors': barrier_colors,
            'closest_point': (closest_point[0], closest_point[1], sz)
        }