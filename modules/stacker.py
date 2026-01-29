"""
Stacker Module - Automatic item stacking.

This module provides two implementations:
1. Legacy: auto_stack_items() - Direct packet sending (original)
2. New: StackerModule - Action scheduler based (Phase 3 migration)

Use USE_ACTION_SCHEDULER flag to switch between implementations.
"""

import time
from typing import Optional, Tuple, Any, Callable

from config import *
from core.packet import PacketManager, get_container_pos
from core.packet_mutex import PacketMutex
from utils.timing import gauss_wait
from core.bot_state import state
from database.lootables_db import is_stackable
# NOTA: imports de auto_loot são LAZY dentro das funções
# para evitar circular import com auto_loot.py

# Feature flag for migration - set to True to use new action scheduler
USE_ACTION_SCHEDULER = False


# =============================================================================
# NEW IMPLEMENTATION - Action Scheduler Based
# =============================================================================

class StackerModule:
    """
    Stacker module using the action scheduler system.

    Instead of sending packets directly, this module:
    1. Queries game_state for container data
    2. Finds stackable items to merge
    3. Submits MOVE_ITEM actions to the scheduler
    4. The scheduler executes with proper timing
    """

    MODULE_NAME = "stacker"

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
        self._last_stack_time = 0.0
        self._stack_cooldown = 0.5  # Seconds between stack attempts
        self._stack_pending = False
        self._stack_submit_time = 0.0  # Timestamp when action was submitted
        self._pending_timeout = 2.0  # Timeout to reset stuck pending flag

    def get_cfg(self, key: str, default: Any = None) -> Any:
        """Get configuration value."""
        try:
            return self._config_getter(key, default)
        except Exception:
            return default

    @property
    def is_enabled(self) -> bool:
        """Check if module is enabled."""
        return self._enabled

    def enable(self):
        """Enable the module."""
        self._enabled = True

    def disable(self):
        """Disable the module."""
        self._enabled = False
        self._stack_pending = False

    def find_stackable_pair(self, loot_ids: list = None) -> Optional[Tuple[int, int, int, int, int]]:
        """
        Find a pair of stackable items to merge.

        Returns:
            Tuple of (container_index, src_slot, dst_slot, item_id, count) or None
        """
        from core.game_state import game_state

        # Get loot_ids from config if not provided
        if loot_ids is None:
            loot_ids = self.get_cfg('loot_ids', [])
            if not loot_ids:
                # Fallback to LOOT_IDS from config
                loot_ids = LOOT_IDS if not USE_CONFIGURABLE_LOOT_SYSTEM else []

        containers = game_state.get_containers()
        if not containers:
            return None

        # Get player containers only (not loot corpses)
        my_containers = [c for c in containers if not c.is_loot_container]

        for cont in my_containers:
            for i, item_dst in enumerate(cont.items):
                # Target must be stackable and not full
                if (item_dst.count < 100 and
                    item_dst.id in loot_ids and
                    is_stackable(item_dst.id)):

                    # Find source item to merge
                    for j, item_src in enumerate(cont.items):
                        if (item_src.id == item_dst.id and
                            item_src.slot_index > item_dst.slot_index and
                            item_src.count < 100):

                            return (
                                cont.index,
                                item_src.slot_index,  # Source slot
                                item_dst.slot_index,  # Destination slot
                                item_src.id,
                                item_src.count
                            )

        return None

    def run_cycle(self):
        """
        Main module cycle - called repeatedly.

        Checks for stackable items and submits move action to scheduler.
        """
        if not self.is_enabled:
            return

        # Check cooldown
        cooldown_remaining = self._stack_cooldown - (time.time() - self._last_stack_time)
        if cooldown_remaining > 0:
            return

        # Don't queue if already pending (with timeout recovery)
        if self._stack_pending:
            elapsed = time.time() - self._stack_submit_time
            # Safety timeout: reset if pending for too long (action expired/failed)
            if elapsed > self._pending_timeout:
                self._stack_pending = False
                self._log(f"[Stacker] Pending flag timeout after {elapsed:.1f}s - resetting")
            else:
                self._log(f"[Stacker] Waiting for pending action ({elapsed:.1f}s / {self._pending_timeout}s)")
                return

        # Check runemaking protection
        from core.game_state import game_state
        if game_state.is_runemaking():
            self._log("[Stacker] Skipping - runemaking active")
            return

        # Find stackable pair
        pair = self.find_stackable_pair()
        if not pair:
            return

        container_index, src_slot, dst_slot, item_id, count = pair
        self._log(f"[Stacker] Found pair: item {item_id} x{count} (slot {src_slot} -> {dst_slot}) in container {container_index}")

        # Get scheduler
        from core.action_scheduler import get_scheduler
        from core.action_types import ActionType, Action

        scheduler = get_scheduler()
        if scheduler is None:
            self._log("[Stacker] ERROR: Scheduler not available")
            return

        # Create validation function (late validation)
        # NOTE: We don't re-validate the pair here because:
        # 1. Containers may change during auto_loot, causing false negatives
        # 2. If the pair no longer exists, move_item will simply fail silently
        # 3. The pending timeout will recover from stuck states
        def validate_stack():
            # Re-check runemaking
            if game_state.is_runemaking():
                self._log("[Stacker] Validation FAILED: runemaking active")
                return False
            # Check if safe to act (not moving, no alarm, etc.)
            if not game_state.can_send_mouse_action():
                self._log("[Stacker] Validation FAILED: can_send_mouse_action=False (moving/alarm)")
                return False
            self._log("[Stacker] Validation PASSED - executing")
            return True

        # Capture positions for closure
        pos_from = get_container_pos(container_index, src_slot)
        pos_to = get_container_pos(container_index, dst_slot)

        # Create execute function
        def execute_stack():
            try:
                self._log(f"[Stacker] EXECUTING: item {item_id} x{count} (slot {src_slot} -> {dst_slot})")
                self.packet.move_item(pos_from, pos_to, item_id, count)

                self._last_stack_time = time.time()
                self._stack_pending = False
                self._log(f"[Stacker] SUCCESS: item {item_id} merged, pending=False")
                return True
            except Exception as e:
                self._log(f"[Stacker] EXECUTE ERROR: {e}")
                self._stack_pending = False
                return False

        # Submit action
        action = Action(
            action_type=ActionType.MOVE_ITEM,
            execute_fn=execute_stack,
            validate_fn=validate_stack,
            source_module=self.MODULE_NAME,
            description=f"Stack item {item_id}",
            expires_at=time.time() + 2.0,  # Expire in 2 seconds
            context={
                "container_index": container_index,
                "src_slot": src_slot,
                "dst_slot": dst_slot,
                "item_id": item_id
            }
        )

        if scheduler.submit(action):
            self._stack_pending = True
            self._stack_submit_time = time.time()  # Track when submitted for timeout
            self._log(f"[Stacker] Action SUBMITTED: item {item_id}, pending=True")
        else:
            self._log(f"[Stacker] Action REJECTED by scheduler: item {item_id}")


# Global module instance (initialized lazily)
_stacker_module: Optional[StackerModule] = None


def get_stacker_module() -> Optional[StackerModule]:
    """Get the global stacker module instance."""
    return _stacker_module


def init_stacker_module(pm, base_addr, config_getter=None, log_callback=None) -> StackerModule:
    """Initialize the global stacker module."""
    global _stacker_module
    _stacker_module = StackerModule(pm, base_addr, config_getter, log_callback)
    return _stacker_module


# =============================================================================
# LEGACY IMPLEMENTATION - Direct Packet Sending
# =============================================================================

def auto_stack_items(pm, base_addr, hwnd, my_containers_count=None, mutex_context=None, loot_ids=None):
    """
    Agrupa itens empilhaveis via Pacotes.

    LEGACY: Esta funcao envia pacotes diretamente.
    Para usar o novo sistema com action scheduler, use StackerModule.

    Args:
        pm: Memory reader instance
        base_addr: Base address of player in memory
        hwnd: Window handle
        my_containers_count: Numero de containers proprios (None = deteccao automatica)
        mutex_context: Contexto de mutex externo (ex: fisher_ctx) para reutilizar lock
        loot_ids: Lista de IDs para stackar (None = usar fallback baseado na flag)
    """
    # If using action scheduler, delegate to module
    if USE_ACTION_SCHEDULER and _stacker_module is not None:
        _stacker_module.run_cycle()
        return False  # Action is queued, not immediate

    # --- Original implementation below ---

    # Protege ciclo de runemaking - nao stacka durante runemaking
    if state.is_runemaking:
        return False

    # NOVO: Fallback baseado na flag se loot_ids nao fornecido
    if loot_ids is None:
        if USE_CONFIGURABLE_LOOT_SYSTEM:
            # Modo novo: tentar ler de BOT_SETTINGS
            try:
                from main import BOT_SETTINGS
                loot_ids = BOT_SETTINGS.get('loot_ids', [])
            except ImportError:
                loot_ids = []
        else:
            # Modo antigo: usar LOOT_IDS hardcoded
            loot_ids = LOOT_IDS

    # Import lazy para evitar circular import
    from modules.auto_loot import scan_containers, get_player_containers, USE_AUTO_CONTAINER_DETECTION
    containers = scan_containers(pm, base_addr)

    # Determina containers do player
    if my_containers_count is not None:
        # Parametro explicito: usa sistema antigo (compatibilidade)
        limit = int(my_containers_count)
        my_containers = [c for c in containers if c.index < limit]
    elif USE_AUTO_CONTAINER_DETECTION:
        # Deteccao automatica via hasparent + tracking temporal
        my_containers = get_player_containers(containers)
    else:
        # Fallback: config padrao
        my_containers = [c for c in containers if c.index < MY_CONTAINERS_COUNT]

    # PacketManager para envio de pacotes
    packet = PacketManager(pm, base_addr)

    for cont in my_containers:
        for i, item_dst in enumerate(cont.items):

            # Alvo valido? (deve ser empilhavel - flag Cumulative)
            if item_dst.count < 100 and item_dst.id in loot_ids and is_stackable(item_dst.id):

                # Procura doador
                for j, item_src in enumerate(cont.items):

                    # Regras de Stack (Mesmo ID, Slot Diferente, Nao Cheio)
                    if (item_src.id == item_dst.id and
                        item_src.slot_index > item_dst.slot_index and
                        item_src.count < 100):

                        print(f"[Stacker] Merging item {item_src.id}")

                        # Origem: Slot Doador
                        pos_from = get_container_pos(cont.index, item_src.slot_index)

                        # Destino: Slot Receptor
                        pos_to = get_container_pos(cont.index, item_dst.slot_index)

                        gauss_wait(0.2, 20)

                        # Executa Movimento (com mutex se contexto fornecido)
                        if mutex_context:
                            # Reutiliza mutex do fisher (mesmo grupo FISHER_GROUP)
                            with PacketMutex("stacker"):
                                packet.move_item(pos_from, pos_to, item_src.id, item_src.count)
                        else:
                            packet.move_item(pos_from, pos_to, item_src.id, item_src.count)
                        gauss_wait(0.3, 20)
                        return True

    return False
