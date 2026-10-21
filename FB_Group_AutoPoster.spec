# -*- mode: python ; coding: utf-8 -*-

import os
import sys
from PyInstaller.utils.hooks import collect_data_files

block_cipher = None

datas = []
# Collect Playwright driver files
datas += collect_data_files('playwright')

# Add app_data.db if exists
if os.path.exists('app_data.db'):
    datas.append(('app_data.db', '.'))

hiddenimports = [
    'PySide6.QtCore',
    'PySide6.QtGui',
    'PySide6.QtWidgets',
    'playwright',
    'playwright.async_api',
    'playwright.sync_api',
    'playwright._impl._driver',
    'requests',
    'sqlite3',
    'asyncio',
    'json',
    're',
    'core',
    'core.anti_spam',
    'core.database',
    'core.fb_automation',
    'core.spintax_parser',
    'ui',
    'ui.main_window',
    'ui.account_tab',
    'ui.group_tab',
    'ui.content_tab',
    'ui.poster_tab',
    'ui.system_tray',
    'ui.floating_widget',
]

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
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
    name='FB_Group_AutoPoster',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # GUI mode
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='FB_Group_AutoPoster',
)
