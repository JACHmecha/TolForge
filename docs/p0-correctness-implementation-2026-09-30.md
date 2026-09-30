# P0 correctness implementation — 2026-09-30

The three P0 recommendations selected from the prioritized backlog are
implemented in the working tree. Git base: `483b54309085fbda6805c4b8cf273a0e3c2e48cd`
on `main`. This record describes uncommitted source changes.

| Item | Result | Principal evidence |
|---|---|---|
| I01 — Eclipse validation | Rejects nonfinite values, negative tolerances, nonpositive diameter ranges/Cpk, invalid iterations/thresholds and invalid samples/statistics. Failed GUI runs clear results. Full-zone bounds include interior diameter extrema. | `Code/tolstack/eclipse.py`, `Code/gui/eclipse_mixin.py`, `tests/test_eclipse.py`, `tests/test_eclipse_gui.py` |
| I02 — Mutable data and strict JSON | Revalidates current domain/project/bank state, nested definitions, geometric signatures, keyed IDs and references. Rejects nonfinite JSON and duplicate keys; completes serialization before opening the save destination. | `Code/tolstack/domain.py`, `Code/tolstack/project.py`, `Code/tolstack/bank.py`, `Code/tolstack/json_data.py`, `Code/tolstack/feature_schema.py`, `tests/test_persistence_validation.py`, `tests/test_feature_signature_validation.py`, `tests/test_bank_gui_validation.py` |
| I03 — Engineering precision | Stores raw pattern numbers separately from display text. Editors, analysis and project synchronization preserve full values; measured bank/Eclipse transfers retain precision. | `Code/gui/gdt_mixin.py`, `Code/gui/project_mixin.py`, `Code/gui/measurement_mixin.py`, `tests/test_pattern_precision.py`, `tests/test_measurement_bank_validation.py` |

The regression example with offset `0.00004` and diametral position tolerance
`0.00005` remains a failure (`0.00008` position error) through display changes,
editing, analysis, project save/load and geometry restore. Stable feature,
member and tolerance IDs survive that round trip. Measurement-to-bank-to-stack
round trips also preserve small coordinates, diameters and tolerance values.

Eclipse retains the existing uniform or Cpk-calibrated, unbounded sign-scaled
normal sampling convention and legacy seeded random stream. Nonpositive normal
diameter draws invalidate the run; samples are not clipped or resampled.
Thresholds use fractions from 0 to 1 in the engine and percentages from 0 to 100
in the GUI.

Eclipse bounds enumerate diameter endpoints and equal-diameter interior points,
then check stationary smaller-radius minima using bounded scalar bisection.
For fixed smaller radius, increasing the larger radius improves coverage.
The stationary condition on a fixed larger-radius boundary is
`beta / sin(beta) = distance / larger_radius`, with at most one interior
minimum. The displayed range is labeled numerical. Regressions cover the two
previously missed interior extrema and independent diameter grids.

Persistence retains schema version 1, existing non-UUID string IDs, optional
signature defaults and arbitrary finite JSON metadata. Known engineering
numbers reject booleans; genuine metadata and confirmation booleans remain
valid. Invalid mutations and invalid serialization preserve the previous
saved file. These checks do not make disk writes atomic.

## Verification

- Full repository suite: **470 passed**, including native cylinder/cone tests.
- Source self-check: GUI/numerical imports, scalar clearance, all 24 GD&T SVGs,
  and cylinder STEP round trip/analytic recognition passed.
- `git diff --check` passed.
- The existing `Code/gui/app.py` content was preserved byte for byte except
  the Eclipse label change from `Exact worst case:` to `Worst case:`.

Verification used Python 3.10, `QT_QPA_PLATFORM=offscreen`, and process-local
`TOLFORGE_DLL_DIRS` containing the installed OCCT, FreeType and Tcl/Tk binary
directories. The DLL environment was not persisted. The full test command was:

```powershell
python -m pytest -q -p no:cacheprovider
```

The source smoke command was:

```powershell
python Code/gui/app.py --self-check-json <report-path> --self-check-cad
```

Verification ran from source. A frozen executable, rendered native viewport
and clean-machine distribution were not qualified in this change.
