"""Gera spawn_graph.json com custos A* pré-computados entre spawn points adjacentes.

Uso:
    python utils/generate_spawn_graph.py [maps_directory]

Se maps_directory não for passado, usa MAPS_DIRECTORY do config.py.
Salva spawn_graph.json no mesmo diretório dos mapas.
"""
import os
import sys
import json
import time

# Adiciona root do projeto ao path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from core.spawn_parser import parse_spawns
from core.global_map import GlobalMap
from config import WALKABLE_COLORS

NEIGHBOR_RADIUS = 60   # Manhattan distance máxima entre spawns adjacentes
MAX_FLOOR_DIFF = 1     # Diferença máxima de andares para considerar adjacência


def make_key(spawn):        
    return f"{spawn.cx}_{spawn.cy}_{spawn.cz}"


def build_spawn_graph(spawns, global_map):
    """Calcula custo A* entre todos os pares de spawns adjacentes."""
    total = len(spawns)
    print(f"Total de spawns: {total}")

    # Index por key para lookup
    spawn_by_key = {make_key(s): s for s in spawns}

    # Pré-computar pares candidatos (filtro Manhattan)
    pairs = []
    for i, a in enumerate(spawns):
        for j, b in enumerate(spawns):
            if j <= i:
                continue
            dz = abs(a.cz - b.cz)
            if dz > MAX_FLOOR_DIFF:
                continue
            manhattan = abs(a.cx - b.cx) + abs(a.cy - b.cy)
            if manhattan > NEIGHBOR_RADIUS:
                continue
            pairs.append((i, j))

    print(f"Pares candidatos (Manhattan <= {NEIGHBOR_RADIUS}, dZ <= {MAX_FLOOR_DIFF}): {len(pairs)}", flush=True)

    # Calcular custos
    edges = {}  # key -> [(to_key, cost), ...]
    computed = 0
    failed = 0
    start_time = time.time()
    print(f"Iniciando calculo de {len(pairs)} pares A*...", flush=True)

    for idx, (i, j) in enumerate(pairs):
        a, b = spawns[i], spawns[j]
        key_a = make_key(a)
        key_b = make_key(b)

        # Usar centros dos spawns diretamente — A* ajusta para tile walkable
        pos_a = (a.cx, a.cy, a.cz)
        pos_b = (b.cx, b.cy, b.cz)

        cost = None

        if a.cz == b.cz:
            # Mesmo andar: A* 2D
            path = global_map.get_path(pos_a, pos_b, max_dist=200, max_iter=3000)
            if path:
                cost = len(path)
        else:
            # Cross-floor: A* 3D multilevel (max_iter reduzido)
            path = global_map.get_path_multilevel(pos_a, pos_b, max_iter=5000)
            if path:
                cost = len(path)

        if cost is not None:
            edges.setdefault(key_a, []).append({"to": key_b, "cost": cost})
            edges.setdefault(key_b, []).append({"to": key_a, "cost": cost})
            computed += 1
        else:
            failed += 1

        # Progress
        if (idx + 1) % 50 == 0 or idx == 0:
            elapsed = time.time() - start_time
            rate = (idx + 1) / elapsed if elapsed > 0 else 0
            remaining = (len(pairs) - idx - 1) / rate if rate > 0 else 0
            print(f"  {idx + 1}/{len(pairs)} pares processados "
                  f"({computed} conexoes, {failed} sem caminho) "
                  f"~{remaining:.0f}s restantes", flush=True)

    elapsed = time.time() - start_time
    print(f"\nConcluido em {elapsed:.1f}s")
    print(f"Conexoes: {computed}, Sem caminho: {failed}")

    # Construir nodes
    nodes = {}
    for s in spawns:
        key = make_key(s)
        nodes[key] = {
            "cx": s.cx, "cy": s.cy, "cz": s.cz,
            "monsters": sorted(s.monster_names())
        }

    return {"nodes": nodes, "edges": edges}


def main():
    if len(sys.argv) > 1:
        maps_dir = sys.argv[1]
    else:
        from config import MAPS_DIRECTORY
        maps_dir = MAPS_DIRECTORY

    if not os.path.isdir(maps_dir):
        print(f"Diretorio nao encontrado: {maps_dir}")
        sys.exit(1)

    # Localizar world-spawn.xml
    project_root = os.path.join(os.path.dirname(__file__), '..')
    spawn_xml = os.path.join(project_root, 'world-spawn.xml')
    if not os.path.isfile(spawn_xml):
        print(f"world-spawn.xml nao encontrado em: {spawn_xml}")
        sys.exit(1)

    # Localizar floor_transitions.json
    transitions_file = os.path.join(maps_dir, "floor_transitions.json")

    print(f"Carregando spawns de: {spawn_xml}")
    spawns = parse_spawns(spawn_xml)
    print(f"Spawns carregados: {len(spawns)}")

    print(f"Carregando mapa de: {maps_dir}")
    global_map = GlobalMap(maps_dir, WALKABLE_COLORS, transitions_file=transitions_file)
    print(f"Transicoes carregadas: {sum(len(v) for v in global_map._transitions_by_floor.values())}")

    print("Gerando grafo de spawns...")
    graph = build_spawn_graph(spawns, global_map)

    output_path = os.path.join(maps_dir, "spawn_graph.json")
    with open(output_path, 'w') as f:
        json.dump(graph, f)

    # Stats
    total_edges = sum(len(v) for v in graph["edges"].values()) // 2
    nodes_with_edges = len(graph["edges"])
    isolated = len(graph["nodes"]) - nodes_with_edges
    print(f"\nSalvo em: {output_path}")
    print(f"Nodes: {len(graph['nodes'])}, Conexoes: {total_edges}, Isolados: {isolated}")


if __name__ == '__main__':
    main()
