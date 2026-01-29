"""
Eater Module - Automatic food consumption.

This module provides two implementations:
1. Legacy: attempt_eat() - Direct packet sending (original)
2. New: EaterModule - Action scheduler based (Phase 2 migration)

Use USE_ACTION_SCHEDULER flag to switch between implementations.
"""

import time
from typing import Optional, Tuple, Any, Callable

from core.packet import PacketManager, get_container_pos
from config import *
from modules.auto_loot import scan_containers, is_player_full
from core.bot_state import state
from core.player_core import is_player_moving

# Feature flag for migration - set to True to use new action scheduler
USE_ACTION_SCHEDULER = False


# =============================================================================
# NEW IMPLEMENTATION - Action Scheduler Based
# =============================================================================

class EaterModule:
    """
    Eater module using the action scheduler system.

    Instead of sending packets directly, this module:
    1. Scans containers for food
    2. Submits an EAT action to the scheduler
    3. The scheduler executes with proper timing and validation
    """

    MODULE_NAME = "eater"

    def __init__(
        self,
        pm,
        base_addr: int,
        config_getter: Callable[[str, Any], Any] = None,
        log_callback: Callable[[str], None] = None
    ):
        self.pm = pm
        self.base_addr = base_addr
        self.packet = PacketManager(pm, base_addr)

        self._config_getter = config_getter or (lambda _k, d=None: d)
        self._log = log_callback or (lambda msg: print(msg))

        self._enabled = False
        self._last_eat_time = 0.0
        self._eat_cooldown = 1.0  # Minimum seconds between eat attempts

        # Track pending eat action to avoid duplicates
        self._eat_pending = False

    def get_cfg(self, key: str, default: Any = None) -> Any:
        """Get configuration value."""
        try:
            return self._config_getter(key, default)
        except Exception:
            return default

    @property
    def is_enabled(self) -> bool:
        """Check if module is enabled."""
        return self._enabled and self.get_cfg('enabled', False)

    def enable(self):
        """Enable the module."""
        self._enabled = True

    def disable(self):
        """Disable the module."""
        self._enabled = False
        self._eat_pending = False

    def find_food(self) -> Optional[Tuple[int, int, int, int, str]]:
        """
        Scan containers for food.

        Returns:
            Tuple of (container_index, slot, item_id, food_pos, food_name) or None
        """
        try:
            containers = scan_containers(self.pm, self.base_addr)
            if not containers:
                return None

            for cont in containers:
                for slot, item in enumerate(cont.items):
                    if item.id in FOOD_IDS:
                        food_name = foods_db.get_food_name(item.id)
                        food_pos = get_container_pos(cont.index, slot)
                        return (cont.index, slot, item.id, food_pos, food_name)

            return None
        except Exception:
            return None

    def is_full(self) -> bool:
        """Check if player is full."""
        try:
            return is_player_full(self.pm, self.base_addr)
        except Exception:
            return False

    def run_cycle(self):
        """
        Main module cycle - called repeatedly.

        Checks for food and submits eat action to scheduler.
        """
        if not self.is_enabled:
            return

        # Check cooldown
        if time.time() - self._last_eat_time < self._eat_cooldown:
            return

        # Don't queue if already pending
        if self._eat_pending:
            return

        # Check if player is full
        if self.is_full():
            return

        # Find food
        food = self.find_food()
        if not food:
            return

        container_index, slot, item_id, food_pos, food_name = food

        # Import here to avoid circular imports
        from core.action_scheduler import get_scheduler
        from core.action_types import ActionType
        from core.game_state import game_state

        scheduler = get_scheduler()
        if scheduler is None:
            return

        # Create validation function (late validation)
        def validate_eat():
            # Check if runemaking
            if game_state.is_runemaking():
                return False
            # Check if safe to act
            if not game_state.can_send_mouse_action():
                return False
            # Check if food still exists at position
            current_food = self.find_food()
            if not current_food:
                return False
            # Verify it's the same food (or any food is fine)
            return True

        # Create execute function
        def execute_eat():
            try:
                # Re-find food in case position changed
                current_food = self.find_food()
                if not current_food:
                    self._eat_pending = False
                    return False

                c_idx, c_slot, c_item_id, c_food_pos, c_food_name = current_food

                self._log(f"[Eater] Comendo {c_food_name} (ID: {c_item_id})")
                self.packet.use_item(c_food_pos, c_item_id, index=c_idx)

                self._last_eat_time = time.time()
                self._eat_pending = False

                # Clear food satiation flag after eating
                # This resets the "You are full" state so we can try eating again
                # if regen time decreases (not about inventory capacity)
                from core.game_state import game_state
                game_state.clear_fullness_flag()

                return True
            except Exception as e:
                self._log(f"[Eater] Erro ao comer: {e}")
                self._eat_pending = False
                return False

        # Submit action
        from core.action_types import Action, ActionCategory

        action = Action(
            action_type=ActionType.EAT,
            execute_fn=execute_eat,
            validate_fn=validate_eat,
            source_module=self.MODULE_NAME,
            description=f"Eat {food_name}",
            expires_at=time.time() + 3.0,  # Expire in 3 seconds
            context={
                "container_index": container_index,
                "slot": slot,
                "item_id": item_id,
                "food_name": food_name
            }
        )

        if scheduler.submit(action):
            self._eat_pending = True
            self._log(f"[Eater] Ação de comer agendada: {food_name}")


# Global module instance (initialized lazily)
_eater_module: Optional[EaterModule] = None


def get_eater_module() -> Optional[EaterModule]:
    """Get the global eater module instance."""
    return _eater_module


def init_eater_module(pm, base_addr, config_getter=None, log_callback=None) -> EaterModule:
    """Initialize the global eater module."""
    global _eater_module
    _eater_module = EaterModule(pm, base_addr, config_getter, log_callback)
    return _eater_module


# =============================================================================
# LEGACY IMPLEMENTATION - Direct Packet Sending
# =============================================================================

def attempt_eat(pm, base_addr, hwnd):
    """
    Tenta comer usando Packet Injection.

    LEGACY: Esta função envia pacotes diretamente.
    Para usar o novo sistema com action scheduler, use EaterModule.
    """
    # If using action scheduler, delegate to module
    if USE_ACTION_SCHEDULER and _eater_module is not None:
        _eater_module.run_cycle()
        return False  # Action is queued, not immediate

    # --- Original implementation below ---

    # Protege ciclo de runemaking - não come durante runemaking
    if state.is_runemaking:
        return False

    # Não come enquanto personagem está andando
    if is_player_moving(pm, base_addr):
        return False

    containers = scan_containers(pm, base_addr)

    # DEBUG 1: Verifica se achou containers
    if not containers:
        print("[DEBUG] scan_containers retornou lista vazia! Erro de leitura ou bolsas fechadas.")
        return False

    # PacketManager para envio de pacotes
    packet = PacketManager(pm, base_addr)

    for cont in containers:
        for slot, item in enumerate(cont.items):
            if item.id in FOOD_IDS:
                f_name = foods_db.get_food_name(item.id)
                print(f"[DEBUG] Comida encontrada: {f_name} ID: {item.id} no Container {cont.index}, Slot {slot}")

                food_pos = get_container_pos(cont.index, slot)

                packet.use_item(food_pos, item.id, index=cont.index)

                # Clear food satiation flag after eating (legacy support)
                # Resets "You are full" state - not about inventory capacity
                from core.game_state import game_state
                game_state.clear_fullness_flag()

                # Pequena pausa para garantir que o servidor processe
                time.sleep(0.6)

                if is_player_full(pm, base_addr):
                    print("[DEBUG] Personagem está cheio (FULL).")
                    return "FULL"

                print(f"[DEBUG] Comeu com sucesso. Retornando ID: {item.id}")
                return item.id

    return False