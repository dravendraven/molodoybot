import pymem
import time
import os
import sys
from walker import Walker
from config import *

# ==============================================================================
# CONFIGURAÇÃO
# ==============================================================================
PROCESS_NAME = "Tibia.exe"

# ==============================================================================
# UTILITÁRIOS
# ==============================================================================
def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')

def get_player_pos(pm):
    """Lê a posição atual do jogador."""
    try:
        x = pm.read_int(PLAYER_X_ADDRESS)
        y = pm.read_int(PLAYER_Y_ADDRESS)
        z = pm.read_int(PLAYER_Z_ADDRESS)
        return x, y, z
    except:
        return None

def print_banner():
    clear_screen()
    print("==========================================")
    print("   CAVEBOT TESTER - WALKER 2.0 (A* + COSTS)")
    print("==========================================")

# ==============================================================================
# MÓDULO DE GRAVAÇÃO
# ==============================================================================
def record_waypoints(pm):
    waypoints = []
    
    while True:
        print_banner()
        print(f"Waypoints Gravados: {len(waypoints)}")
        if waypoints:
            print(f"Último: {waypoints[-1]}")
        
        print("\n[COMANDOS]")
        print("  [ENTER] Salvar posição atual")
        print("  [R]     Rodar (Run) o Cavebot")
        print("  [L]     Limpar lista")
        print("  [Q]     Sair")
        
        choice = input("\n> ").strip().lower()

        if choice == 'q':
            sys.exit()
            
        elif choice == 'l':
            waypoints = []
            print("Lista limpa!")
            time.sleep(1)
            
        elif choice == 'r':
            if len(waypoints) < 2:
                print("⚠️  Precisa de pelo menos 2 waypoints para criar uma rota!")
                time.sleep(2)
                continue
            return waypoints

        else:
            # Tenta gravar
            pos = get_player_pos(pm)
            if pos:
                # Evita gravar o mesmo sqm duas vezes seguidas
                if not waypoints or waypoints[-1] != pos:
                    waypoints.append(pos)
                    print(f"✅ Gravado: {pos}")
                    time.sleep(0.2)
                else:
                    print("⚠️  Você já salvou este sqm.")
                    time.sleep(0.5)
            else:
                print("❌ Erro ao ler posição. O Tibia está aberto?")
                time.sleep(2)

# ==============================================================================
# MÓDULO DE EXECUÇÃO
# ==============================================================================
def run_cavebot(pm, waypoints):
    walker = Walker(pm)
    current_index = 0
    total_wps = len(waypoints)
    
    print_banner()
    print(f"🚀 Iniciando rota com {total_wps} waypoints...")
    print("Pressione Ctrl+C para parar.\n")
    
    try:
        while True:
            target = waypoints[current_index]
            print(f"\n[ROTINA] Indo para WP {current_index + 1}/{total_wps}: {target}")
            
            # --- O GRANDE MOMENTO: O WALKER ASSUME ---
            # Ele vai calcular A*, limpar obstaculos e andar em diagonais
            success = walker.goto(target[0], target[1], target[2])
            
            if success:
                print(f"✅ Chegou no WP {current_index + 1}.")
                
                # Lógica de Cavebot simples: Avança o index circularmente
                current_index = (current_index + 1) % total_wps
                
                # Pequena pausa para parecer humano (opcional)
                time.sleep(0.2)
                
            else:
                print(f"❌ Falha ao alcançar WP {current_index + 1}.")
                print("Tentando pular para o próximo...")
                # Se falhou (bloqueio total), tenta ir direto para o próximo
                current_index = (current_index + 1) % total_wps
                time.sleep(1)

    except KeyboardInterrupt:
        print("\n🛑 Cavebot pausado pelo usuário.")
        input("Pressione Enter para voltar ao menu...")

# ==============================================================================
# MAIN
# ==============================================================================
if __name__ == "__main__":
    try:
        pm = pymem.Pymem(PROCESS_NAME)
        print(f"Conectado ao {PROCESS_NAME} (PID: {pm.process_id})")
        time.sleep(1)
        
        saved_route = []
        
        while True:
            # Se já tiver rota, pergunta se quer usar
            if saved_route:
                print_banner()
                print(f"Rota atual na memória: {len(saved_route)} pontos.")
                print("[1] Usar rota existente")
                print("[2] Gravar nova rota")
                ans = input("\n> ")
                if ans == '2':
                    saved_route = record_waypoints(pm)
            else:
                saved_route = record_waypoints(pm)
            
            # Executa
            if saved_route:
                run_cavebot(pm, saved_route)
                
    except Exception as e:
        print(f"Erro crítico: {e}")