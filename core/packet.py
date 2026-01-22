import pymem
import struct
import time
import threading
import random
from enum import Enum
from config import *

# ==============================================================================
# LOCKS GLOBAIS - Compartilhados entre TODAS as instâncias de PacketManager
# ==============================================================================
_keyboard_lock = threading.Lock()
_mouse_lock = threading.Lock()

# Estado global por tipo de pacote (timestamp do último pacote)
_keyboard_last_time = 0.0
_mouse_last_time = 0.0

# ==============================================================================
# ENDEREÇOS E OPCODES (TIBIA 7.72)
# ==============================================================================
FUNC_CREATE_PACKET = 0x4CB2A0
FUNC_ADD_BYTE      = 0x4CB540
FUNC_ADD_STRING    = 0x4CBA20
FUNC_SEND_PACKET   = 0x4CBE00
FUNC_ADD_U16       = 0x4CB660

# Opcodes de Ação
OP_SAY    = 0x96
OP_ATTACK = 0xA1
OP_MOVE   = 0x78
OP_USE    = 0x82
OP_USE_ON = 0x83
OP_EQUIP  = 0x77
OP_LOOK   = 0x8C
OP_CLOSE_CONTAINER = 0x87
OP_QUIT_GAME = 0x14

# Opcodes de Movimento (Walk)
OP_WALK_NORTH = 0x65
OP_WALK_EAST  = 0x66
OP_WALK_SOUTH = 0x67
OP_WALK_WEST  = 0x68
OP_STOP       = 0xBE
OP_WALK_NORTH_EAST = 0x6A
OP_WALK_SOUTH_EAST = 0x6B
OP_WALK_SOUTH_WEST = 0x6C
OP_WALK_NORTH_WEST = 0x6D

# Opcodes de Fala (SpeakClasses)
TALK_SAY = 1

# ==============================================================================
# ENUM DE TIPO DE PACOTE
# ==============================================================================
class PacketType(Enum):
    KEYBOARD = "keyboard"  # Movimentos (walk), atalhos
    MOUSE = "mouse"        # Cliques (use_item, attack, move_item)
    ANY = "any"            # Outros (say, stop)

# ==============================================================================
#  BUILDER (Gera o assembly para os pacotes)
# ==============================================================================
class PacketBuilder:
    def __init__(self):
        self.asm = b''

    def add_call(self, func_addr, *args):
        for arg in reversed(args):
            if isinstance(arg, int):
                if -128 <= arg < 128:
                    self.asm += b'\x6A' + struct.pack('b', arg)  # PUSH byte
                else:
                    self.asm += b'\x68' + struct.pack('<I', arg)  # PUSH dword

        self.asm += b'\xB8' + struct.pack('<I', func_addr)  # MOV EAX, addr
        self.asm += b'\xFF\xD0'  # CALL EAX

        if args:
            cleanup = 4 * len(args)
            self.asm += b'\x83\xC4' + struct.pack('B', cleanup)

    def add_byte(self, val):
        self.add_call(FUNC_ADD_BYTE, val)

    def add_u16(self, val):
        self.add_byte(val & 0xFF)
        self.add_byte((val >> 8) & 0xFF)

    def add_u32(self, val):
        self.add_byte(val & 0xFF)
        self.add_byte((val >> 8) & 0xFF)
        self.add_byte((val >> 16) & 0xFF)
        self.add_byte((val >> 24) & 0xFF)

    def add_string(self, text):
        pass

    def get_code(self):
        return self.asm + b'\xC3'

# ==============================================================================
# HELPERS DE POSIÇÃO (Funções de módulo - sem mudança)
# ==============================================================================
def get_container_pos(container_index, slot_index):
    """Retorna struct de posição para Container."""
    return {'x': 0xFFFF, 'y': 0x40 + container_index, 'z': slot_index}

def get_inventory_pos(slot_enum):
    """
    Retorna struct para Slots do Corpo (Mãos, Ammo, etc).
    SlotEnum: 1=Head, 3=BP, 5=Right, 6=Left, 10=Ammo
    """
    return {'x': 0xFFFF, 'y': slot_enum, 'z': 0}

def get_ground_pos(x, y, z):
    return {'x': x, 'y': y, 'z': z}

# ==============================================================================
# PACKET MANAGER (Classe principal)
# ==============================================================================
class PacketManager:
    """
    Gerenciador centralizado de pacotes com thread safety e delays humanizados.
    Usa locks GLOBAIS por tipo de pacote para sincronização entre módulos.
    """

    def __init__(self, pm, base_addr):
        """
        Args:
            pm: Instância do Pymem
            base_addr: Endereço base do processo (usado por attack)
        """
        self.pm = pm
        self.base_addr = base_addr

    def send_packet(self, asm_code: bytes, packet_type: PacketType, is_walk=False):
        """
        Método central com locks GLOBAIS por tipo.

        Args:
            asm_code: Código assembly gerado pelo PacketBuilder
            packet_type: Tipo do pacote (KEYBOARD, MOUSE, ANY)
            is_walk: Se True, usa delays mais curtos (key repeat)
        """
        global _keyboard_last_time, _mouse_last_time

        # Seleciona lock baseado no tipo
        if packet_type == PacketType.KEYBOARD:
            lock = _keyboard_lock
        else:
            lock = _mouse_lock  # MOUSE e ANY usam mouse lock

        with lock:
            now = time.time()

            # Tempo desde último pacote deste tipo
            if packet_type == PacketType.KEYBOARD:
                last_time = _keyboard_last_time
            else:
                last_time = _mouse_last_time

            elapsed = now - last_time

            # Calcula delay baseado no tipo
            if is_walk:
                # Walk: delay curto (key repeat ~30-50ms)
                delay = random.gauss(0.04, 0.01)  # ~40ms ± 10ms
                min_delay = 0.025  # Mínimo 25ms
            elif packet_type == PacketType.KEYBOARD:
                delay = random.gauss(0.02, 0.008)  # ~20ms ± 8ms
                min_delay = 0.015  # Mínimo 15ms
            else:
                # MOUSE: mais conservador
                delay = random.gauss(0.05, 0.015)  # ~50ms ± 15ms
                min_delay = 0.03  # Mínimo 30ms

            # Se não passou tempo suficiente, espera a diferença
            if elapsed < min_delay:
                time.sleep(min_delay - elapsed)
            else:
                time.sleep(max(0.01, delay))  # Delay humanizado

            self._inject_packet(asm_code)

            # Atualiza timestamp global
            if packet_type == PacketType.KEYBOARD:
                _keyboard_last_time = time.time()
            else:
                _mouse_last_time = time.time()

    def _inject_packet(self, asm_code: bytes):
        """Injeta código assembly no processo do jogo."""
        code_addr = 0
        try:
            code_addr = self.pm.allocate(len(asm_code) + 1024)
            self.pm.write_bytes(code_addr, asm_code, len(asm_code))
            self.pm.start_thread(code_addr)
            time.sleep(0.05)
        except Exception as e:
            print(f"Erro Packet: {e}")
        finally:
            if code_addr:
                self.pm.free(code_addr)

    # ==========================================================================
    # MÉTODOS DE AÇÃO
    # ==========================================================================

    def attack(self, creature_id):
        """
        Envia o pacote de ataque (0xA1) e atualiza o alvo visualmente no cliente.
        Baseado em Attack.cs: [OpCode] [ID] [ID]

        Args:
            creature_id: ID da criatura alvo
        """
        pb = PacketBuilder()
        pb.add_call(FUNC_CREATE_PACKET, OP_ATTACK)
        pb.add_u32(creature_id)
        pb.add_u32(creature_id)
        pb.add_call(FUNC_SEND_PACKET, 1)

        self.send_packet(pb.get_code(), PacketType.MOUSE)

        # Atualiza o target visual no cliente
        try:
            target_ptr_offset = 0x1C681C
            self.pm.write_int(self.base_addr + target_ptr_offset, creature_id)
        except Exception as e:
            print(f"Erro ao definir Target visual: {e}")

    def walk(self, direction_code):
        """
        Envia pacote de movimento (N, S, E, W, NE, SE, SW, NW).
        Usa delays curtos (is_walk=True) para simular key repeat.

        Args:
            direction_code: Opcode de direção (OP_WALK_NORTH, etc)
        """
        pb = PacketBuilder()
        pb.add_call(FUNC_CREATE_PACKET, direction_code)
        pb.add_call(FUNC_SEND_PACKET, 1)

        # is_walk=True permite delays mais curtos (key repeat)
        self.send_packet(pb.get_code(), PacketType.KEYBOARD, is_walk=True)

    def stop(self):
        """Envia o pacote de STOP (Parar personagem)."""
        pb = PacketBuilder()
        pb.add_call(FUNC_CREATE_PACKET, OP_STOP)
        pb.add_call(FUNC_SEND_PACKET, 1)

        self.send_packet(pb.get_code(), PacketType.KEYBOARD)

    def move_item(self, from_pos, to_pos, item_id, count, stack_pos=0, apply_delay=False):
        """
        Move/Arrasta item.

        Args:
            from_pos: Posição de origem (dict com x, y, z)
            to_pos: Posição de destino (dict com x, y, z)
            item_id: ID do item a mover
            count: Quantidade de itens a mover
            stack_pos: Posição na pilha (0=fundo, aumenta para cima)
            apply_delay: Se True, aplica delay humanizado de drag & drop.
                         Default: False (compatibilidade com código existente que já tem delays próprios)
        """
        # Delay humanizado ANTES de enviar o pacote (apenas se solicitado)
        if apply_delay:
            self._apply_move_item_delay(from_pos, to_pos)

        pb = PacketBuilder()
        pb.add_call(FUNC_CREATE_PACKET, OP_MOVE)

        pb.add_u16(from_pos['x'])
        pb.add_u16(from_pos['y'])
        pb.add_byte(from_pos['z'])
        pb.add_u16(item_id)
        pb.add_byte(stack_pos)

        pb.add_u16(to_pos['x'])
        pb.add_u16(to_pos['y'])
        pb.add_byte(to_pos['z'])
        pb.add_byte(count)

        pb.add_call(FUNC_SEND_PACKET, 1)

        self.send_packet(pb.get_code(), PacketType.MOUSE)

    def smart_move_item(self, from_pos, to_pos, item_id, count, analyzer, player_x, player_y, apply_delay=False):
        """
        Move item com detecção automática de stack_pos.

        Args:
            from_pos: Posição de origem (dict com x, y, z)
            to_pos: Posição de destino (dict com x, y, z)
            item_id: ID do item a mover
            count: Quantidade a mover
            analyzer: MapAnalyzer instance (para detectar stack_pos)
            player_x, player_y: Posição absoluta do player (para converter abs->rel)
            apply_delay: Se True, aplica delay humanizado

        Returns:
            tuple: (success: bool, stack_pos: int) - stack_pos usado ou -1 se falhou
        """
        stack_pos = 0

        # Se é posição no mapa (não container/inventory), detecta stack_pos
        if from_pos['x'] != 0xFFFF:
            # Converte posição absoluta para relativa ao player
            rel_x = from_pos['x'] - player_x
            rel_y = from_pos['y'] - player_y

            stack_pos = analyzer.get_item_stackpos(rel_x, rel_y, item_id)

            if stack_pos < 0:
                # Item específico não encontrado, tenta pegar o topo movível
                top_id, top_pos = analyzer.get_top_movable_stackpos(rel_x, rel_y)
                if top_pos >= 0:
                    stack_pos = top_pos
                else:
                    return (False, -1)  # Nada para mover

        self.move_item(from_pos, to_pos, item_id, count, stack_pos, apply_delay)
        return (True, stack_pos)

    def use_item(self, pos, item_id, stack_pos=0, index=0):
        """
        Usa item (Clique Direito).

        Args:
            pos: Posição do item (dict com x, y, z)
            item_id: ID do item
            stack_pos: Posição na pilha
            index: Índice do container
        """
        pb = PacketBuilder()
        pb.add_call(FUNC_CREATE_PACKET, OP_USE)

        pb.add_u16(pos['x'])
        pb.add_u16(pos['y'])
        pb.add_byte(pos['z'])
        pb.add_u16(item_id)
        pb.add_byte(stack_pos)
        pb.add_byte(index)

        pb.add_call(FUNC_SEND_PACKET, 1)

        self.send_packet(pb.get_code(), PacketType.MOUSE)

    def _apply_use_with_delay(self, rel_x, rel_y=0):
        """
        Aplica delay proporcional à posição visual do target.

        Lógica: UI (inventário) fica à DIREITA da tela.
        - rel_x > 0 (tile à direita) = mais PERTO da UI = delay MENOR
        - rel_x < 0 (tile à esquerda) = mais LONGE da UI = delay MAIOR
        - rel_y afeta menos (movimento vertical é mais curto)

        Args:
            rel_x: Posição X relativa (-7 a +7). 7 = extrema direita (perto do inv)
            rel_y: Posição Y relativa (-5 a +5). Opcional.
        """
        # Normaliza: transforma rel_x de (-7, +7) para fator de distância
        # rel_x = 7 (perto do inv) -> fator = 0 (sem delay extra)
        # rel_x = -7 (longe do inv) -> fator = 14 (delay máximo)
        MAX_REL_X = 7
        distance_factor = MAX_REL_X - rel_x  # Range: 0 (perto) a 14 (longe)

        # Componente Y (menor peso - movimento vertical mais curto)
        if rel_y is not None:
            distance_factor += abs(rel_y) * 0.3

        # Delay: base + proporcional à distância
        # Base: ~100ms (tempo mínimo para mover mouse da UI para game view)
        # Extra: ~15ms por unidade de distância
        base_delay = random.gauss(0.10, 0.02)  # ~100ms ± 20ms
        extra_delay = distance_factor * random.gauss(0.015, 0.003)  # ~15ms/unidade

        total_delay = max(0.08, base_delay + extra_delay)  # Mínimo 80ms
        time.sleep(total_delay)

    def _apply_move_item_delay(self, from_pos, to_pos):
        """
        Aplica delay humanizado para arrastar item (drag & drop).

        Simula o tempo que um jogador humano levaria para:
        1. Localizar o item na tela
        2. Clicar e segurar
        3. Arrastar até o destino
        4. Soltar

        Tipos de posição:
        - Ground: x < 0xFFFF (coordenadas do mapa)
        - Inventory/Container: x == 0xFFFF (UI)

        Cenários:
        - Ground → Ground: distância em tiles
        - Ground → Inventory: tile até UI (direita da tela)
        - Inventory → Ground: UI até tile
        - Inventory → Inventory: UI para UI (mais rápido)
        """
        is_from_ground = from_pos['x'] != 0xFFFF
        is_to_ground = to_pos['x'] != 0xFFFF

        # Tempo base de reação (localizar item + iniciar drag)
        base_reaction = random.gauss(0.25, 0.05)  # ~250ms ± 50ms

        if is_from_ground and is_to_ground:
            # Ground → Ground: distância em tiles
            dx = abs(to_pos['x'] - from_pos['x'])
            dy = abs(to_pos['y'] - from_pos['y'])
            tile_distance = max(dx, dy)  # Chebyshev distance
            # ~30ms por tile de distância
            drag_time = tile_distance * random.gauss(0.03, 0.008)

        elif is_from_ground and not is_to_ground:
            # Ground → Inventory/Container: tile até UI
            # UI fica à direita, então tiles à esquerda = mais longe
            # Assumimos player no centro (rel_x = 0)
            # Distância média: ~10 "unidades" de tela
            drag_time = random.gauss(0.15, 0.03)  # ~150ms

        elif not is_from_ground and is_to_ground:
            # Inventory → Ground: UI até tile
            drag_time = random.gauss(0.15, 0.03)  # ~150ms

        else:
            # Inventory → Inventory/Container: UI para UI
            # Movimento mais curto (mesma região da tela)
            drag_time = random.gauss(0.08, 0.02)  # ~80ms

        # Tempo de soltar o item (release)
        release_time = random.gauss(0.05, 0.015)  # ~50ms

        total_delay = base_reaction + drag_time + release_time
        total_delay = max(0.20, total_delay)  # Mínimo 200ms

        time.sleep(total_delay)

    def use_with(self, from_pos, from_id, from_stack, to_pos, to_id, to_stack, rel_x=None, rel_y=None):
        """
        Envia pacote 'Use with...' (0x83).
        Usado para Pescar, usar Rope, usar Shovel, Runas em alvo, etc.

        Args:
            from_pos: Posição do item fonte (dict com x, y, z)
            from_id: ID do item fonte
            from_stack: Stack position do item fonte
            to_pos: Posição do alvo (dict com x, y, z)
            to_id: ID do item/tile alvo
            to_stack: Stack position do alvo
            rel_x: (Opcional) Posição X relativa ao player (-7 a +7)
            rel_y: (Opcional) Posição Y relativa ao player (-5 a +5)
        """
        # Delay humanizado ANTES de construir o packet
        if rel_x is not None and from_pos['x'] == 0xFFFF:
            self._apply_use_with_delay(rel_x, rel_y)

        pb = PacketBuilder()
        pb.add_call(FUNC_CREATE_PACKET, OP_USE_ON)

        # Origem
        pb.add_u16(from_pos['x'])
        pb.add_u16(from_pos['y'])
        pb.add_byte(from_pos['z'])
        pb.add_u16(from_id)
        pb.add_byte(from_stack)

        # Destino
        pb.add_u16(to_pos['x'])
        pb.add_u16(to_pos['y'])
        pb.add_byte(to_pos['z'])
        pb.add_u16(to_id)
        pb.add_byte(to_stack)

        pb.add_call(FUNC_SEND_PACKET, 1)

        self.send_packet(pb.get_code(), PacketType.MOUSE)

    def say(self, text):
        """
        Usa a função interna 'Say' do jogo (0x4067C0) que já lida com strings.

        Args:
            text: Texto a ser falado
        """
        FUNC_SAY = 0x4067C0
        try:
            # Aloca string
            text_bytes = text.encode('latin-1') + b'\x00'
            text_addr = self.pm.allocate(len(text_bytes))
            self.pm.write_bytes(text_addr, text_bytes, len(text_bytes))

            # Monta assembly: Push TextPtr, Push Mode(1), Call Say
            asm = b'\x68' + struct.pack('<I', text_addr) + \
                  b'\x6A\x01' + \
                  b'\xB8' + struct.pack('<I', FUNC_SAY) + \
                  b'\xFF\xD0' + \
                  b'\x83\xC4\x08' + \
                  b'\xC3'

            self.send_packet(asm, PacketType.ANY)

            time.sleep(0.1)
            self.pm.free(text_addr)
        except Exception as e:
            print(f"Erro Say: {e}")

    def look_at(self, pos, item_id, stack_pos=0):
        """
        Envia pacote Look (0x8C).

        Args:
            pos: Posição do item (dict com x, y, z)
            item_id: ID do item
            stack_pos: Stack position (0 = Topo)
        """
        pb = PacketBuilder()
        pb.add_call(FUNC_CREATE_PACKET, OP_LOOK)

        pb.add_u16(pos['x'])
        pb.add_u16(pos['y'])
        pb.add_byte(pos['z'])
        pb.add_u16(item_id)
        pb.add_byte(stack_pos)

        pb.add_call(FUNC_SEND_PACKET, 1)

        self.send_packet(pb.get_code(), PacketType.MOUSE)

    def close_container(self, container_id):
        """
        Fecha um container específico.

        Args:
            container_id: ID do container a fechar
        """
        pb = PacketBuilder()
        pb.add_call(FUNC_CREATE_PACKET, OP_CLOSE_CONTAINER)
        pb.add_byte(container_id)
        pb.add_call(FUNC_SEND_PACKET, 1)

        self.send_packet(pb.get_code(), PacketType.MOUSE)

    def equip_object(self, item_id, data=0):
        """
        Envia pacote 0x77 (EquipObject).
        O servidor decide automaticamente para qual slot o item vai.

        Args:
            item_id: ID do item a equipar
            data: Dados adicionais (geralmente 0)
        """
        pb = PacketBuilder()
        pb.add_call(FUNC_CREATE_PACKET, OP_EQUIP)

        pb.add_u16(item_id)
        pb.add_byte(data)

        pb.add_call(FUNC_SEND_PACKET, 1)

        self.send_packet(pb.get_code(), PacketType.MOUSE)

    def quit_game(self):
        """
        Envia pacote QuitGame (0x14) para deslogar do servidor.
        O pacote é simples: apenas o opcode, sem dados adicionais.
        """
        pb = PacketBuilder()
        pb.add_call(FUNC_CREATE_PACKET, OP_QUIT_GAME)
        pb.add_call(FUNC_SEND_PACKET, 1)

        self.send_packet(pb.get_code(), PacketType.ANY)
