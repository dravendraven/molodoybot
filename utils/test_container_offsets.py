"""
Test Script: Validacao de Offsets de Container + Simulacao de Tracking
Objetivo: Confirmar valores dos offsets e testar classificacao automatica

INSTRUCOES DE USO:
1. Abra o Tibia e faca login
2. Execute: python utils/test_container_offsets.py
3. Teste os cenarios abaixo e observe os valores:

CENARIOS PARA TESTAR:
- Abrir backpack do slot backpack -> hasparent=0, PLAYER
- Abrir bag DENTRO da backpack -> hasparent=1, PLAYER (herdado)
- Abrir corpo "Dead Rat" -> hasparent=0, LOOT
- Abrir bag dentro do corpo -> hasparent=1, LOOT (herdado)
"""

import pymem
import time

# ========== CONFIG (copiado do bot) ==========
PROCESS_NAME = "Tibia.exe"
OFFSET_CONTAINER_START = 0x1CEDD8
STEP_CONTAINER = 492
MAX_CONTAINERS = 16

# Offsets conhecidos
OFFSET_CNT_IS_OPEN = 0
OFFSET_CNT_NAME = 16
OFFSET_CNT_VOLUME = 48
OFFSET_CNT_AMOUNT = 56

# Offsets validados
OFFSET_CNT_ITEM_ID = 4
OFFSET_CNT_HAS_PARENT = 52  # 0 = raiz, 1 = filho
# =============================================

# Estado de tracking (simula o bot)
_loot_indices = set()

def read_string(pm, addr, max_len=32):
    """Le string da memoria"""
    try:
        raw = pm.read_bytes(addr, max_len)
        return raw.split(b'\x00')[0].decode('latin-1', errors='ignore')
    except:
        return ""

def scan_containers(pm, base_addr):
    """Escaneia todos os containers abertos com offsets extras"""
    containers = []

    for i in range(MAX_CONTAINERS):
        cnt_addr = base_addr + OFFSET_CONTAINER_START + (i * STEP_CONTAINER)
        try:
            is_open = pm.read_int(cnt_addr + OFFSET_CNT_IS_OPEN)
            if is_open != 1:
                continue

            name = read_string(pm, cnt_addr + OFFSET_CNT_NAME)
            volume = pm.read_int(cnt_addr + OFFSET_CNT_VOLUME)
            amount = pm.read_int(cnt_addr + OFFSET_CNT_AMOUNT)
            item_id = pm.read_int(cnt_addr + OFFSET_CNT_ITEM_ID)
            has_parent = pm.read_int(cnt_addr + OFFSET_CNT_HAS_PARENT)

            containers.append({
                'index': i,
                'name': name,
                'volume': volume,
                'amount': amount,
                'item_id': item_id,
                'has_parent': has_parent,
                'addr': hex(cnt_addr)
            })
        except Exception as e:
            print(f"[!] Erro no container {i}: {e}")

    return containers

def track_and_classify(containers):
    """
    Simula o tracking temporal do bot.
    Retorna dict com classificacao de cada container.
    """
    global _loot_indices

    current_open = {c['index'] for c in containers}

    # Limpa indices de containers fechados
    _loot_indices = _loot_indices & current_open

    classifications = {}

    for c in containers:
        idx = c['index']
        name = c['name']
        has_parent = c['has_parent']

        if name.startswith("Dead "):
            # Corpo de criatura = sempre loot
            _loot_indices.add(idx)
            classifications[idx] = ("LOOT", "corpo de criatura")
        elif has_parent == 1 and idx in _loot_indices:
            # Bag que substituiu corpo = mantem como loot
            classifications[idx] = ("LOOT", "bag herdou do corpo")
        elif has_parent == 0 and not name.startswith("Dead "):
            # Container raiz do player = remove do tracking
            _loot_indices.discard(idx)
            classifications[idx] = ("PLAYER", "container raiz")
        elif has_parent == 1 and idx not in _loot_indices:
            # Bag dentro de container do player
            classifications[idx] = ("PLAYER", "bag dentro de player container")
        else:
            classifications[idx] = ("???", "nao classificado")

    return classifications

def main():
    print("=" * 70)
    print("  TESTE DE CONTAINERS - Tibia 7.72 (com Tracking Temporal)")
    print("=" * 70)
    print()

    try:
        pm = pymem.Pymem(PROCESS_NAME)
        base_addr = pm.base_address
        print(f"[OK] Conectado ao {PROCESS_NAME}")
        print(f"[OK] Base Address: {hex(base_addr)}")
    except Exception as e:
        print(f"[ERRO] Nao foi possivel conectar: {e}")
        return

    print()
    print("Pressione ENTER para escanear containers (CTRL+C para sair)")
    print("-" * 70)

    while True:
        input()

        containers = scan_containers(pm, base_addr)

        if not containers:
            print("[!] Nenhum container aberto")
            print(f"    Tracking: loot_indices = {_loot_indices}")
            continue

        classifications = track_and_classify(containers)

        print()
        print(f"{'IDX':<4} {'NOME':<18} {'PARENT':<7} {'CLASS':<8} {'MOTIVO'}")
        print("-" * 70)
        

        for c in containers:
            idx = c['index']
            cls, reason = classifications.get(idx, ("???", ""))
            parent_str = "filho" if c['has_parent'] else "raiz"
            cls_color = cls

            print(f"{idx:<4} {c['name']:<18} {parent_str:<7} {cls_color:<8} {reason}")

        print("-" * 70)
        print(f"Tracking: loot_indices = {_loot_indices}")
        print()

        # Resumo
        loot_count = sum(1 for c in classifications.values() if c[0] == "LOOT")
        player_count = sum(1 for c in classifications.values() if c[0] == "PLAYER")
        print(f"Resumo: {player_count} PLAYER, {loot_count} LOOT")
        print()
        print("Pressione ENTER para escanear novamente...")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[!] Encerrado pelo usuario")
