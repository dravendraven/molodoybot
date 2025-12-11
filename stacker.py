import time
from config import *
from auto_loot import scan_containers
import packet # <--- NOVO

def auto_stack_items(pm, base_addr, hwnd, my_containers_count=MY_CONTAINERS_COUNT):
    """
    Agrupa itens empilháveis via Pacotes.
    """
    containers = scan_containers(pm, base_addr)
    limit = int(my_containers_count)
    my_containers = containers[:limit]
    
    for cont in my_containers:
        for i, item_dst in enumerate(cont.items):
            
            # Alvo válido?
            if item_dst.count < 100 and item_dst.id in LOOT_IDS:
                
                # Procura doador
                for j, item_src in enumerate(cont.items):
                    
                    # Regras de Stack (Mesmo ID, Slot Diferente, Não Cheio)
                    if (item_src.id == item_dst.id and 
                        item_src.slot_index > item_dst.slot_index and 
                        item_src.count < 100):
                        
                        print(f"🔄 STACKER (Packet): Juntando {item_src.id}")
                        
                        # Origem: Slot Doador
                        pos_from = packet.get_container_pos(cont.index, item_src.slot_index)
                        
                        # Destino: Slot Receptor
                        pos_to = packet.get_container_pos(cont.index, item_dst.slot_index)
                        
                        # Executa Movimento
                        packet.move_item(pm, pos_from, pos_to, item_src.id, item_src.count)
                        
                        time.sleep(0.3) 
                        return True
                        
    return False