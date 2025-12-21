import os
import sys
from PIL import Image, ImageDraw
import math

# Adiciona raiz ao path para imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import MAPS_DIRECTORY, WALKABLE_COLORS
from core.global_map import GlobalMap
from utils.color_palette import get_color

def create_visualization(maps_dir, path_data, output_filename="debug_mapa.png", is_failure=False):
    """
    Gera a imagem.
    Se is_failure=True, 'path_data' é o dicionário de debug do flood fill.
    Se is_failure=False, 'path_data' é a lista de tuplas da rota.
    """
    
    # 1. Extrair dados baseados no modo
    if is_failure:
        path_coords = path_data['partial_path']
        visited_set = path_data['visited_coords']
        barriers_set = path_data['barrier_coords']
        z = path_coords[0][2]
        
        # Coleta todos os pontos para definir o tamanho da imagem
        all_xs = [p[0] for p in path_coords] + [b[0] for b in barriers_set]
        all_ys = [p[1] for p in path_coords] + [b[1] for b in barriers_set]
    else:
        path_coords = path_data
        visited_set = set()
        barriers_set = set()
        z = path_coords[0][2]
        all_xs = [p[0] for p in path_coords]
        all_ys = [p[1] for p in path_coords]

    if not all_xs:
        print("Nada para desenhar.")
        return

    # 2. Definir Bounding Box com margem
    padding = 30
    min_x, max_x = min(all_xs) - padding, max(all_xs) + padding
    min_y, max_y = min(all_ys) - padding, max(all_ys) + padding
    
    width = max_x - min_x + 1
    height = max_y - min_y + 1
    
    print(f"🎨 Gerando imagem {width}x{height}...")
    
    # Imagem base
    img = Image.new('RGB', (width, height), (0, 0, 0))
    pixels = img.load()

    # 3. Carregar o Mapa de Fundo
    start_cx, end_cx = min_x // 256, max_x // 256
    start_cy, end_cy = min_y // 256, max_y // 256
    
    for cx in range(start_cx, end_cx + 1):
        for cy in range(start_cy, end_cy + 1):
            filenames = [f"{cx:03}{cy:03}{z:02}.map", f"{cx}{cy}{z:02}.map"]
            map_data = None
            for fname in filenames:
                p = os.path.join(maps_dir, fname)
                if os.path.exists(p):
                    with open(p, "rb") as f: map_data = f.read()
                    break
            
            if map_data:
                base_x, base_y = cx * 256, cy * 256
                for i, val in enumerate(map_data):
                    if val == 0: continue
                    abs_x = base_x + (i // 256)
                    abs_y = base_y + (i % 256)
                    
                    if min_x <= abs_x <= max_x and min_y <= abs_y <= max_y:
                        pixels[abs_x - min_x, abs_y - min_y] = get_color(val)

    # 4. Desenhar Overlays de Debug (Falha)
    if is_failure:
        # A. Desenhar área explorada (Azul fraco)
        EXPLORED_COLOR = (0, 0, 100)
        for (vx, vy) in visited_set:
            if min_x <= vx <= max_x and min_y <= vy <= max_y:
                # Mistura simples se quiser ver o chão embaixo, ou sobrescreve
                pixels[vx - min_x, vy - min_y] = EXPLORED_COLOR

        # B. Desenhar Barreiras encontradas (Vermelho Vivo)
        BARRIER_COLOR = (255, 0, 0)
        for (bx, by) in barriers_set:
            if min_x <= bx <= max_x and min_y <= by <= max_y:
                pixels[bx - min_x, by - min_y] = BARRIER_COLOR

    # 5. Desenhar Rota (Verde se sucesso, Laranja se parcial)
    ROUTE_COLOR = (0, 255, 0) if not is_failure else (255, 165, 0) # Verde ou Laranja
    
    for (px, py, pz) in path_coords:
        if min_x <= px <= max_x and min_y <= py <= max_y:
            pixels[px - min_x, py - min_y] = ROUTE_COLOR

    # Marca Início e Fim
    start = path_coords[0]
    end = path_coords[-1]
    
    # Desenha um quadrado branco no início
    sx, sy = start[0] - min_x, start[1] - min_y
    for dx in range(-1, 2):
        for dy in range(-1, 2):
            if 0 <= sx+dx < width and 0 <= sy+dy < height:
                pixels[sx+dx, sy+dy] = (255, 255, 255)

    img.save(output_filename)
    print(f"💾 Imagem salva: {os.path.abspath(output_filename)}")
    try:
        os.startfile(output_filename)
    except:
        pass

def create_route_visualization(maps_dir, waypoints, output_prefix="mapa_rota"):
    """
    Gera imagens de minimapa para cada andar presente nos waypoints.
    Calcula os caminhos completos entre waypoints usando GlobalMap.

    Args:
        maps_dir: Diretório dos arquivos .map
        waypoints: Lista de dicts com 'x', 'y', 'z'
        output_prefix: Prefixo dos arquivos de saída

    Returns:
        List[str]: Lista de arquivos gerados
    """
    from collections import defaultdict

    if not waypoints:
        print("⚠️ Lista de waypoints vazia.")
        return []

    # 1. Calcular os caminhos completos entre waypoints consecutivos
    gm = GlobalMap(maps_dir, WALKABLE_COLORS)
    full_paths_by_floor = defaultdict(list)
    transitions = []

    print(f"📊 Calculando rotas entre {len(waypoints)} waypoints...")

    for i in range(len(waypoints) - 1):
        curr_wp = waypoints[i]
        next_wp = waypoints[i + 1]
        curr_pos = (curr_wp['x'], curr_wp['y'], curr_wp['z'])
        next_pos = (next_wp['x'], next_wp['y'], next_wp['z'])

        # Se estão no mesmo andar, calcular caminho
        if curr_wp['z'] == next_wp['z']:
            z = curr_wp['z']
            path = gm.get_path_with_fallback(curr_pos, next_pos)
            if path:
                full_paths_by_floor[z].extend(path)
                print(f"  ✓ Rota {i} → {i+1} (Z={z}): {len(path)} tiles")
            else:
                print(f"  ⚠️ Não encontrou rota {i} → {i+1} (Z={z})")
                # Se falhar, ao menos adiciona os waypoints
                full_paths_by_floor[z].append(curr_pos)
        else:
            # Transição de andar
            from_z = curr_wp['z']
            to_z = next_wp['z']
            transitions.append({
                'from_z': from_z,
                'to_z': to_z,
                'x': curr_wp['x'],
                'y': curr_wp['y'],
                'type': 'UP' if to_z < from_z else 'DOWN'
            })
            print(f"  ➜ Transição {i} → {i+1}: Z{from_z} → Z{to_z}")
            # Adiciona último ponto antes da transição
            full_paths_by_floor[from_z].append(curr_pos)
            # Tenta calcular rota após transição
            next_next_idx = i + 2
            if next_next_idx < len(waypoints):
                next_next_wp = waypoints[next_next_idx]
                if next_next_wp['z'] == to_z:
                    next_next_pos = (next_next_wp['x'], next_next_wp['y'], next_next_wp['z'])
                    path = gm.get_path_with_fallback(next_pos, next_next_pos)
                    if path:
                        full_paths_by_floor[to_z].extend(path)
            full_paths_by_floor[to_z].append(next_pos)

    print(f"🪜 {len(transitions)} transições de andar detectadas")

    # 2. Gerar imagem para cada andar
    generated_files = []
    for z in sorted(full_paths_by_floor.keys()):
        path_coords = full_paths_by_floor[z]
        output_file = f"{output_prefix}_z{z}.png"

        # Filtra transições deste andar
        floor_transitions = [t for t in transitions if t['from_z'] == z]

        # Gera visualização com marcadores de transição
        _create_floor_visualization(
            maps_dir,
            path_coords,
            floor_transitions,
            output_file,
            z
        )
        generated_files.append(output_file)

    return generated_files

def _create_floor_visualization(maps_dir, path_coords, transitions, output_file, floor_z):
    """
    Gera visualização de um único andar com marcadores de transição.
    """
    # Remover duplicatas mantendo ordem
    seen = set()
    unique_coords = []
    for coord in path_coords:
        if coord not in seen:
            seen.add(coord)
            unique_coords.append(coord)

    # Extrair coordenadas
    all_xs = [p[0] for p in unique_coords]
    all_ys = [p[1] for p in unique_coords]

    if not all_xs:
        print(f"⚠️ Andar {floor_z} sem waypoints.")
        return

    # Bounding Box
    padding = 30
    min_x, max_x = min(all_xs) - padding, max(all_xs) + padding
    min_y, max_y = min(all_ys) - padding, max(all_ys) + padding
    width = max_x - min_x + 1
    height = max_y - min_y + 1

    print(f"🎨 Gerando andar Z={floor_z} ({width}x{height})...")

    # Criar imagem base
    img = Image.new('RGB', (width, height), (0, 0, 0))
    pixels = img.load()

    # Carregar chunks do mapa
    start_cx, end_cx = min_x // 256, max_x // 256
    start_cy, end_cy = min_y // 256, max_y // 256

    for cx in range(start_cx, end_cx + 1):
        for cy in range(start_cy, end_cy + 1):
            filenames = [f"{cx:03}{cy:03}{floor_z:02}.map", f"{cx}{cy}{floor_z:02}.map"]
            map_data = None
            for fname in filenames:
                p = os.path.join(maps_dir, fname)
                if os.path.exists(p):
                    with open(p, "rb") as f:
                        map_data = f.read()
                    break

            if map_data:
                base_x, base_y = cx * 256, cy * 256
                for i, val in enumerate(map_data):
                    if val == 0:
                        continue
                    abs_x = base_x + (i // 256)
                    abs_y = base_y + (i % 256)

                    if min_x <= abs_x <= max_x and min_y <= abs_y <= max_y:
                        pixels[abs_x - min_x, abs_y - min_y] = get_color(val)

    # Desenhar rota (Verde)
    ROUTE_COLOR = (0, 255, 0)
    for (px, py, pz) in unique_coords:
        if min_x <= px <= max_x and min_y <= py <= max_y:
            pixels[px - min_x, py - min_y] = ROUTE_COLOR

    # Marcar início (Branco)
    start = unique_coords[0]
    sx, sy = start[0] - min_x, start[1] - min_y
    for dx in range(-1, 2):
        for dy in range(-1, 2):
            if 0 <= sx+dx < width and 0 <= sy+dy < height:
                pixels[sx+dx, sy+dy] = (255, 255, 255)

    # Marcar fim (Azul Claro)
    end = unique_coords[-1]
    ex, ey = end[0] - min_x, end[1] - min_y
    for dx in range(-1, 2):
        for dy in range(-1, 2):
            if 0 <= ex+dx < width and 0 <= ey+dy < height:
                pixels[ex+dx, ey+dy] = (100, 200, 255)

    # Marcar transições (Magenta para subir, Ciano para descer)
    for trans in transitions:
        tx, ty = trans['x'] - min_x, trans['y'] - min_y
        color = (255, 0, 255) if trans['type'] == 'UP' else (0, 255, 255)  # Magenta : Ciano

        # Desenha quadrado 3x3
        for dx in range(-1, 2):
            for dy in range(-1, 2):
                if 0 <= tx+dx < width and 0 <= ty+dy < height:
                    pixels[tx+dx, ty+dy] = color

    # Salvar
    img.save(output_file)
    print(f"💾 Andar Z={floor_z} salvo: {os.path.abspath(output_file)}")

# ============================================================================
# EXECUÇÃO
# ============================================================================
if __name__ == "__main__":
    gm = GlobalMap(MAPS_DIRECTORY, WALKABLE_COLORS)
    
    # --- COORDENADAS DO SEU PROBLEMA ---
    start_pos = (32406, 31729, 8) 
    #{x = 32406, y = 31729, z = 8}
    end_pos = (32435, 31637, 8)   
    #{x = 32435, y = 31637, z = 8}
    
    print(f"Testando rota: {start_pos} -> {end_pos}")
    path = gm.get_path_with_fallback(start_pos, end_pos)
    
    if path:
        print("✅ Sucesso!")
        create_visualization(MAPS_DIRECTORY, path, "sucesso.png", is_failure=False)
    else:
        print("❌ Falha na rota. Gerando mapa de diagnóstico...")
        debug_data = gm.diagnose_path_failure(start_pos, end_pos)
        create_visualization(MAPS_DIRECTORY, debug_data, "falha_debug.png", is_failure=True)