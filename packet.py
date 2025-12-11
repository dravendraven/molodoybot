import pymem
import struct
import time
from config import *

# ==============================================================================
# ENDEREÇOS E OPCODES (TIBIA 7.72)
# ==============================================================================
FUNC_CREATE_PACKET = 0x4CB2A0
FUNC_ADD_BYTE      = 0x4CB540
FUNC_ADD_STRING    = 0x4CBA20
FUNC_SEND_PACKET   = 0x4CBE00

# Opcodes de Ação
OP_SAY    = 0x96
OP_ATTACK = 0xA1
OP_MOVE   = 0x78
OP_USE    = 0x82
OP_USE_ON = 0x83
OP_EQUIP  = 0x77 #
OP_LOOK   = 0x8C

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

class PacketBuilder:
    def __init__(self):
        self.asm = b''

    def add_call(self, func_addr, *args):
        for arg in reversed(args):
            if isinstance(arg, int):
                if -128 <= arg < 128:
                    self.asm += b'\x6A' + struct.pack('b', arg) # PUSH byte
                else:
                    self.asm += b'\x68' + struct.pack('<I', arg) # PUSH dword
        
        self.asm += b'\xB8' + struct.pack('<I', func_addr) # MOV EAX, addr
        self.asm += b'\xFF\xD0' # CALL EAX
        
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
        # Para string, precisamos alocar memória para o texto primeiro?
        # A função FUNC_ADD_STRING espera um ponteiro char*
        # Como estamos injetando assembly, é complexo alocar string dentro do blob.
        # TRUQUE: Vamos usar a função 'Say' original (0x4067C0) que já trata isso?
        # Não, vamos fazer o AddString funcionar. 
        # A string precisa estar na memória do jogo. 
        pass 

    def get_code(self):
        return self.asm + b'\xC3'

def inject_packet(pm, asm_code):
    code_addr = 0
    try:
        code_addr = pm.allocate(len(asm_code) + 1024)
        pm.write_bytes(code_addr, asm_code, len(asm_code))
        pm.start_thread(code_addr)
        time.sleep(0.05)
    except Exception as e:
        print(f"Erro Packet: {e}")
    finally:
        if code_addr: pm.free(code_addr)

# ==============================================================================
# HELPERS DE POSIÇÃO
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
# FUNÇÕES DE AÇÃO (API)
# ==============================================================================

def attack(pm, base_addr, creature_id):
    """
    Envia o pacote de ataque (0xA1) e atualiza o alvo visualmente no cliente.
    Baseado em Attack.cs: [OpCode] [ID] [ID]
    """
    # 1. PARTE DE REDE (Envia o comando para o servidor)
    pb = PacketBuilder()
    
    # Opcode 0xA1 (OP_ATTACK já está definido no seu packet.py)
    pb.add_call(FUNC_CREATE_PACKET, OP_ATTACK) 
    
    # O protocolo exige enviar o ID duas vezes (uint32)
    pb.add_u32(creature_id)
    pb.add_u32(creature_id)
    
    pb.add_call(FUNC_SEND_PACKET, 1)
    inject_packet(pm, pb.get_code())

    # 2. PARTE VISUAL (Opcional, mas recomendado)
    # Escreve o ID no ponteiro de Target para aparecer o quadrado vermelho imediatamente
    try:
        # Pega o ponteiro do Target definido no config.py
        # Nota: TARGET_ID_PTR em config.py parece ser um offset direto ou relativo
        # Vamos usar a constante que você já tem.
        target_ptr_offset = 0x1C681C # Valor do seu config.py (TARGET_ID_PTR)
        
        # Escreve na memória
        pm.write_int(base_addr + target_ptr_offset, creature_id)
    except Exception as e:
        print(f"Erro ao definir Target visual: {e}")

def walk(pm, direction_code):
    """Envia pacote de movimento (N, S, E, W)."""
    pb = PacketBuilder()
    pb.add_call(FUNC_CREATE_PACKET, direction_code)
    pb.add_call(FUNC_SEND_PACKET, 1)
    inject_packet(pm, pb.get_code())

def stop(pm):
    """Para o personagem."""
    walk(pm, OP_STOP)

def move_item(pm, from_pos, to_pos, item_id, count):
    """Move/Arrasta item."""
    pb = PacketBuilder()
    pb.add_call(FUNC_CREATE_PACKET, OP_MOVE)
    
    pb.add_u16(from_pos['x'])
    pb.add_u16(from_pos['y'])
    pb.add_byte(from_pos['z'])
    pb.add_u16(item_id)
    pb.add_byte(0) # Stackpos (geralmente 0 funciona)
    
    pb.add_u16(to_pos['x'])
    pb.add_u16(to_pos['y'])
    pb.add_byte(to_pos['z'])
    pb.add_byte(count)
    
    pb.add_call(FUNC_SEND_PACKET, 1)
    inject_packet(pm, pb.get_code())

def use_item(pm, pos, item_id, stack_pos=0, index=0):
    """Usa item (Clique Direito)."""
    pb = PacketBuilder()
    pb.add_call(FUNC_CREATE_PACKET, OP_USE)
    
    pb.add_u16(pos['x'])
    pb.add_u16(pos['y'])
    pb.add_byte(pos['z'])
    pb.add_u16(item_id)
    pb.add_byte(stack_pos)
    pb.add_byte(index)
    
    pb.add_call(FUNC_SEND_PACKET, 1)
    inject_packet(pm, pb.get_code())

def say(pm, text):
    """
    Usa a função interna 'Say' do jogo (0x4067C0) que já lida com strings.
    É mais fácil do que recriar o pacote de string manualmente.
    """
    FUNC_SAY = 0x4067C0
    try:
        # Aloca string
        text_bytes = text.encode('latin-1') + b'\x00'
        text_addr = pm.allocate(len(text_bytes))
        pm.write_bytes(text_addr, text_bytes, len(text_bytes))
        
        # Injeta chamada: Say(1, text_ptr)
        # Push TextPtr
        # Push Mode (1)
        # Call Say
        
        code_addr = pm.allocate(128)
        asm = b'\x68' + struct.pack('<I', text_addr) + \
              b'\x6A\x01' + \
              b'\xE8' + struct.pack('<i', FUNC_SAY - (code_addr + 5 + 7)) + \
              b'\x83\xC4\x08' + \
              b'\xC3'
              
        # Recalculo do CALL relativo é chato aqui pq depende do code_addr.
        # Vamos usar MOV EAX, ADDR -> CALL EAX que é absoluto.
        asm = b'\x68' + struct.pack('<I', text_addr) + \
              b'\x6A\x01' + \
              b'\xB8' + struct.pack('<I', FUNC_SAY) + \
              b'\xFF\xD0' + \
              b'\x83\xC4\x08' + \
              b'\xC3'

        pm.write_bytes(code_addr, asm, len(asm))
        pm.start_thread(code_addr)
        
        time.sleep(0.1)
        pm.free(text_addr)
        pm.free(code_addr)
    except Exception as e:
        print(f"Erro Say: {e}")

def use_with(pm, from_pos, from_id, from_stack, to_pos, to_id, to_stack):
    """
    Envia pacote 'Use with...' (0x83).
    Usado para Pescar, usar Rope, usar Shovel, Runas em alvo, etc.
    """
    pb = PacketBuilder()
    pb.add_call(FUNC_CREATE_PACKET, OP_USE_ON)
    
    # Origem (Vara)
    pb.add_u16(from_pos['x'])
    pb.add_u16(from_pos['y'])
    pb.add_byte(from_pos['z'])
    pb.add_u16(from_id)
    pb.add_byte(from_stack)
    
    # Destino (Água)
    pb.add_u16(to_pos['x'])
    pb.add_u16(to_pos['y'])
    pb.add_byte(to_pos['z'])
    pb.add_u16(to_id)
    pb.add_byte(to_stack)
    
    pb.add_call(FUNC_SEND_PACKET, 1)
    inject_packet(pm, pb.get_code())

def equip_object(pm, item_id, data=0):
    """
    Envia pacote 0x77 (EquipObject).
    Baseado em EquipObject.cs: Escreve ID (u16) + Data (byte).
    O servidor decide automaticamente para qual slot o item vai.
    """
    pb = PacketBuilder()
    pb.add_call(FUNC_CREATE_PACKET, OP_EQUIP)
    
    pb.add_u16(item_id) # ObjectId
    pb.add_byte(data)   # Data (Geralmente 0, ou stackpos/count)
    
    pb.add_call(FUNC_SEND_PACKET, 1)
    inject_packet(pm, pb.get_code())

    # Adicione esta função no final do arquivo, junto com as outras ações
def look_at(pm, pos, item_id, stack_pos=0):
    """
    Envia pacote Look (0x8C).
    Estrutura: [OpCode] [X][Y][Z] [ID] [Stack]
    """
    pb = PacketBuilder()
    pb.add_call(FUNC_CREATE_PACKET, OP_LOOK)
    
    # Posição
    pb.add_u16(pos['x'])
    pb.add_u16(pos['y'])
    pb.add_byte(pos['z'])
    
    # ID do Item (Obrigatório pelo protocolo)
    pb.add_u16(item_id)
    
    # Stack Position (0 = Topo, ou use um valor específico)
    pb.add_byte(stack_pos)
    
    pb.add_call(FUNC_SEND_PACKET, 1)
    inject_packet(pm, pb.get_code())