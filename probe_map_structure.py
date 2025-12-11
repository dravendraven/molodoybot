import pymem
import pymem.process
from config import *
from map_memory import get_tile_flags

def get_player_pos(pm, base_addr):
    x = pm.read_int(base_addr + 0x1D16F0)
    y = pm.read_int(base_addr + 0x1D16EC)
    z = pm.read_int(base_addr + 0x1D16E8)
    return x, y, z

def main():
    print("--- RADAR DE TERRENO ---")
    try:
        pm = pymem.Pymem(PROCESS_NAME)
        base_addr = pymem.process.module_from_name(pm.process_handle, PROCESS_NAME).lpBaseOfDll
    except:
        print("Erro: Tibia não encontrado.")
        return

    px, py, pz = get_player_pos(pm, base_addr)
    print(f"Você está em: {px}, {py}, {pz}")
    print("Legenda: . = Andável, # = Parede/Água, E = Escada, @ = Você\n")

    # Desenha um grid 5x5 ao redor do char
    radius = 2
    for dy in range(-radius, radius + 1):
        line = ""
        for dx in range(-radius, radius + 1):
            if dx == 0 and dy == 0:
                line += " @ " # Player
                continue
                
            tx, ty = px + dx, py + dy
            info = get_tile_flags(pm, base_addr, tx, ty, pz)
            
            char = " ? " # Desconhecido
            if info:
                if info['is_stairs']: char = " E "
                elif info['is_walkable']: char = " . "
                else: char = " # " # Bloqueio
            
            line += char
        print(line)

if __name__ == "__main__":
    main()