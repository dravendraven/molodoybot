import pymem
import struct
import time
import os

# ==============================================================================
# ENDEREÇOS (Baseado no seu const.h e structures.h)
# ==============================================================================
MAP_POINTER_ADDR = 0x005D4C20 
PLAYER_X_ADDR    = 0x005D16F0
PLAYER_Y_ADDR    = 0x005D16EC
PLAYER_Z_ADDR    = 0x005D16E8

# CONSTANTES DE GEOMETRIA DA MEMÓRIA
MAP_WIDTH   = 18
MAP_HEIGHT  = 14
SIZEOF_TILE = 172
FLOOR_SIZE  = MAP_WIDTH * MAP_HEIGHT * SIZEOF_TILE # 43.344 bytes

# CONSTANTES DE POSICIONAMENTO
# O Tibia centraliza o personagem nestes índices da matriz 18x14
CENTER_X_GRID = 9
CENTER_Y_GRID = 5

class MapInspector:
    def __init__(self, process_name="Tibia.exe"):
        try:
            self.pm = pymem.Pymem(process_name)
            self.base_map = self.pm.read_int(MAP_POINTER_ADDR)
            print(f"[MapInspector] Conectado! Map Pointer: {hex(self.base_map)}")
        except Exception as e:
            print(f"[Erro] Não foi possível conectar ao Tibia: {e}")
            exit()

    def get_player_pos(self):
        """Retorna (x, y, z) do jogador."""
        try:
            x = self.pm.read_int(PLAYER_X_ADDR)
            y = self.pm.read_int(PLAYER_Y_ADDR)
            z = self.pm.read_int(PLAYER_Z_ADDR)
            return x, y, z
        except:
            return 0, 0, 0

    def _read_tile_id_at_addr(self, addr):
        """Lê o ID do primeiro item (chão) no endereço de memória dado."""
        try:
            # Lê 8 bytes: Amount (4b) + Primeiro ID (4b)
            buff = self.pm.read_bytes(addr, 8)
            amount = struct.unpack_from('<I', buff, 0)[0]
            
            if amount > 0:
                # O primeiro objeto (Offset 4) é geralmente o chão ou item do topo
                tid = struct.unpack_from('<I', buff, 4)[0]
                return tid, amount
            else:
                return 0, 0 # Tile vazio
        except:
            return -1, 0 # Erro de leitura

    def get_tile_from_memory_grid(self, layer, grid_x, grid_y):
        """
        Acessa a matriz bruta tiles[layer][grid_y][grid_x]
        """
        # Proteção de bordas da memória
        if not (0 <= grid_x < MAP_WIDTH and 0 <= grid_y < MAP_HEIGHT):
            return None, 0

        # FÓRMULA CALCULADA NO ÚLTIMO TESTE:
        # Offset = (Layer * BlockSize) + (Row * Width + Col) * TileSize
        offset = (layer * FLOOR_SIZE) + ((grid_y * MAP_WIDTH) + grid_x) * SIZEOF_TILE
        
        final_addr = self.base_map + offset
        return self._read_tile_id_at_addr(final_addr)

    def get_tile_relative(self, dx, dy):
        """
        Pega o tile relativo ao player.
        dx: -1 (Oeste), +1 (Leste)
        dy: -1 (Norte), +1 (Sul)
        """
        _, _, pz = self.get_player_pos()
        
        # Conversão Z -> Layer (Confirmado no seu teste: Z=8 é Layer 2. Logo Layer = Z - 6)
        layer = pz - 6 
        if layer < 0: layer = 0 # Safety clamp

        # O Player sempre está no [6][8] da grid
        target_grid_x = CENTER_X_GRID + dx
        target_grid_y = CENTER_Y_GRID + dy
        
        return self.get_tile_from_memory_grid(layer, target_grid_x, target_grid_y)

    def get_tile_global(self, gx, gy, gz):
        """
        Tenta pegar um tile dada a coordenada global (Ex: 32000, 32000, 7).
        Só funciona se a coordenada estiver dentro da tela/memória carregada.
        """
        px, py, pz = self.get_player_pos()
        
        # Verifica se o Z pedido é o mesmo do player (ou dentro da memória carregada)
        if gz != pz:
            return None, "Z Diferente" # Simplificação: focar no andar atual

        # Calcula a distância
        dx = gx - px
        dy = gy - py
        
        return self.get_tile_relative(dx, dy)

# ==============================================================================
# MODO DE TESTE INTERATIVO
# ==============================================================================
def run_live_test():
    inspector = MapInspector()
    
    print("\n--- INICIANDO TESTE DE PRECISÃO ---")
    print("Ande com o personagem e compare os valores.\n")
    
    last_pos = (0,0,0)

    try:
        while True:
            px, py, pz = inspector.get_player_pos()
            
            # Só atualiza o print se mudou de posição ou a cada 1s
            # (Aqui atualizo sempre para ver realtime)
            
            os.system('cls' if os.name == 'nt' else 'clear')
            print(f"📍 Posição Global: {px}, {py}, {pz}")
            print("-" * 30)

            # 1. Pega os vizinhos usando a lógica Relativa
            #    [N]
            # [W][C][E]
            #    [S]
            
            t_center, _ = inspector.get_tile_relative(0, 0)
            t_north, _  = inspector.get_tile_relative(0, -1)
            t_south, _  = inspector.get_tile_relative(0, 1)
            t_east, _   = inspector.get_tile_relative(1, 0)
            t_west, _   = inspector.get_tile_relative(-1, 0)

            print(f"      [{t_north:4}]")
            print(f"[{t_west:4}][{t_center:4}][{t_east:4}]")
            print(f"      [{t_south:4}]")
            
            print("-" * 30)
            print("Teste de Coordenada Global (Ex: Tile a direita):")
            # Vamos testar pedindo o tile global EXATO da direita
            target_x = px + 1
            tid_global, _ = inspector.get_tile_global(target_x, py, pz)
            
            match = "✅ OK" if tid_global == t_east else "❌ ERRO"
            print(f"Global({target_x}, {py}) = {tid_global} -> {match}")
            
            time.sleep(0.2)
            
    except KeyboardInterrupt:
        print("Teste encerrado.")

if __name__ == "__main__":
    run_live_test()