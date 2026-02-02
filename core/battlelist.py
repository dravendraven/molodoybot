# core/battlelist.py
"""
Scanner centralizado do battlelist.
Elimina duplicação em trainer.py, alarm.py, player_core.py, main.py.

SEM CACHE - dados em tempo real são críticos para:
- Posição de criaturas (mudam constantemente)
- HP (para detectar morte)
- Visibilidade (para detectar spawn/despawn)
"""
import struct
import time
from typing import List, Optional, Callable
from config import (
    BATTLELIST_BEGIN_ADDRESS, TARGET_ID_PTR, REL_FIRST_ID,
    STEP_SIZE, MAX_CREATURES,
    OFFSET_ID, OFFSET_NAME, OFFSET_X, OFFSET_Y, OFFSET_Z,
    OFFSET_HP, OFFSET_SPEED, OFFSET_VISIBLE,
    OFFSET_MOVEMENT_STATUS, OFFSET_FACING_DIRECTION,
    OFFSET_OUTFIT_TYPE, OFFSET_OUTFIT_HEAD, OFFSET_OUTFIT_BODY,
    OFFSET_OUTFIT_LEGS, OFFSET_OUTFIT_FEET,
    OFFSET_LIGHT, OFFSET_LIGHT_COLOR, OFFSET_BLACKSQUARE
)
from core.models import Creature, Position


# Scan Adaptativo (Early-Exit)
INVALID_SLOT_THRESHOLD = 15  # Slots inválidos consecutivos para parar scan


class BattleListScanner:
    """
    Scanner centralizado do battlelist.
    Lê dados em TEMPO REAL (sem cache) para precisão máxima.
    """

    def __init__(self, pm, base_addr):
        self.pm = pm
        self.base_addr = base_addr

    def scan_all(self, filter_fn: Optional[Callable[[Creature], bool]] = None) -> List[Creature]:
        """
        Scan completo do battlelist.

        Args:
            filter_fn: Função opcional para filtrar (ex: lambda c: c.hp_percent > 0)

        Returns:
            Lista de Creature válidas
        """
        creatures = []
        list_start = self.base_addr + TARGET_ID_PTR + REL_FIRST_ID
        invalid_streak = 0

        for i in range(MAX_CREATURES):
            slot = list_start + (i * STEP_SIZE)

            try:
                # BATCH READ: 1 syscall em vez de 7+
                raw_bytes = self.pm.read_bytes(slot, STEP_SIZE)
                creature = self._parse_creature(raw_bytes, i)

                if creature is None or not creature.is_valid:
                    invalid_streak += 1
                    if invalid_streak >= INVALID_SLOT_THRESHOLD:
                        break  # Early exit - fim da lista
                    continue

                invalid_streak = 0

                # Aplica filtro se fornecido
                if filter_fn is None or filter_fn(creature):
                    creatures.append(creature)

            except Exception:
                continue

        return creatures

    def _parse_creature(self, raw_bytes: bytes, slot_index: int) -> Optional[Creature]:
        """Parse bytes para objeto Creature."""
        try:
            # ID está no offset 0 (4 bytes, little-endian unsigned int)
            c_id = struct.unpack_from('<I', raw_bytes, OFFSET_ID)[0]
            if c_id == 0:
                return None

            # Parse nome (offset 4, até 32 bytes, null-terminated)
            name_bytes = raw_bytes[OFFSET_NAME:OFFSET_NAME + 32]
            name = name_bytes.split(b'\x00')[0].decode('latin-1', errors='ignore').strip()

            # Parse posição
            cx = struct.unpack_from('<i', raw_bytes, OFFSET_X)[0]
            cy = struct.unpack_from('<i', raw_bytes, OFFSET_Y)[0]
            cz = struct.unpack_from('<i', raw_bytes, OFFSET_Z)[0]

            # Parse stats
            hp = struct.unpack_from('<i', raw_bytes, OFFSET_HP)[0]
            speed = struct.unpack_from('<i', raw_bytes, OFFSET_SPEED)[0]
            visible = struct.unpack_from('<i', raw_bytes, OFFSET_VISIBLE)[0]
            moving = struct.unpack_from('<i', raw_bytes, OFFSET_MOVEMENT_STATUS)[0]
            facing = struct.unpack_from('<i', raw_bytes, OFFSET_FACING_DIRECTION)[0]

            # Parse outfit (para detecção precisa de player vs criatura humanoid)
            outfit_type = struct.unpack_from('<I', raw_bytes, OFFSET_OUTFIT_TYPE)[0]
            outfit_head = struct.unpack_from('<I', raw_bytes, OFFSET_OUTFIT_HEAD)[0]
            outfit_body = struct.unpack_from('<I', raw_bytes, OFFSET_OUTFIT_BODY)[0]
            outfit_legs = struct.unpack_from('<I', raw_bytes, OFFSET_OUTFIT_LEGS)[0]
            outfit_feet = struct.unpack_from('<I', raw_bytes, OFFSET_OUTFIT_FEET)[0]

            # Parse campos adicionais (tibianic-dll structures.h)
            light = struct.unpack_from('<I', raw_bytes, OFFSET_LIGHT)[0]
            light_color = struct.unpack_from('<I', raw_bytes, OFFSET_LIGHT_COLOR)[0]
            blacksquare = struct.unpack_from('<I', raw_bytes, OFFSET_BLACKSQUARE)[0]  # uint32_t (GetTickCount)

            return Creature(
                id=c_id,
                name=name,
                position=Position(cx, cy, cz),
                hp_percent=hp,
                speed=speed,
                is_visible=(visible == 1),
                is_moving=(moving == 1),
                facing_direction=facing,
                slot_index=slot_index,
                outfit_type=outfit_type,
                outfit_head=outfit_head,
                outfit_body=outfit_body,
                outfit_legs=outfit_legs,
                outfit_feet=outfit_feet,
                light=light,
                light_color=light_color,
                blacksquare=blacksquare
            )

        except Exception:
            return None

    # ===== MÉTODOS DE CONVENIÊNCIA =====

    def get_monsters(self, target_names: List[str] = None, include_dead: bool = False,
                     player_z: int = None) -> List[Creature]:
        """
        Retorna apenas monstros vivos (opcional: filtrar por nome e andar).

        Args:
            target_names: Lista de nomes para filtrar (None = todos)
            include_dead: Se True, inclui monstros mortos (default: False)
            player_z: Se fornecido, filtra apenas criaturas no mesmo andar

        NOTA: NPCs aparecem no battlelist com bit 31 do ID setado (filtrados via is_npc).
        """
        def is_valid_monster(c: Creature) -> bool:
            if c.is_player:
                return False
            if not include_dead and not c.is_alive:
                return False
            if player_z is not None and c.position.z != player_z:
                return False
            if target_names and c.name not in target_names:
                return False
            return True

        return self.scan_all(filter_fn=is_valid_monster)

    def get_dead_creatures(self) -> List[Creature]:
        """
        Retorna criaturas que acabaram de morrer (hp <= 0, visible = False).
        Útil para auto-loot detectar corpos antes do cliente limpar o target.
        """
        return self.scan_all(filter_fn=lambda c: c.is_dead)

    def get_players(self, exclude_self_id: int = 0) -> List[Creature]:
        """Retorna apenas jogadores (exclui self)."""
        return self.scan_all(
            filter_fn=lambda c: c.is_player and c.id != exclude_self_id
        )

    def get_creature_by_id(self, creature_id: int) -> Optional[Creature]:
        """Busca criatura específica por ID."""
        for c in self.scan_all():
            if c.id == creature_id:
                return c
        return None

    def get_nearest_monster(self, player_pos: Position,
                           target_names: List[str] = None,
                           player_z: int = None) -> Optional[Creature]:
        """
        Retorna monstro mais próximo usando distância Manhattan.

        Args:
            player_pos: Posição do jogador
            target_names: Lista de nomes para filtrar (None = todos)
            player_z: Se fornecido, filtra apenas criaturas no mesmo andar

        NOTA: Para ordenação precisa considerando obstáculos,
        use o A* walker para calcular custo real de cada candidato.
        """
        monsters = self.get_monsters(target_names, player_z=player_z)
        if not monsters:
            return None

        return min(monsters, key=lambda m: player_pos.steps_to(m.position))

    def get_adjacent_creatures(self, player_pos: Position) -> List[Creature]:
        """Retorna criaturas adjacentes (1 tile de distância)."""
        return self.scan_all(filter_fn=lambda c: c.is_adjacent_to(player_pos))

    def get_creatures_in_range(self, player_pos: Position, attack_range: int,
                              player_z: int = None) -> List[Creature]:
        """
        Retorna criaturas dentro do alcance de ataque (Chebyshev).

        Args:
            player_pos: Posição do jogador
            attack_range: Alcance de ataque
            player_z: Se fornecido, filtra apenas criaturas no mesmo andar
        """
        def in_range_filter(c: Creature) -> bool:
            if player_z is not None and c.position.z != player_z:
                return False
            return c.is_in_range(player_pos, attack_range)

        return self.scan_all(filter_fn=in_range_filter)


class SpawnTracker:
    """
    Detecta criaturas que aparecem suspeitamente perto do player.

    GMs testam bots sumonando criaturas próximas. Uma criatura normal:
    - Aparece primeiro a distância maior (caminhando em direção ao player)
    - Ou aparece primeiro em outro andar (subindo/descendo)

    Spawn suspeito = criatura nova que aparece já perto, sem histórico prévio.
    """

    def __init__(self, suspicious_range=5, floor_change_cooldown=3.0, cleanup_age=30.0):
        self.known_creatures = {}  # {creature_id: timestamp_first_seen}
        self.last_player_z = None
        self.last_floor_change_time = 0.0
        self.suspicious_range = suspicious_range
        self.floor_change_cooldown = floor_change_cooldown
        self.cleanup_age = cleanup_age
        self._warmed_up = False  # Primeiro ciclo apenas registra

    def update(self, creatures: List[Creature], player_x: int, player_y: int, player_z: int, self_id: int = 0) -> List[Creature]:
        """
        Atualiza tracker com scan atual e retorna criaturas com spawn suspeito.

        Args:
            creatures: Lista completa do scan_all()
            player_x, player_y, player_z: Posição atual do player
            self_id: ID do próprio personagem (para excluir do tracking)

        Returns:
            Lista de Creature que apareceram suspeitamente perto
        """
        now = time.time()
        suspicious = []

        # Detecta mudança de andar do player
        if self.last_player_z is not None and player_z != self.last_player_z:
            self.last_floor_change_time = now
        self.last_player_z = player_z

        recently_changed_floor = (now - self.last_floor_change_time) < self.floor_change_cooldown

        # IDs presentes neste scan (para cleanup)
        current_ids = set()

        for creature in creatures:
            current_ids.add(creature.id)

            # Ignora o próprio personagem
            if creature.id == self_id:
                continue

            # Ignora players e NPCs (apenas monstros são relevantes)
            if creature.is_player:
                continue

            # Criatura já conhecida - não é suspeita
            if creature.id in self.known_creatures:
                continue

            # Criatura nova - registra
            self.known_creatures[creature.id] = now

            # Primeiro ciclo: apenas registra sem avaliar (warmup)
            if not self._warmed_up:
                continue

            # Não avalia se mudou de andar recentemente (tudo é novo)
            if recently_changed_floor:
                continue

            # Não avalia se criatura está em outro andar
            if creature.position.z != player_z:
                continue

            # Não avalia se não está visível
            if not creature.is_visible:
                continue

            # Calcula distância Chebyshev
            dist = max(abs(player_x - creature.position.x), abs(player_y - creature.position.y))

            # Spawn suspeito: apareceu perto sem histórico prévio
            if dist < self.suspicious_range:
                suspicious.append(creature)

        if not self._warmed_up:
            self._warmed_up = True

        # Cleanup: remove criaturas que não aparecem há muito tempo
        stale_ids = [
            cid for cid, ts in self.known_creatures.items()
            if cid not in current_ids and (now - ts) > self.cleanup_age
        ]
        for cid in stale_ids:
            del self.known_creatures[cid]

        return suspicious
