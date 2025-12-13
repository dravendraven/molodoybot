import customtkinter as ctk
import requests
import os
import subprocess
import sys
import threading
from packaging import version # Precisa instalar: pip install packaging

# ================= CONFIGURAÇÕES =================
# 1. Link do arquivo de texto no GitHub (Botão RAW)
URL_VERSION = "https://raw.githubusercontent.com/dravendraven/molodoybot/refs/heads/main/version.txt"

# 2. Link para baixar o executável. 
# Dica: Use o sistema de "Releases" do GitHub e crie uma tag chamada "latest".
# Assim o link será sempre igual.
URL_EXE = "https://github.com/dravendraven/molodoybot/releases/download/latest/MolodoyBot.exe"

# Nomes dos arquivos no computador
BOT_EXE_NAME = "MolodoyBot.exe"
VERSION_FILE = "version.txt"
# =================================================

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

class LauncherApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Molodoy Launcher")
        self.geometry("300x150")
        self.resizable(False, False)
        
        # Centralizar na tela
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        x = (screen_width/2) - (300/2)
        y = (screen_height/2) - (150/2)
        self.geometry('%dx%d+%d+%d' % (300, 150, x, y))

        self.lbl_status = ctk.CTkLabel(self, text="Verificando atualizações...", font=("Verdana", 12))
        self.lbl_status.pack(pady=20)

        self.progress = ctk.CTkProgressBar(self, width=200)
        self.progress.pack(pady=10)
        self.progress.set(0)

        self.btn_action = ctk.CTkButton(self, text="Cancelar", command=self.close_app, state="disabled", fg_color="#333")
        self.btn_action.pack(pady=10)

        # Inicia a verificação em segundo plano para não travar a janela
        threading.Thread(target=self.start_update_check, daemon=True).start()

    def start_update_check(self):
        try:
            # 1. Ler versão local
            local_ver = "0.0"
            if os.path.exists(VERSION_FILE):
                with open(VERSION_FILE, "r") as f:
                    local_ver = f.read().strip()
            
            # 2. Ler versão remota (GitHub)
            try:
                response = requests.get(URL_VERSION, timeout=5)
                response.raise_for_status()
                remote_ver = response.text.strip()
            except:
                self.launch_bot(f"Falha na conexão. Iniciando v{local_ver}...")
                return

            # 3. Comparar
            if version.parse(remote_ver) > version.parse(local_ver):
                self.update_gui("status", f"Atualizando: v{local_ver} -> v{remote_ver}")
                self.download_update(remote_ver)
            else:
                self.launch_bot("Sistema atualizado. Iniciando...")

        except Exception as e:
            self.launch_bot(f"Erro: {e}")

    def download_update(self, new_ver):
        try:
            self.update_gui("status", "Baixando nova versão...")
            response = requests.get(URL_EXE, stream=True, timeout=10)
            total_length = response.headers.get('content-length')

            if total_length is None: 
                # Se não souber o tamanho, baixa direto
                with open(BOT_EXE_NAME, 'wb') as f:
                    f.write(response.content)
            else:
                dl = 0
                total_length = int(total_length)
                with open(BOT_EXE_NAME, 'wb') as f:
                    for data in response.iter_content(chunk_size=4096):
                        dl += len(data)
                        f.write(data)
                        # Atualiza barra
                        pct = dl / total_length
                        self.update_gui("progress", pct)
            
            # Atualiza o arquivo de versão local
            with open(VERSION_FILE, "w") as f:
                f.write(new_ver)
            
            self.launch_bot("Atualização concluída!")

        except Exception as e:
            self.update_gui("status", f"Erro no download: {e}")
            self.btn_action.configure(state="normal", text="Sair", fg_color="red", command=self.close_app)

    def launch_bot(self, msg):
        self.update_gui("status", msg)
        self.update_gui("progress", 1.0)
        import time
        time.sleep(1.5) # Tempo para ler a mensagem
        
        if os.path.exists(BOT_EXE_NAME):
            subprocess.Popen([BOT_EXE_NAME]) # Abre o Bot
            self.close_app()
        else:
            self.update_gui("status", f"Erro: {BOT_EXE_NAME} não encontrado!")
            self.btn_action.configure(state="normal", text="Fechar", command=self.close_app)

    def update_gui(self, tipo, valor):
        # Atualiza a interface gráfica de forma segura
        if tipo == "status":
            self.lbl_status.configure(text=valor)
        elif tipo == "progress":
            self.progress.set(valor)

    def close_app(self):
        self.destroy()
        sys.exit()

if __name__ == "__main__":
    app = LauncherApp()
    app.mainloop()