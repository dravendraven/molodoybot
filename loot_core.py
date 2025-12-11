import pymem
from config import *

# Classes para facilitar o uso dos dados depois
class Item:
    def __init__(self, item_id, count, slot_index):
        self.id = item_id
        self.count = count
        self.slot_index = slot_index # Importante para saber onde clicar depois

    def __repr__(self):
        return f"[ID: {self.id} | Qt: {self.count}]"

class Container:
    def __init__(self, index, address, name, amount, items):
        self.index = index      # 0 a 15
        self.address = address  # Endereço na memória
        self.name = name        # Nome (ex: "Backpack")
        self.amount = amount    # Quantos itens tem
        self.items = items      # Lista de objetos Item

    def __repr__(self):
        return f"Container {self.index}: {self.name} ({self.amount} itens)"

def read_container_name(pm, address):
    """Lê a string do nome do container na memória."""
    try:
        # O nome tem offset 16. Vamos ler até 32 chars.
        # No C# ele usa Memory.ReadString.
        name = pm.read_string(address + OFFSET_CNT_NAME, 32)
        return name
    except:
        return "Unknown"

def scan_containers(pm, base_addr):
    """
    Varre a memória em busca de todos os containers abertos.
    Retorna uma lista de objetos Container.
    """
    open_containers = []

    # Loop pelos 16 slots possíveis de container
    for i in range(MAX_CONTAINERS):
        # Cálculo do endereço deste container específico
        # Endereço = BaseDll + StartOffset + (Indice * TamanhoContainer)
        cnt_addr = base_addr + OFFSET_CONTAINER_START + (i * STEP_CONTAINER)
        
        try:
            # 1. Verifica se está aberto
            # Em C#: Memory.ReadByte(i + DistanceIsOpen) == 1
            is_open = pm.read_int(cnt_addr + OFFSET_CNT_IS_OPEN)
            
            # Nota: Às vezes lê como int (1) ou byte. Se falhar, tente read_bytes e ord()
            # O valor 1 significa aberto.
            if is_open == 1:
                
                # 2. Lê informações básicas
                name = read_container_name(pm, cnt_addr)
                amount = pm.read_int(cnt_addr + OFFSET_CNT_AMOUNT)
                
                # 3. Lê os itens dentro do container
                items = []
                for slot in range(amount):
                    # Cálculo do endereço do item neste slot
                    # ItemAddr = ContainerAddr + OffsetItemID + (Slot * TamanhoSlot)
                    # Nota: Inventory.cs usa int para ID e byte para Count.
                    
                    item_id_addr = cnt_addr + OFFSET_CNT_ITEM_ID + (slot * STEP_SLOT)
                    item_cnt_addr = cnt_addr + OFFSET_CNT_ITEM_COUNT + (slot * STEP_SLOT)
                    
                    item_id = pm.read_int(item_id_addr)
                    raw_count = pm.read_int(item_cnt_addr)
                    
                    # CORREÇÃO: Se tem ID mas contagem é 0, assume que é 1 (item não empilhável)
                    final_count = max(1, raw_count)
                    
                    if item_id > 0:
                        items.append(Item(item_id, final_count, slot))
                
                # Cria o objeto e adiciona na lista
                container_obj = Container(i, cnt_addr, name, amount, items)
                open_containers.append(container_obj)
                
        except Exception as e:
            print(f"Erro ao ler container {i}: {e}")
            continue

    return open_containers

def get_container_top_y(pm, base_addr, container_index):
    """
    Calcula a posição Y do TOPO do container na tela.
    Usa lógica inteligente para detectar janelas extras (Battle, VIP, etc).
    """
    current_y = 0
    
    try:
        # 1. Ler todas as alturas de janelas abertas na GUI
        gui_ptr = pm.read_int(base_addr + OFFSET_GUI_POINTER)
        ptr = pm.read_int(gui_ptr + GUI_OFFSET_1)
        ptr = pm.read_int(ptr + GUI_OFFSET_2)
        
        window_heights = []
        
        # Limite de segurança de 20 janelas para não travar
        for _ in range(20):
            if ptr == 0: break
            
            win_struct = pm.read_int(ptr + GUI_OFFSET_WINDOW_STRUCT)
            height = pm.read_int(win_struct + GUI_OFFSET_WINDOW_HEIGHT)
            window_heights.append(height)
            
            ptr = pm.read_int(ptr + GUI_OFFSET_NEXT_WINDOW)
            
        # 2. Descobrir quantos containers temos abertos na memória
        # (Precisamos scanear rapidinho ou passar como argumento. 
        #  Para ser robusto, vamos contar os containers ativos aqui mesmo).
        total_containers = 0
        for i in range(MAX_CONTAINERS):
            cnt_addr = base_addr + OFFSET_CONTAINER_START + (i * STEP_CONTAINER)
            if pm.read_int(cnt_addr + OFFSET_CNT_IS_OPEN) == 1:
                total_containers += 1
        
        # 3. Calcular o "Desvio" (Offset)
        # Ex: Se temos 2 janelas na GUI mas só 1 Container, o desvio é 1 (Battle está aberto).
        # Assumimos que os containers são sempre as ÚLTIMAS janelas da lista.
        window_offset = len(window_heights) - total_containers
        
        # Índice real da janela correspondente ao container desejado
        target_window_index = window_offset + container_index
        
        # Proteção contra índices inválidos
        if target_window_index < 0 or target_window_index >= len(window_heights):
            return 0

        # 4. Somar altura APENAS das janelas ANTERIORES
        for i in range(target_window_index):
            # Soma altura da janela + cabeçalho
            current_y += window_heights[i] + GUI_HEADER_HEIGHT
            
        # Adiciona o cabeçalho da própria janela do container (para pular a barra de título dele)
        current_y += GUI_HEADER_HEIGHT
        
        return current_y
        
    except Exception as e:
        print(f"Erro GUI Y: {e}")
        return 0

def get_slot_screen_position(pm, base_addr, container_index, slot_index):
    """
    Retorna a tupla (X, Y) na tela para clicar no slot específico.
    """    
    cols = 4 # Backpacks padrão tem 4 colunas
    
    rel_x = (slot_index % cols) * SLOT_SIZE
    rel_y = (slot_index // cols) * SLOT_SIZE
    
    # Calcula o Y do topo desse container
    container_top_y = get_container_top_y(pm, base_addr, container_index)
    
    # Posição Final (Precisaremos definir o BASE_X_OFFSET depois)
    # Retorna apenas os offsets relativos ao "Início do Painel de Containers"
    return rel_x, container_top_y + rel_y