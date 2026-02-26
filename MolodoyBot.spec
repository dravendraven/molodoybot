# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all
import re

# Lê versão do version.txt
with open('version.txt', 'r') as f:
    VERSION = f.read().strip()

# Atualiza CURRENT_VERSION em auto_update.py automaticamente
with open('auto_update.py', 'r', encoding='utf-8') as f:
    content = f.read()
updated = re.sub(r'CURRENT_VERSION = "[^"]*"', f'CURRENT_VERSION = "{VERSION}"', content)
if updated != content:
    with open('auto_update.py', 'w', encoding='utf-8') as f:
        f.write(updated)
    print(f"[SPEC] Updated CURRENT_VERSION to {VERSION}")

datas = [
    ('world-spawn.xml', '.'),
    ('archway1.txt', '.'),
    ('archway2.txt', '.'),
    ('archway3.txt', '.'),
    ('archway4.txt', '.'),
    ('floor_transitions.json', '.'),
    ('spawn_graph.json', '.'),
]
binaries = []
hiddenimports = [
    'cryptography',
    'cryptography.fernet',
    'cryptography.hazmat.primitives',
    'cryptography.hazmat.primitives.hashes',
    'cryptography.hazmat.primitives.kdf.pbkdf2',
    'packaging',
    'packaging.version',
    'psutil',
    # pywin32 modules
    'win32gui',
    'win32con',
    'win32api',
    'win32process',
    'pywintypes',
]
tmp_ret = collect_all('customtkinter')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

tmp_ret = collect_all('psutil')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

# pywin32 - necessário para interação com janelas Windows
tmp_ret = collect_all('win32')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

# pywin32 DLLs essenciais (pythoncom e pywintypes)
import os
import sys
site_packages = os.path.join(os.path.dirname(sys.executable), 'Lib', 'site-packages')
pywin32_sys32 = os.path.join(site_packages, 'pywin32_system32')
if os.path.exists(pywin32_sys32):
    for dll in os.listdir(pywin32_sys32):
        if dll.endswith('.dll'):
            binaries.append((os.path.join(pywin32_sys32, dll), '.'))
# win32 .pyd files
win32_path = os.path.join(site_packages, 'win32')
if os.path.exists(win32_path):
    for pyd in os.listdir(win32_path):
        if pyd.endswith('.pyd'):
            binaries.append((os.path.join(win32_path, pyd), 'win32'))

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Libs externas pesadas não utilizadas
        'numpy', 'pandas', 'scipy', 'sklearn', 'matplotlib',
        'torch', 'tensorflow', 'keras', 'cv2',
        # Módulos de teste
        'unittest', 'pytest', 'nose',
        # Servidores não usados
        'http.server', 'xmlrpc', 'ftplib',
        # Debug/docs
        'pydoc', 'pdb',
        # Ferramentas do desenvolvedor (NAO incluir no build)
        'tools', 'tools.whitelist_manager',
    ],
    noarchive=False,
    optimize=2,
)
pyz = PYZ(a.pure)

# Remove dados pesados e desnecessários
a.datas = [x for x in a.datas if 'tzdata' not in x[0] and 'zoneinfo' not in x[0] and 'matplotlib' not in x[0]]

# Splash screen nativo do PyInstaller
splash = Splash(
    'splash.png',
    binaries=a.binaries,
    datas=a.datas,
    text_pos=(10, 180),
    text_size=10,
    text_color='#3B8ED0',
    minify_script=True,
    always_on_top=True,
)

exe = EXE(
    pyz,
    a.scripts,
    splash,
    splash.binaries,
    a.binaries,
    a.datas,
    [],
    name='MolodoyBot',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['app.ico'],
)
