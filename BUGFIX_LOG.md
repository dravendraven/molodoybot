# Bug Fix Log

## 🐛 Bug #1: Missing _reconstruct_first_step() Method

### Data
2025-12-17

### Erro
```
AttributeError: 'AStarWalker' object has no attribute '_reconstruct_first_step'
```

### Causa
Durante a edição de `core/astar_walker.py` para adicionar o fallback step, o método `_reconstruct_first_step()` foi acidentalmente removido.

### Impacto
- Cavebot falhava com erro de atributo sempre que A* conseguia planejar uma rota
- Bot não conseguia se mover
- Erro ocorria em praticamente todo ciclo

### Solução
Restaurado o método `_reconstruct_first_step()` em `core/astar_walker.py` (linhas 158-163).

### Commit
```
8913f95 Fix: Restaurar método _reconstruct_first_step() em AStarWalker
```

### Status
🟢 RESOLVIDO

---

## 🐛 Bug #2: Fallback Step Oscilação Diagonal

### Data
2025-12-17

### Problema
Bot ficava oscilando entre dois passos diagonais quando cruzava waypoints em sequência:
```
Ciclo 1: Player (32076,32157,7) → Waypoint 10
  Target relativo: (2, 1)
  A* consegue: Step (1, 1) - vai para (32077,32158,7)

Ciclo 2: Player (32077,32158,7) → Waypoint 8
  Target relativo: (-3, 3) [target anterior, não atualizado]
  Fallback escolhe: (-1, -1) - volta para trás!

Ciclo 3: Volta para (1, 1) novamente
```

### Causa
O fallback step escolhia o passo "mais próximo ao target" sem verificar se estava **reduzindo a distância**. Com um target fora de sight (distante), podia escolher passos que afastavam:

```
Distância atual: sqrt((-3)^2 + 3^2) = 4.24
Passo (-1,-1): sqrt((-1-(-3))^2 + (-1-3)^2) = sqrt(4+16) = 4.47 PIOR!
Passo (1, 1): sqrt((1-(-3))^2 + (1-3)^2) = sqrt(16+4) = 4.47 PIOR!
```

Ambos pioravam a distância, causando oscilação.

### Solução
Filtrar fallback steps para SÓ aceitar passos que reduzem a distância ao target:

```python
# Distância atual
current_distance = sqrt(target_x^2 + target_y^2)

# Para cada vizinho walkable:
new_distance = sqrt((new_x - target_x)^2 + (new_y - target_y)^2)

# SÓ considera se reduce:
if new_distance >= current_distance:
    continue  # Rejeita!
```

### Commit
```
4890e56 Fix: Fallback step não deveria andar para trás
```

### Impacto
- Bot para de oscilar entre waypoints próximos
- Navegação em fila de waypoints muito mais suave
- Fallback apenas anda quando traz mais perto do objetivo

### Status
🟢 RESOLVIDO

---

## Resumo de Todos os Bugfixes

| # | Descrição | Commit | Status |
|---|-----------|--------|--------|
| 1 | Missing _reconstruct_first_step() | 8913f95 | 🟢 |
| 2 | Fallback oscilação diagonal | 4890e56 | 🟢 |

Todos os bugs foram identificados e corrigidos em 2025-12-17.
