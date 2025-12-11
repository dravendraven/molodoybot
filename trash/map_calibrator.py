import pymem
import time
import os

# === CONFIGURAÇÃO ENCONTRADA PELO CALIBRADOR ===
# Se o jogo fechar e abrir, o ADDRESS_BASE muda se não for ponteiro estático.
# Como você acabou de rodar o scan, use o valor que ele deu.
ADDRESS_BASE = 0x5dbf38b2  
TILE_SIZE = 156            # Tamanho da struct encontrado
MAP_WIDTH_MEMORY = 18      # Vamos tentar o padrão de visualização (geralmente 14 ou 18)

# Nome do processo (ajuste se necessário)
PROCESS_NAME = "Tibia.exe" # ou "tutorial-client.exe", verifique no Gerenciador de Tarefas

def print_grid(pm):
    os.system('cls' if os.name == 'nt' else 'clear')
    print(f"--- LENDO MAPA (Base: {hex(ADDRESS_BASE)}) ---")
    print("Tentando desenhar uma grade 3x3 ao redor do endereço base...\n")

    # Vamos tentar ler um quadrado 3x3 com o Player no centro (0,0)
    # A lógica de memória geralmente é linear. 
    # Se o scanner disse que Offset Y é 1560 e Offset X é 156:
    # Significa que para descer 1 linha, pulamos 10 tiles (1560 / 156 = 10).
    # Vamos testar com a largura de 10 que o scanner sugeriu primeiro.
    
    MEMORY_WIDTH = 10 # Sugerido pelo scanner
    
    grid_visual = []

    for y in range(-1, 2): # De -1 (cima) até 1 (baixo)
        row_str = ""
        for x in range(-1, 2): # De -1 (esquerda) até 1 (direita)
            
            # Cálculo do endereço linear
            # Endereço = Base + (Y * Largura_Memoria * Tamanho_Tile) + (X * Tamanho_Tile)
            offset_total = (y * MEMORY_WIDTH * TILE_SIZE) + (x * TILE_SIZE)
            final_addr = ADDRESS_BASE + offset_total
            
            try:
                # Lendo o ID (assumindo que é os primeiros 2 ou 4 bytes da struct)
                # Como vc viu 99 (player), pode ser que tenhamos que somar algo para achar o chão
                # Mas vamos ler o que tem lá primeiro.
                val = pm.read_int(final_addr)
                
                # Formatação bonita
                if x == 0 and y == 0:
                    row_str += f"[{val:^5}]" # Centro (Você)
                else:
                    row_str += f" {val:^5} "
            except Exception as e:
                row_str += " ???  "
        
        grid_visual.append(row_str)

    print("\n".join(grid_visual))
    print("\nLegenda: [Centro] é onde o scanner achou o ID 99.")
    print("Mexa o char. Se os números mudarem coerentemente, BINGO.")

try:
    pm = pymem.Pymem(PROCESS_NAME)
    print(f"Conectado ao {PROCESS_NAME}")
    
    while True:
        print_grid(pm)
        time.sleep(0.5)

except Exception as e:
    print(f"Erro: {e}")
    print("Verifique se o nome do processo está certo e se o jogo está aberto.")