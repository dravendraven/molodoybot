# modules/combat_movement.py
"""
Movimentacao simplificada durante combate.
Duas logicas apenas:
1. Movimento aleatorio (1 criatura) - parecer humano
2. Kiting (3+ criaturas) - sobrevivencia
"""
import random
import time
from typing import Optional, List, Tuple

from config import DEBUG_COMBAT_MOVEMENT


class CombatMover:
    """
    Movimentacao durante combate com duas logicas simples.
    """

    def __init__(self, analyzer):
        """
        Args:
            analyzer: MapAnalyzer para verificar tiles walkable
        """
        self.analyzer = analyzer

        # Timing
        self.last_move_time: float = 0
        self.min_move_interval: float = 1.5  # Segundos entre movimentos

        # Configuracao
        self.random_move_chance: float = 0.1  # 30% chance de mover quando 1 criatura

    def _is_adjacent(self, pos1: Tuple[int, int], pos2: Tuple[int, int]) -> bool:
        """Verifica se dois tiles sao adjacentes (incluindo diagonal)."""
        dx = abs(pos1[0] - pos2[0])
        dy = abs(pos1[1] - pos2[1])
        return dx <= 1 and dy <= 1 and not (dx == 0 and dy == 0)

    def _get_cardinal_tiles(self, pos: Tuple[int, int]) -> List[Tuple[int, int]]:
        """Retorna os 4 tiles nas direcoes cardinais (N, S, E, W).
        Diagonais custam 3x mais, entao evitamos."""
        x, y = pos
        return [
            (x, y - 1),  # Norte
            (x, y + 1),  # Sul
            (x + 1, y),  # Leste
            (x - 1, y),  # Oeste
        ]

    def _get_all_adjacent_tiles(self, pos: Tuple[int, int]) -> List[Tuple[Tuple[int, int], int]]:
        """Retorna todos os 8 tiles adjacentes com seus custos.
        Cardinal = 10, Diagonal = 30 (3x mais caro).

        Returns:
            Lista de ((x, y), custo)
        """
        x, y = pos
        return [
            # Cardinais (custo 10)
            ((x, y - 1), 10),   # Norte
            ((x, y + 1), 10),   # Sul
            ((x + 1, y), 10),   # Leste
            ((x - 1, y), 10),   # Oeste
            # Diagonais (custo 30)
            ((x - 1, y - 1), 30),  # Noroeste
            ((x + 1, y - 1), 30),  # Nordeste
            ((x - 1, y + 1), 30),  # Sudoeste
            ((x + 1, y + 1), 30),  # Sudeste
        ]

    def _is_walkable(self, rel_x: int, rel_y: int) -> bool:
        """Verifica se um tile e walkable."""
        props = self.analyzer.get_tile_properties(rel_x, rel_y)
        return props.get('walkable', False)

    def get_random_move(self, target_rel: Tuple[int, int]) -> Optional[Tuple[int, int]]:
        """
        LOGICA 1: Movimento aleatorio quando ha apenas 1 criatura.

        Encontra tiles que sao:
        - Walkable
        - Adjacentes ao player (0,0)
        - Adjacentes a criatura (target_rel)
        - Diferentes da posicao atual (0,0)

        Retorna um tile aleatorio dentre os validos.

        Args:
            target_rel: Posicao relativa da criatura (ex: (1, 0) = 1 tile a direita)

        Returns:
            (dx, dy) para onde mover, ou None se nao houver opcao
        """
        player_pos = (0, 0)
        target_pos = target_rel

        # Tiles cardinais ao player (evita diagonal que custa 3x)
        player_adjacent = self._get_cardinal_tiles(player_pos)

        valid_tiles = []
        for tile in player_adjacent:
            # Verificar se e walkable
            if not self._is_walkable(tile[0], tile[1]):
                continue

            # Verificar se tambem e adjacente a criatura
            if not self._is_adjacent(tile, target_pos):
                continue

            # Nao pode ser o tile onde a criatura esta
            if tile == target_pos:
                continue

            valid_tiles.append(tile)

        if DEBUG_COMBAT_MOVEMENT:
            print(f"[CombatMover] Random: target={target_rel}, valid_tiles={valid_tiles}")

        if not valid_tiles:
            return None

        # Escolher aleatoriamente
        return random.choice(valid_tiles)

    def get_kiting_move(self,
                        target_rel: Tuple[int, int],
                        other_creatures_rel: List[Tuple[int, int]]) -> Optional[Tuple[int, int]]:
        """
        LOGICA 2: Kiting quando ha 3+ criaturas adjacentes atacando.

        Encontra tile que:
        a. Walkable
        b. Adjacente ao player (0,0) - cardinal (custo 10) ou diagonal (custo 30)
        c. Adjacente a criatura target (manter em melee)
        d. Minimiza criaturas adjacentes

        Prioridade: menos criaturas adjacentes > menor custo de movimento

        Args:
            target_rel: Posicao relativa do alvo atual
            other_creatures_rel: Lista de posicoes relativas das outras criaturas

        Returns:
            (dx, dy) para onde mover, ou None
        """
        player_pos = (0, 0)

        # Todos os 8 tiles adjacentes com custos (cardinal=10, diagonal=30)
        all_adjacent = self._get_all_adjacent_tiles(player_pos)

        # Conta quantas criaturas estao adjacentes ao player atualmente
        current_adjacent_count = len(other_creatures_rel)  # todas estao adjacentes por definicao

        # Lista de (tile, adjacent_count, move_cost) para tiles validos
        tile_scores = []

        for tile, move_cost in all_adjacent:
            # a. Walkable
            if not self._is_walkable(tile[0], tile[1]):
                continue

            # b. Adjacente ao player - ja garantido por all_adjacent

            # c. Adjacente ao target - RELAXADO quando tem 2+ atacantes
            # Com muitos atacantes, priorizar fuga sobre manter adjacencia ao target
            if len(other_creatures_rel) < 2:
                if not self._is_adjacent(tile, target_rel):
                    continue

            # Nao pode ser o tile do target
            if tile == target_rel:
                continue

            # Nao pode ser tile ocupado por outra criatura
            if tile in other_creatures_rel:
                continue

            # d. Contar quantas outras criaturas ficariam adjacentes
            adjacent_count = 0
            for other in other_creatures_rel:
                if self._is_adjacent(tile, other):
                    adjacent_count += 1

            tile_scores.append((tile, adjacent_count, move_cost))

        if DEBUG_COMBAT_MOVEMENT:
            print(f"[CombatMover] Kiting: target={target_rel}, others={other_creatures_rel}, scores={tile_scores}")

        if not tile_scores:
            return None

        # Ordenar por: 1) menos criaturas adjacentes, 2) menor custo de movimento
        tile_scores.sort(key=lambda x: (x[1], x[2]))
        best_tile, best_count, best_cost = tile_scores[0]

        # So mover se for MELHOR que a posicao atual
        # Posicao atual: adjacente a todas as outras criaturas
        if best_count < current_adjacent_count:
            if DEBUG_COMBAT_MOVEMENT:
                cost_type = "cardinal" if best_cost == 10 else "diagonal"
                print(f"[CombatMover] Kiting: melhor={best_tile} ({cost_type}) adj={best_count} vs atual={current_adjacent_count}")
            return best_tile

        if DEBUG_COMBAT_MOVEMENT:
            print(f"[CombatMover] Kiting: sem melhoria (melhor_adj={best_count} >= atual={current_adjacent_count})")

        return None

    def should_random_move(self) -> bool:
        """
        Decide se deve fazer movimento aleatorio.
        Respeita intervalo minimo e chance configurada.
        """
        # Respeitar intervalo
        if time.time() - self.last_move_time < self.min_move_interval:
            return False

        # Chance aleatoria
        return random.random() < self.random_move_chance

    def should_kite(self, total_adjacent_attacking: int) -> bool:
        """
        Decide se deve fazer kiting.
        Ativa quando 3+ criaturas adjacentes estao atacando (incluindo target).

        Args:
            total_adjacent_attacking: Total de criaturas adjacentes atacando o player
                                      (inclui o target atual se ele estiver atacando)
        """
        # Respeitar intervalo
        if time.time() - self.last_move_time < self.min_move_interval:
            return False

        return total_adjacent_attacking >= 3

    def execute_move(self):
        """Registra que um movimento foi executado."""
        self.last_move_time = time.time()
