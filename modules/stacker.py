from config import *
from core.packet import PacketManager, get_container_pos
from core.packet_mutex import PacketMutex
from utils.timing import gauss_wait
from core.bot_state import state
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
        mutex_context: Contexto de mutex externo (ex: fisher_ctx) para reutilizar lock
    """
    # Protege ciclo de runemaking - não stacka durante runemaking
    if state.is_runemaking:
        return False

    # Import lazy para evitar circular import
    from modules.auto_loot import scan_containers
    containers = scan_containers(pm, base_addr)
    limit = int(my_containers_count)
    my_containers = containers[:limit]

    # PacketManager para envio de pacotes
    packet = PacketManager(pm, base_addr)

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
                        pos_from = get_container_pos(cont.index, item_src.slot_index)

                        # Destino: Slot Receptor
                        pos_to = get_container_pos(cont.index, item_dst.slot_index)

                        gauss_wait(0.2, 20)

                        # Executa Movimento (com mutex se contexto fornecido)
                        if mutex_context:
                            # Reutiliza mutex do fisher (mesmo grupo FISHER_GROUP)
                            with PacketMutex("stacker"):
                                packet.move_item(pos_from, pos_to, item_src.id, item_src.count)
                        else:
                            packet.move_item(pos_from, pos_to, item_src.id, item_src.count)
                        gauss_wait(0.3, 20)
                        return True

    return False