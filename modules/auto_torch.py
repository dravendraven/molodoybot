# modules/auto_torch.py
"""
Auto Torch - Mantém uma tocha acesa no ammo slot automaticamente.

Lógica:
1. Tocha acesa no ammo → não faz nada (espera acabar)
2. Tocha apagada no ammo → acende via use_item
3. Tocha queimada (2926) → joga fora, equipa nova do inventário
4. Slot vazio ou outro item → procura tocha no inventário e equipa
"""
import time
from config import (
    OFFSET_SLOT_AMMO, TORCH_UNLIT_IDS, TORCH_LIT_IDS, TORCH_BURNT_ID,
    TORCH_ALL_IDS, OFFSET_CONTAINER_START, STEP_CONTAINER, MAX_CONTAINERS,
    OFFSET_CNT_IS_OPEN, OFFSET_CNT_AMOUNT, OFFSET_CNT_ITEM_ID,
    OFFSET_CNT_ITEM_COUNT, OFFSET_CNT_NAME, STEP_SLOT
)
from core.packet import PacketManager, get_inventory_pos, get_container_pos, get_ground_pos
from core.packet_mutex import PacketMutex
from core.bot_state import state
from core.map_core import get_player_pos
from utils.timing import gauss_wait

# Slot index para packets (ammo = 10)
PACKET_SLOT_AMMO = 10


def _can_act():
    """Verifica se é seguro agir (mesmo padrão dos outros módulos)."""
    if not state.is_safe():
        return False
    if state.is_processing_loot:
        return False
    if state.is_runemaking:
        return False
    if state.is_spear_pickup_pending:
        return False
    if state.is_following:
        return False
    return True


def _find_torch_in_containers(pm, base_addr):
    """
    Procura qualquer tocha (acesa ou apagada) nos containers abertos.

    Returns:
        (container_index, slot_index, item_id) ou None
    """
    torch_ids = set(TORCH_UNLIT_IDS + TORCH_LIT_IDS)

    for i in range(MAX_CONTAINERS):
        cnt_addr = base_addr + OFFSET_CONTAINER_START + (i * STEP_CONTAINER)
        try:
            is_open = pm.read_int(cnt_addr + OFFSET_CNT_IS_OPEN)
            if is_open != 1:
                continue

            # Lê o nome do container para identificar se é loot
            name_bytes = pm.read_bytes(cnt_addr + OFFSET_CNT_NAME, 32)
            name = name_bytes.split(b'\x00')[0].decode('latin-1', errors='ignore')

            # Pula apenas containers de loot (corpos de monstros)
            if name.startswith("Dead ") or name.startswith("Slain "):
                continue

            amount = pm.read_int(cnt_addr + OFFSET_CNT_AMOUNT)
            for slot in range(amount):
                item_id = pm.read_int(cnt_addr + OFFSET_CNT_ITEM_ID + (slot * STEP_SLOT))
                if item_id in torch_ids:
                    return (i, slot, item_id)
        except Exception:
            continue

    return None


def auto_torch_loop(pm, base_addr, check_running, get_enabled, log_func=print):
    """
    Loop principal do Auto Torch.

    Args:
        pm: pymem instance
        base_addr: base address do cliente
        check_running: callable que retorna False para encerrar
        get_enabled: callable que retorna True se feature está habilitada
        log_func: callback de log
    """
    packet = PacketManager(pm, base_addr)

    def log(msg):
        timestamp = time.strftime("%H:%M:%S")
        log_func(f"[{timestamp}] [TORCH] {msg}")

    while True:
        if check_running and not check_running():
            return

        if not get_enabled():
            time.sleep(2)
            continue

        if not _can_act():
            time.sleep(1)
            continue

        try:
            ammo_id = pm.read_int(base_addr + OFFSET_SLOT_AMMO)

            # 1. Tocha acesa → nada a fazer
            if ammo_id in TORCH_LIT_IDS:
                pass

            # 2. Tocha apagada → acender
            elif ammo_id in TORCH_UNLIT_IDS:
                if _can_act():
                    ammo_pos = get_inventory_pos(PACKET_SLOT_AMMO)
                    with PacketMutex("auto_torch"):
                        packet.use_item(ammo_pos, ammo_id, 0, 0)
                    log("🔥 Tocha acesa.")
                    gauss_wait(1.0, 20)

            # 3. Tocha queimada → jogar fora + equipar nova
            elif ammo_id == TORCH_BURNT_ID:
                if _can_act():
                    px, py, pz = get_player_pos(pm, base_addr)
                    ammo_pos = get_inventory_pos(PACKET_SLOT_AMMO)
                    ground_pos = get_ground_pos(px, py, pz)

                    # Joga tocha queimada no chão
                    with PacketMutex("auto_torch"):
                        packet.move_item(ammo_pos, ground_pos, TORCH_BURNT_ID, 1)
                    log("🗑️ Tocha queimada descartada.")
                    gauss_wait(0.5, 25)

                    # Procura nova tocha e equipa
                    if _can_act():
                        found = _find_torch_in_containers(pm, base_addr)
                        if found:
                            cnt_idx, slot_idx, torch_id = found
                            from_pos = get_container_pos(cnt_idx, slot_idx)
                            to_pos = get_inventory_pos(PACKET_SLOT_AMMO)
                            with PacketMutex("auto_torch"):
                                packet.move_item(from_pos, to_pos, torch_id, 1)
                            log("🔦 Nova tocha equipada.")
                            gauss_wait(0.5, 25)

                            # Se tocha apagada, acende
                            if _can_act() and torch_id in TORCH_UNLIT_IDS:
                                with PacketMutex("auto_torch"):
                                    packet.use_item(to_pos, torch_id, 0, 0)
                                log("🔥 Tocha acesa.")
                                gauss_wait(0.5, 20)
                        else:
                            log("⚠️ Sem tochas no inventário.")

            # 4. Vazio ou outro item → procurar tocha no inventário
            elif ammo_id == 0 or ammo_id not in TORCH_ALL_IDS:
                if _can_act():
                    found = _find_torch_in_containers(pm, base_addr)
                    if found:
                        cnt_idx, slot_idx, torch_id = found
                        from_pos = get_container_pos(cnt_idx, slot_idx)
                        to_pos = get_inventory_pos(PACKET_SLOT_AMMO)
                        with PacketMutex("auto_torch"):
                            packet.move_item(from_pos, to_pos, torch_id, 1)
                        log("🔦 Tocha equipada no ammo slot.")
                        gauss_wait(0.5, 25)

                        # Se tocha apagada, acende
                        if _can_act() and torch_id in TORCH_UNLIT_IDS:
                            with PacketMutex("auto_torch"):
                                packet.use_item(to_pos, torch_id, 0, 0)
                            log("🔥 Tocha acesa.")
                            gauss_wait(0.5, 20)

        except Exception as e:
            log(f"❌ Erro: {e}")

        gauss_wait(2.0, 30)
