import tkinter as tk
from tkinter import ttk
import os
import subprocess
import sys
import threading
# requests e packaging são importados sob demanda (lazy) para inicialização mais rápida

# ================= CONFIGURAÇÕES =================
URL_VERSION = "https://raw.githubusercontent.com/dravendraven/molodoybot/refs/heads/main/version.txt"
URL_EXE = "https://github.com/dravendraven/molodoybot/releases/download/latest/MolodoyBot.exe"
GITHUB_API_COMMITS = "https://api.github.com/repos/dravendraven/molodoybot/commits"
GITHUB_API_COMPARE = "https://api.github.com/repos/dravendraven/molodoybot/compare"
BOT_EXE_NAME = "MolodoyBot.exe"
VERSION_FILE = "version.txt"
# =================================================

import re

def is_version_commit(msg, ver=None):
    """Verifica se o commit é um commit de versão (ex: 'v2.5', 'versão 2.5', 'version 2.5')"""
    msg_lower = msg.lower().strip()
    if ver:
        # Checa se é a versão específica
        patterns = [f"v{ver}", f"versão {ver}", f"versao {ver}", f"version {ver}"]
        return any(msg_lower == p or msg_lower.startswith(p) for p in patterns)
    # Checa se é qualquer commit de versão
    return bool(re.match(r'^(v\d|vers[aã]o\s*\d|version\s*\d)', msg_lower))


def fetch_patch_notes(local_ver, remote_ver):
    """Busca os commits entre as versões baseado nas mensagens de commit"""
    import requests  # Lazy import
    try:
        # Busca commits recentes (até 50 para encontrar a versão anterior)
        response = requests.get(f"{GITHUB_API_COMMITS}?per_page=50", timeout=10)
        if response.status_code != 200:
            return ["• Não foi possível carregar as notas"]

        commits = response.json()
        notes = []
        found_local_version = False

        for commit in commits:
            msg = commit.get("commit", {}).get("message", "").split("\n")[0]
            if not msg:
                continue

            # Se encontrou o commit da versão local, para de coletar
            if is_version_commit(msg, local_ver):
                found_local_version = True
                break

            # Ignora commits de versão e merges
            if is_version_commit(msg) or msg.startswith("Merge"):
                continue

            notes.append(f"• {msg}")

        # Se não encontrou a versão local, retorna o que coletou (limitado)
        if not found_local_version:
            notes = notes[:10]

        return notes if notes else ["• Sem alterações registradas"]

    except Exception:
        return ["• Erro ao buscar patch notes"]


class LauncherApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Molodoy Launcher")
        self.root.geometry("300x150")
        self.root.resizable(False, False)
        self.root.configure(bg="#1a1a1a")
        self.patch_notes_window = None

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

        # Força renderização imediata da UI antes de qualquer processamento pesado
        self.root.update()

        # Inicia a verificação em segundo plano com pequeno delay para garantir UI responsiva
        self.root.after(100, lambda: threading.Thread(target=self.start_update_check, daemon=True).start())

    def run(self):
        self.root.mainloop()

    def start_update_check(self):
        try:
            # Import dos módulos (pode demorar em sistemas lentos)
            self.update_gui("status", "Carregando módulos...")
            try:
                import requests
                from packaging import version
            except ImportError as e:
                self.update_gui("status", f"Erro ao carregar: {e}")
                self.root.after(0, self._enable_close_button)
                return

            self.update_gui("status", "Verificando atualizações...")

            # 1. Ler versão local
            local_ver = "0.0"
            if os.path.exists(VERSION_FILE):
                with open(VERSION_FILE, "r") as f:
                    local_ver = f.read().strip()

            # 2. Ler versão remota (GitHub)
            self.update_gui("status", "Conectando ao servidor...")
            try:
                response = requests.get(URL_VERSION, timeout=15)
                response.raise_for_status()
                remote_ver = response.text.strip()
            except Exception:
                self.launch_bot(f"Falha na conexão. Iniciando v{local_ver}...")
                return

            # 3. Comparar
            self.update_gui("status", "Comparando versões...")
            if version.parse(remote_ver) > version.parse(local_ver):
                self.update_gui("status", f"Atualizando: v{local_ver} -> v{remote_ver}")

                # Busca e mostra patch notes
                notes = fetch_patch_notes(local_ver, remote_ver)
                if notes:
                    self.show_patch_notes(local_ver, remote_ver, notes)

                self.download_update(remote_ver)
            else:
                self.launch_bot("Sistema atualizado. Iniciando...")

        except Exception as e:
            self.update_gui("status", f"Erro: {e}")
            self.root.after(0, self._enable_close_button)

    def download_update(self, new_ver):
        import requests  # Lazy import
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

        # Breve pausa para ler a mensagem
        import time
        time.sleep(0.3)

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

    def show_patch_notes(self, local_ver, remote_ver, notes):
        """Mostra janela com patch notes"""
        def _show():
            if self.patch_notes_window and self.patch_notes_window.winfo_exists():
                return

            self.patch_notes_window = tk.Toplevel(self.root)
            self.patch_notes_window.title("Patch Notes")
            self.patch_notes_window.geometry("350x250")
            self.patch_notes_window.configure(bg="#1a1a1a")
            self.patch_notes_window.resizable(False, False)

            # Posicionar ao lado do launcher
            x = self.root.winfo_x() + self.root.winfo_width() + 10
            y = self.root.winfo_y()
            self.patch_notes_window.geometry(f"350x250+{x}+{y}")

            # Header
            header = tk.Label(
                self.patch_notes_window,
                text=f"Novidades v{remote_ver}",
                font=("Verdana", 11, "bold"),
                bg="#1a1a1a",
                fg="#3B8ED0"
            )
            header.pack(pady=(10, 5))

            # Subheader
            subheader = tk.Label(
                self.patch_notes_window,
                text=f"Atualizando de v{local_ver}",
                font=("Verdana", 9),
                bg="#1a1a1a",
                fg="#888888"
            )
            subheader.pack(pady=(0, 10))

            # Frame para scroll
            frame = tk.Frame(self.patch_notes_window, bg="#1a1a1a")
            frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))

            # Canvas + Scrollbar
            canvas = tk.Canvas(frame, bg="#252525", highlightthickness=0)
            scrollbar = ttk.Scrollbar(frame, orient="vertical", command=canvas.yview)
            scrollable_frame = tk.Frame(canvas, bg="#252525")

            scrollable_frame.bind(
                "<Configure>",
                lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
            )

            canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
            canvas.configure(yscrollcommand=scrollbar.set)

            # Adiciona as notas
            for note in notes:
                lbl = tk.Label(
                    scrollable_frame,
                    text=note,
                    font=("Verdana", 9),
                    bg="#252525",
                    fg="#CCCCCC",
                    anchor="w",
                    justify="left",
                    wraplength=300
                )
                lbl.pack(fill="x", padx=5, pady=2)

            canvas.pack(side="left", fill="both", expand=True)
            scrollbar.pack(side="right", fill="y")

            # Bind scroll do mouse
            def _on_mousewheel(event):
                canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
            canvas.bind_all("<MouseWheel>", _on_mousewheel)

        self.root.after(0, _show)

    def close_app(self):
        self.root.destroy()
        sys.exit()


if __name__ == "__main__":
    app = LauncherApp()
    app.run()
