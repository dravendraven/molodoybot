# food_tracker.py (Versão Wrapper)
import foods_db

def get_food_regen_time(item_id):
    """Wrapper para manter compatibilidade com códigos antigos."""
    return foods_db.get_regen_time(item_id)