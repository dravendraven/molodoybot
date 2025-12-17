# PacketMutex Integration Example

## Overview

Exemplo de como integrar o `PacketMutex` no módulo Fisher para evitar conflitos com Runemaker.

---

## Current Fisher Code (Line 300-335)

```python
# 4. EXECUÇÃO
# -----
water_pos = packet.get_ground_pos(abs_x, abs_y, pz)

# CALCULA DELAY (COM FADIGA)
human_wait = calculate_human_delay(dx, dy, fatigue_count, fatigue_limit)
time.sleep(human_wait)

cap_before = get_player_cap(pm, base_addr)
packet.use_with(pm, rod_pos, ROD_ID, 0, water_pos, water_id, 0)  # ← PACKET ACTION

# Atualiza Contadores
session_total_casts += 1
if is_fatigue_enabled:
    fatigue_count += 1

time.sleep(random.uniform(0.6, 0.8))

# Rest logic...
```

---

## Problem Scenario

```
T+0.0s: Fisher executa packet.use_with(rod, water)
T+0.1s: Runemaker requisita mutex para começar ciclo
T+0.2s: Runemaker aguarda que Fisher termine
T+0.3s: Fisher ainda dormindo (random.uniform(0.6, 0.8)) ← problema!
        Runemaker quer começar move_item mas Fisher não libera
```

**Resultado:** Sincronização quebra porque Fisher não libera rapidamente

---

## Solution 1: Wrap use_with (Simple)

```python
from core.packet_mutex import PacketMutex

# 4. EXECUÇÃO
water_pos = packet.get_ground_pos(abs_x, abs_y, pz)

# CALCULA DELAY (COM FADIGA)
human_wait = calculate_human_delay(dx, dy, fatigue_count, fatigue_limit)
time.sleep(human_wait)

cap_before = get_player_cap(pm, base_addr)

# Wrap apenas a ação de packet
with PacketMutex("fisher"):
    packet.use_with(pm, rod_pos, ROD_ID, 0, water_pos, water_id, 0)

# Atualiza Contadores fora do mutex
session_total_casts += 1
if is_fatigue_enabled:
    fatigue_count += 1

time.sleep(random.uniform(0.6, 0.8))
```

**Benefício:** Libera mutex imediatamente após use_with, deixando Runemaker começar

**Fluxo:**
```
T+0.0s: Fisher espera (0.3-0.8s human_delay)
T+0.3s: Fisher adquire mutex
T+0.4s: Fisher executa use_with + libera mutex
T+0.4s: Runemaker pode adquirir mutex (com 1s delay)
T+1.4s: Runemaker inicia ações
T+2.0s: Runemaker termina e libera
T+2.0s: Fisher próximo ciclo (no sleep normal)
```

---

## Solution 2: Wrap Full Cycle (Comprehensive)

```python
from core.packet_mutex import PacketMutex

with PacketMutex("fisher"):
    # 4. EXECUÇÃO
    water_pos = packet.get_ground_pos(abs_x, abs_y, pz)

    # CALCULA DELAY (COM FADIGA)
    human_wait = calculate_human_delay(dx, dy, fatigue_count, fatigue_limit)
    time.sleep(human_wait)

    cap_before = get_player_cap(pm, base_addr)
    packet.use_with(pm, rod_pos, ROD_ID, 0, water_pos, water_id, 0)

    # Atualiza Contadores
    session_total_casts += 1
    if is_fatigue_enabled:
        fatigue_count += 1

    time.sleep(random.uniform(0.6, 0.8))

# Rest logic outside mutex...
```

**Benefício:** Garante que toda a ação e seus efeitos sejam atômicos

**Trade-off:** Mutex mantém por mais tempo (0.6-1.8s)

---

## Solution 3: Hybrid (Recommended)

```python
from core.packet_mutex import PacketMutex

# Prepare fora do mutex (não é ação de packet)
water_pos = packet.get_ground_pos(abs_x, abs_y, pz)

# CALCULA DELAY (COM FADIGA)
human_wait = calculate_human_delay(dx, dy, fatigue_count, fatigue_limit)
time.sleep(human_wait)

cap_before = get_player_cap(pm, base_addr)

# Execute ação de packet dentro do mutex
with PacketMutex("fisher"):
    packet.use_with(pm, rod_pos, ROD_ID, 0, water_pos, water_id, 0)
    time.sleep(0.1)  # Pequeno delay para garantir pacote chega

# Cleanup fora do mutex
session_total_casts += 1
if is_fatigue_enabled:
    fatigue_count += 1

time.sleep(random.uniform(0.6, 0.8))
```

**Benefício:** Melhor balanço entre sincronização e performance

**Fluxo:**
```
T+0.0s: Fisher prepara (get_ground_pos, delay)
T+0.3s: Fisher adquire mutex
T+0.4s: Fisher executa use_with
T+0.5s: Fisher libera mutex (rápido!)
T+0.5s: Fisher atualiza contadores
T+1.0s: Fisher dorme até próximo ciclo
T+1.5s: Runemaker pode pegar mutex (1s delay após liberação)
T+2.5s: Runemaker começa
T+3.2s: Runemaker termina
```

---

## Comparison Matrix

| Aspecto | Solution 1 | Solution 2 | Solution 3 |
|---------|-----------|-----------|-----------|
| Sincronização | ✅ Boa | ✅✅ Ótima | ✅ Boa |
| Performance | ✅✅ Melhor | ⚠️ Slower | ✅ Melhor |
| Complexidade | ✅ Simples | ⚠️ Média | ✅ Simples |
| Segurança | ✅ Seguro | ✅✅ Mais seguro | ✅ Seguro |
| **Recomendado** | ⭐ | | ⭐⭐ |

---

## Step-by-Step Integration

### Step 1: Import PacketMutex

At the top of `modules/fisher.py`:

```python
import time
import random
import traceback
import math
from core import packet
from config import *
from core.inventory_core import find_item_in_containers, find_item_in_equipment
from core.map_core import get_player_pos
from modules.stacker import auto_stack_items
from database import fishing_db
from core.memory_map import MemoryMap
from core.config_utils import make_config_getter
from core.packet_mutex import PacketMutex  # ← ADD THIS
```

### Step 2: Modify Line 309 Area

**Before:**
```python
cap_before = get_player_cap(pm, base_addr)
packet.use_with(pm, rod_pos, ROD_ID, 0, water_pos, water_id, 0)
```

**After:**
```python
cap_before = get_player_cap(pm, base_addr)

with PacketMutex("fisher"):
    packet.use_with(pm, rod_pos, ROD_ID, 0, water_pos, water_id, 0)
```

### Step 3: Test

Run Fisher with Runemaker enabled:

```
Fisher e Runemaker rodando simultaneamente
↓
Verificar logs de sincronização:
  [PACKET-MUTEX] 🔒 FISHER adquiriu mutex
  [PACKET-MUTEX] 🔓 FISHER liberou mutex (duração: 0.05s)
  [PACKET-MUTEX] 🔒 RUNEMAKER adquiriu mutex
  [PACKET-MUTEX] 🔓 RUNEMAKER liberou mutex (duração: 0.95s)
↓
✅ Sem conflitos!
```

---

## Similar Changes for Other Modules

### Runemaker (Line 309, 346, 351)

```python
# Before
packet.move_item(pm, pos_from, pos_to, current_id, 1)

# After
with PacketMutex("runemaker"):
    packet.move_item(pm, pos_from, pos_to, current_id, 1)
```

### Trainer (move_item calls)

```python
# Before
packet.move_item(pm, food_pos, pos_ground, item.id, item.count)

# After
with PacketMutex("trainer"):
    packet.move_item(pm, food_pos, pos_ground, item.id, item.count)
```

### Auto-Loot (use_item and move_item)

```python
# Before
packet.use_item(pm, bag_pos, bag_item_ref.id, index=cont.index)
packet.move_item(pm, food_pos, pos_ground, item.id, item.count)

# After
with PacketMutex("auto_loot"):
    packet.use_item(pm, bag_pos, bag_item_ref.id, index=cont.index)
    time.sleep(0.2)
    packet.move_item(pm, food_pos, pos_ground, item.id, item.count)
```

---

## Debugging

### Check Current Status

```python
from core.packet_mutex import get_packet_mutex_status

status = get_packet_mutex_status()
print(status)
# {
#     'current_holder': 'fisher',
#     'waiting_modules': ['runemaker', 'trainer'],
#     'last_action_time': 1702894523.45,
#     'time_since_last_action': 0.32
# }
```

### Enable Verbose Logging

PacketMutex já loga automaticamente:

```
[PACKET-MUTEX] 🔒 FISHER adquiriu mutex
[PACKET-MUTEX] 🔓 FISHER liberou mutex (duração: 0.05s)
[PACKET-MUTEX] 🔒 RUNEMAKER adquiriu mutex
[PACKET-MUTEX] 💡 Aguardando FISHER liberar... (5 segundos)
[PACKET-MUTEX] 🔓 RUNEMAKER liberou mutex (duração: 0.95s)
```

---

## Expected Behavior After Integration

### Fisher + Runemaker Together

**Before Integration:**
```
❌ Mouse/personagem se move erraticamente
❌ Ações se cruzam
❌ Runes não são criadas corretamente
❌ Fisher continua enquanto Runemaker deveria estar fazendo ações
```

**After Integration:**
```
✅ Fisher pausa quando Runemaker começa
✅ Runemaker executa ciclo completo sem interrupção
✅ Fisher retoma após Runemaker terminar
✅ Behavior é previsível e sincronizado
```

---

## Performance Notes

- **Overhead:** ~1-2ms por acquire/release
- **Mutex lock duration:** 50-100ms (ação rápida)
- **Delay between modules:** 1s (configurable)
- **Total impact:** Negligible

---

## Rollout Plan

1. **Phase 1:** Integrar Fisher (baixo risco)
2. **Phase 2:** Integrar Runemaker (crítico)
3. **Phase 3:** Integrar Trainer
4. **Phase 4:** Integrar Auto-Loot, Stacker, Eater

---

## Files to Modify

```
modules/fisher.py        - Add PacketMutex to use_with (line 309)
modules/runemaker.py     - Add PacketMutex to all move_item (lines 309, 346, 351)
modules/trainer.py       - Add PacketMutex to use_item + move_item
modules/auto_loot.py     - Add PacketMutex to use_item + move_item
modules/stacker.py       - Add PacketMutex to move_item
modules/eater.py         - Add PacketMutex to use_item
```

---

## Summary

PacketMutex garante sincronização limpa entre módulos com integração mínima:

- Add 1 import
- Wrap packet calls com `with PacketMutex("module_name"):`
- Pronto!

**Resultado:** Múltiplos módulos rodando simultaneamente sem conflitos ✅

---

*Exemplo criado: 2025-12-17*
