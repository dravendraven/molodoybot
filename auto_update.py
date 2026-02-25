"""
Auto-update integrado para MolodoyBot.
Verifica updates ao iniciar e aplica automaticamente.
"""
import os
import sys
import subprocess
import tempfile
import threading
import tkinter as tk
from tkinter import ttk

# ================= CONFIGURAÇÕES =================
# Versão atual hardcoded (atualizada automaticamente pelo publicar.bat)
CURRENT_VERSION = "5.8"

# URLs do GitHub
URL_VERSION = "https://raw.githubusercontent.com/dravendraven/molodoybot/refs/heads/main/version.txt"
URL_EXE = "https://github.com/dravendraven/molodoybot/releases/download/latest/MolodoyBot.exe"
EXE_NAME = "MolodoyBot.exe"

# Arquivos legados a serem removidos (migração do launcher antigo)
LEGACY_FILES = ["MolodoyLauncher.exe", "version.txt"]
# =================================================


def cleanup_legacy_files():
    """Remove arquivos do sistema antigo (launcher) para forçar uso do auto-update."""
    for filename in LEGACY_FILES:
        if os.path.exists(filename):
            try:
                os.remove(filename)
            except:
                pass


def cleanup_duplicate_exes():
    """
    Remove cópias do bot na mesma pasta (ex: 'molodoybot2.exe', 'copia de molodoybot.exe').
    Mantém apenas o executável atual.
    """
    if not getattr(sys, 'frozen', False):
        return

    current_exe = os.path.basename(sys.executable).lower()
    current_dir = os.path.dirname(sys.executable) or "."

    try:
        for filename in os.listdir(current_dir):
            # Só processa arquivos .exe
            if not filename.lower().endswith('.exe'):
                continue

            # Ignora o próprio executável
            if filename.lower() == current_exe:
                continue

            # Verifica se contém "molodoy" no nome (detecta cópias)
            if "molodoy" in filename.lower():
                filepath = os.path.join(current_dir, filename)
                try:
                    os.remove(filepath)
                except:
                    pass
    except:
        pass


class UpdateWindow:
    """Janela de progresso para update."""

    def __init__(self, local_ver, remote_ver):
        self.root = tk.Tk()
        self.root.title("Atualizando")
        self.root.geometry("300x120")
        self.root.resizable(False, False)
        self.root.configure(bg="#1a1a1a")
        self.root.protocol("WM_DELETE_WINDOW", lambda: None)  # Impede fechar

        # Centraliza na tela
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        x = (screen_width // 2) - 150
        y = (screen_height // 2) - 60
        self.root.geometry(f"300x120+{x}+{y}")

        # Estilo
        style = ttk.Style()
        style.theme_use('clam')
        style.configure("dark.Horizontal.TProgressbar",
                       background="#3B8ED0",
                       troughcolor="#333333")

        # Título
        title = tk.Label(
            self.root,
            text=f"Atualizando v{local_ver} -> v{remote_ver}",
            font=("Verdana", 10, "bold"),
            bg="#1a1a1a",
            fg="#3B8ED0"
        )
        title.pack(pady=(15, 5))

        # Status
        self.lbl_status = tk.Label(
            self.root,
            text="Baixando...",
            font=("Verdana", 9),
            bg="#1a1a1a",
            fg="#CCCCCC"
        )
        self.lbl_status.pack(pady=5)

        # Barra de progresso
        self.progress = ttk.Progressbar(
            self.root,
            style="dark.Horizontal.TProgressbar",
            length=250,
            mode='determinate'
        )
        self.progress.pack(pady=10)

        self.root.update()

    def update_progress(self, percent, status=None):
        """Atualiza barra de progresso (thread-safe)."""
        def _update():
            self.progress['value'] = percent
            if status:
                self.lbl_status.config(text=status)
        self.root.after(0, _update)

    def close(self):
        """Fecha a janela."""
        self.root.after(0, self.root.destroy)

    def mainloop(self):
        self.root.mainloop()


def get_local_version():
    """Retorna versão hardcoded (não manipulável pelo usuário)."""
    return CURRENT_VERSION


def get_remote_version():
    """Retorna versão remota ou None se falhar."""
    try:
        import requests
        response = requests.get(URL_VERSION, timeout=10)
        if response.status_code == 200:
            return response.text.strip()
    except:
        pass
    return None


def needs_update():
    """Verifica se precisa atualizar."""
    try:
        from packaging import version
        local = get_local_version()
        remote = get_remote_version()
        if remote and version.parse(remote) > version.parse(local):
            return local, remote
    except:
        pass
    return None


def download_with_progress(url, dest_path, progress_callback):
    """Baixa arquivo com callback de progresso."""
    import requests

    response = requests.get(url, stream=True, timeout=120)
    response.raise_for_status()

    total = response.headers.get('content-length')
    downloaded = 0

    with open(dest_path, 'wb') as f:
        if total is None:
            f.write(response.content)
            progress_callback(100)
        else:
            total = int(total)
            for chunk in response.iter_content(chunk_size=131072):
                downloaded += len(chunk)
                f.write(chunk)
                percent = (downloaded / total) * 100
                progress_callback(percent)


def apply_update(new_exe_path):
    """Cria script .bat para trocar executáveis e reiniciar."""
    current_exe = os.path.abspath(sys.executable)
    new_exe = os.path.abspath(new_exe_path)
    pid = os.getpid()

    # Script mais robusto:
    # 1. Mata o processo pelo PID
    # 2. Espera e tenta deletar várias vezes
    # 3. Move o novo exe
    # 4. Inicia o novo exe
    bat_content = f'''@echo off
:: Espera inicial
timeout /t 1 /nobreak >nul

:: Mata o processo se ainda estiver rodando
taskkill /PID {pid} /F >nul 2>&1
timeout /t 2 /nobreak >nul

:: Tenta deletar o exe antigo (com retry)
:retry_delete
del /f "{current_exe}" >nul 2>&1
if exist "{current_exe}" (
    timeout /t 1 /nobreak >nul
    goto retry_delete
)

:: Move o novo exe
move /y "{new_exe}" "{current_exe}" >nul 2>&1

:: Verifica se moveu corretamente
if not exist "{current_exe}" (
    :: Se falhou, tenta copiar
    copy /y "{new_exe}" "{current_exe}" >nul 2>&1
    del /f "{new_exe}" >nul 2>&1
)

:: Inicia o novo exe
timeout /t 1 /nobreak >nul
start "" "{current_exe}"

:: Deleta este script
del "%~f0"
'''

    bat_path = os.path.join(tempfile.gettempdir(), "molodoy_update.bat")
    with open(bat_path, 'w') as f:
        f.write(bat_content)

    # Executa o bat e fecha imediatamente
    subprocess.Popen(
        ['cmd', '/c', bat_path],
        creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS,
        close_fds=True
    )

    # Força saída imediata
    os._exit(0)


def run_update(local_ver, remote_ver):
    """Executa o processo de update com UI."""
    window = UpdateWindow(local_ver, remote_ver)

    def do_update():
        try:
            new_exe = EXE_NAME + ".new"

            # Download com progresso
            def on_progress(percent):
                window.update_progress(percent, f"Baixando... {int(percent)}%")

            download_with_progress(URL_EXE, new_exe, on_progress)

            window.update_progress(100, "Aplicando...")
            window.root.after(500, lambda: apply_update(new_exe))

        except Exception as e:
            window.update_progress(0, f"Erro: {e}")
            window.root.after(3000, window.close)

    # Inicia download em thread separada
    thread = threading.Thread(target=do_update, daemon=True)
    thread.start()

    window.mainloop()


def check_and_update():
    """
    Verifica e aplica update se necessário.
    Retorna True se vai reiniciar (não continuar execução).
    """
    # Só checa update se rodando como .exe compilado
    if not getattr(sys, 'frozen', False):
        return False

    # Remove arquivos legados do launcher antigo
    cleanup_legacy_files()

    # Limpa arquivo .new de update anterior interrompido
    new_file = EXE_NAME + ".new"
    if os.path.exists(new_file):
        try:
            os.remove(new_file)
        except:
            pass

    result = needs_update()
    if result:
        local_ver, remote_ver = result
        run_update(local_ver, remote_ver)
        return True  # Nunca chega aqui pois run_update faz sys.exit

    return False
