# Testes para Cruzamento de Limites de Chunk

## Contexto

Após implementar a solução de fallback step, precisamos validar que a navegação funciona corretamente quando cruzamos limites de chunk.

---

## Teste 1: Navegação Longa com Fallback

### Setup
1. Ativar cavebot com `DEBUG_PATHFINDING = True`
2. Criar um caminho de waypoints que cruza pelo menos 2 chunks
3. Exemplo: Rotas longas na cave onde cada seção fica em chunk diferente

### Comportamento Esperado

**Log esperado:**
```
[Cavebot] Player pos: (32050, 32160, 7), ID: 12345
[Cavebot] read_full_map() retornou: True, is_calibrated: True
[Cavebot] center_index: 84, offsets: (-2, -5, 0)

[Cavebot] ⚠️ Caminho bloqueado ou calculando...
[Cavebot] DEBUG INFO:
  Player pos: (32050, 32160, 7)
  Waypoint: (32060, 32140, 7)
  Target relativo: (10, -20)
  Target absoluto chebyshev distance: 20 (limite: 7)

[A*] 💡 FALLBACK: Dando um passo em direção ao target (7, -7)
[A*] Step: (1, -1), distância: 5.66

[Cavebot] Próximo ciclo...
[Cavebot] Player pos: (32051, 32159, 7), ID: 12345
[Cavebot] read_full_map() retornou: True, is_calibrated: True
[Cavebot] center_index: 85, offsets: (-1, -4, 0)
[Cavebot] ===== A* conseguiu planejar até o target! =====
```

### Verificações
- ✅ Bot não trava (não aparece stuck detection)
- ✅ Fallback step aparece no log quando target > MAX_VIEW_RANGE
- ✅ Bot anda 1 passo na direção correta (diagonal preferencialmente)
- ✅ Próximo ciclo consegue planejar normalmente
- ✅ Bot eventualmente chega ao waypoint

---

## Teste 2: Navegação Perto de Borda (Edge Case)

### Setup
1. Player posicionado perto da borda do chunk (offset_x ≈ +8)
2. Waypoint localizado no mesmo andar, mas fora do chunk visível
3. Exemplo: Player em (32065, 32160, 7) com offset_x = +8
   - Target: (32070, 32160, 7) (que fica fora do chunk atual)

### Comportamento Esperado

**Na borda leste:**
```
[MemoryMap] get_tile(2, -2) -> FORA DOS BOUNDS
  target_x=18, target_y=4 (offset_x=+8, offset_y=-2)

[A*] 💡 FALLBACK: Dando um passo em direção ao target (0, 0)
[A*] Step: (1, 0), distância: 4.00
→ Bot anda para LESTE
→ Próximo ciclo: Chunk leste carregada, A* funciona

```

### Verificações
- ✅ Fallback escolhe o passo que reduz a distância
- ✅ Bot anda na direção certa (LESTE, quando target fica a LESTE)
- ✅ Não há erro ou travamento

---

## Teste 3: Navegação em Canto (Hardest Case)

### Setup
1. Player no canto do chunk (offset_x = +9, offset_y = +7)
2. Waypoint bem distante, fora do chunk

### Comportamento Esperado

```
[A*] 💡 FALLBACK: Dando um passo em direção ao target (2, 1)
[A*] Step: (1, 0), distância: 2.16

Ciclo 1: Bot anda LESTE
Ciclo 2: Bot anda SUL (nova chunk)
Ciclo 3: A* consegue planejar
```

### Verificações
- ✅ Fallback funciona mesmo quando player está no canto
- ✅ Bot consegue navegar para o novo chunk

---

## Teste 4: Validação de Desempenho

### Setup
1. Rota longa com múltiplos waypoints
2. `DEBUG_PATHFINDING = True` (ativa logs)
3. Medir quantos ciclos usam fallback

### Métrica
```
Total de ciclos: 150
Ciclos com fallback: 8-12 (esperado: < 10% dos ciclos)
Ciclos sem movimento: 0 (nenhum travamento)
Tempo total: ~75 segundos (500ms de walk_delay)
```

### Verificações
- ✅ Fallback é raro (não mais que 10% dos ciclos)
- ✅ Sem delay adicional perceptível
- ✅ Log mostra que A* consegue planejar normalmente ~90% do tempo

---

## Teste 5: Sem Walkables (Verdadeiro Bloqueio)

### Setup
1. Posicionar player cercado por paredes/não-walkables
2. Waypoint do outro lado de um buraco grande

### Comportamento Esperado

```
[MapAnalyzer] get_tile_properties(1, 0) -> BLOQUEADO (bloqueio_id=20)
[MapAnalyzer] get_tile_properties(0, 1) -> BLOQUEADO (bloqueio_id=20)
... (todos bloqueados)

[A*] ⚠️ DEBUG: Nenhum tile walkable encontrado ao redor!
[A*] Tiles analisados: 8 bloqueados, 0 walkable

[Cavebot] ⚠️ Caminho bloqueado ou calculando...
→ Stuck detection dispara depois de 5 segundos
```

### Verificações
- ✅ Fallback NÃO ativa (corretamente, sem walkables)
- ✅ Bot espera stuck detection (comportamento antigo, correto)

---

## Teste 6: Validação com Andar Especial (Escadas/Rope)

### Setup
1. Caminho que cruza chunk COM escadas de mudança de andar
2. Exemplo: Descer rope, cruzar chunk, subir escada

### Comportamento Esperado

```
[Cavebot] Ação: ESCADA UP_USE em (2, 1)
time.sleep(0.6) ← Espera mudança de andar
→ Player sobe para andar 6

[Cavebot] Player pos: (32050, 32156, 6)
[MemoryMap] read_full_map() → Novo andar, novo center
→ Chunk recarregada para andar 6

[Cavebot] Próximo waypoint em (32080, 32140, 6)
[A*] 💡 FALLBACK... (se necessário)
```

### Verificações
- ✅ Floor change + chunk recarga funciona em conjunto
- ✅ Offsets recalculados corretamente para novo andar
- ✅ Fallback funciona em andares diferentes

---

## Teste 7: Regra de Horizonte (MAX_VIEW_RANGE)

### Setup
1. Verificar que a "regra de horizonte" funciona com fallback
2. Target muito distante (>15 tiles)

### Comportamento Esperado

```
Target relativo: (25, 15)
Target chebyshev: 25 (MAX_VIEW_RANGE = 7)
Factor: 7/25 = 0.28

Walk target: (25*0.28, 15*0.28) = (7, 4) ← Redimensionado
[A*] Planejando até (7, 4)... SUCCESS!

Próximo ciclo:
[A*] Planejando até (7, 4)... SUCCESS!
(Vai iterativamente chegando ao target verdadeiro)
```

### Verificações
- ✅ Horizonte funciona em conjunto com fallback
- ✅ Não há loops infinitos

---

## Teste 8: Regressão - Navegação Normal

### Setup
1. Waypoint DENTRO do chunk visível (< MAX_VIEW_RANGE)
2. Nenhuma mudança de andar necessária

### Comportamento Esperado

```
Target relativo: (3, 2)
[A*] Planejando até (3, 2)...
[A*] Encontrou rota ✓

next_step: (1, 0)
→ Bot anda LESTE

(Nenhum fallback deve ativar)
```

### Verificações
- ✅ Comportamento normal NÃO foi alterado
- ✅ Fallback NÃO ativa quando não é necessário
- ✅ A* consegue planejar normalmente

---

## Checklist de Validação

### Antes de Fazer Deploy

- [ ] Teste 1: Navegação longa com fallback ✓
- [ ] Teste 2: Edge case (borda de chunk) ✓
- [ ] Teste 3: Canto do chunk ✓
- [ ] Teste 4: Desempenho (<10% fallback) ✓
- [ ] Teste 5: Bloqueio verdadeiro (sem walkables) ✓
- [ ] Teste 6: Floor changes com chunks ✓
- [ ] Teste 7: Regra de horizonte funciona ✓
- [ ] Teste 8: Regressão (casos normais) ✓

### Logs Esperados

✅ Encontrar em debug logs:
- `[A*] 💡 FALLBACK: Dando um passo...` (quando necessário)
- Sem mensagens de erro ou exceções
- Smooth progression em direção aos waypoints

### Performance

✅ Métricas:
- Fallback < 10% dos ciclos
- Sem lag adicional
- Walk_delay mantido em 500ms

---

## Desativar Debug Após Testes

Quando tudo estiver validado:

**`config.py` (Linha ~348):**
```python
# Antes:
DEBUG_PATHFINDING = True

# Depois:
DEBUG_PATHFINDING = False
```

Isso remove os logs chatosos e melhora a performance um pouco.

---

## Conclusão

Após passar em todos esses testes, a solução estará pronta para uso em produção!

O fallback step é uma adição **transparente** que melhora a robustez sem quebrar funcionalidade existente. 🎯
