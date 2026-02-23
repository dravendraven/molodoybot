# modules/healer.py
"""
Healer Module - Automatic healing for self and friends.

Features:
- Priority-based rule system (user defines order)
- Self-healing with HP threshold
- Friend/party healing with individual rules
- Creature/summon healing by name
- Spells via packet.say() or runes via use_on_creature()
- Global heal cooldown (matches game's exhaust mechanic)
- HP threshold jitter for anti-detection (±3%)
"""

import time
import random
from dataclasses import dataclass
from typing import Optional, List, Dict, Any, Callable

from modules.base_module import BaseModule
from core.game_state import game_state
from core.packet import get_container_pos
from core.player_core import get_player_id
from modules.auto_loot import scan_containers


# =============================================================================
# CONSTANTS
# =============================================================================

HEALING_RUNES = {
    "IH": 3152,  # Intense Healing Rune
    "UH": 3160,  # Ultimate Healing Rune
}

HEALING_SPELLS = {
    "exura": {"mana": 20},
    "exura vita": {"mana": 40},
    "exura gran": {"mana": 70},
    "exura sio": {"mana": 120, "target": True},
}


# =============================================================================
# HEAL RULE DATACLASS
# =============================================================================

@dataclass
class HealRule:
    """
    A single healing rule with priority.

    Attributes:
        priority: Lower number = higher priority (executed first)
        enabled: Whether this rule is active
        target_type: "self" | "friend" | "creature"
        target_name: Name for friend/creature (empty for self)
        hp_below_percent: Heal when HP falls below this %
        method: "spell" | "rune"
        spell_or_rune: Spell words or rune type (e.g., "exura vita" or "UH")
    """
    priority: int
    enabled: bool
    target_type: str        # "self" | "friend" | "creature"
    target_name: str
    hp_below_percent: int
    method: str             # "spell" | "rune"
    spell_or_rune: str

    @classmethod
    def from_dict(cls, d: dict) -> 'HealRule':
        """Create HealRule from dictionary (loaded from settings)."""
        return cls(
            priority=d.get('priority', 99),
            enabled=d.get('enabled', True),
            target_type=d.get('target_type', 'self'),
            target_name=d.get('target_name', ''),
            hp_below_percent=d.get('hp_below_percent', 50),
            method=d.get('method', 'spell'),
            spell_or_rune=d.get('spell_or_rune', 'exura'),
        )

    def to_dict(self) -> dict:
        """Convert to dictionary for saving."""
        return {
            'priority': self.priority,
            'enabled': self.enabled,
            'target_type': self.target_type,
            'target_name': self.target_name,
            'hp_below_percent': self.hp_below_percent,
            'method': self.method,
            'spell_or_rune': self.spell_or_rune,
        }


# =============================================================================
# HEALER MODULE
# =============================================================================

class HealerModule(BaseModule):
    """
    Healer module for automatic HP healing.

    Features:
    - Priority-based rule system
    - ONE action per tick (no spamming)
    - Global heal cooldown (matches game exhaust)
    - ±3% threshold jitter for anti-detection
    - Graceful rune handling (skip if not found)
    """

    MODULE_NAME = "healer"
    THRESHOLD_JITTER = 3  # ±3% randomization

    def __init__(
        self,
        pm,
        base_addr: int,
        config_getter: Callable[[str, Any], Any] = None,
        log_callback: Callable[[str], None] = None
    ):
        super().__init__(pm, base_addr, config_getter, log_callback)
        self._rules: List[HealRule] = []
        self._rules_dirty = True  # Reload from settings on next cycle
        self._last_heal_time: float = 0.0  # Global cooldown tracker
        self._player_id: int = 0  # Cached player ID

    # =========================================================================
    # MAIN CYCLE
    # =========================================================================

    def run_cycle(self):
        """
        Main cycle - evaluate rules in priority order, execute first match.

        ONE action per tick to prevent packet spam.
        """
        # Check preconditions
        if not self.can_act():
            return

        # Check healer enabled in settings
        if not self.get_cfg('healer_enabled', False):
            return

        # Check GLOBAL cooldown (matches game's heal exhaust)
        if not self._is_heal_ready():
            return

        # Reload rules if settings changed
        if self._rules_dirty:
            self._load_rules()

        # Cache player ID if not set
        if self._player_id == 0:
            self._player_id = get_player_id(self.pm, self.base_addr)

        # Sort by priority (lower number = higher priority)
        sorted_rules = sorted(self._rules, key=lambda r: r.priority)

        for rule in sorted_rules:
            if not rule.enabled:
                continue

            # Resolve target and check HP
            target = self._resolve_target(rule)
            if target is None:
                continue

            # Apply jitter to threshold (±3%) for anti-detection
            jittered_threshold = rule.hp_below_percent + random.randint(
                -self.THRESHOLD_JITTER, self.THRESHOLD_JITTER
            )
            jittered_threshold = max(1, min(100, jittered_threshold))

            if target['hp_percent'] >= jittered_threshold:
                continue

            # Execute heal and return (ONE action per tick)
            success = self._execute_heal(rule, target)
            if success:
                self._last_heal_time = time.time()  # Update GLOBAL cooldown
            return  # Exit after first action attempt

    # =========================================================================
    # COOLDOWN
    # =========================================================================

    def _is_heal_ready(self) -> bool:
        """Check if global heal cooldown has elapsed."""
        cooldown_ms = self.get_cfg('healer_cooldown_ms', 2000)
        elapsed_ms = (time.time() - self._last_heal_time) * 1000
        return elapsed_ms >= cooldown_ms

    # =========================================================================
    # TARGET RESOLUTION
    # =========================================================================

    def _resolve_target(self, rule: HealRule) -> Optional[Dict]:
        """
        Resolve target type to creature_id and hp_percent.

        Returns:
            Dict with 'id', 'hp_percent', 'name' or None if target not found.
        """
        if rule.target_type == "self":
            hp, hp_max, hp_percent = game_state.get_player_hp()
            return {
                'id': self._player_id,
                'hp_percent': hp_percent,
                'name': 'self'
            }

        # For friend/creature: search battlelist by name
        target_name = rule.target_name.lower().strip()
        if not target_name:
            return None

        # Get all creatures (includes players and monsters)
        creatures = game_state.get_creatures()

        for creature in creatures:
            # Skip self
            if creature.id == self._player_id:
                continue

            # Match by name (case insensitive)
            if creature.name.lower() == target_name and creature.is_visible:
                return {
                    'id': creature.id,
                    'hp_percent': creature.hp_percent,
                    'name': creature.name
                }

        return None  # Target not found on screen

    # =========================================================================
    # HEAL EXECUTION
    # =========================================================================

    def _execute_heal(self, rule: HealRule, target: Dict) -> bool:
        """
        Execute the heal action.

        Returns:
            True on success, False otherwise.
        """
        if rule.method == "spell":
            return self._cast_spell(rule, target)
        else:
            return self._use_rune(rule, target)

    def _cast_spell(self, rule: HealRule, target: Dict) -> bool:
        """Cast healing spell via packet.say()."""
        spell_words = rule.spell_or_rune.strip()

        # For friend/creature targets, format as 'exura sio "Name"'
        if rule.target_type in ("friend", "creature") and rule.target_name:
            # exura sio requires target name
            if "sio" in spell_words.lower():
                spell_words = f'exura sio "{target["name"]}"'
            # Other spells might not support targeting
            elif rule.target_type != "self":
                self.log(f"Spell {spell_words} does not support targeting others")
                return False

        try:
            self.packet.say(spell_words)
            self.log(f"Healed {target['name']} with {spell_words}")
            return True
        except Exception as e:
            self.log(f"Spell error: {e}")
            return False

    def _use_rune(self, rule: HealRule, target: Dict) -> bool:
        """Use healing rune via packet.use_on_creature()."""
        rune_type = rule.spell_or_rune.upper().strip()
        rune_id = HEALING_RUNES.get(rune_type)

        if not rune_id:
            self.log(f"Unknown rune type: {rune_type}")
            return False

        # Find rune in containers
        rune_location = self._find_rune_in_backpack(rune_id)

        if rune_location is None:
            self.log(f"Runa {rune_type} nao encontrada!")
            return False  # Skip to next rule

        if rune_location['count'] <= 3:
            self.log(f"Poucas runas restantes: {rune_location['count']}")

        try:
            rune_pos = get_container_pos(
                rune_location['container_index'],
                rune_location['slot_index']
            )
            # Use OP_USE_ON_CREATURE (0x84) - same as aimbot
            self.packet.use_on_creature(
                from_pos=rune_pos,
                item_id=rune_id,
                stack_pos=0,
                creature_id=target['id']
            )
            self.log(f"Healed {target['name']} with {rune_type} rune")
            return True
        except Exception as e:
            self.log(f"Rune error: {e}")
            return False

    def _find_rune_in_backpack(self, rune_id: int) -> Optional[Dict]:
        """
        Find rune location and count in containers.

        Returns:
            Dict with 'container_index', 'slot_index', 'count' or None.
        """
        try:
            containers = scan_containers(self.pm, self.base_addr)

            for cont in containers:
                for item in cont.items:
                    if item.id == rune_id:
                        return {
                            'container_index': cont.index,
                            'slot_index': item.slot,
                            'count': item.count
                        }
        except Exception as e:
            self.log(f"Error scanning containers: {e}")

        return None

    # =========================================================================
    # SETTINGS
    # =========================================================================

    def _load_rules(self):
        """Load rules from settings and parse into HealRule objects."""
        rules_data = self.get_cfg('healer_rules', [])
        self._rules = [HealRule.from_dict(r) for r in rules_data if isinstance(r, dict)]
        self._rules_dirty = False
        self.log(f"Loaded {len(self._rules)} heal rules")

    def mark_rules_dirty(self):
        """Call when settings change to trigger reload."""
        self._rules_dirty = True

    # =========================================================================
    # LIFECYCLE
    # =========================================================================

    def on_start(self):
        """Called when module is started."""
        self._rules_dirty = True
        self._player_id = 0
        self.log("Healer started")

    def on_stop(self):
        """Called when module is stopped."""
        super().on_stop()
        self.log("Healer stopped")


# =============================================================================
# MODULE SINGLETON
# =============================================================================

_healer_module: Optional[HealerModule] = None


def get_healer_module() -> Optional[HealerModule]:
    """Get the global healer module instance."""
    return _healer_module


def init_healer_module(
    pm,
    base_addr: int,
    config_getter: Callable = None,
    log_callback: Callable = None
) -> HealerModule:
    """Initialize the global healer module instance."""
    global _healer_module
    _healer_module = HealerModule(pm, base_addr, config_getter, log_callback)
    return _healer_module
