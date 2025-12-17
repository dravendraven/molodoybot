# core/memory_utils.py
"""
Utilitários para leitura segura de memória.

Fornece wrappers thread-safe e com tratamento de erro para operações
comuns de leitura de memória do Tibia.
"""


def safe_read_int(pm, address: int, default: int = 0) -> int:
    """
    Lê um inteiro de forma segura, retornando default em caso de erro.

    Args:
        pm: Instância do Pymem
        address: Endereço de memória absoluto
        default: Valor retornado em caso de falha

    Returns:
        Valor lido ou default se falhar
    """
    try:
        return pm.read_int(address)
    except Exception:
        return default


def safe_read_string(pm, address: int, max_length: int = 32, default: str = "") -> str:
    """
    Lê uma string de forma segura, limpando null bytes.

    Args:
        pm: Instância do Pymem
        address: Endereço de memória absoluto
        max_length: Tamanho máximo da string
        default: Valor retornado em caso de falha

    Returns:
        String lida (sem null bytes) ou default se falhar
    """
    try:
        raw = pm.read_string(address, max_length)
        return raw.split('\x00')[0].strip()
    except Exception:
        return default


def safe_read_float(pm, address: int, default: float = 0.0) -> float:
    """
    Lê um float de forma segura, retornando default em caso de erro.

    Args:
        pm: Instância do Pymem
        address: Endereço de memória absoluto
        default: Valor retornado em caso de falha

    Returns:
        Valor lido ou default se falhar
    """
    try:
        return pm.read_float(address)
    except Exception:
        return default


def safe_read_bytes(pm, address: int, size: int, default: bytes = b'') -> bytes:
    """
    Lê bytes de forma segura, retornando default em caso de erro.

    Args:
        pm: Instância do Pymem
        address: Endereço de memória absoluto
        size: Número de bytes a ler
        default: Valor retornado em caso de falha

    Returns:
        Bytes lidos ou default se falhar
    """
    try:
        return pm.read_bytes(address, size)
    except Exception:
        return default
