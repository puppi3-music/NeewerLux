# -*- mode: python ; coding: utf-8 -*-
# Puppi3Lux PyInstaller spec file
# Build with:  pyinstaller Puppi3Lux.spec
# Produces, on the OS it is run on (PyInstaller can't cross-compile):
#   Windows: dist/Puppi3Lux/Puppi3Lux.exe   (--onedir, no console)
#   Linux:   dist/Puppi3Lux/Puppi3Lux       (--onedir)
#   macOS:   dist/Puppi3Lux.app                    (app bundle, for the CPU of the build machine)
# On Windows and Linux the release workflow copies light_prefs/ next to the program. The macOS app carries
# it inside the bundle and copies it to ~/Library/Application Support/Puppi3Lux on first launch.

import os
import re
import sys
from PyInstaller.utils.hooks import collect_all

block_cipher = None
APP_ID = 'io.github.puppi3_music.Puppi3Lux'

with open('Puppi3Lux.py', encoding='utf-8') as f:
    VERSION = re.search(r'^PUPPI3LUX_VERSION = "([^"]+)"', f.read(), re.M).group(1)

# Collect all bleak subpackages/data (the WinRT, CoreBluetooth and BlueZ backends)
bleak_datas, bleak_binaries, bleak_hiddenimports = collect_all('bleak')

if sys.platform == 'win32':
    bleak_backend = ['bleak.backends.winrt']
elif sys.platform == 'darwin':
    bleak_backend = ['bleak.backends.corebluetooth']
else:
    bleak_backend = ['bleak.backends.bluezdbus']

datas = [
    (APP_ID + '.ico', '.'),
    (APP_ID + '.png', '.'),
    ('LICENSE', '.'),
    ('LICENSE-MIT', '.'),
]
if sys.platform == 'darwin':
    datas += [
        ('light_prefs/animations', 'light_prefs/animations'),
        ('light_prefs/customLights.prefs.default', 'light_prefs'),
        ('light_prefs/sound_presets.json.default', 'light_prefs'),
    ]

# The release workflow makes the .icns from the .png on macOS (sips + iconutil)
if sys.platform == 'darwin':
    icon = APP_ID + '.icns' if os.path.exists(APP_ID + '.icns') else None
else:
    icon = APP_ID + '.ico'

a = Analysis(
    ['Puppi3Lux.py'],
    pathex=[],
    binaries=bleak_binaries,
    datas=datas + bleak_datas,
    hiddenimports=[
        'bleak',
        'puppi3lux_ui',
        'puppi3lux_theme',
        'puppi3lux_webui',
        'puppi3lux_anim_editor',
        'puppi3lux_audio',
        'sounddevice',
        'puppi3lux_midi',
        'puppi3lux_nanoleaf',
        'rtmidi',
        'numpy',
        'PySide6',
        'PySide6.QtWidgets',
        'PySide6.QtCore',
        'PySide6.QtGui',
        'PySide6.QtSvg',
    ] + bleak_backend + bleak_hiddenimports,
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
    name='Puppi3Lux',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=sys.platform == 'win32',  # UPX breaks Qt libraries on Linux and code signatures on macOS
    console=False,           # windowed GUI app, no console (on Linux, run it from a terminal to see the log)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=sys.platform == 'win32',
    upx_exclude=[],
    name='Puppi3Lux',
)

if sys.platform == 'darwin':
    app = BUNDLE(
        coll,
        name='Puppi3Lux.app',
        icon=icon,
        bundle_identifier=APP_ID,
        version=VERSION,
        info_plist={
            'CFBundleName': 'Puppi3Lux',
            'CFBundleDisplayName': "Puppi3Lux",
            'CFBundleShortVersionString': VERSION,
            'CFBundleVersion': VERSION,
            'NSHighResolutionCapable': True,
            'LSMinimumSystemVersion': '11.0',
            # Without these, macOS refuses (or kills the app on) Bluetooth, microphone and local network access
            'NSBluetoothAlwaysUsageDescription': "Puppi3Lux uses Bluetooth to control your Neewer lights.",
            'NSMicrophoneUsageDescription': "Puppi3Lux listens to an audio input to drive the lights in Sound mode.",
            'NSLocalNetworkUsageDescription': "Puppi3Lux finds and controls Nanoleaf panels on your network, and serves its web dashboard.",
        },
    )
