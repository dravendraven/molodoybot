"""
Base Module - Abstract base class for all bot modules.

This module provides the BaseModule class that:
- Provides consistent action submission interface
- Handles module-specific configuration
- Tags actions with source_module automatically
- Provides common utility methods

Usage:
    from modules.base_module import BaseModule

    class EaterModule(BaseModule):
        MODULE_NAME = "eater"

        def run_cycle(self):
            if not self.is_enabled:
                return

            food = self.find_food()
            if food:
                self.submit_action(
                    ActionType.EAT,
                    execute_fn=lambda: self.packet.use_item(food.pos, food.id),
                    description=f"Eat {food.name}"
                )
"""

from abc import ABC, abstractmethod
from typing import Callable, Optional, Dict, Any
import time

from core.action_scheduler import get_scheduler
from core.action_types import Action, ActionType, ActionCategory, create_action
from core.game_state import game_state
from core.packet import PacketManager


class BaseModule(ABC):
    """
    Abstract base class for all bot modules.

    Provides:
    - Consistent action submission interface
    - Module-specific configuration access
    - Automatic source_module tagging
    - Common utility methods

    Subclasses must:
    - Set MODULE_NAME class attribute
    - Implement run_cycle() method
    """

    MODULE_NAME: str = "base"  # Override in subclass

    def __init__(
        self,
        pm,
        base_addr: int,
        config_getter: Callable[[str, Any], Any] = None,
        log_callback: Callable[[str], None] = None
    ):
        """
        Initialize the module.

        Args:
            pm: Pymem instance for memory access
            base_addr: Base address of Tibia process
            config_getter: Function to get config values: get(key, default) -> value
            log_callback: Optional function to log messages to GUI
        """
        self.pm = pm
        self.base_addr = base_addr
        self.packet = PacketManager(pm, base_addr)

        # Configuration getter (returns default if key not found)
        self._config_getter = config_getter or (lambda k, d=None: d)

        # Logging callback
        self._log = log_callback or (lambda msg: None)

        # Module state
        self._enabled = False
        self._last_cycle_time = 0.0
        self._cycle_count = 0

    # =========================================================================
    # CONFIGURATION
    # =========================================================================

    def get_cfg(self, key: str, default: Any = None) -> Any:
        """
        Get a configuration value.

        Args:
            key: Configuration key
            default: Default value if key not found

        Returns:
            Configuration value or default
        """
        try:
            return self._config_getter(key, default)
        except Exception:
            return default

    @property
    def is_enabled(self) -> bool:
        """Check if module is enabled (internal flag AND config)."""
        if not self._enabled:
            return False
        return self.get_cfg('enabled', False)

    def enable(self):
        """Enable the module."""
        self._enabled = True

    def disable(self):
        """Disable the module and clear pending actions."""
        self._enabled = False
        scheduler = get_scheduler()
        if scheduler:
            scheduler.clear_module_actions(self.MODULE_NAME)

    # =========================================================================
    # ACTION SUBMISSION
    # =========================================================================

    def submit_action(
        self,
        action_type: ActionType,
        execute_fn: Callable[[], bool],
        validate_fn: Callable[[], bool] = None,
        priority: int = None,
        expires_in: float = None,
        description: str = "",
        context: Dict[str, Any] = None
    ) -> bool:
        """
        Submit an action to the scheduler.

        The action is automatically tagged with this module's name.

        Args:
            action_type: Type of action (determines default priority and category)
            execute_fn: Function to execute the action (returns True on success)
            validate_fn: Optional late validation function (called at execution time)
            priority: Optional priority override (lower = higher priority)
            expires_in: Optional expiry time in seconds from now
            description: Human-readable description for debugging
            context: Optional context dict for validation

        Returns:
            True if submitted successfully, False otherwise
        """
        scheduler = get_scheduler()
        if scheduler is None:
            return False

        action = create_action(
            action_type=action_type,
            execute_fn=execute_fn,
            source_module=self.MODULE_NAME,
            validate_fn=validate_fn,
            priority=priority,
            expires_in=expires_in,
            description=description,
            context=context
        )

        return scheduler.submit(action)

    def submit_immediate(
        self,
        action_type: ActionType,
        execute_fn: Callable[[], bool],
        description: str = ""
    ) -> bool:
        """
        Submit an action for immediate execution (bypasses queue).

        Only use for STOP and ALARM_RESPONSE actions.

        Args:
            action_type: Type of action (should be STOP or ALARM_RESPONSE)
            execute_fn: Function to execute
            description: Description for debugging

        Returns:
            True if executed successfully
        """
        scheduler = get_scheduler()
        if scheduler is None:
            return False

        action = create_action(
            action_type=action_type,
            execute_fn=execute_fn,
            source_module=self.MODULE_NAME,
            description=description
        )

        return scheduler.submit_immediate(action)

    def clear_pending_actions(self):
        """Clear all pending actions from this module."""
        scheduler = get_scheduler()
        if scheduler:
            scheduler.clear_module_actions(self.MODULE_NAME)

    # =========================================================================
    # MODULE LOCK
    # =========================================================================

    def acquire_lock(self, timeout: float = 5.0) -> bool:
        """
        Acquire the module lock for atomic action sequences.

        Args:
            timeout: How long this module can hold the lock

        Returns:
            True if lock acquired
        """
        return game_state.acquire_module_lock(self.MODULE_NAME, timeout)

    def release_lock(self):
        """Release the module lock."""
        game_state.release_module_lock(self.MODULE_NAME)

    def has_lock(self) -> bool:
        """Check if this module holds the lock."""
        return game_state.is_module_active(self.MODULE_NAME)

    # =========================================================================
    # STATE CHECKS
    # =========================================================================

    def can_act(self) -> bool:
        """
        Check if module can perform actions.

        Returns True if:
        - Module is enabled
        - Bot is running
        - Connected to game
        - No GM detected
        """
        if not self.is_enabled:
            return False
        if not game_state.is_bot_running():
            return False
        if not game_state.is_connected():
            return False
        if game_state.is_gm_detected():
            return False
        return True

    def is_safe_to_act(self) -> bool:
        """
        Check if safe to perform actions (no alarm, not paused).

        More strict than can_act() - also checks alarm and chat pause.
        """
        if not self.can_act():
            return False
        if not game_state.is_safe():
            return False
        if game_state.is_chat_paused():
            return False
        return True

    # =========================================================================
    # LOGGING
    # =========================================================================

    def log(self, message: str):
        """Log a message (if log callback is set)."""
        try:
            self._log(f"[{self.MODULE_NAME}] {message}")
        except Exception:
            pass

    def log_debug(self, message: str):
        """Log a debug message (only if debug enabled in config)."""
        if self.get_cfg('debug', False):
            self.log(f"[DEBUG] {message}")

    # =========================================================================
    # ABSTRACT METHODS
    # =========================================================================

    @abstractmethod
    def run_cycle(self):
        """
        Main module logic - called repeatedly by the module's thread.

        Should:
        1. Check preconditions (is_enabled, can_act, etc.)
        2. Read game state (memory)
        3. Decide what action to take (if any)
        4. Submit action via submit_action()

        Should NOT:
        - Directly call packet methods (use submit_action instead)
        - Block for long periods
        - Have complex validation logic (put in validate_fn)

        Example:
            def run_cycle(self):
                if not self.can_act():
                    return

                # Read state
                food = self.find_food()
                if not food:
                    return

                # Submit action
                self.submit_action(
                    ActionType.EAT,
                    execute_fn=lambda: self.packet.use_item(food.pos, food.id),
                    validate_fn=lambda: self.is_food_still_there(food),
                    description=f"Eat {food.name}"
                )
        """
        pass

    # =========================================================================
    # LIFECYCLE
    # =========================================================================

    def on_start(self):
        """Called when module is started. Override for initialization."""
        pass

    def on_stop(self):
        """Called when module is stopped. Override for cleanup."""
        self.clear_pending_actions()
        if self.has_lock():
            self.release_lock()

    def tick(self):
        """
        Single tick of the module - calls run_cycle with bookkeeping.

        Called by the module's thread loop.
        """
        self._last_cycle_time = time.time()
        self._cycle_count += 1

        try:
            self.run_cycle()
        except Exception as e:
            self.log(f"Error in run_cycle: {e}")

    def get_stats(self) -> dict:
        """Get module statistics for debugging."""
        return {
            "module_name": self.MODULE_NAME,
            "enabled": self._enabled,
            "is_enabled": self.is_enabled,
            "cycle_count": self._cycle_count,
            "last_cycle_time": self._last_cycle_time,
            "has_lock": self.has_lock(),
        }
