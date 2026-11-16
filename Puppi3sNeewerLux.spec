# -*- mode: python ; coding: utf-8 -*-
# Puppi3's NeewerLux PyInstaller spec file
# Build with:  pyinstaller Puppi3sNeewerLux.spec
# Produces:    dist/Puppi3sNeewerLux/  (--onedir mode)

import sys
from PyInstaller.utils.hooks import collect_all

block_cipher = None

# Collect all bleak subpackages/data (WinRT backends, etc.)
bleak_datas, bleak_binaries, bleak_hiddenimports = collect_all('bleak')

a = Analysis(
    ['Puppi3sNeewerLux.py'],
    pathex=[],
    binaries=bleak_binaries,
    datas=[
        ('io.github.puppi3_music.Puppi3sNeewerLux.ico', '.'),
        ('io.github.puppi3_music.Puppi3sNeewerLux.png', '.'),
        ('LICENSE', '.'),
        ('LICENSE-MIT', '.'),
    ] + bleak_datas,
    hiddenimports=[
        'bleak',
        'bleak.backends.winrt',
        'puppi3s_neewerlux_ui',
        'puppi3s_neewerlux_theme',
        'puppi3s_neewerlux_webui',
        'puppi3s_neewerlux_anim_editor',
        'puppi3s_neewerlux_audio',
        'sounddevice',
        'puppi3s_neewerlux_midi',
        'puppi3s_neewerlux_nanoleaf',
        'rtmidi',
        'numpy',
        'PySide6',
        'PySide6.QtWidgets',
        'PySide6.QtCore',
        'PySide6.QtGui',
        'PySide6.QtSvg',
    ] + bleak_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Puppi3sNeewerLux',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,           # windowed GUI app, no console
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='io.github.puppi3_music.Puppi3sNeewerLux.ico',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Puppi3sNeewerLux',
)
