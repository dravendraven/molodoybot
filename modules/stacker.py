from config import *
from core.packet import PacketManager, get_container_pos
from core.packet_mutex import PacketMutex
from utils.timing import gauss_wait
from core.bot_state import state
from database.lootables_db import is_stackable
# NOTA: imports de auto_loot são LAZY dentro da função auto_stack_items()
# para evitar circular import com auto_loot.py

def auto_stack_items(pm, base_addr, hwnd, my_containers_count=None, mutex_context=None, loot_ids=None):
    """
    Agrupa itens empilháveis via Pacotes.

    Args:
        pm: Memory reader instance
        base_addr: Base address of player in memory
        hwnd: Window handle
        my_containers_count: Número de containers próprios (None = detecção automática)
        mutex_context: Contexto de mutex externo (ex: fisher_ctx) para reutilizar lock
        loot_ids: Lista de IDs para stackar (None = usar fallback baseado na flag)
    """
    # Protege ciclo de runemaking - não stacka durante runemaking
    if state.is_runemaking:
        return False

    # NOVO: Fallback baseado na flag se loot_ids não fornecido
    if loot_ids is None:
        if USE_CONFIGURABLE_LOOT_SYSTEM:
            # Modo novo: tentar ler de BOT_SETTINGS
            try:
                from main import BOT_SETTINGS
                loot_ids = BOT_SETTINGS.get('loot_ids', [])
            except ImportError:
                loot_ids = []
        else:
            # Modo antigo: usar LOOT_IDS hardcoded
            loot_ids = LOOT_IDS

    # Import lazy para evitar circular import
    from modules.auto_loot import scan_containers, get_player_containers, USE_AUTO_CONTAINER_DETECTION
    containers = scan_containers(pm, base_addr)

    # Determina containers do player
    if my_containers_count is not None:
        # Parâmetro explícito: usa sistema antigo (compatibilidade)
        limit = int(my_containers_count)
        my_containers = [c for c in containers if c.index < limit]
    elif USE_AUTO_CONTAINER_DETECTION:
        # Detecção automática via hasparent + tracking temporal
        my_containers = get_player_containers(containers)
    else:
        # Fallback: config padrão
        my_containers = [c for c in containers if c.index < MY_CONTAINERS_COUNT]

    # PacketManager para envio de pacotes
    packet = PacketManager(pm, base_addr)

    for cont in my_containers:
        for i, item_dst in enumerate(cont.items):

            # Alvo válido? (deve ser empilhável - flag Cumulative)
            if item_dst.count < 100 and item_dst.id in loot_ids and is_stackable(item_dst.id):

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