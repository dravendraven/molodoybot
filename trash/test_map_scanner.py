import pymem
import pymem.process
import struct
import time
import os
import sys

# Tenta importar as configurações existentes
try:
    from config import PROCESS_NAME, OFFSET_MAP_POINTER
    import corpses
    print("✅ Config e Corpses DB carregados com sucesso.")
except ImportError as e:
    print(f"❌ Erro ao importar arquivos: {e}")
    print("Certifique-se de que config.py e corpses.py estão na mesma pasta.")
    sys.exit()

# ==============================================================================
# CONFIGURAÇÕES DE MEMÓRIA (Estrutura do Tibia 7.x)
# ==============================================================================
# Cada Tile ocupa 172 bytes na memória:
# - 4 bytes: Count (Quantidade de objetos na pilha)
# - 14 * 12 bytes: Array de Objetos (ID + Data + DataEx)
TILE_SIZE = 172 

# Dimensões da Matriz em Memória (O que o cliente vê)
MAX_X = 18
MAX_Y = 14
MAX_Z = 8 # (Geralmente o cliente carrega 8 andares, mas focamos no atual)

# O Player sempre está no centro dessa matriz local
CENTER_X = 8
CENTER_Y = 6

def get_map_pointer(pm, base_addr):
    """Pega o endereço dinâmico onde começa a matriz do mapa."""
    try:
        return pm.read_int(base_addr + OFFSET_MAP_POINTER)
    except:
        return 0

def read_tile(pm, map_start_addr, relative_x, relative_y):
    """
    Lê um tile baseado na posição relativa ao player (dx, dy).
    dx: -1 (Oeste) a +1 (Leste)
    dy: -1 (Norte) a +1 (Sul)
    """
    # 1. Converter coordenada relativa para índice da matriz de memória
    mem_x = CENTER_X + relative_x
    mem_y = CENTER_Y + relative_y
    
    # Validação de bordass
    if not (0 <= mem_x < MAX_X and 0 <= mem_y < MAX_Y):
        return None, 0

    # 2. Calcular o endereço exato desse Tile
    # Fórmula linear: (Row * Width + Col) * Size
    # Assumindo que Z=0 é o andar atual visível (Padrão em muitos clientes dessa versão)
    tile_index = (mem_y * MAX_X) + mem_x
    tile_addr = map_start_addr + (tile_index * TILE_SIZE)
    
    try:
        # Lê o bloco bruto de dados do tile
        tile_data = pm.read_bytes(tile_addr, TILE_SIZE)
        
        # O primeiro Int (4 bytes) é a quantidade de itens no tile (Count)
        # down_count (itens no chão?) ou total_count. 
        # Na estrutura 7.72, geralmente o primeiro DWORD é o count.
        tile_count = struct.unpack_from("<I", tile_data, 0)[0]
        
        items = []
        # Lê até 14 objetos (limite da estrutura)
        # Começa do offset 4 (pula o count)
        for i in range(14):
            offset = 4 + (i * 12) # 12 bytes por objeto
            
            # id, data1, data2
            item_id, data1, data2 = struct.unpack_from("<III", tile_data, offset)
            
            if item_id > 0: # ID 0 costuma ser vazio (ou 99 em alguns casos)
                items.append({
                    "stack_pos": i,
                    "id": item_id,
                    "data": data1
                })
            else:
                # Se achou ID 0, acabou a pilha deste tile
                break
                
        return items, tile_count

    except Exception as e:
        print(f"Erro ao ler tile {relative_x},{relative_y}: {e}")
        return [], 0

def main():
    print("--- INICIANDO TESTE DE LEITURA DE MAPA ---")
    print("1. Abra o Tibia e logue no personagem.")
    print("2. Fique perto de alguns itens e corpos.")
    print("3. Aguardando processo...")

    pm = None
    while not pm:
        try:
            pm = pymem.Pymem(PROCESS_NAME)
            base_addr = pymem.process.module_from_name(pm.process_handle, PROCESS_NAME).lpBaseOfDll
            print(f"✅ Processo encontrado! Base Address: {hex(base_addr)}")
        except:
            time.sleep(1)

    print("\n🔍 LEITURA EM TEMPO REAL (Pressione Ctrl+C para parar)")
    print("Mova seu personagem para ver os dados mudarem.\n")

    try:
        while True:
            map_addr = get_map_pointer(pm, base_addr)
            if map_addr == 0:
                print("❌ Ponteiro de mapa inválido (Logue no char).")
                time.sleep(1)
                continue

            # Limpa o console (opcional, pode comentar se piscar muito)
            os.system('cls' if os.name == 'nt' else 'clear')
            print(f"📍 Map Pointer: {hex(map_addr)}")
            print("="*60)

            # Escaneia 3x3 ao redor do player
            # dy: -1 (Norte), 0 (Centro), 1 (Sul)
            # dx: -1 (Oeste), 0 (Centro), 1 (Leste)
            
            found_corpses = []

            for dy in range(-1, 2):
                row_str = ""
                for dx in range(-1, 2):
                    items, count = read_tile(pm, map_addr, dx, dy)
                    
                    # Formatação visual simples
                    if dx == 0 and dy == 0:
                        cell_desc = "[PLAYER]"
                    else:
                        top_item = items[-1]['id'] if items else 0
                        cell_desc = f"Top: {top_item}"
                    
                    row_str += f"{cell_desc:^15} |"

                    # Análise detalhada
                    for item in items:
                        # Verifica se é corpo
                        corpse_name = "N/A"
                        # Procura reverso no dicionário de corpses (ID -> Nome)
                        for name, cid in corpses.CORPSE_IDS.items():
                            if cid == item['id']:
                                corpse_name = name
                                found_corpses.append(f"💀 Em ({dx}, {dy}) Stack {item['stack_pos']}: {name} (ID {item['id']})")
                                break
                        
                print(row_str)
                print("-" * 50)

            print("\n📋 DETALHES ENCONTRADOS:")
            if found_corpses:
                for fc in found_corpses:
                    print(fc)
            else:
                print("Nenhum corpo identificado ao redor.")

            print("\n(Ctrl+C para encerrar)")
            time.sleep(0.5)

    except KeyboardInterrupt:
        print("\n🛑 Teste encerrado.")

if __name__ == "__main__":
    main()