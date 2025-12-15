import pymem
import time
import os
from config import *
from core.memory_map import MemoryMap

def test():
    print("Tentando conectar ao Tibia...")
    try:
        pm = pymem.Pymem("Tibia.exe")
        base_addr = pm.process_base.lpBaseOfDll
        print(f"Conectado! Base Address: {hex(base_addr)}")
    except:
        print("Erro: Tibia.exe não encontrado.")
        return

    # 1. Ler ID do Jogador (Necessário para calibração)
    try:
        player_id = pm.read_int(base_addr + OFFSET_PLAYER_ID)
        print(f"Player ID: {player_id}")
    except:
        print("Erro ao ler Player ID. Verifique offsets.")
        return

    # 2. Iniciar Mapeador
    mapper = MemoryMap(pm, base_addr)

    print("\n--- INICIANDO LEITURA (Ctrl+C para parar) ---")
    while True:
        # Lê o mapa
        success = mapper.read_full_map(player_id)
        
        if success:
            os.system('cls' if os.name == 'nt' else 'clear')
            print(f"Player ID: {player_id} | Calibração Index: {mapper.center_index}")
            
            if mapper.center_index != -1:
                # Mostra o que tem ao redor (Grade 3x3)
                print("\nGrade Local (IDs dos itens no topo):")
                for y in range(-1, 2):
                    row_str = ""
                    for x in range(-1, 2):
                        tile = mapper.get_tile(x, y)
                        if tile:
                            top_id = tile.get_top_item()
                            # Marca o player
                            char = f"{top_id:4}"
                            if x == 0 and y == 0: char = "[YOU ]"
                            row_str += char + " "
                        else:
                            row_str += "???? "
                    print(row_str)
                
                print("\n[LEGENDA]: 99=Criatura/Player, 0=Vazio, Outros=Item ID")
                print("Ande no jogo e veja os IDs mudarem!")
            else:
                print("Procurando jogador na matriz de memória...")
        
        time.sleep(0.5)

if __name__ == "__main__":
    test()