import pymem
import pymem.process
import time
import os

# ==============================================================================
# CONFIGURAÇÕES
# ==============================================================================
PROCESS_NAME = "Tibia.exe" # Verifique no Gerenciador de Tarefas se é esse o nome exato
TARGET_ID_OFFSET = 0x1C681C # O offset que você achou no Cheat Engine

def main():
    os.system('cls')
    print(f"Procurando por {PROCESS_NAME}...")

    try:
        # 1. Conecta no processo do jogo
        pm = pymem.Pymem(PROCESS_NAME)
        print(f"Conectado! PID: {pm.process_id}")

        # 2. Pega o endereço base do Tibia.exe (Module Base Address)
        # Isso é vital, pois o Windows muda o local da memória toda vez que abre o jogo
        base_address = pymem.process.module_from_name(pm.process_handle, PROCESS_NAME).lpBaseOfDll
        print(f"Base Address do Tibia: {hex(base_address)}")

        # 3. Calcula o endereço final do Target ID
        target_id_addr = base_address + TARGET_ID_OFFSET
        print(f"Endereço do Target ID calculado: {hex(target_id_addr)}")
        print("-" * 30)

        print("Monitorando... (Ctrl+C para parar)")
        
        last_status = -1

        while True:
            # 4. LÊ A MEMÓRIA
            # Lê 4 bytes como um Inteiro (int)
            current_target_id = pm.read_int(target_id_addr)

            # Só imprime se o status mudar (pra não spamar o console)
            if current_target_id != last_status:
                if current_target_id == 0:
                    print(f"[STATUS] Parado (Não atacando ninguém)")
                else:
                    print(f"[STATUS] ATACANDO! ID do Alvo: {current_target_id}")
                
                last_status = current_target_id

            time.sleep(0.1)

    except pymem.exception.ProcessNotFound:
        print("Erro: O Tibia não está aberto.")
    except Exception as e:
        print(f"Erro crítico: {e}")

if __name__ == "__main__":
    main()