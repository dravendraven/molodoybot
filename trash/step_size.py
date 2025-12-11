import pymem
import pymem.process
import struct

# ==============================================================================
# FERRAMENTA DE MAPEAMENTO DE BATTLE LIST
# ==============================================================================

PROCESS_NAME = "Tibia.exe"
# Coloque aqui o OFFSET que você achou no Cheat Engine (o verde)
# No seu print é 1C85F0.
KNOWN_CREATURE_OFFSET = 0x1C85F0 

def main():
    try:
        pm = pymem.Pymem(PROCESS_NAME)
        base_address = pymem.process.module_from_name(pm.process_handle, PROCESS_NAME).lpBaseOfDll
        print(f"Conectado! Base: {hex(base_address)}")
        
        # Endereço absoluto na RAM onde está o Troll que você achou
        known_addr = base_address + KNOWN_CREATURE_OFFSET
        print(f"Analisando memória ao redor de: {hex(known_addr)}")
        
        # Vamos ler um bloco grande de memória ao redor desse endereço (4000 bytes)
        # Para tentar achar padrões de texto (Nomes de criaturas)
        
        # Lendo 1000 bytes antes e 3000 depois
        start_read = known_addr - 1000
        buffer = pm.read_bytes(start_read, 4000)
        
        print("\n--- VARREDURA DE PADRÕES ---")
        print("Procurando nomes 'Troll' ou 'Bug' para calcular distância...")
        
        # Encontra todas as ocorrências da string "Troll" ou strings comuns
        # Nota: O nome geralmente está num offset fixo depois do ID.
        # Vamos procurar onde os nomes começam.
        
        positions = []
        # Procura byte a byte por strings legíveis
        for i in range(len(buffer) - 10):
            # Se achar 'T' 'r' 'o' 'l' 'l' (Bytes: 54 72 6F 6C 6C)
            if buffer[i] == 0x54 and buffer[i+1] == 0x72 and buffer[i+2] == 0x6F:
                rel_pos = i - 1000 # Posição relativa ao endereço conhecido
                print(f"Nome encontrado no offset relativo: {rel_pos}")
                positions.append(rel_pos)

        if len(positions) >= 2:
            diff = positions[1] - positions[0]
            print(f"\n[DESCOBERTA] Distância provável entre monstros (STEP SIZE): {diff} bytes")
            print(f"Hex: {hex(diff)}")
            
            # Tentando achar o Battle Start
            # Se o known_addr for, por exemplo, o slot 5, o start é: known_addr - (5 * diff)
            # Como não sabemos qual slot é, vamos chutar baseado no alinhamento
            
            # Geralmente o ID fica uns 4 a 8 bytes ANTES do nome.
            # Vamos assumir que a estrutura começa perto de onde achou o ID.
            
            print("\n[DICA PARA CHEAT ENGINE]")
            print(f"1. Volte no Memory Viewer.")
            print(f"2. Vá para o endereço {hex(known_addr)}.")
            print(f"3. O próximo monstro deve estar em {hex(known_addr + diff)}.")
            print(f"4. O monstro anterior deve estar em {hex(known_addr - diff)}.")
            
        else:
            print("\nNão encontrei monstros suficientes perto desse endereço para calcular a distância.")
            print("Tente ter 2 ou 3 Trolls na tela e rode de novo.")

    except Exception as e:
        print(f"Erro: {e}")

if __name__ == "__main__":
    main()