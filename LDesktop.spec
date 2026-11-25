# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_all

from pathlib import Path
from PySide6.QtCore import QLibraryInfo

qt_multimedia_plugin_dir = (
    Path(QLibraryInfo.path(QLibraryInfo.LibraryPath.PluginsPath))
    / "multimedia"
)

qt_multimedia_binaries = [
    (str(plugin), "PySide6/plugins/multimedia")
    for plugin in sorted(qt_multimedia_plugin_dir.glob("*.dll"))
]

if not qt_multimedia_binaries:
    raise RuntimeError(
        f"Plugins Qt Multimedia n?o encontrados em: {qt_multimedia_plugin_dir}"
    )

sd_datas, sd_binaries, sd_hiddenimports = collect_all(
    "_sounddevice_data"
)

livekit_datas, livekit_binaries, livekit_hiddenimports = collect_all(
    "livekit"
)

wgc_datas, wgc_binaries, wgc_hiddenimports = collect_all(
    "windows_capture"
)

a = Analysis(
    ['src/main.py'],
    pathex=['src'],
    binaries=[
        ('bin/ffmpeg.exe', 'bin'),
        ('bin/ffprobe.exe', 'bin'),
        ('bin/LiveAudioCapture/LiveAudioCapture.exe', 'LiveAudioCapture'),
        *sd_binaries,
        *livekit_binaries,
        *wgc_binaries,
        *qt_multimedia_binaries,
    ],
    datas=[
        ('assets', 'assets'),
        *sd_datas,
        *livekit_datas,
        *wgc_datas,
    ],
    hiddenimports=[
        'sounddevice',
        'PySide6.QtMultimedia',
        'PySide6.QtMultimediaWidgets',
        '_sounddevice_data',
        *sd_hiddenimports,
        *livekit_hiddenimports,
        *wgc_hiddenimports,
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