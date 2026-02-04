"""Gera transicoes dos mapas e merge com arquivo existente (sem remover custom).

Uso:
    python utils/merge_transitions.py [maps_directory]

Compara transicoes geradas dos .map files com floor_transitions.json existente.
Adiciona apenas novas transicoes, preservando as custom adicionadas manualmente.
"""
import os
import sys
import json
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

TRANSITION_COLOR = 210


def parse_map_filename(filename):
    name = os.path.splitext(filename)[0]
    if not name.isdigit():
        return None
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


def scan_maps_for_transitions(maps_dir):
    """Gera transicoes a partir dos arquivos .map."""
    transition_tiles = set()
    map_files = [f for f in os.listdir(maps_dir) if f.endswith('.map')]
    print(f"Escaneando {len(map_files)} arquivos .map...")

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

        if (i + 1) % 200 == 0:
            print(f"  {i + 1}/{len(map_files)} arquivos...")

    # Gerar transicoes onde (x,y) tem cor 210 em andares adjacentes
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


def transition_key(t):
    """Chave unica para uma transicao."""
    return (t["x"], t["y"], t["z_from"], t["z_to"])


def main():
    if len(sys.argv) > 1:
        maps_dir = sys.argv[1]
    else:
        from config import MAPS_DIRECTORY
        maps_dir = MAPS_DIRECTORY

    if not os.path.isdir(maps_dir):
        print(f"Diretorio nao encontrado: {maps_dir}")
        sys.exit(1)

    existing_file = os.path.join(maps_dir, "floor_transitions.json")

    # Carregar existente
    existing_transitions = []
    if os.path.isfile(existing_file):
        with open(existing_file) as f:
            data = json.load(f)
            existing_transitions = data.get("transitions", [])
        print(f"Transicoes existentes: {len(existing_transitions)}")
    else:
        print("Nenhum arquivo existente encontrado, criando novo.")

    # Gerar do mapa
    generated = scan_maps_for_transitions(maps_dir)
    print(f"Transicoes geradas dos mapas: {len(generated)}")

    # Criar sets para comparacao
    existing_keys = set(transition_key(t) for t in existing_transitions)
    generated_keys = set(transition_key(t) for t in generated)

    # Encontrar diferencas
    new_from_maps = generated_keys - existing_keys
    custom_kept = existing_keys - generated_keys
    common = existing_keys & generated_keys

    print(f"\n--- Comparacao ---")
    print(f"Em comum (mapa + existente): {len(common)}")
    print(f"Novas do mapa (serao adicionadas): {len(new_from_maps)}")
    print(f"Custom/manual (serao preservadas): {len(custom_kept)}")

    # Mostrar algumas novas
    if new_from_maps:
        print(f"\nExemplos de novas transicoes:")
        for key in list(new_from_maps)[:10]:
            x, y, zf, zt = key
            direction = "UP" if zt < zf else "DOWN"
            print(f"  ({x}, {y}) z{zf} -> z{zt} ({direction})")
        if len(new_from_maps) > 10:
            print(f"  ... e mais {len(new_from_maps) - 10}")

    # Mostrar custom preservadas
    if custom_kept:
        print(f"\nTransicoes custom preservadas:")
        for key in list(custom_kept)[:10]:
            x, y, zf, zt = key
            direction = "UP" if zt < zf else "DOWN"
            print(f"  ({x}, {y}) z{zf} -> z{zt} ({direction})")
        if len(custom_kept) > 10:
            print(f"  ... e mais {len(custom_kept) - 10}")

    # Merge: existentes + novas do mapa
    merged = list(existing_transitions)
    for t in generated:
        if transition_key(t) in new_from_maps:
            merged.append(t)

    print(f"\nTotal apos merge: {len(merged)}")

    # Confirmar
    if new_from_maps:
        response = input("\nSalvar arquivo merged? [y/N]: ").strip().lower()
        if response == 'y':
            with open(existing_file, 'w') as f:
                json.dump({"transitions": merged}, f)
            print(f"Salvo em: {existing_file}")
        else:
            print("Cancelado.")
    else:
        print("\nNenhuma nova transicao para adicionar.")


if __name__ == '__main__':
    main()
