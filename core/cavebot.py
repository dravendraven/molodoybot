# core/cavebot.py
import time
import math
from config import *
from core.packet import *
from core.map_core import get_player_pos
from core.map_analyzer import MapAnalyzer
from core.astar_walker import AStarWalker
from core.memory_map import MemoryMap
from core.inventory_core import find_item_in_containers, find_item_in_equipment # Necessário para achar a corda
from database.tiles_config import ROPE_ITEM_ID

# Mapeamento de Delta (dx, dy) para Opcode do Packet
MOVE_OPCODES = {
    (0, -1): OP_WALK_NORTH,
    (0, 1):  OP_WALK_SOUTH,
    (-1, 0): OP_WALK_WEST,
    (1, 0):  OP_WALK_EAST,
    (1, -1): OP_WALK_NORTH_EAST,
    (1, 1):  OP_WALK_SOUTH_EAST,
    (-1, 1): OP_WALK_SOUTH_WEST,
    (-1, -1): OP_WALK_NORTH_WEST
}

class Cavebot:
    def __init__(self, pm, base_addr):
        self.pm = pm
        self.base_addr = base_addr
        
        # Inicializa o MemoryMap e o Analisador
        self.memory_map = MemoryMap(pm, base_addr)
        self.analyzer = MapAnalyzer(self.memory_map)
        self.walker = AStarWalker(self.analyzer)
        
        self.waypoints = []
        self.current_index = 0
        self.enabled = False
        self.last_action_time = 0
        self.walk_delay = 0.5 # 500ms entre passos

    def load_waypoints(self, waypoints_list):
        """
        Carrega lista de waypoints.
        Ex: [{'x': 32000, 'y': 32000, 'z': 7, 'action': 'walk'}, ...]
        """
        self.waypoints = waypoints_list
        self.current_index = 0

    def start(self):
        self.enabled = True

    def stop(self):
        self.enabled = False

    def run_cycle(self):
        """Deve ser chamado no loop principal do bot."""
        if not self.enabled or not self.waypoints:
            return

        # Controle de Cooldown
        if time.time() - self.last_action_time < self.walk_delay:
            return

        # 1. Atualizar Posição e Mapa
        px, py, pz = get_player_pos(self.pm, self.base_addr)
        
        # Precisamos do Player ID para ler o mapa corretamente (calibração)
        # Lendo do offset definido no config.py
        player_id = self.pm.read_int(self.base_addr + OFFSET_PLAYER_ID)
        self.memory_map.read_full_map(player_id)

        # 2. Selecionar Waypoint Atual
        wp = self.waypoints[self.current_index]

        # 3. Checar se chegou (Distância < 1.5 SQM e mesmo Z)
        dist = math.sqrt((wp['x'] - px)**2 + (wp['y'] - py)**2)
        
        if dist <= 1.5 and wp['z'] == pz:
            print(f"[Cavebot] Chegou no WP {self.current_index}")
            self.current_index = (self.current_index + 1) % len(self.waypoints)
            return

        # ======================================================================
        # 4. LÓGICA DE ANDARES (FLOOR CHANGE)
        # ======================================================================
        if wp['z'] != pz:
            # O scanner retorna: (rel_x, rel_y, type, special_id)
            floor_target = self.analyzer.scan_for_floor_change(wp['z'], pz)
            
            if floor_target:
                fx, fy, ftype, fid = floor_target
                
                # Distância até o objeto especial
                # Se fx, fy são relativos, a distância é a magnitude do vetor
                dist_obj = math.sqrt(fx**2 + fy**2)

                # Se estamos ADJACENTES (dist <= 1.5) ou EM CIMA (dist == 0)
                # Para Ladder e Rope, precisamos estar PERTO.
                if dist_obj <= 1.5:
                    self._handle_special_tile(fx, fy, ftype, fid, px, py, pz)

                    # Após uma interação de andar/usar, a posição global pode ter mudado (ex: subir de andar).
                    npx, npy, npz = get_player_pos(self.pm, self.base_addr)
                    if wp['z'] == npz:
                        dist_after = math.sqrt((wp['x'] - npx) ** 2 + (wp['y'] - npy) ** 2)
                        if dist_after <= 1.5:
                            print(f"[Cavebot] Chegou no WP {self.current_index} após floor change")
                            self.current_index = (self.current_index + 1) % len(self.waypoints)
                            self.last_action_time = time.time()
                            return
                else:
                    # Para escadas de USE, prefira parar em um tile cardinal adjacente e usar à distância.
                    target_fx, target_fy = fx, fy
                    if ftype == 'UP_USE':
                        target_fx, target_fy = self._get_adjacent_use_tile(fx, fy)

                    # A escada está longe. Usa A* para chegar nela (ou ao adjacente definido).
                    step = self.walker.get_next_step(target_fx, target_fy)
                    if step:
                        self._move_step(step[0], step[1])
                    else:
                        print("[Cavebot] Caminho para a escada bloqueado.")
            else:
                print(f"[Cavebot] Stuck? WP Z={wp['z']} vs Player Z={pz}. Nenhuma escada vista.")
            
            self.last_action_time = time.time()
            return

        # 5. Caminho Normal (A*)
        target_rel_x = wp['x'] - px
        target_rel_y = wp['y'] - py

        # --- LÓGICA DE HORIZONTE (FIX PARA CAMINHOS LONGOS) ---
        # O MemoryMap geralmente lê com segurança uns 7 a 9 sqms do centro.
        # Se o destino for mais longe que isso, o A* vai falhar.
        # Precisamos criar um "Sub-Destino" na borda da visão.
        
        MAX_VIEW_RANGE = 7 # Limite seguro de leitura de memória
        
        # Distância Chebyshev (maior eixo)
        dist_axis = max(abs(target_rel_x), abs(target_rel_y))
        
        walk_x, walk_y = target_rel_x, target_rel_y

        if dist_axis > MAX_VIEW_RANGE:
            # Regra de 3 para encurtar o vetor mantendo o ângulo
            factor = MAX_VIEW_RANGE / dist_axis
            walk_x = int(target_rel_x * factor)
            walk_y = int(target_rel_y * factor)
            # Exemplo: Se o alvo é (20, 0) -> vira (7, 0)
            # Exemplo: Se o alvo é (20, 20) -> vira (7, 7)
        
        # -----------------------------------------------------
        
        # Pede o próximo passo ao A*
        next_step = self.walker.get_next_step(walk_x, walk_y)
        
        if next_step:
            dx, dy = next_step
            self._move_step(dx, dy)
        else:
            print("[Cavebot] Caminho bloqueado ou calculando...")

        self.last_action_time = time.time()

    def _move_step(self, dx, dy):
        """Envia o pacote de andar."""
        opcode = MOVE_OPCODES.get((dx, dy))
        if opcode:
            walk(self.pm, opcode)
        else:
            print(f"[Cavebot] Direção inválida: {dx}, {dy}")

    def _handle_special_tile(self, rel_x, rel_y, ftype, special_id, px, py, pz):
        """Executa a ação correta para tiles especiais (escadas, buracos, rope)."""
        abs_x = px + rel_x
        abs_y = py + rel_y
        target_pos = get_ground_pos(abs_x, abs_y, pz)
        special_id = special_id or 0

        if ftype in ['UP_WALK', 'DOWN']:
            # Essas escadas sobem/descem apenas caminhando até elas.
            if rel_x != 0 or rel_y != 0:
                self._move_step(rel_x, rel_y)
            return

        if ftype == 'UP_USE':
            manhattan = abs(rel_x) + abs(rel_y)
            if manhattan == 0:
                # Já estamos em cima da ladder, apenas usa.
                self._use_ladder_tile(target_pos, special_id, 0, 0)
            elif manhattan == 1:
                # Adjacente cardinal: usa à distância.
                self._use_ladder_tile(target_pos, special_id, rel_x, rel_y)
            else:
                # Diagonal ou mais longe: alinhar para um tile cardinal e tentar novamente.
                if not self._ensure_cardinal_adjacent(rel_x, rel_y, label="ladder"):
                    return
            return

        if ftype == 'ROPE':
            # Rope precisa de adjacência cardeal, tile livre e corda no inventário.
            if not self._ensure_cardinal_adjacent(rel_x, rel_y):
                return
            if not self._clear_rope_spot(rel_x, rel_y, px, py, pz, special_id or 386):
                return
            rope_source = self._get_rope_source_position()
            if not rope_source:
                print("[Cavebot] Corda (3003) não encontrada em containers ou mãos.")
                return
            use_with(self.pm, rope_source, ROPE_ITEM_ID, 0, target_pos, special_id or 386, 0)
            return

        if ftype == 'SHOVEL':
            print("[Cavebot] Ação: USAR PÁ (Ainda não implementado).")
            return

    def _use_ladder_tile(self, target_pos, ladder_id, rel_x=0, rel_y=0):
        """Executa o packet de USE na ladder quando estivermos sobre ela."""
        if ladder_id == 0:
            print("[Cavebot] Ladder sem ID especial, abortando USE.")
            return
        stack_pos = 0
        ladder_tile = self.memory_map.get_tile(rel_x, rel_y)
        if ladder_tile and ladder_tile.items:
            # Procura o stackpos real do ID da ladder (última ocorrência = topo).
            for idx, item_id in enumerate(ladder_tile.items):
                if item_id == ladder_id:
                    stack_pos = idx
        else:
            print("[Cavebot] Tile da ladder não encontrado na memória, usando stack_pos=0.")

        use_item(self.pm, target_pos, ladder_id, stack_pos=stack_pos)

    def _get_adjacent_use_tile(self, ladder_rel_x, ladder_rel_y):
        """
        Escolhe um tile cardinal adjacente à ladder para usar à distância.
        Prioriza o mais próximo do player e walkable; fallback é o próprio tile da ladder.
        """
        options = [
            (ladder_rel_x + 1, ladder_rel_y),
            (ladder_rel_x - 1, ladder_rel_y),
            (ladder_rel_x, ladder_rel_y + 1),
            (ladder_rel_x, ladder_rel_y - 1),
        ]

        best = (ladder_rel_x, ladder_rel_y)
        best_dist = 999
        for ox, oy in options:
            props = self.analyzer.get_tile_properties(ox, oy)
            if not props['walkable']:
                continue
            dist = abs(ox) + abs(oy)
            if dist < best_dist:
                best_dist = dist
                best = (ox, oy)
        return best

    def _ensure_cardinal_adjacent(self, rel_x, rel_y, label="rope"):
        """
        Considera adjacente qualquer tile a 1 SQM de distância (incluindo diagonais).
        Se estiver mais longe que isso, tenta alinhar primeiro num eixo.
        """
        chebyshev = max(abs(rel_x), abs(rel_y))
        if chebyshev == 1:
            return True
        if chebyshev == 0:
            print(f"[Cavebot] {label.capitalize()} inválido (rel=0,0).")
            return False

        # Ajusta posicionamento tentando primeiro no eixo X.
        if rel_x != 0:
            self._move_step(rel_x, 0)
        elif rel_y != 0:
            self._move_step(0, rel_y)
        return False

    def _get_rope_source_position(self):
        """Procura a corda nos equipamentos ou containers e retorna a posição do packet."""
        equip = find_item_in_equipment(self.pm, self.base_addr, ROPE_ITEM_ID)
        if equip:
            slot_map = {'right': 5, 'left': 6, 'ammo': 10}
            slot_enum = slot_map.get(equip['slot'])
            if slot_enum:
                return get_inventory_pos(slot_enum)

        cont_data = find_item_in_containers(self.pm, self.base_addr, ROPE_ITEM_ID)
        if cont_data:
            return get_container_pos(cont_data['container_index'], cont_data['slot_index'])
        return None

    def _clear_rope_spot(self, rel_x, rel_y, px, py, pz, rope_tile_id):
        """
        Rope spot precisa estar livre.
        Caso o topo tenha item diferente do rope spot, tentamos arrastar para nosso tile.
        """
        tile = self.memory_map.get_tile(rel_x, rel_y)
        if not tile or tile.count == 0:
            print("[Cavebot] Tile do rope spot não encontrado na memória.")
            return False

        top_id = tile.get_top_item()
        rope_id = rope_tile_id or 386

        if top_id in (0, rope_id):
            return True

        if top_id == 99:
            print("[Cavebot] Rope spot bloqueado por criatura/jogador. Não moveremos por enquanto.")
            return False

        from_pos = get_ground_pos(px + rel_x, py + rel_y, pz)
        drop_pos = get_ground_pos(px, py, pz)
        move_item(self.pm, from_pos, drop_pos, top_id, 1)
        print(f"[Cavebot] Movendo item {top_id} para liberar rope spot.")
        return False
