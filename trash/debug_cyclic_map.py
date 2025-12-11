import pymem
import pymem.process
import struct
import sys

# --- CONFIGURAÇÃO ---
PROCESS_NAME = "Tibia.exe"
OFFSET_MAP_POINTER = 0x1D4C20 
OFFSET_PLAYER_X = 0x1D16F0
OFFSET_PLAYER_Y = 0x1D16EC
OFFSET_PLAYER_Z = 0x1D16E8

# ID do item que está DEBAIXO do seu pé (Ex: 4515 grama, 410 preto)
TARGET_ID = 103

# Estrutura
TILE_SIZE = 172
MAX_X = 18
MAX_Y = 14
MAX_Z = 8

def get_base_addr(pm):
    return pymem.process.module_from_name(pm.process_handle, PROCESS_NAME).lpBaseOfDll

def main():
    print(f"\n🕵️ DETETIVE DE MEMÓRIA (Procurando ID {TARGET_ID})")
    try:
        pm = pymem.Pymem(PROCESS_NAME)
        base = get_base_addr(pm)
        map_ptr = pm.read_int(base + OFFSET_MAP_POINTER)
        px = pm.read_int(base + OFFSET_PLAYER_X)
        py = pm.read_int(base + OFFSET_PLAYER_Y)
        pz = pm.read_int(base + OFFSET_PLAYER_Z)
    except Exception as e:
        print(f"Erro ao ler memória: {e}")
        return

    print(f"📍 Player Global: {px}, {py}, {pz}")
    print(f"🧠 Map Pointer: {hex(map_ptr)}")
    print("-" * 50)

    # Varrer todos os tiles do andar Z=0 (Memória) até Z=7
    # Vamos procurar onde está o TARGET_ID
    
    found = False
    
    # Lendo todo o bloco de memória de uma vez para analisar
    # Tamanho total = 18 * 14 * 8 * 172 = ~346kb
    total_size = MAX_X * MAX_Y * MAX_Z * TILE_SIZE
    try:
        raw_data = pm.read_bytes(map_ptr, total_size)
    except:
        print("Erro ao ler bloco de mapa.")
        return

    print("Varrendo memória...")
    
    for i in range(MAX_X * MAX_Y * MAX_Z):
        offset = i * TILE_SIZE
        if offset + 16 > len(raw_data): break
        
        # Lê Count e Primeiro ID
        count = struct.unpack_from("<I", raw_data, offset)[0]
        id1 = struct.unpack_from("<I", raw_data, offset + 4)[0] # ID do primeiro item
        
        if id1 == TARGET_ID:
            # Achamos um tile com o ID do chão!
            # Agora vamos tentar descobrir qual coordenada (x,y,z) isso representa
            
            # Decodificando índices lineares
            # Supondo Z-Plane Major: i = z * (18*14) + index_2d
            z_guess = i // (MAX_X * MAX_Y)
            rem = i % (MAX_X * MAX_Y)
            
            # Opção A (Row Major): rem = y * 18 + x
            y_a = rem // MAX_X
            x_a = rem % MAX_X
            
            # Opção B (Col Major): rem = x * 14 + y
            x_b = rem // MAX_Y
            y_b = rem % MAX_Y
            
            # Teste de Cíclico
            # O índice X na memória deve ser (PlayerX % 18)
            # O índice Y na memória deve ser (PlayerY % 14)
            # O índice Z na memória deve ser (PlayerZ % 8)
            
            mem_x_target = px % MAX_X
            mem_y_target = py % MAX_Y
            mem_z_target = pz % MAX_Z
            
            print(f"🔎 ENCONTRADO ID {TARGET_ID} no Índice {i} (Offset {offset})")
            print(f"   Possibilidade A -> Z:{z_guess} Y:{y_a} X:{x_a}")
            print(f"   Possibilidade B -> Z:{z_guess} X:{x_b} Y:{y_b}")
            print(f"   --- Comparando com sua posição ---")
            print(f"   Seu Global % Tamanho: Z:{mem_z_target} X:{mem_x_target} Y:{mem_y_target}")
            
            if z_guess == 0: # Geralmente o andar do player é mapeado no 0 ou no Z global % 8
                if x_a == mem_x_target and y_a == mem_y_target:
                    print("\n🎉 DESCOBERTA: A memória usa Row-Major [Z][Y][X]!")
                    print("Fórmula: index = (z * 18 * 14) + (y * 18) + x")
                    print(f"Onde x = GlobalX % 18, y = GlobalY % 14")
                    found = True
                    break
                
                if x_b == mem_x_target and y_b == mem_y_target:
                    print("\n🎉 DESCOBERTA: A memória usa Column-Major [Z][X][Y] (Igual TibiaAPI)!")
                    print("Fórmula: index = (z * 18 * 14) + (x * 14) + y")
                    print(f"Onde x = GlobalX % 18, y = GlobalY % 14")
                    found = True
                    break

    if not found:
        print("\n❌ Não encontrei correspondência exata com a lógica cíclica.")
        print("Tente se mover para outro tile e rodar novamente.")

if __name__ == "__main__":
    main()