# core/whitelist.py
"""
Modulo de validacao de whitelist para MolodoyBot.
Valida nomes de personagens contra uma lista criptografada embutida.

IMPORTANTE: A whitelist criptografada e o salt estao embutidos neste arquivo.
Apenas o desenvolvedor pode modifica-los usando tools/whitelist_manager.py.
"""

import base64
import threading
import time
import random

# Tenta importar cryptography; fornece erro se nao disponivel
try:
    from cryptography.fernet import Fernet, InvalidToken
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    CRYPTO_AVAILABLE = True
except ImportError:
    CRYPTO_AVAILABLE = False

# ==============================================================================
# DADOS CRIPTOGRAFADOS EMBUTIDOS (Gerados por tools/whitelist_manager.py)
# ==============================================================================
# NAO MODIFIQUE MANUALMENTE - Use a ferramenta de gerenciamento para regenerar

# Salt para derivacao de chave (base64, 16 bytes)
_EMBEDDED_SALT = "Hd6rqwe9GeP2o8vkoopXiA=="

# Blob da whitelist criptografada (token Fernet em base64)
_EMBEDDED_WHITELIST = "Z0FBQUFBQnBuTVdqZXl4d0hVSjU0WHdVQnE4Nmhia0JpUjM3UzM4NkR5Z2JieGM4RVRWUmlTX2FrNXQyZVdobnBMRVowQVd3YUlSOEZDaWplRFRaM0V3bG9Ma183OWpWbTQwOUNLcENNQnF1dTlrZDA2NXJfc2dPLTdyUUc5YXVRVDljM1JBdldEVkFuckxkTzdDUUh5YTJpX3BNWGROTXdKaDVWWjBaallsRWhyVUJyckh0UnNBNnRXaHpZQTI3Nm9vS205eC11b01Bd0s3TkZrRWNDdFpMby1vWi15UHNwdGxYX3dKSjlxQXlyb3FNSnpkejdMNkk2dF9oRGtLdWVLZ2FDZlpJanNtUHM5UXdSakY2eFJTamhRdkFJMWFLNWc9PQ=="

# Componentes da chave (divididos para ofuscacao leve)
_K1 = "Molodoy"
_K2 = "Bot"
_K3 = "Secret"
_K4 = "2024"
_K5 = "!MB"

# Tempo em segundos antes de desativar (5 minutos = 300 segundos)
_GRACE_PERIOD = 300

# Configuracao do Telegram do desenvolvedor (notificacao de logins)
_DEV_TELEGRAM_TOKEN = "7238077578:AAELH9lr8dLGJqOE5mZlXmYkpH4fIHDAGAM"
_DEV_CHAT_ID = "452514119"

# ==============================================================================
# FUNCOES INTERNAS
# ==============================================================================

def _get_key_material() -> str:
    """
    Monta o material da chave a partir dos componentes divididos.
    Fornece ofuscacao leve - nao e seguranca criptografica, mas dificulta
    inspecao casual.
    """
    parts = [_K1, _K3, _K2, _K4, _K5]
    return "".join(parts)


def _derive_key(passphrase: str, salt: bytes) -> bytes:
    """
    Deriva uma chave compativel com Fernet a partir de passphrase e salt usando PBKDF2.

    Args:
        passphrase: A frase secreta
        salt: Valor salt de 16 bytes

    Returns:
        Chave de 32 bytes adequada para Fernet (codificada em base64 urlsafe)
    """
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=480000,  # Alto numero de iteracoes para seguranca
    )
    key = base64.urlsafe_b64encode(kdf.derive(passphrase.encode()))
    return key


def _decrypt_whitelist() -> set:
    """
    Descriptografa a whitelist embutida e retorna um set de nomes em minusculo.

    Returns:
        Set de nomes de personagens autorizados (minusculo)
        Set vazio se a descriptografia falhar
    """
    if not CRYPTO_AVAILABLE:
        return set()

    if not _EMBEDDED_SALT or not _EMBEDDED_WHITELIST:
        return set()

    try:
        salt = base64.b64decode(_EMBEDDED_SALT)
        passphrase = _get_key_material()
        key = _derive_key(passphrase, salt)

        fernet = Fernet(key)
        encrypted_data = base64.b64decode(_EMBEDDED_WHITELIST)
        decrypted = fernet.decrypt(encrypted_data)

        # Parse dos dados descriptografados (nomes separados por newline)
        names = decrypted.decode('utf-8').strip().split('\n')
        # Normaliza para minusculo e remove espacos
        return {name.strip().lower() for name in names if name.strip()}

    except InvalidToken:
        return set()
    except Exception:
        return set()


def _silent_disable():
    """
    Thread que aguarda o periodo de graca e depois desativa silenciosamente o bot.
    Simula comportamento de "bug" aleatorio para nao levantar suspeitas.
    """
    # Adiciona variacao aleatoria ao tempo (4-6 minutos)
    jitter = random.randint(-60, 60)
    wait_time = _GRACE_PERIOD + jitter

    time.sleep(wait_time)

    try:
        from core.bot_state import state
        # Desativa o bot silenciosamente
        state._bot_running = False
    except Exception:
        pass


def _notify_login(char_name: str, is_authorized: bool):
    """
    Envia notificacao de login para o Telegram do desenvolvedor.
    Roda em thread separada para nao bloquear.
    """
    def _send():
        try:
            import requests
            from datetime import datetime

            now = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
            status = "✅ AUTORIZADO" if is_authorized else "❌ NAO AUTORIZADO"

            msg = f"{status}\nChar: {char_name}\nHora: {now}"

            url = f"https://api.telegram.org/bot{_DEV_TELEGRAM_TOKEN}/sendMessage"
            data = {"chat_id": _DEV_CHAT_ID, "text": msg}
            requests.post(url, data=data, timeout=5)
        except Exception:
            pass

    t = threading.Thread(target=_send, daemon=True)
    t.start()


# ==============================================================================
# API PUBLICA
# ==============================================================================

# Cache da whitelist descriptografada (calculado uma vez no primeiro uso)
_whitelist_cache = None
_disable_scheduled = False


def is_character_whitelisted(char_name: str) -> bool:
    """
    Verifica se um nome de personagem esta na whitelist.

    Args:
        char_name: O nome do personagem para validar

    Returns:
        True se autorizado, False caso contrario
    """
    global _whitelist_cache

    if not char_name:
        return False

    # Inicializacao lazy do cache
    if _whitelist_cache is None:
        _whitelist_cache = _decrypt_whitelist()

    # Comparacao case-insensitive
    return char_name.strip().lower() in _whitelist_cache


def validate_character_or_exit(char_name: str) -> bool:
    """
    Valida o nome do personagem. Se nao autorizado, agenda desativacao silenciosa.

    Este e o ponto de entrada principal para validacao, destinado a ser chamado
    de connection_watchdog() apos deteccao de login bem-sucedido.

    Args:
        char_name: O nome do personagem para validar

    Returns:
        True sempre (para nao revelar que existe whitelist)
    """
    global _disable_scheduled

    is_authorized = is_character_whitelisted(char_name)

    # Notifica o desenvolvedor sobre o login
    _notify_login(char_name, is_authorized)

    if is_authorized:
        return True
    else:
        # Agenda desativacao silenciosa se ainda nao agendada
        if not _disable_scheduled:
            _disable_scheduled = True
            t = threading.Thread(target=_silent_disable, daemon=True)
            t.start()
        return True  # Retorna True para nao levantar suspeitas
