import os
import heapq
import math
import time

class GlobalMap:
    def __init__(self, maps_dir, walkable_ids):
        self.maps_dir = maps_dir
        self.walkable_ids = set(walkable_ids) # Ex: {186, 121} - IDs que são chão
        self.cache = {} # Cache de arquivos carregados
        self.temporary_obstacles = {} # (x, y, z) -> timestamp

    def get_color_id(self, abs_x, abs_y, abs_z):
        """Lê o byte do arquivo .map correto."""
        chunk_x = abs_x // 256
        chunk_y = abs_y // 256
        
        # Tenta os formatos de nome padrão do Tibia
        filenames = [
            f"{chunk_x}{chunk_y}{abs_z:02}.map",
            f"{chunk_x:03}{chunk_y:03}{abs_z:02}.map"
        ]
        
        filename = None
        for f in filenames:
            if os.path.exists(os.path.join(self.maps_dir, f)):
                filename = f
                break
        
        if not filename: return 0 # Mapa não existe/não explorado

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

    def is_walkable(self, x, y, z):
        # 1. Verifica bloqueio temporário
        if (x, y, z) in self.temporary_obstacles:
            if time.time() < self.temporary_obstacles[(x, y, z)]:
                return False
            else:
                del self.temporary_obstacles[(x, y, z)] # Expire

        # 2. Verifica cor do mapa
        color = self.get_color_id(x, y, z)
        return color in self.walkable_ids

    def add_temp_block(self, x, y, z, duration=10):
        """Bloqueia um tile temporariamente (ex: player trapando)."""
        self.temporary_obstacles[(x, y, z)] = time.time() + duration

    def clear_temp_blocks(self):
        self.temporary_obstacles.clear()

    def get_path(self, start_pos, end_pos, max_dist=5000):
        """
        A* Global com suporte a diagonais.
        Retorna lista [(x,y,z), (x,y,z)...] do início ao fim.
        """
        sx, sy, sz = start_pos
        ex, ey, ez = end_pos
        
        if sz != ez: return None # Apenas mesmo andar
        
        # Otimização: Se destino for parede, tenta vizinho
        if not self.is_walkable(ex, ey, ez):
            found = False
            # Procura vizinho andável (incluindo diagonais agora)
            for dx in [-1, 0, 1]:
                for dy in [-1, 0, 1]:
                    if dx == 0 and dy == 0: continue
                    if self.is_walkable(ex+dx, ey+dy, ez):
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
        
        while open_list:
            _, _, cx, cy = heapq.heappop(open_list)
            
            if (cx, cy) == (ex, ey):
                break
            
            current_cost = cost_so_far[(cx, cy)]
            if current_cost > max_dist * 10: # Ajuste do limite pelo custo base
                continue

            for dx, dy, move_cost in moves:
                nx, ny = cx + dx, cy + dy
                
                # Verifica se o tile destino é andável
                if self.is_walkable(nx, ny, sz):
                    
                    # CUSTO EXTRA: Se for diagonal, verificar se não está "cortando parede" (opcional mas recomendado)
                    # No Tibia, você não pode andar diagonal se os dois cardinais adjacentes forem bloqueados.
                    # Para o GlobalMap (Macro), geralmente ignoramos isso para performance, 
                    # mas se o bot travar muito em quinas, podemos adicionar a verificação aqui.
                    
                    new_cost = current_cost + move_cost
                    
                    if (nx, ny) not in cost_so_far or new_cost < cost_so_far[(nx, ny)]:
                        cost_so_far[(nx, ny)] = new_cost
                        
                        # Heurística Manhatan ou Euclidiana ajustada para escala 10
                        # Euclidiana é melhor para grids com diagonais
                        h_cost = int(math.sqrt((ex-nx)**2 + (ey-ny)**2) * 10)
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
                print(f"[GlobalMap] ✅ Rota direta encontrada para waypoint {end_pos}")
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

            # Tenta calcular rota até esse tile vizinho
            neighbor_end = (nx, ny, nz)
            path = self.get_path(start_pos, neighbor_end)

            if path:
                if DEBUG_GLOBAL_MAP:
                    print(f"[GlobalMap] ✅ Rota alternativa encontrada!")
                    print(f"[GlobalMap]   Waypoint original: ({ex}, {ey}, {ez})")
                    print(f"[GlobalMap]   Tile alternativo: ({nx}, {ny}, {nz}) [offset: ({dx:+d}, {dy:+d})]")
                    print(f"[GlobalMap]   Distância ao waypoint: {dist} sqm")
                return path

        # Nenhum tile adjacente funcionou
        if DEBUG_GLOBAL_MAP:
            print(f"[GlobalMap] ❌ FALHA COMPLETA: Nem waypoint nem tiles adjacentes (raio {max_offset}) têm rota")

        #self.diagnose_path_failure(start_pos, end_pos)

        return None
    
    # Adicione isso dentro da classe GlobalMap, no final do arquivo
    # Adicione/Substitua estes métodos na classe GlobalMap
    
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
            print(f"❌ ERRO: A origem é parede (Cor {start_color}).")
        if end_color not in self.walkable_ids:
            print(f"❌ ERRO: O destino é parede (Cor {end_color}).")

        # 2. Flood Fill (Busca o caminho mais próximo possível)
        print("🌊 Executando Flood Fill para mapear obstáculos...")
        result = self._debug_flood_fill(start_pos, end_pos)
        
        closest_point = result['closest_point']
        barriers = result['barrier_colors']
        
        dist_remaining = math.sqrt((ex - closest_point[0])**2 + (ey - closest_point[1])**2)
        print(f"❌ O bot travou a {dist_remaining:.1f} sqm do destino.")
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
            
            # Atualiza o ponto mais próximo do destino que conseguimos chegar
            dist = math.sqrt((ex - cx)**2 + (ey - cy)**2)
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

        # Reconstrói o caminho parcial até o ponto mais próximo
        partial_path = []
        curr = closest_point
        while curr:
            partial_path.append((curr[0], curr[1], sz))
            curr = came_from.get(curr)
        partial_path.reverse()

        return {
            'visited_coords': set(came_from.keys()), # Onde a "água" tocou (azul)
            'partial_path': partial_path,            # Caminho laranja até o travamento
            'barrier_coords': barriers_coords,       # Paredes vermelhas que tocaram na água
            'barrier_colors': barrier_colors,
            'closest_point': (closest_point[0], closest_point[1], sz)
        }