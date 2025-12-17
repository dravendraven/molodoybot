# Phase 3: Eater & Stacker Integration

## Sumário
Integração bem-sucedida do PacketMutex nos módulos Eater e Stacker.

## Mudanças

### Eater (modules/eater.py)
**Linhas:** 3-4, 33-34

```python
# Import adicionado
from core.packet_mutex import PacketMutex

# Wrapping do packet.use_item
with PacketMutex("eater"):
    packet.use_item(pm, food_pos, item.id, index=cont.index)
```

- Prioridade: 20 (ação oportunista - baixa)
- Linhas adicionadas: 4

### Stacker (modules/stacker.py)
**Linhas:** 5, 38-39

```python
# Import adicionado
from core.packet_mutex import PacketMutex

# Wrapping do packet.move_item
with PacketMutex("stacker"):
    packet.move_item(pm, pos_from, pos_to, item_src.id, item_src.count)
```

- Prioridade: 30 (organização em background - baixa)
- Linhas adicionadas: 3

## Estatísticas
- **Total de linhas adicionadas:** 7
- **Packet actions sincronizadas:** 2
- **Complexidade:** Mínima (1 ação cada)
- **Risco:** Baixo

## Comportamento Esperado
- Eater executa apenas quando tem mutex
- Stacker aguarda outros módulos (especialmente Fisher, Trainer, Runemaker)
- Nenhum conflito de ações simultâneas
- Logs mostram: `[PACKET-MUTEX] 🔒 EATER/STACKER adquiriu mutex`

## Testes Recomendados

### Test 1: Eater Alone (15 min)
- Verificar: Comida consumida normalmente
- Logs: EATER mutex events

### Test 2: Stacker Alone (15 min)
- Verificar: Itens empilhados corretamente
- Logs: STACKER mutex events

### Test 3: Todos Juntos (30 min)
- Verificar: Sincronização por prioridade
- Ordem esperada: Runemaker (100) > Trainer (80) > Fisher (60) > Auto-Loot (40) > Stacker (30) > Eater (20)

## Próximos Passos
Phase 4: Integrar Trainer, Auto-Loot e Runemaker (módulos de alta complexidade)

---

*Phase 3 implementada: 2025-12-17*
