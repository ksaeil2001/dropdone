# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

a = Analysis(
    ['app/main.py'],
    pathex=['.'],
    binaries=[],
    datas=[
        ('app/dashboard/static',          'app/dashboard/static'),
        ('app/dashboard/onboarding.html', 'app/dashboard'),
        ('assets/icon.ico',               'assets'),
        ('extension',                     'extension'),
        ('native_host',                   'native_host'),
    ],
    hiddenimports=[
        'pystray._win32',
        'plyer.platforms.win.notification',
        'winotify',
        'app.utils.notifier',
        'app.native_host_runtime',
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        'numpy', 'numpy._core', 'numpy.lib', 'numpy.linalg',
        'pandas', 'scipy', 'matplotlib',
        'PIL.ImageTk', 'PIL.ImageQt',
        'tkinter', '_tkinter', 'wx', 'PyQt5', 'PyQt6',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# onedir: exe에는 scripts만, 나머지는 COLLECT가 폴더로 배치
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,   # onedir 핵심 — COLLECT가 DLL/데이터 담당
    name='DropDone',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    console=False,
    icon='assets/icon.ico',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='DropDone',  # → dist/DropDone/ 폴더 생성
)
