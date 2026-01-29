"""
Action Types and Data Structures for the Action Queue System.

This module defines the core types used by the action scheduler:
- ActionType: Enum of all possible game actions with default priorities
- ActionCategory: KEYBOARD vs MOUSE (for movement blocking rules)
- Action: Dataclass representing an intention to perform a game action
"""

from enum import IntEnum
from dataclasses import dataclass, field
from typing import Callable, Optional, Any, Dict
import time


class ActionType(IntEnum):
    """
    Action types ordered by default priority (lower value = higher priority).

    Tibia game rules:
    - KEYBOARD actions (attack, walk, stop) allowed during movement
    - MOUSE actions (use_item, move_item) blocked during movement
    """
    # Critical - never delayed, bypass queue
    STOP = 10               # Emergency stop movement
    ALARM_RESPONSE = 20     # GM detected, logout

    # Combat - high priority
    ATTACK = 100            # Attack a creature
    FOLLOW = 110            # Follow a creature (pre-attack)

    # Movement - medium-high priority
    WALK = 200              # Walk to adjacent tile

    # Item manipulation - medium priority (blocked during walk)
    USE_ITEM = 300          # Open corpse, use ladder, click item
    USE_WITH = 310          # Rope, shovel, fishing rod
    MOVE_ITEM = 320         # Loot item, stack, pickup spear

    # Low priority - opportunistic actions
    EAT = 400               # Eat food
    EQUIP = 410             # Equip/unequip item

    # Utility - lowest priority
    SAY = 500               # Chat message
    LOOK = 510              # Look at something


class ActionCategory(IntEnum):
    """
    Categories for game restriction validation.

    Tibia 7.72 blocks mouse actions during player movement.
    Keyboard actions (hotkeys) are always allowed.
    """
    KEYBOARD = 1    # walk, attack, stop, spell - allowed during movement
    MOUSE = 2       # use_item, move_item - blocked during movement
    ANY = 3         # say, quit - no movement restrictions


# Map action types to their categories
ACTION_CATEGORY_MAP: Dict[ActionType, ActionCategory] = {
    ActionType.STOP: ActionCategory.KEYBOARD,
    ActionType.ALARM_RESPONSE: ActionCategory.ANY,
    ActionType.ATTACK: ActionCategory.KEYBOARD,
    ActionType.FOLLOW: ActionCategory.KEYBOARD,
    ActionType.WALK: ActionCategory.KEYBOARD,
    ActionType.USE_ITEM: ActionCategory.MOUSE,
    ActionType.USE_WITH: ActionCategory.MOUSE,
    ActionType.MOVE_ITEM: ActionCategory.MOUSE,
    ActionType.EAT: ActionCategory.MOUSE,
    ActionType.EQUIP: ActionCategory.MOUSE,
    ActionType.SAY: ActionCategory.ANY,
    ActionType.LOOK: ActionCategory.MOUSE,
}


def get_category(action_type: ActionType) -> ActionCategory:
    """Get the category for an action type."""
    return ACTION_CATEGORY_MAP.get(action_type, ActionCategory.MOUSE)


@dataclass
class Action:
    """
    Represents an intention to perform a game action.

    Modules create Actions and submit them to the scheduler.
    The scheduler validates and executes them in priority order.

    Key concepts:
    - execute_fn: Called when the action is executed
    - validate_fn: Called at execution time (late validation) to check if action is still valid
    - expires_at: Actions expire if not executed within timeout
    - context: Arbitrary data for validation (e.g., target_id, container_index)

    Example:
        action = Action(
            action_type=ActionType.ATTACK,
            execute_fn=lambda: packet.attack(target_id),
            validate_fn=lambda: is_creature_alive(target_id),
            source_module="trainer",
            description="Attack Rat #12345",
            expires_in=2.0,  # Expire if not executed within 2 seconds
            context={"target_id": 12345}
        )
    """
    action_type: ActionType

    # Execution function - returns True if successful
    execute_fn: Callable[[], bool]

    # Late validation - called just before execution (default: always valid)
    validate_fn: Callable[[], bool] = field(default=lambda: True)

    # Metadata
    source_module: str = ""
    description: str = ""

    # Priority override (None = use default from action_type)
    priority: Optional[int] = None

    # Timing
    created_at: float = field(default_factory=time.time)
    expires_at: Optional[float] = None  # None = never expires

    # Context data for validation and debugging
    context: Dict[str, Any] = field(default_factory=dict)

    # Category (auto-derived if not specified)
    _category: Optional[ActionCategory] = field(default=None, repr=False)

    def __post_init__(self):
        """Set derived fields after initialization."""
        if self._category is None:
            self._category = get_category(self.action_type)

    @property
    def category(self) -> ActionCategory:
        """Get the action category."""
        return self._category if self._category is not None else get_category(self.action_type)

    def get_priority(self) -> int:
        """Returns effective priority (custom or default from action_type)."""
        if self.priority is not None:
            return self.priority
        return int(self.action_type)

    def is_expired(self) -> bool:
        """Check if action has expired."""
        if self.expires_at is None:
            return False
        return time.time() > self.expires_at

    def is_valid(self) -> bool:
        """
        Late validation - called just before execution.

        Returns False if:
        - Action has expired
        - validate_fn returns False
        - validate_fn raises an exception
        """
        if self.is_expired():
            return False
        try:
            return self.validate_fn()
        except Exception:
            return False

    def age_ms(self) -> float:
        """Return the age of this action in milliseconds."""
        return (time.time() - self.created_at) * 1000

    def time_until_expiry_ms(self) -> Optional[float]:
        """Return milliseconds until expiry, or None if no expiry."""
        if self.expires_at is None:
            return None
        return max(0, (self.expires_at - time.time()) * 1000)

    def is_immediate(self) -> bool:
        """Check if this action should bypass the queue."""
        return self.action_type in (ActionType.STOP, ActionType.ALARM_RESPONSE)

    def is_mouse_action(self) -> bool:
        """Check if this is a mouse action (blocked during movement)."""
        return self.category == ActionCategory.MOUSE

    def __repr__(self) -> str:
        status = "expired" if self.is_expired() else "valid"
        return (
            f"Action({self.action_type.name}, "
            f"module={self.source_module}, "
            f"priority={self.get_priority()}, "
            f"status={status}, "
            f"desc={self.description!r})"
        )


def create_action(
    action_type: ActionType,
    execute_fn: Callable[[], bool],
    source_module: str,
    validate_fn: Callable[[], bool] = None,
    priority: int = None,
    expires_in: float = None,
    description: str = "",
    context: Dict[str, Any] = None
) -> Action:
    """
    Factory function to create an Action with common defaults.

    Args:
        action_type: Type of action (determines default priority and category)
        execute_fn: Function to execute the action
        source_module: Name of the module creating this action
        validate_fn: Optional late validation function
        priority: Optional priority override (lower = higher priority)
        expires_in: Optional expiry time in seconds from now
        description: Human-readable description for debugging
        context: Optional context dict for validation

    Returns:
        Configured Action instance
    """
    return Action(
        action_type=action_type,
        execute_fn=execute_fn,
        validate_fn=validate_fn if validate_fn else lambda: True,
        source_module=source_module,
        description=description,
        priority=priority,
        expires_at=time.time() + expires_in if expires_in else None,
        context=context or {}
    )
