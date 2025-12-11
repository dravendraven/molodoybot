# Arquivo gerado automaticamente do objects.srv
# ID: {'name': Nome, 'regen': Segundos de Regen, 'weight': Peso em Oz}
FOODS = {
    3250: {'name': 'the carrot of doom', 'regen': 96, 'weight': 1.6},
    3577: {'name': 'meat', 'regen': 180, 'weight': 13.0},
    3578: {'name': 'a fish', 'regen': 144, 'weight': 5.2},
    3579: {'name': 'salmon', 'regen': 120, 'weight': 3.2},
    3580: {'name': 'a fish', 'regen': 204, 'weight': 8.3},
    3581: {'name': 'shrimp', 'regen': 48, 'weight': 0.5},
    3582: {'name': 'ham', 'regen': 360, 'weight': 20.0},
    3583: {'name': 'dragon ham', 'regen': 720, 'weight': 30.0},
    3584: {'name': 'a pear', 'regen': 60, 'weight': 1.4},
    3585: {'name': 'a red apple', 'regen': 72, 'weight': 1.5},
    3586: {'name': 'an orange', 'regen': 156, 'weight': 1.1},
    3587: {'name': 'a banana', 'regen': 96, 'weight': 1.8},
    3588: {'name': 'a blueberry', 'regen': 12, 'weight': 0.2},
    3589: {'name': 'a coconut', 'regen': 216, 'weight': 4.8},
    3590: {'name': 'a cherry', 'regen': 12, 'weight': 0.2},
    3591: {'name': 'a strawberry', 'regen': 24, 'weight': 0.2},
    3592: {'name': 'grapes', 'regen': 108, 'weight': 2.5},
    3593: {'name': 'a melon', 'regen': 240, 'weight': 9.5},
    3594: {'name': 'a pumpkin', 'regen': 204, 'weight': 13.5},
    3595: {'name': 'a carrot', 'regen': 96, 'weight': 1.6},
    3596: {'name': 'a tomato', 'regen': 72, 'weight': 1.0},
    3597: {'name': 'a corncob', 'regen': 108, 'weight': 3.5},
    3598: {'name': 'a cookie', 'regen': 24, 'weight': 0.1},
    3599: {'name': 'a candy cane', 'regen': 24, 'weight': 0.5},
    3600: {'name': 'a bread', 'regen': 120, 'weight': 5.0},
    3601: {'name': 'a roll', 'regen': 36, 'weight': 1.0},
    3602: {'name': 'a brown bread', 'regen': 96, 'weight': 4.0},
    3606: {'name': 'an egg', 'regen': 72, 'weight': 0.3},
    3607: {'name': 'cheese', 'regen': 108, 'weight': 4.0},
    3723: {'name': 'a white mushroom', 'regen': 108, 'weight': 0.4},
    3724: {'name': 'a red mushroom', 'regen': 48, 'weight': 0.5},
    3725: {'name': 'a brown mushroom', 'regen': 264, 'weight': 0.2},
    3726: {'name': 'an orange mushroom', 'regen': 360, 'weight': 0.3},
    3727: {'name': 'a wood mushroom', 'regen': 108, 'weight': 0.3},
    3728: {'name': 'a dark mushroom', 'regen': 72, 'weight': 0.1},
    3729: {'name': 'some mushrooms', 'regen': 144, 'weight': 0.1},
    3730: {'name': 'some mushrooms', 'regen': 36, 'weight': 0.1},
    3731: {'name': 'a fire mushroom', 'regen': 432, 'weight': 0.1},
    3732: {'name': 'a green mushroom', 'regen': 60, 'weight': 0.1},
}

# --- NOVAS FUNÇÕES AUXILIARES ---

def get_food_ids():
    """Retorna uma lista contendo todos os IDs de comida conhecidos."""
    return list(FOODS.keys())

def get_food_info(item_id):
    """Retorna o dicionário de info da comida ou None se não existir."""
    return FOODS.get(item_id, None)

def get_regen_time(item_id):
    """Retorna apenas o tempo de regen. Útil para o Tracker."""
    data = FOODS.get(item_id)
    if data:
        return data.get('regen', 0)
    return 0

def get_food_name(item_id):
    """Retorna o nome da comida."""
    data = FOODS.get(item_id)
    if data:
        return data.get('name', 'Unknown Food')
    return "Unknown"