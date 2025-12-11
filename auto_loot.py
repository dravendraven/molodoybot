import time
import pymem
import random
from config import *
from mouse_lock import is_mouse_busy
import packet 
import foods_db

# ==============================================================================
# CLASSES DE DADOS
# ==============================================================================
class Item:
    def __init__(self, item_id, count, slot_index):
        self.id = item_id
        self.count = count
        self.slot_index = slot_index 

    def __repr__(self):
        return f"[Slot {self.slot_index}] ID: {self.id} | Qt: {self.count}"

class Container:
    def __init__(self, index, address, name, amount, volume, items):
        self.index = index
        self.address = address
        self.name = name
        self.amount = amount
        self.volume = volume # <--- NOVO: Capacidade Total (ex: 20 para BP)
        self.items = items

    def __repr__(self):
        return f"Container {self.index}: '{self.name}' ({self.amount}/{self.volume})"

# ==============================================================================
# LEITURA DE MEMÓRIA
# ==============================================================================
def read_container_name(pm, address):
    try: return pm.read_string(address + OFFSET_CNT_NAME, 32)
    except: return "Unknown"

def scan_containers(pm, base_addr):
    open_containers = []
    
    # Previne erro se MAX_CONTAINERS for lido errado
    max_cnt = MAX_CONTAINERS if isinstance(MAX_CONTAINERS, int) else 16
    
    for i in range(max_cnt):
        cnt_addr = base_addr + OFFSET_CONTAINER_START + (i * STEP_CONTAINER)
        try:
            is_open = pm.read_int(cnt_addr + OFFSET_CNT_IS_OPEN)
            if is_open == 1:
                name = read_container_name(pm, cnt_addr)
                amount = pm.read_int(cnt_addr + OFFSET_CNT_AMOUNT)
                volume = pm.read_int(cnt_addr + OFFSET_CNT_VOLUME) # <--- Lendo Capacidade
                
                items = []
                for slot in range(amount):
                    item_id_addr = cnt_addr + OFFSET_CNT_ITEM_ID + (slot * STEP_SLOT)
                    item_cnt_addr = cnt_addr + OFFSET_CNT_ITEM_COUNT + (slot * STEP_SLOT)
                    try:
                        raw_id = int(pm.read_int(item_id_addr))
                        raw_count = int(pm.read_int(item_cnt_addr))
                        final_count = max(1, raw_count)
                        if raw_id > 0: items.append(Item(raw_id, final_count, slot))
                    except: pass
                
                open_containers.append(Container(i, cnt_addr, name, amount, volume, items))
        except: continue
    return open_containers

def is_player_full(pm, base_addr):
    try:
        timer = int(pm.read_int(base_addr + OFFSET_STATUS_TIMER))
        if timer > 0:
            msg = pm.read_string(base_addr + OFFSET_STATUS_TEXT, 50)
            if "full" in msg.lower() or "capacity" in msg.lower(): return True
        return False
    except: return False

# ==============================================================================
# LÓGICA INTELIGENTE DE DESTINO
# ==============================================================================
def get_best_loot_destination(containers, my_containers_max_count, start_index=0):
    """
    Procura o primeiro container SEU (índice < my_containers_max_count)
    que tenha espaço livre (amount < volume).
    
    Retorna: (container_index, slot_para_jogar) ou (None, None) se tudo cheio.
    """
    # Filtra apenas os containers que são "meus" (geralmente 0, 1, 2...)
    my_bps = [c for c in containers if c.index < my_containers_max_count]
    
    # Ordena para checar na ordem: Destino Preferido -> Próximos -> Anteriores
    # Ex: Se start=1, checa 1, depois 2, depois 0.
    sorted_bps = sorted(my_bps, key=lambda c: (c.index < start_index, c.index))

    for cont in sorted_bps:
        # Verifica se tem espaço
        if cont.amount < cont.volume:
            # Tem espaço! O slot alvo é igual à quantidade atual (Append no final)
            return cont.index, cont.amount
            
    return None, None

# ==============================================================================
# EXECUÇÃO DO AUTO LOOT
# ==============================================================================
def run_auto_loot(pm, base_addr, hwnd, my_containers_count=MY_CONTAINERS_COUNT, dest_container_index=DEST_CONTAINER_INDEX):
    
    containers = scan_containers(pm, base_addr)
    limit_containers = int(my_containers_count)
    
    # Se não tem containers de monstros abertos, não faz nada
    if len(containers) <= limit_containers: return None

    # 1. Calcula onde vamos jogar o loot ANTES de processar
    # Isso evita calcular para cada item, assumindo que vai caber um por vez
    dest_idx, dest_slot = get_best_loot_destination(containers, limit_containers, dest_container_index)
    
    is_backpack_full = (dest_idx is None)

    # Itera sobre containers de Monstros (os que estão além do meu limite)
    for cont in containers[limit_containers:]:
        
        # --- LÓGICA DE BAG (ABRIR BAGS DENTRO DE CORPOS) ---
        has_bag_to_open = False
        bag_item_ref = None
        useful_items_count = 0
        bag_count = 0
        
        for it in cont.items:
            if it.id in LOOT_IDS or it.id in FOOD_IDS or it.id in DROP_IDS: useful_items_count += 1
            if it.id in LOOT_CONTAINER_IDS: bag_count += 1; bag_item_ref = it

        if useful_items_count == 0 and bag_count > 0: has_bag_to_open = True

        if has_bag_to_open and bag_item_ref:
            print(f"🎒 Abrindo Bag no corpo...")
            bag_pos = packet.get_container_pos(cont.index, bag_item_ref.slot_index)
            packet.use_item(pm, bag_pos, bag_item_ref.id, index=cont.index)
            time.sleep(0.6)
            return "BAG"

        # VARRER ITENS DO CORPO
        for item in reversed(cont.items):
            
            # --- AUTO EAT ---
            if item.id in FOOD_IDS:
                food_name = foods_db.get_food_name(item.id)
                print(f"🍖 Comida no corpo: {food_name} (ID: {item.id})")
                food_pos = packet.get_container_pos(cont.index, item.slot_index)
                for i in range(item.count):
                    packet.use_item(pm, food_pos, item.id)
                    time.sleep(0.25)
                    if is_player_full(pm, base_addr): return "EAT_FULL"
                return ("EAT", item.id)

            # --- AUTO LOOT ---
            if item.id in LOOT_IDS:
                
                # VERIFICAÇÃO DE FULL
                if is_backpack_full:
                    print(f"⚠️ BACKPACK CHEIA! Não consigo pegar {item.id}")
                    # Retorna um código especial para a GUI talvez tocar um alarme
                    return "FULL_BP_ALARM"

                print(f"💰 Loot: ID {item.id} -> BP {dest_idx} Slot {dest_slot}")
                
                pos_from = packet.get_container_pos(cont.index, item.slot_index)
                
                # AQUI ESTÁ A MÁGICA: Joga no slot calculado dinamicamente
                pos_to = packet.get_container_pos(dest_idx, dest_slot)
                
                packet.move_item(pm, pos_from, pos_to, item.id, item.count)
                
                time.sleep(0.3)
                
                # Truque: Incrementa o slot localmente para tentar pegar o próximo item
                # Se a BP encher nesse meio tempo, na próxima iteração o get_best recalcula
                dest_slot += 1
                
                return ("LOOT", item.id, item.count)

            # --- AUTO DROP ---
            if item.id in DROP_IDS:
                print(f"🗑️ Drop: ID {item.id}")
                pos_from = packet.get_container_pos(cont.index, item.slot_index)
                # Precisamos da posição do player para jogar no chão
                # Import circular evitado se passarmos coordenadas ou lermos aqui rápido
                # Vamos assumir que drop é menos prioritário ou usar import dentro da func
                from map_core import get_player_pos
                px, py, pz = get_player_pos(pm, base_addr)
                pos_ground = {'x': px, 'y': py, 'z': pz}
                
                packet.move_item(pm, pos_from, pos_ground, item.id, item.count)
                time.sleep(0.3)
                return "DROP"
                
    return None