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
CURRENT_VERSION = "7.7"

# URLs do GitHub
URL_VERSION = "https://raw.githubusercontent.com/dravendraven/molodoybot/refs/heads/main/version.txt"
URL_EXE = "https://github.com/dravendraven/molodoybot/releases/download/latest/MolodoyBot.exe"
EXE_NAME = "MolodoyBot.exe"

# Arquivos legados a serem removidos (migração do launcher antigo)
LEGACY_FILES = ["MolodoyLauncher.exe", "version.txt"]
# =================================================


def cleanup_legacy_files():
    """Remove arquivos do sistema antigo (launcher) para forçar uso do auto-update."""
    import time

    # Pequeno delay para garantir que o launcher já fechou
    time.sleep(0.5)

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

    # Verifica se o arquivo baixado existe e tem tamanho razoável (> 1MB)
    if not os.path.exists(new_exe_path):
        return
    if os.path.getsize(new_exe_path) < 1_000_000:  # Menos de 1MB = corrompido
        os.remove(new_exe_path)
        return

    # Validate the downloaded file is a valid PE executable (MZ header)
    try:
        with open(new_exe_path, 'rb') as f:
            if f.read(2) != b'MZ':
                os.remove(new_exe_path)
                return
    except (IOError, OSError):
        try:
            os.remove(new_exe_path)
        except:
            pass
        return

    # Cria arquivo HTA para splash durante update
    hta_path = os.path.join(tempfile.gettempdir(), "molodoy_splash.hta")
    hta_content = '''<html>
<head>
<meta http-equiv="Content-Type" content="text/html; charset=utf-8">
<title>MolodoyBot</title>
<HTA:APPLICATION
    ID="MoloDoySplash"
    APPLICATIONNAME="MolodoyBot Update"
    BORDER="none"
    BORDERSTYLE="none"
    CAPTION="no"
    SHOWINTASKBAR="no"
    SINGLEINSTANCE="yes"
    SYSMENU="no"
    WINDOWSTATE="normal"
    SCROLL="no"
/>
<style>
body {
    margin: 0;
    padding: 0;
    background: #1a1a1a;
    display: flex;
    justify-content: center;
    align-items: center;
    height: 100%;
    font-family: Verdana, sans-serif;
}
.container {
    text-align: center;
    color: #3B8ED0;
}
.title {
    font-size: 16px;
    font-weight: bold;
    margin-bottom: 10px;
}
.status {
    font-size: 12px;
    color: #CCCCCC;
}
.dots {
    display: inline-block;
    width: 20px;
    text-align: left;
}
</style>
<script>
window.resizeTo(280, 100);
var w = (screen.width - 280) / 2;
var h = (screen.height - 100) / 2;
window.moveTo(w, h);

var dots = 0;
setInterval(function() {
    dots = (dots + 1) % 4;
    var d = "";
    for (var i = 0; i < dots; i++) d += ".";
    document.getElementById("dots").innerText = d;
}, 400);
</script>
</head>
<body>
<div class="container">
    <div class="title">MolodoyBot</div>
    <div class="status">Finalizando atualizacao<span id="dots" class="dots"></span></div>
</div>
</body>
</html>'''

    with open(hta_path, 'w', encoding='utf-8-sig') as f:
        f.write(hta_content)

    # Script batch otimizado com splash
    bat_content = f'''@echo off
:: Inicia splash screen
start "" mshta.exe "{hta_path}"
ping 127.0.0.1 -n 2 >nul

:: Espera processo fechar (3 segundos)
ping 127.0.0.1 -n 4 >nul

:: Mata o processo
taskkill /PID {pid} /F >nul 2>&1
ping 127.0.0.1 -n 2 >nul

:: Mata QUALQUER instância do MolodoyBot
taskkill /IM MolodoyBot.exe /F >nul 2>&1
ping 127.0.0.1 -n 2 >nul

:: Verifica se o arquivo novo existe
if not exist "{new_exe}" (
    taskkill /IM mshta.exe /F >nul 2>&1
    exit /b 1
)

:: Tenta deletar o exe antigo (max 5 tentativas)
set retry=0
:retry_delete
set /a retry+=1
if %retry% gtr 5 goto force_rename
del /f /q "{current_exe}" >nul 2>&1
if exist "{current_exe}" (
    ping 127.0.0.1 -n 2 >nul
    goto retry_delete
)
goto do_move

:force_rename
ren "{current_exe}" "MolodoyBot_old.exe" >nul 2>&1

:do_move
move /y "{new_exe}" "{current_exe}" >nul 2>&1

:: Verifica se moveu corretamente
if not exist "{current_exe}" (
    taskkill /IM mshta.exe /F >nul 2>&1
    exit /b 1
)

:: Deleta o arquivo antigo renomeado
del /f /q "{os.path.dirname(current_exe)}\\MolodoyBot_old.exe" >nul 2>&1

:: Fecha splash screen
taskkill /IM mshta.exe /F >nul 2>&1

:: Limpa pastas _MEI orfas (evita erro "Failed to load Python DLL")
for /d %%i in ("%TEMP%\\_MEI*") do rd /s /q "%%i" 2>nul

:: Espera breve antes de iniciar (1 segundo)
ping 127.0.0.1 -n 2 >nul

:: Inicia o novo exe
explorer.exe "{current_exe}"

:: Limpa arquivos temporários
del /f /q "{hta_path}" >nul 2>&1
ping 127.0.0.1 -n 2 >nul
del "%~f0"
'''

    bat_path = os.path.join(tempfile.gettempdir(), "molodoy_update.bat")
    with open(bat_path, 'w') as f:
        f.write(bat_content)

    # Usa VBScript para executar o .bat completamente invisível
    vbs_content = f'CreateObject("Wscript.Shell").Run "cmd /c ""{bat_path}""", 0, False'
    vbs_path = os.path.join(tempfile.gettempdir(), "molodoy_update.vbs")
    with open(vbs_path, 'w') as f:
        f.write(vbs_content)

    # Cria marcador para evitar loop de update
    marker_file = os.path.join(tempfile.gettempdir(), "molodoy_update_done.txt")
    with open(marker_file, 'w') as f:
        f.write("update")

    # Executa o VBScript (que executa o .bat invisível)
    subprocess.Popen(
        ['wscript', vbs_path],
        creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # Shut down cleanly so PyInstaller bootloader can clean up _MEI folder
    sys.exit(0)


def run_update(local_ver, remote_ver):
    """Executa o processo de update com UI."""
    # Fecha splash nativo do PyInstaller (se existir) para não cobrir a GUI de update
    try:
        import pyi_splash
        pyi_splash.close()
    except ImportError:
        pass

    window = UpdateWindow(local_ver, remote_ver)

    def do_update():
        try:
            # Baixa para o mesmo diretório do exe atual (NÃO o diretório de trabalho!)
            exe_dir = os.path.dirname(os.path.abspath(sys.executable))
            new_exe = os.path.join(exe_dir, EXE_NAME + ".new")

            # Download com progresso
            def on_progress(percent):
                window.update_progress(percent, f"Baixando... {int(percent)}%")

            download_with_progress(URL_EXE, new_exe, on_progress)

            # Verifica se o download foi bem-sucedido (arquivo > 1MB)
            if not os.path.exists(new_exe) or os.path.getsize(new_exe) < 1_000_000:
                raise Exception("Download incompleto")

            window.update_progress(100, "Aplicando...")
            window.root.after(1000, lambda: apply_update(new_exe))

        except Exception as e:
            window.update_progress(0, f"Erro: {e}")
            window.root.after(3000, window.close)

    # Inicia download em thread separada
    thread = threading.Thread(target=do_update, daemon=True)
    thread.start()

    window.mainloop()


def cleanup_stale_mei_folders():
    """
    Remove orphaned _MEI folders from TEMP that don't belong to running processes.
    PyInstaller --onefile creates _MEI{pid} folders; if the process exits uncleanly
    (e.g., os._exit), these folders are left behind and can cause conflicts via PID reuse.
    """
    import glob
    import re

    temp_dir = tempfile.gettempdir()
    mei_pattern = os.path.join(temp_dir, '_MEI*')

    current_pid = os.getpid()

    for mei_path in glob.glob(mei_pattern):
        folder_name = os.path.basename(mei_path)
        match = re.match(r'_MEI(\d+)', folder_name)
        if not match:
            continue

        mei_pid = int(match.group(1))

        # Don't delete our own _MEI folder
        if mei_pid == current_pid:
            continue

        # Check if a process with this PID is still running
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, mei_pid)
            if handle:
                kernel32.CloseHandle(handle)
                continue  # Process exists, skip this folder
        except:
            pass

        # Process doesn't exist, safe to remove the orphaned folder
        try:
            import shutil
            shutil.rmtree(mei_path, ignore_errors=True)
        except:
            pass


def check_and_update():
    """
    Verifica e aplica update se necessário.
    Retorna True se vai reiniciar (não continuar execução).
    """
    # Só checa update se rodando como .exe compilado
    if not getattr(sys, 'frozen', False):
        return False

    # Verifica se update acabou de acontecer (evita loop)
    marker_file = os.path.join(tempfile.gettempdir(), "molodoy_update_done.txt")
    if os.path.exists(marker_file):
        try:
            # Se marcador tem menos de 60 segundos, pula update
            import time
            age = time.time() - os.path.getmtime(marker_file)
            if age < 60:
                os.remove(marker_file)
                return False  # Pula update, acabou de atualizar
            os.remove(marker_file)
        except:
            pass

    # Limpa pastas _MEI órfãs (evita erro "Failed to load Python DLL")
    cleanup_stale_mei_folders()

    # Remove arquivos legados do launcher antigo
    cleanup_legacy_files()

    # Remove cópias duplicadas do exe
    cleanup_duplicate_exes()

    # Limpa arquivo .new de update anterior interrompido
    exe_dir = os.path.dirname(os.path.abspath(sys.executable))
    new_file = os.path.join(exe_dir, EXE_NAME + ".new")
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
