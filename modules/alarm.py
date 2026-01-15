import time
import winsound
from config import *
from core.map_core import get_player_pos
from core.player_core import get_connected_char_name
from core.bot_state import state
from core.config_utils import make_config_getter

# Definição de intervalos de alerta (Fallback caso não esteja no config)
TELEGRAM_INTERVAL_NORMAL = 60
TELEGRAM_INTERVAL_GM = 10

# Offset do ponteiro do console (Baseado no seu input: 0x71DD18 - 0x400000)
OFFSET_CONSOLE_PTR = 0x31DD18


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
    set_safe_state = callbacks.get('set_safe', lambda x: None)
    set_gm_state = callbacks.get('set_gm', lambda x: None)
    send_telegram = callbacks.get('telegram', lambda x: None)
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
    
    last_seen_msg = ""
    last_seen_author = ""
    
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
            # B. VERIFICAÇÃO DE CHAT (DEFAULT)
            # =================================================================
            chat_danger = False
            
            if chat_enabled or chat_gm_enabled:
                author, msg = get_last_chat_entry(pm, base_addr)
                
                # DEBUG: Mostra no terminal o que o bot está lendo
                if debug_mode and (author or msg):
                    print(f"[DEBUG CHAT] Author: '{author}' | Msg: '{msg}'")

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
                list_start = base_addr + TARGET_ID_PTR + REL_FIRST_ID
                my_x, my_y, my_z = get_player_pos(pm, base_addr)

                for i in range(MAX_CREATURES):
                    slot = list_start + (i * STEP_SIZE)
                    try:
                        c_id = pm.read_int(slot)
                        if c_id > 0:
                            name_raw = pm.read_string(slot + OFFSET_NAME, 32)
                            name = name_raw.split('\x00')[0].strip()
                            if name == current_name: continue

                            vis = pm.read_int(slot + OFFSET_VISIBLE)
                            cz = pm.read_int(slot + OFFSET_Z)

                            valid_floor = False
                            if floor_mode == "Padrão": valid_floor = (cz == my_z)
                            elif floor_mode == "Superior (+1)": valid_floor = (cz == my_z or cz == my_z - 1)
                            elif floor_mode == "Inferior (-1)": valid_floor = (cz == my_z or cz == my_z + 1)
                            else: valid_floor = (abs(cz - my_z) <= 1)

                            if vis != 0 and valid_floor:
                                # Detecta GM Visualmente
                                if any(name.startswith(prefix) for prefix in GM_PREFIXES):
                                    visual_danger = True
                                    is_visual_gm = True
                                    visual_danger_name = f"GAMEMASTER {name}"
                                    break

                                # Detecta Monstro/Player
                                is_safe_creature = any(s in name for s in safe_list)
                                if not is_safe_creature:
                                    cx = pm.read_int(slot + OFFSET_X)
                                    cy = pm.read_int(slot + OFFSET_Y)
                                    dist = max(abs(my_x - cx), abs(my_y - cy))

                                    if dist <= alarm_range:
                                        visual_danger = True
                                        visual_danger_name = f"{name} ({dist} sqm)"
                                        break
                    except: continue

            # =================================================================
            # D. CONSOLIDAÇÃO DE ESTADO
            # =================================================================
            final_danger = visual_danger or chat_danger
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
            
            elif not chat_danger:
                # Se visual está limpo E chat está limpo -> Seguro
                set_safe_state(True)
                set_gm_state(False)
                set_status("🛡️ Seguro - Monitorando...")

            time.sleep(0.5)

        except Exception as e:
            print(f"[ALARM ERROR] {e}")
            time.sleep(1)