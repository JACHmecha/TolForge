# GUI clarity and selection: selected high-priority improvements

The four high-priority items from the October 15 GUI review are implemented in
the primary source working tree, based on `cf02b7680697419a3c5ebe52d10e894b9ab4f633`.
The existing Qt Widgets framework, engineering services, project schema and
COMPAS/OpenCASCADE renderer remain in use. This is source implementation
evidence; no executable was rebuilt or release qualification asserted.

## Delivered behavior

1. **Units and precision.** Workspace headers identify the project's length and
   angle units. Stack column headers and acceptance inputs identify their length
   unit and refresh when opening or creating a project. Updating presentation
   does not convert values, emit cell edits or change stable metadata roles.
   Analysis cards and the histogram read units from the evaluated report's
   evidence snapshot, never from a subsequently edited project. Reports without
   captured units explicitly say so. Nonzero lengths smaller than the ordinary
   four-decimal display use significant/scientific notation instead of appearing
   as zero. Tooltips and an expandable, selectable precision view expose the
   evaluated float's round-trip representation. Counts, Cpk, percentages and PPM
   remain dimensionless; calculations, report exports and legacy summary text
   retain their prior behavior.

2. **Coherent 3D selection.** The renderer resolves a hit without applying a
   highlight. The controller checks the active filter before committing the
   logical selection, inspector and scene highlight. A rejected click preserves
   the previous selection; an accepted solid highlights all its existing faces
   without adding scene objects or changing IDs. Armed measurement/datum/link
   tools keep their callback contracts. Context menus retain their raw-entity
   targeting and update the inspector/highlight consistently. Clearing or
   replacing the displayed geometry clears stale selection references.

3. **Explicit stack analysis actions.** `Analyze stack` appears within Stack and
   Results, with the current method shown beside it and in its accessible name.
   The ambiguous global viewport command was removed. GD&T, Study and projected
   interference retain their own analysis commands; no new calculation dispatcher
   or method semantics were introduced.

4. **Readable viewport status.** `ViewportStatus` preserves the existing
   `setText()`/`text()` contract and the original full message. Its one-line
   summary fits the available width beside progress. `Details…` exposes long or
   multiline messages in a bounded, nonmodal, scrollable plain-text view that
   supports copying and updates while open. Escape/Close returns keyboard focus
   to the trigger. Diagnostic paths and markup-like text are not interpreted as
   rich text. Existing load progress and cancellation remain unchanged.

The shared palette and layout are retained. Improving navigation grouping,
camera controls, library organization and other medium-priority items remains
separate proposed work.

## Verification

- **268 tests passed**, with the real native CAD backend required and no skips.
  The selected tests cover workspace sizing/navigation, units and precision,
  analysis services/report evidence, viewport selection/adapter/loading/
  cancellation, stack models, project lifecycle/persistence, measurements,
  previews, datum inspection, relinking, drawing controls and cylinders.
- After matching the new detail editor to the shared input/focus palette,
  all **14** selected workspace, status and theme checks passed again.
- The new integration tests verify unit/header refresh without editing cell
  values or IDs, project reset back to mm, command visibility/routing, and full
  status access in the actual window. Selection regressions exercise the
  production hit-routing methods with framebuffer doubles.
- `launch.ps1 -SelfCheckJson <task-output>/source-cad-check.json -IncludeCad
  -QualifyViewport` passed with the existing Python 3.10/PySide6 6.11.1 CAD
  environment. The check rendered actual STEP geometry in a native Windows
  OpenGL context, verified GPU picking/camera controls, and completed cylinder,
  box and cone STEP round-trips.
- An additional native application check loaded a synthetic box through the
  real worker, selected a face through the renderer framebuffer, rejected that
  face under the edge filter without changing the previous inspector/highlight,
  selected and highlighted all six solid faces, then cleared the model and
  verified the empty inspector. It also ran seeded stack analysis and opened
  the full status detail view.
- Fresh source screenshots were inspected at 1300 × 800 and 1024 × 768 logical
  window sizes in layout mode, including a 1.5 scale factor. Native screenshots
  separately establish the rendered viewport/selection evidence. The layout
  harness deliberately disables the renderer and does not substitute for that
  native check. Synthetic input values are examples, not customer data.

Task evidence includes `source-cad-check.json`, `native-ui-check.json`,
`native-selection-inspector.png`, `native-stack.png`, `native-results.png` and
`native-status-details.png`, plus layout captures and before-change images.
It is retained with the task artifacts outside the source tree.

Restart TolForge from this checkout using `launch.ps1` to see the source changes.
Existing packaged executables do not pick up these edits automatically.
