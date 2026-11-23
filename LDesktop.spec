# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_all

sd_datas, sd_binaries, sd_hiddenimports = collect_all(
    "_sounddevice_data"
)

a = Analysis(
    ['src/main.py'],
    pathex=['src'],
    binaries=[
        ('bin/ffmpeg.exe', 'bin'),
        ('bin/ffprobe.exe', 'bin'),
        *sd_binaries,
    ],
    datas=[
        ('assets', 'assets'),
        *sd_datas,
    ],
    hiddenimports=[
        'sounddevice',
        '_sounddevice_data',
        *sd_hiddenimports,
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='LDesktop',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='assets/icon.ico'
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='LDesktop',
)