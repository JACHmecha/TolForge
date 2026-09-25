# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
import os
from PyInstaller.utils.hooks import collect_all, collect_data_files

root = Path(SPECPATH)
viewer_datas, viewer_binaries, viewer_hiddenimports = collect_all('compas_viewer')
include_cad = os.environ.get('TOLFORGE_BUILD_CAD') == '1'
cad_datas, cad_binaries, cad_hiddenimports = [], [], []
if include_cad:
    for package in ('compas_occ', 'OCC'):
        datas, binaries, imports = collect_all(package)
        cad_datas.extend(datas)
        cad_binaries.extend(binaries)
        cad_hiddenimports.extend(imports)
# Optional OCCT needs a separately qualified CAD environment. Do not absorb
# a workstation's native CAD installation accidentally during a build.
a = Analysis(
    [str(root / 'Code' / 'gui' / 'app.py')],
    pathex=[str(root / 'Code')],
    binaries=viewer_binaries + cad_binaries,
    datas=viewer_datas + cad_datas + collect_data_files('compas') + [
        (str(root / 'Code' / 'gui' / 'assets' / 'icons' / 'gdt'), 'gui/assets/icons/gdt'),
    ],
    hiddenimports=viewer_hiddenimports + cad_hiddenimports + ['PySide6.QtSvg'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=([] if include_cad else ['compas_occ', 'OCC']) + ['PyQt5', 'PyQt6', 'PySide2'],
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
    name='TolForge',
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
