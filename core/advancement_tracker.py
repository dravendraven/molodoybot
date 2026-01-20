# core/advancement_tracker.py
"""
Rastreia se o bot está avançando em direção ao waypoint.
Detecta cenários de "andar sem progredir" (ping-pong, círculos, etc.)

Usa duas estratégias:
1. Node-based: Quando há rota global, conta nodes restantes (mais preciso)
2. Distance-based: Fallback para rotas locais (menos preciso, pode dar falso positivo)
"""
import time


class AdvancementTracker:
    """
    Rastreia se o bot está avançando em direção ao waypoint.

    Preferência: nodes > distance
    - Nodes: Conta quantos nodes da rota global foram consumidos
    - Distance: Fallback quando não há rota global
    """

    def __init__(self, window_seconds=3.0, min_advancement_ratio=0.3):
        """
        Args:
            window_seconds: Janela de tempo para análise (default: 3s)
            min_advancement_ratio: Fração mínima do avanço esperado (default: 30%)
        """
        self.window_seconds = window_seconds
        self.min_advancement_ratio = min_advancement_ratio

        # Histórico de nodes restantes (para rota global)
        self.node_history = []  # [(timestamp, nodes_remaining), ...]

        # Histórico de distância (fallback para rota local)
        self.distance_history = []  # [(timestamp, distance_to_wp), ...]

        # Modo atual de tracking
        self.using_nodes = False

    def record_nodes(self, nodes_remaining):
        """
        Registra quantidade de nodes restantes na rota global.
        Método preferido - mais preciso que distância.
        """
        now = time.time()
        self.node_history.append((now, nodes_remaining))
        self.using_nodes = True

        # Limpa entradas antigas
        cutoff = now - self.window_seconds
        self.node_history = [
            (t, n) for t, n in self.node_history if t > cutoff
        ]

    def record_distance(self, distance_to_waypoint):
        """
        Registra distância ao waypoint (fallback quando não há rota global).
        """
        now = time.time()
        self.distance_history.append((now, distance_to_waypoint))

        # Limpa entradas antigas
        cutoff = now - self.window_seconds
        self.distance_history = [
            (t, d) for t, d in self.distance_history if t > cutoff
        ]

    def is_advancing(self, expected_speed_sqm_per_sec=2.0):
        """
        Verifica se estamos avançando.

        Usa nodes se disponível, senão fallback para distância.

        Returns:
            bool: True se avançando normalmente, False se não
        """
        # Preferência: usar nodes se temos dados recentes
        if self.node_history and len(self.node_history) >= 2:
            return self._is_advancing_by_nodes()

        # Fallback: usar distância
        if self.distance_history and len(self.distance_history) >= 2:
            return self._is_advancing_by_distance(expected_speed_sqm_per_sec)

        # Dados insuficientes - assume OK
        return True

    def _is_advancing_by_nodes(self):
        """
        Verifica avanço por consumo de nodes da rota global.
        Mais preciso - funciona mesmo em rotas que contornam obstáculos.
        """
        if len(self.node_history) < 2:
            return True

        oldest_time, oldest_nodes = self.node_history[0]
        newest_time, newest_nodes = self.node_history[-1]

        time_elapsed = newest_time - oldest_time
        if time_elapsed < 1.0:
            return True  # Muito pouco tempo

        # Quantos nodes consumimos? (positivo = avançando)
        nodes_consumed = oldest_nodes - newest_nodes

        # Esperamos consumir ~2-3 nodes por segundo (velocidade normal)
        # Mas ser mais tolerante: apenas verificar se consumimos ALGO
        # Se nodes_consumed <= 0 por window_seconds, estamos parados

        # Critério: consumir pelo menos 1 node na janela de tempo
        # Ou seja, se em 3 segundos não consumimos nenhum node, há problema
        return nodes_consumed >= 1

    def _is_advancing_by_distance(self, expected_speed_sqm_per_sec):
        """
        Verifica avanço por diminuição de distância ao waypoint.
        Fallback - pode dar falso positivo em rotas que contornam obstáculos.
        """
        if len(self.distance_history) < 2:
            return True

        oldest_time, oldest_dist = self.distance_history[0]
        newest_time, newest_dist = self.distance_history[-1]

        time_elapsed = newest_time - oldest_time
        if time_elapsed < 1.0:
            return True

        # Quanto avançamos? (positivo = aproximando do WP)
        actual_advancement = oldest_dist - newest_dist

        # Quanto DEVERIAMOS ter avançado?
        expected_advancement = time_elapsed * expected_speed_sqm_per_sec

        # Se avançamos menos que 30% do esperado → problema
        # Mas para evitar falsos positivos, também aceitar se distância é pequena
        if newest_dist < 3.0:
            return True  # Perto do waypoint, não precisa se preocupar

        return actual_advancement >= (expected_advancement * self.min_advancement_ratio)

    def get_advancement_info(self):
        """
        Retorna informações de debug sobre o avanço.

        Returns:
            dict: {mode, rate, ...}
        """
        info = {
            'mode': 'nodes' if self.using_nodes and self.node_history else 'distance',
            'node_rate': 0.0,
            'distance_rate': 0.0,
        }

        # Taxa de consumo de nodes
        if len(self.node_history) >= 2:
            oldest_time, oldest_nodes = self.node_history[0]
            newest_time, newest_nodes = self.node_history[-1]
            time_elapsed = newest_time - oldest_time
            if time_elapsed > 0.1:
                info['node_rate'] = (oldest_nodes - newest_nodes) / time_elapsed

        # Taxa de aproximação por distância
        if len(self.distance_history) >= 2:
            oldest_time, oldest_dist = self.distance_history[0]
            newest_time, newest_dist = self.distance_history[-1]
            time_elapsed = newest_time - oldest_time
            if time_elapsed > 0.1:
                info['distance_rate'] = (oldest_dist - newest_dist) / time_elapsed

        return info

    def get_advancement_rate(self):
        """
        Retorna taxa de avanço (para compatibilidade).
        Retorna node_rate se usando nodes, senão distance_rate.
        """
        info = self.get_advancement_info()
        if info['mode'] == 'nodes':
            return info['node_rate']
        return info['distance_rate']

    def reset(self):
        """Limpa histórico (chamar ao mudar de waypoint)."""
        self.node_history.clear()
        self.distance_history.clear()
        self.using_nodes = False
