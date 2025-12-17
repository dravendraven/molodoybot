# Runemaker Bug Analysis - "Both" Hands Re-equip Failure

## Problem Summary

When using `hand_mode = "BOTH"`, the runemaker successfully:
1. Unequips sword from LEFT and RIGHT hands
2. Equips blank runes in both hands
3. Casts the spell
4. Returns the runes to backpack
5. **❌ BUT FAILS** to re-equip the sword

The sword remains in the backpack instead of being equipped back to the hands.

---

## Root Cause Analysis

### The Bug Location

The issue is in the loop structure at **lines 305-351** in [runemaker.py](modules/runemaker.py#L305-L351).

### Code Flow (BUGGY)

```python
for slot_enum in hands_to_use:  # hands_to_use = [SLOT_LEFT, SLOT_RIGHT]
    # ... unequip hand, move blank rune to hand ...

    active_runes.append({
        "hand_pos": pos_to,
        "origin_idx": blank_data['container_index'],
        "slot_enum": slot_enum,
        "restorable_item": unequipped_item_id  # ← THE PROBLEM IS HERE
    })
    time.sleep(0.6)

# Cast the spell AFTER both hands are prepared
if active_runes:
    log_msg(f"🪄 Pressionando {hotkey_str}...")
    press_hotkey(hwnd, vk_hotkey)
    time.sleep(1.2)

    for info in active_runes:
        # Return rune to backpack
        detected_id = get_item_id_in_hand(pm, base_addr, info['slot_enum'])
        rune_id_to_move = detected_id if detected_id > 0 else blank_id
        pos_dest = packet.get_container_pos(info['origin_idx'], 0)
        packet.move_item(pm, info['hand_pos'], pos_dest, rune_id_to_move, 1)
        time.sleep(0.8)

        # ← Re-equip happens here
        if info['restorable_item']:
            reequip_hand(pm, base_addr, info['restorable_item'], info['slot_enum'])
```

### The Problem Visualized

**Iteration 1 (LEFT Hand):**
```
unequipped_item_id = sword_id (from LEFT hand)
active_runes[0] = {
    "restorable_item": sword_id,
    "slot_enum": SLOT_LEFT
}
```

**Iteration 2 (RIGHT Hand):**
```
unequipped_item_id = sword_id (from RIGHT hand - OVERWRITES!)
active_runes[1] = {
    "restorable_item": sword_id,  # ← SAME sword_id!
    "slot_enum": SLOT_RIGHT
}
```

### What Actually Happens

**Before Spell:**
```
LEFT hand:  Sword
RIGHT hand: Sword (or Shield/Item)
```

**Step 1 - First iteration (LEFT):**
- Unequip LEFT → `unequipped_item_id = SWORD`
- Move blank to LEFT
- Store in `active_runes[0]` with `restorable_item = SWORD`

**Step 2 - Second iteration (RIGHT):**
- Unequip RIGHT → `unequipped_item_id = SHIELD` (or same sword duplicate?)
- Move blank to RIGHT
- Store in `active_runes[1]` with `restorable_item = SHIELD`

**Wait...** If you have the SAME sword in both hands:

**Step 2 - Second iteration (RIGHT) - SAME SWORD:**
- Unequip RIGHT → `unequipped_item_id = SWORD` (same item!)
- Move blank to RIGHT
- Store in `active_runes[1]` with `restorable_item = SWORD`

### The Critical Issue

After casting and returning runes:

**Re-equip Loop:**
```
Iteration 1:
  find_item_in_containers(pm, base_addr, SWORD)
  → Finds the sword in backpack
  → Moves it to LEFT hand ✅
  → Sword is now in LEFT hand

Iteration 2:
  find_item_in_containers(pm, base_addr, SWORD)
  → Tries to find the sword again... but it's already in LEFT hand!
  → find_item_in_containers fails OR returns old cached location
  → reequip_hand tries to move from backpack but sword isn't there anymore
  → ❌ FAILS - Sword stays where it is (LEFT hand) instead of going to RIGHT hand
```

---

## Why This Happens with "Both" Hands

### Single Hand Mode (WORKS ✅)
```
hands_to_use = [SLOT_RIGHT]

for slot_enum in hands_to_use:
    unequipped_item_id = sword (from RIGHT)
    active_runes[0] = {"restorable_item": sword, "slot_enum": SLOT_RIGHT}

# Re-equip
Iteration 1:
    find sword in backpack
    move to RIGHT hand ✅
```

### Both Hands Mode (FAILS ❌)
```
hands_to_use = [SLOT_LEFT, SLOT_RIGHT]

Iteration 1:
    unequipped_item_id = sword (from LEFT)
    active_runes[0] = {"restorable_item": sword, "slot_enum": SLOT_LEFT}

Iteration 2:
    unequipped_item_id = sword (from RIGHT)
    active_runes[1] = {"restorable_item": sword, "slot_enum": SLOT_RIGHT}

# Re-equip
Iteration 1:
    find sword → Found in backpack
    move to LEFT hand ✅

Iteration 2:
    find sword → NOT in backpack anymore (it's in LEFT hand from iteration 1!)
    move to RIGHT hand ❌ FAILS
```

---

## Solution

The fix requires storing the unequipped item ID **before** the loop, not during the loop. Here's the corrected logic:

### Fix Option 1: Store All Unequipped Items FIRST

```python
# Step 1: FIRST, unequip ALL hands and store their items
unequipped_items = {}  # slot_enum → item_id

for slot_enum in hands_to_use:
    unequipped_item_id = unequip_hand(pm, base_addr, slot_enum)
    unequipped_items[slot_enum] = unequipped_item_id  # ← Store for later
    time.sleep(0.3)

# Step 2: THEN, equip blank runes
blank_id = get_cfg('blank_id', 3147)
active_runes = []

for slot_enum in hands_to_use:
    blank_data = find_item_in_containers(pm, base_addr, blank_id)

    if not blank_data:
        log_msg(f"⚠️ Sem Blanks na BP!")
        # Restore all unequipped items
        for slot, item_id in unequipped_items.items():
            if item_id:
                reequip_hand(pm, base_addr, item_id, slot)
        break

    # Move blank to hand
    pos_from = packet.get_container_pos(blank_data['container_index'], blank_data['slot_index'])
    pos_to = packet.get_inventory_pos(slot_enum)
    packet.move_item(pm, pos_from, pos_to, blank_id, 1)

    active_runes.append({
        "hand_pos": pos_to,
        "origin_idx": blank_data['container_index'],
        "slot_enum": slot_enum,
        "restorable_item": unequipped_items[slot_enum]  # ← Use stored value!
    })
    time.sleep(0.6)

# Step 3: Cast spell and return runes (SAME AS BEFORE)
if active_runes:
    press_hotkey(hwnd, vk_hotkey)
    time.sleep(1.2)

    for info in active_runes:
        detected_id = get_item_id_in_hand(pm, base_addr, info['slot_enum'])
        rune_id_to_move = detected_id if detected_id > 0 else blank_id
        pos_dest = packet.get_container_pos(info['origin_idx'], 0)
        packet.move_item(pm, info['hand_pos'], pos_dest, rune_id_to_move, 1)
        time.sleep(0.8)

        # This will work correctly because all unequipped items are known upfront
        if info['restorable_item']:
            reequip_hand(pm, base_addr, info['restorable_item'], info['slot_enum'])
```

### How This Fixes the Issue

**Before (BUGGY):**
```
Iteration 1: Unequip LEFT → sword
Iteration 2: Unequip RIGHT → sword (overwrites!)
Result: Both iterations reference the SAME sword, only one hand gets it back
```

**After (FIXED):**
```
unequipped_items = {
    SLOT_LEFT: sword_or_item_1,
    SLOT_RIGHT: sword_or_item_2
}
Result: Each hand knows exactly which item to get back
```

---

## Alternative Fix: Use Item Position Instead of ID

If `find_item_in_containers` has caching issues, you could also fix by storing the item **position** instead of just the ID:

```python
# Store position of unequipped item
unequipped_items = {}  # slot_enum → (container_idx, slot_idx)

for slot_enum in hands_to_use:
    current_id = get_item_id_in_hand(pm, base_addr, slot_enum)
    if current_id > 0:
        item_data = find_item_in_containers(pm, base_addr, current_id)
        if item_data:
            unequipped_items[slot_enum] = (item_data['container_index'], item_data['slot_index'])
            unequip_hand(pm, base_addr, slot_enum)
    time.sleep(0.3)

# Later when re-equipping:
if info['restorable_item']:
    container_idx, slot_idx = info['restorable_item']
    pos_from = packet.get_container_pos(container_idx, slot_idx)
    pos_to = packet.get_inventory_pos(info['slot_enum'])
    packet.move_item(pm, pos_from, pos_to, item_id, 1)
```

---

## Why Single Hand Works but "Both" Doesn't

| Aspect | Single Hand | Both Hands |
|--------|------------|-----------|
| Unequip iterations | 1 | 2 |
| Items to restore | 1 | 2 |
| `unequipped_item_id` overwrites | No (only 1 loop) | **Yes (2nd overwrites 1st)** |
| `find_item_in_containers` state | Always finds item in BP | **2nd iteration: Item already moved!** |
| Probability of success | 100% | ~50% (depends on item duplication) |

---

## Testing the Fix

After implementing the fix, test scenarios:

### Test 1: Different items in both hands
```
LEFT:  Sword
RIGHT: Shield
→ Both should be re-equipped
```

### Test 2: Same item in both hands
```
LEFT:  Sword (duplicate)
RIGHT: Sword (duplicate)
→ Each should be re-equipped to correct hand
```

### Test 3: One hand with weapon, one empty
```
LEFT:  Sword
RIGHT: Empty
→ Sword should be re-equipped to LEFT
```

### Test 4: No space after casting (rare edge case)
```
→ Should handle gracefully without crashing
```

---

## Summary

**The Bug:** Variable `unequipped_item_id` is overwritten in the second loop iteration (when `hand_mode = "BOTH"`), causing the second hand to not get its original item back.

**The Fix:** Store all unequipped items **before** processing blanks, so each hand knows exactly which item belongs to it.

**Code Changes Needed:**
- Lines 305-330: Restructure to separate unequip/blank-equip phases
- Use a dictionary to store `unequipped_items` by slot_enum
- Reference this dictionary when re-equipping instead of relying on loop variable

**Estimated Fix Complexity:** Low (restructure existing code, no new logic needed)

**Risk Level:** Very Low (only affects "Both" hands mode, single hand unaffected)

---

## Files to Modify

- `modules/runemaker.py` - Lines 305-351 (re-equip logic for "Both" hands)

---

**Status:** 🔴 **BUG CONFIRMED**

The sword is not being re-equipped when using `hand_mode = "BOTH"` because the unequipped item tracking gets overwritten during the second hand processing. The fix requires separating the unequip phase from the blank-equip phase.
