import time

from core import packet
from core.packet_mutex import PacketMutex
from config import *
from modules.auto_loot import scan_containers, is_player_full

def attempt_eat(pm, base_addr, hwnd):
    """
    Tenta comer usando Packet Injection.
    Inclui logs de DEBUG para diagnosticar falhas.
    """
    containers = scan_containers(pm, base_addr)
    
    # DEBUG 1: Verifica se achou containers
    if not containers:
        print("[DEBUG] scan_containers retornou lista vazia! Erro de leitura ou bolsas fechadas.")
        return False

    print(f"[DEBUG] Varrendo {len(containers)} containers...")

    for cont in containers:
        for slot, item in enumerate(cont.items):
            # DEBUG 2: Descomente a linha abaixo se quiser ver TODOS os itens que ele acha (pode spammar o log)
            # print(f"[DEBUG] Container {cont.index} Slot {slot}: ID {item.id}")

            if item.id in FOOD_IDS:
                f_name = foods_db.get_food_name(item.id)
                print(f"[DEBUG] Comida encontrada: {f_name} ID: {item.id} no Container {cont.index}, Slot {slot}")
                
                food_pos = packet.get_container_pos(cont.index, slot)

                with PacketMutex("eater"):
                    packet.use_item(pm, food_pos, item.id, index=cont.index)
                
                # Pequena pausa para garantir que o servidor processe
                time.sleep(0.6) 
                
                if is_player_full(pm, base_addr):
                    print("[DEBUG] Personagem está cheio (FULL).")
                    return "FULL"
                
                print(f"[DEBUG] Comeu com sucesso. Retornando ID: {item.id}")
                return item.id
    
    print("[DEBUG] Loop finalizado. Nenhuma comida da lista FOOD_IDS foi encontrada.")
    return False