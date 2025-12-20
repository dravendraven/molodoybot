import time
import pymem
import random
from config import *
from core.mouse_lock import is_mouse_busy
from core import packet
from core.packet_mutex import PacketMutex
from database import foods_db
from core.map_core import get_player_pos
from core.bot_state import state
# NOTA: auto_stack_items é importado LAZY dentro da função run_auto_loot()
# para evitar circular import com stacker.py

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
def run_auto_loot(pm, base_addr, hwnd, config=None):
    
    # --- HELPER DE CONFIGURAÇÃO ---
    def get_cfg(key, default):
        if callable(config):
            return config().get(key, default)
        return default

    # Lê as configs atuais
    my_containers_count = get_cfg('loot_containers', 2)
    dest_container_index = get_cfg('loot_dest', 0)
    drop_food_if_full = get_cfg('loot_drop_food', False)

    containers = scan_containers(pm, base_addr)
    limit_containers = int(my_containers_count)

    # Se não há loot para coletar, marca state como sem loot
    if len(containers) <= limit_containers:
        state.set_loot_state(False)
        return None

    # NOVO: Marca que há loot sendo processado
    state.set_loot_state(True)

    dest_idx, dest_slot = get_best_loot_destination(containers, limit_containers, dest_container_index)
    is_backpack_full = (dest_idx is None)

    for cont in containers[limit_containers:]:
        
        # --- LÓGICA DE BAG ---
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

            with PacketMutex("auto_loot"):
                packet.use_item(pm, bag_pos, bag_item_ref.id, index=cont.index)
            time.sleep(0.6)
            state.set_loot_state(False)
            return "BAG"

        # VARRER ITENS DO CORPO
        for item in reversed(cont.items):
            
            # --- AUTO EAT ---
            if item.id in FOOD_IDS:
                if is_player_full(pm, base_addr) and not drop_food_if_full:
                    # Se não for dropar, apenas ignora e continua o loop para o próximo item
                    continue
                
                food_pos = packet.get_container_pos(cont.index, item.slot_index)

                # Tenta comer
                with PacketMutex("auto_loot"):
                    packet.use_item(pm, food_pos, item.id)
                time.sleep(0.25)
                
                # Verifica se está full e a config de drop
                if is_player_full(pm, base_addr):
                    if drop_food_if_full:
                        food_name = foods_db.get_food_name(item.id)
                        print(f"🤢 Barriga cheia! Descartando {food_name}...")

                        px, py, pz = get_player_pos(pm, base_addr)
                        pos_ground = {'x': px, 'y': py, 'z': pz}

                        with PacketMutex("auto_loot"):
                            packet.move_item(pm, food_pos, pos_ground, item.id, item.count)
                        state.set_loot_state(False)
                        return ("DROP_FOOD", item.id, item.count)
                    else:
                        state.set_loot_state(False)
                        return "EAT_FULL"

                state.set_loot_state(False)
                return ("EAT", item.id)

            # --- AUTO LOOT ---
            if item.id in LOOT_IDS:
                if is_backpack_full:
                    print(f"⚠️ BACKPACK CHEIA! Não consigo pegar {item.id}")
                    state.set_loot_state(False)
                    return "FULL_BP_ALARM"

                print(f"💰 Loot: ID {item.id} -> BP {dest_idx} Slot {dest_slot}")

                pos_from = packet.get_container_pos(cont.index, item.slot_index)
                pos_to = packet.get_container_pos(dest_idx, dest_slot)

                with PacketMutex("auto_loot") as loot_ctx:
                    packet.move_item(pm, pos_from, pos_to, item.id, item.count)
                time.sleep(random.uniform(0.4, 0.8))

                # NOVO: Stack imediatamente após lotar (reutiliza contexto, sem delay)
                # Import lazy para evitar circular import
                from modules.stacker import auto_stack_items
                auto_stack_items(pm, base_addr, hwnd,
                                 my_containers_count=limit_containers,
                                 mutex_context=loot_ctx)

                dest_slot += 1
                state.set_loot_state(False)
                return ("LOOT", item.id, item.count)

            # --- AUTO DROP ---
            if item.id in DROP_IDS:
                print(f"🗑️ Drop: ID {item.id}")
                pos_from = packet.get_container_pos(cont.index, item.slot_index)
                px, py, pz = get_player_pos(pm, base_addr)
                pos_ground = {'x': px, 'y': py, 'z': pz}

                with PacketMutex("auto_loot"):
                    packet.move_item(pm, pos_from, pos_ground, item.id, item.count)
                time.sleep(0.3)
                state.set_loot_state(False)
                return "DROP"

    # NOVO: Fecha todos os containers de loot processados
    for cont in containers[limit_containers:]:
        packet.close_container(pm, cont.index)
        time.sleep(random.uniform(0.5, 1))

    state.set_loot_state(False)
    return None