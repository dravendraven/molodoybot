# Tibia 7.72 Rune IDs
# Extraidos de objects.srv - items com flag "Rune"

BLANK_RUNE_ID = 3147

# Spell Runes (runas conjuradas) - IDs 3148-3203
SPELL_RUNE_IDS = set(range(3148, 3204))


def is_blank_rune(item_id):
    """Verifica se o item ID e uma blank rune."""
    return item_id == BLANK_RUNE_ID


def is_conjured_rune(item_id):
    """Verifica se o item ID e uma runa conjurada (spell rune)."""
    return item_id in SPELL_RUNE_IDS


def is_any_rune(item_id):
    """Verifica se o item ID e qualquer tipo de runa (blank ou conjurada)."""
    return item_id == BLANK_RUNE_ID or item_id in SPELL_RUNE_IDS
