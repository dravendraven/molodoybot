import pymem
import time
import os
import struct

# Endereço encontrado pelo seu scan anterior
# ATENÇÃO: Se você fechou o Tibia, esse endereço mudou e precisará rodar o Calibrador de novo.
ADDRESS_BASE = 0x5dbf38b2 

PROCESS_NAME = "Tibia.exe" # Ajuste se necessário (ex: "tutorial-client.exe")

def main():
    try:
        pm = pymem.Pymem(PROCESS_NAME)
        print(f"Conectado! Lendo Tile em: {hex(ADDRESS_BASE)}")
        print("Ande pelo mapa e observe qual ID muda conforme o chão.\n")

        while True:
            # Vamos ler os primeiros 32 bytes desse Tile para ver o que tem dentro
            # O ID 99 (Player) estava no início, o chão deve estar logo depois (ou antes)
            buffer = pm.read_bytes(ADDRESS_BASE, 32)
            
            # Desempacota em 16 inteiros curtos (Shorts de 2 bytes) - Padrão de IDs do Tibia
            # '<' = Little Endian, '16H' = 16 Unsigned Shorts
            values = struct.unpack('<16H', buffer)
            
            output = ""
            found_99 = False
            
            for i, val in enumerate(values):
                # Destaque visual
                if val == 99:
                    display = f"[\033[91mPLAYER:99\033[0m]" # Vermelho para o Player
                    found_99 = True
                elif val == 0:
                    display = "   .   " # Ignora zeros
                elif val > 60000:
                    display = "  ???  " # Ignora lixo
                else:
                    # IDs prováveis de Chão ou Itens ficam aqui
                    display = f"[{val:^5}]" 

                output += f"{i*2:02d}:{display}  "
                
                # Quebra de linha a cada 4 valores para facilitar leitura
                if (i + 1) % 4 == 0:
                    output += "\n"

            os.system('cls' if os.name == 'nt' else 'clear')
            print(f"--- INSPETOR DE TILE ({hex(ADDRESS_BASE)}) ---")
            print(output)
            print("\n------------------------------------------------")
            if found_99:
                print(">>> PLAYER (99) DETECTADO! Estamos no lugar certo.")
                print(">>> O ID do chão é provavelmente um dos outros números acima.")
            else:
                print(">>> ALERTA: ID 99 sumiu. Você saiu do Tile (0,0) relativo à memória?")
                print(">>> Se o 99 não voltar quando você para, o endereço Base mudou.")
            
            time.sleep(0.2)

    except Exception as e:
        print(f"Erro: {e}")

if __name__ == "__main__":
    main()