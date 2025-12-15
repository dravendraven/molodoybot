import pymem
import time
import sys
import os

# Garante que conseguimos importar os módulos do projeto
sys.path.append(os.getcwd())

from config import *
from core.memory_map import MemoryMap

# Lista de teste abrangente (caso o config esteja incompleto)
TEST_WATER_IDS = [
    618, 619, 620, 621, 622, # Clássicos
    4608, 4609, 4610, 4611, 4612, 4613, # Tiquanda/News
    4614, 4615, 4616, 4617, 4618, 4619, 
    4620, 4621, 4622, 4623, 4624, 4625,
    4811, 4812,
    4597, 4598, 4599, 4600, 4601, 4602 # Outros
]

def run_test():
    print("========================================")
    print("🛠️  TESTE DE SCAN DE ÁGUA (MEMORY MAP)")
    print("========================================")
    
    # 1. Conexão
    try:
        pm = pymem.Pymem("Tibia.exe")
        base_addr = pm.process_base.lpBaseOfDll
        print(f"✅ Tibia conectado. Base Address: {hex(base_addr)}")
    except Exception as e:
        print(f"❌ Erro ao conectar no Tibia: {e}")
        return

    # 2. Player ID
    try:
        player_id = pm.read_int(base_addr + OFFSET_PLAYER_ID)
        print(f"👤 Player ID lido: {player_id}")
        if player_id == 0:
            print("❌ Player ID é 0. Entre no jogo primeiro!")
            return
    except:
        print("❌ Falha ao ler OFFSET_PLAYER_ID.")
        return

    # 3. Inicializar Mapper
    mapper = MemoryMap(pm, base_addr)
    
    print("\n📥 Lendo Matriz do Mapa...")
    start_time = time.time()
    
    if not mapper.read_full_map(player_id):
        print("❌ mapper.read_full_map() retornou False.")
        return
        
    print(f"✅ Leitura concluída em {(time.time() - start_time)*1000:.2f}ms")
    
    if mapper.center_index == -1:
        print("❌ ERRO CRÍTICO: Jogador não encontrado dentro da matriz de memória!")
        print("   Isso significa que o OFFSET_MAP_POINTER pode estar errado para esta versão")
        print("   ou o ID do player mudou.")
        return
    else:
        print(f"📍 Jogador localizado no índice de memória: {mapper.center_index}")

    # 4. Scan Visual
    print("\n--- VARREDURA 7x5 (Sua tela) ---")
    print("Legenda: [ID] = Chão normal | \033[94m[ID]\033[0m = ÁGUA DETECTADA\n")

    water_count = 0
    
    # Tenta usar a lista do config, senão usa a de teste
    try:
        scan_ids = WATER_IDS
        print(f"ℹ️ Usando lista WATER_IDS do config.py ({len(scan_ids)} IDs)")
    except:
        scan_ids = TEST_WATER_IDS
        print("⚠️ Usando lista de IDs interna de teste.")

    # Desenha o grid
    for dy in range(-5, 6):
        row_display = ""
        for dx in range(-7, 8):
            if dx == 0 and dy == 0:
                row_display += " [ YOU  ] "
                continue
            
            tile = mapper.get_tile(dx, dy)
            if tile:
                top_id = tile.get_top_item()
                
                # É água?
                if top_id in scan_ids:
                    water_count += 1
                    # Tenta pintar de azul (ANSI code)
                    row_display += f" \033[94m[{top_id:^6}]\033[0m "
                else:
                    row_display += f" [{top_id:^6}] "
            else:
                row_display += " [NULL] "
        
        print(f"Y={dy:+2}: {row_display}")

    print("\n========================================")
    print(f"🌊 Total de tiles de ÁGUA encontrados: {water_count}")
    print("========================================")

    if water_count == 0:
        print("\n⚠️ DIAGNÓSTICO: O bot não está vendo água.")
        print("1. Olhe os IDs na grade acima ao redor do [ YOU ].")
        print("2. Veja qual é o ID da água onde você está (ex: tile à frente).")
        print("3. Adicione esse ID na lista WATER_IDS no config.py.")

if __name__ == "__main__":
    run_test()
    input("\nPressione Enter para sair...")