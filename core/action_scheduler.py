"""
Action Scheduler - Central action queue with single executor.

This module provides the ActionScheduler class that:
- Maintains a priority queue of pending actions
- Executes actions one at a time in priority order
- Validates actions at execution time (late validation)
- Enforces Tibia game restrictions (mouse blocked during movement)
- Applies humanized timing between actions
- Retries mouse actions that were blocked by movement

Usage:
    from core.action_scheduler import init_scheduler, get_scheduler

    # Initialize once during startup
    init_scheduler(pm, base_addr)

    # Get scheduler instance
    scheduler = get_scheduler()

    # Submit actions
    scheduler.submit(action)
"""

import threading
import time
import heapq
import random
from typing import List, Optional, Tuple, Callable
from dataclasses import dataclass, field
from collections import deque

from core.action_types import Action, ActionType, ActionCategory
from core.player_core import is_player_moving

# Humanization constants (in milliseconds)
MIN_ACTION_INTERVAL_MS = 80     # Minimum ms between any actions
MAX_ACTION_INTERVAL_MS = 150    # Maximum delay (prevents excessive waiting)
JITTER_STD_MS = 15              # Standard deviation for timing jitter
IDLE_POLL_MS = 10               # Polling interval when queue is empty

# Retry settings for blocked mouse actions
MAX_BLOCKED_RETRIES = 10        # Maximum times to retry a blocked action
BLOCKED_RETRY_TIMEOUT_S = 3.0   # Timeout for blocked actions


@dataclass(order=True)
class PrioritizedAction:
    """Wrapper for heap ordering: (priority, sequence, action)."""
    priority: int
    sequence: int  # Tie-breaker for same priority (FIFO order)
    action: Action = field(compare=False)


class ActionScheduler:
    """
    Central action queue and executor.

    Single point of control for all game actions:
    - Priority queue for action ordering
    - Single executor thread (eliminates race conditions)
    - Late validation before execution
    - Game restriction enforcement (mouse blocked during walk)
    - Humanized timing between actions
    - Automatic retry for blocked mouse actions

    Thread Safety:
    - All public methods are thread-safe
    - Internal state protected by _queue_lock
    - Only the executor thread sends packets
    """

    def __init__(self, pm, base_addr):
        """
        Initialize the action scheduler.

        Args:
            pm: Pymem instance for memory access
            base_addr: Base address of Tibia process
        """
        self.pm = pm
        self.base_addr = base_addr

        # Priority queue: List[PrioritizedAction]
        self._queue: List[PrioritizedAction] = []
        self._queue_lock = threading.Lock()
        self._sequence = 0  # Monotonic counter for FIFO ordering

        # Blocked mouse actions waiting for movement to stop
        self._blocked_actions: deque = deque(maxlen=50)
        self._blocked_lock = threading.Lock()

        # Executor state
        self._running = False
        self._executor_thread: Optional[threading.Thread] = None
        self._last_action_time = 0.0

        # Statistics (for debugging)
        self._stats = {
            "submitted": 0,
            "executed": 0,
            "expired": 0,
            "blocked": 0,
            "invalid": 0,
        }
        self._stats_lock = threading.Lock()

        # Callbacks for state checking (set via set_state_checker)
        self._can_send_mouse: Callable[[], bool] = lambda: True
        self._can_send_keyboard: Callable[[], bool] = lambda: True

    def set_state_checker(
        self,
        can_send_mouse: Callable[[], bool],
        can_send_keyboard: Callable[[], bool]
    ):
        """
        Set callbacks for state validation.

        These are called before executing actions to check global state
        (e.g., GM detected, alarm active).

        Args:
            can_send_mouse: Returns True if mouse actions are allowed
            can_send_keyboard: Returns True if keyboard actions are allowed
        """
        self._can_send_mouse = can_send_mouse
        self._can_send_keyboard = can_send_keyboard

    def start(self):
        """Start the executor thread."""
        if self._running:
            return

        self._running = True
        self._executor_thread = threading.Thread(
            target=self._executor_loop,
            name="ActionScheduler",
            daemon=True
        )
        self._executor_thread.start()

    def stop(self):
        """Stop the executor thread and clear queues."""
        self._running = False
        if self._executor_thread:
            self._executor_thread.join(timeout=2.0)
            self._executor_thread = None
        self.clear_queue()

    def is_running(self) -> bool:
        """Check if scheduler is running."""
        return self._running

    def submit(self, action: Action) -> bool:
        """
        Submit an action to the queue.

        The action will be executed when:
        1. It reaches the front of the priority queue
        2. Its validate_fn returns True
        3. Game state allows its category (mouse/keyboard)

        Args:
            action: Action to submit

        Returns:
            True if submitted, False if rejected
        """
        if not self._running:
            return False

        # Immediate actions bypass the queue
        if action.is_immediate():
            return self._execute_immediate(action)

        with self._queue_lock:
            self._sequence += 1
            pa = PrioritizedAction(
                priority=action.get_priority(),
                sequence=self._sequence,
                action=action
            )
            heapq.heappush(self._queue, pa)

        with self._stats_lock:
            self._stats["submitted"] += 1

        return True

    def submit_immediate(self, action: Action) -> bool:
        """
        Execute an action immediately, bypassing the queue.

        Used for STOP and ALARM_RESPONSE actions.
        Still respects timing delays.

        Args:
            action: Action to execute immediately

        Returns:
            True if executed successfully
        """
        return self._execute_immediate(action)

    def clear_queue(self):
        """Clear all pending actions."""
        with self._queue_lock:
            self._queue.clear()
        with self._blocked_lock:
            self._blocked_actions.clear()

    def clear_module_actions(self, module_name: str):
        """
        Remove all pending actions from a specific module.

        Useful when a module is disabled or needs to cancel pending work.

        Args:
            module_name: Name of the module whose actions to remove
        """
        with self._queue_lock:
            self._queue = [
                pa for pa in self._queue
                if pa.action.source_module != module_name
            ]
            heapq.heapify(self._queue)

        with self._blocked_lock:
            self._blocked_actions = deque(
                (a for a in self._blocked_actions
                 if a.source_module != module_name),
                maxlen=50
            )

    def get_queue_size(self) -> int:
        """Get current queue size."""
        with self._queue_lock:
            return len(self._queue)

    def get_blocked_count(self) -> int:
        """Get number of blocked mouse actions."""
        with self._blocked_lock:
            return len(self._blocked_actions)

    def get_stats(self) -> dict:
        """Get execution statistics."""
        with self._stats_lock:
            return dict(self._stats)

    def peek_next(self) -> Optional[Action]:
        """Peek at the next action without removing it."""
        with self._queue_lock:
            if self._queue:
                return self._queue[0].action
        return None

    # ==================== Private Methods ====================

    def _executor_loop(self):
        """Main executor loop - runs in dedicated thread."""
        while self._running:
            action = self._get_next_action()

            if action is None:
                time.sleep(IDLE_POLL_MS / 1000)
                continue

            # Apply humanized timing between actions
            self._apply_timing_delay()

            # Execute the action
            success = self._execute_action(action)

            if not success and action.is_mouse_action():
                # Mouse action blocked - queue for retry
                self._queue_blocked(action)

    def _get_next_action(self) -> Optional[Action]:
        """
        Get the next action to execute.

        Priority order:
        1. Blocked mouse actions (if player stopped moving)
        2. Priority queue (highest priority first)

        Skips expired actions.
        """
        # First, check if blocked mouse actions can be retried
        if not self._is_player_moving():
            action = self._pop_blocked()
            if action and not action.is_expired():
                return action

        # Then check priority queue
        with self._queue_lock:
            while self._queue:
                pa = heapq.heappop(self._queue)
                action = pa.action

                # Skip expired actions
                if action.is_expired():
                    with self._stats_lock:
                        self._stats["expired"] += 1
                    continue

                # For mouse actions, check if blocked by movement
                if action.is_mouse_action() and self._is_player_moving():
                    self._queue_blocked(action)
                    continue

                return action

        return None

    def _execute_action(self, action: Action) -> bool:
        """
        Execute a single action.

        Returns True if executed successfully.
        """
        # Late validation - check if action is still valid
        if not action.is_valid():
            with self._stats_lock:
                self._stats["invalid"] += 1
            return False

        # Category-specific game state check
        if action.is_mouse_action():
            if not self._can_send_mouse():
                return False
            if self._is_player_moving():
                return False
        else:
            if not self._can_send_keyboard():
                return False

        # Execute the action
        try:
            result = action.execute_fn()
            self._last_action_time = time.time()

            with self._stats_lock:
                self._stats["executed"] += 1

            return bool(result)
        except Exception as e:
            print(f"[ActionScheduler] Error executing {action.action_type.name}: {e}")
            return False

    def _execute_immediate(self, action: Action) -> bool:
        """Execute an action immediately (bypasses queue)."""
        # Still apply minimal delay for humanization
        self._apply_timing_delay()
        return self._execute_action(action)

    def _apply_timing_delay(self):
        """Apply humanized delay between actions."""
        elapsed_ms = (time.time() - self._last_action_time) * 1000

        if elapsed_ms < MIN_ACTION_INTERVAL_MS:
            # Calculate remaining delay with jitter
            remaining = MIN_ACTION_INTERVAL_MS - elapsed_ms
            jitter = random.gauss(0, JITTER_STD_MS)
            delay_ms = min(MAX_ACTION_INTERVAL_MS, max(10, remaining + jitter))
            time.sleep(delay_ms / 1000)

    def _is_player_moving(self) -> bool:
        """Check if player is currently moving."""
        try:
            return is_player_moving(self.pm, self.base_addr)
        except Exception:
            return False

    def _queue_blocked(self, action: Action):
        """Queue a mouse action that was blocked by movement."""
        with self._blocked_lock:
            # Check if already at retry limit
            retry_count = action.context.get("_retry_count", 0)
            if retry_count >= MAX_BLOCKED_RETRIES:
                with self._stats_lock:
                    self._stats["expired"] += 1
                return

            # Check if blocked too long
            blocked_time = action.context.get("_blocked_time", time.time())
            if time.time() - blocked_time > BLOCKED_RETRY_TIMEOUT_S:
                with self._stats_lock:
                    self._stats["expired"] += 1
                return

            # Update retry metadata
            action.context["_retry_count"] = retry_count + 1
            if "_blocked_time" not in action.context:
                action.context["_blocked_time"] = time.time()

            self._blocked_actions.append(action)

            with self._stats_lock:
                self._stats["blocked"] += 1

    def _pop_blocked(self) -> Optional[Action]:
        """Pop the oldest blocked action."""
        with self._blocked_lock:
            if self._blocked_actions:
                return self._blocked_actions.popleft()
        return None


# ==================== Global Instance ====================

_scheduler: Optional[ActionScheduler] = None
_scheduler_lock = threading.Lock()


def init_scheduler(pm, base_addr) -> ActionScheduler:
    """
    Initialize the global scheduler instance.

    Should be called once during bot startup after Pymem is attached.

    Args:
        pm: Pymem instance
        base_addr: Base address of Tibia process

    Returns:
        The initialized ActionScheduler instance
    """
    global _scheduler

    with _scheduler_lock:
        if _scheduler is not None:
            _scheduler.stop()

        _scheduler = ActionScheduler(pm, base_addr)
        _scheduler.start()
        return _scheduler


def get_scheduler() -> Optional[ActionScheduler]:
    """
    Get the global scheduler instance.

    Returns None if not initialized.
    """
    return _scheduler


def stop_scheduler():
    """Stop and cleanup the global scheduler."""
    global _scheduler

    with _scheduler_lock:
        if _scheduler is not None:
            _scheduler.stop()
            _scheduler = None
