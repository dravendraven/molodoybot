"""
Spear Picker Module - Pega spears do chao automaticamente.

Funcionalidade para Paladinos:
- Identifica spears (ID 3277) no chao em tiles adjacentes
- Move itens que estao acima da spear (ex: corpo de criatura) para tile adjacente
- Verifica cap do personagem e calcula quantas pode pegar (20 oz cada)
- Move para a mao que ja tem spear ou esta vazia
- Repete o processo (quando ataca com spear, ela cai no tile da criatura)

Sistema de Scanning (2 scans independentes):

SCAN 1 - Monitoramento de Mão (150ms):
  - Verifica quantidade de spears na mão constantemente
  - Detecta quando houve ataque (spear count diminuiu)
  - Roda SEMPRE, independente do estado

SCAN 2 - Busca no Chão (200ms):
  - Escaneia tiles adjacentes procurando spears
  - Roda APENAS quando spears < max_spears
  - Ativado automaticamente pelo SCAN 1

Delays Humanizados (aplicados APENAS em ações):
  - Tempo de reação ao detectar spear: 250ms + variação gaussiana 30%
  - Tempo entre move_items: 250ms + variação gaussiana 30%
"""

import time
import random
import threading

from config import (
    OFFSET_PLAYER_ID,
    SLOT_RIGHT,
    SLOT_LEFT,
)
from database.movable_items_db import is_movable
from database.tiles_config import FLOOR_CHANGE
from core.map_core import get_player_pos
from core.memory_map import MemoryMap
from core.map_analyzer import MapAnalyzer
from core.packet import PacketManager, get_ground_pos, get_inventory_pos
from core.packet_mutex import PacketMutex
from core.player_core import get_player_cap
from core.inventory_core import get_item_id_in_hand, get_spear_count_in_hands
from core.bot_state import state
from utils.timing import gauss_wait

# Constantes do modulo
SPEAR_ID = 3277          # ID da spear
SPEAR_WEIGHT = 20.0      # Peso de cada spear em oz

# Debug - ativa/desativa prints do modulo
DEBUG_SPEAR = True

def _log(msg):
    """Log condicional baseado em DEBUG_SPEAR."""
    if DEBUG_SPEAR:
        print(msg)

# Decremento de probabilidade por spear na mao (15% por spear)
PICK_CHANCE_DECREMENT = 0.20

# Tiles a escanear (proprio tile + adjacentes incluindo diagonais)
ADJACENT_TILES = [
    (0,  0),                      # Proprio tile do jogador
    (-1, -1), (0, -1), (1, -1),   # Norte
    (-1,  0),          (1,  0),   # Leste/Oeste
    (-1,  1), (0,  1), (1,  1),   # Sul
]

# IDs de criaturas/players (item ID 99 na memoria do mapa)
CREATURE_ID = 99

# IDs de rope spots (não dropar items aqui)
ROPE_SPOT_IDS = FLOOR_CHANGE.get('ROPE', set())

# ========== DELAYS DE SCAN (RÁPIDOS, SEM HUMANIZAÇÃO) ==========
# Estes delays controlam a velocidade dos loops de monitoramento
SCAN_HAND_DELAY = 0.15         # Delay entre scans de spears na mao (monitoramento constante)
SCAN_TILES_DELAY = 0.4         # Delay entre scans de tiles ao redor (procurando spears no chao)

# ========== DELAYS HUMANIZADOS (APLICADOS APENAS EM AÇÕES) ==========
# Estes delays simulam tempo de reação humana e são aplicados APENAS em move_item
REACTION_DELAY_MIN = 0.3      # Delay minimo de reacao ao detectar spear no chao (250ms base)
MOVE_ITEM_DELAY_MIN = 0.5     # Delay minimo global apos QUALQUER move_item (250ms base)
# Nota: Variacao gaussiana de ~30% sera aplicada sobre estes valores base

# ========== CONSOLIDAÇÃO DE SPEARS (HUMANIZAÇÃO) ==========
ENABLE_CONSOLIDATION = False  # Desativado por enquanto
# Delay entre moves de consolidação (juntar spears em um tile)
CONSOLIDATE_MOVE_DELAY_MIN = 0.25  # 250ms base + variação 30%
# Chance de consolidar vs pegar uma por uma (humanização adicional)
CONSOLIDATE_CHANCE = 0.85  # 85% das vezes consolida, 15% pega uma por uma
# Maximo de spears a consolidar antes de puxar para a mao
# Ex: se tem 4 spears no chao e MAX=2, consolida 2 e puxa, depois repete
MAX_SPEARS_TO_CONSOLIDATE = 2


class SpearPickerState:
    """
    Estado compartilhado entre threads do spear picker (thread-safe).

    Thread Monitor: atualiza via update_from_hand_scan()
    Thread Ações: lê via get_action_state() e atualiza via update_after_pickup()
    """

    def __init__(self):
        self.last_spear_count = 0
        self.needs_spears = False  # Flag: precisa procurar spears no chão
        self.max_spears = 3
        self.lock = threading.Lock()

    def update_from_hand_scan(self, current_spears, max_spears):
        """
        Atualiza estado baseado em scan de mão (Thread Monitor).

        Args:
            current_spears: Quantidade atual de spears na mão
            max_spears: Quantidade máxima configurada

        Returns:
            True se detectou ataque (spear count diminuiu)
        """
        with self.lock:
            attack_detected = current_spears < self.last_spear_count
            self.last_spear_count = current_spears
            self.max_spears = max_spears
            self.needs_spears = (current_spears < max_spears)
            return attack_detected

    def get_action_state(self):
        """
        Retorna cópia do estado para thread de ações.

        Returns:
            Dict com current_spears, max_spears, needs_spears
        """
        with self.lock:
            return {
                'current_spears': self.last_spear_count,
                'max_spears': self.max_spears,
                'needs_spears': self.needs_spears
            }

    def update_after_pickup(self, spears_picked):
        """
        Atualiza count após pegar spears (Thread Ações).

        Args:
            spears_picked: Quantidade de spears que foram pegas
        """
        with self.lock:
            self.last_spear_count += spears_picked
            self.needs_spears = (self.last_spear_count < self.max_spears)


def find_target_hand(pm, base_addr):
    """
    Encontra a mao alvo para colocar a spear.

    Prioridade:
    1. Mao que ja tem spear (stack)
    2. Mao vazia
    3. None se ambas ocupadas com outros items

    Returns:
        SLOT_RIGHT, SLOT_LEFT ou None
    """
    right_id = get_item_id_in_hand(pm, base_addr, SLOT_RIGHT)
    left_id = get_item_id_in_hand(pm, base_addr, SLOT_LEFT)

    # Prioridade 1: Mao que ja tem spear
    if right_id == SPEAR_ID:
        return SLOT_RIGHT
    if left_id == SPEAR_ID:
        return SLOT_LEFT

    # Prioridade 2: Mao vazia
    if right_id == 0:
        return SLOT_RIGHT
    if left_id == 0:
        return SLOT_LEFT

    # Ambas ocupadas com outros items
    return None


def calculate_pick_probability(current_count, max_count):
    """
    Calcula a probabilidade de pegar a spear baseado em quantas tem na mao.

    Logica humanizada - decremento fixo de 15% por spear:
    - 0 spears na mao: 100% de chance
    - 1 spear na mao: 85% de chance
    - 2 spears na mao: 70% de chance
    - 3 spears na mao: 55% de chance
    - 4 spears na mao: 40% de chance
    - max spears na mao: 0% (nao tenta pegar)

    Exemplo com max=2:
    - 0 spears: 100%
    - 1 spear: 85%
    - 2 spears: 0% (nao tenta)

    Exemplo com max=5:
    - 0 spears: 100%
    - 1 spear: 85%
    - 2 spears: 70%
    - 3 spears: 55%
    - 4 spears: 40%
    - 5 spears: 0% (nao tenta)

    Args:
        current_count: Quantidade atual de spears na mao
        max_count: Quantidade maxima configurada

    Returns:
        Float entre 0.0 e 1.0 representando a probabilidade
    """
    if current_count >= max_count:
        return 0.0  # Ja esta cheio, nao tenta pegar

    # Formula simples: 100% - (15% * spears_na_mao)
    # 0 spears = 100%, 1 spear = 85%, 2 spears = 70%, etc.
    chance = 1.0 - (PICK_CHANCE_DECREMENT * current_count)

    # Garante que nao fique negativo
    return max(0.5, chance)


def find_spear_on_adjacent_tiles(mapper, my_x, my_y, my_z):
    """
    Procura spears em tiles adjacentes ao player.

    Returns:
        Tuple (abs_x, abs_y, z, list_index, rel_x, rel_y, tile) ou None se nao encontrar

    Nota: list_index e o indice na lista tile.items (0=fundo, len-1=topo)
    """
    for rel_x, rel_y in ADJACENT_TILES:
        tile = mapper.get_tile_visible(rel_x, rel_y)
        if tile is None:
            continue

        # Procura spear no tile (do topo para baixo)
        for i in range(len(tile.items) - 1, -1, -1):
            if tile.items[i] == SPEAR_ID:
                abs_x = my_x + rel_x
                abs_y = my_y + rel_y
                return (abs_x, abs_y, my_z, i, rel_x, rel_y, tile)

    return None


def find_all_spears_on_adjacent_tiles(mapper, my_x, my_y, my_z):
    """
    Procura TODAS as spears em tiles adjacentes ao player.

    Diferente de find_spear_on_adjacent_tiles() que retorna apenas a primeira,
    esta funcao retorna uma lista com todas as spears encontradas.

    Returns:
        Lista de dicts com informacoes de cada spear encontrada:
        [{'abs_x', 'abs_y', 'z', 'rel_x', 'rel_y', 'stack_count', 'tile'}, ...]
    """
    spears = []
    for rel_x, rel_y in ADJACENT_TILES:
        tile = mapper.get_tile_visible(rel_x, rel_y)
        if tile is None:
            continue

        # Procura spear no tile (do topo para baixo)
        for i in range(len(tile.items) - 1, -1, -1):
            if tile.items[i] == SPEAR_ID:
                stack_count = get_stack_count(tile, i)
                spears.append({
                    'abs_x': my_x + rel_x,
                    'abs_y': my_y + rel_y,
                    'z': my_z,
                    'rel_x': rel_x,
                    'rel_y': rel_y,
                    'stack_count': stack_count,
                    'tile': tile
                })
                break  # So uma spear por tile (elas stackam)

    return spears


def consolidate_spears(mapper, analyzer, packet, pm, base_addr, player_id,
                       spears_list, target_spear, my_x, my_y, my_z):
    """
    Consolida spears de multiplos tiles para o tile da target_spear.

    Esta funcao implementa comportamento humanizado: um jogador real juntaria
    as spears em um tile antes de pega-las, ao inves de pegar uma por uma.

    IMPORTANTE: Antes de mover cada spear, verifica se ha itens bloqueando
    (acima da spear no stack) e os move primeiro. Isso e necessario porque
    spears so podem ser consolidadas quando estao no topo do stack.

    Args:
        mapper: MemoryMap instance
        analyzer: MapAnalyzer instance
        packet: PacketManager instance
        pm: Pymem instance
        base_addr: Endereco base do processo
        player_id: ID do player
        spears_list: Lista de spears encontradas (de find_all_spears_on_adjacent_tiles)
        target_spear: Spear que sera o destino (as outras serao movidas para la)
        my_x, my_y, my_z: Posicao absoluta do player

    Returns:
        int: Total de spears consolidadas no tile destino (0 se falhou/abortou)
    """
    target_x = target_spear['abs_x']
    target_y = target_spear['abs_y']
    target_z = target_spear['z']
    target_rel_x = target_spear['rel_x']
    target_rel_y = target_spear['rel_y']

    total_consolidated = target_spear['stack_count']  # Ja conta as do tile destino

    _log(f"[Spear Consolidate] Iniciando consolidacao para tile ({target_x},{target_y})")
    _log(f"[Spear Consolidate] Spears iniciais no destino: {total_consolidated}, limite: {MAX_SPEARS_TO_CONSOLIDATE}")

    for spear in spears_list:
        # ===== VERIFICACAO DE LIMITE DE CONSOLIDACAO =====
        # Nao consolida mais do que MAX_SPEARS_TO_CONSOLIDATE
        if total_consolidated >= MAX_SPEARS_TO_CONSOLIDATE:
            _log(f"[Spear Consolidate] Limite atingido ({total_consolidated}/{MAX_SPEARS_TO_CONSOLIDATE}) - parando consolidacao")
            break
        # ==================================================

        # Pula o tile destino (nao move para si mesmo)
        if spear['abs_x'] == target_x and spear['abs_y'] == target_y:
            continue

        # ===== VERIFICACAO CRITICA: Loot pode ter sido aberto =====
        if state.is_processing_loot or state.has_open_loot:
            _log("[Spear Consolidate] Loot foi aberto - abortando consolidacao")
            return 0
        # ===========================================================

        # ===== VERIFICACAO: Player pode ter se movido =====
        current_x, current_y, current_z = get_player_pos(pm, base_addr)
        if current_x != my_x or current_y != my_y or current_z != my_z:
            _log("[Spear Consolidate] Player se moveu - abortando consolidacao")
            return 0
        # ===================================================

        # Re-le mapa para ter dados atualizados
        if not mapper.read_full_map(player_id):
            _log("[Spear Consolidate] Falha ao ler mapa - abortando")
            return 0

        # Verifica se spear ainda existe no tile de origem
        source_tile = mapper.get_tile_visible(spear['rel_x'], spear['rel_y'])
        if source_tile is None:
            _log(f"[Spear Consolidate] Tile origem ({spear['rel_x']},{spear['rel_y']}) nao visivel - pulando")
            continue

        # Procura indice da spear no tile de origem
        spear_list_index = -1
        for i in range(len(source_tile.items) - 1, -1, -1):
            if source_tile.items[i] == SPEAR_ID:
                spear_list_index = i
                break

        if spear_list_index < 0:
            _log(f"[Spear Consolidate] Spear sumiu do tile ({spear['abs_x']},{spear['abs_y']}) - pulando")
            continue

        # ========== MOVER BLOQUEADORES ACIMA DA SPEAR ==========
        # Spears precisam estar no topo do stack para serem consolidadas
        items_above = get_items_above_spear(source_tile, spear_list_index)

        if items_above:
            _log(f"[Spear Consolidate] {len(items_above)} bloqueadores acima da spear em ({spear['abs_x']},{spear['abs_y']})")

            # Encontra tile para dropar bloqueadores (evitando tiles com spears)
            drop_tile = find_drop_tile_avoiding_spears(
                mapper, spear['rel_x'], spear['rel_y'], my_x, my_y, my_z, spears_list
            )
            if drop_tile is None:
                _log(f"[Spear Consolidate] Nao encontrou tile para mover bloqueadores - pulando spear")
                continue

            drop_x, drop_y, drop_z = drop_tile
            _log(f"[Spear Consolidate] Dropando bloqueadores em ({drop_x},{drop_y}) - evitando tiles com spears")

            # Move cada bloqueador
            for idx_move, (item_id, list_idx) in enumerate(items_above):
                # Verificacao de loot antes de cada move
                if state.is_processing_loot or state.has_open_loot:
                    _log("[Spear Consolidate] Loot aberto durante move de bloqueador - abortando")
                    return 0

                # Calcula stack_pos atual do bloqueador
                blocker_stack_pos = analyzer.get_item_stackpos(spear['rel_x'], spear['rel_y'], item_id)
                if blocker_stack_pos < 0:
                    _log(f"[Spear Consolidate] Bloqueador ID={item_id} nao encontrado - pulando")
                    continue

                from_pos = get_ground_pos(spear['abs_x'], spear['abs_y'], spear['z'])
                to_pos = get_ground_pos(drop_x, drop_y, drop_z)

                _log(f"[Spear Consolidate] Movendo bloqueador ID={item_id} para ({drop_x},{drop_y})")

                with PacketMutex("spear_consolidate"):
                    packet.move_item(from_pos, to_pos, item_id, 1, blocker_stack_pos, apply_delay=True)

                # Re-le mapa apos mover bloqueador
                mapper.read_full_map(player_id)

                # Delay entre moves de bloqueadores
                if idx_move < len(items_above) - 1:
                    gauss_wait(CONSOLIDATE_MOVE_DELAY_MIN, 30)

            # Delay apos mover todos os bloqueadores antes de mover a spear
            gauss_wait(CONSOLIDATE_MOVE_DELAY_MIN, 30)

            # Re-le mapa e verifica se spear ainda existe
            if not mapper.read_full_map(player_id):
                _log("[Spear Consolidate] Falha ao ler mapa apos mover bloqueadores")
                continue

            source_tile = mapper.get_tile_visible(spear['rel_x'], spear['rel_y'])
            if source_tile is None:
                continue

        # ========== MOVER SPEAR PARA TILE DESTINO ==========
        # Calcula stack_pos atual da spear (pode ter mudado apos mover bloqueadores)
        spear_stack_pos = analyzer.get_item_stackpos(spear['rel_x'], spear['rel_y'], SPEAR_ID)
        if spear_stack_pos < 0:
            _log(f"[Spear Consolidate] Nao encontrou stack_pos da spear apos mover bloqueadores - pulando")
            continue

        # Obtem count atual (pode ter mudado)
        current_count = get_stack_count(source_tile, spear_stack_pos)

        # Limita count para nao ultrapassar MAX_SPEARS_TO_CONSOLIDATE
        space_left = MAX_SPEARS_TO_CONSOLIDATE - total_consolidated
        if current_count > space_left:
            current_count = space_left
            _log(f"[Spear Consolidate] Limitando para {current_count} spear(s) (limite de consolidacao)")

        # Move spear para tile destino
        from_pos = get_ground_pos(spear['abs_x'], spear['abs_y'], spear['z'])
        to_pos = get_ground_pos(target_x, target_y, target_z)

        _log(f"[Spear Consolidate] Movendo {current_count} spear(s) de ({spear['abs_x']},{spear['abs_y']}) -> ({target_x},{target_y})")

        with PacketMutex("spear_consolidate"):
            packet.move_item(from_pos, to_pos, SPEAR_ID, current_count, spear_stack_pos, apply_delay=True)

        total_consolidated += current_count

        # Delay humanizado entre moves de consolidacao
        gauss_wait(CONSOLIDATE_MOVE_DELAY_MIN, 30)

    _log(f"[Spear Consolidate] Consolidacao completa. Total no tile destino: {total_consolidated}")
    return total_consolidated


def find_drop_tile_avoiding_spears(mapper, spear_rel_x, spear_rel_y, my_x, my_y, my_z, spears_list):
    """
    Encontra tile para dropar bloqueadores durante consolidacao de spears.

    IMPORTANTE: Esta funcao e especifica para consolidacao.
    - Preferencia ABSOLUTA pelo tile do player (sempre primeiro)
    - NUNCA retorna um tile que contenha spear (para nao atrapalhar consolidacao)

    Args:
        mapper: MemoryMap instance
        spear_rel_x, spear_rel_y: Posicao relativa do tile com a spear
        my_x, my_y, my_z: Posicao absoluta do player
        spears_list: Lista de spears sendo consolidadas (para evitar esses tiles)

    Returns:
        Tuple (abs_x, abs_y, z) ou None se nao encontrar
    """
    analyzer = MapAnalyzer(mapper)

    # Cria set de tiles com spears para lookup rapido
    spear_tiles = set()
    for s in spears_list:
        spear_tiles.add((s['abs_x'], s['abs_y']))

    # PREFERENCIA 1: Tile do player (se nao tiver spear E nao tiver rope spot)
    if (my_x, my_y) not in spear_tiles:
        player_tile = mapper.get_tile(0, 0)
        if not tile_has_rope_spot(player_tile):
            return (my_x, my_y, my_z)

    # PREFERENCIA 2: Tiles adjacentes ao player que NAO tenham spear
    adjacent_options = list(ADJACENT_TILES)
    random.shuffle(adjacent_options)

    for dx, dy in adjacent_options:
        check_rel_x = spear_rel_x + dx
        check_rel_y = spear_rel_y + dy

        # Pula o tile da spear de origem
        if dx == 0 and dy == 0:
            continue

        # Verifica se esta no range visivel
        if abs(check_rel_x) > 7 or abs(check_rel_y) > 7:
            continue

        # Verifica se tile e adjacente ao player (distancia <= 1)
        player_dist = max(abs(check_rel_x), abs(check_rel_y))
        if player_dist > 1:
            continue

        # Calcula posicao absoluta do tile candidato
        candidate_x = my_x + check_rel_x
        candidate_y = my_y + check_rel_y

        # CRITICO: Nao dropar em tile que tem spear
        if (candidate_x, candidate_y) in spear_tiles:
            continue

        # Verifica se tile existe
        tile = mapper.get_tile_visible(check_rel_x, check_rel_y)
        if tile is None or len(tile.items) == 0:
            continue

        # Verifica se tile e walkable
        props = analyzer.get_tile_properties(check_rel_x, check_rel_y)
        if not props['walkable']:
            continue

        # Verifica se tile tem rope spot (não dropar items em rope spots)
        if tile_has_rope_spot(tile):
            continue

        return (candidate_x, candidate_y, my_z)

    # Fallback: tile do player (ultimo recurso)
    # Retorna None se player estiver em rope spot
    player_tile = mapper.get_tile(0, 0)
    if not tile_has_rope_spot(player_tile):
        return (my_x, my_y, my_z)

    return None


def find_drop_tile_for_blocker(mapper, my_x, my_y, my_z):
    """
    Encontra tile para dropar bloqueadores ao pegar spear.

    Diferente de find_drop_tile_avoiding_spears(), esta funcao:
    - NAO evita tiles com spears (bloqueadores podem cair em qualquer tile)
    - Apenas evita rope spots
    - Prioridade: tile do player > tiles adjacentes walkable

    Args:
        mapper: MemoryMap instance
        my_x, my_y, my_z: Posicao absoluta do player

    Returns:
        Tuple (abs_x, abs_y, z) ou None se nao encontrar
    """
    analyzer = MapAnalyzer(mapper)

    # PREFERENCIA 1: Tile do player (se nao tiver rope spot)
    player_tile = mapper.get_tile(0, 0)
    if player_tile and not tile_has_rope_spot(player_tile):
        return (my_x, my_y, my_z)

    # PREFERENCIA 2: Qualquer tile adjacente walkable sem rope spot
    for dx, dy in ADJACENT_TILES:
        if dx == 0 and dy == 0:
            continue  # Ja verificamos o tile do player

        tile = mapper.get_tile_visible(dx, dy)
        if tile is None:
            continue

        # Verifica se walkable
        props = analyzer.get_tile_properties(dx, dy)
        if not props['walkable']:
            continue

        # Verifica rope spot
        if tile_has_rope_spot(tile):
            continue

        return (my_x + dx, my_y + dy, my_z)

    return None


def is_movable_item(item_id):
    """
    Determina se um item pode ser movido.

    Baseado nas flags do objects.srv:
    - Take = item pode ser pego/movido (corpos, itens, etc.)
    - Unmove/Bottom = objeto do mapa (chao, paredes, splashes, etc.)

    Args:
        item_id: ID do item

    Returns:
        True se o item pode ser movido
    """
    # Criaturas (ID=99) sao um caso especial - nao podem ser movidas
    if item_id == CREATURE_ID:
        return False

    # Consulta a database gerada do objects.srv
    result = is_movable(item_id)

    # Se o item nao esta na database, assume que NAO pode mover (mais seguro)
    if result is None:
        return False

    return result


def tile_has_rope_spot(tile):
    """
    Verifica se um tile contém um rope spot.

    Rope spots não devem receber items dropados pois podem
    interferir na mecânica de mudança de andar.

    Args:
        tile: MemoryTile

    Returns:
        True se o tile contém um rope spot (ID 386)
    """
    if tile is None:
        return False
    for item_id in tile.items:
        if item_id in ROPE_SPOT_IDS:
            return True
    return False


def get_stack_count(tile, item_index):
    """
    Retorna a quantidade de itens empilhados em um slot do tile.

    Para itens stackaveis (como spears), o count esta em data1.
    Se data1=0, assume count=1.

    Args:
        tile: MemoryTile
        item_index: Indice do item na lista tile.items

    Returns:
        Quantidade de itens empilhados (minimo 1)
    """
    if not hasattr(tile, 'items_debug') or item_index >= len(tile.items_debug):
        return 1

    _, data1, _, _ = tile.items_debug[item_index]

    # Para stackaveis, data1 contem o count
    # Se data1=0, pode ser 1 item ou item nao-stackavel
    return data1 if data1 > 0 else 1


def get_items_above_spear(tile, spear_list_index):
    """
    Retorna lista de itens MOVEIS acima da spear no stack.

    Ordem dos MOVABLES na memoria (INVERTIDA):
    - Primeiro movable (menor idx) = TOPO visual
    - Ultimo movable (maior idx) = FUNDO visual

    Items ACIMA da spear = movables com idx MENOR que spear_list_index

    Args:
        tile: MemoryTile
        spear_list_index: Indice da spear na lista tile.items

    Returns:
        Lista de (item_id, list_index) do topo para baixo
    """
    items_above = []

    # Itens acima da spear = indices MENORES que spear_list_index
    # Comeca em 1 para pular o chao (idx=0)
    for i in range(1, spear_list_index):
        item_id = tile.items[i]

        # Verifica se e movivel usando database do objects.srv
        if not is_movable_item(item_id):
            continue

        items_above.append((item_id, i))

    return items_above


def monitor_hand_loop(pm, base_addr, check_running, get_enabled, get_max_spears, shared_state):
    """
    Thread de monitoramento - monitora spears na mão constantemente.

    Responsabilidades:
    - Ler quantidade de spears na mão a cada 150ms
    - Detectar ataques (count diminuiu)
    - Atualizar flag needs_spears
    - Nunca bloqueia, sempre roda

    Args:
        pm: Instancia do Pymem
        base_addr: Endereco base do processo
        check_running: Funcao que retorna False para encerrar
        get_enabled: Funcao que retorna True/False se modulo esta ativo
        get_max_spears: Funcao que retorna o maximo de spears configurado
        shared_state: Instancia de SpearPickerState (estado compartilhado)
    """
    _log("[Spear Monitor] Thread iniciada")

    while True:
        if check_running and not check_running():
            _log("[Spear Monitor] Thread encerrada")
            return

        if not get_enabled():
            time.sleep(1)
            continue

        if pm is None:
            time.sleep(1)
            continue

        try:
            # Le spears na mão
            current_spears, _ = get_spear_count_in_hands(pm, base_addr, SPEAR_ID)
            max_spears = get_max_spears()

            # Atualiza estado compartilhado (thread-safe)
            attack_detected = shared_state.update_from_hand_scan(current_spears, max_spears)

            if attack_detected:
                _log(f"[Spear Monitor] Ataque detectado! Spears: {current_spears}")

            # Log periódico para confirmar que Monitor está ativo (a cada 30 scans = ~4.5s)
            if not hasattr(monitor_hand_loop, '_scan_count'):
                monitor_hand_loop._scan_count = 0
            monitor_hand_loop._scan_count += 1
            if monitor_hand_loop._scan_count % 30 == 0:
                _log(f"[Spear Monitor] Sync: spears={current_spears}/{max_spears}")

            # Delay fixo de scan (sem humanização)
            time.sleep(SCAN_HAND_DELAY)

        except Exception as e:
            _log(f"[Spear Monitor] Erro: {e}")
            time.sleep(1)


def action_loop(pm, base_addr, check_running, get_enabled, shared_state):
    """
    Thread de ações - busca e pega spears do chão.

    Responsabilidades:
    - Escanear tiles ao redor quando needs_spears=True
    - Executar ações de move_item (com delays humanizados)
    - Atualizar estado após pegar spears
    - Pode bloquear durante ações, mas não afeta monitor

    Args:
        pm: Instancia do Pymem
        base_addr: Endereco base do processo
        check_running: Funcao que retorna False para encerrar
        get_enabled: Funcao que retorna True/False se modulo esta ativo
        shared_state: Instancia de SpearPickerState (estado compartilhado)
    """
    _log("[Spear Action] Thread iniciada")

    mapper = MemoryMap(pm, base_addr)
    packet = PacketManager(pm, base_addr)
    analyzer = MapAnalyzer(mapper)  # Para usar get_item_stackpos() e get_top_movable_stackpos()

    # Timeout para ciclo prioritário (evita cavebot pausado indefinidamente)
    PRIORITY_PICKUP_TIMEOUT = 5.0  # 5 segundos
    priority_pickup_start_time = None

    # Timeout defensivo para is_processing_loot travado
    LOOT_STUCK_TIMEOUT = 2.0  # 2 segundos
    loot_processing_start_time = None

    # Timeout defensivo para has_open_loot travado
    loot_open_timeout = None

    while True:
        if check_running and not check_running():
            _log("[Spear Action] Thread encerrada")
            return

        if not get_enabled():
            time.sleep(1)
            continue

        if pm is None:
            time.sleep(1)
            continue

        # Pausa durante AFK humanization
        if state.is_afk_paused:
            _log(f"[Spear Action] Pausado por AFK ({state.get_afk_pause_remaining():.0f}s)")
            time.sleep(0.5)
            continue

        try:
            # Verifica se precisa procurar spears (thread-safe)
            state_data = shared_state.get_action_state()

            # ===== RE-SYNC DEFENSIVO =====
            # Se Action acha que não precisa de spears, verificar diretamente na memória
            if not state_data['needs_spears']:
                real_count, _ = get_spear_count_in_hands(pm, base_addr, SPEAR_ID)
                if real_count != state_data['current_spears']:
                    _log(f"[Spear Action] DESSINCRONIZAÇÃO DETECTADA: state={state_data['current_spears']} vs real={real_count}")
                    # Força re-sync no shared_state
                    max_spears = state_data['max_spears']
                    shared_state.update_from_hand_scan(real_count, max_spears)
                    state_data = shared_state.get_action_state()  # Re-le o estado corrigido
            # =============================

            if not state_data['needs_spears']:
                # Cleanup: se não precisa de spears mas flag está True, libera cavebot
                if state.is_spear_pickup_pending:
                    state.set_spear_pickup_pending(False)
                    priority_pickup_start_time = None
                    _log("[Spear Action] needs_spears=False - cavebot liberado")
                #else:
                    #_log(f"[Spear Action] Aguardando needs_spears (atual={state_data['current_spears']}/{state_data['max_spears']})")
                time.sleep(SCAN_TILES_DELAY)
                continue

            # ===== VERIFICAÇÃO DE LOOT PRIORITY / PICKUP PENDENTE =====
            # Permite pickup quando is_spear_pickup_pending (ciclo pós-loot)
            is_priority_pickup = state.is_spear_pickup_pending

            # Timeout para ciclo prioritário - evita cavebot pausado indefinidamente
            if is_priority_pickup:
                if priority_pickup_start_time is None:
                    priority_pickup_start_time = time.time()
                    _log(f"[Spear Action] PRIORITY PICKUP iniciado - timeout em {PRIORITY_PICKUP_TIMEOUT}s")
                else:
                    elapsed = time.time() - priority_pickup_start_time
                    if elapsed > PRIORITY_PICKUP_TIMEOUT:
                        _log(f"[Spear Action] Timeout do ciclo prioritário ({PRIORITY_PICKUP_TIMEOUT}s) - liberando cavebot")
                        _log(f"[Spear Action]   state.is_spear_pickup_pending será setado para False")
                        state.set_spear_pickup_pending(False)
                        state.end_loot_cycle()  # CRÍTICO: Reseta is_processing_loot para evitar bloqueio permanente
                        priority_pickup_start_time = None
                        continue
            else:
                priority_pickup_start_time = None  # Reset quando não está em modo prioritário

            if not is_priority_pickup:
                # Pausa spear picker durante ciclo de loot (CORPSE_READY → fim)
                # Previne conflitos durante abertura do corpo e processamento de loot
                if state.is_processing_loot:
                    # ===== TIMEOUT DEFENSIVO: Detecta is_processing_loot travado =====
                    if loot_processing_start_time is None:
                        loot_processing_start_time = time.time()
                    elif time.time() - loot_processing_start_time > LOOT_STUCK_TIMEOUT:
                        _log(f"[Spear Action] AVISO: is_processing_loot travado por {LOOT_STUCK_TIMEOUT}s - forçando reset")
                        state.end_loot_cycle()
                        loot_processing_start_time = None
                        # Continua para tentar pegar spear
                    else:
                        elapsed = time.time() - loot_processing_start_time
                        _log(f"[Spear Action] Aguardando is_processing_loot=False (esperando há {elapsed:.1f}s / timeout={LOOT_STUCK_TIMEOUT}s)")
                        time.sleep(SCAN_TILES_DELAY)  # 500ms
                        continue
                else:
                    loot_processing_start_time = None  # Reset quando não está bloqueando

                # Verificação adicional - previne race condition
                # Se container está aberto, aguarda mesmo que is_processing_loot seja False
                if state.has_open_loot:
                    if loot_open_timeout is None:
                        loot_open_timeout = time.time()
                        _log("[Spear Action] Aguardando has_open_loot=False (container de loot aberto)")
                    elif time.time() - loot_open_timeout > LOOT_STUCK_TIMEOUT:
                        _log(f"[Spear Action] AVISO: has_open_loot travado por {LOOT_STUCK_TIMEOUT}s - ignorando")
                        loot_open_timeout = None
                        # Continua para tentar pegar spear (ignora a flag travada)
                    else:
                        time.sleep(SCAN_TILES_DELAY)
                        continue
                else:
                    loot_open_timeout = None  # Reset quando não está bloqueando
            else:
                _log("[Spear Action] PRIORITY PICKUP: Executando ciclo pós-loot")
            # ============================================================

            # === PRÉ-CONDIÇÕES ===
            my_x, my_y, my_z = get_player_pos(pm, base_addr)
            if my_z == 0:
                if is_priority_pickup:
                    _log("[Spear Action] Priority pickup: my_z=0 - liberando cavebot")
                    state.set_spear_pickup_pending(False)
                    priority_pickup_start_time = None
                continue

            current_cap = get_player_cap(pm, base_addr)
            if current_cap < SPEAR_WEIGHT:
                if is_priority_pickup:
                    _log("[Spear Action] Priority pickup: cap insuficiente - liberando cavebot")
                    state.set_spear_pickup_pending(False)
                    priority_pickup_start_time = None
                continue

            target_hand = find_target_hand(pm, base_addr)
            if target_hand is None:
                if is_priority_pickup:
                    _log("[Spear Action] Priority pickup: mãos cheias - liberando cavebot")
                    state.set_spear_pickup_pending(False)
                    priority_pickup_start_time = None
                continue

            # === PROBABILIDADE ===
            current_spears = state_data['current_spears']
            max_spears = state_data['max_spears']

            pick_chance = calculate_pick_probability(current_spears, max_spears)
            #pick_chance = 0.5  # 80% de chance em combate (era 50%)

            # OVERRIDE: Fora de combate, sempre pega spear (100% chance)
            if not state.is_in_combat:
                pick_chance = 1.0
                #print(f"[Spear Action] Fora de combate - forçando pick_chance=100%")

            roll = random.random()
            if roll > pick_chance:
                _log(f"[Spear Action] Probabilidade falhou (chance={pick_chance:.1%}, roll={roll:.1%})")
                time.sleep(SCAN_TILES_DELAY)
                continue

            #print(f"[Spear Action] Vai pegar spear (prob={pick_chance:.1%}, roll={roll:.1%}) - spears={current_spears}/{max_spears}")

            # === BUSCA SPEAR NO CHÃO ===
            player_id = pm.read_int(base_addr + OFFSET_PLAYER_ID)
            if not mapper.read_full_map(player_id):
                time.sleep(0.5)
                continue

            # ========== NOVA LOGICA: BUSCA TODAS AS SPEARS ==========
            # Usa find_all para decidir se deve consolidar
            all_spears = find_all_spears_on_adjacent_tiles(mapper, my_x, my_y, my_z)

            if not all_spears:
                # Cleanup: se estava em priority pickup e não há spears, libera cavebot
                if state.is_spear_pickup_pending:
                    state.set_spear_pickup_pending(False)
                    _log("[Spear Action] Sem spears no chão - cavebot liberado")
                time.sleep(SCAN_TILES_DELAY)
                continue

            total_on_ground = sum(s['stack_count'] for s in all_spears)
            spears_needed = max_spears - current_spears

            # ========== DECISAO: CONSOLIDAR OU PEGAR DIRETO? ==========
            # Condições para consolidar:
            # 1. Múltiplas spears em tiles diferentes (len > 1)
            # 2. Precisa de mais de 1 spear
            # 3. Há mais de 1 spear no total no chão
            # 4. Chance de consolidar (85% humanizado)
            should_consolidate = (
                ENABLE_CONSOLIDATION and
                len(all_spears) > 1 and
                spears_needed > 1 and
                total_on_ground > 1 and
                random.random() < CONSOLIDATE_CHANCE
            )

            if should_consolidate:
                _log(f"[Spear Action] CONSOLIDANDO: {len(all_spears)} tiles com spears, total={total_on_ground}, precisa={spears_needed}")

                # Escolhe tile destino (prefere tile do player se houver spear la)
                target_spear = None
                for s in all_spears:
                    if s['rel_x'] == 0 and s['rel_y'] == 0:  # Tile do player
                        target_spear = s
                        break
                if target_spear is None:
                    target_spear = all_spears[0]  # Primeiro encontrado

                # Executa consolidação
                consolidated = consolidate_spears(
                    mapper, analyzer, packet, pm, base_addr, player_id,
                    all_spears, target_spear, my_x, my_y, my_z
                )

                if consolidated == 0:
                    _log("[Spear Action] Consolidacao falhou/abortou")
                    time.sleep(SCAN_TILES_DELAY)
                    continue

                # Re-le mapa apos consolidacao
                if not mapper.read_full_map(player_id):
                    time.sleep(0.3)
                    continue

                # Atualiza posicao (pode ter se movido)
                my_x, my_y, my_z = get_player_pos(pm, base_addr)

            # Busca spear (agora deve estar consolidada se foi o caso)
            spear_location = find_spear_on_adjacent_tiles(mapper, my_x, my_y, my_z)

            if spear_location is None:
                # Cleanup: se estava em priority pickup e spear sumiu, libera cavebot
                if state.is_spear_pickup_pending:
                    state.set_spear_pickup_pending(False)
                    _log("[Spear Action] Spear não encontrada - cavebot liberado")
                time.sleep(SCAN_TILES_DELAY)
                continue

            pre_abs_x, pre_abs_y, _, _, pre_rel_x, pre_rel_y, _ = spear_location
            #print(f"[Spear Action] Detectou spear em tile ({pre_abs_x},{pre_abs_y}) rel=({pre_rel_x},{pre_rel_y})")

            # ========== VERIFICAÇÃO DE PAUSE ANTES DE INICIAR PICKUP ==========
            if not get_enabled():
                _log("[Spear Action] Módulo desativado - abortando antes do pickup")
                continue

            # ========== ATIVA FLAG: PICKUP ATIVO ==========
            # Encontrou spear e vai pegar - pausa cavebot durante o processo
            if not state.is_spear_pickup_pending:
                state.set_spear_pickup_pending(True)
                _log("[Spear Action] PICKUP ATIVO - cavebot pausado")

            # ========== VERIFICAÇÃO DE PAUSE ANTES DO DELAY ==========
            if not get_enabled():
                _log("[Spear Action] Módulo desativado durante pickup - abortando")
                state.set_spear_pickup_pending(False)
                continue

            # ========== DELAY DE REAÇÃO HUMANIZADO ==========
            # Simula tempo para "perceber" que tem spear no chão (min 250ms + variacao)
            gauss_wait(REACTION_DELAY_MIN, 30)

            # ===== VERIFICAÇÃO CRÍTICA: Loot pode ter sido aberto durante delay =====
            if state.is_processing_loot:
                _log("[Spear Action] Loot foi aberto durante delay de reação - abortando")
                state.set_spear_pickup_pending(False)  # Cleanup: libera cavebot
                continue
            # ========================================================================

            # === RELE ESTADO (pode ter mudado durante delay de reação) ===
            my_x, my_y, my_z = get_player_pos(pm, base_addr)
            current_cap = get_player_cap(pm, base_addr)
            state_data = shared_state.get_action_state()  # Estado atualizado pelo monitor
            current_spears = state_data['current_spears']
            max_spears = state_data['max_spears']

            if current_spears >= max_spears:
                _log("[Spear Action] Ficou cheio durante delay de reacao")
                state.set_spear_pickup_pending(False)  # Cleanup: libera cavebot
                continue

            # Rele mapa
            if not mapper.read_full_map(player_id):
                time.sleep(0.3)
                state.set_spear_pickup_pending(False)  # Cleanup: libera cavebot
                continue

            spear_location = find_spear_on_adjacent_tiles(mapper, my_x, my_y, my_z)
            if spear_location is None:
                _log("[Spear Action] Spear sumiu durante delay de reacao")
                state.set_spear_pickup_pending(False)  # Cleanup: libera cavebot
                continue

            abs_x, abs_y, z, spear_list_index, rel_x, rel_y, tile = spear_location

            # === DEBUG: Mostra todos os items no tile ===
            #print(f"[Spear Action] Tile ({abs_x}, {abs_y}, {z}) rel=({rel_x}, {rel_y}) - {len(tile.items)} items:")
            first_movable = -1
            for idx, item_id in enumerate(tile.items):
                data1 = 0
                data2 = 0
                if hasattr(tile, 'items_debug') and idx < len(tile.items_debug):
                    _, data1, data2, _ = tile.items_debug[idx]

                can_move = is_movable_item(item_id)
                item_type = "MOVABLE" if can_move else "MAP_OBJ"

                if can_move and first_movable == -1:
                    first_movable = idx

                marker = ""
                if item_id == SPEAR_ID:
                    marker = f" <-- SPEAR"
                elif item_id == CREATURE_ID:
                    marker = " (CREATURE)"

                #print(f"  [idx={idx}] ID={item_id} | {item_type} data1={data1} data2={data2} movable={can_move}{marker}")

            #print(f"[Spear Action] Spear em idx={spear_list_index}, primeiro_movable={first_movable}")

            # === VERIFICAR ITEMS ACIMA DA SPEAR ===
            items_above = get_items_above_spear(tile, spear_list_index)
            if items_above:
                #print(f"[Spear Action] {len(items_above)} items MOVEIS acima da spear:")
                for item_id, list_idx in items_above:
                    _log(f"  - ID={item_id} em idx={list_idx}")
            else:
                _log(f"[Spear Action] Nenhum item movel acima da spear (idx < {spear_list_index})")

            # === MOVER BLOQUEADORES (se necessário) ===
            if items_above:
                # ===== VERIFICAÇÃO DEFENSIVA: Loot pode ter sido aberto antes de find_drop_tile =====
                if state.is_processing_loot:
                    _log("[Spear Action] Loot foi aberto antes de mover bloqueadores - abortando")
                    state.set_spear_pickup_pending(False)  # Cleanup: libera cavebot
                    continue
                # =====================================================================================

                drop_tile = find_drop_tile_for_blocker(mapper, my_x, my_y, my_z)

                if drop_tile is None:
                    _log("[Spear Action] Nao encontrou tile valido para mover items bloqueadores")
                    state.set_spear_pickup_pending(False)  # Cleanup: libera cavebot
                    continue

                drop_x, drop_y, drop_z = drop_tile
                #print(f"[Spear Action] Movendo {len(items_above)} items bloqueadores para tile drop=({drop_x}, {drop_y}, {drop_z})")

                for idx_move, (item_id, list_idx) in enumerate(items_above):
                    # ===== VERIFICAÇÃO DE PAUSE =====
                    if not get_enabled():
                        _log("[Spear Action] Módulo desativado durante move de bloqueadores - abortando")
                        state.set_spear_pickup_pending(False)
                        break

                    # ===== VERIFICAÇÃO CRÍTICA: Loot pode abrir durante delays entre moves =====
                    if state.is_processing_loot:
                        _log(f"[Spear Action] Loot foi aberto durante move #{idx_move} de bloqueadores - abortando")
                        continue
                    # ============================================================================

                    # Usa get_item_stackpos() para obter o stack_pos do bloqueador específico
                    # (items_above contém itens com índice < spear = visualmente acima da spear)
                    blocker_stack_pos = analyzer.get_item_stackpos(rel_x, rel_y, item_id)
                    if blocker_stack_pos < 0:
                        _log(f"[Spear Action] Bloqueador ID={item_id} não encontrado - pulando")
                        continue

                    from_pos = get_ground_pos(abs_x, abs_y, z)
                    to_pos = get_ground_pos(drop_x, drop_y, drop_z)

                    with PacketMutex("spear_picker"):
                        packet.move_item(from_pos, to_pos, item_id, 1, blocker_stack_pos, apply_delay=True)

                    #print(f"[Spear Action] Moveu bloqueador ID={item_id} (stack_pos={blocker_stack_pos}) de ({abs_x},{abs_y},{z}) -> ({drop_x},{drop_y},{drop_z})")

                    # Re-lê o mapa para atualizar o estado do tile
                    mapper.read_full_map(player_id)

                    # ========== DELAY GLOBAL ENTRE MOVE_ITEMS ==========
                    if idx_move < len(items_above) - 1:
                        gauss_wait(MOVE_ITEM_DELAY_MIN, 30)
                        _log(f"[Spear Action] Delay global entre move_items: {MOVE_ITEM_DELAY_MIN}s base")

                # Rele mapa após mover bloqueadores
                if not mapper.read_full_map(player_id):
                    time.sleep(0.3)
                    state.set_spear_pickup_pending(False)  # Cleanup: libera cavebot
                    continue

                # ========== DELAY GLOBAL APÓS MOVER BLOQUEADORES ==========
                gauss_wait(MOVE_ITEM_DELAY_MIN, 30)
                _log(f"[Spear Action] Delay global após move_items antes de pegar spear")

                # ===== VERIFICAÇÃO CRÍTICA: Loot pode ter sido aberto durante moves dos bloqueadores =====
                if state.is_processing_loot:
                    _log("[Spear Action] Loot foi aberto durante move dos bloqueadores - abortando")
                    state.set_spear_pickup_pending(False)  # Cleanup: libera cavebot
                    continue
                # ================================================================================================

            # Re-read map AFTER delay to get updated stack positions
            if not mapper.read_full_map(player_id):
                time.sleep(0.3)
                state.set_spear_pickup_pending(False)
                _log("[Spear Action] Falha ao re-ler mapa após delay de bloqueadores")
                continue

            # === CALCULA STACK_POS (usando nova função utilitária) ===
            spear_stack_pos = analyzer.get_item_stackpos(rel_x, rel_y, SPEAR_ID)
            if spear_stack_pos < 0:
                _log(f"[Spear Action] Spear não encontrada no tile após mover bloqueadores")
                state.set_spear_pickup_pending(False)  # Cleanup: libera cavebot
                continue
            _log(f"[Spear Action] Stack_pos da spear: {spear_stack_pos}")

            # === RE-LÊ ESTADO ATUALIZADO (permite mudança on-the-fly de max_spears) ===
            state_data = shared_state.get_action_state()
            current_spears = state_data['current_spears']
            max_spears = state_data['max_spears']

            # Verifica se ainda precisa de spears após possível mudança de config
            if current_spears >= max_spears:
                _log(f"[Spear Action] Já tem {current_spears}/{max_spears} spears - config mudou")
                state.set_spear_pickup_pending(False)
                continue

            # === CALCULA QUANTIDADE A PEGAR ===
            # Obtém tile atualizado para ler o count corretamente
            fresh_tile = mapper.get_tile_visible(rel_x, rel_y)
            spears_on_tile = get_stack_count(fresh_tile, spear_stack_pos) if fresh_tile else 1
            cap_allows = int(current_cap / SPEAR_WEIGHT)
            space_left = max_spears - current_spears

            count_to_pick = min(spears_on_tile, cap_allows, space_left)
            count_to_pick = max(1, count_to_pick)

            #print(f"[Spear Action] Estado: cap={current_cap:.1f}oz, spears_na_mao={current_spears}/{max_spears}, spears_no_tile={spears_on_tile}")
            #print(f"[Spear Action] Limites: tile={spears_on_tile}, cap_permite={cap_allows}, falta_para_max={space_left}")
            #print(f"[Spear Action] Pegando count={count_to_pick} spear(s) com stack_pos={spear_stack_pos}")

            # === MOVE SPEAR PARA MÃO ===
            # ===== VERIFICAÇÃO DE PAUSE ANTES DE PEGAR SPEAR =====
            if not get_enabled():
                _log("[Spear Action] Módulo desativado antes de pegar spear - abortando")
                state.set_spear_pickup_pending(False)
                continue

            # ===== VERIFICAÇÃO FINAL: Loot pode ter sido aberto durante moves de bloqueadores =====
            if state.is_processing_loot:
                _log("[Spear Action] Loot foi aberto - abortando antes de pegar spear")
                state.set_spear_pickup_pending(False)  # Cleanup: libera cavebot
                continue
            # =======================================================================================

            from_pos = get_ground_pos(abs_x, abs_y, z)
            to_pos = get_inventory_pos(target_hand)
            hand_name = "direita" if target_hand == SLOT_RIGHT else "esquerda"

            _log(f"[Spear Action] move_item: from=({abs_x},{abs_y},{z}) to=hand_{target_hand}({hand_name}) id={SPEAR_ID} count={count_to_pick} stack_pos={spear_stack_pos}")

            with PacketMutex("spear_picker"):
                packet.move_item(from_pos, to_pos, SPEAR_ID, count_to_pick, spear_stack_pos, apply_delay=True)

            # Atualiza estado compartilhado (thread-safe)
            shared_state.update_after_pickup(count_to_pick)

            _log(f"[Spear Action] ✓ Pegou {count_to_pick} spear(s) do chao ({abs_x},{abs_y},{z}) -> mao {hand_name}")

            # ========== DELAY GLOBAL APÓS PEGAR SPEAR ==========
            gauss_wait(MOVE_ITEM_DELAY_MIN, 30)
            _log(f"[Spear Action] Delay global após pegar spear na mão")

            # ===== LIMPA PENDING FLAG SE CICLO PRIORITÁRIO COMPLETO =====
            if state.is_spear_pickup_pending:
                new_state = shared_state.get_action_state()
                _log(f"[Spear Action] Priority check: needs_spears={new_state['needs_spears']}, current={new_state['current_spears']}, max={new_state['max_spears']}")
                if not new_state['needs_spears']:
                    state.set_spear_pickup_pending(False)
                    state.end_loot_cycle()  # CRÍTICO: Reseta is_processing_loot para evitar bloqueio permanente
                    priority_pickup_start_time = None  # Reset timeout
                    _log("[Spear Action] ✓ Ciclo prioritário COMPLETO - cavebot liberado")
                    _log(f"[Spear Action]   state.is_spear_pickup_pending={state.is_spear_pickup_pending}")
            # ============================================================

        except Exception as e:
            _log(f"[Spear Action] Erro: {e}")
            time.sleep(1)


def spear_picker_loop(pm, base_addr, check_running, get_enabled, get_max_spears=lambda: 3, log_func=print):
    """
    Inicia o sistema de spear picker com 2 threads independentes.

    Arquitetura de 2 threads:

    Thread 1 (Monitor):
    - Monitora spears na mão constantemente (150ms)
    - Detecta ataques em tempo real
    - Atualiza flag needs_spears
    - Nunca bloqueia, sempre roda

    Thread 2 (Ações):
    - Busca spears no chão quando needs_spears=True
    - Executa move_items com delays humanizados
    - Pode bloquear, mas não afeta monitor
    - Usa dados sempre atualizados do monitor

    Delays humanizados (APENAS em ações):
    - Tempo de reação ao detectar spear: 250ms + variação 30%
    - Tempo entre move_items: 250ms + variação 30%

    Args:
        pm: Instancia do Pymem
        base_addr: Endereco base do processo
        check_running: Funcao que retorna False para encerrar
        get_enabled: Funcao que retorna True/False se modulo esta ativo
        get_max_spears: Funcao que retorna o maximo de spears configurado
        log_func: Funcao de log (default: print)
    """
    _log("[SpearPicker] Iniciando sistema com 2 threads independentes")

    # Estado compartilhado entre threads (thread-safe)
    shared_state = SpearPickerState()

    # Cria threads
    monitor_thread = threading.Thread(
        target=monitor_hand_loop,
        args=(pm, base_addr, check_running, get_enabled, get_max_spears, shared_state),
        name="SpearMonitor",
        daemon=True
    )

    action_thread = threading.Thread(
        target=action_loop,
        args=(pm, base_addr, check_running, get_enabled, shared_state),
        name="SpearAction",
        daemon=True
    )

    # Inicia threads
    monitor_thread.start()
    action_thread.start()

    _log("[SpearPicker] Threads iniciadas: Monitor + Action")

    # Aguarda threads finalizarem
    try:
        monitor_thread.join()
        action_thread.join()
    except KeyboardInterrupt:
        _log("[SpearPicker] Interrompido pelo usuário")
