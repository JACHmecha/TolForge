# TolForge

A tolerance stack-up analysis tool with a PySide6 desktop GUI, including an
embedded 3D STEP file viewer (via COMPAS / OpenCASCADE) with face, edge, and
vertex selection.

## Features

- **Tolerance stack-up analysis** (`tolstack` package): Worst Case, RSS
  (Root Sum Square), and Monte Carlo methods, with optional per-dimension
  Cpk (process capability) modeling.
- **Dimension bank**: reusable dimension templates that can be saved,
  loaded from JSON, and pulled into different stack analyses without
  retyping their values.
- **Interactive results**: a draggable-interval histogram for Monte Carlo
  results, showing in-range/out-of-range percentages live as you drag.
- **STEP file 3D viewer**: load a `.step`/`.stp` file and view it in an
  embedded, interactive 3D viewport - rotate, pan, zoom, and click to
  select individual faces, edges, or vertices.

## Project structure

```
Code/
  main.py                     Minimal CLI entry point / quick example
  tolstack/                   Core calculation package (no GUI dependency)
    models.py                 Dimension, StackResult, MonteCarloResult, FitAssessment
    stack.py                  Stack class: worst_case(), rss(), monte_carlo()
    bank.py                   DimensionBank / DimensionTemplate (JSON persistence)
  gui/                        PySide6 desktop application
    app.py                    Window layout + main() entry point
    step_renderer.py          Embedded 3D viewport widget (rotate/pan/zoom/select)
    step_viewer_mixin.py      STEP loading, 3D preview, entity selection logic
    dimension_bank_mixin.py   Dimension table + bank UI logic
    analysis_mixin.py         Stack analysis + histogram UI logic
  examples/
    basic_usage.py            tolstack package usage without the GUI
tests/
  test_stack.py                Tests for the tolstack calculation package
  test_step_viewer.py          Tests for STEP backend detection
```

The GUI is split into focused files rather than one large module:
`TolstackWindow` (in `app.py`) combines three mixins
(`StepViewerMixin`, `DimensionBankMixin`, `AnalysisMixin`), each of which
assumes certain widgets already exist on `self` - see each mixin's
docstring for exactly which ones.

## Requirements

### Base (tolstack calculations + GUI, no 3D viewer)

- Python 3.10+
- PySide6
- numpy
- matplotlib

```bash
pip install PySide6 numpy matplotlib
```

This is enough to run the dimension table, dimension bank, and analysis
features. The STEP preview panel will show a message explaining that the
3D backend isn't available, but everything else works normally.

### STEP 3D viewer (compas_occ / compas_viewer)

This is the more demanding part of the stack, and it comes with a real
constraint:

> **compas_viewer is not compatible with Python 3.14** (or newer). Its
> `Config` class breaks under Python 3.14's new lazy annotation evaluation
> (PEP 649). **Use Python 3.10, 3.11, or 3.12** for this part.

**Recommended: conda-forge** (by far the simplest path - gets you
precompiled `pythonocc-core` without building OpenCASCADE from source):

```bash
conda install -c conda-forge compas compas_occ compas_viewer pythonocc-core
```

**Alternative: build from source**, if you can't use conda. This is a
substantially more involved process - broad strokes:

1. Build OpenCASCADE (OCCT) from source with a matching MSVC toolset
   (Windows) or your platform's equivalent, using OCCT's official
   `3rdparty` dependency bundle (FreeType, TCL/TK, RapidJSON, etc.)
2. Build `pythonocc-core` from source (via CMake + SWIG) against that
   OCCT build, targeting your Python 3.10/3.11/3.12 interpreter
   specifically - the compiled `.pyd`/`.so` files are tied to that exact
   Python ABI
3. `pip install compas compas_viewer` (pure Python, no build needed)
4. `pip install git+https://github.com/compas-dev/compas_occ.git`
   (`compas_occ` is not currently published on PyPI under either
   `compas_occ` or `compas-occ` - install from source)

If you go this route on Windows and Python can't find OCCT's DLLs at
import time (`DLL load failed`), note that Python 3.8+ no longer searches
`PATH` for a C-extension's dependency DLLs - you need
`os.add_dll_directory(...)` pointing at OCCT's `bin` folder (and, for STEP
reading specifically, FreeType's and TCL/TK's `bin` folders too - `OCC.Core.STEPControl`
transitively needs them even though basic modules like `OCC.Core.gp` don't).
See the top of `gui/app.py` for exactly where this goes; the hardcoded
paths there are specific to one development machine and will need
updating for any other setup.

## Usage

### Running the GUI

```bash
python Code/gui/app.py
```

Requires whichever Python interpreter has the dependencies above
installed - if you built the STEP viewer stack against a specific Python
install (e.g. Python 3.10), make sure you run `app.py` with that same
interpreter, not whatever `python` resolves to by default.

### STEP viewer controls

| Action | Control |
|---|---|
| Rotate | Left-click + drag |
| Pan | Right-click + drag, or Shift + left-click + drag |
| Zoom | Scroll wheel |
| Select a face / edge / vertex | Left-click (without dragging) |

Selecting an entity shows its type and index in the status label above
the viewport. Loading a new STEP file replaces the current geometry; use
**Clear** to empty the viewport without loading a new file.

### Using `tolstack` without the GUI

```python
from tolstack import Stack, Dimension

stack = Stack()
stack.add_dimension(Dimension(name="Base", nominal=25.0, tol_plus=0.10, tol_minus=0.05, sign="+"))
stack.add_dimension(Dimension(name="Spacer", nominal=12.5, tol_plus=0.05, tol_minus=0.05, sign="+"))
stack.add_dimension(Dimension(name="Bearing", nominal=40.0, tol_plus=0.20, tol_minus=0.10, sign="-"))

stack.summary(method="monte_carlo")
```

See `Code/examples/basic_usage.py` for a runnable version, and
`Code/main.py` for the minimal quick-start.

`Dimension.cpk` is optional: leave it as `None` for uniform sampling
(the most pessimistic assumption for Monte Carlo) or set it to a target
process capability (e.g. `1.33`) to sample from a split-normal
distribution instead.

The dimension bank (`DimensionBank`/`DimensionTemplate`) intentionally
does not store a sign - the same physical part can be `+` in one stack
and `-` in another, depending on how it's used in that particular chain.

## Testing

```bash
pip install pytest
QT_QPA_PLATFORM=offscreen python -m pytest tests/ -q
```

`QT_QPA_PLATFORM=offscreen` lets the Qt-dependent tests run headless
(e.g. in CI or over SSH) without a real display.

## Known limitations

- The DLL directory paths in `gui/app.py` (for the from-source OCCT build)
  are hardcoded to one development machine. If you're not using the
  conda-forge install path, update these to match your own OCCT/3rdparty
  install locations.
- `compas_viewer`'s scene is a singleton shared across every `Renderer`
  widget in the process (tied to its `Viewer` singleton) - the STEP viewer
  code explicitly clears stale scene objects on each load to avoid
  accumulating geometry from previously-loaded files.
- Large STEP files with many faces/edges/vertices create a scene object
  per topological entity (needed for individual selection), which may be
  slower to load than a single merged mesh for very complex parts.
