import pymem
import pymem.process
import struct
import time
import sys
import os

# Tenta importar config
try:
    from config import PROCESS_NAME, OFFSET_MAP_POINTER
    print(f"✅ Config carregada. Offset Map: {hex(OFFSET_MAP_POINTER)}")
except ImportError:
    print("❌ config.py não encontrado. Usando padrões.")
    PROCESS_NAME = "Tibia.exe"
    OFFSET_MAP_POINTER = 0x1D4C20 

# CONSTANTES ESTRUTURAIS
TILE_SIZE = 172 # (4 bytes count + 14 * 12 bytes obj)
MAX_X = 18
MAX_Y = 14
MAX_Z = 8

# Centro da tela (Onde seu char está na memória)
CENTER_X = 8
CENTER_Y = 6

def get_map_address(pm, base_addr):
    try:
        # Lê o ponteiro
        ptr = pm.read_int(base_addr + OFFSET_MAP_POINTER)
        return ptr
    except:
        return 0

def debug_tile(pm, map_start, offset, desc):
    """Lê um tile em um offset específico e formata a saída."""
    addr = map_start + offset
    try:
        data = pm.read_bytes(addr, TILE_SIZE)
        # Primeiro valor é o Count
        count = struct.unpack_from("<I", data, 0)[0]
        
        # Lê o primeiro item da stack (Item no chão ou logo acima)
        # Offset 4 = Primeiro Objeto. Estrutura: [ID (4b)] [Data (4b)] [DataEx (4b)]
        id1, d1, _ = struct.unpack_from("<III", data, 4)
        
        # Lê o segundo item (se tiver)
        id2, d2, _ = struct.unpack_from("<III", data, 16)
        
        valid_mark = "✅" if (0 < count < 20 and id1 > 100) else "❌"
        
        print(f"   [{desc}] Offset {offset}: {valid_mark} Count: {count} | Top ID: {id1} | 2nd ID: {id2}")
        return True
    except:
        print(f"   [{desc}] Erro de leitura.")
        return False

def main():
    print("\n🕵️ DIAGNÓSTICO DE MAPA DO TIBIA")
    print("-----------------------------------")
    
    try:
        pm = pymem.Pymem(PROCESS_NAME)
        base_addr = pymem.process.module_from_name(pm.process_handle, PROCESS_NAME).lpBaseOfDll
        print(f"Processo: {hex(base_addr)}")
    except:
        print("Tibia não encontrado.")
        return

    map_addr = get_map_address(pm, base_addr)
    print(f"Map Address: {hex(map_addr)}")
    print("-" * 50)
    print(f"Lendo Tile Central (X={CENTER_X}, Y={CENTER_Y}) em diferentes camadas Z...")
    print("Procure por 'Count' entre 1 e 5 e IDs que pareçam itens (1000+).\n")

    # TESTE 1: LÓGICA PADRÃO (Z-MAJOR / PLANO A PLANO)
    # offset = (z * 18 * 14 + y * 18 + x) * 172
    print("--- HIPÓTESE A: PLANOS (Z * 18 * 14) ---")
    for z in range(8):
        # Calcula índice linear assumindo que cada Z é um bloco completo de 18x14
        idx = (z * MAX_X * MAX_Y) + (CENTER_Y * MAX_X) + CENTER_X
        offset = idx * TILE_SIZE
        debug_tile(pm, map_addr, offset, f"Layer Z={z}")

    print("\n--- HIPÓTESE B: ESTRUTURA C++ (X * 14 * 8) ---")
    # offset = (x * 14 * 8 + y * 8 + z) * 172
    for z in range(8):
        idx = (CENTER_X * MAX_Y * MAX_Z) + (CENTER_Y * MAX_Z) + z
        offset = idx * TILE_SIZE
        debug_tile(pm, map_addr, offset, f"Layer Z={z}")

    print("-" * 50)
    print("CONCLUSÃO:")
    print("1. Veja qual 'Layer Z' mostrou um 'Count' correto (qtd de itens no seu pé).")
    print("2. Me diga qual Hipótese (A ou B) e qual Z funcionou.")

if __name__ == "__main__":
    main()