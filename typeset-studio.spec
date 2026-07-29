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
* PyInstaller cannot cross-compile: a Windows build must be made on Windows, a
  .app on a Mac, a Linux build on Linux. The platform branches below are so the
  same spec *runs* on all three rather than stopping on a Windows-only detail —
  the Windows path is the one that has actually been built and shipped; the mac
  and Linux paths have not, and want a real build day (see ROADMAP).
"""

import os
import re
import sys

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

IS_WIN = sys.platform == 'win32'
IS_MAC = sys.platform == 'darwin'

# The version lives in typeset-studio.iss and nowhere else; make-installer.bat
# reads it the same way. A Mac bundle carries it in its Info.plist, so read it
# here too rather than adding a second place to forget to bump.
try:
    _iss = open('typeset-studio.iss', encoding='utf-8').read()
    APP_VERSION = re.search(r'#define AppVersion "([^"]+)"', _iss).group(1)
except Exception:
    APP_VERSION = '0.0.0'

datas = [
    ('templates', 'templates'),
    ('static', 'static'),
    ('sample', 'sample'),
    ('presets', 'presets'),
    ('covers', 'covers'),
    ('fonts', 'fonts'),
    ('app.ico', '.'),
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
    console=False,           # windowed app — the pywebview window is the whole UI, no console box
    disable_windowed_traceback=False,
    # .ico is a Windows format: PyInstaller wants .icns on a Mac and ignores the
    # icon on Linux, so naming it unconditionally would fail a Mac build on a
    # detail that has nothing to do with the app. Drop an app.icns beside app.ico
    # to give the Mac build its icon.
    icon=('app.ico' if IS_WIN else
          ('app.icns' if IS_MAC and os.path.exists('app.icns') else None)),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name='Typeset Studio',
)

if IS_MAC:
    # A Mac wants a .app bundle, not a bare folder of binaries — this is what
    # `hdiutil` then wraps into a .dmg. Untested: it needs a Mac to run on.
    app = BUNDLE(
        coll,
        name='Typeset Studio.app',
        icon='app.icns' if os.path.exists('app.icns') else None,
        bundle_identifier='com.ashforge.typesetstudio',
        info_plist={
            'NSHighResolutionCapable': True,
            'CFBundleShortVersionString': APP_VERSION,
            'CFBundleVersion': APP_VERSION,
        },
    )
