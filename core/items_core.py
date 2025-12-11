from database.items_db import ITEMS

# Constantes de Role (Devem bater com o items_db)
ROLE_WALK  = 0
ROLE_BLOCK = 1
ROLE_STACK = 2
ROLE_MOVE  = 3

def get_item_role(item_id):
    """
    Retorna o papel do item baseado no ID.
    Se não estiver no banco, assume que é caminhável (0).
    """
    return ITEMS.get(item_id, ROLE_WALK)

def is_walkable(item_id):
    """Retorna True se o item for chão, decoração rasteira ou stackável."""
    role = get_item_role(item_id)
    # Stack (Parcel) tecnicamente dá pra andar se não tiver empilhado,
    # mas por segurança inicial vamos considerar apenas WALK como 100% livre.
    return role == ROLE_WALK

def is_blocking(item_id):
    """Retorna True se for parede, árvore, pedra, etc."""
    role = get_item_role(item_id)
    return role == ROLE_BLOCK or role == ROLE_MOVE