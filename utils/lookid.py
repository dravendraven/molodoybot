import pymem
import pymem.process
import time

def main():
    print("--- Visualizador de Look ID (Com Limpeza) ---")
    try:
        pm = pymem.Pymem("Tibia.exe")
        base = pm.process_base.lpBaseOfDll
        
        addr_look_id = base + 0x31C63C 
        addr_status_msg = base + 0x31DBE0 
        addr_status_timer = base + 0x31DBDC

        last_id = 0

        while True:
            current_id = pm.read_int(addr_look_id)

            if current_id != last_id and current_id > 0:
                
                # --- PASSO EXTRA: LIMPEZA ---
                # Cria 100 bytes vazios (nulos)
                # b'\x00' é o byte que diz "fim de texto" para o computador
                empty_buffer = b'\x00' * 100 
                
                # Escreve esses nulos no endereço da mensagem para apagar tudo que tinha antes
                pm.write_bytes(addr_status_msg, empty_buffer, len(empty_buffer))
                
                # --- AGORA ESCREVE O NOVO ---
                text_to_show = f"ID: {current_id}"
                pm.write_string(addr_status_msg, text_to_show)
                
                # Define o tempo da mensagem
                pm.write_int(addr_status_timer, 50)
                
                print(f"Limpo e Atualizado: {current_id}")
                last_id = current_id

            time.sleep(0.1)

    except pymem.exception.ProcessNotFound:
        print("Tibia.exe não encontrado!")
    except Exception as e:
        print(f"Erro: {e}")

if __name__ == "__main__":
    main()