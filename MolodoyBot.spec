# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all
# from PyInstaller.building.splash import Splash  # Desabilitado - causa erro DLL

# Lê versão do version.txt
with open('version.txt', 'r') as f:
    VERSION = f.read().strip()

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
]
tmp_ret = collect_all('customtkinter')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

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

# Splash screen nativa DESABILITADA - causa erro "Failed to load Python DLL"
# O fallback tkinter em main.py será usado automaticamente

exe = EXE(
    pyz,
    a.scripts,
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
