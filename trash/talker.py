import pymem
import pymem.process
import struct
import time

# ==============================================================================
# CONFIGURAÇÕES
# ==============================================================================
PROCESS_NAME = "Tibia.exe"

# Endereço extraído do seu arquivo const.h
SAY_FUNC_ADDR = 0x4067C0 

# Mensagem que você quer falar
MESSAGE_TEXT = "Ola do Python!"
SPEAK_MODE = 1  # 1 = Say (Falar normal amarelo)

def inject_say(pm, text):
    """
    Injeta código para chamar a função interna de 'Say' do Tibia.
    """
    try:
        # 1. Alocar memória para a String (Texto)
        # Precisamos converter a string para bytes e adicionar um byte nulo final (\x00)
        text_bytes = text.encode('latin-1') + b'\x00'
        text_addr = pm.allocate(len(text_bytes))
        pm.write_bytes(text_addr, text_bytes, len(text_bytes))
        print(f"[DEBUG] Texto escrito em: {hex(text_addr)}")

        # 2. Alocar memória para o Código Assembly (Code Cave)
        code_addr = pm.allocate(64) # 64 bytes é mais que suficiente
        print(f"[DEBUG] Code Cave alocada em: {hex(code_addr)}")

        # 3. Montar o Código Assembly (OpCodes)
        
        # PUSH String Address (0x68 + 4 bytes do endereço)
        # Empilha o endereço onde escrevemos o texto
        asm_push_string = b'\x68' + struct.pack('<I', text_addr)

        # PUSH Mode (0x6A + 1 byte do modo)
        # Empilha o número 1 (Speak Say)
        asm_push_mode = b'\x6A' + struct.pack('<B', SPEAK_MODE)

        # CALL Function (0xE8 + 4 bytes do offset relativo)
        # A instrução CALL tem 5 bytes. O salto é calculado a partir do final da instrução.
        # Origem = code_addr + tamanho_dos_pushs
        current_pos = code_addr + len(asm_push_string) + len(asm_push_mode)
        relative_offset = SAY_FUNC_ADDR - (current_pos + 5)
        asm_call = b'\xE8' + struct.pack('<i', relative_offset)

        # ADD ESP, 8 (0x83 0xC4 0x08) - Limpeza de Pilha (Cdecl)
        # Se o jogo crashar, tente remover esta linha (pode ser StdCall)
        asm_cleanup = b'\x83\xC4\x08'

        # RET (0xC3) - Retorna
        asm_ret = b'\xC3'

        # Junta tudo
        shellcode = asm_push_string + asm_push_mode + asm_call + asm_cleanup + asm_ret

        # 4. Escrever o código na memória
        pm.write_bytes(code_addr, shellcode, len(shellcode))

        # 5. Executar!
        print(f"[EXEC] Injetando Thread...")
        pm.start_thread(code_addr)
        
        # 6. Limpeza (Opcional, mas recomendada para não vazar memória)
        # Espera um pouco para garantir que o código rodou antes de deletar
        time.sleep(0.1)
        pm.free(text_addr)
        pm.free(code_addr)
        print("[SUCESSO] Mensagem enviada!")

    except Exception as e:
        print(f"[ERRO] Falha na injeção: {e}")

def main():
    print("=== TIBIA INJECTOR: AUTO SAY ===")
    try:
        pm = pymem.Pymem(PROCESS_NAME)
        print(f"Conectado ao Tibia (PID: {pm.process_id})")
        
        # Envia a mensagem
        inject_say(pm, MESSAGE_TEXT)
        
    except Exception as e:
        print(f"Erro: {e}")

if __name__ == "__main__":
    main()