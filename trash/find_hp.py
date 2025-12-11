import pymem
import pymem.process

# ==============================================================================
# SEUS ENDEREÇOS
# ==============================================================================
PROCESS_NAME = "Tibia.exe"
BATTLE_LIST_START = 0x1C8248 # O endereço inicial que calculamos antes
STEP_SIZE = 156              # O tamanho que achamos

def main():
    pm = pymem.Pymem(PROCESS_NAME)
    base_address = pymem.process.module_from_name(pm.process_handle, PROCESS_NAME).lpBaseOfDll
    
    # Endereço do primeiro slot
    slot_addr = base_address + BATTLE_LIST_START
    
    print(f"Lendo estrutura do Slot 0 em: {hex(slot_addr)}")
    print("Procurando pelo valor '100' (Vida Cheia)...")
    print("-" * 30)
    
    # Vamos ler byte a byte, de 4 em 4, para achar Inteiros
    for offset in range(0, STEP_SIZE, 4):
        try:
            val = pm.read_int(slot_addr + offset)
            
            # Se acharmos 100, é um forte candidato a ser o HP
            if val == 100:
                print(f"[CANDIDATO] Offset: {offset} (Hex: {hex(offset)}) | Valor: {val} <--- PROVÁVEL HP")
            
            # Imprime outros valores para referência (ID, etc)
            elif val > 1000000: 
                print(f"Offset: {offset} (Hex: {hex(offset)}) | Valor: {val} (Provável ID)")
            
        except:
            pass

if __name__ == "__main__":
    main()