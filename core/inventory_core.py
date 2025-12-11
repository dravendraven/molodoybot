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
    Lê o ID do item que está na mão especificada (Left/Right) direto da memória.
    """
    try:
        offset = 0
        if slot_enum == 5: offset = 0x1CED90 # OFFSET_SLOT_RIGHT
        elif slot_enum == 6: offset = 0x1CED9C # OFFSET_SLOT_LEFT
        else: return 0
        return pm.read_int(base_addr + offset)
    except:
        return 0