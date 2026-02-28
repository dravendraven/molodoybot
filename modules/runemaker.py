import time
import random
import win32con

from core.packet import (
    PacketManager, get_inventory_pos, get_container_pos
)
from core.navigation_utils import navigate_to_position
from core.packet_mutex import PacketMutex
from config import *
from core.inventory_core import find_item_in_containers
from modules.auto_loot import scan_containers
from core.map_core import get_player_pos
from modules.eater import attempt_eat
from core.input_core import press_hotkey
from database import foods_db
from core.config_utils import make_config_getter
from core.bot_state import state
from core.player_core import wait_until_stopped
from database.runes_db import BLANK_RUNE_ID, is_conjured_rune

# Usar constantes do config.py ao invés de redefinir
# SLOT_RIGHT e SLOT_LEFT removidos (usar HandSlot do config)

def get_vk_code(key_str):
    key_str = key_str.upper().strip()
    mapping = {
        "F1": win32con.VK_F1, "F2": win32con.VK_F2, "F3": win32con.VK_F3,
        "F4": win32con.VK_F4, "F5": win32con.VK_F5, "F6": win32con.VK_F6,
        "F7": win32con.VK_F7, "F8": win32con.VK_F8, "F9": win32con.VK_F9,
        "F10": win32con.VK_F10, "F11": win32con.VK_F11, "F12": win32con.VK_F12
    }
    return mapping.get(key_str, win32con.VK_F3)

def get_item_id_in_hand(pm, base_addr, slot_enum):
    try:
        offset = 0
        if slot_enum == SLOT_RIGHT: offset = OFFSET_SLOT_RIGHT
        elif slot_enum == SLOT_LEFT:  offset = OFFSET_SLOT_LEFT
        else: return 0
        return pm.read_int(base_addr + offset)
    except:
        return 0

def find_container_with_space(pm, base_addr, preferred_idx=0):
    """
    Busca container com espaco livre.
    Prioriza preferred_idx, mas busca em outros se cheio.

    Returns: (container_index, free_slot) ou (None, None) se todos cheios
    """
    containers = scan_containers(pm, base_addr)

    # Ordenar: preferred primeiro, depois por index
    sorted_conts = sorted(containers, key=lambda c: (c.index != preferred_idx, c.index))

    for cont in sorted_conts:
        if cont.amount < cont.volume:
            return cont.index, cont.amount

    return None, None  # Todos cheios


def get_free_slot_in_container(pm, base_addr, target_container_idx=0):
    """
    Encontra o próximo slot livre em um container específico.
    DEPRECATED: Use find_container_with_space() para busca mais inteligente.

    Retorna: (container_index, free_slot) ou (None, None) se container cheio/não encontrado.
    """
    containers = scan_containers(pm, base_addr)

    for cont in containers:
        if cont.index == target_container_idx:
            if cont.amount < cont.volume:
                return cont.index, cont.amount
            else:
                return None, None

    return None, None


def execute_with_retry(action_fn, validate_fn, max_retries=3, delay=0.5, description="acao"):
    """
    Executa uma acao e valida o resultado. Retry ate max_retries.

    Args:
        action_fn: funcao que executa a acao (sem args), pode ser None se acao ja foi executada
        validate_fn: funcao que retorna True se sucesso
        max_retries: tentativas maximas
        delay: delay entre tentativas
        description: descricao para logs

    Returns: True se sucesso, False se todas tentativas falharam
    """
    for attempt in range(max_retries):
        if action_fn is not None:
            action_fn()
        time.sleep(delay)

        if validate_fn():
            return True

        if attempt < max_retries - 1:
            print(f"[RUNEMAKER] {description} falhou, tentativa {attempt+1}/{max_retries}")
            # Re-executa a acao na proxima tentativa se action_fn existir

    print(f"[RUNEMAKER] {description} falhou apos {max_retries} tentativas!")
    return False


def verify_blank_equipped(pm, base_addr, slot_enum, blank_id):
    """Verifica se blank rune esta equipada na mao."""
    hand_id = get_item_id_in_hand(pm, base_addr, slot_enum)
    return hand_id == blank_id


def verify_rune_conjured(pm, base_addr, slot_enum, blank_id):
    """Verifica se a runa foi conjurada (ID mudou de blank)."""
    hand_id = get_item_id_in_hand(pm, base_addr, slot_enum)
    # Sucesso se: ID diferente de blank E (ID e runa conhecida OU ID > 0)
    if hand_id == blank_id:
        return False
    return hand_id > 0 and (is_conjured_rune(hand_id) or hand_id != blank_id)


def verify_hand_empty(pm, base_addr, slot_enum):
    """Verifica se a mao esta vazia."""
    return get_item_id_in_hand(pm, base_addr, slot_enum) == 0


def verify_item_in_hand(pm, base_addr, slot_enum, expected_item_id):
    """Verifica se um item especifico esta na mao."""
    return get_item_id_in_hand(pm, base_addr, slot_enum) == expected_item_id


def unequip_hand(pm, base_addr, slot_enum, preferred_container=0, packet=None):
    """
    Desequipa item da mao para um container com espaco.

    Busca inteligente: se container preferido esta cheio, busca outros.
    Retorna dict com informacoes detalhadas para rastreamento.

    Args:
        slot_enum: SLOT_LEFT ou SLOT_RIGHT
        preferred_container: container preferido (default: 0)
        packet: PacketManager instance (created if None)

    Returns:
        dict: {"item_id": int, "container_idx": int, "slot_idx": int} se sucesso
        None: Se falha (mao vazia, todos containers cheios, ou validacao falhou)
    """
    if packet is None:
        packet = PacketManager(pm, base_addr)

    current_id = get_item_id_in_hand(pm, base_addr, slot_enum)
    if current_id <= 0:
        return None  # Mao ja vazia

    # Busca container com espaco (busca inteligente em todos containers)
    dest_idx, dest_slot = find_container_with_space(pm, base_addr, preferred_container)
    if dest_idx is None:
        print(f"[RUNEMAKER] Todos containers cheios! Nao e possivel desequipar.")
        return None

    # Se nao e o container preferido, loga a mudanca
    if dest_idx != preferred_container:
        print(f"[RUNEMAKER] Container {preferred_container} cheio, usando container {dest_idx}")

    # Envia pacote de movimento
    pos_from = get_inventory_pos(slot_enum)
    pos_to = get_container_pos(dest_idx, dest_slot)
    packet.move_item(pos_from, pos_to, current_id, 1)

    # VALIDACAO com retry e backoff exponencial
    max_attempts = 3
    for attempt in range(max_attempts):
        time.sleep(0.5 + (attempt * 0.3))  # 0.5s, 0.8s, 1.1s

        # Verifica se mao esta vazia ou item mudou
        new_id = get_item_id_in_hand(pm, base_addr, slot_enum)
        if new_id == 0 or new_id != current_id:
            # Sucesso! Item saiu da mao
            return {"item_id": current_id, "container_idx": dest_idx, "slot_idx": dest_slot}

        # Ainda tem o item na mao, tenta novamente
        if attempt < max_attempts - 1:
            print(f"[RUNEMAKER] Unequip nao confirmado, tentativa {attempt+1}/{max_attempts}")
            # Re-envia o pacote
            packet.move_item(pos_from, pos_to, current_id, 1)

    print(f"[RUNEMAKER] Falha ao desequipar item {current_id} apos {max_attempts} tentativas!")
    return None

def reequip_hand(pm, base_addr, item_id, target_slot_enum, max_retries=3, packet=None):
    """
    Re-equipa item na mao COM VALIDACAO de sucesso.

    Args:
        item_id: ID do item a re-equipar
        target_slot_enum: SLOT_LEFT ou SLOT_RIGHT
        max_retries: tentativas maximas
        packet: PacketManager instance

    Returns:
        True se item confirmado na mao, False se falhou
    """
    if not item_id:
        return False

    if packet is None:
        packet = PacketManager(pm, base_addr)

    for attempt in range(max_retries):
        time.sleep(0.3)

        # Encontra item nos containers
        item_data = find_item_in_containers(pm, base_addr, item_id)
        if not item_data:
            if attempt < max_retries - 1:
                print(f"[RUNEMAKER] Item {item_id} nao encontrado, tentativa {attempt+1}/{max_retries}")
            continue

        # Move para mao
        pos_from = get_container_pos(item_data['container_index'], item_data['slot_index'])
        pos_to = get_inventory_pos(target_slot_enum)
        packet.move_item(pos_from, pos_to, item_id, 1)

        # NOVA VALIDACAO: Confirma que item chegou na mao
        time.sleep(0.5)
        hand_id = get_item_id_in_hand(pm, base_addr, target_slot_enum)
        if hand_id == item_id:
            return True  # Sucesso confirmado!

        # Item nao chegou, loga e tenta novamente
        if attempt < max_retries - 1:
            print(f"[RUNEMAKER] Item {item_id} nao confirmado na mao (atual: {hand_id}), tentativa {attempt+1}/{max_retries}")

    print(f"[RUNEMAKER] Falha ao re-equipar item {item_id} apos {max_retries} tentativas!")
    return False

def get_target_id(pm, base_addr):
    try:
        return pm.read_int(base_addr + TARGET_ID_PTR)
    except:
        return 0
    
def runemaker_loop(pm, base_addr, hwnd, check_running=None, config=None, is_safe_callback=None, is_gm_callback=None, log_callback=None, eat_callback=None, status_callback=None):
    """
    Loop principal do runemaker.
    status_callback: função opcional para reportar status ao Status Panel
    """
    get_cfg = make_config_getter(config)

    def set_status(msg):
        """Helper para atualizar status do módulo."""
        if status_callback:
            try:
                status_callback(msg)
            except:
                pass

    def log_msg(text):
        timestamp = time.strftime("%H:%M:%S")
        print(f"[{timestamp}] [RUNEMAKER] {text}")
        if log_callback: log_callback(f"[RUNE] {text}")

    # Variáveis de Estado
    STATE_IDLE = 0
    STATE_FLEEING = 1
    STATE_RETURNING = 2
    STATE_WORKING = 3
    
    current_state = STATE_IDLE
    
    last_log_wait = 0
    return_timer_start = 0
    next_cast_time = 0
    
    # Controle de "Barriga Cheia"
    is_full_lock = False
    full_lock_time = 0
    FULL_COOLDOWN_SECONDS = 60 
    
    # Controle de Combate
    last_combat_time = 0
    COMBAT_COOLDOWN = 7  # Aumentado para 7s: aguarda estabilização do loot (3-5s) + margem de segurança

    # Controle de Logout por Falta de Blanks
    logout_no_blanks_start = None  # Timestamp quando detectou falta de blanks
    logout_no_blanks_pos = None    # Posição quando detectou falta de blanks
    LOGOUT_NO_BLANKS_DELAY = 15    # Segundos para aguardar antes do logout

    log_msg(f"Iniciado (Modo Segurança Avançada).")

    # PacketManager para envio de pacotes
    packet = PacketManager(pm, base_addr)

    while True:
        if check_running and not check_running(): return

        # Configs em Tempo Real
        hotkey_str = get_cfg('hotkey', 'F3')
        vk_hotkey = get_vk_code(hotkey_str)
        mana_req = get_cfg('mana_req', 100)
        return_delay = get_cfg('return_delay', 300)
        work_pos = get_cfg('work_pos', (0,0,0))
        safe_pos = get_cfg('safe_pos', (0,0,0))
        enable_move = get_cfg('enable_movement', False)
        
        # Flag especial vinda do Main (Controla Cool-off)
        can_act = get_cfg('can_perform_actions', True)

        # Checagem de Segurança
        is_safe = is_safe_callback() if is_safe_callback else True
        is_gm = is_gm_callback() if is_gm_callback else False
        
        # ======================================================================
        # PRIORIDADE 1: GM DETECTADO (PÂNICO TOTAL)
        # ======================================================================
        if is_gm:
            # Se for GM, paramos TUDO. Não movemos.
            # O estado de movimento também é ignorado.
            set_status("⚠️ GM detectado - pausado")
            if time.time() - last_log_wait > 5:
                log_msg("👮 GM DETECTADO! Congelando ações...")
                packet.stop()
                last_log_wait = time.time()
            time.sleep(1)
            continue

        # ======================================================================
        # PRIORIDADE 1.5: CANCELAMENTO DE AFK POR EMERGÊNCIA
        # ======================================================================
        # AFK pause é cancelado se fuga for necessária (segurança > humanização)
        if state.is_afk_paused and not is_safe and enable_move:
            log_msg("⚠️ AFK pause cancelado - fuga necessária para segurança!")
            set_status("⚠️ Emergência - cancelando AFK")
            state.set_afk_pause(False)
            # Continua para processar fuga normalmente

        # ======================================================================
        # PRIORIDADE 2: PAUSA AFK (HUMANIZAÇÃO)
        # ======================================================================
        if state.is_afk_paused:
            remaining = state.get_afk_pause_remaining()
            set_status(f"pausado (AFK {remaining:.0f}s)")
            time.sleep(0.5)
            continue

        # ======================================================================
        # PRIORIDADE 3: FUGA (MONSTRO/PK)
        # ======================================================================
        if not is_safe and enable_move:
            if current_state != STATE_FLEEING:
                flee_delay = get_cfg('flee_delay', 0)
                if flee_delay > 0:
                    wait = random.uniform(flee_delay, flee_delay * 1.2)
                    log_msg(f"🚨 PERIGO! Reagindo em {wait:.1f}s...")
                    set_status(f"reagindo em {wait:.1f}s...")
                    time.sleep(wait)

                log_msg("🏃 Fugindo para Safe Spot...")
                current_state = STATE_FLEEING
                state.set_runemaker_fleeing(True)  # Sinaliza que está em fuga

            set_status("fugindo para safe spot...")
            # Movimento para Safe usando A* navigation
            arrived = navigate_to_position(
                pm, base_addr, hwnd, safe_pos,
                check_safety=lambda: not is_safe_callback() if is_safe_callback else True,
                packet=packet,
                clear_obstacles=True,
                log_func=log_msg
            )
            if arrived:
                log_msg("📍 Chegou ao safe spot!")
                state.set_runemaker_fleeing(False)  # Fuga completa - libera alarme
                # Sinaliza que está seguro no safe_pos (permite transição FLEEING → RETURNING)
                state.clear_alarm()
            time.sleep(0.3)
            continue

        # ======================================================================
        # PRIORIDADE 4: RETORNO
        # ======================================================================
        if is_safe and current_state == STATE_FLEEING:
            current_state = STATE_RETURNING
            return_timer_start = time.time() + return_delay
            log_msg(f"🛡️ Seguro. Retornando em {return_delay}s...")

        if current_state == STATE_RETURNING:
            if time.time() < return_timer_start:
                remaining = int(return_timer_start - time.time())
                set_status(f"retornando em {remaining}s...")
                time.sleep(1)
                continue
            else:
                if enable_move:
                    log_msg("🚶 Voltando para o Work Spot...")
                    set_status("voltando ao work spot...")
                    arrived = navigate_to_position(
                        pm, base_addr, hwnd, work_pos,
                        check_safety=lambda: is_safe_callback() if is_safe_callback else True,
                        packet=packet,
                        clear_obstacles=True,
                        log_func=log_msg
                    )
                    if arrived:
                        current_state = STATE_WORKING
                        state.set_runemaker_fleeing(False)  # Fallback: garante que flag está limpo
                        log_msg("📍 Cheguei no trabalho.")
                    else:
                        continue  # Continua andando ate chegar
                else:
                    current_state = STATE_WORKING
                    state.set_runemaker_fleeing(False)  # Fallback: garante que flag está limpo

        # ======================================================================
        # PRIORIDADE 5: MODO DE ESPERA (COOL-OFF / SEGURANÇA GLOBAL)
        # ======================================================================
        # Se 'can_perform_actions' for False, significa que estamos no delay de segurança
        # definido pelo Main (ex: GM sumiu há pouco tempo, ou monstro sumiu e move=off).
        if not can_act:
            if time.time() - last_log_wait > 10:
                log_msg("⏳ Aguardando segurança para retomar ações...")
                last_log_wait = time.time()
            time.sleep(1)
            continue

        # ======================================================================
        # PRIORIDADE 6: TRABALHO (MANA TRAIN / RUNAS / COMIDA)
        # ======================================================================
        
        # 1. Proteção de Combate (integrada com bot_state)
        # Só pausa para combate/loot se cavebot estiver ativo
        # Permite runemaking durante treino (trainer-only mode)
        if state.cavebot_active and (state.is_in_combat or state.has_open_loot):
            time.sleep(0.5); continue

        # Cooldown mais inteligente: aguarda 7s após combate terminar
        # Permite que auto-loot (3-5s) termine completamente
        # Só aplica cooldown se cavebot estiver ativo
        if state.cavebot_active and (time.time() - state.last_combat_time < COMBAT_COOLDOWN):
            time.sleep(0.5); continue

        # 2. Auto Eat
        if get_cfg('auto_eat', False):
            if is_full_lock and (time.time() - full_lock_time > FULL_COOLDOWN_SECONDS):
                is_full_lock = False 
            
            if not is_full_lock:
                check_hunger = get_cfg('check_hunger', lambda: False)
                if check_hunger():
                    try:
                        res = attempt_eat(pm, base_addr, hwnd)
                        if res == "FULL":
                            is_full_lock = True
                            full_lock_time = time.time()
                        elif res:
                            if eat_callback: eat_callback(res)
                    except: pass

        # 3. Mana Train (Prioridade sobre Runas se ativo)
        if get_cfg('mana_train', False):
            try:
                curr_mana = pm.read_int(base_addr + OFFSET_PLAYER_MANA)
                if curr_mana >= mana_req:
                    if next_cast_time == 0:
                        h_min = get_cfg('human_min', 0)
                        h_max = get_cfg('human_max', 0)
                        if h_max > 0:
                            delay = random.uniform(h_min, h_max)
                            next_cast_time = time.time() + delay
                            log_msg(f"⏳ Mana cheia! Aguardando {int(delay)}s (Treino)...")
                            set_status(f"mana train: aguardando {int(delay)}s")
                        else:
                            next_cast_time = time.time()

                    if time.time() >= next_cast_time:
                        log_msg(f"⚡ Mana cheia. Usando {hotkey_str}...")
                        set_status(f"mana train: usando {hotkey_str}")
                        press_hotkey(hwnd, vk_hotkey)
                        next_cast_time = 0
                        time.sleep(2.2)
                    else:
                        # Mostrar countdown em tempo real
                        remaining = int(next_cast_time - time.time())
                        if remaining > 0:
                            set_status(f"mana train: cast em {remaining}s")
                else:
                    # Mostrar mana atual vs requerida
                    set_status(f"mana train: aguardando ({curr_mana}/{mana_req})")
                    next_cast_time = 0
            except: pass

            time.sleep(0.5)
            continue # Pula Runemaker se Mana Train está ativo

        # 4. Fabricação de Runas
        try:
            curr_mana = pm.read_int(base_addr + OFFSET_PLAYER_MANA)
            blank_id = get_cfg('blank_id', 3147)

            # LOGOUT COUNTDOWN: Se já iniciou, continua mesmo sem checar blanks
            # Isso evita spam de DEBUG no terminal
            if logout_no_blanks_start is not None:
                logout_on_no_blanks = get_cfg('logout_on_no_blanks', False)
                if logout_on_no_blanks:
                    current_pos = get_player_pos(pm, base_addr)

                    # Verificar se jogador se moveu
                    if current_pos != logout_no_blanks_pos:
                        log_msg("🚶 Movimento detectado - logout cancelado, aguardando novo ciclo...")
                        logout_no_blanks_start = None
                        logout_no_blanks_pos = None
                    else:
                        # Verificar se passou o tempo de espera
                        elapsed = time.time() - logout_no_blanks_start
                        remaining = LOGOUT_NO_BLANKS_DELAY - elapsed

                        if remaining <= 0:
                            log_msg("🚪 LOGOUT: Sem blanks e parado por 15s - deslogando...")
                            set_status("deslogando...")
                            try:
                                packet.quit_game()
                                time.sleep(2)
                                return
                            except Exception as e:
                                log_msg(f"❌ Erro ao deslogar: {e}")
                        else:
                            set_status(f"sem blanks - logout em {int(remaining)}s")
                            time.sleep(0.5)
                            continue
                else:
                    # Logout desabilitado, reseta estado
                    logout_no_blanks_start = None
                    logout_no_blanks_pos = None

            if curr_mana >= mana_req:
                if next_cast_time == 0:
                    h_min = get_cfg('human_min', 2)
                    h_max = get_cfg('human_max', 10)
                    delay = random.uniform(h_min, h_max)
                    next_cast_time = time.time() + delay
                    log_msg(f"⏳ Mana cheia! Aguardando {int(delay)}s...")

                if time.time() >= next_cast_time:
                    log_msg(f"⚡ Mana ok ({curr_mana}). Fabricando...")
                    set_status("fabricando runa...")
                    state.set_runemaking(True)

                    try:
                        # === CONFIGURAÇÃO DE CICLOS ===
                        hand_mode = get_cfg('hand_mode', 'DIREITA')
                        rune_count = get_cfg('rune_count', 1)  # 1, 2, 3 ou 4 runas

                        # Mapear mão selecionada
                        selected_hand = SLOT_LEFT if hand_mode == "ESQUERDA" else SLOT_RIGHT

                        # Definir ciclos baseado na quantidade
                        # Qtd 1: usa mão selecionada (esquerda ou direita)
                        # Qtd 2: usa ambas as mãos
                        # Qtd 3: ambas + mão selecionada (esquerda ou direita)
                        # Qtd 4: ambas × 2
                        if rune_count == 1:
                            cycles = [[selected_hand]]
                        elif rune_count == 2:
                            cycles = [[SLOT_LEFT, SLOT_RIGHT]]
                        elif rune_count == 3:
                            cycles = [[SLOT_LEFT, SLOT_RIGHT], [selected_hand]]
                        elif rune_count == 4:
                            cycles = [[SLOT_LEFT, SLOT_RIGHT], [SLOT_LEFT, SLOT_RIGHT]]
                        else:
                            cycles = [[selected_hand]]  # fallback

                        # Calcular todas as mãos para unequip inicial (união de todos os ciclos)
                        all_hands_to_unequip = set()
                        for cycle_hands in cycles:
                            all_hands_to_unequip.update(cycle_hands)
                        all_hands_to_unequip = list(all_hands_to_unequip)

                        log_msg(f"Conjurando {rune_count} runa(s) em {len(cycles)} ciclo(s)")

                        # PACKET MUTEX: Wrap entire runemaking cycle (unequip -> blank -> cast -> return -> reequip)
                        with PacketMutex("runemaker"):
                            # STOP: Garante que o personagem pare antes de mover itens
                            packet.stop()
                            if not wait_until_stopped(pm, base_addr, packet=packet, timeout=1.5):
                                log_msg("⚠️ Timeout aguardando parada. Tentando novamente...")
                                state.set_runemaking(False)
                                continue  # Volta ao início do loop
                            time.sleep(0.1)  # Pequena margem adicional

                            # PHASE 1: Unequip ALL hands that will be used in ANY cycle
                            # Executa apenas uma vez no início
                            unequipped_items = {}  # slot_enum → dict com item_id, container_idx, slot_idx
                            phase1_failed = False
                            for slot_enum in all_hands_to_unequip:
                                if is_safe_callback and not is_safe_callback():
                                    phase1_failed = True
                                    break

                                unequip_result = unequip_hand(pm, base_addr, slot_enum, preferred_container=0, packet=packet)
                                if unequip_result is None:
                                    # Mao estava vazia, ok continuar
                                    unequipped_items[slot_enum] = None
                                    log_msg(f"Mao {slot_enum} ja estava vazia")
                                else:
                                    unequipped_items[slot_enum] = unequip_result
                                    log_msg(f"Desarmou mao {slot_enum}: Item {unequip_result['item_id']} -> Container {unequip_result['container_idx']}")

                                time.sleep(1.2)

                            if phase1_failed:
                                log_msg("PHASE 1 interrompida por seguranca")
                                state.set_runemaking(False)
                                continue

                            # === LOOP DE CICLOS ===
                            all_cycles_success = True
                            for cycle_idx, hands_in_cycle in enumerate(cycles):
                                is_last_cycle = (cycle_idx == len(cycles) - 1)
                                cycle_num = cycle_idx + 1
                                total_cycles = len(cycles)

                                if total_cycles > 1:
                                    log_msg(f"--- Ciclo {cycle_num}/{total_cycles} ---")

                                # PHASE 2: Equip blank runes COM VALIDACAO (apenas para mãos deste ciclo)
                                active_runes = []
                                phase2_failed = False

                                for slot_enum in hands_in_cycle:
                                    if is_safe_callback and not is_safe_callback():
                                        phase2_failed = True
                                        break

                                    # Re-busca blank rune (pode ter mudado de posicao)
                                    blank_data = find_item_in_containers(pm, base_addr, blank_id)
                                    if not blank_data:
                                        log_msg(f"Sem blank runes para equipar na mao {slot_enum}")
                                        # Iniciar timer de logout se feature está habilitada
                                        if get_cfg('logout_on_no_blanks', False) and logout_no_blanks_start is None:
                                            logout_no_blanks_start = time.time()
                                            logout_no_blanks_pos = get_player_pos(pm, base_addr)
                                            log_msg(f"⚠️ Sem blanks! Logout em {LOGOUT_NO_BLANKS_DELAY}s se continuar parado...")
                                        phase2_failed = True
                                        break

                                    # Move Blank -> Mao
                                    pos_from = get_container_pos(blank_data['container_index'], blank_data['slot_index'])
                                    pos_to = get_inventory_pos(slot_enum)

                                    # Executa com retry e validacao
                                    def do_equip_blank():
                                        packet.move_item(pos_from, pos_to, blank_id, 1)

                                    equip_success = execute_with_retry(
                                        action_fn=do_equip_blank,
                                        validate_fn=lambda se=slot_enum: verify_blank_equipped(pm, base_addr, se, blank_id),
                                        max_retries=3,
                                        delay=0.6,
                                        description=f"equipar blank na mao {slot_enum}"
                                    )

                                    if not equip_success:
                                        log_msg(f"Falha ao equipar blank na mao {slot_enum}, abortando ciclo")
                                        phase2_failed = True
                                        break

                                    # Adiciona a lista de runes ativas deste ciclo
                                    unequip_data = unequipped_items.get(slot_enum)
                                    restorable_item = unequip_data['item_id'] if unequip_data else None

                                    active_runes.append({
                                        "hand_pos": pos_to,
                                        "origin_idx": blank_data['container_index'],
                                        "slot_enum": slot_enum,
                                        "restorable_item": restorable_item,
                                        "unequip_data": unequip_data  # Guarda info completa
                                    })
                                    log_msg(f"Blank equipada na mao {slot_enum}")
                                    time.sleep(0.8)

                                if phase2_failed:
                                    log_msg("PHASE 2 falhou, tentando restaurar itens...")
                                    # Tenta restaurar itens que foram desequipados
                                    for slot_enum, data in unequipped_items.items():
                                        if data and data.get('item_id'):
                                            reequip_hand(pm, base_addr, data['item_id'], slot_enum, packet=packet)
                                    all_cycles_success = False
                                    break  # Sai do loop de ciclos

                                if active_runes:
                                    # PHASE 3: Cast spell
                                    log_msg(f"Pressionando {hotkey_str}...")
                                    press_hotkey(hwnd, vk_hotkey)
                                    time.sleep(1.2)

                                    # Verifica se runas foram conjuradas (informativo)
                                    for info in active_runes:
                                        if verify_rune_conjured(pm, base_addr, info['slot_enum'], blank_id):
                                            detected_id = get_item_id_in_hand(pm, base_addr, info['slot_enum'])
                                            log_msg(f"Runa conjurada na mao {info['slot_enum']}: ID {detected_id}")
                                        else:
                                            log_msg(f"Runa pode nao ter sido conjurada na mao {info['slot_enum']}")

                                    # PHASE 4: Return ALL runes to backpack COM VALIDACAO
                                    for info in active_runes:
                                        slot_enum = info['slot_enum']

                                        # Identifica o que esta na mao
                                        detected_id = get_item_id_in_hand(pm, base_addr, slot_enum)
                                        rune_id_to_move = detected_id if detected_id > 0 else blank_id

                                        # Busca container com espaco para devolver
                                        dest_idx, dest_slot = find_container_with_space(pm, base_addr, info['origin_idx'])
                                        if dest_idx is None:
                                            log_msg(f"Todos containers cheios! Nao e possivel devolver runa da mao {slot_enum}")
                                            continue

                                        pos_dest = get_container_pos(dest_idx, dest_slot)

                                        # Move runa com retry e validacao
                                        def do_return_rune():
                                            packet.move_item(info['hand_pos'], pos_dest, rune_id_to_move, 1)

                                        return_success = execute_with_retry(
                                            action_fn=do_return_rune,
                                            validate_fn=lambda se=slot_enum: verify_hand_empty(pm, base_addr, se),
                                            max_retries=3,
                                            delay=0.6,
                                            description=f"devolver runa da mao {slot_enum}"
                                        )

                                        if return_success:
                                            log_msg(f"Devolvido: Runa {rune_id_to_move} -> Container {dest_idx}")
                                        else:
                                            log_msg(f"Falha ao devolver runa da mao {slot_enum}")

                                        time.sleep(0.5)

                                # Se não é o último ciclo, delay humanizado antes do próximo
                                if not is_last_cycle:
                                    delay_between = random.uniform(0.5, 1.0)
                                    log_msg(f"Aguardando {delay_between:.1f}s antes do proximo ciclo...")
                                    time.sleep(delay_between)

                            # PHASE 5: Re-equip ALL original items (apenas após último ciclo)
                            # Executa apenas se todos os ciclos foram bem sucedidos
                            if all_cycles_success:
                                # Coleta todos os itens que precisam ser restaurados
                                items_to_restore = [(slot, data) for slot, data in unequipped_items.items()
                                                   if data and data.get('item_id')]
                                if items_to_restore:
                                    log_msg(f"Restaurando {len(items_to_restore)} item(ns) original(is)...")
                                    for slot_enum, data in items_to_restore:
                                        log_msg(f"Tentando re-equipar {data['item_id']} na mao {slot_enum}...")
                                        success = reequip_hand(pm, base_addr, data['item_id'], slot_enum, packet=packet)
                                        if success:
                                            log_msg(f"Item {data['item_id']} re-equipado com sucesso!")
                                        else:
                                            log_msg(f"Falha ao re-equipar {data['item_id']}")
                                        time.sleep(0.5)

                                log_msg(f"Ciclo completo: {rune_count} runa(s) conjurada(s).")
                                # Resetar timer de logout (blanks foram encontradas)
                                logout_no_blanks_start = None
                                logout_no_blanks_pos = None
                            next_cast_time = 0
                    finally:
                        state.set_runemaking(False)
                else:
                    # Countdown em tempo real enquanto aguarda delay
                    remaining = int(next_cast_time - time.time())
                    if remaining > 0:
                        set_status(f"mana cheia, cast em {remaining}s")
            else:
                # Aguardando mana
                set_status(f"aguardando mana ({curr_mana}/{mana_req})")
                next_cast_time = 0

        except Exception as e:
            print(f"Rune Error: {e}")
            state.set_runemaking(False)

        time.sleep(0.5)