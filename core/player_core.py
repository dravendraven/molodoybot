# core/player_core.py
"""
Funções relacionadas ao jogador atual.
Centraliza código que estava duplicado em main.py, trainer.py e alarm.py.

IMPORTANTE: Estas funções leem memória em tempo real.
O nome do personagem é constante durante a sessão e pode ser
armazenado pelo caller após primeira leitura bem-sucedida.
"""

from config import (
    BATTLELIST_BEGIN_ADDRESS,
    TARGET_ID_PTR,
    REL_FIRST_ID,
    STEP_SIZE,
    MAX_CREATURES,
    OFFSET_PLAYER_ID,
    OFFSET_NAME,
    OFFSET_X,
    OFFSET_Y,
    OFFSET_Z,
    OFFSET_HP,
    OFFSET_SPEED,
)

def get_player_speed(pm, base_addr) -> int:
    """
    Escaneia a Battle List (endereço fixo) procurando pelo próprio player
    para ler o Speed atual.

    Args:
        pm: Instância do Pymem
        base_addr: Endereço base do módulo Tibia

    Returns:
        int: Velocidade atual do player (ex: 220).
             Retorna 220 (padrão) se não encontrar.
    """
    try:
        # 1. Ler o ID do Player Logado
        try:
            player_id = pm.read_int(base_addr + OFFSET_PLAYER_ID)
        except Exception as e:
            print(f"[PlayerCore] Failed to read player ID: {e}")
            return 220

        if player_id == 0:
            return 220  # Não logado ou erro

        # 2. Endereço inicial da Battle List
        battle_list_addr = base_addr + BATTLELIST_BEGIN_ADDRESS

        # 3. Iterar pela lista com bounds checking
        for i in range(MAX_CREATURES):
            # Calcula endereço da criatura atual
            creature_addr = battle_list_addr + (i * STEP_SIZE)

            # Tenta ler o ID da criatura (com proteção contra endereço inválido)
            try:
                creature_id = pm.read_int(creature_addr)
            except Exception as e:
                # Se falhar ao ler creature_id, significa que chegamos ao fim da memória válida
                print(f"[PlayerCore] Battle list read failed at slot {i}: {e}")
                break

            # Otimização: ID 0 indica fim da lista válida
            if creature_id == 0:
                break

            # Se for o nosso player
            if creature_id == player_id:
                try:
                    speed = pm.read_int(creature_addr + OFFSET_SPEED)
                    return speed
                except Exception as e:
                    # Falha ao ler speed apesar de encontrar o player ID
                    print(f"[PlayerCore] Could not read speed at 0x{creature_addr + OFFSET_SPEED:X}: {e}")
                    return 220

    except Exception as e:
        print(f"[PlayerCore] Erro ao ler speed: {e}")

    # Valor de fallback seguro (velocidade normal de char lvl baixo)
    return 220

def get_player_id(pm, base_addr: int) -> int:
    """
    Retorna o ID único do personagem logado.
    
    Este valor é constante durante a sessão - o caller pode
    armazenar após primeira leitura bem-sucedida.
    
    Args:
        pm: Instância do Pymem conectada ao Tibia
        base_addr: Endereço base do módulo Tibia
    
    Returns:
        ID do jogador ou 0 se falhar
    """
    try:
        return pm.read_int(base_addr + OFFSET_PLAYER_ID)
    except Exception:
        return 0


def get_connected_char_name(pm, base_addr: int) -> str:
    """
    Lê o ID do jogador local e busca o nome correspondente na Battle List.
    
    O nome é constante durante a sessão. O caller pode armazenar
    o resultado após a primeira chamada bem-sucedida para evitar
    buscas repetidas na BattleList.
    
    Args:
        pm: Instância do Pymem conectada ao Tibia
        base_addr: Endereço base do módulo Tibia
    
    Returns:
        Nome do personagem ou string vazia se não encontrar
    """
    try:
        player_id = pm.read_int(base_addr + OFFSET_PLAYER_ID)
        if player_id == 0:
            return ""

        list_start = base_addr + TARGET_ID_PTR + REL_FIRST_ID

        for i in range(MAX_CREATURES):
            slot = list_start + (i * STEP_SIZE)
            creature_id = pm.read_int(slot)

            if creature_id == player_id:
                raw_name = pm.read_string(slot + OFFSET_NAME, 32)
                return raw_name.split('\x00')[0].strip()
    except Exception:
        pass

    return ""


def get_target_id(pm, base_addr: int) -> int:
    """
    Retorna o ID da criatura atualmente sendo atacada.
    
    TEMPO REAL - Este valor muda constantemente durante combate.
    Não armazenar entre ciclos.
    
    Args:
        pm: Instância do Pymem conectada ao Tibia
        base_addr: Endereço base do módulo Tibia
    
    Returns:
        ID do alvo atual ou 0 se não estiver atacando
    """
    try:
        return pm.read_int(base_addr + TARGET_ID_PTR)
    except Exception:
        return 0


def is_attacking(pm, base_addr: int) -> bool:
    """
    Verifica se o jogador está atacando alguma criatura.
    
    TEMPO REAL - Não armazenar entre ciclos.
    
    Args:
        pm: Instância do Pymem conectada ao Tibia
        base_addr: Endereço base do módulo Tibia
    
    Returns:
        True se estiver atacando, False caso contrário
    """
    return get_target_id(pm, base_addr) != 0


def find_player_in_battlelist(pm, base_addr: int, player_id: int = None) -> dict:
    """
    Encontra os dados do próprio jogador na BattleList.
    
    Útil quando você já tem o player_id e quer evitar releitura.
    
    Args:
        pm: Instância do Pymem conectada ao Tibia
        base_addr: Endereço base do módulo Tibia
        player_id: ID do jogador (se None, será lido da memória)
    
    Returns:
        Dict com dados do jogador ou None se não encontrar
        {
            'id': int,
            'name': str,
            'x': int,
            'y': int,
            'z': int,
            'hp_percent': int,
            'slot_index': int
        }
    """
    try:
        if player_id is None:
            player_id = pm.read_int(base_addr + OFFSET_PLAYER_ID)
        
        if player_id == 0:
            return None

        list_start = base_addr + TARGET_ID_PTR + REL_FIRST_ID

        for i in range(MAX_CREATURES):
            slot = list_start + (i * STEP_SIZE)
            creature_id = pm.read_int(slot)

            if creature_id == player_id:
                raw_name = pm.read_string(slot + OFFSET_NAME, 32)
                return {
                    'id': player_id,
                    'name': raw_name.split('\x00')[0].strip(),
                    'x': pm.read_int(slot + OFFSET_X),
                    'y': pm.read_int(slot + OFFSET_Y),
                    'z': pm.read_int(slot + OFFSET_Z),
                    'hp_percent': pm.read_int(slot + OFFSET_HP),
                    'slot_index': i
                }
    except Exception:
        pass

    return None
