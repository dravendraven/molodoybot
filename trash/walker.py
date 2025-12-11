import time
import packet 
from config import *
from map_reader import MapReader, CENTER_X_GRID, CENTER_Y_GRID
from pathfinder import astar_search

DIR_NORTH = 0x65
DIR_EAST  = 0x66
DIR_SOUTH = 0x67
DIR_WEST  = 0x68
OP_NE = 0x6A
OP_SE = 0x6B
OP_SW = 0x6C
OP_NW = 0x6D

class Walker:
    def __init__(self, pymem_instance):
        self.pm = pymem_instance
        self.map_reader = MapReader(self.pm)

    def get_player_pos(self):
        try:
            x = self.pm.read_int(PLAYER_X_ADDRESS)
            y = self.pm.read_int(PLAYER_Y_ADDRESS)
            z = self.pm.read_int(PLAYER_Z_ADDRESS)
            return x, y, z
        except:
            print("[DEBUG Walker] Erro lendo posição do player!")
            return 0, 0, 0

    def goto(self, target_x, target_y, target_z):
        print(f"\n[DEBUG Walker] GOTO Iniciado -> Destino: {target_x}, {target_y}, {target_z}")
        
        fail_count = 0
        
        while True:
            px, py, pz = self.get_player_pos()
            print(f"[DEBUG Loop] Estou em: {px}, {py}, {pz}")
            
            if (px, py, pz) == (target_x, target_y, target_z):
                print("[DEBUG Walker] SUCESSO: Cheguei no destino.")
                return True
                
            if pz != target_z:
                print(f"[DEBUG Walker] ERRO: Andar errado (Estou {pz} vs Alvo {target_z})")
                return False

            # 1. Mapa
            grid = self.map_reader.get_cost_grid(pz)
            if not grid: 
                print("[DEBUG Walker] ERRO: Grid retornou None/Vazio")
                return False
            
            # 2. Alvo na Grid
            rel_x = target_x - px
            rel_y = target_y - py
            grid_end_x = CENTER_X_GRID + rel_x
            grid_end_y = CENTER_Y_GRID + rel_y
            
            print(f"[DEBUG Walker] Delta Relativo: ({rel_x}, {rel_y}) -> Grid Destino: [{grid_end_x}, {grid_end_y}]")

            # Verifica limites
            if not (0 <= grid_end_x < 18 and 0 <= grid_end_y < 14):
                print("[DEBUG Walker] Destino longe demais da tela. Clampando...")
                grid_end_x = max(2, min(grid_end_x, 15))
                grid_end_y = max(2, min(grid_end_y, 11))
                print(f"[DEBUG Walker] Novo Grid Destino Temporário: [{grid_end_x}, {grid_end_y}]")
            
            # 3. Pathfinder
            start_node = (CENTER_X_GRID, CENTER_Y_GRID)
            end_node = (grid_end_x, grid_end_y)
            
            # Check rápido se o destino é parede
            dest_cost = grid[grid_end_y][grid_end_x]
            if dest_cost >= 999:
                print(f"[DEBUG Walker] AVISO: O destino final é uma PAREDE (Custo {dest_cost})!")
            
            path = astar_search(grid, start_node, end_node)
            
            if not path:
                print("[DEBUG Walker] A* falhou! Retornou caminho VAZIO. Bloqueado?")
                # Imprime o grid para o usuário ver o bloqueio
                # self.print_debug_grid(grid, start_node, end_node) 
                fail_count += 1
                time.sleep(1)
                if fail_count > 3: return False
                continue
                
            print(f"[DEBUG Walker] Caminho encontrado! {len(path)} passos. Próximo nó: {path[1]}")

            # 4. Movimento
            next_step = path[1]
            dx = next_step[0] - start_node[0]
            dy = next_step[1] - start_node[1]
            
            opcode = None
            dir_name = "Unknown"
            
            if dx == 0 and dy == -1:   opcode, dir_name = DIR_NORTH, "Norte"
            elif dx == 1 and dy == 0:  opcode, dir_name = DIR_EAST, "Leste"
            elif dx == 0 and dy == 1:  opcode, dir_name = DIR_SOUTH, "Sul"
            elif dx == -1 and dy == 0: opcode, dir_name = DIR_WEST, "Oeste"
            elif dx == 1 and dy == -1: opcode, dir_name = OP_NE, "Nordeste"
            elif dx == 1 and dy == 1:  opcode, dir_name = OP_SE, "Sudeste"
            elif dx == -1 and dy == 1: opcode, dir_name = OP_SW, "Sudoeste"
            elif dx == -1 and dy == -1: opcode, dir_name = OP_NW, "Noroeste"
            
            if opcode:
                print(f"[DEBUG Walker] Enviando pacote: {dir_name} (0x{opcode:X})")
                packet.walk(self.pm, opcode)
                
                # Espera chegar
                time.sleep(0.1) # Pequeno delay fixo antes de checar
                timeout = 0
                while timeout < 10: 
                    npx, npy, _ = self.get_player_pos()
                    if npx != px or npy != py:
                        print("[DEBUG Walker] Movimento confirmado pelo cliente.")
                        fail_count = 0
                        break
                    time.sleep(0.05)
                    timeout += 1
                
                if timeout >= 10:
                    print("[DEBUG Walker] Timeout: Personagem não saiu do lugar. Lag ou Server Block?")
            else:
                print(f"[DEBUG Walker] Erro lógico: Delta estranho {dx}, {dy}")
                fail_count += 1
                
            if fail_count > 10:
                print("[DEBUG Walker] TRAVADO TOTAL. Abortando.")
                return False