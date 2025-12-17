import time
from config import *
from core import packet
from core.packet_mutex import PacketMutex
# NOTA: scan_containers é importado LAZY dentro da função auto_stack_items()
# para evitar circular import com auto_loot.py

def auto_stack_items(pm, base_addr, hwnd, my_containers_count=MY_CONTAINERS_COUNT, mutex_context=None):
    """
    Agrupa itens empilháveis via Pacotes.

    Args:
        pm: Memory reader instance
        base_addr: Base address of player in memory
        hwnd: Window handle
        my_containers_count: Número de containers próprios
        mutex_context: Se fornecido, reutiliza mutex do módulo caller (Fisher/AutoLoot).
                      Se None, adquire próprio mutex (standalone mode).
    """
    # Import lazy para evitar circular import
    from modules.auto_loot import scan_containers
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

                        print(f"🔄 STACKER: Juntando {item_src.id}")

                        # Origem: Slot Doador
                        pos_from = packet.get_container_pos(cont.index, item_src.slot_index)

                        # Destino: Slot Receptor
                        pos_to = packet.get_container_pos(cont.index, item_dst.slot_index)

                        # Executa Movimento
                        if mutex_context:
                            # Reutiliza contexto do caller (Fisher/AutoLoot)
                            packet.move_item(pm, pos_from, pos_to, item_src.id, item_src.count)
                        else:
                            # Adquire próprio mutex (standalone mode)
                            with PacketMutex("stacker"):
                                packet.move_item(pm, pos_from, pos_to, item_src.id, item_src.count)

                        time.sleep(0.3)
                        return True

    return False