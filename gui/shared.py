"""
Variáveis e referências compartilhadas entre componentes GUI.

Este módulo serve como hub central para evitar circular imports.
Widgets e referências são registrados aqui e acessados por outros módulos.
"""

import threading
from typing import Any, Dict, Optional

# Lock para acesso thread-safe
_lock = threading.Lock()

# Referência ao app principal (set por main.py)
app = None

# Dicionário de widgets que threads precisam acessar
_widgets: Dict[str, Any] = {}


def get_widget(name: str) -> Optional[Any]:
    """Obtém referência a um widget pelo nome (thread-safe)."""
    with _lock:
        return _widgets.get(name)


def set_widget(name: str, widget: Any) -> None:
    """Registra um widget pelo nome (thread-safe)."""
    with _lock:
        _widgets[name] = widget


def clear_widgets() -> None:
    """Limpa todas as referências de widgets."""
    with _lock:
        _widgets.clear()
