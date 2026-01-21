import pymem
from config import *
from modules.auto_loot import scan_containers

def find_item_in_containers(pm, base_addr, item_id):
    """
    Procura um item (ID) dentro de todas as backpacks abertas.
    Retorna os índices lógicos (Container Index, Slot Index).
    """
    print(f"\n[DEBUG] Procurando Item ID: {item_id}...")
    
    # Obtém lista de contêineres abertos
    containers = scan_containers(pm, base_addr)
    
    if not containers:
        print("[DEBUG] Nenhum container encontrado/aberto!")
        return None

    total_items_seen = 0
    
    for cont in containers:
        print(f"[DEBUG] Container #{cont.index} (Qt: {cont.amount})")
        
        for item in cont.items:
            total_items_seen += 1
            # print(f"   - Slot {item.slot_index}: ID {item.id} (Qtd: {item.count})") # Descomente para ver TUDO
            
            if item.id == item_id:
                print(f"[DEBUG] ✅ ENCONTRADO! Container {cont.index}, Slot {item.slot_index}")
                return {
                    "type": "container",
                    "container_index": cont.index,
                    "slot_index": item.slot_index
                }
    
    print(f"[DEBUG] ❌ Item {item_id} não encontrado após verificar {total_items_seen} itens.")
    return None

def find_item_in_equipment(pm, base_addr, item_id):
    """
    Verifica se o item está equipado nas mãos ou munição.
    """
    # Lê IDs dos slots
    r_hand = pm.read_int(base_addr + OFFSET_SLOT_RIGHT)
    l_hand = pm.read_int(base_addr + OFFSET_SLOT_LEFT)
    ammo = pm.read_int(base_addr + OFFSET_SLOT_AMMO)
    
    # print(f"[DEBUG] Equip: R_HAND={r_hand}, L_HAND={l_hand}, AMMO={ammo}")

    if r_hand == item_id: return {"type": "equip", "slot": "right"}
    if l_hand == item_id: return {"type": "equip", "slot": "left"}
    if ammo == item_id: return {"type": "equip", "slot": "ammo"}
        
    return None

def get_item_id_in_hand(pm, base_addr, slot_enum):
    """
    Lê o ID do item que está na mão especificada direto da memória.

    Args:
        pm: Instância do Pymem
        base_addr: Endereço base do processo
        slot_enum: SLOT_RIGHT (5) ou SLOT_LEFT (6)

    Returns:
        ID do item ou 0 se vazio/erro
    """
    try:
        if slot_enum == SLOT_RIGHT:
            return pm.read_int(base_addr + OFFSET_SLOT_RIGHT)
        elif slot_enum == SLOT_LEFT:
            return pm.read_int(base_addr + OFFSET_SLOT_LEFT)
        return 0
    except Exception:
        return 0


def get_item_count_in_hand(pm, base_addr, slot_enum):
    """
    Lê a quantidade do item que está na mão especificada.

    Args:
        pm: Instância do Pymem
        base_addr: Endereço base do processo
        slot_enum: SLOT_RIGHT (5) ou SLOT_LEFT (6)

    Returns:
        Quantidade do item ou 0 se vazio/erro
    """
    try:
        if slot_enum == SLOT_RIGHT:
            return pm.read_int(base_addr + OFFSET_SLOT_RIGHT_COUNT)
        elif slot_enum == SLOT_LEFT:
            return pm.read_int(base_addr + OFFSET_SLOT_LEFT_COUNT)
        return 0
    except Exception:
        return 0


def get_spear_count_in_hands(pm, base_addr, spear_id=3277):
    """
    Conta quantas spears estão nas mãos do jogador.
    Verifica ambas as mãos e retorna o total.

    Args:
        pm: Instância do Pymem
        base_addr: Endereço base do processo
        spear_id: ID da spear (default: 3277)

    Returns:
        Tuple (total_count, slot_with_spear) onde slot_with_spear é SLOT_RIGHT, SLOT_LEFT ou None
    """
    total = 0
    slot_with_spear = None

    # Verifica mão direita
    right_id = get_item_id_in_hand(pm, base_addr, SLOT_RIGHT)
    if right_id == spear_id:
        count = get_item_count_in_hand(pm, base_addr, SLOT_RIGHT)
        total += count if count > 0 else 1  # Se count=0 mas tem item, assume 1
        slot_with_spear = SLOT_RIGHT

    # Verifica mão esquerda
    left_id = get_item_id_in_hand(pm, base_addr, SLOT_LEFT)
    if left_id == spear_id:
        count = get_item_count_in_hand(pm, base_addr, SLOT_LEFT)
        total += count if count > 0 else 1
        if slot_with_spear is None:
            slot_with_spear = SLOT_LEFT

    return total, slot_with_spear