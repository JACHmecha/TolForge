# Development guide

[Documentation home](../README.md)

## Environment setup

Run commands from the primary Git repository root. Install the GUI and test dependencies:

```powershell
python -m pip install -r requirements.txt
.\launch.ps1
```

`requirements.txt` includes NumPy, PySide6, Matplotlib, COMPAS, compas_viewer,
and pytest. STEP import also needs a compatible `compas_occ`, `pythonocc-core`,
and OpenCASCADE installation; these are optional comments in the requirements,
not packages installed by that command. The requirements suggest conda-forge
for the CAD backend. Use mutually compatible backend binaries and interpreter.

`setup.py` declares Python 3.10+ and a `tolforge` GUI entry point. Package
dependencies include NumPy, PySide6, Matplotlib, COMPAS, and compas_viewer, with
compatible version ranges. Use `python -m pip install -e '.[dev]'` for an editable
development installation. `requirements.txt` pins the direct dependency baseline;
a build's `pip-freeze.txt` records the resolved transitive environment. It is not
a universal lockfile for every platform or native CAD backend.

### Source provenance and project memory

The selected primary checkout on this workstation is `D:\GIT\REPOS\TolForge`.
The earlier `D:\TolForge` source workspace is preserved. Do not synchronize it
over the Git checkout; its external `MEMORY` folder remains the selected vault.
The four guides were reconciled against the current committed source, retaining
the Study/service/model boundaries, P0 validation/precision changes, and native
runtime recovery behavior.

`launch.ps1` resolves `Code/gui/app.py` relative to its own location, switches to
that checkout while running, and prints the source/interpreter paths. Use
`-Python <interpreter>` for a prepared environment. To run a bounded source smoke
without opening a window:

```powershell
.\launch.ps1 -SelfCheckJson source-smoke.json
.\launch.ps1 -SelfCheckJson source-cad-smoke.json -IncludeCad
```

The CAD check is explicit and fails when its required backend cannot load. Its
generated STEP check does not establish native viewport or clean-machine
qualification. Relative report paths resolve against the calling directory.

PMC project ID `tolforge` maps the primary Git checkout to the existing external
vault through `%LOCALAPPDATA%\ProjectMemory\config.json`. Keep repository and
vault paths in that machine-local registration. `AGENTS.md` loads the vault's
orientation notes by project ID; the vault is a separate secondary source folder
and is not duplicated into this checkout. Keep durable code references relative
to logical repository `tolforge`. The dated backlog remains historical evidence;
subsequent implementation updates distinguish committed work from local edits
and leave unselected recommendations proposed.

Builds retain a separate `dist/scalar` or `dist/cad` package. Its
`build-provenance.json` records the source commit, branch, dirty state, per-file
hashes and aggregate source hash. `tolforge-build.json` is embedded in the
executable and retained beside it. `SHA256.json` identifies the executable and
all evidence files. Build from a clean reviewed revision for distribution;
dirty builds explicitly identify their actual source contents. Keep evidence
with its exact executable. An old top-level `dist/TolForge.exe` is historical.

`app.py` calls `gui.runtime.configure_native_runtime()` before CAD imports.
Configure compatible libraries locally; workstation paths are not embedded in
the application.

### Native CAD configuration

On Windows, choose one of these configuration sources, in priority order:

1. `TOLFORGE_DLL_DIRS`, a semicolon-separated list of absolute DLL directories.
2. `%LOCALAPPDATA%\TolForge\runtime.json`.
3. `.tolforge/runtime.json` in the source checkout, when the per-user file is
   absent. This private directory is ignored by Git. Frozen executables use
   bundled libraries only and ignore all source configuration mechanisms,
   including environment, per-user and active Conda DLL directories.

Either JSON file uses this structure; replace the example paths with the
compatible native libraries installed on your machine:

```json
{
  "dll_directories": [
    "C:/CAD/OCCT/bin",
    "C:/CAD/FreeType/bin",
    "C:/CAD/TclTk/bin"
  ]
}
```

An active conda environment also contributes its `Library/bin` directory.
An existing malformed per-user file produces a warning and retains its
priority; repair that file rather than expecting the checkout fallback.

Load STEP refreshes the configuration before checking the reader. After adding
missing DLL directories, retry Load STEP. Existing registered DLL directories
and loaded libraries stay active for the process lifetime; restart after
removing paths or replacing incompatible native binaries.

On a reader import failure, the dialog identifies the interpreter, configuration
source and registered directory count. The app also attempts to save
`%LOCALAPPDATA%\TolForge\native-runtime-diagnostics.json`, containing selected
runtime paths and loaded native modules. A diagnostic write failure preserves
the original reader error.

Packaged tools can redirect AppData writes. When configuring a source checkout
from such a tool, verify which file the external launcher can actually see;
the private checkout file avoids this ambiguity.

## Architecture

| Area | Responsibility |
|---|---|
| `Code/tolstack/models.py`, `stack.py` | Dimensions, result objects, Worst Case/RSS/Monte Carlo |
| `Code/tolstack/analysis.py` | Input/settings validation, scalar orchestration, functional acceptance, contributions, report snapshots |
| `Code/tolstack/inspection.py`, `workflow.py` | Measured size/position evaluation, study validation, CAD readiness findings |
| `Code/tolstack/project.py` | Versioned engineering definitions and validation |
| `Code/tolstack/features.py` | Persistent geometric signatures and matching |
| `Code/tolstack/gdt.py` | Plane/axis frames, position/size checks, mating boundaries |
| `Code/gui/app.py`, `theme.py` | Window construction, workspace navigation, shared styling |
| `Code/gui/stack_table.py` | Stack `QAbstractTableModel` / `QTableView`, roles and compatibility facade |
| `Code/gui/study_mixin.py` | Study editor, measured-data CSV import, JSON report export, study persistence bridge |
| `Code/gui/step_load_worker.py`, `step_viewer_mixin.py` | STEP loading, analytic face metadata, scene/pick integration |
| `Code/gui/step_renderer.py` | Viewport rendering and interaction |
| `Code/gui/viewport_adapter.py` | Scene operations, selection, refresh, and managed GL context boundary |
| `Code/gui/runtime.py` | Portable native DLL registration and packaged executable smoke check |
| `Code/gui/measurement_mixin.py` | Sampled measurements and measurement previews |
| `Code/gui/offset_preview.py`, `stack_link_mixin.py` | Shared offset controls/layers and linked stack previews |
| `Code/gui/gdt_mixin.py`, `datum_inspection.py` | Datum/pattern editing and inspection graphics |
| `Code/gui/project_mixin.py` | UI/domain bridge, saving, opening, geometry reattachment |
| `Code/tolstack/relinking.py`, `Code/gui/feature_relinking.py` | Candidate diagnostics, revision acceptance and stable-ID manual relinking |
| `Code/tolstack/inspection_import.py`, `Code/gui/inspection_import_dialog.py` | Captured CSV mapping/validation and review before dataset mutation |
| `Code/gui/analysis_mixin.py`, `dimension_bank_mixin.py` | Analysis-service presentation and reusable templates |

Keep domain data independent of Qt, scene objects, and OCCT wrappers. Read
[engineering-domain.md](engineering-domain.md) before changing persistence and
[gdt-semantics.md](gdt-semantics.md) before changing frame or acceptance logic.

PySide6/Qt Widgets remains the desktop framework. The first separation step is
service-based numerical analysis, a model/view stack table, and an explicit
viewport boundary. Legacy GUI mixins remain; this is not a full application-wide
rewrite. New numerical logic should accept domain/plain values and return
validated results rather than reading widgets or mutating renderer state.

Analytic surface dictionaries travel from `StepLoadResult.face_surfaces` to
entity `info["surface"]`. A plane/cylinder has a point and direction; a cylinder
also has a radius. `other` and `unknown` distinguish unsupported geometry from
recognition failure. GUI datum extraction uses this metadata; ordinary sampled
measurements and normal-offset translations remain separate operations.

STEP cancellation uses a thread-safe event plus checkpoints around source
hashing, native read, grouping and geometry extraction. The native call itself
is not interrupted. A generation-tagged terminal payload and stage/progress
updates arrive through queued bound GUI slots; stale generations cannot commit
a scene. The worker remains owned until terminal handling and actual thread
completion, including a nonblocking join check for native thread teardown.
Close defers destruction while ownership remains. Scene commits run on the GUI
thread without unrestricted event processing inside the commit.

## Verification

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
python -m pytest tests -q
python Code/examples/basic_usage.py
```

Tests cover scalar services, acceptance/contribution calculations, measured
inspection, study persistence, stack model/view behavior, runtime configuration,
viewport operations, project bridging, and existing geometry/UI behavior.
Run the CI headless selection explicitly when native CAD is outside the intended
coverage:

```powershell
python -m pytest tests -q -m "not native_cad" --strict-markers
```

The ordinary full suite can visibly skip the four native geometry cases when
the backend is absent or broken. A required native qualification must instead
prove backend availability and fail on skipped or unselected native tests:

```powershell
python -m pytest tests -q -m native_cad --require-native-cad --strict-markers
```

`.github/workflows/test.yml` runs the headless selection on pull requests and
main-branch pushes with Windows Python 3.10 and 3.12. The release workflow calls
the same checks before building. `.github/workflows/native-cad.yml` is an
explicit, manually dispatched source-CAD qualification job; its
`.github/environments/native-cad.yml` declares conda-forge Python 3.12 and
pythonocc-core 7.9.3, with compas_occ 1.5.0 installed alongside the declared
desktop requirements. The job preserves revision, dependency manifests, JUnit
results, and source smoke evidence. Headless/fake-renderer tests and native STEP
round trips do not prove native OpenGL rendering works.

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

For the study/report path, enter one measured feature with a hand-checkable
position error, verify size and position margins, then edit an input and confirm
the prior report is invalidated. Import a valid CSV and an invalid/duplicate-name
CSV, verify append behavior, save/reopen the Study, and export the refreshed
report. For scalar analysis, compare repeated seeded runs and reassess the same
samples with changed acceptance limits.

Exercise lifecycle guards with Save, Discard and Cancel, including a canceled
Save As and a failed/invalid save. Recovery drafts use raw input text and IDs
without result/status columns; verify incomplete stack/control rows, partial
datums and unresolved geometry survive recovery and source reattachment.
Automatic drafts use ignored `.tolforge/drafts` for source runs and per-user
app data for frozen runs. Draft recovery is distinct from validated `.bak`
project recovery. Close during a STEP read defers destruction until the worker
finishes and disables editing after the close choice.

For loader/relink/import changes, cancel a slow load, Clear and select another
source, and close while native reading is pending. Verify stale results cannot
change the scene and edits made during an initial project load survive. Inspect
saved versus loaded source hashes, require changed-revision acceptance, assign
an ambiguous feature explicitly, and rebuild the frame. Open with a missing CAD
source and confirm saved pattern rows/IDs remain visible. Preview mapped CSV
columns/constants, test a bad row beyond the preview limit, cancel, and verify
unit/frame relabeling cannot convert imported coordinates. The corresponding
regressions are `test_step_cancellation.py`, `test_relinking.py`,
`test_feature_relinking_gui.py`, `test_inspection_import.py`,
`test_inspection_import_gui.py` and `test_selected_workflows_integration.py`.

For coverage, record position and unsupported profile requests, multiple
specifications on one measurement, absent links and differing datum references.
Verify every requested control appears without a whole-drawing pass claim.
For evidence, change a source after import/evaluation, check captured hashes
and explicit mismatch/unavailability, mutate caller inputs, and verify previous
exports remain unchanged. Acceptance-bound reassessment creates new IDs without
resampling or rehashing original sources. `tests/test_project_lifecycle.py`,
`test_drawing_characteristics.py`, `test_drawing_controls_gui.py`,
`test_report_evidence.py` and `test_report_gui_traceability.py` cover these paths.

The native startup path constructs COMPAS `Viewer()` before reusing its
`QApplication`. A custom smoke harness that creates another application first
can fail viewer initialization; follow `main()` when testing the real renderer.

## Packaging

Release builds use Windows x64 Python **3.12.15** and the complete SHA256-pinned
desktop/build/test dependency closure in
`.github/environments/windows-release-py312.lock`. Source development retains
the Python 3.10+ support boundary. Select the prepared interpreter explicitly:

```powershell
conda create -n tolforge-scalar --file .github/environments/scalar-win-64.conda.lock
conda activate tolforge-scalar
.\build_installer.ps1 -Python "$env:CONDA_PREFIX\python.exe"
```

The default scalar profile excludes `compas_occ` and `OCC`. Prepare the CAD
profile from the platform-specific explicit archive lock, which pins Python,
OCC/OCCT **7.9.3**, its `novtk` variant and the complete native dependency set.
The YAML recipe describes how to regenerate that lock; builds consume the lock.

```powershell
conda create -n tolforge-cad --file .github/environments/native-cad-win-64.conda.lock
conda activate tolforge-cad
.\build_installer.ps1 -Python "$env:CONDA_PREFIX\python.exe" -IncludeCad
```

The script installs hash-locked Python archives, verifies all pinned versions,
runs the relevant strict test suite, collects the OCC PE import closure from
that exact prefix and records native DLL/extension hashes. The CAD wrapper is
the official `compas_occ` 1.5.0 source revision recorded in
`windows-cad-py312.lock`, rather than an unavailable PyPI requirement.
`-SkipDependencyInstall` still validates the complete environment and origin.
The spec requires prepared metadata, excludes workstation OCC configuration,
includes distribution metadata and disables UPX. Both profiles include the
COMPAS resources and 24 GD&T SVGs. Source changes during a build fail the gate.
Windows ICU is selected explicitly before Qt imports. Conda's versioned ICU
exports are incompatible with Qt's Windows ICU interface despite sharing DLL
names. Source startup, build subprocesses and frozen startup use Windows ICU;
installed native packages are preserved. Diagnostics record the selected paths.

Outputs include `TolForge.exe`, both provenance records, `packaged-smoke.json`,
`pip-freeze.txt`, the dependency locks, `tests.xml` and `SHA256.json`. CAD also
includes `native-dependencies.json`, the native explicit lock and reproducible
STEP fixtures. Each build uses fresh staging and preserves an earlier completed
profile before replacement. A failed build cannot publish partial new files.
Frozen checks require the exact profile and reject missing or substituted CAD
libraries, externally imported modules and borrowed native DLLs. A successful
build establishes a local frozen check, with its scope recorded in the report.
The injected Windows Defender `MpOAV.dll` is accepted only from the OS-resolved
Defender directory after offline Windows signature and Microsoft publisher
verification. Its path, hash and signer are recorded separately.

The target verifier needs only Windows and PowerShell. It checks all package
hashes and native manifest bindings to embedded build metadata, records its own
script hash, copies only the executable to a detached directory, clears Python,
Conda, Qt and CAD overrides and uses fresh user configuration and a minimal
Windows PATH. CAD requires real native rendering, GPU picking and camera
controls, preserving a screenshot, driver versions, loaded DLL hashes and STEP
fixtures. An unavailable native context fails; offscreen Qt is rejected.
The CAD viewport requires a desktop OpenGL 3.3 driver. Qt's bundled older
software OpenGL library is not a qualified substitute for COMPAS/PyOpenGL.

```powershell
.\scripts\verify_windows_package.ps1 -PackageDirectory dist\scalar -Profile scalar -OutputDirectory .tolforge\scalar-target-check
.\scripts\verify_windows_package.ps1 -PackageDirectory dist\cad -Profile cad -OutputDirectory .tolforge\cad-target-check
# Source native viewport check, using its configured source CAD environment:
.\launch.ps1 -SelfCheckJson .tolforge\source-viewport.json -IncludeCad -QualifyViewport
```

Choose a new output directory for each target run. Local isolated execution
records `isolated-workstation`, without claiming a fresh machine.
`build-release.yml` builds both profiles, then downloads their artifacts to
different fresh Windows VMs without checking out source or installing Python
or CAD. Both target checks must pass before release upload. The separate
`native-cad.yml` workflow uses the same locks for required source geometry tests.
Configured workflows are not evidence of a completed hosted run. See
[I08 evidence and limits](implementation-i08-2026-10-08.md) for the actual runs.

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
