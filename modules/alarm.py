import time
import winsound
import threading
import win32gui
from config import *
from core.map_core import get_player_pos
from core.player_core import get_connected_char_name, get_player_id
from core.bot_state import state
from core.config_utils import make_config_getter
from core.battlelist import BattleListScanner, SpawnTracker

# Definição de intervalos de alerta (Fallback caso não esteja no config)
TELEGRAM_INTERVAL_NORMAL = 60
TELEGRAM_INTERVAL_GM = 10

# Offset do ponteiro do console (Baseado no seu input: 0x71DD18 - 0x400000)
OFFSET_CONSOLE_PTR = 0x31DD18

# Fila de eventos de chat do sniffer (thread-safe)
_chat_event_queue = []
_chat_event_lock = threading.Lock()
_event_listener_setup = False


def _setup_chat_event_listener():
    """Configura listener para eventos de chat do sniffer."""
    global _event_listener_setup
    if _event_listener_setup:
        return

    try:
        from core.event_bus import EventBus, EVENT_CHAT

        event_bus = EventBus.get_instance()

        def on_chat_event(event):
            """Callback quando sniffer detecta chat."""
            with _chat_event_lock:
                _chat_event_queue.append(event)
                # Limita tamanho da fila
                while len(_chat_event_queue) > 100:
                    _chat_event_queue.pop(0)

        event_bus.subscribe(EVENT_CHAT, on_chat_event)
        _event_listener_setup = True
    except ImportError:
        pass  # Sniffer não disponível


def _get_pending_chat_events():
    """Retorna e limpa eventos de chat pendentes."""
    with _chat_event_lock:
        events = _chat_event_queue.copy()
        _chat_event_queue.clear()
        return events


def get_my_name(pm, base_addr):
    """
    Retorna nome do personagem usando BotState (thread-safe).
    O nome não muda durante a sessão.
    """
    # Usa cache do BotState (thread-safe)
    if not state.char_name:
        name = get_connected_char_name(pm, base_addr)
        if name:
            state.char_name = name
            # Também setar o char_id
            try:
                player_id = get_player_id(pm, base_addr)
                if player_id and player_id > 0:
                    state.char_id = player_id
            except:
                pass
    return state.char_name

def get_last_chat_entry(pm, base_addr):
    """
    Lê a última entrada do canal Default.
    Retorna: (autor_string, mensagem_string)
    """
    try:        
        # TENTATIVA 1: Via Ponteiro (Correção baseada no seu debug)
        # Lê o endereço da estrutura do console primeiro
        console_struct = pm.read_int(base_addr + OFFSET_CONSOLE_PTR)
        if console_struct > 0:
            author_str = pm.read_string(console_struct + 0xF0, 128)
            msg_str = pm.read_string(console_struct + 0x118, 128)
            return author_str, msg_str
    except:
        pass

    try:
        # TENTATIVA 2: Estático (Fallback para config antiga)
        author_str = pm.read_string(base_addr + OFFSET_CONSOLE_AUTHOR, 128)
        msg_str = pm.read_string(base_addr + OFFSET_CONSOLE_MSG, 128)
        return author_str, msg_str
    except:
        return None, None

def alarm_loop(pm, base_addr, check_running, config, callbacks, status_callback=None):

    # --- HELPER: LER CONFIGURAÇÃO EM TEMPO REAL ---
    get_cfg = make_config_getter(config)

    # Recupera callbacks
    set_safe_state = callbacks.get('set_safe', lambda _: None)
    set_gm_state = callbacks.get('set_gm', lambda _: None)
    send_telegram = callbacks.get('telegram', lambda _: None)
    log_msg = callbacks.get('log', print)
    logout_callback = callbacks.get('logout', lambda: None)

    # Helper para atualizar status do alarme na GUI
    def set_status(msg):
        """Helper para atualizar status do alarme na GUI."""
        if status_callback:
            try:
                status_callback(msg)
            except:
                pass

    last_telegram_time = 0
    last_hp_alert = 0

    # Mana GM detection tracking
    last_mana_value = None  # Track raw mana for GM manipulation detection
    last_level_value = None  # Track level to ignore mana gain from level up

    last_seen_msg = ""
    last_seen_author = ""

    # Configura listener de eventos do sniffer
    _setup_chat_event_listener()

    # Spawn Tracker: detecta criaturas sumonadas por GM
    scanner = BattleListScanner(pm, base_addr)
    spawn_tracker = SpawnTracker(suspicious_range=5, floor_change_cooldown=3.0)

    # Movimento inesperado: hwnd para walk-back
    hwnd = win32gui.FindWindow("TibiaClient", None)

    log_msg("🔔 Módulo de Alarme Iniciado.")

    while True:
        if check_running and not check_running(): return

        # 1. Verifica se o Alarme Global está ativado
        enabled = get_cfg('enabled', False)
        if not enabled:
            set_safe_state(True)
            set_gm_state(False)
            set_status("💤 Desativado")
            time.sleep(1)
            continue

        if pm is None:
            set_status("⏳ Aguardando conexão...")
            time.sleep(1)
            continue

        # Lê configs dinâmicas
        safe_list = get_cfg('safe_list', [])
        alarm_range = get_cfg('range', 8)
        floor_mode = get_cfg('floor', "Padrão")

        hp_check_enabled = get_cfg('hp_enabled', False)
        hp_threshold = get_cfg('hp_percent', 50)

        visual_enabled = get_cfg('visual_enabled', True)
        alarm_players = get_cfg('alarm_players', True)
        alarm_creatures = get_cfg('alarm_creatures', True)
        targets_list = get_cfg('targets_list', [])

        chat_enabled = get_cfg('chat_enabled', False)
        chat_gm_enabled = get_cfg('chat_gm', True)
        debug_mode = get_cfg('debug_mode', False)
        logout_enabled = get_cfg('logout_enabled', False)

        try:
            current_name = get_my_name(pm, base_addr)
            
            # =================================================================
            # A. VERIFICAÇÃO DE HP BAIXO
            # =================================================================
            if hp_check_enabled:
                try:
                    curr_hp = pm.read_int(base_addr + OFFSET_PLAYER_HP)
                    max_hp = pm.read_int(base_addr + OFFSET_PLAYER_HP_MAX)

                    if max_hp > 0 and curr_hp > 0:
                        pct = (curr_hp / max_hp) * 100
                        if pct < hp_threshold:
                            # Marca como não-seguro (outros módulos vão reagir)
                            set_safe_state(False)

                            # Limita o alerta sonoro a cada 2 segundos
                            if (time.time() - last_hp_alert) > 2.0:
                                log_msg(f"🩸 ALARME DE VIDA: {pct:.1f}% (Abaixo de {hp_threshold}%)")
                                set_status(f"🩸 HP baixo ({pct:.0f}%)")
                                winsound.Beep(2500, 200)
                                winsound.Beep(2500, 200)
                                last_hp_alert = time.time()
                except: pass

            # =================================================================
            # A2. VERIFICAÇÃO DE MANA MANIPULADA (GM INJECTION)
            # =================================================================
            # GMs testam bots adicionando mana artificial para trigger auto-spells
            # Mana normal sobe de 1 em 1 por tick. Incremento > threshold = GM
            # EXCEÇÃO: Level up dá +5/+15/+30 mana dependendo da vocação
            mana_gm_enabled = get_cfg('mana_gm_enabled', False)

            if mana_gm_enabled:
                try:
                    curr_mana = pm.read_int(base_addr + OFFSET_PLAYER_MANA)
                    curr_level = pm.read_int(base_addr + OFFSET_LEVEL)

                    if last_mana_value is not None and curr_mana > last_mana_value:
                        mana_diff = curr_mana - last_mana_value
                        mana_threshold = get_cfg('mana_gm_threshold', 10)

                        # Ignora se houve level up (level up dá mana: +5/+15/+30)
                        leveled_up = (last_level_value is not None and curr_level > last_level_value)

                        if mana_diff > mana_threshold and not leveled_up:
                            # Mana aumentou mais que o normal SEM level up - possível GM
                            log_msg(f"👮 MANA GM DETECTADA: {last_mana_value} → {curr_mana} (+{mana_diff})")
                            set_status(f"👮 Mana GM! +{mana_diff}")

                            # Ações de segurança
                            set_safe_state(False)
                            set_gm_state(True)
                            winsound.Beep(2500, 1000)

                            if (time.time() - last_telegram_time) > TELEGRAM_INTERVAL_GM:
                                send_telegram(f"👮 MANA GM DETECTADA: +{mana_diff} mana artificial!")
                                last_telegram_time = time.time()

                    last_mana_value = curr_mana
                    last_level_value = curr_level
                except:
                    pass

            # =================================================================
            # B. VERIFICAÇÃO DE CHAT (EVENTOS DO SNIFFER + MEMÓRIA)
            # =================================================================
            chat_danger = False

            if chat_enabled or chat_gm_enabled:
                # 1. Primeiro verifica eventos do sniffer (tempo real, mais confiável)
                chat_events = _get_pending_chat_events()

                for event in chat_events:
                    # Ignora a mim mesmo
                    if current_name and current_name in event.speaker:
                        continue

                    # DEBUG
                    if debug_mode:
                        print(f"[DEBUG CHAT/SNIFFER] Speaker: '{event.speaker}' | Msg: '{event.message}' | GM: {event.is_gm}")

                    # GM detectado via sniffer (verifica prefixo OU tipo de canal)
                    if chat_gm_enabled and event.is_gm:
                        log_msg(f"👮 GM NO CHAT (SNIFFER): {event.speaker}: {event.message}")
                        chat_danger = True
                        set_status(f"👮 GM detectado: {event.speaker}")

                        # Ações Imediatas
                        set_gm_state(True)
                        set_safe_state(False)
                        winsound.Beep(2500, 1000)

                        if (time.time() - last_telegram_time) > TELEGRAM_INTERVAL_GM:
                            send_telegram(f"👮 GM DETECTADO (SNIFFER): {event.speaker}: {event.message}")
                            last_telegram_time = time.time()
                        break  # Já detectou GM, não precisa continuar

                    # Alarme Chat Comum
                    elif chat_enabled and event.speak_type in (0x01, 0x02, 0x03):  # say, whisper, yell
                        log_msg(f"💬 Chat: {event.speaker}: {event.message}")
                        set_status(f"💬 {event.speaker}")
                        winsound.Beep(800, 300)

                # 2. Fallback: leitura de memória (para garantir compatibilidade)
                if not chat_events:
                    author, msg = get_last_chat_entry(pm, base_addr)

                    # DEBUG: Mostra no terminal o que o bot está lendo
                    if debug_mode and (author or msg):
                        print(f"[DEBUG CHAT/MEM] Author: '{author}' | Msg: '{msg}'")

                    # Se mensagem é nova
                    if author and msg and (msg != last_seen_msg or author != last_seen_author):
                        last_seen_msg = msg
                        last_seen_author = author

                        # Ignora a mim mesmo
                        if not (current_name and current_name in author):
                            is_gm_talk = any(prefix in author for prefix in GM_PREFIXES)

                            # 1. Alarme GM no Chat
                            if chat_gm_enabled and is_gm_talk:
                                log_msg(f"👮 GM NO CHAT: {author} {msg}")
                                chat_danger = True
                                set_status(f"👮 GM no chat: {author}")

                                # Ações Imediatas
                                set_gm_state(True)
                                set_safe_state(False)
                                winsound.Beep(2000, 1000)

                                if (time.time() - last_telegram_time) > TELEGRAM_INTERVAL_GM:
                                    send_telegram(f"GM FALOU NO CHAT: {author} {msg}")
                                    last_telegram_time = time.time()

                            # 2. Alarme Chat Comum
                            elif chat_enabled:
                                if "says:" in author or "whispers:" in author or "yells:" in author:
                                    log_msg(f"💬 Chat: {author} {msg}")
                                    set_status(f"💬 {author}")
                                    winsound.Beep(800, 300)

            # =================================================================
            # C. VERIFICAÇÃO VISUAL (CRIATURAS)
            # =================================================================
            visual_danger = False
            visual_danger_name = ""
            is_visual_gm = False

            if visual_enabled:
                my_x, my_y, my_z = get_player_pos(pm, base_addr)
                all_creatures = scanner.scan_all()

                for creature in all_creatures:
                    # Skip NPCs (bit 31 do ID setado) — via Creature model
                    if creature.is_npc:
                        continue

                    name = creature.name
                    if name == current_name:
                        continue

                    if not creature.is_visible:
                        continue

                    cz = creature.position.z
                    valid_floor = False
                    if floor_mode == "Padrão": valid_floor = (cz == my_z)
                    elif floor_mode == "Superior (+1)": valid_floor = (cz == my_z or cz == my_z - 1)
                    elif floor_mode == "Inferior (-1)": valid_floor = (cz == my_z or cz == my_z + 1)
                    else: valid_floor = (abs(cz - my_z) <= 1)

                    if not valid_floor:
                        continue

                    # Detecta GM Visualmente (sempre dispara)
                    if any(name.startswith(prefix) for prefix in GM_PREFIXES):
                        visual_danger = True
                        is_visual_gm = True
                        visual_danger_name = f"GAMEMASTER {name}"
                        break

                    # Ignora se está na safe_list
                    if any(s in name for s in safe_list):
                        continue

                    # Calcula distância
                    dist = max(abs(my_x - creature.position.x), abs(my_y - creature.position.y))
                    if dist > alarm_range:
                        continue

                    # Player vs creature — via Creature model (is_npc already filtered)
                    if creature.is_player:
                        if alarm_players:
                            visual_danger = True
                            visual_danger_name = f"PLAYER: {name} ({dist} sqm)"
                            break
                    else:
                        # Ignora se é alvo do Trainer (você está caçando ela!)
                        is_target = any(t in name for t in targets_list)
                        if is_target:
                            continue

                        if alarm_creatures:
                            visual_danger = True
                            visual_danger_name = f"{name} ({dist} sqm)"
                            break

            # =================================================================
            # C2. DETECÇÃO DE SPAWN SUSPEITO (GM sumonando criaturas)
            # =================================================================
            if visual_enabled:
                suspicious_spawns = spawn_tracker.update(all_creatures, my_x, my_y, my_z, self_id=state.char_id)

                if suspicious_spawns:
                    names = ", ".join(f"{c.name} (dist:{max(abs(my_x - c.position.x), abs(my_y - c.position.y))})" for c in suspicious_spawns)
                    log_msg(f"👮 SPAWN SUSPEITO (possível GM): {names}")
                    set_status(f"👮 Spawn suspeito: {names}")
                    set_safe_state(False)
                    set_gm_state(True)
                    winsound.Beep(2500, 1000)

                    if (time.time() - last_telegram_time) > TELEGRAM_INTERVAL_GM:
                        send_telegram(f"👮 SPAWN SUSPEITO (possível GM): {names}")
                        last_telegram_time = time.time()

                    visual_danger = True
                    is_visual_gm = True

            # =================================================================
            # E. VERIFICAÇÃO DE MOVIMENTO INESPERADO
            # =================================================================
            movement_danger = False
            movement_enabled = get_cfg('movement_enabled', False)
            keep_position = get_cfg('keep_position', False)
            runemaker_return_safe = get_cfg('runemaker_return_safe', False)

            if movement_enabled and not state.cavebot_active:
                # Lê posição (pode já ter sido lida na seção C)
                if not visual_enabled:
                    my_x, my_y, my_z = get_player_pos(pm, base_addr)

                # Posição de origem definida ao ligar o alarme (via switch na GUI)
                origin = state.alarm_origin_pos
                if origin is None:
                    # Fallback: usa posição atual como referência
                    origin = (my_x, my_y, my_z)
                    state.alarm_origin_pos = origin

                ex, ey, ez = origin
                if (my_x, my_y, my_z) != (ex, ey, ez):
                    movement_danger = True
                    dist_moved = max(abs(my_x - ex), abs(my_y - ey))
                    log_msg(f"🚨 MOVIMENTO INESPERADO: ({ex},{ey},{ez}) → ({my_x},{my_y},{my_z}) [{dist_moved} sqm]")
                    set_status(f"🚨 Movimento inesperado! ({dist_moved} sqm)")
                    set_safe_state(False)
                    winsound.Beep(1500, 500)

                    if (time.time() - last_telegram_time) > TELEGRAM_INTERVAL_NORMAL:
                        send_telegram(f"🚨 Movimento inesperado: ({ex},{ey},{ez}) → ({my_x},{my_y},{my_z})")
                        last_telegram_time = time.time()

                    # Manter Posição: retornar ao ponto (só se runemaker return_safe NÃO está ativo)
                    if keep_position and not runemaker_return_safe:
                        try:
                            from modules.runemaker import move_to_coord_hybrid
                            move_to_coord_hybrid(pm, base_addr, hwnd, origin, log_func=log_msg)
                        except Exception as e:
                            log_msg(f"[ALARM] Erro ao retornar posição: {e}")

            # =================================================================
            # D. CONSOLIDAÇÃO DE ESTADO
            # =================================================================
            final_danger = visual_danger or chat_danger or movement_danger
            final_is_gm = is_visual_gm or chat_danger # Se viu ou ouviu GM
            
            if final_danger:
                set_safe_state(False)
                if final_is_gm:
                    set_gm_state(True)
                else:
                    # Alarme não-GM: executa logout imediato se habilitado
                    if logout_enabled:
                        logout_callback()

                # Se detectou visualmente (chat já logou o dele)
                if visual_danger:
                    log_msg(f"⚠️ PERIGO: {visual_danger_name}!")

                    # Atualiza status baseado no tipo de perigo
                    if final_is_gm:
                        set_status(f"👮 GM DETECTADO: {visual_danger_name}")
                    else:
                        set_status(f"⚠️ {visual_danger_name}")

                    freq = 2500 if final_is_gm else 1000
                    winsound.Beep(freq, 500)
                    
                    interval = TELEGRAM_INTERVAL_GM if final_is_gm else TELEGRAM_INTERVAL_NORMAL
                    
                    if (time.time() - last_telegram_time) > interval:
                        prefix = "👮 GM DETECTADO" if final_is_gm else "⚠️ PERIGO"
                        send_telegram(f"{prefix}: {visual_danger_name}!")
                        last_telegram_time = time.time()
            
            elif not chat_danger and not movement_danger:
                # Se visual está limpo E chat está limpo E sem movimento inesperado -> Seguro
                set_safe_state(True)
                set_gm_state(False)

                # Verifica se há cooldown de retomada ativo
                cooldown = state.cooldown_remaining
                if cooldown > 0:
                    set_status(f"⏳ Retomando em {int(cooldown)}s...")
                else:
                    set_status("🛡️ Seguro - Monitorando...")

            time.sleep(0.5)

        except Exception as e:
            print(f"[ALARM ERROR] {e}")
            time.sleep(1)