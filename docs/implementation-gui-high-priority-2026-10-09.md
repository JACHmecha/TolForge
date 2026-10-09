# GUI layout improvements: UI01–UI05

The user selected the five high-priority items from the [GUI layout and aesthetics recommendations](gui-layout-aesthetics-recommendations-2026-10-09.md). They are implemented in the primary source working tree on `main`, based on `4d5cd908237ab472c4066668b92e6f167052d33f`. The checkout already contained other uncommitted changes; this task preserves those changes. UI06–UI12 remain proposals.

| Item | Delivered behavior |
|---|---|
| UI01 | Projected-interference fields reflow into labeled grids; mode/units and compact parameter controls fit the pane. Wrapped labels prevent page overflow. |
| UI02 | Study, Stack, GD&T, Results, and projected interference receive more workspace width. Manual divider choices are retained per page during navigation and window resizing for the current session. |
| UI03 | Stack results use headings and aligned cards for functional acceptance, response metrics, the separate zero-clearance fit check, and contributors. Results and charts precede settings; Measure, GD&T, and projected summaries align captions and values. |
| UI04 | Study has five titled sections: references, alignment/scope, drawing controls, measurements, and results/readiness. Confirmation labels wrap while retaining checkbox behavior. |
| UI05 | Stack, Study, GD&T, import, and relinking tables share row heights, alternating fills, restrained grid treatment, bounded column widths, and numeric alignment. |

Engineering calculations and schemas are unchanged by these presentation changes. Summary cards read typed report fields; the original plain summary remains available through `result_label.text()`. Editing inputs clears displayed results as before. Numeric delegates preserve editing precision, IDs, and model roles. Wide tables can scroll internally; workspace forms fit without horizontal page scrolling.

Implementation files: `Code/gui/app.py`, `layout_presentation.py`, `analysis_summary.py`, `analysis_mixin.py`, `study_mixin.py`, `table_presentation.py`, `theme.py`, `gdt_mixin.py`, `inspection_import_dialog.py`, and `feature_relinking.py`.

## Verification

- Integrated GUI, precision, import, relinking, persistence, and recovery checks: **193 passed** in the existing Python 3.10/CAD environment.
- Presentation checks: **5 passed**, covering both 1024 × 768 and 1300 × 800 windows, a manually narrowed projected pane, unchanged engineering state during navigation, divider retention, and checkbox mouse/keyboard behavior.
- Full Python 3.12 scalar suite: **1,207 passed, 8 native-CAD tests explicitly deselected**. The final field-grid spacing adjustment also passed the five presentation checks in the working CAD environment.
- Source launch self-check passed with native CAD enabled, including generated cylinder, box, and cone STEP round-trips.
- Fresh offscreen visual review covered Study, Stack, Results, Measure, GD&T, projected inputs, both projected result modes, and Monte Carlo results. Windows fonts were loaded explicitly for this sandbox's initially empty font database. The CAD renderer was disabled for these layout screenshots.

The broader Python 3.10 run passed **1,214 tests** with required native CAD and no skips, with one unrelated packaging-test failure: the test mocks Python 3.12 while its actual Python 3.10 interpreter lacks `hashlib.file_digest`. That exact test **passed under the existing Python 3.12 scalar environment**. The packaging source and test were not changed.

A full-suite attempt in the separate Python 3.12 CAD environment could not collect GUI tests because its native Qt DLL loading failed with Windows procedure-not-found errors. This is recorded as an environment limitation; it does not replace the successful Python 3.10 native-CAD verification or establish a new CAD release qualification.

No executable was rebuilt. Offscreen layout screenshots do not qualify a native GPU viewport or a release artifact. To see the changes, restart the application from the primary checkout using `launch.ps1`.
