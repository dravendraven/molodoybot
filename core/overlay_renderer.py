"""
Overlay Renderer - Sistema centralizado para renderização de overlays sobre o jogo.

Uso:
    from core.overlay_renderer import renderer

    # Registrar dados de um módulo
    renderer.register_layer('trainer', [
        {'type': 'creature_info', 'dx': 2, 'dy': -1, 'text': 'vis:1 hp:80% d:3', 'color': '#FF0000'}
    ])

    # Remover layer quando módulo desativa
    renderer.unregister_layer('trainer')
"""

import threading
from typing import Dict, List, Optional, Tuple


class OverlayRenderer:
    """
    Singleton que gerencia layers de overlay de múltiplos módulos.
    Thread-safe para acesso concorrente.
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._init()
        return cls._instance

    def _init(self):
        """Inicialização interna (chamada apenas uma vez)."""
        self._layers: Dict[str, List[dict]] = {}
        self._layer_lock = threading.Lock()
        self._game_view = None
        self._offset = (0, 0)

    def register_layer(self, layer_id: str, data: List[dict]):
        """
        Registra ou atualiza dados de overlay para um layer.

        Args:
            layer_id: Identificador único do módulo (ex: 'trainer', 'fisher')
            data: Lista de dicts com dados do overlay
                  Formato: {'type': str, 'dx': int, 'dy': int, 'text': str, 'color': str, ...}
        """
        with self._layer_lock:
            self._layers[layer_id] = data

    def unregister_layer(self, layer_id: str):
        """Remove um layer do renderer."""
        with self._layer_lock:
            self._layers.pop(layer_id, None)

    def get_all_layers(self) -> Dict[str, List[dict]]:
        """Retorna cópia de todos os layers registrados."""
        with self._layer_lock:
            return {k: list(v) for k, v in self._layers.items()}

    def clear_all(self):
        """Remove todos os layers."""
        with self._layer_lock:
            self._layers.clear()

    def update_game_view(self, gv: dict, offset: Tuple[int, int]):
        """
        Atualiza informações do viewport do jogo.
        Chamado pelo main.py no loop de update do xray.

        Args:
            gv: Dict com 'center' (cx, cy), 'sqm' (pixels por tile), 'rect' (x, y, w, h)
            offset: (offset_x, offset_y) para compensar bordas da janela
        """
        self._game_view = gv
        self._offset = offset

    def relative_to_screen(self, dx: int, dy: int) -> Optional[Tuple[int, int]]:
        """
        Converte coordenadas relativas ao player para pixels na tela.

        Args:
            dx: Distância X relativa ao player (-7 a +7)
            dy: Distância Y relativa ao player (-5 a +5)

        Returns:
            (pixel_x, pixel_y) ou None se game_view não disponível
        """
        if not self._game_view:
            return None

        gv = self._game_view
        cx = int(gv['center'][0] + (dx * gv['sqm']) + self._offset[0])
        cy = int(gv['center'][1] + (dy * gv['sqm']) + self._offset[1])
        return (cx, cy)

    @property
    def is_ready(self) -> bool:
        """Verifica se o renderer tem game_view configurado."""
        return self._game_view is not None


# Singleton global - importar assim: from core.overlay_renderer import renderer
renderer = OverlayRenderer()
