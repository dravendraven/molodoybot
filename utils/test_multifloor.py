"""Testa get_path_multilevel entre dois pontos.

Uso:
    python utils/test_multifloor.py                          # modo interativo
    python utils/test_multifloor.py x1 y1 z1 x2 y2 z2       # modo CLI
    python utils/test_multifloor.py 33100 31900 7 33100 31900 9
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from core.global_map import GlobalMap
from config import WALKABLE_COLORS, MAPS_DIRECTORY


def parse_coords(raw):
    """Parseia coordenadas em varios formatos:
    - 6 inteiros: 33168 31810 8 33117 31776 7
    - Lua/dict:   {x = 33168, y = 31810, z = 8} {x = 33117, y = 31776, z = 7}
    """
    import re
    # Tenta formato {x = ..., y = ..., z = ...}
    matches = re.findall(r'\{\s*x\s*=\s*(\d+)\s*,\s*y\s*=\s*(\d+)\s*,\s*z\s*=\s*(\d+)\s*\}', raw)
    if len(matches) == 2:
        return [int(v) for m in matches for v in m]
    # Formato simples: 6 inteiros
    parts = raw.replace(',', ' ').split()
    if len(parts) != 6:
        raise ValueError("Esperado 6 valores ou 2 blocos {x=, y=, z=}")
    return [int(p) for p in parts]


def test_route(gm, x1, y1, z1, x2, y2, z2):
    start = (x1, y1, z1)
    end = (x2, y2, z2)

    print(f"\nBuscando rota: {start} -> {end}")
    t0 = time.time()
    path = gm.get_path_multilevel(start, end, debug=True)
    elapsed = time.time() - t0

    if path:
        floor_changes = 0
        for i in range(1, len(path)):
            if path[i][2] != path[i-1][2]:
                floor_changes += 1

        print(f"\nRota encontrada em {elapsed*1000:.0f}ms")
        print(f"  Tiles: {len(path)}")
        print(f"  Mudancas de andar: {floor_changes}")
        print(f"  Z inicial: {path[0][2]}, Z final: {path[-1][2]}")

        print(f"\n  Transicoes:")
        for i in range(1, len(path)):
            if path[i][2] != path[i-1][2]:
                print(f"    {path[i-1]} -> {path[i]}")

        print(f"\n  Primeiros 5: {path[:5]}")
        print(f"  Ultimos 5:   {path[-5:]}")
    else:
        print(f"\nNenhuma rota encontrada ({elapsed*1000:.0f}ms)")

        if z1 == z2:
            direct = gm.get_path(start, end)
            if direct:
                print(f"  (get_path direto funcionou: {len(direct)} tiles)")
            else:
                print(f"  (get_path direto tambem falhou)")

        print(f"  Start walkable: {gm.is_walkable(x1, y1, z1)} (cor: {gm.get_color_id(x1, y1, z1)})")
        print(f"  End walkable:   {gm.is_walkable(x2, y2, z2)} (cor: {gm.get_color_id(x2, y2, z2)})")


def load_map():
    transitions_file = os.path.join(MAPS_DIRECTORY, "floor_transitions.json")
    print(f"Carregando mapa de: {MAPS_DIRECTORY}")
    gm = GlobalMap(MAPS_DIRECTORY, WALKABLE_COLORS, transitions_file=transitions_file)
    print(f"Transicoes carregadas: {sum(len(v) for v in gm._transitions_by_floor.values())}")
    return gm


def main():
    gm = load_map()

    if len(sys.argv) == 7:
        coords = [int(a) for a in sys.argv[1:7]]
        test_route(gm, *coords)
        return

    print("\nModo interativo (digite 'q' para sair)")
    while True:
        try:
            raw = input("\nCoordenadas (x1 y1 z1 x2 y2 z2): ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not raw or raw.lower() == 'q':
            break
        try:
            coords = parse_coords(raw)
        except ValueError as e:
            print(f"  Erro: {e}")
            continue
        test_route(gm, *coords)


if __name__ == '__main__':
    main()
