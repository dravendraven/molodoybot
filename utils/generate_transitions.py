"""Gera floor_transitions.json a partir dos arquivos .map.

Uso:
    python utils/generate_transitions.py [maps_directory]

Se maps_directory não for passado, usa MAPS_DIRECTORY do config.py.
Salva floor_transitions.json no mesmo diretório dos mapas.
"""
import os
import sys
import json
import re
from collections import defaultdict

TRANSITION_COLOR = 210


def parse_map_filename(filename):
    """Extrai (chunk_x, chunk_y, z) do nome do arquivo .map.

    Formatos suportados:
        12912407.map  -> cx=129, cy=124, z=7
        129124 07.map -> (sem espaço, mas 3+3+2 dígitos)
    """
    name = os.path.splitext(filename)[0]
    if not name.isdigit():
        return None

    # Formato: últimos 2 dígitos = z, restante dividido ao meio = cx, cy
    if len(name) < 4:
        return None

    z_str = name[-2:]
    rest = name[:-2]

    if len(rest) % 2 != 0:
        return None

    half = len(rest) // 2
    cx_str = rest[:half]
    cy_str = rest[half:]

    try:
        return int(cx_str), int(cy_str), int(z_str)
    except ValueError:
        return None


def scan_all_maps(maps_dir):
    """Varre todos os .map files e retorna dict de tiles cor 210 por (x, y, z)."""
    # Primeiro passo: encontrar todos os tiles com cor 210
    transition_tiles = set()  # (abs_x, abs_y, z)

    map_files = [f for f in os.listdir(maps_dir) if f.endswith('.map')]
    print(f"Encontrados {len(map_files)} arquivos .map")

    for i, filename in enumerate(map_files):
        parsed = parse_map_filename(filename)
        if not parsed:
            continue

        chunk_x, chunk_y, z = parsed
        filepath = os.path.join(maps_dir, filename)

        try:
            with open(filepath, 'rb') as f:
                data = f.read()
        except IOError:
            continue

        if len(data) < 256 * 256:
            continue

        for rel_x in range(256):
            for rel_y in range(256):
                idx = rel_x * 256 + rel_y
                if data[idx] == TRANSITION_COLOR:
                    abs_x = chunk_x * 256 + rel_x
                    abs_y = chunk_y * 256 + rel_y
                    transition_tiles.add((abs_x, abs_y, z))

        if (i + 1) % 100 == 0:
            print(f"  Processados {i + 1}/{len(map_files)} arquivos... ({len(transition_tiles)} tiles 210 encontrados)")

    print(f"Total de tiles cor 210: {len(transition_tiles)}")

    # Segundo passo: para cada tile 210, verificar se z-1 ou z+1 também tem 210
    transitions = []
    tiles_by_xy = defaultdict(set)
    for x, y, z in transition_tiles:
        tiles_by_xy[(x, y)].add(z)

    for (x, y), z_levels in tiles_by_xy.items():
        for z in z_levels:
            if z - 1 in z_levels:
                transitions.append({"x": x, "y": y, "z_from": z, "z_to": z - 1})
            if z + 1 in z_levels:
                transitions.append({"x": x, "y": y, "z_from": z, "z_to": z + 1})

    return transitions


def main():
    if len(sys.argv) > 1:
        maps_dir = sys.argv[1]
    else:
        # Importar do config
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
        from config import MAPS_DIRECTORY
        maps_dir = MAPS_DIRECTORY

    if not os.path.isdir(maps_dir):
        print(f"Diretorio nao encontrado: {maps_dir}")
        sys.exit(1)

    print(f"Escaneando mapas em: {maps_dir}")
    transitions = scan_all_maps(maps_dir)

    # Agrupar por (z_from, z_to) para stats
    by_pair = defaultdict(int)
    for t in transitions:
        by_pair[(t["z_from"], t["z_to"])] += 1

    print(f"\nTotal de transicoes: {len(transitions)}")
    for (zf, zt), count in sorted(by_pair.items()):
        direction = "UP" if zt < zf else "DOWN"
        print(f"  Z{zf} -> Z{zt} ({direction}): {count} transicoes")

    project_root = os.path.join(os.path.dirname(__file__), '..')
    output_path = os.path.join(project_root, "floor_transitions.json")
    with open(output_path, 'w') as f:
        json.dump({"transitions": transitions}, f)

    print(f"\nSalvo em: {output_path}")


if __name__ == '__main__':
    main()
