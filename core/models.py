# core/models.py
"""
Classes de modelo para objetos comuns do bot.
Centraliza tipos de dados usados em múltiplos módulos.
"""
from dataclasses import dataclass
from typing import Optional, List
from database.creature_outfits import is_humanoid_creature


@dataclass
class Position:
    """Posição no mapa (usada em Creature, Player, Item)."""
    x: int
    y: int
    z: int

    def manhattan_to(self, other: 'Position') -> int:
        """
        Distância Manhattan (ideal para Tibia grid-based).
        Retorna soma dos deltas absolutos.
        """
        return abs(self.x - other.x) + abs(self.y - other.y)

    def chebyshev_to(self, other: 'Position') -> int:
        """
        Distância Chebyshev (máx dos deltas).
        Útil para verificar adjacência: chebyshev == 1 = adjacente.
        """
        return max(abs(self.x - other.x), abs(self.y - other.y))

    def is_adjacent_to(self, other: 'Position') -> bool:
        """
        Verifica se está adjacente (1 tile de distância, inclui diagonal).
        Usado em cavebot para rope, ladder, shovel, etc.
        """
        return self.chebyshev_to(other) == 1 and self.z == other.z

    def relative_to(self, other: 'Position') -> tuple:
        """Retorna (dx, dy) relativo a outra posição."""
        return (self.x - other.x, self.y - other.y)

    def steps_to(self, other: 'Position') -> int:
        """
        Distância Manhattan até outra posição (número de passos cardinais).

        NOTA: Assume movimento cardinal (N/S/E/W).
        O cálculo de path real (diagonal vs cardinal) é feito pelo A* walker.
        """
        return abs(self.x - other.x) + abs(self.y - other.y)

    def steps_to_adjacent(self, other: 'Position', attack_range: int = 1) -> int:
        """
        Distância Manhattan até o tile ADJACENTE mais próximo de outra posição.

        MUITO USADO EM TIBIA:
        - Atacar criatura: só precisa chegar adjacente (range=1)
        - Usar rope/shovel/ladder: só precisa estar adjacente
        - Waypoints: não precisa pisar no tile exato

        Args:
            other: Posição de destino
            attack_range: Alcance de interação (1 = melee/adjacente)

        Returns:
            Número de passos cardinais até tile adjacente.
            0 se já está adjacente ou dentro do range.

        NOTA: O cálculo de path real (diagonal vs cardinal) é feito pelo A* walker.
        """
        dx = abs(self.x - other.x)
        dy = abs(self.y - other.y)

        # Se já está adjacente ou dentro do range
        if dx <= attack_range and dy <= attack_range:
            return 0

        # Passos necessários até a borda do range
        steps_x = max(0, dx - attack_range)
        steps_y = max(0, dy - attack_range)

        return steps_x + steps_y

    def get_adjacent_target(self, other: 'Position', attack_range: int = 1) -> 'Position':
        """
        Retorna a posição do tile adjacente mais próximo para alcançar 'other'.

        Usado quando precisamos passar um destino para o A*, que deve ser
        o tile adjacente, não o tile de destino em si.

        Args:
            other: Posição do alvo (criatura, escada, waypoint)
            attack_range: Alcance de interação

        Returns:
            Position do tile adjacente mais próximo.
            Retorna self se já está adjacente.
        """
        dx = other.x - self.x
        dy = other.y - self.y

        # Se já está adjacente
        if abs(dx) <= attack_range and abs(dy) <= attack_range:
            return self

        # Calcula tile adjacente na direção do alvo
        if abs(dx) > attack_range:
            target_x = other.x - attack_range if dx > 0 else other.x + attack_range
        else:
            target_x = self.x  # Já está dentro do range nesse eixo

        if abs(dy) > attack_range:
            target_y = other.y - attack_range if dy > 0 else other.y + attack_range
        else:
            target_y = self.y

        return Position(target_x, target_y, self.z)


# Cache global para rastrear mudanças no blacksquare (fora da dataclass)
# {creature_id: (last_blacksquare_value, last_change_timestamp)}
_blacksquare_cache: dict = {}


@dataclass
class Creature:
    """Representa uma criatura do battlelist."""
    id: int
    name: str
    position: Position
    hp_percent: int
    speed: int
    is_visible: bool
    is_moving: bool
    facing_direction: int
    slot_index: int  # Índice no battlelist (útil para debug)
    # Outfit (para detecção precisa de player vs criatura humanoid)
    outfit_type: int = 0    # LookType (sprite base)
    outfit_head: int = 0    # Cor da cabeça
    outfit_body: int = 0    # Cor do corpo
    outfit_legs: int = 0    # Cor das pernas
    outfit_feet: int = 0    # Cor dos pés
    # Campos adicionais do tibianic-dll structures.h
    light: int = 0          # Light level emitted
    light_color: int = 0    # Light color
    blacksquare: int = 0    # Shown when creature attacks player (8 bytes)

    @property
    def is_npc(self) -> bool:
        """NPCs have bit 31 set in their creature ID (0x80000000+)."""
        return (self.id & 0x80000000) != 0

    @property
    def is_valid(self) -> bool:
        """Valida se a criatura é válida."""
        if self.hp_percent < 0 or self.hp_percent > 100:
            return False
        if self.position.z < 0 or self.position.z > 15:
            return False
        if not self.name or len(self.name) == 0:
            return False
        return True

    @property
    def is_player(self) -> bool:
        """
        Verifica se é um jogador (não monstro).
        NOTA: NPCs aparecem no battlelist com bit 31 do ID setado (0x80000000+).
        São filtrados via is_npc antes desta verificação.

        DETECÇÃO TRIPLA:
        1. Verifica se tem cores de outfit (head + body + legs + feet > 0)
        2. Verifica se NÃO é uma criatura humanoid conhecida (Amazon, Hunter, etc.)
        3. FALLBACK: Se não tem cores E nome não é criatura conhecida → player

        Isso evita falsos positivos com criaturas que usam outfits de player.
        Também detecta players mesmo quando cores de outfit não são lidas corretamente.
        """
        if not self.name:
            return False

        # NPCs não são players
        if self.is_npc:
            return False

        # Players têm cores no outfit
        has_colors = (self.outfit_head + self.outfit_body +
                      self.outfit_legs + self.outfit_feet) > 0

        # Verifica se é criatura humanoid conhecida (Amazon, Hunter, etc.)
        # Dupla validação: outfit + nome devem bater
        is_known_humanoid = is_humanoid_creature(
            self.name,
            self.outfit_type,
            self.outfit_head,
            self.outfit_body,
            self.outfit_legs,
            self.outfit_feet
        )

        # FALLBACK: Se não tem cores de outfit, verifica pelo nome
        # Se nome não é de nenhuma criatura conhecida → provavelmente é player
        if not has_colors:
            from database.corpses import CORPSE_IDS
            # Verifica se o nome corresponde a alguma criatura conhecida
            name_lower = self.name.lower()
            is_known_creature = any(
                creature_name.lower() == name_lower or
                creature_name.lower() in name_lower or
                name_lower in creature_name.lower()
                for creature_name in CORPSE_IDS.keys()
            )
            # Nome desconhecido + sem cores = provavelmente player
            if not is_known_creature:
                return True

        # Player = tem cores E NÃO é criatura humanoid conhecida
        return has_colors and not is_known_humanoid

    @property
    def is_monster(self) -> bool:
        """Verifica se é um monstro (não player, não NPC)."""
        return not self.is_player and not self.is_npc

    @property
    def is_dead(self) -> bool:
        """
        Verifica se a criatura está morta.

        No Tibia 7.72, uma criatura morta tem:
        - hp_percent <= 0 (sem vida)
        - is_visible == False (não aparece mais na tela)

        OTIMIZAÇÃO TRAINER+AUTOLOOT:
        Permite detectar morte instantânea sem esperar o cliente
        limpar o target_id.
        """
        return self.hp_percent <= 0 and not self.is_visible

    @property
    def is_alive(self) -> bool:
        """Verifica se a criatura está viva e visível."""
        return self.hp_percent > 0 and self.is_visible

    def is_in_range(self, player_pos: Position, attack_range: int) -> bool:
        """Verifica se está no alcance de ataque (Chebyshev)."""
        return self.position.chebyshev_to(player_pos) <= attack_range

    def is_adjacent_to(self, player_pos: Position) -> bool:
        """Verifica se está adjacente ao player (1 tile)."""
        return self.position.is_adjacent_to(player_pos)

    def is_on_same_floor(self, player_z: int) -> bool:
        """Verifica se criatura está no mesmo andar que o player."""
        return self.position.z == player_z

    def is_targetable(self, player_z: int) -> bool:
        """
        Verifica se criatura pode ser alvo (viva, visível, mesmo andar).

        IMPORTANTE: Use este método em vez de is_alive quando precisar
        garantir que a criatura está no mesmo andar.

        Replica a lógica do trainer.py:
        is_on_battle_list = (vis == 1 and z == my_z)
        """
        return self.is_alive and self.position.z == player_z

    def is_attacking_player(self, threshold_ms: int = 5000, debug: bool = False) -> bool:
        """
        Verifica se a criatura está nos atacando baseado em mudanças no blacksquare.

        O blacksquare usa um timestamp INTERNO do cliente Tibia (não GetTickCount do Windows).
        Por isso, rastreamos MUDANÇAS no valor em vez de comparar com tempo absoluto.

        Lógica:
        - Se blacksquare == 0: não está atacando
        - Se blacksquare mudou recentemente: está atacando
        - Se blacksquare não mudou por mais de threshold: parou de atacar

        Args:
            threshold_ms: Tempo em ms para considerar ataque ativo (default 5000ms)
            debug: Se True, imprime valores para debug

        Returns:
            True se a criatura está nos atacando
        """
        import time

        # Criatura morta ou invisível: limpa cache para evitar falso positivo
        # quando o slot da battlelist é reusado por outra criatura
        if self.hp_percent <= 0 or not self.is_visible:
            if self.id in _blacksquare_cache:
                del _blacksquare_cache[self.id]
            return False

        if self.blacksquare == 0:
            # Limpa cache se blacksquare zerou
            if self.id in _blacksquare_cache:
                del _blacksquare_cache[self.id]
            if debug:
                print(f"  [BLACKSQUARE] {self.name}: blacksquare=0 → False")
            return False

        current_time = time.time() * 1000  # Converte para ms
        cache_entry = _blacksquare_cache.get(self.id)

        if cache_entry is None:
            # Primeira vez vendo esta criatura com blacksquare != 0
            # Assume que está atacando (valor novo)
            _blacksquare_cache[self.id] = (self.blacksquare, current_time)
            if debug:
                print(f"  [BLACKSQUARE] {self.name}: NOVO blacksquare={self.blacksquare} → True")
            return True

        last_value, last_change_time = cache_entry

        if self.blacksquare != last_value:
            # Blacksquare mudou - criatura atacou recentemente
            _blacksquare_cache[self.id] = (self.blacksquare, current_time)
            if debug:
                print(f"  [BLACKSQUARE] {self.name}: MUDOU {last_value}→{self.blacksquare} → True")
            return True

        # Blacksquare não mudou - verifica há quanto tempo
        age_ms = current_time - last_change_time

        if debug:
            print(f"  [BLACKSQUARE] {self.name}: blacksquare={self.blacksquare}, age={age_ms:.0f}ms, threshold={threshold_ms}")

        result = age_ms < threshold_ms
        if debug:
            status = "ATIVO" if result else "EXPIRADO"
            print(f"  [BLACKSQUARE] {self.name}: {status} → {result}")
        return result


@dataclass
class Item:
    """Item em container ou chão."""
    id: int
    count: int
    slot_index: int

    def __repr__(self):
        return f"[Slot {self.slot_index}] ID: {self.id} | Qt: {self.count}"

    # NOTA: Para verificar se é stackable, usar:
    # from database.lootables_db import is_stackable
    # is_stackable(item.id)  # Verifica flag 'Cumulative' no database


@dataclass
class Container:
    """Container aberto."""
    index: int
    name: str
    volume: int       # Slots totais
    amount: int       # Itens atuais
    has_parent: bool  # True se é filho de outro container (hasparent=1)
    items: List[Item]
    address: int = 0  # Endereço de memória (opcional, para debug)

    def __repr__(self):
        parent_str = "filho" if self.has_parent else "raiz"
        return f"Container {self.index}: '{self.name}' ({self.amount}/{self.volume}) [{parent_str}]"

    @property
    def is_loot_container(self) -> bool:
        """Verifica se é um corpo/loot."""
        return self.name.startswith("Dead ") or self.name.startswith("Slain ")

    @property
    def has_space(self) -> bool:
        return self.amount < self.volume

    def find_item(self, item_id: int) -> Optional[Item]:
        """Busca item por ID."""
        for item in self.items:
            if item.id == item_id:
                return item
        return None


@dataclass
class Player:
    """
    Player character state snapshot.

    Representa o estado completo do player lido da memória pelo game_state.
    Atualizado 20 vezes por segundo (20Hz polling).
    """
    char_id: int
    char_name: str
    position: Position
    hp: int
    hp_max: int
    hp_percent: float
    mana: int
    mana_max: int
    mana_percent: float
    cap: float  # Carrying capacity (oz)
    speed: int  # Movement speed
    is_moving: bool
    is_full: bool  # Inventory full
    # Stats / Progressão
    level: int = 0
    experience: int = 0
    magic_level: int = 0
    magic_level_pct: int = 0  # % progresso para próximo magic level
    # Skills
    sword_skill: int = 0
    sword_skill_pct: int = 0
    shield_skill: int = 0
    shield_skill_pct: int = 0
    # Equipamento (IDs dos itens)
    right_hand_id: int = 0
    left_hand_id: int = 0
    ammo_id: int = 0
    # Movimento / Combate
    facing_direction: int = 0  # 0=N, 1=E, 2=S, 3=W
    target_id: int = 0  # ID da criatura sendo atacada (0 = nenhuma)

    @property
    def is_alive(self) -> bool:
        """Check if player is alive."""
        return self.hp > 0

    @property
    def is_low_hp(self) -> bool:
        """Check if HP is below 50% threshold."""
        return self.hp_percent < 50.0

    @property
    def is_low_mana(self) -> bool:
        """Check if mana is below 30% threshold."""
        return self.mana_percent < 30.0

    @property
    def can_carry_more(self) -> bool:
        """Check if player can carry more items."""
        return self.cap > 10.0 and not self.is_full

    def is_hp_below(self, threshold: float) -> bool:
        """Check if HP is below custom threshold percent."""
        return self.hp_percent < threshold

    def is_mana_below(self, threshold: float) -> bool:
        """Check if mana is below custom threshold percent."""
        return self.mana_percent < threshold
