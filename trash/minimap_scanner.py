import pymem
import struct

def probe_minimap_colors():
    try:
        pm = pymem.Pymem("Tibia.exe")
    except:
        print("Tibia não encontrado.")
        return

    # Seus endereços EXATOS
    start_addr = 0x1967F8
    end_addr   = 0x198E08
    buffer_size = end_addr - start_addr # 9744 bytes
    
    # Hipótese de Largura (Tentativa e Erro)
    # Se 9744 bytes / 106 de largura = ~91.9 linhas.
    # Vamos assumir largura de memória = 106
    MAP_WIDTH = 106
    
    # O Centro (Jogador) deve estar no meio do buffer
    center_index = buffer_size // 2 
    
    print(f"Lendo Buffer de {hex(start_addr)} (+{buffer_size} bytes)")
    print(f"Assumindo Largura: {MAP_WIDTH} | Centro Index: {center_index}")

    try:
        # Lendo o buffer
        buffer = pm.read_bytes(start_addr, buffer_size)
        
        # Função auxiliar para pegar valor
        def get_val(idx):
            if 0 <= idx < len(buffer):
                val = buffer[idx]
                return f"{val} (0x{val:02X})"
            return "FORA"

        # Coletando vizinhos
        val_center = get_val(center_index)
        val_north  = get_val(center_index - MAP_WIDTH)
        val_south  = get_val(center_index + MAP_WIDTH)
        val_east   = get_val(center_index + 1)
        val_west   = get_val(center_index - 1)
        
        print("\n--- SONDA DE TILES ---")
        print(f"CENTRO (Pé do Char): {val_center}")
        print(f"NORTE  (dy = -1):    {val_north}")
        print(f"SUL    (dy = +1):    {val_south}")
        print(f"LESTE  (dx = +1):    {val_east}")
        print(f"OESTE  (dx = -1):    {val_west}")
        
        print("\n--- Análise ---")
        print("Se você está na GRAMA, o valor do CENTRO é o código da Grama.")
        print("Se tem ÁGUA ao Norte, o valor NORTE é o código da Água.")
        
        # Verificação do padrão '0xCC' (Grama?)
        if "CC" in val_center:
            print(">> O valor 0xCC (204) coincide com o 'Green' da Grama.")

    except Exception as e:
        print(f"Erro: {e}")

probe_minimap_colors()