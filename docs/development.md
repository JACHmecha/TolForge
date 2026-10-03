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

Builds retain `dist/source-provenance.json` with the source commit, branch,
working-tree state, and CAD profile alongside `packaged-smoke.json`,
`pip-freeze.txt`, and `SHA256.txt`. A dirty working tree is recorded explicitly;
its commit alone does not identify the uncommitted contents. Build release
artifacts from a clean reviewed revision and keep all evidence with that exact
executable. The executable hash identifies the artifact. Source smoke reports
and an old `dist` executable are not interchangeable release evidence.

`app.py` calls `gui.runtime.configure_native_runtime()` before CAD imports.
Configure compatible libraries locally; workstation paths are not embedded in
the application.

### Native CAD configuration

On Windows, choose one of these configuration sources, in priority order:

1. `TOLFORGE_DLL_DIRS`, a semicolon-separated list of absolute DLL directories.
2. `%LOCALAPPDATA%\TolForge\runtime.json`.
3. `.tolforge/runtime.json` in the source checkout, when the per-user file is
   absent. This private directory is ignored by Git. Frozen executables do not
   use the checkout fallback.

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

Use the build script for dependency installation, tests, the configured
PyInstaller spec, and a frozen executable smoke check:

```powershell
.\build_installer.ps1
```

The default profile builds the GUI/scalar application and excludes the optional
`compas_occ`/`OCC` backend. For a STEP-capable artifact, first prepare a mutually
compatible native CAD environment, then select its explicit profile:

```powershell
.\build_installer.ps1 -IncludeCad
```

`-SkipDependencyInstall` reuses an already prepared environment. `-IncludeCad`
sets `TOLFORGE_BUILD_CAD=1` for the spec to collect the installed CAD packages;
it does not install or qualify a CAD environment. A direct spec build uses the
same environment switch. The spec bundles COMPAS viewer resources and GD&T SVG
assets in both profiles.

Output includes `dist/TolForge.exe`, `source-provenance.json`,
`packaged-smoke.json`, `pip-freeze.txt`, and `SHA256.txt`. The script runs tests
before building, then invokes the frozen
executable with `--self-check-json <path>` to check numerical/GUI imports, a
known scalar clearance, and bundled SVGs. The CAD profile additionally passes
`--self-check-cad` to check a generated cylinder's STEP round trip and analytic
recognition. Keep this evidence with the built executable. A build/smoke pass
does not qualify native OpenGL behavior or a clean target machine; exercise the
native verification checklist and target installation separately.

GitHub Actions uses the shared Windows headless checks for Python 3.10 and 3.12,
followed by the default pip-only build on Python 3.12. The workflow preserves the
executable and evidence and uploads them on a published release. The separate
source-CAD workflow does not build a CAD executable. These are configured checks,
not a claim that a new release, native viewport, or clean-machine artifact has
been qualified.

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
