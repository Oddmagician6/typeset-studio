# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build spec for Typeset Studio (onedir).

Build:   pyinstaller typeset-studio.spec --noconfirm --clean
Output:  dist/Typeset Studio/  →  run "Typeset Studio.exe"

Notes
-----
* onedir (not onefile): faster startup, and it avoids onefile's temp-extraction
  issues with the app's bundled data.
* The app loads read-only assets via app.resource_path(), which resolves against
  sys._MEIPASS when frozen — so templates/, sample/, and the *default*
  presets/covers/fonts must land in the bundle at those same relative paths.
  Writable copies are seeded into %APPDATA%\\Typeset Studio on first run.
* pyphen (hyphenation dictionaries) and reportlab (fonts/encodings) ship data
  files that must be collected explicitly or the frozen app breaks.
* anthropic is an optional lazy import (continuity checker tier-2). It is
  excluded to drop a large dependency chain (httpx/pydantic); the app degrades
  gracefully with a "not installed" note if a user sets an API key.
"""

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

datas = [
    ('templates', 'templates'),
    ('sample', 'sample'),
    ('presets', 'presets'),
    ('covers', 'covers'),
    ('fonts', 'fonts'),
]
datas += collect_data_files('pyphen')       # hyphenation dictionaries
datas += collect_data_files('reportlab')    # bundled fonts / encodings
datas += collect_data_files('webview')      # pywebview backend assets (native window)

hiddenimports = collect_submodules('reportlab')
hiddenimports += collect_submodules('webview')

excludes = ['anthropic', 'tkinter']

a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Typeset Studio',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,            # keeps a "close this window to quit" console; set False once pywebview lands
    disable_windowed_traceback=False,
    icon='app.ico',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name='Typeset Studio',
)
