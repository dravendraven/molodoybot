# database/attack_runes.py
"""
Database de runas de ataque e Virtual Key Codes para o Aimbot.
"""

# Runas de ataque com seus IDs e configuracoes
ATTACK_RUNES = {
    "SD": {
        "id": 3155,        # Sudden Death Rune
        "name": "Sudden Death Rune",
        "range": 4,
        "cooldown": 2.0,   # segundos (exhaust)
    },
    "HMM": {
        "id": 3198,        # Heavy Magic Missile Rune
        "name": "Heavy Magic Missile Rune",
        "range": 4,
        "cooldown": 2.0,
    },
    "GFB": {
        "id": 3191,        # Great Fireball Rune
        "name": "Great Fireball Rune",
        "range": 4,
        "cooldown": 2.0,
        "is_area": True,
    },
    "EXPLO": {
        "id": 3200,        # Explosion Rune
        "name": "Explosion Rune",
        "range": 3,
        "cooldown": 2.0,
        "is_area": True,
    },
    "UH": {
        "id": 3160,        # Ultimate Healing Rune
        "name": "Ultimate Healing Rune",
        "range": 1,
        "cooldown": 1.0,
        "is_healing": True,
    },
    "IH": {
        "id": 3152,        # Intense Healing Rune
        "name": "Intense Healing Rune",
        "range": 1,
        "cooldown": 1.0,
        "is_healing": True,
    },
}

# Virtual Key Codes para hotkeys
# Referencia: https://docs.microsoft.com/en-us/windows/win32/inputdev/virtual-key-codes
VK_CODES = {
    # Teclas de funcao
    "F1": 0x70, "F2": 0x71, "F3": 0x72, "F4": 0x73,
    "F5": 0x74, "F6": 0x75, "F7": 0x76, "F8": 0x77,
    "F9": 0x78, "F10": 0x79, "F11": 0x7A, "F12": 0x7B,
    # Botoes do mouse
    "MOUSE4": 0x05,  # X Button 1 (botao lateral traseiro)
    "MOUSE5": 0x06,  # X Button 2 (botao lateral dianteiro)
    # Teclas numericas
    "0": 0x30, "1": 0x31, "2": 0x32, "3": 0x33, "4": 0x34,
    "5": 0x35, "6": 0x36, "7": 0x37, "8": 0x38, "9": 0x39,
    # Numpad
    "NUMPAD0": 0x60, "NUMPAD1": 0x61, "NUMPAD2": 0x62, "NUMPAD3": 0x63,
    "NUMPAD4": 0x64, "NUMPAD5": 0x65, "NUMPAD6": 0x66, "NUMPAD7": 0x67,
    "NUMPAD8": 0x68, "NUMPAD9": 0x69,
}


def get_rune_info(rune_type: str) -> dict:
    """
    Retorna informacoes de uma runa pelo tipo.

    Args:
        rune_type: Tipo da runa ("SD", "HMM", etc)

    Returns:
        Dict com id, name, range, cooldown, etc
        None se runa nao encontrada
    """
    return ATTACK_RUNES.get(rune_type.upper())


def get_vk_code(key_name: str) -> int:
    """
    Retorna o Virtual Key Code para uma tecla.

    Args:
        key_name: Nome da tecla ("F5", "MOUSE4", etc)

    Returns:
        VK code (int), ou 0x74 (F5) como default
    """
    return VK_CODES.get(key_name.upper(), 0x74)
