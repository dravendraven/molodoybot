import json
import time
import os
from config import FISH_RESPAWN_TIME

DB_FILE = "fishing_map.json"

# Estrutura em memória:
# Key: "x,y,z" (string)
# Value: { "is_water": bool, "last_caught": float (timestamp) }
tile_data = {}

def load_db():
    global tile_data
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, 'r') as f:
                tile_data = json.load(f)
            print(f"[DB] Mapa de pesca carregado: {len(tile_data)} tiles conhecidos.")
        except:
            tile_data = {}

def save_db():
    try:
        with open(DB_FILE, 'w') as f:
            json.dump(tile_data, f)
    except Exception as e:
        print(f"[DB] Erro ao salvar: {e}")

# Carrega ao iniciar o módulo
load_db()

def _get_key(x, y, z):
    return f"{x},{y},{z}"

def update_tile_type(x, y, z, is_water):
    key = _get_key(x, y, z)
    if key not in tile_data:
        tile_data[key] = {"is_water": is_water, "last_caught": 0}
        # Salva apenas quando descobre novos tiles para evitar I/O excessivo
        save_db()
    else:
        # Se já existe, só atualiza se mudou status da água
        if tile_data[key]["is_water"] != is_water:
            tile_data[key]["is_water"] = is_water
            save_db()

def mark_fish_caught(x, y, z, custom_timestamp=None):
    """
    Registra que pescamos (ou falhamos) neste tile.
    custom_timestamp: Permite definir um tempo no passado para cooldowns menores (falhas).
    """
    key = _get_key(x, y, z)
    now = time.time()
    
    # Se passamos um tempo customizado (ex: fake time no passado), usamos ele
    ts = custom_timestamp if custom_timestamp is not None else now
    
    if key in tile_data:
        tile_data[key]["last_caught"] = ts
    else:
        tile_data[key] = {"is_water": True, "last_caught": ts}

    save_db()

def is_tile_ready(x, y, z):
    """
    Verifica se o tile é água E se o cooldown já passou.
    Retorna: "READY", "COOLDOWN", "UNKNOWN", "IGNORE"
    """
    key = _get_key(x, y, z)
    
    if key not in tile_data:
        return "UNKNOWN"
    
    data = tile_data[key]
    
    if not data.get("is_water", False):
        return "IGNORE"
    
    last_caught = data.get("last_caught", 0)
    time_passed = time.time() - last_caught
    
    if time_passed >= FISH_RESPAWN_TIME:
        return "READY"
    else:
        return "COOLDOWN"

def get_cooldown_timestamp(x, y, z):
    """
    Retorna o timestamp absoluto de quando o tile estará pronto (liberado).
    Usado pelo Fisher HUD para desenhar o timer regressivo.
    Retorna 0 se estiver pronto ou não for água.
    """
    key = _get_key(x, y, z)
    
    if key not in tile_data:
        return 0
        
    data = tile_data[key]
    
    # Se não é água, não tem cooldown (é ignorado)
    if not data.get("is_water", False):
        return 0

    last_caught = data.get("last_caught", 0)
    
    # Calcula quando libera: Última Pesca + Tempo de Respawn Configurado
    release_time = last_caught + FISH_RESPAWN_TIME
    
    # Se já passou do tempo, retorna 0 (não desenhar timer)
    if time.time() > release_time:
        return 0
        
    return release_time