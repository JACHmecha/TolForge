# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
import os
import json
import sys
from PyInstaller.utils.hooks import collect_all, collect_data_files, copy_metadata

root = Path(SPECPATH)
viewer_datas, viewer_binaries, viewer_hiddenimports = collect_all('compas_viewer')
include_cad = os.environ.get('TOLFORGE_BUILD_CAD') == '1'
metadata_path = Path(os.environ.get('TOLFORGE_BUILD_METADATA', ''))
if not metadata_path.is_file():
    raise RuntimeError('Use build_installer.ps1: a prepared, verified build manifest is required.')
metadata = json.loads(metadata_path.read_text(encoding='utf-8'))
profile = 'cad' if include_cad else 'scalar'
if metadata.get('profile') != profile:
    raise RuntimeError('The prepared build manifest does not match the package profile.')
cad_datas, cad_binaries, cad_hiddenimports = [], [], []
native_manifest = None

def is_private_icu(name):
    name = Path(name).name.lower()
    return name in ('icuuc.dll', 'icuin.dll') or (name.startswith('icudt') and name.endswith('.dll'))

if include_cad:
    for package in ('compas_occ', 'OCC'):
        datas, binaries, imports = collect_all(package)
        cad_datas.extend(datas)
        cad_binaries.extend(binaries)
        cad_hiddenimports.extend(imports)
    native_manifest = json.loads((metadata_path.parent / 'native-dependencies.json').read_text(encoding='utf-8'))
    if any(is_private_icu(item['bundle_path']) for item in native_manifest['native_binaries']):
        raise RuntimeError('The CAD import closure requires a private ICU ABI; qualify a compatible environment before packaging.')
    cad_datas.append((str(metadata_path.parent / 'native-dependencies.json'), '.'))
    for binary in native_manifest['native_binaries']:
        source = Path(sys.prefix) / binary['path']
        if not source.is_file() or not source.resolve().is_relative_to(Path(sys.prefix).resolve()):
            raise RuntimeError('A verified native DLL is missing from the selected CAD interpreter.')
        cad_binaries.append((str(source), '.'))
package_metadata = []
for package in ('numpy', 'matplotlib', 'PySide6', 'compas', 'compas_viewer', 'freetype-py', 'PyOpenGL') + (('compas_occ',) if include_cad else ()):
    package_metadata.extend(copy_metadata(package, recursive=True))
# Optional OCCT needs a separately qualified CAD environment. Do not absorb
# a workstation's native CAD installation accidentally during a build.
a = Analysis(
    [str(root / 'Code' / 'gui' / 'app.py')],
    pathex=[str(root / 'Code')],
    binaries=viewer_binaries + cad_binaries,
    datas=viewer_datas + cad_datas + package_metadata + collect_data_files('compas') + [
        (str(metadata_path), '.'),
        (str(root / 'Code' / 'gui' / 'assets' / 'branding' / 'tolforge-logo-v1.png'), 'gui/assets/branding'),
        (str(root / 'Code' / 'gui' / 'assets' / 'icons' / 'gdt'), 'gui/assets/icons/gdt'),
    ],
    hiddenimports=viewer_hiddenimports + cad_hiddenimports + ['PySide6.QtSvg'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[str(root / 'scripts' / 'pyinstaller_runtime_hook.py')],
    # pythonocc's generated config may contain its compiler's OCCT path. The
    # frozen runtime registers the bundle directory before importing OCC.
    excludes=(['OCC.config'] if include_cad else ['compas_occ', 'OCC']) + ['PyQt5', 'PyQt6', 'PySide2'],
    noarchive=False,
    optimize=0,
)
# Qt 6.11 imports the unversioned Windows ICU API. A conda private ICU DLL
# has versioned exports and must not replace this Windows OS component.
# The CAD closure above must prove it does not require those private DLLs.
a.binaries = [entry for entry in a.binaries if not is_private_icu(entry[0])]
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
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
