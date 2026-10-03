# TolForge

The Study workspace records requested drawing controls and reports their
evaluation coverage, including unsupported callouts. Scalar, inspection and
CAD-position reports retain evaluation-time traceability. Project transitions
guard unsaved changes, and separate recovery drafts preserve incomplete work.
See the [user guide](docs/user-guide.md) and
[implementation evidence](docs/implementation-i05-i12-f01.md).
STEP loads support cancellation and deferred close, saved CAD features have a
guided relinking/revision review, and generic aligned CSV imports support a
mapping preview with measurement provenance. See
[I09/I11/F02 implementation evidence](docs/implementation-i09-i11-f02.md).

TolForge is a desktop application and Python library for mechanical tolerance
stack analysis, STEP inspection, and a limited set of GD&T position checks.
It uses PySide6, NumPy, Matplotlib, COMPAS, and OpenCASCADE.

## Documentation

- [User guide](docs/user-guide.md): workspaces, measurement, surface offsets,
  datums, position patterns, and project files.
- [GD&T semantics](docs/gdt-semantics.md): frame construction, size acceptance,
  material modifiers, and calculation limits.
- [Engineering domain](docs/engineering-domain.md): project schema, geometry
  identity, persistence, and the solver boundary.
- [Development guide](docs/development.md): dependencies, architecture, tests,
  packaging, and troubleshooting.
- [Roadmap](ROADMAP.md): implemented capabilities and remaining work.
- [GD&T icon library](Code/gui/assets/icons/gdt/README.md): asset conventions.

## Current capabilities

- Worst Case, RSS, and seeded Monte Carlo stacks with asymmetric tolerances,
  functional acceptance intervals, variance contributors, and JSON reports.
- Editable stack tables, a reusable dimension bank, and interactive acceptance
  intervals on Monte Carlo histograms.
- STEP viewing with face, edge, vertex, and whole-solid selection, plus
  contextual measurement, datum, pattern, and stack-link actions.
- A resizable viewport and workspace panel, with Inspect, Study, Library, Stack,
  Results, Measure, GD&T, and Eclipse navigation.
- Measured-part Study with drawing/source/alignment references, CSV import,
  per-feature size/position checks, persisted inputs, and report invalidation.
- Live nominal-relative surface previews with numeric/slider controls,
  direction reversal, and lower/upper tolerance layers.
- Color-coded A/B/C datum geometry, labeled axes and origin, and analytic
  recognition of planar and cylindrical STEP faces.
- Limited plane/axis datum frames, position-pattern evaluation, and
  circular-aperture occlusion analysis.
- Versioned project JSON and signature-based geometry reattachment.

## Run from source

The primary source checkout on this workstation is **`D:\GIT\REPOS\TolForge`**.
`D:\TolForge` is the preserved earlier workspace; its `MEMORY` folder remains
the external project vault. Edit, test, launch, and build from the primary Git
checkout. An older source copy or executable does not contain new edits.

Use an interpreter containing the dependencies in [requirements.txt](requirements.txt):

```powershell
python -m pip install -r requirements.txt
.\launch.ps1
```

STEP import additionally requires `compas_occ` and its compatible
`pythonocc-core`/OpenCASCADE runtime. These are not installed by
`requirements.txt`; see [environment setup](docs/development.md#environment-setup).
The GUI imports COMPAS modules even when no STEP file is loaded; installing
only PySide6, NumPy, and Matplotlib is insufficient for the current GUI.

`launch.ps1` always runs the `Code/gui/app.py` beside that script, including when
called from another directory. It prints the source and interpreter paths. The
local CAD-capable interpreter can be selected explicitly:

```powershell
& 'D:\GIT\REPOS\TolForge\launch.ps1' -Python 'D:\PROGRAMS\PYTHON\python.exe'
```

Package metadata requires Python 3.10+. The direct command
`python Code/gui/app.py` also works from the primary root. Restart after source
changes and reload STEP after geometry-recognition changes. Release builds
retain source revision, build profile, dependency and executable-hash evidence;
see [provenance and project memory](docs/development.md#source-provenance-and-project-memory).

## Python library example

From the repository root, run the self-contained example:

```powershell
python Code/examples/basic_usage.py
```

For scripts with `Code` on `PYTHONPATH`, or after package installation:

```python
from tolstack import Dimension, Stack

stack = Stack()
stack.add_dimension(Dimension("Base", 25.0, 0.10, 0.05, "+"))
stack.add_dimension(Dimension("Spacer", 12.5, 0.05, 0.05, "+"))
stack.add_dimension(Dimension("Bearing", 40.0, 0.20, 0.10, "-"))
result = stack.worst_case()
print(result.nominal, result.lower_limit, result.upper_limit)
```

The `tolstack` package has no GUI dependency. The dimension bank stores
unsigned templates; each stack determines its own dimension signs.

## Tests

PowerShell:

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
python -m pytest tests -q
```

POSIX shells:

```bash
QT_QPA_PLATFORM=offscreen python -m pytest tests -q
```

Native 3D verification is separate from headless tests; see the
[verification checklist](docs/development.md#verification).

## Scope

TolForge is not a general 3D assembly/contact solver. Measurements are mostly
mesh-based approximations. Datum cylinder recognition reads analytic STEP
geometry, but does not fit cylinders to spline surfaces. Surface previews
translate geometry; they do not inflate curved surfaces or certify clearance.
Datum mobility, arbitrary skew-axis frames, and general GD&T form/orientation
solvers remain outside the current implementation.

Project units are metadata, not automatic unit conversion. Keep CAD and
numerical inputs consistent; some older measurement displays use fixed mm/deg
labels. See [known limitations](docs/user-guide.md#known-limitations).

## License

Apache-2.0; see [LICENSE](LICENSE).
