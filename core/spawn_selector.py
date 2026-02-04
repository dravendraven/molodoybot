import time
from config import DEBUG_AUTO_EXPLORE


def _make_key(spawn):
    return f"{spawn.cx}_{spawn.cy}_{spawn.cz}"


def _short_monsters(spawn):
    """Helper: retorna nomes de monstros abreviados para log."""
    names = sorted(spawn.monster_names())
    return ", ".join(names[:2]) + ("..." if len(names) > 2 else "")


class SpawnSelector:
    """Seleciona o próximo spawn point usando grafo pré-computado de custos A*."""

    def __init__(self, spawns, global_map, floor_connector=None, target_monsters=None,
                 revisit_cooldown=120, search_radius=50, max_floors=0, spawn_graph=None):
        self.all_spawns = spawns
        self.global_map = global_map
        self.floor_connector = floor_connector
        self.target_monsters = [m.lower().strip() for m in (target_monsters or []) if m.strip()]
        self.revisit_cooldown = revisit_cooldown
        self.search_radius = search_radius
        self.max_floors = max_floors
        self.active_spawns = []
        self._initialized = False
        self._last_z = None

        # Grafo pré-computado
        self.spawn_graph = spawn_graph
        self._spawn_by_key = {_make_key(s): s for s in spawns}
        self._current_spawn_key = None
        self._needs_initial_walk = True
        self._initial_spawn = None

    def initialize(self, player_pos):
        """Filtra spawns por z/raio/monstro e verifica walkable target. Sem A*."""
        px, py, pz = player_pos
        self.active_spawns = []
        self._last_z = pz
        self._initialized = True

        for s in self.all_spawns:
            if abs(s.cz - pz) > self.max_floors:
                continue
            if abs(s.cx - px) + abs(s.cy - py) > self.search_radius:
                continue
            if self.target_monsters:
                if not s.monster_names().intersection(self.target_monsters):
                    continue
            target = s.nearest_walkable_target(self.global_map)
            if not target:
                continue
            self.active_spawns.append(s)

        # Determinar spawn mais próximo do player como ponto de partida no grafo
        self._current_spawn_key = self._find_nearest_spawn_key(px, py, pz)
        self._needs_initial_walk = True
        self._initial_spawn = self._spawn_by_key.get(self._current_spawn_key) if self._current_spawn_key else None

        if DEBUG_AUTO_EXPLORE:
            floors = {}
            for s in self.active_spawns:
                floors.setdefault(s.cz, []).append(s)
            print(f"[SpawnSelector] Inicializado: {len(self.active_spawns)} spawns ativos de {len(self.all_spawns)} total")
            for z in sorted(floors):
                print(f"[SpawnSelector]   Z={z}: {len(floors[z])} spawns")
            print(f"[SpawnSelector]   Origem no grafo: {self._current_spawn_key}")
            if self.spawn_graph:
                edges = self.spawn_graph.get("edges", {})
                n_edges = len(edges.get(self._current_spawn_key, []))
                print(f"[SpawnSelector]   Edges da origem: {n_edges}")

        return len(self.active_spawns)

    def select_next(self, player_pos, visible_players=None):
        """Seleciona próximo spawn usando grafo pré-computado. Retorna SpawnArea ou None."""
        px, py, pz = player_pos
        now = time.time()
        visible_players = visible_players or []

        # Primeira execução: ir até o spawn mais próximo antes de usar o grafo
        if self._needs_initial_walk and self._initial_spawn:
            # Verificar se initial_spawn está em cooldown (marcado como inalcançável)
            if now - self._initial_spawn.last_visited < self.revisit_cooldown:
                if DEBUG_AUTO_EXPLORE:
                    print(f"[SpawnSelector] INITIAL: Spawn inicial em cooldown, desativando modo INITIAL")
                self._needs_initial_walk = False
                # Continuar para lógica normal do grafo/fallback
            else:
                if DEBUG_AUTO_EXPLORE:
                    print(f"[SpawnSelector] INITIAL: Indo até spawn mais próximo: {_make_key(self._initial_spawn)} [{_short_monsters(self._initial_spawn)}]")
                return self._initial_spawn

        # Se temos grafo, usar edges pré-computados
        if self.spawn_graph and self._current_spawn_key:
            result = self._select_from_graph(px, py, pz, now, visible_players)
            if result:
                return result

        # Fallback: considera todos os spawns ativos
        return self._select_fallback(px, py, pz, now, visible_players, player_pos)

    def _select_from_graph(self, px, py, pz, now, visible_players):
        """Seleção via grafo pré-computado — O(n) lookup, sem A*."""
        edges = self.spawn_graph.get("edges", {})
        neighbors = edges.get(self._current_spawn_key, [])

        if DEBUG_AUTO_EXPLORE:
            print(f"[SpawnSelector] GRAPH: Origem={self._current_spawn_key} ({len(neighbors)} vizinhos)")

        # Se spawn atual não tem edges no grafo, reposicionar
        if not neighbors:
            new_key = self._find_nearest_spawn_key_with_edges(px, py, pz)
            if new_key:
                self._current_spawn_key = new_key
                neighbors = edges.get(new_key, [])
                if DEBUG_AUTO_EXPLORE:
                    print(f"[SpawnSelector] GRAPH: Sem edges, reposicionou para {new_key} ({len(neighbors)} vizinhos)")
            if not neighbors:
                if DEBUG_AUTO_EXPLORE:
                    print(f"[SpawnSelector] GRAPH: Sem vizinhos, usando fallback")
                return self._select_fallback(px, py, pz, now, visible_players, (px, py, pz))

        # Construir set de keys ativos para filtrar
        active_keys = {_make_key(s) for s in self.active_spawns}

        candidates = []
        if DEBUG_AUTO_EXPLORE:
            print(f"[SpawnSelector] GRAPH: Avaliando vizinhos:")
        for edge in neighbors:
            to_key = edge["to"]
            spawn = self._spawn_by_key.get(to_key)
            if not spawn:
                continue

            # Coletar motivo de rejeição
            reason = None
            if to_key not in active_keys:
                reason = "inativo"
            elif now - spawn.last_visited < self.revisit_cooldown:
                cd_left = self.revisit_cooldown - (now - spawn.last_visited)
                reason = f"cooldown ({cd_left:.0f}s)"
            elif spawn.cz == pz and self.is_occupied_by_closer_player(spawn, px, py, visible_players):
                reason = "ocupado por player"

            effective_cost = edge["cost"]

            if DEBUG_AUTO_EXPLORE:
                monsters = _short_monsters(spawn)
                status = f"SKIP ({reason})" if reason else f"OK custo={effective_cost}"
                floor_tag = f" [Z={spawn.cz}]" if spawn.cz != pz else ""
                print(f"[SpawnSelector]   → {to_key} [{monsters}]{floor_tag}: {status}")

            if reason:
                continue
            candidates.append((effective_cost, spawn))

        if not candidates:
            if DEBUG_AUTO_EXPLORE:
                print(f"[SpawnSelector] GRAPH: Nenhum candidato! Resetando cooldowns...")
            # Reset cooldowns exceto o spawn atual (evita ping-pong)
            any_reset = False
            for s in self.active_spawns:
                if s.last_visited > 0 and _make_key(s) != self._current_spawn_key:
                    s.last_visited = 0
                    any_reset = True
            if any_reset:
                return self._select_from_graph(px, py, pz, time.time(), visible_players)
            return None

        candidates.sort(key=lambda x: x[0])

        if DEBUG_AUTO_EXPLORE:
            winner_cost, winner = candidates[0]
            print(f"[SpawnSelector] GRAPH: Selecionado: {_make_key(winner)} [{_short_monsters(winner)}] custo={winner_cost} (de {len(candidates)} candidatos)")

        return candidates[0][1]

    def _select_fallback(self, px, py, pz, now, visible_players, player_pos):
        """Método original sem grafo — Manhattan + top 3 reachability."""
        if DEBUG_AUTO_EXPLORE:
            print(f"[SpawnSelector] FALLBACK: Avaliando {len(self.active_spawns)} spawns ativos")

        candidates = []
        for s in self.active_spawns:
            reason = None
            if now - s.last_visited < self.revisit_cooldown:
                cd_left = self.revisit_cooldown - (now - s.last_visited)
                reason = f"cooldown ({cd_left:.0f}s)"
            elif s.cz == pz and self.is_occupied_by_closer_player(s, px, py, visible_players):
                reason = "ocupado por player"

            if DEBUG_AUTO_EXPLORE and reason:
                print(f"[SpawnSelector]   SKIP {_make_key(s)} [{_short_monsters(s)}]: {reason}")

            if reason:
                continue
            cost = s.distance_to(px, py)
            candidates.append((cost, id(s), s))

        if not candidates:
            if DEBUG_AUTO_EXPLORE:
                print(f"[SpawnSelector] FALLBACK: Nenhum candidato! Resetando cooldowns...")
            any_reset = False
            for s in self.active_spawns:
                if s.last_visited > 0 and _make_key(s) != self._current_spawn_key:
                    s.last_visited = 0
                    any_reset = True
            if any_reset:
                return self._select_fallback(px, py, pz, time.time(), visible_players, player_pos)
            return None

        candidates.sort(key=lambda x: x[0])

        if DEBUG_AUTO_EXPLORE:
            print(f"[SpawnSelector] FALLBACK: {len(candidates)} candidatos (top 3 por custo):")
            for cost, _, s in candidates[:5]:
                floor_tag = f" [Z={s.cz}]" if s.cz != pz else ""
                print(f"[SpawnSelector]   → {_make_key(s)} [{_short_monsters(s)}]{floor_tag} custo={cost:.0f}")

        for _, _, s in candidates[:3]:
            target = s.nearest_walkable_target(self.global_map)
            if not target:
                if DEBUG_AUTO_EXPLORE:
                    print(f"[SpawnSelector]   SKIP {_make_key(s)}: sem tile walkable")
                continue
            if s.cz == pz:
                path = self.global_map.get_path(player_pos, target)
                if path:
                    if DEBUG_AUTO_EXPLORE:
                        print(f"[SpawnSelector] FALLBACK: Selecionado: {_make_key(s)} [{_short_monsters(s)}] (rota OK, {len(path)} tiles)")
                    return s
                else:
                    if DEBUG_AUTO_EXPLORE:
                        print(f"[SpawnSelector]   SKIP {_make_key(s)}: sem rota A*")
            else:
                if DEBUG_AUTO_EXPLORE:
                    print(f"[SpawnSelector] FALLBACK: Selecionado: {_make_key(s)} [{_short_monsters(s)}] (cross-floor, sem A*)")
                return s

        for _, _, s in candidates[3:]:
            if s.cz != pz:
                if DEBUG_AUTO_EXPLORE:
                    print(f"[SpawnSelector] FALLBACK: Selecionado (overflow): {_make_key(s)} [{_short_monsters(s)}] (cross-floor)")
                return s

        if DEBUG_AUTO_EXPLORE:
            print(f"[SpawnSelector] FALLBACK: Nenhum spawn acessivel!")
        return None

    def mark_visited(self, spawn):
        """Marca spawn como visitado e atualiza posição no grafo."""
        spawn.last_visited = time.time()
        key = _make_key(spawn)
        if self._needs_initial_walk and self._initial_spawn and key == _make_key(self._initial_spawn):
            self._needs_initial_walk = False
            if DEBUG_AUTO_EXPLORE:
                print(f"[SpawnSelector] INITIAL: Chegou ao spawn inicial, ativando lógica de grafo")
        old_key = self._current_spawn_key
        if self.spawn_graph and key in self.spawn_graph.get("edges", {}):
            self._current_spawn_key = key
        if DEBUG_AUTO_EXPLORE:
            print(f"[SpawnSelector] Visitado: {key} [{_short_monsters(spawn)}] (origem: {old_key} → {self._current_spawn_key})")

    def skip_spawn(self, spawn, reason="", player_pos=None):
        """Marca spawn como pulado (cooldown) e reposiciona no grafo.

        Usar quando spawn é inalcançável, ocupado, ou deve ser evitado.
        Reposiciona para o spawn skipado (se tem edges) ou mais próximo do player.
        """
        spawn.last_visited = time.time()
        key = _make_key(spawn)

        # Desativar modo INITIAL se era o spawn inicial
        if self._needs_initial_walk and self._initial_spawn and key == _make_key(self._initial_spawn):
            self._needs_initial_walk = False
            if DEBUG_AUTO_EXPLORE:
                print(f"[SpawnSelector] INITIAL: Spawn inicial pulado, desativando modo INITIAL")

        # Reposicionar no grafo para buscar vizinhos do spawn skipado
        old_key = self._current_spawn_key
        if self.spawn_graph:
            edges = self.spawn_graph.get("edges", {})
            if key in edges and edges[key]:
                # Spawn skipado tem edges → usar como nova origem
                self._current_spawn_key = key
            elif player_pos:
                # Spawn skipado sem edges → reposicionar baseado no player
                px, py, pz = player_pos
                new_key = self._find_nearest_spawn_key_with_edges(px, py, pz)
                if new_key:
                    self._current_spawn_key = new_key

        if DEBUG_AUTO_EXPLORE:
            reason_str = f" - {reason}" if reason else ""
            print(f"[SpawnSelector] Pulado: {key} [{_short_monsters(spawn)}]{reason_str} (origem: {old_key} → {self._current_spawn_key})")

    def reset_cooldowns(self):
        """Reseta cooldowns de todos os spawns ativos."""
        for s in self.active_spawns:
            s.last_visited = 0
        if DEBUG_AUTO_EXPLORE:
            print(f"[SpawnSelector] Cooldowns resetados para {len(self.active_spawns)} spawns")

    def is_occupied_by_closer_player(self, spawn, px, py, visible_players):
        """Retorna True se algum player visível está mais perto do spawn que nós."""
        if not visible_players:
            return False

        my_dist = spawn.distance_to(px, py)
        for p in visible_players:
            try:
                ppx, ppy, ppz = p.position.x, p.position.y, p.position.z
            except AttributeError:
                continue
            if ppz != spawn.cz:
                continue
            player_dist = spawn.distance_to(ppx, ppy)
            if player_dist <= my_dist and player_dist <= 7:
                return True
        return False

    def _find_nearest_spawn_key(self, px, py, pz):
        """Encontra o spawn mais próximo do player (Manhattan) entre os ativos."""
        best_key = None
        best_dist = float('inf')
        for s in self.active_spawns:
            dist = abs(s.cx - px) + abs(s.cy - py) + abs(s.cz - pz) * 20
            if dist < best_dist:
                best_dist = dist
                best_key = _make_key(s)
        return best_key

    def _find_nearest_spawn_key_with_edges(self, px, py, pz):
        """Encontra o spawn ativo mais próximo que tem edges no grafo."""
        edges = self.spawn_graph.get("edges", {}) if self.spawn_graph else {}
        best_key = None
        best_dist = float('inf')
        for s in self.active_spawns:
            key = _make_key(s)
            if key not in edges or not edges[key]:
                continue
            dist = abs(s.cx - px) + abs(s.cy - py) + abs(s.cz - pz) * 20
            if dist < best_dist:
                best_dist = dist
                best_key = key
        return best_key
