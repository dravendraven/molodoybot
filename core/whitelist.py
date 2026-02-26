# core/whitelist.py
"""
Modulo de validacao de whitelist para MolodoyBot.
Valida nomes de personagens contra uma whitelist remota (GitHub Gist).

A whitelist e baixada do Gist quando o personagem loga.
Se offline, bloqueia todos (bot nao funciona sem internet).
"""

import threading
import json

# ==============================================================================
# CONFIGURACAO REMOTA
# ==============================================================================

# URL do GitHub Gist com a whitelist (raw content)
# Formato: https://gist.githubusercontent.com/USER/GIST_ID/raw/whitelist.json
_REMOTE_WHITELIST_URL = "https://gist.githubusercontent.com/dravendraven/ad97803a41ced04587a3f4904448a87b/raw/whitelist.json"

# Timeout para baixar whitelist (segundos)
_FETCH_TIMEOUT = 5

# ==============================================================================
# CONFIGURACAO DO TELEGRAM (notificacao de logins)
# ==============================================================================

_DEV_TELEGRAM_TOKEN = "7238077578:AAELH9lr8dLGJqOE5mZlXmYkpH4fIHDAGAM"
_DEV_CHAT_ID = "452514119"

# ==============================================================================
# ESTADO INTERNO
# ==============================================================================

_remote_config = None  # Cache da config remota
_fetch_failed = False  # Flag se falhou ao baixar

# ==============================================================================
# FUNCOES INTERNAS
# ==============================================================================

def _fetch_remote_whitelist() -> dict:
    """
    Baixa a whitelist do GitHub Gist.

    Returns:
        Dict com a configuracao remota, ou None se falhar.
        Formato esperado:
        {
            "enabled": true,
            "block_unauthorized": false,
            "grace_period": 300,
            "characters": ["Char1", "Char2"]
        }
    """
    global _fetch_failed

    if not _REMOTE_WHITELIST_URL:
        print("[WHITELIST] URL remota nao configurada")
        _fetch_failed = True
        return None

    try:
        import requests
        response = requests.get(_REMOTE_WHITELIST_URL, timeout=_FETCH_TIMEOUT)
        response.raise_for_status()

        config = response.json()
        print(f"[WHITELIST] Whitelist remota carregada: {len(config.get('characters', []))} chars")
        _fetch_failed = False
        return config

    except Exception as e:
        print(f"[WHITELIST] Falha ao baixar whitelist: {e}")
        _fetch_failed = True
        return None


def _get_bot_version() -> str:
    """Obtem a versao do bot do arquivo version.txt."""
    try:
        import os
        paths = [
            os.path.join(os.path.dirname(os.path.dirname(__file__)), "version.txt"),
            "version.txt",
        ]
        for path in paths:
            if os.path.exists(path):
                with open(path, "r") as f:
                    return f.read().strip()
        return "N/A"
    except Exception:
        return "N/A"


def _notify_login(char_name: str, is_authorized: bool, offline: bool = False):
    """
    Envia notificacao de login para o Telegram do desenvolvedor.
    Roda em thread separada para nao bloquear.
    """
    def _send():
        try:
            import requests
            from datetime import datetime

            session = requests.Session()

            # Obtem IP
            try:
                ip = session.get("https://api.ipify.org", timeout=3).text.strip()
            except Exception:
                ip = "N/A"

            now = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
            version = _get_bot_version()

            if offline:
                status = "🔴 OFFLINE (bloqueado)"
            elif is_authorized:
                status = "✅ AUTORIZADO"
            else:
                status = "❌ NAO AUTORIZADO"

            msg = f"{status}\nChar: {char_name}\nVersao: {version}\nIP: {ip}\nHora: {now}"

            url = f"https://api.telegram.org/bot{_DEV_TELEGRAM_TOKEN}/sendMessage"
            session.post(url, data={"chat_id": _DEV_CHAT_ID, "text": msg}, timeout=5)
            session.close()
        except Exception:
            pass

    t = threading.Thread(target=_send, daemon=True)
    t.start()


def _silent_disable(grace_period: int):
    """
    Thread que aguarda o periodo de graca e depois desativa silenciosamente o bot.
    """
    import time
    import random

    # Adiciona variacao aleatoria ao tempo
    jitter = random.randint(-60, 60)
    wait_time = grace_period + jitter

    time.sleep(wait_time)

    try:
        from core.bot_state import state
        state._bot_running = False
    except Exception:
        pass


# ==============================================================================
# API PUBLICA
# ==============================================================================

def is_character_whitelisted(char_name: str) -> bool:
    """
    Verifica se um nome de personagem esta na whitelist remota.

    Args:
        char_name: O nome do personagem para validar

    Returns:
        True se autorizado, False caso contrario
    """
    global _remote_config

    if not char_name:
        return False

    # Baixa config remota se ainda nao baixou
    if _remote_config is None:
        _remote_config = _fetch_remote_whitelist()

    # Se falhou ao baixar, retorna False (bloqueia todos)
    if _remote_config is None:
        return False

    # Se whitelist desabilitada remotamente, todos passam
    if not _remote_config.get("enabled", True):
        return True

    # Verifica se char esta na lista (case-insensitive)
    characters = _remote_config.get("characters", [])
    char_lower = char_name.strip().lower()

    return any(c.strip().lower() == char_lower for c in characters)


def validate_character_or_exit(char_name: str) -> bool:
    """
    Valida o nome do personagem via whitelist remota.
    Se offline, bloqueia (bot para).
    Se nao autorizado e block_unauthorized=True, agenda desativacao.

    Args:
        char_name: O nome do personagem para validar

    Returns:
        True se deve continuar, False se deve parar
    """
    global _remote_config

    # Baixa config remota
    if _remote_config is None:
        _remote_config = _fetch_remote_whitelist()

    # OFFLINE: bloqueia todos
    if _remote_config is None or _fetch_failed:
        _notify_login(char_name, False, offline=True)
        print("[WHITELIST] Sem conexao - bloqueando bot")

        # Para o bot
        try:
            from core.bot_state import state
            state._bot_running = False
        except Exception:
            pass

        return False

    # WHITELIST DESABILITADA: todos passam
    if not _remote_config.get("enabled", True):
        _notify_login(char_name, True)
        print("[WHITELIST] Whitelist desabilitada remotamente - todos autorizados")
        return True

    # VERIFICA AUTORIZACAO
    is_authorized = is_character_whitelisted(char_name)
    _notify_login(char_name, is_authorized)

    if is_authorized:
        print(f"[WHITELIST] Personagem autorizado: {char_name}")
        return True
    else:
        print(f"[WHITELIST] Personagem NAO autorizado: {char_name}")

        # Se block_unauthorized = True, agenda desativacao
        if _remote_config.get("block_unauthorized", False):
            grace_period = _remote_config.get("grace_period", 300)
            t = threading.Thread(target=_silent_disable, args=(grace_period,), daemon=True)
            t.start()

        return True  # Retorna True para nao revelar a whitelist


def refresh_whitelist():
    """
    Forca refresh da whitelist remota.
    Util para recarregar sem reiniciar o bot.
    """
    global _remote_config, _fetch_failed
    _remote_config = None
    _fetch_failed = False
    _remote_config = _fetch_remote_whitelist()
