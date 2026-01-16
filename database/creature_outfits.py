# database/creature_outfits.py
"""
Banco de dados de outfits de criaturas humanoides.
Gerado a partir de mon.zip - Tibia 7.72

Estas criaturas usam outfits de player (com cores), o que poderia
causar falsos positivos na detecção de players.

A validação é DUPLA: outfit + nome devem bater.
"""

# Formato: (looktype, head, body, legs, feet) -> "nome da criatura"
HUMANOID_CREATURE_OUTFITS = {
    (137, 113, 120, 95, 115): "amazon",
    (129, 95, 95, 95, 95): "assassin",
    (129, 58, 40, 24, 95): "bandit",
    (131, 95, 95, 95, 95): "black knight",
    (130, 57, 113, 95, 113): "ferumbras",
    (129, 95, 116, 120, 115): "hunter",
    (134, 95, 0, 113, 115): "smuggler",
    (128, 97, 116, 95, 95): "stalker",
    (139, 113, 38, 76, 96): "valkyrie",
    (131, 38, 38, 38, 38): "wild warrior",
}


def get_creature_name_by_outfit(looktype, head, body, legs, feet):
    """
    Retorna o nome da criatura se o outfit bater exatamente.
    Retorna None se não for um outfit conhecido.
    """
    return HUMANOID_CREATURE_OUTFITS.get((looktype, head, body, legs, feet))


def is_humanoid_creature(name, looktype, head, body, legs, feet):
    """
    Verifica se é uma criatura humanoid conhecida.

    Retorna True se: outfit bate E nome bate.
    Retorna False se: outfit não bate OU nome não bate (player disfarçado!).

    Cenários:
    - Criatura "Hunter" com outfit de Hunter → True (é criatura)
    - Player "Fulano" com outfit de Hunter → False (é player disfarçado!)
    - Player "Hunter" com outfit de Hunter → True (edge case - nome igual)
    """
    expected_name = get_creature_name_by_outfit(looktype, head, body, legs, feet)
    if expected_name is None:
        return False  # Outfit desconhecido = não é criatura humanoid conhecida

    # Compara nome (case-insensitive, substring match)
    return expected_name.lower() in name.lower()
