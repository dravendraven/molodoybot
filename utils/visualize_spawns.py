"""Visualiza spawn points e grafo de conexões no mapa.

Uso:
    python utils/visualize_spawns.py <x> <y> <z> [radius]

Exemplo:
    python utils/visualize_spawns.py 33080 31730 9 80
"""
import os
import sys
import json
import re

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from config import MAPS_DIRECTORY
from utils.color_palette import get_color

SPAWN_RADIUS = 5
SCALE = 3  # pixels por tile para melhor legibilidade


def load_graph(maps_dir):
    path = os.path.join(maps_dir, "spawn_graph.json")
    if not os.path.isfile(path):
        # Tentar na raiz do projeto
        path = os.path.join(os.path.dirname(__file__), '..', 'spawn_graph.json')
    with open(path) as f:
        return json.load(f)


def filter_nodes(graph, cx, cy, cz, radius):
    """Retorna nodes dentro do raio Manhattan do ponto central."""
    filtered = {}
    for key, node in graph["nodes"].items():
        dist = abs(node["cx"] - cx) + abs(node["cy"] - cy)
        if dist <= radius:
            filtered[key] = node
    return filtered


def draw_floor(maps_dir, graph, filtered_keys, floor_z, center_x, center_y, radius, output_file):
    """Gera imagem de um andar com spawns e edges."""
    # Nodes neste andar
    floor_nodes = {k: graph["nodes"][k] for k in filtered_keys if graph["nodes"][k]["cz"] == floor_z}
    if not floor_nodes:
        return

    # Bounding box
    padding = 15
    min_x = center_x - radius - padding
    max_x = center_x + radius + padding
    min_y = center_y - radius - padding
    max_y = center_y + radius + padding

    tile_w = max_x - min_x + 1
    tile_h = max_y - min_y + 1
    img_w = tile_w * SCALE
    img_h = tile_h * SCALE

    img = Image.new('RGB', (img_w, img_h), (0, 0, 0))
    pixels = img.load()

    # Desenhar mapa de fundo
    start_cx, end_cx = min_x // 256, max_x // 256
    start_cy, end_cy = min_y // 256, max_y // 256

    for mcx in range(start_cx, end_cx + 1):
        for mcy in range(start_cy, end_cy + 1):
            filenames = [f"{mcx:03}{mcy:03}{floor_z:02}.map", f"{mcx}{mcy}{floor_z:02}.map"]
            map_data = None
            for fname in filenames:
                p = os.path.join(maps_dir, fname)
                if os.path.exists(p):
                    with open(p, "rb") as f:
                        map_data = f.read()
                    break

            if map_data:
                base_x, base_y = mcx * 256, mcy * 256
                for i, val in enumerate(map_data):
                    if val == 0:
                        continue
                    ax = base_x + (i // 256)
                    ay = base_y + (i % 256)
                    if min_x <= ax <= max_x and min_y <= ay <= max_y:
                        color = get_color(val)
                        # Escurecer para que overlays fiquem visíveis
                        color = tuple(c // 2 for c in color)
                        sx = (ax - min_x) * SCALE
                        sy = (ay - min_y) * SCALE
                        for dx in range(SCALE):
                            for dy in range(SCALE):
                                if sx + dx < img_w and sy + dy < img_h:
                                    pixels[sx + dx, sy + dy] = color

    draw = ImageDraw.Draw(img)

    # Tentar carregar fonte pequena
    try:
        font = ImageFont.truetype("arial.ttf", 10)
    except (OSError, IOError):
        font = ImageFont.load_default()

    # Desenhar spawn areas (quadrado semi-transparente)
    SPAWN_COLOR = (60, 180, 60, 128)
    for key, node in floor_nodes.items():
        ncx, ncy = node["cx"], node["cy"]
        x1 = (ncx - SPAWN_RADIUS - min_x) * SCALE
        y1 = (ncy - SPAWN_RADIUS - min_y) * SCALE
        x2 = (ncx + SPAWN_RADIUS - min_x + 1) * SCALE
        y2 = (ncy + SPAWN_RADIUS - min_y + 1) * SCALE
        draw.rectangle([x1, y1, x2, y2], outline=(0, 255, 0), width=1)

    # Desenhar as 2 edges de menor custo de cada spawn
    edges = graph.get("edges", {})
    best_edges = set()  # (from_key, to_key, cost) tuples to draw
    total_edges_per_node = {}  # key -> total de edges

    for key in filtered_keys:
        node = graph["nodes"][key]
        if node["cz"] != floor_z:
            continue
        node_edges = edges.get(key, [])
        total_edges_per_node[key] = len(node_edges)
        if not node_edges:
            continue
        # Filtrar edges para nodes no filtro
        valid = [e for e in node_edges if e["to"] in filtered_keys]
        if not valid:
            continue
        # 2 menores custos
        sorted_valid = sorted(valid, key=lambda e: e["cost"])
        for e in sorted_valid[:2]:
            best_edges.add((key, e["to"], e["cost"]))

    drawn_edges = set()
    for from_key, to_key, cost in best_edges:
        edge_id = tuple(sorted([from_key, to_key]))
        if edge_id in drawn_edges:
            continue
        drawn_edges.add(edge_id)

        from_node = graph["nodes"][from_key]
        to_node = graph["nodes"][to_key]
        x1 = (from_node["cx"] - min_x) * SCALE + SCALE // 2
        y1 = (from_node["cy"] - min_y) * SCALE + SCALE // 2
        x2 = (to_node["cx"] - min_x) * SCALE + SCALE // 2
        y2 = (to_node["cy"] - min_y) * SCALE + SCALE // 2

        cross_floor = to_node["cz"] != floor_z
        if cross_floor:
            line_color = (255, 100, 255)
            draw.line([x1, y1, x2, y2], fill=line_color, width=1)
            mid_x, mid_y = (x1 + x2) // 2, (y1 + y2) // 2
            draw.text((mid_x + 2, mid_y - 5), f"{cost} Z{to_node['cz']}", fill=(255, 150, 255), font=font)
        else:
            line_color = (100, 100, 255)
            draw.line([x1, y1, x2, y2], fill=line_color, width=1)
            mid_x, mid_y = (x1 + x2) // 2, (y1 + y2) // 2
            draw.text((mid_x + 2, mid_y - 5), str(cost), fill=(150, 150, 255), font=font)

    # Desenhar centros dos spawns e labels de monstros
    for key, node in floor_nodes.items():
        ncx, ncy = node["cx"], node["cy"]
        sx = (ncx - min_x) * SCALE + SCALE // 2
        sy = (ncy - min_y) * SCALE + SCALE // 2
        # Ponto central
        draw.ellipse([sx - 3, sy - 3, sx + 3, sy + 3], fill=(255, 255, 0))
        # Label de monstros + total de conexões
        monsters = ", ".join(node["monsters"][:2])
        if len(node["monsters"]) > 2:
            monsters += "..."
        n_edges = total_edges_per_node.get(key, 0)
        label = f"{monsters} ({n_edges})"
        draw.text((sx + 5, sy - 5), label, fill=(255, 255, 200), font=font)

    # Marcar centro de referência
    ref_sx = (center_x - min_x) * SCALE + SCALE // 2
    ref_sy = (center_y - min_y) * SCALE + SCALE // 2
    draw.ellipse([ref_sx - 5, ref_sy - 5, ref_sx + 5, ref_sy + 5], fill=(255, 0, 0))

    img.save(output_file)
    print(f"Salvo: {os.path.abspath(output_file)} ({img_w}x{img_h}, {len(floor_nodes)} spawns, {len(drawn_edges)} edges)")
    return output_file


def parse_position(args_str):
    """Extrai x, y, z de vários formatos:
    - {x = 32633, y = 31933, z = 10}
    - {x=32633, y=31933, z=10}
    - 32633 31933 10
    """
    # Tentar formato {x = valor, y = valor, z = valor}
    x_match = re.search(r'x\s*=\s*(\d+)', args_str)
    y_match = re.search(r'y\s*=\s*(\d+)', args_str)
    z_match = re.search(r'z\s*=\s*(\d+)', args_str)

    if x_match and y_match and z_match:
        return int(x_match.group(1)), int(y_match.group(1)), int(z_match.group(1))

    # Fallback: extrair apenas números na ordem
    nums = [int(x) for x in re.findall(r'\d+', args_str) if len(x) >= 1]
    if len(nums) >= 3:
        return nums[0], nums[1], nums[2]

    return None


def main():
    if len(sys.argv) < 2:
        print("Uso: python utils/visualize_spawns.py \"{x = 32633, y = 31933, z = 10}\" [radius]")
        print("  ou: python utils/visualize_spawns.py <x> <y> <z> [radius]")
        sys.exit(1)

    args_str = " ".join(sys.argv[1:])
    position = parse_position(args_str)

    if not position:
        print("Uso: python utils/visualize_spawns.py \"{x = 32633, y = 31933, z = 10}\" [radius]")
        print("  ou: python utils/visualize_spawns.py 32633 31933 10 [radius]")
        sys.exit(1)

    cx, cy, cz = position

    # Extrair radius (último número que não seja x, y ou z)
    all_nums = [int(x) for x in re.findall(r'\d+', args_str)]
    radius = 100
    if len(all_nums) > 3:
        # Pegar o último número se houver mais de 3
        radius = all_nums[-1]
        # Verificar se não é o z (caso seja igual)
        if radius == cz and len(all_nums) == 4:
            radius = all_nums[3]

    print(f"Centro: ({cx}, {cy}, {cz}), Raio: {radius}")
    print(f"Carregando grafo...")

    graph = load_graph(MAPS_DIRECTORY)
    print(f"Nodes: {len(graph['nodes'])}, Edge keys: {len(graph.get('edges', {}))}")

    filtered_keys = set(filter_nodes(graph, cx, cy, cz, radius).keys())
    print(f"Nodes no raio: {len(filtered_keys)}")

    # Agrupar por andar
    floors = set()
    for k in filtered_keys:
        floors.add(graph["nodes"][k]["cz"])

    generated = []
    for z in sorted(floors):
        output = f"spawns_z{z}.png"
        result = draw_floor(MAPS_DIRECTORY, graph, filtered_keys, z, cx, cy, radius, output)
        if result:
            generated.append(result)

    if generated:
        try:
            os.startfile(generated[0])
        except (AttributeError, OSError):
            pass


if __name__ == '__main__':
    main()
