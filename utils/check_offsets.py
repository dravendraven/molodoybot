"""
Script para verificar quais offsets estão funcionando no cliente.
Execute com o jogo aberto e logado em um personagem.
"""
import pymem
import pymem.process
import sys
import os

# Adiciona o diretório raiz ao path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import (
    PROCESS_NAME, CLIENT_TYPE,
    PLAYER_X_ADDRESS, PLAYER_Y_ADDRESS, PLAYER_Z_ADDRESS,
    BATTLELIST_BEGIN_ADDRESS, TARGET_ID_PTR,
    OFFSET_PLAYER_HP, OFFSET_PLAYER_HP_MAX,
    OFFSET_PLAYER_MANA, OFFSET_PLAYER_MANA_MAX,
    OFFSET_PLAYER_CAP,
    OFFSET_LEVEL, OFFSET_EXP, OFFSET_MAGIC_LEVEL,
    OFFSET_CONNECTION,
    STEP_SIZE, MAX_CREATURES,
)

def check_offsets():
    print("=" * 60)
    print(f"VERIFICADOR DE OFFSETS - {CLIENT_TYPE}")
    print(f"Processo: {PROCESS_NAME}")
    print("=" * 60)

    try:
        pm = pymem.Pymem(PROCESS_NAME)
        base = pymem.process.module_from_name(pm.process_handle, PROCESS_NAME).lpBaseOfDll
        print(f"\n[OK] Conectado ao processo!")
        print(f"[OK] Base Address: 0x{base:X}\n")
    except Exception as e:
        print(f"\n[ERRO] Nao foi possivel conectar ao {PROCESS_NAME}")
        print(f"       Certifique-se que o jogo esta aberto.")
        print(f"       Erro: {e}")
        return

    print("-" * 60)
    print("POSICAO DO PLAYER")
    print("-" * 60)

    # Posicao X, Y, Z
    tests = [
        ("Player X", PLAYER_X_ADDRESS, "int", "Sua coordenada X no mapa"),
        ("Player Y", PLAYER_Y_ADDRESS, "int", "Sua coordenada Y no mapa"),
        ("Player Z", PLAYER_Z_ADDRESS, "int", "Andar (7=terreo, <7=acima, >7=subsolo)"),
    ]

    for name, offset, tipo, desc in tests:
        try:
            if tipo == "int":
                value = pm.read_int(base + offset)
            elif tipo == "float":
                value = pm.read_float(base + offset)

            # Verificar se o valor faz sentido
            status = "?"
            if name == "Player X" and 30000 < value < 40000:
                status = "OK"
            elif name == "Player Y" and 30000 < value < 40000:
                status = "OK"
            elif name == "Player Z" and 0 <= value <= 15:
                status = "OK"
            elif value == 0:
                status = "ERRADO (valor 0)"

            print(f"  [{status}] {name}: {value}")
            print(f"       Offset: 0x{offset:X} | {desc}")
        except Exception as e:
            print(f"  [ERRO] {name}: {e}")

    print("\n" + "-" * 60)
    print("STATUS DO PLAYER")
    print("-" * 60)

    tests = [
        ("HP", OFFSET_PLAYER_HP, "int", "Vida atual"),
        ("HP Max", OFFSET_PLAYER_HP_MAX, "int", "Vida maxima"),
        ("Mana", OFFSET_PLAYER_MANA, "int", "Mana atual"),
        ("Mana Max", OFFSET_PLAYER_MANA_MAX, "int", "Mana maxima"),
        ("Cap", OFFSET_PLAYER_CAP, "float", "Capacidade (peso)"),
        ("Level", OFFSET_LEVEL, "int", "Nivel do personagem"),
        ("Exp", OFFSET_EXP, "int", "Experiencia total"),
        ("Magic Level", OFFSET_MAGIC_LEVEL, "int", "Nivel de magia"),
    ]

    for name, offset, tipo, desc in tests:
        try:
            if tipo == "int":
                value = pm.read_int(base + offset)
            elif tipo == "float":
                value = pm.read_float(base + offset)

            # Verificar se o valor faz sentido
            status = "?"
            if "HP" in name and 0 < value < 50000:
                status = "OK"
            elif "Mana" in name and 0 <= value < 50000:
                status = "OK"
            elif name == "Cap" and 0 < value < 50000:
                status = "OK"
            elif name == "Level" and 1 <= value <= 1000:
                status = "OK"
            elif name == "Exp" and value >= 0:
                status = "OK" if value > 0 else "?"
            elif name == "Magic Level" and 0 <= value <= 150:
                status = "OK"
            elif value == 0:
                status = "ERRADO?"

            print(f"  [{status}] {name}: {value}")
            print(f"       Offset: 0x{offset:X} | {desc}")
        except Exception as e:
            print(f"  [ERRO] {name}: {e}")

    print("\n" + "-" * 60)
    print("BUSCA DO PLAYER NA BATTLELIST (por nome)")
    print("-" * 60)

    # Nome do personagem a buscar
    SEARCH_NAME = "Babau"
    print(f"  Buscando por: '{SEARCH_NAME}'")

    try:
        # Buscar player na battlelist pelo nome
        player_found = False
        for i in range(MAX_CREATURES):
            slot_addr = base + BATTLELIST_BEGIN_ADDRESS + (i * STEP_SIZE)

            # Ler nome do slot
            name_bytes = pm.read_bytes(slot_addr + 4, 32)
            name = name_bytes.split(b'\x00')[0].decode('latin-1', errors='ignore')

            if name.lower() == SEARCH_NAME.lower():
                player_found = True
                creature_id = pm.read_int(slot_addr)
                pos_x = pm.read_int(slot_addr + 0x24)
                pos_y = pm.read_int(slot_addr + 0x28)
                pos_z = pm.read_int(slot_addr + 0x2C)
                hp_percent = pm.read_int(slot_addr + 0x84)
                speed = pm.read_int(slot_addr + 0x88)

                print(f"\n  [OK] PLAYER '{SEARCH_NAME}' ENCONTRADO NO SLOT {i}!")
                print(f"  ========================================")
                print(f"    Nome: {name}")
                print(f"    ID: {creature_id}")
                print(f"    Posicao: X={pos_x}, Y={pos_y}, Z={pos_z}")
                print(f"    HP%: {hp_percent}")
                print(f"    Speed: {speed}")
                print(f"    Slot Offset: 0x{BATTLELIST_BEGIN_ADDRESS + (i * STEP_SIZE):X}")
                print(f"    Slot Address: 0x{slot_addr:X}")
                print(f"  ========================================")

                # Mostrar offsets calculados
                print(f"\n  Offsets encontrados para este player:")
                print(f"    ID offset:    slot + 0x00")
                print(f"    Nome offset:  slot + 0x04")
                print(f"    X offset:     slot + 0x24")
                print(f"    Y offset:     slot + 0x28")
                print(f"    Z offset:     slot + 0x2C")
                print(f"    HP% offset:   slot + 0x84")
                print(f"    Speed offset: slot + 0x88")
                break

        if not player_found:
            print(f"\n  [ERRO] '{SEARCH_NAME}' nao encontrado na battlelist!")
            print(f"         Verifique se o nome esta correto e se voce esta logado.")
            print(f"         Pode ser que BATTLELIST_BEGIN_ADDRESS ou STEP_SIZE esteja errado.")

    except Exception as e:
        print(f"  [ERRO] {e}")

    print("\n" + "-" * 60)
    print("BATTLELIST COMPLETA (Criaturas/Players na tela)")
    print("-" * 60)
    print(f"  Offset Base: 0x{BATTLELIST_BEGIN_ADDRESS:X}")
    print(f"  Step Size: {STEP_SIZE} bytes")
    print(f"  Max Slots: {MAX_CREATURES}")
    print()

    try:
        found_count = 0
        for i in range(MAX_CREATURES):
            slot_addr = base + BATTLELIST_BEGIN_ADDRESS + (i * STEP_SIZE)

            creature_id = pm.read_int(slot_addr)

            # Slot vazio
            if creature_id == 0:
                continue

            # Ler dados da criatura
            name_bytes = pm.read_bytes(slot_addr + 4, 32)
            name = name_bytes.split(b'\x00')[0].decode('latin-1', errors='ignore')

            pos_x = pm.read_int(slot_addr + 0x24)
            pos_y = pm.read_int(slot_addr + 0x28)
            pos_z = pm.read_int(slot_addr + 0x2C)
            hp_percent = pm.read_int(slot_addr + 0x84)
            speed = pm.read_int(slot_addr + 0x88)

            # Outfit para identificar se é player ou criatura
            outfit_head = pm.read_int(slot_addr + 0x64)
            outfit_body = pm.read_int(slot_addr + 0x68)
            is_player = outfit_head > 0 or outfit_body > 0

            tipo = "PLAYER" if is_player else "CRIATURA"

            found_count += 1
            print(f"  [{i:3}] {tipo}: {name}")
            print(f"        ID: {creature_id} | Pos: ({pos_x}, {pos_y}, {pos_z})")
            print(f"        HP: {hp_percent}% | Speed: {speed}")
            print()

        if found_count > 0:
            print(f"  [OK] Encontradas {found_count} entidades na battlelist!")
        else:
            print(f"  [?] Nenhuma entidade encontrada.")
            print(f"      Pode ser offset errado ou ninguem na tela.")

    except Exception as e:
        print(f"  [ERRO] Nao foi possivel ler battlelist: {e}")

    print("\n" + "-" * 60)
    print("TARGET (Criatura atacada)")
    print("-" * 60)

    try:
        target_id = pm.read_int(base + TARGET_ID_PTR)
        print(f"  Target ID: {target_id}")
        print(f"  (0 = nenhum alvo, >0 = atacando algo)")
        print(f"  Offset: 0x{TARGET_ID_PTR:X}")

        if target_id == 0:
            print(f"\n  [DICA] Ataque uma criatura e rode o script novamente")
    except Exception as e:
        print(f"  [ERRO] {e}")

    print("\n" + "-" * 60)
    print("NOME DO PERSONAGEM")
    print("-" * 60)

    try:
        # O nome geralmente fica na battlelist no slot do proprio player
        # Vamos procurar pelo ID do player
        player_id = pm.read_int(base + BATTLELIST_BEGIN_ADDRESS + 0x94)  # REL_FIRST_ID
        print(f"  Player ID (estimado): {player_id}")

        # Tentar ler nome de varios lugares comuns
        name_offsets = [
            (0x1C68B0 + 4, "Battlelist slot 0 + 4"),
            (0x31C588 + 0x10, "Connection + 0x10"),
        ]

        for offset, desc in name_offsets:
            try:
                name_bytes = pm.read_bytes(base + offset, 32)
                name = name_bytes.split(b'\x00')[0].decode('latin-1', errors='ignore')
                if len(name) > 2 and name.isprintable():
                    print(f"  Nome encontrado em 0x{offset:X}: '{name}' ({desc})")
            except:
                pass

    except Exception as e:
        print(f"  [ERRO] {e}")

    print("\n" + "=" * 60)
    print("RESUMO")
    print("=" * 60)
    print("""
Para offsets marcados como ERRADO ou ?, use o Cheat Engine:
1. Abra o Cheat Engine e anexe ao processo do jogo
2. Busque o valor atual (ex: seu HP, posicao X, etc)
3. Mude o valor no jogo e busque novamente
4. O endereco encontrado sera: Base + Offset
5. Calcule: Offset = Endereco - Base (0x{:X})

Atualize os valores em config.py na secao do MAS_VIS.
""".format(base))

    pm.close_process()

if __name__ == "__main__":
    check_offsets()
    input("\nPressione ENTER para sair...")
