# -*- mode: python ; coding: utf-8 -*-

import os
import sys
from PyInstaller.utils.hooks import collect_data_files

block_cipher = None

datas = []
# Thu thập tài nguyên Playwright
datas += collect_data_files('playwright')

# Thu thập icon và tài nguyên assets
if os.path.exists('assets'):
    datas.append(('assets', 'assets'))

# Thêm app_data.db nếu có sẵn
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
    'PIL',
    'PIL.Image',
    'core',
    'core.anti_spam',
    'core.database',
    'core.fb_automation',
    'core.threads_automation',
    'core.license_manager',
    'core.spintax_parser',
    'ui',
    'ui.main_window',
    'ui.account_tab',
    'ui.group_tab',
    'ui.content_tab',
    'ui.poster_tab',
    'ui.threads_account_tab',
    'ui.threads_poster_tab',
    'ui.system_tray',
    'ui.floating_widget',
    'ui.license_dialog',
]

excludes = [
    'numpy',
    'numpy.libs',
    'scipy',
    'matplotlib',
    'pandas',
    'IPython',
    'jupyter',
    'tkinter',
    'unittest',
    'pydoc',
    'pydoc_data',
    'test',
    'distutils',
    'setuptools',
    'xmlrpc',
    'email.test',
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
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

# Loại bỏ các thư viện đồ họa & module Qt cồng kềnh không dùng tới để giảm mạnh dung lượng
excluded_binaries = {
    'opengl32sw.dll',
    'qt6quick.dll',
    'qt6qml.dll',
    'qt6pdf.dll',
    'qt6pdfwidgets.dll',
    'qt6virtualkeyboard.dll',
    'qt6qmlmodels.dll',
    'qt6quickwidgets.dll',
    'qt6networkauth.dll',
    'qt6designer.dll',
    'qt6help.dll',
    'qt6multimedia.dll',
    'qt6multimediawidgets.dll',
    'qt6spatialaudio.dll',
}

filtered_binaries = []
for b in a.binaries:
    base_name = os.path.basename(b[0]).lower()
    if base_name in excluded_binaries:
        continue
    filtered_binaries.append(b)
a.binaries = filtered_binaries

# Lọc bỏ các gói dịch ngôn ngữ Qt không cần thiết (.qm)
filtered_datas = []
for d in a.datas:
    dest = d[0].lower()
    if 'translations' in dest and dest.endswith('.qm') and not ('qt_en' in dest or 'qtbase_en' in dest):
        continue
    filtered_datas.append(d)
a.datas = filtered_datas

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Auto Post',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # Không hiện màn hình đen console
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.abspath('assets/icon.ico') if os.path.exists('assets/icon.ico') else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Auto Post',
)
