import pymem
import pymem.process
import struct
import sys

# --- CONFIGURAÇÃO ---
PROCESS_NAME = "Tibia.exe"

# Configure aqui o que você está pisando AGORA:
# Exemplo: Grama (4515) vazia = Count 1, ID 4515
# Exemplo: Grama (4515) + Sheep Morta (4086) = Count 2, ID 4515
CURRENT_TILE_COUNT = 4    # Quantas coisas tem no seu pé (Chão + Itens)?
CURRENT_GROUND_ID = 4518   # Qual o ID do chão? (4515 = Grama)

def main():
    print("🕵️ SCANNER DE ASSINATURA DE MAPA")
    print("---------------------------------")
    print(f"Procurando tile com: Count={CURRENT_TILE_COUNT}, GroundID={CURRENT_GROUND_ID}")
    
    try:
        pm = pymem.Pymem(PROCESS_NAME)
    except:
        print("Tibia não encontrado.")
        return

    # Cria a assinatura em bytes (Little Endian)
    # Estrutura: [Count (4b)] [GroundID (4b)] [Data1 (4b)] [Data2 (4b)]
    # Procuramos apenas Count + GroundID para garantir
    signature = struct.pack("<II", CURRENT_TILE_COUNT, CURRENT_GROUND_ID)
    
    print(f"Assinatura Hex: {signature.hex().upper()}")
    print("Varrendo memória (pode levar alguns segundos)...")

    # Varre a memória do processo
    results = pm.pattern_scan_all(signature, return_multiple=True)
    
    if not results:
        print("❌ Nenhuma ocorrência encontrada. Verifique o ID do chão e o Count.")
        return

    print(f"✅ Encontrados {len(results)} candidatos.")
    print("-" * 50)
    
    # Filtra os resultados para achar o que parece ser o Player
    # O Player geralmente está no centro da estrutura de memória do mapa.
    # Mas primeiro, vamos ver onde esses endereços estão.
    
    for addr in results:
        # Lê um pouco mais para ver se faz sentido (ex: não deve ser código executável)
        try:
            data = pm.read_bytes(addr, 32)
            # Decodifica para mostrar
            vals = struct.unpack("<IIII", data[:16])
            print(f"📍 Endereço: {hex(addr)} | Dados: {vals} (Count, ID, Data1, Data2)")
            
            # Dica: O endereço do mapa costuma ser algo alocado na Heap
            # Vamos tentar deduzir o inicio do mapa se assumirmos que este é o tile central (8, 6)
            # Index central = (6 * 18) + 8 = 116 (Se for Linear)
            # MapStart = Addr - (116 * 172)
            
            suspect_map_start = addr - (116 * 172)
            print(f"   ↳ Se este for o player (8,6), o Mapa começa em: {hex(suspect_map_start)}")
            
        except:
            pass

    print("-" * 50)
    print("Tente jogar um item no chão para mudar o Count para 2 e rode de novo.")
    print("O endereço que persistir (com o offset ajustado) é o seu Mapa Real.")

if __name__ == "__main__":
    main()