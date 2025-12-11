import time

# Definições de Estado do Tile
TILE_UNKNOWN = 0
TILE_CLEAR   = 1 # Livre (Andável)
TILE_STATIC  = 2 # Bloqueio Fixo (Parede, Pedra, Árvore) - Nunca expira
TILE_TEMP    = 3 # Bloqueio Temporário (Player, Monstro, Magic Wall) - Expira

# Tempo que um bloqueio temporário (ex: player) fica na memória antes de tentarmos de novo
TEMP_BLOCK_DURATION = 2.0 # segundos

class GridMap:
    def __init__(self):
        # Dicionário: Chave=(x,y,z), Valor={status, timestamp}
        self.grid = {} 

    def mark_tile(self, x, y, z, status):
        """Atualiza o estado de um tile no mapa."""
        self.grid[(x, y, z)] = {
            'status': status,
            'time': time.time()
        }
        # Debug visual no console
        status_name = ["?", "LIVRE", "PAREDE", "TEMP"][status]
        # print(f"[GRID] Tile {x},{y} marcado como: {status_name}")

    def is_blocked(self, x, y, z):
        """
        Retorna True se o tile estiver bloqueado (Fixo ou Temp válido).
        """
        if (x, y, z) not in self.grid:
            return False # Se não conhecemos, assumimos que dá pra andar (tentativa e erro)
            
        tile = self.grid[(x, y, z)]
        status = tile['status']
        
        # Se for parede, está sempre bloqueado
        if status == TILE_STATIC:
            return True
            
        # Se for temporário, verifica se já expirou
        if status == TILE_TEMP:
            if time.time() - tile['time'] < TEMP_BLOCK_DURATION:
                return True # Ainda bloqueado
            else:
                # Expirou! Remove do grid para testar de novo
                del self.grid[(x, y, z)]
                return False
                
        return False # TILE_CLEAR
    
    def clear(self):
        self.grid = {}