# Fisher Memory Map Fix

## Problema
Fisher não conseguia ler todos os 165 tiles visíveis na tela (15x11) porque `get_tile()` retornava `None` para posições fora dos bounds do chunk atual. Alguns tiles de água em chunks adjacentes não eram identificados.

## Causa Raiz
- `memory_map.get_tile()` valida rigorosamente: `0 ≤ target < 18` e `0 ≤ target < 14`
- Fisher precisa ver toda tela visível (15x11 = 165 tiles)
- Player está no centro da tela do jogo
- Tiles visíveis podem estar em chunks diferentes (wrap-around necessário)

## Solução
Adicionado novo método `get_tile_visible()` que ignora bounds e usa wrap-around para cobrir chunks adjacentes:

### 1. Adicionar método no MemoryMap

**Arquivo:** `core/memory_map.py` (linhas 139-168)

```python
def get_tile_visible(self, rel_x, rel_y):
    """Retorna tile com suporte a chunks adjacentes (wrap-around)"""
    if not self.is_calibrated or self.center_index == -1:
        return None

    target_x = 8 + rel_x + self.offset_x
    target_y = 6 + rel_y + self.offset_y

    # Usa wrap-around para cobrir chunks adjacentes
    final_x = target_x % 18
    final_y = target_y % 14
    final_z = self.offset_z

    index = final_x + (final_y * 18) + (final_z * 18 * 14)

    if 0 <= index < TOTAL_TILES and self.tiles[index]:
        return self.tiles[index]

    return None
```

### 2. Atualizar Fisher para usar novo método

**Arquivo:** `modules/fisher.py` (linha 214)

**Antes:**
```python
tile = mapper.get_tile(dx, dy)
```

**Depois:**
```python
tile = mapper.get_tile_visible(dx, dy)
```

## Impacto
- ✅ Fisher lê 100% dos 165 tiles visíveis da tela (15x11)
- ✅ Nenhum tile perdido mesmo em borders de chunks
- ✅ Funciona com wrap-around para chunks adjacentes
- ✅ `get_tile()` continua seguro para pathfinding (sem wrap-around)
- ✅ `get_tile_visible()` é específico para detecção (com wrap-around)

## Como Funciona
```
Chunk 18x14:    Player na posição (8, 6)
┌──────────────────────────┐
│        chunk 0           │  dx = -7 a +8 (15 tiles)
│    ┌─────────────┐       │  dy = -5 a +6 (11 tiles)
│    │ ← → 😁 ← →  │       │
│    └─────────────┘       │  Alguns tiles visíveis
│                          │  podem estar fora do chunk (wrap-around)
└──────────────────────────┘
```

Sem wrap-around: Alguns tiles = `None` ❌
Com wrap-around: Todos os tiles identificados ✅

---

*Fix aplicado: 2025-12-17*
