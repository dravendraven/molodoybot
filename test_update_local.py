"""
Script para testar o processo de update localmente.
Simula o que acontece quando um usuário com versão antiga atualiza.

Como usar:
1. Compile a versão atual: pyinstaller MolodoyBot.spec
2. Copie dist/MolodoyBot.exe para uma pasta de teste (ex: C:\teste\)
3. Execute este script - ele vai iniciar um servidor HTTP local
4. O script também vai criar um version.txt local com versão maior
5. Modifique temporariamente as URLs no auto_update.py para localhost
6. Rode o MolodoyBot.exe da pasta de teste - ele deve atualizar do servidor local
"""

import http.server
import socketserver
import os
import threading
import shutil

# Configurações
PORT = 8888
DIST_FOLDER = "dist"
TEST_VERSION = "99.0"  # Versão alta para forçar update

def setup_local_server():
    """Configura e inicia servidor HTTP local."""

    # Cria version.txt com versão alta
    version_path = os.path.join(DIST_FOLDER, "version.txt")
    with open(version_path, 'w') as f:
        f.write(TEST_VERSION)
    print(f"[OK] Criado {version_path} com versão {TEST_VERSION}")

    # Verifica se o exe existe
    exe_path = os.path.join(DIST_FOLDER, "MolodoyBot.exe")
    if not os.path.exists(exe_path):
        print(f"[ERRO] {exe_path} não encontrado!")
        print("Compile primeiro com: pyinstaller MolodoyBot.spec")
        return

    print(f"[OK] Encontrado {exe_path}")

    # Inicia servidor HTTP
    os.chdir(DIST_FOLDER)
    handler = http.server.SimpleHTTPRequestHandler

    with socketserver.TCPServer(("", PORT), handler) as httpd:
        print(f"\n{'='*50}")
        print(f"SERVIDOR LOCAL INICIADO")
        print(f"{'='*50}")
        print(f"URL versão:  http://localhost:{PORT}/version.txt")
        print(f"URL exe:     http://localhost:{PORT}/MolodoyBot.exe")
        print(f"\nPara testar:")
        print(f"1. Modifique auto_update.py:")
        print(f'   URL_VERSION = "http://localhost:{PORT}/version.txt"')
        print(f'   URL_EXE = "http://localhost:{PORT}/MolodoyBot.exe"')
        print(f"2. Compile novamente com versão menor (ex: 1.0)")
        print(f"3. Copie o .exe para outra pasta e execute")
        print(f"4. Ele deve detectar update e baixar do servidor local")
        print(f"\nPressione Ctrl+C para parar o servidor")
        print(f"{'='*50}\n")

        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nServidor encerrado.")

if __name__ == "__main__":
    setup_local_server()
