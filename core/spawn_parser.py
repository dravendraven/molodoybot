import xml.etree.ElementTree as ET
import time


class SpawnArea:
    """Representa uma área de spawn parseada do world-spawn.xml."""

    def __init__(self, cx, cy, cz, xml_radius, monsters):
        self.cx = cx
        self.cy = cy
        self.cz = cz
        self.xml_radius = xml_radius
        self.radius = 5  # raio fixo da "área" para navegação
        self.monsters = monsters  # [{"name": str, "spawntime": int}, ...]

        # Estado de exploração
        self.last_visited = 0  # timestamp
        self.is_reachable = None  # None=não testado, True/False após validação

    def distance_to(self, px, py):
        """Distância Manhattan do ponto (px, py) à BORDA mais próxima da área."""
        nearest_x = max(self.cx - self.radius, min(px, self.cx + self.radius))
        nearest_y = max(self.cy - self.radius, min(py, self.cy + self.radius))
        return abs(px - nearest_x) + abs(py - nearest_y)

    def is_inside(self, px, py, pz):
        """Retorna True se a posição está dentro da área do spawn."""
        return (pz == self.cz
                and abs(px - self.cx) <= self.radius
                and abs(py - self.cy) <= self.radius)

    def nearest_walkable_target(self, global_map):
        """Retorna (x, y, z) walkable mais próximo do centro, ou None."""
        if global_map.is_walkable(self.cx, self.cy, self.cz):
            return (self.cx, self.cy, self.cz)

        for dist in range(1, self.radius + 1):
            for dx in range(-dist, dist + 1):
                for dy in range(-dist, dist + 1):
                    if abs(dx) == dist or abs(dy) == dist:
                        x, y = self.cx + dx, self.cy + dy
                        if global_map.is_walkable(x, y, self.cz):
                            return (x, y, self.cz)
        return None

    def monster_names(self):
        """Retorna set de nomes de monstros neste spawn (lowercase)."""
        return {m["name"].lower() for m in self.monsters}

    def __repr__(self):
        names = ", ".join(sorted(self.monster_names()))
        return f"SpawnArea(({self.cx}, {self.cy}, {self.cz}) monsters=[{names}])"


def parse_spawns(xml_path):
    """Parseia world-spawn.xml e retorna lista de SpawnArea."""
    tree = ET.parse(xml_path)
    root = tree.getroot()

    spawns = []
    for spawn_elem in root.findall("spawn"):
        cx = int(spawn_elem.get("centerx", 0))
        cy = int(spawn_elem.get("centery", 0))
        cz = int(spawn_elem.get("centerz", 0))
        radius = int(spawn_elem.get("radius", 3))

        monsters = []
        for monster_elem in spawn_elem.findall("monster"):
            monsters.append({
                "name": monster_elem.get("name", ""),
                "spawntime": int(monster_elem.get("spawntime", 60)),
            })

        if monsters:
            spawns.append(SpawnArea(cx, cy, cz, radius, monsters))

    return spawns
