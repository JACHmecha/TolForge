# I06, I04 and I07 implementation — 2026-10-02

The user selected these three backlog items. They are implemented in the local
`main` working tree based on `49459f8` (native runtime recovery). The earlier
P0 fixes I01–I03 are in `63eec98`. No commit, merge or release of this work is
asserted. Other backlog recommendations remain proposals.

## I06 — Primary source and provenance

- The selected primary Git checkout is documented in README and the development
  guide. The earlier source workspace is preserved; its existing external
  `MEMORY` vault remains selected, without copying or synchronizing application
  source between folders.
- Machine-local PMC registration now associates logical project `tolforge`
  with the primary checkout and the existing vault. Both source locations have
  orientation guidance. Durable notes use logical and relative code references.
- `launch.ps1` resolves application source against its own script directory,
  supports an explicit Python interpreter, and can run a bounded source smoke.
- The four guides reflect the implemented Study, service, model, packaging,
  P0 validation/precision, and native-runtime recovery boundaries.
- `build_installer.ps1` records source revision, branch, dirty state, build
  start time and CAD profile in `dist/source-provenance.json`. Build workflows
  retain/upload it with smoke evidence, the dependency manifest and executable
  hash. Dirty source is labeled explicitly, not treated as the named commit.

## I04 — Safe saves and previous-version recovery

`tolstack.persistence.save_json()` serializes strict JSON before file access.
New content is written to a uniquely named sibling temporary file, flushed,
synced and closed before replacing the destination. The previous valid file is
staged and replaced atomically as `<filename>.bak` before the destination commit.
Project/bank/annotation backup rotation also checks the domain loader. Corrupt
existing content does not replace a good recovery copy. An unreadable previous
file or a backup/staging/replace failure aborts the save.

Projects, banks, legacy annotations and all Study JSON report exports use this
boundary. Project save success updates the path, title and status only after
the file commit; failed saves restore the previous project object and active
datum/position identities while retaining the user's UI inputs. A retry after
deleting a pattern persists the deletion correctly.

File → **Open Previous Saved Version** opens and validates the project backup
as an unsaved recovered study. It does not rewrite the current saved file.
**Save As** lets the user keep the recovered study. Bank loading accepts
`.json.bak`; library callers can use `Project.load_previous()`,
`DimensionBank.load_previous()` and `AnnotationSet.load_previous()`.
Recovery tracks the loaded source separately from the save destination, so
relocating a missing STEP source preserves the saved part and feature identities.

The backup is one prior valid saved version, not an edit history or draft
recovery feature. Safe replacement is not a lock for concurrent writers or
a guarantee against every filesystem/power-loss failure. I05 remains proposed.

## I07 — Continuous checks and explicit CAD qualification

- `test.yml` runs Windows Python 3.10/3.12 checks on pull requests and main
  pushes, and is reused as the release build gate. It tests scalar/domain and
  offscreen GUI behavior with `native_cad` cases explicitly deselected.
- `native-cad.yml` is a separate manually selected source qualification using
  the versioned conda recipe. Commands explicitly use that named environment.
  It retains the source revision, resolved environments, test results and STEP
  smoke evidence.
- `--require-native-cad` imports the required backend before testing and fails
  if no native cases are selected or a selected native case skips. The default
  optional full suite can still report missing CAD as an explicit skip.
- Builds select headless tests for the default package and required native
  qualification for `-IncludeCad`. PR/headless workflows have read permission;
  only the release build job receives repository write permission.

## Verification

- Full local suite: **528 passed**, no skipped tests, with Python 3.10,
  `QT_QPA_PLATFORM=offscreen` and the installed OCC 7.9.0 backend:
  `python -m pytest tests -q -p no:cacheprovider --require-native-cad --strict-markers`.
- The suite includes **43** disk-failure/recovery/GUI regressions and **six**
  subprocess checks of the native qualification boundary.
- Primary launch helper passed a source CAD smoke when invoked from the older
  workspace: GUI/numerical imports, scalar clearance, 24 SVGs and generated
  cylinder STEP round-trip/analytic recognition.
- PowerShell launcher/build syntax and CI YAML parsing passed. Diff whitespace
  checks passed.

Hosted workflows, the clean Python 3.12 CI environment and its pinned OCC 7.9.3
recipe have not run here. The local recipe solve was blocked by network access.
No frozen executable was rebuilt and no native viewport or clean-machine
distribution qualification is claimed; these remain I08 work.
