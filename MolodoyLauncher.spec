# -*- mode: python ; coding: utf-8 -*-

# Launcher otimizado - sem customtkinter (usa tkinter puro)
a = Analysis(
    ['launcher.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Libs externas pesadas (100% seguro excluir)
        'numpy', 'pandas', 'PIL', 'matplotlib', 'scipy', 'cv2',
        'torch', 'tensorflow', 'keras', 'sklearn',
        # Módulos de teste
        'unittest', 'pytest', 'nose',
        # Servidores (não usados)
        'http.server', 'xmlrpc', 'ftplib',
        # Debug/docs
        'pydoc', 'pdb',
    ],
    noarchive=False,
    optimize=2,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='MolodoyLauncher',
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
