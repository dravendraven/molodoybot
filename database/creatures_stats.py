"""
Lightweight creature stats helpers used by the training monitor.
Extend the dictionary below with any additional monsters you hunt.
"""

CREATURE_MAX_HP = {
    "rotworm": 65,
    "minotaur": 55,
    "wasp": 35,
    "wolf": 25,
    "spider": 30,
    "troll": 50,
    "bug": 30,
}


def get_creature_max_hp(name):
    """
    Returns the configured max HP for the creature name, matching case-insensitively.
    Falls back to None when the creature is unknown so the caller can still use
    percentage-based calculations.
    """
    if not name:
        return None

    normalized = name.strip().lower()
    if normalized in CREATURE_MAX_HP:
        return CREATURE_MAX_HP[normalized]

    # Allow partial matches such as "Minotaur Archer" -> "minotaur"
    for creature_name, hp in CREATURE_MAX_HP.items():
        if creature_name in normalized:
            return hp

    return None
