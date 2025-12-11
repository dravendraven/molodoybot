import pymem
import time
import packet
from config import *
from inventory_core import find_item_in_containers

# Definição do Slot da Mão Direita (Right Hand)
# No Tibia: 5 = Direita, 6 = Esquerda
DEST_SLOT_ENUM = 5 

def test_move_logic(pm, base_addr, target_id):
    print(f"🔎 Procurando item ID {target_id} nas backpacks abertas...")
    
    # 1. Encontra ONDE o item está (precisamos das coordenadas de origem)
    item_data = find_item_in_containers(pm, base_addr, target_id)
    
    if not item_data:
        print(f"❌ Item {target_id} não encontrado em nenhuma backpack aberta.")
        return

    print(f"✅ Encontrado! Container {item_data['container_index']}, Slot {item_data['slot_index']}")

    # 2. Define Origem (Container)
    pos_from = packet.get_container_pos(item_data['container_index'], item_data['slot_index'])
    
    # 3. Define Destino (Mão Direita)
    pos_to = packet.get_inventory_pos(DEST_SLOT_ENUM)
    
    print(f"📦 Movendo de {pos_from} para {pos_to}...")
    
    # 4. Envia o pacote (MoveItem 0x78)
    # count=1 (move apenas 1 unidade/pilha)
    packet.move_item(pm, pos_from, pos_to, target_id, 1)
    
    print("🚀 Pacote enviado.")

def main():
    try:
        print("🔌 Conectando ao Tibia...")
        pm = pymem.Pymem("Tibia.exe")
        
        # Pega o endereço base do módulo
        base_addr = pymem.process.module_from_name(pm.process_handle, "Tibia.exe").lpBaseOfDll
        
        print("🟢 Conectado.")
        
        # Pergunta o ID (ex: 3308 para Machete, 3147 para Blank Rune)
        target_id = int(input("Digite o ID do item para mover para a MÃO DIREITA (ex: 3308): "))
        
        print("\n⚠️  ATENÇÃO: Deixe a Mão Direita VAZIA para o teste funcionar!")
        print("⏳  Você tem 3 segundos para focar na janela do Tibia...")
        time.sleep(3)
        
        test_move_logic(pm, base_addr, target_id)
        
        print("\nTeste finalizado.")
        
    except Exception as e:
        print(f"❌ Erro crítico: {e}")
        import traceback
        traceback.print_exc()
        input("Pressione Enter para sair...")

if __name__ == "__main__":
    main()