import pymem
import time
import sys

# Importa configurações e ferramentas do projeto
try:
    from config import PROCESS_NAME, MY_CONTAINERS_COUNT
    from core.packet import PacketBuilder, inject_packet, FUNC_CREATE_PACKET, FUNC_SEND_PACKET
except ImportError:
    print("❌ Erro de Importação: Certifique-se de salvar este script na pasta raiz do bot.")
    sys.exit(1)

# Define o Opcode de Fechar Container (Não estava no packet.py original)
OP_CLOSE = 0x87

def close_container(pm, container_id):
    """
    Envia o pacote para fechar um container específico.
    Estrutura: [Len] [OpCode 0x87] [ContainerID]
    """
    print(f"📦 Tentando fechar container ID: {container_id}...")
    
    pb = PacketBuilder()
    
    # 1. Cria o pacote com o Opcode 0x87
    pb.add_call(FUNC_CREATE_PACKET, OP_CLOSE)
    
    # 2. Adiciona o ID do container (Byte)
    pb.add_byte(container_id)
    
    # 3. Envia
    pb.add_call(FUNC_SEND_PACKET, 1)
    
    # 4. Injeta o código na memória
    inject_packet(pm, pb.get_code())
    print("✅ Packet injetado.")

def main():
    print("=== TESTE DE FECHAR CONTAINER ===")
    
    # 1. Conexão com o Cliente
    try:
        pm = pymem.Pymem(PROCESS_NAME)
        print(f"✅ Conectado ao {PROCESS_NAME}")
    except Exception as e:
        print(f"❌ Erro ao conectar: {e}")
        return

    # 2. Definição do Alvo
    # O "primeiro container de loot" é aquele logo após as suas backpacks.
    # Se MY_CONTAINERS_COUNT é 2 (BP Principal + Loot BP), o container de loot (corpo) será o índice 2.
    # Se você usa 0, o índice será 0.
    
    # Vamos ler do config ou usar um fallback seguro
    loot_start_index = MY_CONTAINERS_COUNT if 'MY_CONTAINERS_COUNT' in locals() else 2
    
    print(f"ℹ️ Configuração MY_CONTAINERS_COUNT: {loot_start_index}")
    print(f"🎯 Alvo: Fechar o container índice {loot_start_index} (Primeiro Loot Container)")

    # 3. Execução
    close_container(pm, loot_start_index)
    
    print("\nTeste concluído. Verifique no jogo se a janela fechou.")

if __name__ == "__main__":
    main()