# Development guide

[Documentation home](../README.md)

## Environment setup

Run commands from the repository root. Install the GUI and test dependencies:

```powershell
python -m pip install -r requirements.txt
python Code/gui/app.py
```

`requirements.txt` includes NumPy, PySide6, Matplotlib, COMPAS, compas_viewer,
and pytest. STEP import also needs a compatible `compas_occ`, `pythonocc-core`,
and OpenCASCADE installation; these are optional comments in the requirements,
not packages installed by that command. The requirements suggest conda-forge
for the CAD backend. Use mutually compatible backend binaries and interpreter.

`setup.py` declares Python 3.11+ and installs a `tolforge` console entry point.
Its dependency list currently includes only NumPy, PySide6, and Matplotlib:
installing the package alone does not supply all GUI dependencies. An editable
installation on a compatible interpreter is `python -m pip install -e .`.

The configured local source environment uses Python 3.10 at
`D:\PROGRAMS\PYTHON\python.exe`, while VS Code opens
`D:\GIT\REPOS\TolForge\Code\gui\app.py`. This source execution works in
that environment but differs from the package's Python 3.11+ metadata.
Reconcile and test the environment before changing interpreter or packaging.
`app.py` also conditionally registers machine-specific OCCT, FreeType, and
Tcl/Tk DLL directories under `D:\GIT\REPOS`; other installations must provide
their own compatible DLL search configuration.

## Architecture

| Area | Responsibility |
|---|---|
| `Code/tolstack/models.py`, `stack.py` | Dimensions, result objects, Worst Case/RSS/Monte Carlo |
| `Code/tolstack/project.py` | Versioned engineering definitions and validation |
| `Code/tolstack/features.py` | Persistent geometric signatures and matching |
| `Code/tolstack/gdt.py` | Plane/axis frames, position/size checks, mating boundaries |
| `Code/gui/app.py`, `theme.py` | Window construction, workspace navigation, shared styling |
| `Code/gui/step_load_worker.py`, `step_viewer_mixin.py` | STEP loading, analytic face metadata, scene/pick integration |
| `Code/gui/step_renderer.py` | Viewport rendering and interaction |
| `Code/gui/measurement_mixin.py` | Sampled measurements and measurement previews |
| `Code/gui/offset_preview.py`, `stack_link_mixin.py` | Shared offset controls/layers and linked stack previews |
| `Code/gui/gdt_mixin.py`, `datum_inspection.py` | Datum/pattern editing and inspection graphics |
| `Code/gui/project_mixin.py` | UI/domain bridge, saving, opening, geometry reattachment |
| `Code/gui/analysis_mixin.py`, `dimension_bank_mixin.py` | Stack analysis and reusable templates |

Keep domain data independent of Qt, scene objects, and OCCT wrappers. Read
[engineering-domain.md](engineering-domain.md) before changing persistence and
[gdt-semantics.md](gdt-semantics.md) before changing frame or acceptance logic.

Analytic surface dictionaries travel from `StepLoadResult.face_surfaces` to
entity `info["surface"]`. A plane/cylinder has a point and direction; a cylinder
also has a radius. `other` and `unknown` distinguish unsupported geometry from
recognition failure. GUI datum extraction uses this metadata; ordinary sampled
measurements and normal-offset translations remain separate operations.

## Verification

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
python -m pytest tests -q
python Code/examples/basic_usage.py
```

Tests cover stacks, project validation/round trips, GUI bridging, workspace
layout, theme/icons, shared previews, datum inspection, and cylindrical datum
recognition. Backend-dependent tests may skip if CAD dependencies are missing;
inspect the test summary. Headless/fake-renderer tests do not prove native
OpenGL rendering works.

For changes affecting 3D behavior, also verify in a native GUI session:

1. Load a STEP with planar and cylindrical faces; exercise pick filters and
   the context menu. Check the viewport remains visible after picking.
2. Compare measurement and stack surface offsets at nominal, both bounds,
   asymmetric tolerances, and reversed direction. Check Show limits and cleanup.
3. Assign A/B/C, inspect colored geometry/labels, build a frame, and confirm
   origin/axes. Reassign/clear a datum and check that the old frame disappears.
4. Use a rotated or partial cylindrical face as a datum; check its axis and
   reject unsupported/underconstrained frame combinations with a clear message.
5. Save/reopen a complete project, reload its STEP, inspect reattached links,
   and clear the model to check annotation/resource cleanup.

The native startup path constructs COMPAS `Viewer()` before reusing its
`QApplication`. A custom smoke harness that creates another application first
can fail viewer initialization; follow `main()` when testing the real renderer.

## Packaging

The configured PyInstaller spec includes the GD&T asset directory:

```powershell
python -m pip install pyinstaller
python -m PyInstaller --clean --noconfirm TolForge.spec
```

The output is `dist/TolForge.exe`. Build using an environment with the required
runtime dependencies, then verify the executable independently of source.
`build_installer.ps1` invokes PyInstaller directly with one-file/windowed flags;
it does not use the spec's explicit asset configuration. Prefer the spec when
checking the configured packaged assets.

The GitHub Actions build runs on Windows with Python 3.11, installs
`requirements.txt`, builds the spec, and attaches the executable on a published
release. It does not install the optional CAD backend or run the test suite.
A successful build alone does not establish working STEP import on another PC.

## Troubleshooting

- **Edits are missing:** verify the script path and selected VS Code interpreter.
  Restart the process. A source change does not rebuild an existing executable.
- **STEP backend/DLL import fails:** check dependencies in the interpreter that
  starts the app, plus the compatible native libraries and DLL directories.
- **New recognition is missing:** restart and reload STEP to populate fresh
  analytic metadata. Old scene entities do not acquire it automatically.
- **Datum frame cannot build:** check the supported combinations, perpendicular
  plane/axis relationship, and a tertiary feature that resolves rotation.
- **Saved feature is unresolved:** inspect the source CAD path and relink the
  feature. Signatures are geometric heuristics, not permanent topology IDs.
- **Headless test passes but native rendering fails:** use the native checklist;
  renderer initialization, graphics drivers, and resource cleanup need a real
  viewport check.
