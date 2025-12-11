import threading
import time

# O Lock é um objeto nativo do Python para evitar conflito de threads
_mouse_lock = threading.Lock()

def acquire_mouse():
    """
    Tenta pegar o controle do mouse. 
    Se outra thread estiver usando, esta função ESPERA até liberar.
    """
    _mouse_lock.acquire()

def release_mouse():
    """
    Libera o controle do mouse para outras threads usarem.
    """
    _mouse_lock.release()

def is_mouse_busy():
    """Retorna True se o mouse estiver sendo usado por alguém."""
    return _mouse_lock.locked()