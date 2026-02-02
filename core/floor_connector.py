"""Gerencia transições entre andares usando floor_transitions.json pré-gerado."""
import json
import os
from collections import defaultdict


class FloorTransition:
    """Representa uma transição entre dois andares."""
    __slots__ = ('x', 'y', 'z_from', 'z_to')

    def __init__(self, x, y, z_from, z_to):
        self.x = x
        self.y = y
        self.z_from = z_from
        self.z_to = z_to

    def __repr__(self):
        return f"Transition({self.x}, {self.y}, Z{self.z_from}->Z{self.z_to})"


class FloorConnector:
    """Carrega transições de floor_transitions.json e provê pathfinding cross-floor."""

    def __init__(self, global_map, transitions_file=None):
        self.global_map = global_map
        # Cache: (z_from, z_to) -> [FloorTransition, ...]
        self._cache = {}

        if transitions_file and os.path.isfile(transitions_file):
            self._load_from_json(transitions_file)

    def _load_from_json(self, filepath):
        """Carrega transições do JSON pré-gerado."""
        with open(filepath, 'r') as f:
            data = json.load(f)

        grouped = defaultdict(list)
        for t in data.get("transitions", []):
            key = (t["z_from"], t["z_to"])
            grouped[key].append(FloorTransition(t["x"], t["y"], t["z_from"], t["z_to"]))

        self._cache = dict(grouped)
        total = sum(len(v) for v in self._cache.values())
        print(f"[FloorConnector] Carregado {total} transicoes de {filepath}")

    def get_transitions(self, z_from, z_to):
        """Retorna lista de transições entre dois andares (adjacentes)."""
        return self._cache.get((z_from, z_to), [])

    def get_transitions_chain(self, z_from, z_to):
        """Retorna lista de listas de transições para ir de z_from a z_to.

        Ex: z_from=8, z_to=10 -> [[trans 8->9], [trans 9->10]]
        Retorna None se algum segmento não tem transições.
        """
        if z_from == z_to:
            return []

        step = 1 if z_to > z_from else -1
        chain = []
        z = z_from
        while z != z_to:
            z_next = z + step
            transitions = self.get_transitions(z, z_next)
            if not transitions:
                return None
            chain.append(transitions)
            z = z_next
        return chain

    def best_transition(self, player_pos, target_z):
        """Encontra a transição mais próxima do player para ir em direção a target_z.

        Retorna FloorTransition ou None.
        """
        px, py, pz = player_pos
        step = 1 if target_z > pz else -1
        next_z = pz + step

        transitions = self.get_transitions(pz, next_z)
        if not transitions:
            return None

        # Escolhe a mais próxima via pathfinding real
        best = None
        best_cost = float('inf')
        for t in transitions:
            path = self.global_map.get_path(player_pos, (t.x, t.y, pz))
            if path and len(path) < best_cost:
                best_cost = len(path)
                best = t

        return best

    def calculate_cross_floor_cost(self, player_pos, target_pos, z_from, z_to, penalty=0):
        """Calcula custo total para ir de player_pos (z_from) até target_pos (z_to).

        Custo = path_to_transition + penalty + path_from_transition_to_target
        Retorna float('inf') se impossível.
        """
        step = 1 if z_to > z_from else -1
        next_z = z_from + step

        transitions = self.get_transitions(z_from, next_z)
        if not transitions:
            return float('inf')

        best_cost = float('inf')
        for t in transitions:
            path_to = self.global_map.get_path(player_pos, (t.x, t.y, z_from))
            if not path_to:
                continue

            if next_z == z_to:
                path_from = self.global_map.get_path((t.x, t.y, z_to), target_pos)
                if not path_from:
                    continue
                total = len(path_to) + penalty + len(path_from)
            else:
                sub_cost = self.calculate_cross_floor_cost(
                    (t.x, t.y, next_z), target_pos, next_z, z_to, penalty
                )
                if sub_cost == float('inf'):
                    continue
                total = len(path_to) + penalty + sub_cost

            if total < best_cost:
                best_cost = total

        return best_cost
