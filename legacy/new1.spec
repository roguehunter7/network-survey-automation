# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import copy_metadata

datas = [('<PATH_TO_PYTHON_SITE_PACKAGES>/ntc_templates/templates', 'ntc_templates/templates'), ('data', 'data')]
datas += copy_metadata('ntc-templates')
datas += copy_metadata('importlib-metadata')


a = Analysis(
    ['new1.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=['ntc_templates.parse', 'serial.tools.list_ports', 'config', 'data_manager', 'utils'],
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
    a.binaries,
    a.datas,
    [],
    name='new1',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
