import tkinter as tk
from tkinter import ttk
import requests
import os
import subprocess
import sys
import threading
from packaging import version

# ================= CONFIGURAÇÕES =================
URL_VERSION = "https://raw.githubusercontent.com/dravendraven/molodoybot/refs/heads/main/version.txt"
URL_EXE = "https://github.com/dravendraven/molodoybot/releases/download/latest/MolodoyBot.exe"
BOT_EXE_NAME = "MolodoyBot.exe"
VERSION_FILE = "version.txt"
# =================================================

class LauncherApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Molodoy Launcher")
        self.root.geometry("300x150")
        self.root.resizable(False, False)
        self.root.configure(bg="#1a1a1a")

        # Centralizar na tela
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        x = (screen_width // 2) - 150
        y = (screen_height // 2) - 75
        self.root.geometry(f"300x150+{x}+{y}")

        # Estilo dark para ttk
        style = ttk.Style()
        style.theme_use('clam')
        style.configure("dark.Horizontal.TProgressbar",
                       background="#3B8ED0",
                       troughcolor="#333333",
                       bordercolor="#1a1a1a",
                       lightcolor="#3B8ED0",
                       darkcolor="#3B8ED0")

        # Status label
        self.lbl_status = tk.Label(
            self.root,
            text="Verificando atualizações...",
            font=("Verdana", 11),
            bg="#1a1a1a",
            fg="#CCCCCC"
        )
        self.lbl_status.pack(pady=20)

        # Progress bar
        self.progress = ttk.Progressbar(
            self.root,
            style="dark.Horizontal.TProgressbar",
            length=200,
            mode='determinate'
        )
        self.progress.pack(pady=10)

        # Botão
        self.btn_action = tk.Button(
            self.root,
            text="Cancelar",
            command=self.close_app,
            state="disabled",
            bg="#333333",
            fg="#888888",
            activebackground="#444444",
            activeforeground="#CCCCCC",
            relief="flat",
            padx=20,
            pady=5
        )
        self.btn_action.pack(pady=10)

        # Inicia a verificação em segundo plano
        threading.Thread(target=self.start_update_check, daemon=True).start()

    def run(self):
        self.root.mainloop()

    def start_update_check(self):
        try:
            # 1. Ler versão local
            local_ver = "0.0"
            if os.path.exists(VERSION_FILE):
                with open(VERSION_FILE, "r") as f:
                    local_ver = f.read().strip()

            # 2. Ler versão remota (GitHub)
            try:
                response = requests.get(URL_VERSION, timeout=10)
                response.raise_for_status()
                remote_ver = response.text.strip()
            except Exception:
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

            # Timeout maior e headers otimizados
            response = requests.get(
                URL_EXE,
                stream=True,
                timeout=120,
                headers={'Connection': 'keep-alive'}
            )
            response.raise_for_status()

            total_length = response.headers.get('content-length')

            if total_length is None:
                # Se não souber o tamanho, baixa direto
                with open(BOT_EXE_NAME, 'wb') as f:
                    f.write(response.content)
            else:
                dl = 0
                total_length = int(total_length)
                with open(BOT_EXE_NAME, 'wb') as f:
                    # Chunk size de 128KB para download mais rápido
                    for data in response.iter_content(chunk_size=131072):
                        dl += len(data)
                        f.write(data)
                        # Atualiza barra (0-100)
                        pct = (dl / total_length) * 100
                        self.update_gui("progress", pct)

            # Atualiza o arquivo de versão local
            with open(VERSION_FILE, "w") as f:
                f.write(new_ver)

            self.launch_bot("Atualização concluída!")

        except Exception as e:
            self.update_gui("status", f"Erro no download: {e}")
            self.root.after(0, self._enable_exit_button)

    def _enable_exit_button(self):
        self.btn_action.configure(state="normal", text="Sair", bg="#AA3333", fg="#FFFFFF")

    def launch_bot(self, msg):
        self.update_gui("status", msg)
        self.update_gui("progress", 100)

        # Aguarda 1 segundo para ler a mensagem
        import time
        time.sleep(1.0)

        if os.path.exists(BOT_EXE_NAME):
            subprocess.Popen([BOT_EXE_NAME])
            self.close_app()
        else:
            self.update_gui("status", f"Erro: {BOT_EXE_NAME} não encontrado!")
            self.root.after(0, self._enable_close_button)

    def _enable_close_button(self):
        self.btn_action.configure(state="normal", text="Fechar", bg="#AA3333", fg="#FFFFFF")

    def update_gui(self, tipo, valor):
        """Atualiza a interface gráfica de forma thread-safe"""
        if tipo == "status":
            self.root.after(0, lambda: self.lbl_status.configure(text=valor))
        elif tipo == "progress":
            self.root.after(0, lambda: self.progress.configure(value=valor))

    def close_app(self):
        self.root.destroy()
        sys.exit()


if __name__ == "__main__":
    app = LauncherApp()
    app.run()
