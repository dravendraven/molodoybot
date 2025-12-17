# Solução para Cruzamento de Limites de Chunk

## Problema Original

Quando o bot tentava navegar para um waypoint que ficava em um chunk vizinho (fora da área visível), o sistema falhava com:
```
[Cavebot] Caminho bloqueado ou calculando...
[MemoryMap] get_tile(2, -2) -> FORA DOS BOUNDS
  target_x=8, target_y=-1 (offset_x=-2, offset_y=-5)
```

**Raiz do Problema:**
- Tibia 7.72 carrega apenas UMA chunk por vez (18×14×8 tiles = 2016 tiles)
- Quando o player fica perto das bordas, os offsets ficam grandes (até -8 ou +9)
- A* tenta acessar tiles fora dos limites visíveis (0-17, 0-13) e recebe `None`
- Pathfinding falha mesmo quando há um caminho claro

**Exemplo do Bug:**
```
Player: (32076, 32160, 7) com offset_y = -5 (5 tiles norte do centro)
Target: (2, -2) relativo
Cálculo: target_y = 6 + (-2) + (-5) = -1 ← OUT OF BOUNDS!
```

---

## Solução Implementada: Fallback Step

### Como Funciona

A solução é elegante e aproveita como o Tibia atualiza chunks:

1. **A* Falha na Rota Completa**
   - Não consegue planejar até o waypoint porque está em outro chunk
   - Mas ainda consegue acessar tiles walkable próximos (vizinhos do player)

2. **Fallback Step Ativado**
   - `AStarWalker._get_fallback_step()` examina os 8 tiles vizinhos
   - Escolhe o que está mais próximo do waypoint

3. **Player Anda um Passo**
   - Bot move para um tile mais próximo do waypoint
   - Normalmente anda em direção à borda do chunk

4. **Próximo Ciclo: Nova Chunk Carregada**
   - `MemoryMap.read_full_map()` relê a memória com novo player_id
   - `_calibrate_center()` recalcula offsets
   - Nova chunk (vizinha) é lida automaticamente
   - A* consegue planejar novamente

### Código Alterado

**`core/astar_walker.py` - Linhas 106-109:**
```python
# FALLBACK: Se A* não encontrou caminho, tenta dar um passo em direção ao waypoint
# (Útil quando o target está fora do chunk visível)
if walkable_count > 0:
    return self._get_fallback_step(target_rel_x, target_rel_y)
```

**`core/astar_walker.py` - Novo método (Linhas 113-149):**
```python
def _get_fallback_step(self, target_rel_x, target_rel_y):
    """
    FALLBACK: Se A* não conseguir planejar até o destino (porque está fora do chunk),
    tenta dar um passo na direção mais próxima do destino.
    """
    neighbors = [
        (0, -1), (0, 1), (-1, 0), (1, 0),
        (-1, -1), (-1, 1), (1, -1), (1, 1)
    ]

    best_step = None
    best_distance = float('inf')

    for dx, dy in neighbors:
        props = self.analyzer.get_tile_properties(dx, dy)
        if not props['walkable']:
            continue

        distance = math.sqrt((dx - target_rel_x)**2 + (dy - target_rel_y)**2)

        if distance < best_distance:
            best_distance = distance
            best_step = (dx, dy)

    if best_step and self.debug:
        print(f"[A*] 💡 FALLBACK: Dando um passo em direção ao target ({target_rel_x}, {target_rel_y})")
        print(f"[A*] Step: {best_step}, distância: {best_distance:.2f}")

    return best_step
```

---

## Exemplo Visual

### Antes (Bug)

```
Chunk carregada:     Target fora:
┌─────────────────┐
│      ┌─X        │  X = Target (chunk vizinha)
│      │   ░░░░░░│░░░ ░ = Target relativo fora do chunk
│  P   │   ░░░    │    P = Player (perto da borda)
│      └─□         │  □ = A* tenta planejar até ░
└─────────────────┘

Result: A* falha, tile fora do chunk retorna None
```

### Depois (Solução)

```
Ciclo 1: Fallback Step
┌─────────────────┐
│      ┌─          │
│      │   ░░░░░░  │  P1 = Player
│ P1→→ └─□         │  □ = Fallback step (borda do chunk)
└─────────────────┘

Ciclo 2: Novo chunk carregado
        ┌─────────────────┐
        │  □→X            │  P2 = Player (nova chunk)
        │   ░░░░░░        │  X = Target (agora visível!)
        │      P2         │  A* consegue planejar
        └─────────────────┘
```

---

## Comportamento Observável

### Antes da Solução
- Bot reporta: `[Cavebot] Caminho bloqueado ou calculando...`
- Fica travado até stuck detection (5+ segundos)
- Depois anda para o lado aleatoriamente

### Depois da Solução
- Bot reporta: `[Cavebot] Caminho bloqueado ou calculando...`
- Se for fallback: `[A*] 💡 FALLBACK: Dando um passo em direção ao target`
- Bot anda 1-2 tiles em direção ao waypoint
- Próximo ciclo: chunk recarrega, continua normalmente

### Quando o Fallback NÃO Funciona
- Se o player está completamente cercado por tiles não-walkable
- Nesse caso: `walkable_count == 0` (nenhum vizinho walkable)
- Continuará com stuck detection como antes (comportamento correto)

---

## Configurações

### Variáveis Importantes

**`config.py`:**
```python
DEBUG_PATHFINDING = True  # Ativa logs detalhados quando fallback é usado
```

**`core/cavebot.py` (Linha 213):**
```python
MAX_VIEW_RANGE = 7  # Limite seguro de leitura de memória
```

Se aumentar `MAX_VIEW_RANGE` para 8+:
- Bot planeja mais longe (menos fallback steps)
- MAS: risco de ler fora do chunk → retorna None → falha

Se diminuir para 5-6:
- Bot usa fallback mais frequentemente (mais ciclos)
- MAS: navegação mais lenta e cautelosa

**Recomendação:** Manter em 7 (atual) - está balanceado.

---

## Fluxo Completo

```
run_cycle()
    ↓
read_full_map() ← Lê chunk atualizada
    ↓
Seleciona waypoint
    ↓
Calcula target_rel = waypoint - player
    ↓
Se dist_chebyshev > MAX_VIEW_RANGE:
    Redimensiona para MAX_VIEW_RANGE (horizonte)
    ↓
get_next_step() ← A* tentando planejar
    ├─ Consegue achar rota? → Retorna primeiro passo ✓
    └─ Não consegue? (target fora do chunk)
        ├─ Existem tiles walkable ao redor?
        │   ├─ SIM → FALLBACK: get_fallback_step()
        │   │         ↓
        │   │         Escolhe melhor vizinho em direção ao target
        │   │         ↓
        │   │         Move um passo ← Bot se aproxima da borda
        │   │         ↓
        │   │         Próximo ciclo: Nova chunk, A* funciona! ✓
        │   │
        │   └─ NÃO → Retorna None
        │             ↓
        │             Stuck detection dispara
        │             ↓
        │             Bot anda aleatoriamente depois

_move_step() ← Envia movimento ao jogo
    ↓
Aguarda walk_delay (500ms)
    ↓
Volta para run_cycle()
```

---

## Testes Recomendados

### Teste 1: Navegação Longa (Borda de Chunk)
- Criar waypoint que cruza limite de chunk
- Verificar se há fallback steps no log
- Confirmar que bot anda normalmente depois

### Teste 2: Desempenho
- Com `DEBUG_PATHFINDING = True`
- Observar que fallback é raro (<10% dos ciclos)
- Confirmar que não há delay adicional

### Teste 3: Caso Edge (Cercado)
- Waypoint que é verdadeiramente bloqueado
- Confirmar que fallback NÃO ativa (nenhum walkable)
- Stuck detection dispara normalmente

---

## Conclusão

A solução é **elegante** porque:
1. Não requer alterações arquiteturais
2. Aproveita como o Tibia carrega chunks automaticamente
3. Fallback é transparente (1-2 tiles, normal de qualquer forma)
4. Sem aumento de latência ou overhead

O Tibia 7.72 foi projetado para funcionar com um player que anda continuamente e chunks que recarregam a cada passo. Nossa solução só segue esse padrão ao cruzar limites de chunk! 🎯
