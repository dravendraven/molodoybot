import pymem
import time
import packet

def main():
    print("--- TESTE DE PACOTES (PACKET INJECTION) ---")
    try:
        pm = pymem.Pymem("Tibia.exe")
        print("Conectado ao Tibia.")
    except:
        print("Erro: Tibia não encontrado.")
        return

    print("\n1. Teste de Rotação (Dancinha)...")
    print("Olhe para o seu char!")
    
    directions = [packet.OP_TURN_N, packet.OP_TURN_E, packet.OP_TURN_S, packet.OP_TURN_W]
    
    for _ in range(2): # 2 Voltas
        for op in directions:
            packet.turn(pm, op)
            time.sleep(0.5)
            
    print("✅ Teste de Rotação concluído.")
    
    print("\n2. Teste de Ataque (Opcional)")
    tid_str = input("Digite o ID de uma criatura para atacar (ou ENTER para pular): ")
    
    if tid_str:
        try:
            tid = int(tid_str)
            print(f"Enviando ataque ao ID {tid}...")
            packet.attack(pm, tid)
            print("Pacote enviado! Verifique se o quadrado vermelho apareceu.")
        except:
            print("ID inválido.")

if __name__ == "__main__":
    main()