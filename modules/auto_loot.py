import time
import pymem
import random
from config import *
from utils.timing import gauss_wait
from core.mouse_lock import is_mouse_busy
from core.packet import PacketManager, get_container_pos, get_ground_pos
# PacketMutex removido - locks globais em PacketManager cuidam da sincronização
from database import foods_db
from core.map_core import get_player_pos
from core.bot_state import state
from core.player_core import is_player_moving

# Imports condicionais do novo sistema de loot configurável
if USE_CONFIGURABLE_LOOT_SYSTEM:
    from database import lootables_db
# NOTA: auto_stack_items e get_player_cap são importados LAZY dentro da função run_auto_loot()
# para evitar circular import com stacker.py e fisher.py

# ==============================================================================
# CONFIGURAÇÃO: SISTEMA DE DETECÇÃO DE CONTAINERS
# ==============================================================================
# True  = Usa detecção automática (hasparent + tracking temporal)
# False = Usa sistema antigo (config 'loot_containers' define quantidade)
USE_AUTO_CONTAINER_DETECTION = True  # Desabilitado por padrão - testar antes

# ==============================================================================
# TRACKING DE CONTAINERS DE LOOT (Estado Global)
# ==============================================================================
_loot_indices = set()  # Índices marcados como loot em tempo real

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
    def __init__(self, index, address, name, amount, volume, hasparent, items):
        self.index = index
        self.address = address
        self.name = name
        self.amount = amount
        self.volume = volume
        self.hasparent = hasparent  # 0 = raiz, 1 = filho de outro container
        self.items = items

    def __repr__(self):
        parent_str = "filho" if self.hasparent else "raiz"
        return f"Container {self.index}: '{self.name}' ({self.amount}/{self.volume}) [{parent_str}]"

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
                volume = pm.read_int(cnt_addr + OFFSET_CNT_VOLUME)
                hasparent = pm.read_int(cnt_addr + OFFSET_CNT_HAS_PARENT)  # 0=raiz, 1=filho

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

                open_containers.append(Container(i, cnt_addr, name, amount, volume, hasparent, items))
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
# CLASSIFICAÇÃO AUTOMÁTICA DE CONTAINERS (Tracking Temporal)
# ==============================================================================
def track_loot_containers(containers):
    """
    Atualiza tracking de quais índices são loot.
    Usa nome "Dead " + hasparent para classificar.
    """
    global _loot_indices

    current_open = {c.index for c in containers}

    # Limpa índices de containers que fecharam
    _loot_indices = _loot_indices & current_open

    for c in containers:
        if c.name.startswith("Dead ") or c.name.startswith("Slain "):
            # Corpo de criatura = sempre loot
            _loot_indices.add(c.index)
        elif c.hasparent == 1 and c.index in _loot_indices:
            # Bag que substituiu corpo = mantém como loot
            pass
        elif c.hasparent == 0 and not c.name.startswith("Dead "):
            # Container raiz do player = remove do tracking
            _loot_indices.discard(c.index)

def get_loot_containers(containers):
    """Retorna apenas containers classificados como loot."""
    track_loot_containers(containers)
    return [c for c in containers if c.index in _loot_indices or c.name.startswith("Dead ")]

def get_player_containers(containers):
    """Retorna apenas containers do player."""
    loot_set = {c.index for c in get_loot_containers(containers)}
    return [c for c in containers if c.index not in loot_set]

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
    # Protege ciclo de runemaking - não processa loot durante runemaking
    if state.is_runemaking:
        return None

    # Não processa loot enquanto personagem está andando
    if is_player_moving(pm, base_addr):
        return None

    # --- HELPER DE CONFIGURAÇÃO ---
    def get_cfg(key, default):
        if callable(config):
            return config().get(key, default)
        return default

    # Lê as configs atuais
    dest_container_index = get_cfg('loot_dest', 0)
    drop_food_if_full = get_cfg('loot_drop_food', False)

    # NOVO: Ler listas configuráveis OU usar hardcoded (depende da flag)
    if USE_CONFIGURABLE_LOOT_SYSTEM:
        loot_ids = get_cfg('loot_ids', [])  # Lista de IDs resolvidos da GUI
        drop_ids = get_cfg('drop_ids', [])
    else:
        # Fallback: usar valores hardcoded do config.py
        loot_ids = LOOT_IDS
        drop_ids = DROP_IDS

    containers = scan_containers(pm, base_addr)

    # ==========================================================================
    # SELEÇÃO DO SISTEMA DE DETECÇÃO DE CONTAINERS
    # ==========================================================================
    if USE_AUTO_CONTAINER_DETECTION:
        # NOVO SISTEMA: Detecção automática via hasparent + tracking temporal
        loot_containers = get_loot_containers(containers)
        player_containers = get_player_containers(containers)
        my_containers_count = len(player_containers)
    else:
        # SISTEMA ANTIGO: Usa config 'loot_containers' para definir quantidade
        my_containers_count = get_cfg('loot_containers', 2)
        limit_containers = int(my_containers_count)

        # Sistema antigo: containers[0:limit] = player, containers[limit:] = loot
        player_containers = [c for c in containers if c.index < limit_containers]
        loot_containers = [c for c in containers if c.index >= limit_containers]

    # Se não há loot para coletar, marca state como sem loot
    if not loot_containers:
        state.set_loot_state(False)
        return None

    # NOVO: Marca que há loot sendo processado
    state.set_loot_state(True)

    # PacketManager para envio de pacotes
    packet = PacketManager(pm, base_addr)

    # Encontra destino nos containers do player
    dest_idx, dest_slot = get_best_loot_destination(player_containers, len(player_containers), dest_container_index)
    is_backpack_full = (dest_idx is None)

    for cont in loot_containers:
        
        # --- LÓGICA DE BAG ---
        has_bag_to_open = False
        bag_item_ref = None
        useful_items_count = 0
        bag_count = 0
        
        for it in cont.items:
            if it.id in loot_ids or it.id in FOOD_IDS or it.id in drop_ids: useful_items_count += 1
            if it.id in LOOT_CONTAINER_IDS: bag_count += 1; bag_item_ref = it

        if useful_items_count == 0 and bag_count > 0: has_bag_to_open = True

        if has_bag_to_open and bag_item_ref:
            print(f"🎒 Abrindo Bag no corpo...")
            bag_pos = get_container_pos(cont.index, bag_item_ref.slot_index)

            packet.use_item(bag_pos, bag_item_ref.id, index=cont.index)
            gauss_wait(0.6, 15)
            state.set_loot_state(False)
            return "BAG"

        # VARRER ITENS DO CORPO
        for item in reversed(cont.items):
            
            # --- AUTO EAT ---
            if item.id in FOOD_IDS:
                if is_player_full(pm, base_addr) and not drop_food_if_full:
                    # Se não for dropar, apenas ignora e continua o loop para o próximo item
                    continue

                food_pos = get_container_pos(cont.index, item.slot_index)

                # Tenta comer
                packet.use_item(food_pos, item.id)
                gauss_wait(0.25, 20)

                # Verifica se está full e a config de drop
                if is_player_full(pm, base_addr):
                    if drop_food_if_full:
                        food_name = foods_db.get_food_name(item.id)
                        print(f"🤢 Barriga cheia! Descartando {food_name}...")

                        px, py, pz = get_player_pos(pm, base_addr)
                        pos_ground = get_ground_pos(px, py, pz)

                        packet.move_item(food_pos, pos_ground, item.id, item.count)
                        state.set_loot_state(False)
                        return ("DROP_FOOD", item.id, item.count)
                    else:
                        state.set_loot_state(False)
                        return "EAT_FULL"

                state.set_loot_state(False)
                return ("EAT", item.id)

            # --- AUTO LOOT ---
            if item.id in loot_ids:
                # NOVO: Weight check antes de lotar (só se sistema configurável ativo)
                if USE_CONFIGURABLE_LOOT_SYSTEM:
                    # Import lazy para evitar circular import
                    from modules.fisher import get_player_cap

                    item_weight = lootables_db.get_loot_weight(item.id)
                    current_cap = get_player_cap(pm, base_addr)

                    if item_weight > current_cap:
                        # Item muito pesado para capacity atual
                        item_name = lootables_db.get_loot_name(item.id)
                        print(f"⚠️ LOOT IGNORADO: {item_name} ({item_weight:.1f}oz) > Cap ({current_cap:.1f}oz)")
                        continue  # Pula este item, vai para o próximo

                if is_backpack_full:
                    print(f"⚠️ BACKPACK CHEIA! Não consigo pegar {item.id}")
                    state.set_loot_state(False)
                    return "FULL_BP_ALARM"

                print(f"💰 Loot: ID {item.id} -> BP {dest_idx} Slot {dest_slot}")

                pos_from = get_container_pos(cont.index, item.slot_index)
                pos_to = get_container_pos(dest_idx, dest_slot)

                packet.move_item(pos_from, pos_to, item.id, item.count)
                gauss_wait(0.6, 30)

                # Stack imediatamente após lotar
                # Import lazy para evitar circular import
                from modules.stacker import auto_stack_items
                auto_stack_items(pm, base_addr, hwnd,
                                 my_containers_count=my_containers_count,
                                 loot_ids=loot_ids)

                dest_slot += 1
                state.set_loot_state(False)
                return ("LOOT", item.id, item.count)

            # --- AUTO DROP ---
            if item.id in drop_ids:
                print(f"🗑️ Drop: ID {item.id}")
                pos_from = get_container_pos(cont.index, item.slot_index)
                px, py, pz = get_player_pos(pm, base_addr)
                pos_ground = get_ground_pos(px, py, pz)

                packet.move_item(pos_from, pos_ground, item.id, item.count)
                gauss_wait(0.3, 20)
                state.set_loot_state(False)
                return "DROP"

    # Fecha todos os containers de loot processados
    for cont in loot_containers:
        packet.close_container(cont.index)
        gauss_wait(0.75, 30)

    state.set_loot_state(False)
    return None