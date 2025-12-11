import pymem
import os
import time
import colorama
from colorama import Fore, Style
from config import *
from map_reader import MapReader, CENTER_X_GRID, CENTER_Y_GRID, COST_BLOCKED, COST_WALKABLE

colorama.init()

def print_debug_map(grid):
    os.system('cls' if os.name == 'nt' else 'clear')
    print(f"--- VISÃO DO CAVEBOT ---")
    print(f"Legenda: {Fore.GREEN}.{Style.RESET_ALL} = Andável | {Fore.RED}#{Style.RESET_ALL} = Parede | {Fore.YELLOW}S{Style.RESET_ALL} = Stack/Móvel\n")

    output = "    " + "".join([f"{x:<3}" for x in range(len(grid[0]))]) + "\n"
    
    for y, row in enumerate(grid):
        line_str = f"{y:<3} "
        for x, cost in enumerate(row):
            symbol = " ? "
            
            # É o player?
            if x == CENTER_X_GRID and y == CENTER_Y_GRID:
                symbol = f"{Fore.CYAN} @ {Style.RESET_ALL}"
            
            # É Parede?
            elif cost >= COST_BLOCKED:
                symbol = f"{Fore.RED} # {Style.RESET_ALL}"
            
            # É Chão Limpo?
            elif cost <= COST_WALKABLE:
                symbol = f"{Fore.GREEN} . {Style.RESET_ALL}"
            
            # É Obstáculo Móvel (Mesa/Parcel)?
            else:
                symbol = f"{Fore.YELLOW} S {Style.RESET_ALL}"
            
            line_str += symbol
        output += line_str + "\n"
    
    print(output)
    print(f"Centro (Você): [{CENTER_X_GRID}, {CENTER_Y_GRID}]")

if __name__ == "__main__":
    try:
        pm = pymem.Pymem("Tibia.exe")
        reader = MapReader(pm)
        print("Conectado! Pressione Ctrl+C para parar.")
        
        while True:
            # 1. Pega Z do player
            try:
                pz = pm.read_int(PLAYER_Z_ADDRESS)
            except:
                continue

            # 2. Gera Grid
            grid = reader.get_cost_grid(pz)
            
            # 3. Desenha
            if grid:
                print_debug_map(grid)
            
            # Atualiza a cada 0.5s
            time.sleep(0.5)
            
    except Exception as e:
        print(f"Erro: {e}")