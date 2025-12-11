import pymem
import pymem.process
import time
import win32gui 
import win32con
import win32api
import struct
import os

# ==============================================================================
# 1. ENDEREÇO DA FUNÇÃO NOVA (SetAttackedCreature)
# ==============================================================================
# COLOQUE AQUI O ENDEREÇO QUE VOCÊ ACHOU NO DISASSEMBLER PARA ESSA FUNÇÃO
ATTACK_FUNC_ADDR = 0x408080

# ==============================================================================
# 2. CONFIGURAÇÕES
# ==============================================================================
PROCESS_NAME = "Tibia.exe"
MY_PLAYER_NAME = "It is Molodoy"
TARGET_MONSTERS = ["Rotworm", "Troll"]

# Offsets Memória
TARGET_ID_PTR = 0x1C681C 
REL_FIRST_ID = 0x94
STEP_SIZE = 156

OFFSET_ID = 0
OFFSET_NAME = 4
OFFSET_X = 0x24
OFFSET_Y = 0x28
OFFSET_Z = 0x2C
OFFSET_HP = 0x84
OFFSET_VISIBLE = 0x8C

MAX_CREATURES = 250

# ==============================================================================
# 3. FUNÇÃO DE INJEÇÃO (ADAPTADA PARA 2 ARGUMENTOS)
# ==============================================================================
def inject_attack_v2(pm, player_id, target_id):
    """
    Chama Game::playerSetAttackedCreature(playerID, creatureID)
    Lógica Assembly:
      PUSH target_id
      PUSH player_id
      CALL function
      ADD ESP, 8 (Limpeza de pilha, opcional se for stdcall)
      RET
    """
    if ATTACK_FUNC_ADDR == 0:
        print("[ERRO] Configure o ATTACK_FUNC_ADDR!")
        return

    # Aloca memória
    code_addr = pm.allocate(64)
    
    try:
        # 1. PUSH Target ID (Arg 2)
        # Opcode 68 = PUSH Imm32
        asm_push_target = b'\x68' + struct.pack('<I', target_id)
        
        # 2. PUSH Player ID (Arg 1)
        asm_push_player = b'\x68' + struct.pack('<I', player_id)
        
        # 3. CALL Function
        # Offset = Destino - (Origem + TamanhoInstrução)
        # Origem é onde o CALL começa + 5 bytes dele mesmo
        current_pos = code_addr + len(asm_push_target) + len(asm_push_player)
        call_offset = ATTACK_FUNC_ADDR - (current_pos + 5)
        asm_call = b'\xE8' + struct.pack('<i', call_offset)
        
        # 4. Limpeza de Pilha (ADD ESP, 8) -> 0x83 0xC4 0x08
        # (Use isso se o jogo crashar sem isso. Se for stdcall, remova)
        asm_clean = b'\x83\xC4\x08' 
        
        # 5. RET
        asm_ret = b'\xC3'
        
        # Monta o pacote final
        shellcode = asm_push_target + asm_push_player + asm_call + asm_clean + asm_ret

        # Escreve e Executa
        pm.write_bytes(code_addr, shellcode, len(shellcode))
        pm.start_thread(code_addr)
        
        print(f">>> INJEÇÃO ENVIADA: Player {player_id} -> Atacar {target_id}")
        
    except Exception as e:
        print(f"[ERRO INJEÇÃO] {e}")
    finally:
        # Limpa a memória alocada (rápido)
        time.sleep(0.05)
        pm.free(code_addr)

# ==============================================================================
# 4. LEITURA DE DADOS
# ==============================================================================
def get_player_data(pm, list_addr):
    """ Retorna (ID, X, Y, Z) do jogador """
    # O Player costuma ser o primeiro da lista, mas buscamos pelo nome por segurança
    for i in range(30):
        try:
            slot = list_addr + (i * STEP_SIZE)
            c_id = pm.read_int(slot)
            if c_id > 0:
                raw = pm.read_string(slot + OFFSET_NAME, 32)
                name = raw.split('\x00')[0].strip()
                
                if name == MY_PLAYER_NAME:
                    px = pm.read_int(slot + OFFSET_X)
                    py = pm.read_int(slot + OFFSET_Y)
                    pz = pm.read_int(slot + OFFSET_Z)
                    return c_id, px, py, pz
        except: pass
    return 0, 0, 0, 0

# ==============================================================================
# 5. LOOP PRINCIPAL
# ==============================================================================
def main():
    os.system('cls')
    print("=== TIBIA BOT: DUAL ARGUMENT INJECTION ===")
    
    try:
        pm = pymem.Pymem(PROCESS_NAME)
        base = pymem.process.module_from_name(pm.process_handle, PROCESS_NAME).lpBaseOfDll
        
        target_addr = base + TARGET_ID_PTR
        list_start = base + TARGET_ID_PTR + REL_FIRST_ID
        
        print("Bot rodando... (Ctrl+C para parar)")

        while True:
            # 1. Pega MEUS dados (Inclusive ID)
            my_id, my_x, my_y, my_z = get_player_data(pm, list_start)
            
            if my_id == 0:
                time.sleep(1)
                continue

            # 2. Verifica se já estou atacando
            current_target = pm.read_int(target_addr)
            
            # Se não estiver atacando, procura alvo
            if current_target == 0:
                
                for i in range(MAX_CREATURES):
                    slot = list_start + (i * STEP_SIZE)
                    try:
                        c_id = pm.read_int(slot)
                        if c_id > 0:
                            raw = pm.read_string(slot + OFFSET_NAME, 32)
                            name = raw.split('\x00')[0].strip()
                            
                            if name == MY_PLAYER_NAME: continue
                            
                            # Verifica se é alvo
                            is_target = any(t in name for t in TARGET_MONSTERS)
                            
                            if is_target:
                                vis = pm.read_int(slot + OFFSET_VISIBLE)
                                z = pm.read_int(slot + OFFSET_Z)
                                
                                # Visível e no mesmo andar
                                if vis != 0 and z == my_z:
                                    
                                    # Checa distância (1 SQM)
                                    cx = pm.read_int(slot + OFFSET_X)
                                    cy = pm.read_int(slot + OFFSET_Y)
                                    dist = max(abs(my_x - cx), abs(my_y - cy))
                                    
                                    hp = pm.read_int(slot + OFFSET_HP)
                                    
                                    if dist <= 1 and hp > 0:
                                        print(f"Atacando {name} (ID: {c_id})")
                                        
                                        # >>> CHAMA A NOVA FUNÇÃO DE INJEÇÃO <<<
                                        inject_attack_v2(pm, my_id, c_id)
                                        
                                        time.sleep(0.5)
                                        break
                    except: continue

            time.sleep(0.1)

    except Exception as e:
        print(f"Erro: {e}")

if __name__ == "__main__":
    main()