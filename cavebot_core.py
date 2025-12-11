import time
import json
import os
import math
import packet
from map_core import get_player_pos
from config import ROD_ID # Ou defina IDs de ferramentas aqui

# IDs de Ferramentas (Ajuste conforme seu servidor)
ID_ROPE = 3003
ID_SHOVEL = 3457

# --- Módulos de Inteligência ---
from scanner_core import scan_tile
from items_core import is_blocking
from grid_core import GridMap, TILE_STATIC, TILE_TEMP

class CavebotManager:
    def __init__(self, pm, base_addr):
        self.pm = pm
        self.base_addr = base_addr
        self.waypoints = [] 
        self.current_index = 0
        
        # Inteligência
        self.grid = GridMap()
        self.hwnd = 0 
        self.game_view = None 
        
        # Estado
        self.is_recording = False
        self.last_recorded_pos = (0,0,0)
        
        self.last_walk_time = 0
        self.last_player_pos = (0,0,0)
        self.stuck_count = 0
        self.last_attempted_direction = None 
        self.action_retries = 0

    # ... [MÉTODOS DE ARQUIVO: get_scripts_dir, save, load, clear - MANTIDOS] ...
    # (Copie os mesmos métodos da versão anterior para economizar espaço aqui)
    
    def get_scripts_dir(self):
        directory = "cavebot_scripts"
        if not os.path.exists(directory): os.makedirs(directory)
        return directory

    def clear(self):
        self.waypoints = []
        self.current_index = 0
        self.grid.clear()
        print("[CAVEBOT] Limpo.")

    def save_waypoints(self, filename="default"):
        try:
            if not filename.lower().endswith(".json"): filename += ".json"
            path = os.path.join(self.get_scripts_dir(), filename)
            with open(path, 'w') as f: json.dump(self.waypoints, f, indent=4)
            print(f"[CAVEBOT] Salvo: {path}")
            return True
        except: return False

    def load_waypoints(self, filename="default"):
        try:
            if not filename.lower().endswith(".json"): filename += ".json"
            path = os.path.join(self.get_scripts_dir(), filename)
            with open(path, 'r') as f: self.waypoints = json.load(f)
            self.current_index = 0
            self.grid.clear()
            print(f"[CAVEBOT] Carregado de: {path}")
            return True
        except: return False
    
    # =========================================================================
    # RECORDER (GRAVA COMO 'WALK' PARA PRECISÃO)
    # =========================================================================
    def start_recording(self):
        self.is_recording = True
        print("[REC] Iniciado...")

    def stop_recording(self):
        self.is_recording = False
        print(f"[REC] Parado. {len(self.waypoints)} pontos.")

    def add_waypoint(self, wp_type, x, y, z, options=None):
        self.waypoints.append({
            'type': wp_type.upper(), 
            'x': int(x), 'y': int(y), 'z': int(z),
            'options': options if options else {}
        })

    def record_step(self):
        if not self.is_recording: return
        px, py, pz = get_player_pos(self.pm, self.base_addr)
        if px == 0: return

        if not self.waypoints:
            self.add_waypoint("WALK", px, py, pz)
            self.last_recorded_pos = (px, py, pz)
            return

        lx, ly, lz = self.last_recorded_pos
        if (px, py, pz) == (lx, ly, lz): return

        # Se mudou de andar, grava o ponto anterior como LADDER (tentativa de inteligência)
        # ou apenas grava o novo ponto. Vamos manter simples: Grava onde pisou.
        # No futuro, podemos detectar se usou escada e mudar o tipo do WP anterior.
        
        if px != lx or py != ly or pz != lz:
            # Grava como WALK para garantir precisão
            self.add_waypoint("WALK", px, py, pz)
            self.last_recorded_pos = (px, py, pz)

    # =========================================================================
    # LÓGICA DE EXECUÇÃO (CRYSTAL STYLE)
    # =========================================================================
    
    def get_next_waypoint(self):
        if not self.waypoints: return None
        return self.waypoints[self.current_index % len(self.waypoints)]

    def get_neighbors(self, px, py):
        return [
            (0, -1, packet.OP_WALK_NORTH), (0, 1, packet.OP_WALK_SOUTH),
            (1, 0, packet.OP_WALK_EAST), (-1, 0, packet.OP_WALK_WEST),
            (1, -1, packet.OP_WALK_NORTH_EAST), (-1, -1, packet.OP_WALK_NORTH_WEST),
            (1, 1, packet.OP_WALK_SOUTH_EAST), (-1, 1, packet.OP_WALK_SOUTH_WEST)
        ]

    def get_smart_move(self, px, py, pz, tx, ty):
        # ... (Mesma lógica do Smart Walker anterior) ...
        neighbors = self.get_neighbors(px, py)
        valid_moves = []

        for dx, dy, opcode in neighbors:
            target_x = px + dx
            target_y = py + dy
            if self.grid.is_blocked(target_x, target_y, pz): continue
            
            dist = math.sqrt((tx - target_x)**2 + (ty - target_y)**2)
            if dx != 0 and dy != 0: dist += 0.5 
            valid_moves.append((dist, opcode, dx, dy))

        if not valid_moves:
            self.grid.clear()
            return None, 0, 0

        valid_moves.sort(key=lambda x: x[0])
        _, best_opcode, best_dx, best_dy = valid_moves[0]
        return best_opcode, best_dx, best_dy

    def handle_stuck(self, px, py, pz):
        # ... (Mesma lógica do Probe/Scan anterior) ...
        if not self.last_attempted_direction: return
        
        attempt_dx, attempt_dy = self.last_attempted_direction
        block_x = px + attempt_dx
        block_y = py + attempt_dy
        
        from map_core import get_game_view
        if not self.game_view: self.game_view = get_game_view(self.pm, self.base_addr)
        
        if self.game_view:
            print(f"[SMART] Obstáculo em ({attempt_dx}, {attempt_dy}). Sondando...")
            tile_id = scan_tile(self.pm, self.base_addr, self.hwnd, self.game_view, attempt_dx, attempt_dy)
            
            if tile_id > 0:
                if is_blocking(tile_id):
                    self.grid.mark_tile(block_x, block_y, pz, TILE_STATIC)
                else:
                    self.grid.mark_tile(block_x, block_y, pz, TILE_TEMP)
            else:
                 self.grid.mark_tile(block_x, block_y, pz, TILE_TEMP)

    def run_cycle(self):
        if self.is_recording:
            self.record_step()
            return
        if not self.waypoints: return
        if not self.hwnd:
             import win32gui
             self.hwnd = win32gui.FindWindow("TibiaClient", None)

        if time.time() - self.last_walk_time < 0.4: return 

        px, py, pz = get_player_pos(self.pm, self.base_addr)
        if px == 0: return

        wp = self.get_next_waypoint()
        if not wp: return

        # --- LÓGICA POR TIPO DE WAYPOINT ---
        
        dist_xy = max(abs(px - wp['x']), abs(py - wp['y']))
        
        # 1. TIPO: WALK (Caminhada Precisa)
        if wp['type'] == 'WALK':
            if pz != wp['z']:
                # Mudou de andar inesperadamente (ou chegou perto de escada anterior)
                if dist_xy < 8: self.current_index = (self.current_index + 1) % len(self.waypoints)
                return
            
            if dist_xy == 0: # Chegou exatamente
                self.current_index = (self.current_index + 1) % len(self.waypoints)
                return

        # 2. TIPO: NODE (Caminhada Solta)
        elif wp['type'] == 'NODE':
            if pz != wp['z']:
                 self.current_index = (self.current_index + 1) % len(self.waypoints)
                 return
            
            if dist_xy <= 3: # Tolerância de 3 SQM
                print(f"[NODE] Perto o suficiente ({dist_xy} sqm). Próximo.")
                self.current_index = (self.current_index + 1) % len(self.waypoints)
                return

        # 3. TIPO: ROPE (Usar Corda)
        elif wp['type'] == 'ROPE':
            if pz != wp['z']: # Se o andar já mudou (subiu), sucesso!
                print("[ROPE] Sucesso. Andar mudou.")
                self.action_retries = 0
                self.current_index = (self.current_index + 1) % len(self.waypoints)
                return
            
            # Se não mudou, precisamos ir para o local e usar a corda
            if dist_xy > 1: # Longe do buraco
                self.perform_walk(px, py, pz, wp['x'], wp['y'])
                return
            
            # Perto do buraco: Usar Corda
            # Precisa implementar busca da corda no inventario, por enquanto hardcoded
            rope_pos = packet.get_inventory_pos(packet.SLOT_BP) # Exemplo
            target_pos = packet.get_ground_pos(wp['x'], wp['y'], wp['z'])
            
            if time.time() - self.last_walk_time > 1.0: # 1s cooldown para ação
                print("[ROPE] Usando corda...")
                packet.use_with(self.pm, rope_pos, ID_ROPE, 0, target_pos, 0, 0)
                self.last_walk_time = time.time()
                self.action_retries += 1
            return

        # 4. TIPO: LADDER (Escada)
        elif wp['type'] == 'LADDER':
            if pz != wp['z']:
                print("[LADDER] Sucesso.")
                self.current_index = (self.current_index + 1) % len(self.waypoints)
                return
            
            if dist_xy > 0: # Precisa estar EM CIMA da escada para subir (geralmente)
                self.perform_walk(px, py, pz, wp['x'], wp['y'])
                return
            
            # Está em cima. Se não subiu automático, tenta "Use" no chão
            if time.time() - self.last_walk_time > 1.0:
                print("[LADDER] Tentando usar escada...")
                my_pos = packet.get_ground_pos(px, py, pz)
                packet.use_item(self.pm, my_pos, 99, 0)
                self.last_walk_time = time.time()
            return
            
        # --- Execução Padrão de Movimento (Se caiu num bloco de andar) ---
        self.perform_walk(px, py, pz, wp['x'], wp['y'])

    def perform_walk(self, px, py, pz, tx, ty):
        """Função auxiliar que contém a lógica de Stuck e Smart Move"""
        # Anti-Stuck Check
        if self.last_player_pos == (px, py, pz):
            self.stuck_count += 1
            if self.stuck_count >= 2: self.handle_stuck(px, py, pz)
            if self.stuck_count > 8:
                print("[STUCK] Pulando WP forçado.")
                self.current_index = (self.current_index + 1) % len(self.waypoints)
                self.stuck_count = 0
                return
        else:
            self.stuck_count = 0
            self.last_player_pos = (px, py, pz)
            
        # Movimento
        opcode, dx, dy = self.get_smart_move(px, py, pz, tx, ty)
        if opcode:
            packet.walk(self.pm, opcode)
            self.last_walk_time = time.time()
            self.last_attempted_direction = (dx, dy)