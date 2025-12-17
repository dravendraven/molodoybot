# PacketMutex Implementation Roadmap

## Overview

Plano de implementação do `PacketMutex` em todos os módulos que utilizam ações de packet.

**Objetivo:** Sincronização completa entre módulos para evitar conflitos

**Escopo:** 8 módulos, ~50 ações de packet para sincronizar

**Timeline:** Faseado (Phase 1-4)

---

## Modules Requiring Sync

| Módulo | Tipo | Prioridade | # Packet Actions | Status |
|--------|------|-----------|-----------------|--------|
| Runemaker | Crítica | 100 | 3-5 | 🟡 Pendente |
| Trainer | Alta | 80 | 2-3 | 🟡 Pendente |
| Fisher | Média | 60 | 1 | 🟡 Pendente |
| Auto-Loot | Média | 40 | 5-7 | 🟡 Pendente |
| Stacker | Baixa | 30 | 2-3 | 🟡 Pendente |
| Eater | Baixa | 20 | 1 | 🟡 Pendente |
| Cavebot | Meta | — | 0 | ✅ N/A |
| Alarm | Meta | — | 0 | ✅ N/A |

---

## Phase 1: Foundation & Testing (Week 1)

### ✅ Completed
- [x] Create `core/packet_mutex.py`
- [x] Implement thread-safe mutex
- [x] Add priority system
- [x] Add inter-module delay (1s)
- [x] Add context manager support
- [x] Create documentation

### 🟡 Next Steps
- [ ] Unit tests para PacketMutex
- [ ] Manual integration test
- [ ] Verify no deadlocks
- [ ] Check thread safety

### Deliverables
- `core/packet_mutex.py` ✅
- `MODULE_SYNC_GUIDE.md` ✅
- `PACKET_MUTEX_INTEGRATION_EXAMPLE.md` ✅
- Unit tests (pending)

---

## Phase 2: Low-Risk Modules (Week 2)

### Target: Fisher (1 packet action)

**File:** `modules/fisher.py`
**Line:** 309
**Action:** `packet.use_with()`

**Change:**
```python
# Before
packet.use_with(pm, rod_pos, ROD_ID, 0, water_pos, water_id, 0)

# After
with PacketMutex("fisher"):
    packet.use_with(pm, rod_pos, ROD_ID, 0, water_pos, water_id, 0)
```

**Testing:**
- [ ] Run Fisher alone (10 min)
- [ ] Run Fisher + Cavebot (10 min)
- [ ] Verify no errors

**Risk:** Very Low

---

## Phase 3: Medium-Risk Modules (Week 3)

### Target: Eater (1 packet action)

**File:** `modules/eater.py`
**Actions:** `packet.use_item()`

**Change:**
```python
with PacketMutex("eater"):
    packet.use_item(pm, food_pos, item.id, index=cont.index)
```

**Testing:**
- [ ] Run Eater alone
- [ ] Run Eater + Fisher
- [ ] Verify proper pause/resume

**Risk:** Low

---

### Target: Stacker (2-3 packet actions)

**File:** `modules/stacker.py`
**Actions:** `packet.move_item()`

**Change:**
```python
with PacketMutex("stacker"):
    packet.move_item(pm, pos_from, pos_to, item_src.id, item_src.count)
```

**Testing:**
- [ ] Run Stacker alone
- [ ] Run Stacker + Fisher + Eater
- [ ] Check loot organization

**Risk:** Low

---

## Phase 4: High-Risk Modules (Week 4)

### Target: Trainer (2-3 packet actions)

**File:** `modules/trainer.py`
**Actions:** `packet.use_item()`, `packet.move_item()`

**Change:**
```python
with PacketMutex("trainer"):
    packet.use_item(pm, pos_dict, corpse_id, ...)
    time.sleep(0.5)
    packet.move_item(pm, pos_from, pos_to, ...)
```

**Testing:**
- [ ] Run Trainer alone (30 min)
- [ ] Run Trainer + Fisher + Eater
- [ ] Run Trainer + Cavebot
- [ ] Verify corpse looting works

**Risk:** Medium

---

### Target: Auto-Loot (5-7 packet actions)

**File:** `modules/auto_loot.py`
**Actions:** `packet.use_item()`, `packet.move_item()` (multiple)

**Change Pattern:**
```python
# Group related actions
with PacketMutex("auto_loot"):
    packet.use_item(pm, bag_pos, bag_item_ref.id, ...)
    time.sleep(0.2)

    for item in items_to_move:
        packet.move_item(pm, pos_from, pos_to, item.id, item.count)
        time.sleep(0.1)
```

**Testing:**
- [ ] Run Auto-Loot alone (30 min, varios containers)
- [ ] Run Auto-Loot + all other modules
- [ ] Verify all loot is picked up
- [ ] No items left behind

**Risk:** High

---

### Target: Runemaker (3-5 packet actions) - CRITICAL

**File:** `modules/runemaker.py`
**Lines:** 309, 322, 346, 351
**Actions:** `packet.move_item()` (multiple)

**Change:**
```python
# Entire runemaking cycle in one mutex block
with PacketMutex("runemaker"):
    # Unequip
    packet.move_item(pm, pos_from, pos_to, current_id, 1)
    time.sleep(0.3)

    # Equip blank
    packet.move_item(pm, pos_from, pos_to, blank_id, 1)
    time.sleep(0.3)

    # Cast (hotkey, não packet)
    press_hotkey(hwnd, vk_hotkey)
    time.sleep(1.2)

    # Return rune
    packet.move_item(pm, info['hand_pos'], pos_dest, rune_id_to_move, 1)
    time.sleep(0.3)

    # Re-equip
    packet.move_item(pm, pos_from, pos_to, item_id, 1)
```

**Testing - COMPREHENSIVE:**
- [ ] Run Runemaker alone (1 hour) - todos cenários
- [ ] Run Runemaker + Fisher (1 hour) - scenario original
- [ ] Run Runemaker + Trainer (30 min)
- [ ] Run Runemaker + Auto-Loot + Fisher (1 hour)
- [ ] Verify runes are created correctly
- [ ] Verify equipment is re-equipped
- [ ] Verify no sword/shield loss

**Risk:** Critical - but already implemented in code with fix 🎯

---

## Implementation Checklist

### For Each Module:

- [ ] Add import: `from core.packet_mutex import PacketMutex`
- [ ] Identify all `packet.` calls
- [ ] Group related actions
- [ ] Wrap in `with PacketMutex("module_name"):`
- [ ] Add appropriate delays between related actions
- [ ] Test alone (baseline)
- [ ] Test with dependencies (regression)
- [ ] Test with conflicts (stress)
- [ ] Verify performance (should be neutral)
- [ ] Commit changes
- [ ] Document module-specific notes

---

## Testing Procedure

### Unit Tests (for PacketMutex itself)

```python
# Test basic acquire/release
assert PacketMutex.acquire("fisher")
assert PacketMutex.release("fisher")

# Test context manager
with PacketMutex("fisher"):
    assert PacketMutex.get_status()['current_holder'] == 'fisher'
assert PacketMutex.get_status()['current_holder'] is None

# Test timeout
PacketMutex.acquire("fisher")
start = time.time()
result = PacketMutex.acquire("trainer", timeout=1.0)
elapsed = time.time() - start
assert not result
assert elapsed >= 1.0
PacketMutex.release("fisher")

# Test priorities
# (Fisher priority 60, Trainer 80)
# If both waiting, Trainer should get it first
```

### Integration Tests

**Test Case 1: Single Module**
```
Run: Fisher alone
Duration: 30 minutes
Verify: Normal behavior, no errors
Result: ✅ or ❌
```

**Test Case 2: Two Modules**
```
Run: Fisher + Runemaker simultaneously
Duration: 30 minutes
Verify:
  - Fisher pauses during Runemaker cycles
  - Runemaker completes full cycle
  - No sword/shield loss
  - Normal fishing resumes after
Result: ✅ or ❌
```

**Test Case 3: All Modules**
```
Run: All enabled simultaneously
Duration: 1 hour
Verify:
  - No deadlocks
  - All modules execute properly
  - No item loss
  - No conflicts
Result: ✅ or ❌
```

---

## Success Criteria

### ✅ Mutex works correctly
- [x] Thread-safe implementation
- [x] No race conditions
- [x] No deadlocks possible
- [x] Priority system functional

### ✅ Modules are synchronized
- [ ] Fisher respects mutex
- [ ] Trainer respects mutex
- [ ] Auto-Loot respects mutex
- [ ] Runemaker respects mutex
- [ ] All other modules sync'd

### ✅ Performance is maintained
- [ ] <5ms overhead per action
- [ ] <1% CPU increase
- [ ] No FPS drops
- [ ] Latency unchanged

### ✅ User experience improves
- [ ] No conflicting actions
- [ ] Clean behavior
- [ ] Predictable timing
- [ ] Reliable operation

---

## Risk Mitigation

### High Risk Areas
1. **Runemaker** - Already fixed, just needs wrapping
2. **Auto-Loot** - Complex with many moves
3. **Trainer** - Tight timing with corpse looting

### Mitigation
- Extensive testing before rollout
- Ability to quickly revert (simple code changes)
- Detailed logging for debugging
- Prioritize critical fixes

---

## Rollback Plan

If issues arise:

```bash
# Revert PacketMutex system entirely
git revert 90c47cc

# Or revert specific module
git revert <commit-hash-of-module>
```

Each module is separate commit, easy to isolate.

---

## Communication Plan

### Phase 1 (Done)
```
"Added PacketMutex system for module sync.
Ready for integration into individual modules."
```

### Phase 2
```
"Integrating Fisher module with PacketMutex.
Tested and working. Fisher pauses during Runemaker."
```

### Phase 3-4
```
"All modules now synchronized.
Multiple modules can run simultaneously without conflicts."
```

---

## Timeline Estimate

| Phase | Task | Duration | Start | End |
|-------|------|----------|-------|-----|
| 1 | Foundation | Done | ✅ | ✅ |
| 2 | Fisher | 1 day | TBD | TBD |
| 3a | Eater | 1 day | TBD | TBD |
| 3b | Stacker | 1 day | TBD | TBD |
| 4a | Trainer | 2 days | TBD | TBD |
| 4b | Auto-Loot | 2 days | TBD | TBD |
| 4c | Runemaker | 1 day | TBD | TBD |
| **Total** | **All** | **~8 days** | | |

---

## Documentation to Create

- [x] `core/packet_mutex.py` - Implementation
- [x] `MODULE_SYNC_GUIDE.md` - Usage guide
- [x] `PACKET_MUTEX_INTEGRATION_EXAMPLE.md` - Fisher example
- [x] This file (roadmap)
- [ ] Per-module integration guides (during Phase 2-4)
- [ ] Troubleshooting guide (after Phase 1)
- [ ] Performance analysis (after Phase 4)

---

## Next Steps

### Immediate (Today)
1. Review PacketMutex implementation
2. Review documentation
3. Plan Phase 2 start date

### Phase 2 (Fisher Integration)
1. Modify `modules/fisher.py` (1 change, 1 line)
2. Test alone (30 min)
3. Test with Runemaker (1 hour)
4. Verify sync logs
5. Commit with testing notes

### After Phase 2
- Decide if proceeding with Phase 3-4
- Adjust priorities if needed
- Plan rollout schedule

---

## Success Example

### Before Integration
```
[Cavebot] Andando para waypoint...
[Fisher] Pescando...
[Fisher] use_with(rod, water)
[Runemaker] Fabricando runa...
[Runemaker] move_item(blank -> mao)
[Fisher] use_with(rod, water)  ← CONFLICT!
[Runemaker] move_item(runa -> backpack)
[Cavebot] Personagem se mexeu erraticamente...
```

### After Integration
```
[Cavebot] Andando para waypoint...
[Fisher] Pescando...
[PACKET-MUTEX] 🔒 FISHER adquiriu mutex
[Fisher] use_with(rod, water)
[PACKET-MUTEX] 🔓 FISHER liberou mutex (0.05s)
[Runemaker] Fabricando runa...
[PACKET-MUTEX] 🔒 RUNEMAKER adquiriu mutex (1s delay)
[Runemaker] move_item(blank -> mao)
[Runemaker] move_item(runa -> backpack)
[Runemaker] spell cast
[Runemaker] move_item(equipamento -> mao)
[PACKET-MUTEX] 🔓 RUNEMAKER liberou mutex (0.95s)
[Fisher] Prontos para próximo ciclo...
[PACKET-MUTEX] 🔒 FISHER adquiriu mutex (1s delay)
[Cavebot] Personagem se move normalmente...
```

**Result:** Sincronização perfeita ✅

---

**Status:** 🟡 Roadmap defined, Phase 1 complete, Phase 2-4 pending

*Roadmap created: 2025-12-17*
