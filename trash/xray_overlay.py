import tkinter as tk
import win32gui
import win32con
import time
import threading
from config import *
from map_core import get_game_view, get_screen_coord

class XRayOverlay:
    def __init__(self, pm, base_addr):
        self.pm = pm
        self.base_addr = base_addr
        self.running = False
        self.root = None
        self.canvas = None
        self.labels = []
        
    def start(self):
        self.running = True
        # Cria thread para a GUI do Overlay (Tkinter precisa de thread própria se não for main)
        # Mas como já temos uma GUI principal, o ideal é rodar isso como Toplevel da principal
        # ou num processo separado. Para teste, vamos rodar aqui.
        self.run_overlay()

    def run_overlay(self):
        self.root = tk.Tk()
        self.root.title("Molodoy X-Ray")
        
        # Configuração de Transparência (Chroma Key)
        # Tudo que for "black" ficará invisível
        self.root.wm_attributes("-transparentcolor", "black")
        self.root.wm_attributes("-topmost", True)
        self.root.overrideredirect(True) # Remove bordas/barra de título
        self.root.config(bg="black")
        
        self.canvas = tk.Canvas(self.root, bg="black", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        
        self.update_loop()
        self.root.mainloop()
        
    def get_tibia_rect(self):
        hwnd = win32gui.FindWindow("TibiaClient", None)
        if not hwnd: hwnd = win32gui.FindWindow(None, "Tibia")
        if hwnd:
            try:
                rect = win32gui.GetWindowRect(hwnd)
                return rect # (left, top, right, bottom)
            except: pass
        return None

    def update_loop(self):
        if not self.running:
            self.root.destroy()
            return

        try:
            # 1. Sincroniza Janela com o Tibia
            rect = self.get_tibia_rect()
            if rect:
                x, y, r, b = rect
                w = r - x
                h = b - y
                self.root.geometry(f"{w}x{h}+{x}+{y}")
            
            # 2. Limpa desenhos anteriores
            self.canvas.delete("all")
            
            # 3. Lê dados do jogo
            # Precisamos da posição do player para calcular o Z relativo
            # Replicando leitura rápida para não depender de imports circulares
            my_z = self.pm.read_int(self.base_addr + 0x1D16E8) # OFFSET_Z
            
            gv = get_game_view(self.pm, self.base_addr)
            
            if gv and my_z != 0:
                # Varre criaturas
                list_start = self.base_addr + TARGET_ID_PTR + REL_FIRST_ID
                
                for i in range(MAX_CREATURES):
                    slot = list_start + (i * STEP_SIZE)
                    if self.pm.read_int(slot) > 0:
                        vis = self.pm.read_int(slot + OFFSET_VISIBLE)
                        
                        # O PULO DO GATO: 
                        # O cliente mantém na memória criaturas de outros andares
                        # se elas estiverem no range de comunicação, mesmo vis=0 na tela.
                        # Mas geralmente queremos ver quem está visível para o cliente (pacote recebido).
                        
                        if vis == 1: # O cliente sabe onde ela está
                            cz = self.pm.read_int(slot + OFFSET_Z)
                            
                            # Só desenha se for andar DIFERENTE (Raio-X)
                            if cz != my_z:
                                raw_name = self.pm.read_string(slot + OFFSET_NAME, 32)
                                name = raw_name.split('\x00')[0]
                                
                                if name == MY_PLAYER_NAME: continue
                                
                                # Cor baseada no andar
                                color = COLOR_FLOOR_ABOVE if cz < my_z else COLOR_FLOOR_BELOW
                                floor_tag = "▲" if cz < my_z else "▼"
                                
                                # Calcula Posição na Tela
                                cx = self.pm.read_int(slot + OFFSET_X)
                                cy = self.pm.read_int(slot + OFFSET_Y)
                                
                                # Precisamos do Player X,Y para o Delta
                                my_x = self.pm.read_int(self.base_addr + 0x1D16F0)
                                my_y = self.pm.read_int(self.base_addr + 0x1D16EC)
                                
                                dx = cx - my_x
                                dy = cy - my_y
                                
                                # Converte para pixel
                                # Como o overlay está exatamente em cima da janela do Tibia,
                                # Coordenada de Cliente = Coordenada do Canvas! (quase)
                                # O get_screen_coord usa ClientToScreen, que é global.
                                # Nosso Canvas é global. Então bate!
                                
                                sx, sy = get_screen_coord(gv, dx, dy, 0) # HWND 0 retorna tela global?
                                # get_screen_coord precisa de HWND para clienttoscreen.
                                # Vamos calcular manual aqui para ser relativo ao GameView
                                
                                # Lógica Manual (Relativa ao GameView):
                                # Centro do GV + (Delta * SQM)
                                screen_x = gv['center'][0] + (dx * gv['sqm'])
                                screen_y = gv['center'][1] + (dy * gv['sqm'])
                                
                                # Ajuste: O Canvas começa no (0,0) da janela do Tibia.
                                # O GameView['rect'] tem X,Y relativos à janela.
                                # Então screen_x, screen_y já são relativos à janela!
                                
                                # Desenha
                                self.canvas.create_text(screen_x, screen_y - 40, 
                                                        text=f"{floor_tag} {name}", 
                                                        fill=color, font=("Verdana", 10, "bold"))
                                self.canvas.create_rectangle(screen_x-15, screen_y-15, screen_x+15, screen_y+15, 
                                                             outline=color, width=2)

        except Exception as e:
            print(f"Erro Overlay: {e}")
            
        # Atualiza a cada 50ms (20 FPS)
        self.root.after(50, self.update_loop)

# Teste Isolado
if __name__ == "__main__":
    import pymem
    try:
        pm = pymem.Pymem(PROCESS_NAME)
        base_addr = pymem.process.module_from_name(pm.process_handle, PROCESS_NAME).lpBaseOfDll
        print("Iniciando X-Ray...")
        overlay = XRayOverlay(pm, base_addr)
        overlay.start()
    except Exception as e:
        print(e)