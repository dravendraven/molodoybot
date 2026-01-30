"""
Game State Manager - Eyes of the Bot (Memory Scanner + Aggregator).

This module continuously scans game memory and provides a unified API for all modules.

Architecture:
    SCAN (Eyes) → BRAIN (game_state) → HANDS (action_scheduler)

    game_state polls memory at 20Hz and caches:
    - Player state (pos, HP, mana, cap, moving)
    - Creatures & players (from battlelist)
    - Containers & items
    - Map tiles (15x11 grid)
    - Equipment slots
    - Ground items
    - Chat messages

Modules query game_state instead of reading memory directly.
"""

import threading
import time
from typing import Optional, List, Dict, Tuple, Any

# Import shared models
from core.models import Position, Player, Creature

# Import existing scanners
from core.battlelist import BattleListScanner
from core.memory_map import MemoryMap
from core.map_analyzer import MapAnalyzer
from core.map_core import get_player_pos
from core.player_core import (
    get_player_id, get_target_id,
    is_player_moving, get_player_speed,
    get_connected_char_name, get_player_facing_direction
)
from modules.auto_loot import scan_containers, is_player_full
from core.inventory_core import get_item_id_in_hand
from config import (
    OFFSET_PLAYER_HP, OFFSET_PLAYER_HP_MAX,
    OFFSET_PLAYER_MANA, OFFSET_PLAYER_MANA_MAX,
    OFFSET_PLAYER_CAP,
    OFFSET_LEVEL, OFFSET_EXP, OFFSET_MAGIC_LEVEL, OFFSET_MAGIC_PCT,
    OFFSET_SKILL_SWORD, OFFSET_SKILL_SWORD_PCT,
    OFFSET_SKILL_SHIELD, OFFSET_SKILL_SHIELD_PCT,
    OFFSET_SLOT_RIGHT, OFFSET_SLOT_LEFT, OFFSET_SLOT_AMMO,
    TARGET_ID_PTR,
)

# Import bot control state (GM detection, alarm)
from core.bot_state import state as legacy_state

# Import event bus for event-driven detection
from core.event_bus import EventBus, EVENT_SYSTEM_MSG


class GameState:
    """
    Centralized game state manager.

    Polls memory at 20Hz (50ms) and caches everything modules need.
    All modules query this instead of reading memory directly.

    This provides:
    - Single source of truth (all modules see same snapshot)
    - Performance (one scan shared by all modules)
    - Consistency (no race conditions from modules reading at different times)
    """

    def __init__(self):
        """Initialize game state (pm/base_addr set later via init())."""
        self._lock = threading.RLock()

        # Memory access (set during init)
        self.pm = None
        self.base_addr = 0

        # Scanners (initialized during init)
        self.battlelist: Optional[BattleListScanner] = None
        self.memory_map: Optional[MemoryMap] = None
        self.map_analyzer: Optional[MapAnalyzer] = None

        # === CACHED STATE (updated by polling thread) ===

        # Player state
        self._player = Player(
            char_id=0, char_name="", position=Position(0, 0, 0),
            hp=0, hp_max=1, hp_percent=0.0,
            mana=0, mana_max=1, mana_percent=0.0,
            cap=0.0, speed=0, is_moving=False, is_full=False
        )
        self._target_id: int = 0

        # Creatures & players
        self._creatures: List[Creature] = []
        self._players: List[Creature] = []

        # Containers
        self._containers: List[Any] = []  # List of Container objects from auto_loot

        # Map (15x11 tiles around player)
        self._map_tiles: Dict[Tuple[int, int, int], Any] = {}

        # Equipment slots
        self._left_hand_id: int = 0
        self._right_hand_id: int = 0

        # Update thread
        self._running = False
        self._update_thread: Optional[threading.Thread] = None
        self._update_interval = 0.05  # 20Hz = 50ms

        # Performance stats
        self._update_count = 0
        self._last_update_time = 0.0
        self._update_duration_ms = 0.0

        # Module lock (for atomic action sequences)
        self._active_module: Optional[str] = None
        self._module_lock_time: float = 0.0
        self._module_lock_timeout: float = 30.0

        # Event-based food satiation detection (regen full, not inventory)
        self._event_bus = EventBus.get_instance()
        self._is_full_event = False  # Flag set by "You are full" event (food regen maxed)
        self._full_event_timestamp = 0.0
        self._full_flag_timeout = 5.0  # Seconds to keep flag after event

    # =========================================================================
    # INITIALIZATION
    # =========================================================================

    def init(self, pm, base_addr):
        """
        Initialize with Pymem instance and base address.

        Called after Pymem attaches to Tibia.exe.
        """
        with self._lock:
            self.pm = pm
            self.base_addr = base_addr

            # Initialize scanners
            self.battlelist = BattleListScanner(pm, base_addr)
            self.memory_map = MemoryMap(pm, base_addr)
            self.map_analyzer = MapAnalyzer(self.memory_map)

            # Start polling thread
            if not self._running:
                self._running = True
                self._update_thread = threading.Thread(
                    target=self._update_loop,
                    name="GameState-Poller",
                    daemon=True
                )
                self._update_thread.start()

            # Subscribe to system messages for event-based food satiation detection
            self._event_bus.subscribe(EVENT_SYSTEM_MSG, self._on_system_message)

    def _on_system_message(self, event):
        """
        Event handler for system messages.

        Detects "You are full" message from server and sets satiation flag.
        This message means the player has maximum food regen time and cannot
        eat more food at the moment (not about inventory capacity).

        This provides more reliable detection than memory reading alone.

        Args:
            event: SystemMessageEvent with msg_type, message, timestamp
        """
        try:
            message = event.message.lower()
            # Tibia 7.72 sends "You are full." when food regen is at maximum
            if "you are full" in message or "you cannot carry" in message:
                with self._lock:
                    self._is_full_event = True
                    self._full_event_timestamp = event.timestamp
        except Exception:
            pass  # Ignore malformed events

    def shutdown(self):
        """Stop the polling thread."""
        self._running = False
        if self._update_thread:
            self._update_thread.join(timeout=2.0)

    # =========================================================================
    # POLLING LOOP (20Hz)
    # =========================================================================

    def _update_loop(self):
        """
        Main polling loop - runs at 20Hz (50ms intervals).

        Reads all game state from memory and caches it.
        """
        while self._running:
            start_time = time.time()

            try:
                self._update_state()
            except Exception:
                # Don't crash on read errors
                pass

            # Track performance
            self._last_update_time = time.time()
            self._update_duration_ms = (self._last_update_time - start_time) * 1000
            self._update_count += 1

            # Sleep to maintain 20Hz
            elapsed = time.time() - start_time
            sleep_time = max(0, self._update_interval - elapsed)
            if sleep_time > 0:
                time.sleep(sleep_time)

    def _update_state(self):
        """
        Single atomic update of all game state.

        This is called 20 times per second (50ms intervals).
        """
        if not self.pm or not legacy_state.is_connected:
            return

        try:
            # === PLAYER STATE ===
            player_id = get_player_id(self.pm, self.base_addr)
            player_pos = get_player_pos(self.pm, self.base_addr)

            hp = self.pm.read_int(self.base_addr + OFFSET_PLAYER_HP)
            hp_max = self.pm.read_int(self.base_addr + OFFSET_PLAYER_HP_MAX)
            mana = self.pm.read_int(self.base_addr + OFFSET_PLAYER_MANA)
            mana_max = self.pm.read_int(self.base_addr + OFFSET_PLAYER_MANA_MAX)
            cap = self.pm.read_float(self.base_addr + OFFSET_PLAYER_CAP)

            # Stats / Progressão
            level = self.pm.read_int(self.base_addr + OFFSET_LEVEL)
            experience = self.pm.read_int(self.base_addr + OFFSET_EXP)
            magic_level = self.pm.read_int(self.base_addr + OFFSET_MAGIC_LEVEL)
            magic_level_pct = self.pm.read_int(self.base_addr + OFFSET_MAGIC_PCT)

            # Skills
            sword_skill = self.pm.read_int(self.base_addr + OFFSET_SKILL_SWORD)
            sword_skill_pct = self.pm.read_int(self.base_addr + OFFSET_SKILL_SWORD_PCT)
            shield_skill = self.pm.read_int(self.base_addr + OFFSET_SKILL_SHIELD)
            shield_skill_pct = self.pm.read_int(self.base_addr + OFFSET_SKILL_SHIELD_PCT)

            # Equipment
            right_hand_equip = self.pm.read_int(self.base_addr + OFFSET_SLOT_RIGHT)
            left_hand_equip = self.pm.read_int(self.base_addr + OFFSET_SLOT_LEFT)
            ammo_equip = self.pm.read_int(self.base_addr + OFFSET_SLOT_AMMO)

            # Calculate percentages
            hp_percent = (hp / hp_max * 100) if hp_max > 0 else 0
            mana_percent = (mana / mana_max * 100) if mana_max > 0 else 0

            # Movement and speed
            is_moving = is_player_moving(self.pm, self.base_addr)
            speed = get_player_speed(self.pm, self.base_addr)

            # Target
            target_id = get_target_id(self.pm, self.base_addr)
            facing_direction = get_player_facing_direction(self.pm, self.base_addr)

            # Character name
            char_name = get_connected_char_name(self.pm, self.base_addr)

            # Fullness check - hybrid approach (events + memory fallback)
            is_full = self._check_is_full_hybrid()

            # === BATTLELIST (Creatures & Players) ===
            # BattleListScanner already returns List[Creature] from models.py!
            all_entities = self.battlelist.scan_all() if self.battlelist else []

            creatures = []
            players = []

            for creature in all_entities:
                # Creature objects already have is_player property
                if creature.is_player:
                    players.append(creature)
                else:
                    creatures.append(creature)

            # === CONTAINERS ===
            containers = scan_containers(self.pm, self.base_addr)

            # === MAP TILES ===
            # Read full map (15x11 around player)
            if self.memory_map and player_pos:
                map_data = self.memory_map.read_full_map()
                # Store as dict keyed by (x, y, z)
                map_tiles = {}
                for tile in map_data:
                    pos = tile.get('position')
                    if pos:
                        map_tiles[pos] = tile
            else:
                map_tiles = {}

            # === EQUIPMENT ===
            left_hand = get_item_id_in_hand(self.pm, self.base_addr, is_left=True)
            right_hand = get_item_id_in_hand(self.pm, self.base_addr, is_left=False)

            # Convert position tuple to Position object
            if player_pos:
                position = Position(player_pos[0], player_pos[1], player_pos[2])
            else:
                position = Position(0, 0, 0)

            # === ATOMIC UPDATE (write all cached state) ===
            with self._lock:
                # Player - create new Player object
                self._player = Player(
                    char_id=player_id,
                    char_name=char_name,
                    position=position,
                    hp=hp,
                    hp_max=hp_max,
                    hp_percent=hp_percent,
                    mana=mana,
                    mana_max=mana_max,
                    mana_percent=mana_percent,
                    cap=cap,
                    speed=speed,
                    is_moving=is_moving,
                    is_full=is_full,
                    level=level,
                    experience=experience,
                    magic_level=magic_level,
                    magic_level_pct=magic_level_pct,
                    sword_skill=sword_skill,
                    sword_skill_pct=sword_skill_pct,
                    shield_skill=shield_skill,
                    shield_skill_pct=shield_skill_pct,
                    right_hand_id=right_hand_equip,
                    left_hand_id=left_hand_equip,
                    ammo_id=ammo_equip,
                    facing_direction=facing_direction,
                    target_id=target_id,
                )

                # Target
                self._target_id = target_id

                # Entities
                self._creatures = creatures
                self._players = players

                # Containers
                self._containers = containers

                # Map
                self._map_tiles = map_tiles

                # Equipment
                self._left_hand_id = left_hand
                self._right_hand_id = right_hand

        except Exception:
            # Ignore read errors (disconnected, etc.)
            pass

    def _check_is_full_hybrid(self) -> bool:
        """
        Hybrid food satiation detection: Event-based with memory fallback.

        Detects if player has maximum food regen time ("You are full" state).
        This is NOT about inventory capacity, but about food satiation.

        Priority:
        1. If event received recently (< 5 seconds) -> use event flag
        2. Otherwise -> fallback to memory reading

        This provides best of both worlds:
        - Event-driven: Real-time server messages (authoritative)
        - Memory fallback: Works when sniffer isn't running

        Returns:
            True if player is full of food (cannot eat more due to max regen time)
        """
        current_time = time.time()

        # Check if event flag is still valid (not timed out)
        if self._is_full_event:
            # Check timeout - flag expires after 5 seconds
            if current_time - self._full_event_timestamp < self._full_flag_timeout:
                return True
            else:
                # Timeout expired, clear flag
                self._is_full_event = False

        # Fallback to memory reading
        # Handles: sniffer not running, event missed, or timeout expired
        return is_player_full(self.pm, self.base_addr)

    def clear_fullness_flag(self):
        """
        Clear the food satiation event flag.

        Called when player successfully eats food, resetting the "full" state.
        This allows the eater module to attempt eating again without waiting
        for the 5-second timeout, in case the regen time has decreased.
        """
        with self._lock:
            self._is_full_event = False

    # =========================================================================
    # QUERY API - Player State
    # =========================================================================

    def get_player_state(self) -> Player:
        """Get full player state snapshot (copy)."""
        with self._lock:
            # Return a copy to avoid mutation
            import dataclasses
            return dataclasses.replace(self._player)

    def get_player_position(self) -> Position:
        """Get player position as Position object."""
        with self._lock:
            return self._player.position

    def get_player_hp(self) -> Tuple[int, int, float]:
        """Get (hp, hp_max, hp_percent)."""
        with self._lock:
            return (self._player.hp, self._player.hp_max, self._player.hp_percent)

    def get_player_mana(self) -> Tuple[int, int, float]:
        """Get (mana, mana_max, mana_percent)."""
        with self._lock:
            return (self._player.mana, self._player.mana_max, self._player.mana_percent)

    def get_player_cap(self) -> float:
        """Get player carrying capacity."""
        with self._lock:
            return self._player.cap

    def is_player_moving(self) -> bool:
        """Check if player is currently moving."""
        with self._lock:
            return self._player.is_moving

    def is_player_full(self) -> bool:
        """Check if player inventory is full."""
        with self._lock:
            return self._player.is_full

    # =========================================================================
    # QUERY API - Combat State
    # =========================================================================

    def get_target_id(self) -> int:
        """Get current target ID (0 = no target)."""
        with self._lock:
            return self._target_id

    def is_in_combat(self) -> bool:
        """Check if in combat (has target)."""
        with self._lock:
            return self._target_id != 0

    def get_creatures(self) -> List[Creature]:
        """Get list of all visible creatures (copy)."""
        with self._lock:
            return list(self._creatures)

    def get_players(self) -> List[Creature]:
        """Get list of all visible players (copy)."""
        with self._lock:
            return list(self._players)

    def get_creature_by_id(self, creature_id: int) -> Optional[Creature]:
        """Get specific creature by ID."""
        with self._lock:
            for creature in self._creatures:
                if creature.id == creature_id:  # Note: 'id' not 'creature_id'
                    return creature
            # Check players too
            for player in self._players:
                if player.id == creature_id:
                    return player
            return None

    # =========================================================================
    # QUERY API - Containers & Items
    # =========================================================================

    def get_containers(self) -> List[Any]:
        """Get list of all open containers (copy)."""
        with self._lock:
            return list(self._containers)

    def get_equipment_slots(self) -> Tuple[int, int]:
        """Get (left_hand_id, right_hand_id)."""
        with self._lock:
            return (self._left_hand_id, self._right_hand_id)

    # =========================================================================
    # QUERY API - Map & Environment
    # =========================================================================

    def get_map_tiles(self) -> Dict[Tuple[int, int, int], Any]:
        """Get full map snapshot (15x11 tiles)."""
        with self._lock:
            return dict(self._map_tiles)

    def get_tile_at(self, x: int, y: int, z: int) -> Optional[Any]:
        """Get specific tile data."""
        with self._lock:
            return self._map_tiles.get((x, y, z))

    # =========================================================================
    # STATE VALIDATION (for action_scheduler)
    # =========================================================================

    def can_send_mouse_action(self) -> bool:
        """
        Check if mouse actions (use_item, move_item) are allowed.

        Returns False if:
        - GM detected
        - Alarm active
        - Chat paused
        - Player is moving (checked separately by scheduler)
        """
        if legacy_state.is_gm_detected:
            return False
        if not legacy_state.is_safe():
            return False
        if legacy_state.is_chat_paused:
            return False
        return True

    def can_send_keyboard_action(self) -> bool:
        """
        Check if keyboard actions (attack, walk, stop) are allowed.

        More permissive than mouse - only blocked by GM/alarm.
        """
        if legacy_state.is_gm_detected:
            return False
        if not legacy_state.is_safe():
            return False
        return True

    # =========================================================================
    # BOT CONTROL (bridge to legacy_state)
    # =========================================================================

    def is_bot_running(self) -> bool:
        """Check if bot is running."""
        return legacy_state.is_running

    def is_connected(self) -> bool:
        """Check if connected to game."""
        return legacy_state.is_connected

    def is_gm_detected(self) -> bool:
        """Check if GM was detected."""
        return legacy_state.is_gm_detected

    def is_safe(self) -> bool:
        """Check if safe to act (no alarm, no cooldown)."""
        return legacy_state.is_safe()

    def is_chat_paused(self) -> bool:
        """Check if paused for chat."""
        return legacy_state.is_chat_paused

    def trigger_alarm(self, is_gm: bool = False, reason: str = ""):
        """Trigger alarm state."""
        legacy_state.trigger_alarm(is_gm, reason)

    def clear_alarm(self, cooldown_seconds: float = 0.0):
        """Clear alarm state."""
        legacy_state.clear_alarm(cooldown_seconds)

    # =========================================================================
    # MODULE LOCK (for atomic action sequences)
    # =========================================================================

    def acquire_module_lock(self, module_name: str, timeout: float = 5.0) -> bool:
        """Acquire module lock for atomic sequences."""
        with self._lock:
            current_time = time.time()

            # Check timeout
            if self._active_module is not None:
                if current_time - self._module_lock_time > self._module_lock_timeout:
                    self._active_module = None
                elif self._active_module == module_name:
                    self._module_lock_time = current_time
                    return True
                else:
                    return False

            # Acquire
            self._active_module = module_name
            self._module_lock_time = current_time
            self._module_lock_timeout = timeout
            return True

    def release_module_lock(self, module_name: str):
        """Release module lock."""
        with self._lock:
            if self._active_module == module_name:
                self._active_module = None

    def is_module_active(self, module_name: str) -> bool:
        """Check if specific module holds lock."""
        with self._lock:
            return self._active_module == module_name

    def is_runemaking(self) -> bool:
        """Check if runemaker is active."""
        return legacy_state.is_runemaking

    def set_runemaking(self, value: bool):
        """Set runemaking state."""
        legacy_state.set_runemaking(value)

    # =========================================================================
    # DEBUG & STATS
    # =========================================================================

    def get_stats(self) -> dict:
        """Get polling statistics."""
        with self._lock:
            return {
                "update_count": self._update_count,
                "last_update_ms": self._update_duration_ms,
                "update_hz": 1.0 / self._update_interval if self._update_interval > 0 else 0,
                "creatures_cached": len(self._creatures),
                "players_cached": len(self._players),
                "containers_cached": len(self._containers),
                "map_tiles_cached": len(self._map_tiles),
                "active_module": self._active_module,
            }


# =========================================================================
# GLOBAL INSTANCE
# =========================================================================

game_state = GameState()


def init_game_state(pm, base_addr):
    """Initialize game state with Pymem instance."""
    game_state.init(pm, base_addr)


def shutdown_game_state():
    """Shutdown game state polling."""
    game_state.shutdown()
