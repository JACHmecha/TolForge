# User guide

[Documentation home](../README.md)

## Workspace layout

The left rail selects Inspect, Study, Library, Stack, Results, Measure, GD&T, or
Eclipse. The 3D viewport stays visible. Drag the divider to widen the workspace;
Stack, Measure, and the longer analysis panels scroll as needed.

The viewport toolbar contains Load STEP, Cancel load, Clear, and Analyze. Mesh quality and
selection filters are immediately below it. Analysis method, Cpk, iterations,
and acceptance bounds are in Results. Status messages appear below the viewport.

## Recommended study workflow

Start with the characteristic being decided, then establish the model, validate
its inputs, evaluate, and review a saved report. This adopts the useful workflow
principles of guided model validation, contribution review, and reporting described
by [Sigmetrix for CETOL 6σ](https://www.sigmetrix.com/software/cetol). TolForge's
current solvers cover a narrower scope than CETOL's CAD-integrated 3D assembly
variation analysis.

| Question | Workspace | Input and result |
|---|---|---|
| Which requested drawing controls have been checked? | Study | Drawing inventory and externally aligned measurements; per-control outcomes and coverage gaps |
| What does the CAD position pattern show, and how might assumed variation affect it? | GD&T | CAD centers in a supported datum frame; as-modeled and Monte Carlo checks |
| Does a signed dimensional chain meet a functional interval? | Stack / Results | Scalar dimensions; Worst Case, RSS, or Monte Carlo acceptance and contributors |

For measured-part work, follow the next section. For CAD prediction, record the
requirement and assumptions in Study, confirm project units, and choose **Check
CAD study**. Resolve missing geometry links, datum assignments/frame, and control
input errors before evaluating in GD&T. Readiness findings describe the supported
model; they are not approval of a drawing or inspection method.

## Measured-part study

1. Open **Study** and record the requirement and assumptions. Enter the drawing
   number/revision and governing standard, the part/serial and inspection record,
   and the measurement datum order/alignment.
2. Choose **mm** or **in** for this inspection dataset. Enter measurements already
   aligned by the CMM or inspection system; basic XY coordinates must use that
   same datum frame and units. TolForge does not perform this alignment.
3. Choose **Add drawing control** for each requested balloon. Record drawing,
   revision, characteristic, specification, datum reference and measured-feature
   name. Control IDs remain stable. Supported characteristics are `position`
   and `size`: enter a diametral position limit such as `0.2`, or size limits
   such as `10:10.2`. Both use the selected measurement unit. Record other
   callouts, such as `profile`, with their specification text; they remain
   unsupported and visible in coverage. Position datum references must match
   the dataset frame; blank or different references remain unevaluated.
4. Choose **Add feature** or **Import CSV**. Each row needs a unique feature name,
   basic XY, measured XY, measured diameter, drawing size minimum/maximum,
   diametral position tolerance, modifier (`RFS`, `MMC`, or `LMC`), and feature
   kind (`hole` or `pin`). An inventory control's specification overrides the
   corresponding row limit. Position controls still use the row's size bounds
   for material-condition bonus. Multiple controls may link to the same row.
5. Confirm common alignment/units and the supported scope: single-segment
   position, axes parallel to datum Z, and no datum mobility.
6. Choose **Evaluate measured part**. Review each requested control and the
   evaluated/requested counts. Position and size controls have separate
   dispositions; unsupported, unlinked or differently aligned controls never
   become passing results. Without an inventory, the older row workflow checks
   both size and position, while drawing coverage remains unknown.
7. Choose **Export report** to save inputs, references, results and traceability
   as JSON. Editing inputs
   clears the current result and requires evaluation before exporting again.

**Import CSV** opens a review dialog. Map each required measurement field to a
column or a constant, choose comma/semicolon/tab separation and source units,
and inspect the source and mapped previews. Record the external datum frame,
alignment procedure and fitting method (or explicitly record that the fitting
method was not provided). Confirm alignment before importing. An optional source
feature-ID column preserves the inspection system's identifiers.

Canonical headers are mapped automatically, for example:

```csv
name,basic_x,basic_y,measured_x,measured_y,diameter,size_lower,size_upper,position_tolerance,modifier,feature_kind
Hole 1,20,10,20.03,10.04,10.1,10,10.2,0.1,MMC,hole
```

Use decimal points for numbers. UTF-8 CSV with an optional byte-order mark is
supported. Every row is validated; row/field errors block the entire import.
Cancel leaves the dataset unchanged. Acceptance appends the reviewed rows,
rejects duplicate feature names, repeated stable measurement IDs and source-ID
duplicates within the batch, and retains the exact captured file SHA256,
mapping, units, alignment, fitting method and stable measurement IDs. Those
records survive project saves and recovery drafts. Changing the dataset unit
label or datum-frame text does not convert or transform imported values; a
mismatch blocks evaluation. Additional imports must share the dataset units and
frame.
The example has a diametral position
error of 0.10, MMC bonus of 0.10, and allowed position tolerance of 0.20. Its
position margin is 0.10 and its size margin is 0.10 in the selected length unit.

These are results for the supplied controls, not whole-drawing conformance.
Measured-datum fitting, form, general orientation, composite position, datum
mobility, and uncertainty guard bands/decision rules are outside the model.
A supplied diameter is not a complete feature-of-size form/envelope inspection.
Review the inspection method and uncertainty before using a result for disposition.

## Report traceability

Scalar, measured-part and CAD-position reports capture evidence when evaluated:
report and input-snapshot IDs, UTC time, project/study identity, schema and
software/runtime versions, settings, units, scope and a canonical SHA256 input
digest. They retain source file hashes or an explicit reason a hash is unavailable.
Free-text drawing references do not supply drawing file bytes. Imported CSV
hashes are compared with the referenced file at evaluation, so later file edits
do not silently replace the measurements used. CAD source hashes identify the
referenced file; a stored hash alone cannot prove equivalence with geometry
already loaded in memory. Reports retain the loader's verified source digest
separately and show whether the evaluation-time file matches the loaded geometry,
differs from it, is unavailable, or has unverified loaded-revision evidence.

Export copies the captured evidence. It does not refresh timestamps, source
hashes or inputs. Editing inputs or report context requires another evaluation.
Reassessing scalar acceptance bounds creates new report/snapshot IDs and a new
digest while retaining the original samples, source evidence and evaluation time.
Reports from an uncommitted checkout record that state and numerical source-file
fingerprints; frozen source fingerprints may be unavailable. Keep the separate
build artifact evidence when distributing an executable.

## STEP inspection

1. Choose **Load STEP** and open a `.step` or `.stp` file.
2. Choose Any, Vertices, Edges, Faces, or Solids in the selection filter.
3. Click geometry to inspect it, or right-click to open feature actions.

| Action | Control |
|---|---|
| Rotate | Left drag |
| Pan | Right drag or Shift + left drag |
| Zoom | Mouse wheel |
| Select | Left click without dragging |
| Feature actions | Right click without dragging |

Mesh quality is tessellation deflection: lower values request a finer mesh.
It takes effect on a subsequent load, not as a live retessellation slider.
The loader reports when the installed backend ignores the requested setting.

Loading shows the current stage and geometry progress. **Cancel load** keeps the
previous scene and stops at the next controllable stage. A native CAD read may
need to finish first. Closing during a load retains the window until its worker
has stopped; it does not destroy a running loader. Clear removes geometry and
active measurement/datum previews.

In **Inspect**, choose **Review saved feature links** to see unresolved or
ambiguous saved IDs, candidate scores and match reasons. Scores are geometric
heuristics; review the selected geometry before assigning it. Manual assignment
preserves engineering IDs and existing input rows. Use **Locate saved CAD
source** when a referenced file moved. Relative CAD paths resolve against the
project file and are rebased when saving elsewhere.

The loader compares the captured CAD hash with the saved revision. A changed
revision, or one that cannot be verified against a saved hash, requires explicit
acceptance before links can attach, CAD evaluation can run or an engineering
project can be saved. Recovery drafts remain available. Missing definitions and
pattern rows remain visible. Review links and rebuild the datum frame after a
reload or manual assignment; pattern actual coordinates then refresh from the
current geometry.

Inspect displays feature identity, geometry, persistent-link state, and datum
membership. Analytic cylinders show their diameter and axis direction. Datum
and frame annotations do not intercept geometry picking.

## Dimension library and stacks

Library stores reusable nominal, positive/negative tolerance, and optional Cpk
values. Add templates to Stack, save a selected stack row to the bank, or load
and save a separate bank JSON file. Bank entries have no stack sign.

Stack columns include Name, Nominal, Tol +, Tol -, +/-, Cpk, and 3D Value.
Use positive tolerance magnitudes and choose the contribution sign separately.
The sign control includes both a symbol and a color.

Choose an analysis method in Results and press Analyze. Worst Case and RSS
report limits; Monte Carlo provides a histogram and acceptance statistics.
Drag its interval boundaries or edit acceptance bounds to update the statistics.

Name the functional response and set its acceptance interval in Results. These
bounds are separate from the fit assessment at zero clearance. Enter a **Study
random seed** for repeatable stack and CAD-position Monte Carlo runs (blank uses
a fresh random sequence). Keep inputs, method, iteration count, and seed fixed
when reproducing a result.

Results rank variance contributions for the independent scalar model, including
the mean shift from asymmetric distributions. The signs are scalar sensitivities
of +1 or -1; this ranking is not a 3D GD&T sensitivity calculation. Use it to
identify a justified input to investigate, change one assumption at a time, and
compare with the same seed. **Export stack report** saves the current input
snapshot, settings, result summary, acceptance, fit check, contributors, and
assumptions as JSON; raw sample arrays are omitted. Changing the acceptance
interval reassesses existing Monte Carlo samples without resampling.

Monte Carlo yield and observed rejection PPM describe the generated samples.
Zero observed rejects does not establish zero failure risk or six-sigma
performance. RSS gives an engineering tolerance band rather than a guaranteed
bound or calibrated yield prediction.

A dimension Cpk overrides the global value. With neither set, sampling is
uniform within the limits. With Cpk set, each side uses
`sigma = tolerance / (3 * Cpk)` in a split-normal model. Uniform sampling is
not a universal worst-case probability model, and normal samples are not
clipped to tolerance limits.

## Measure

Right-click features and assign **Set as Measure A** and **Set as Measure B**.
These are measurement slots, distinct from datum A/B/C. Results include sampled
minimum/maximum distance, projected normal distance, offsets, angle, and
circle-fit information where available. Measurements can become library entries.

Distances and angles mostly use tessellated points and fitted directions.
They are not exact CAD minimum-distance or solid-interference calculations.
Analytic cylindrical *datum* recognition does not convert every measurement
or surface-offset operation into an analytic cylinder operation.

## Live surface offsets

### From a measurement

1. Assign two measurement features, including a face.
2. Enter nonnegative Tol + and Tol - values.
3. Click **Show live offset**.
4. Drag the slider or edit **From nominal**; Reset returns to zero.

The preview uses face A if present, otherwise face B. A positive deviation
moves that face in the direction that increases the projected separation;
Reverse direction flips this preview direction. Zero leaves the source face
at its nominal location. Clear offset stops the preview.

### From a stack row

1. Select a row, choose **Link selected row to feature**, and choose Surface
   offset. Alternatively, use the feature context menu's normal-offset action.
2. Pick the feature and select the linked row.
3. Use the row slider or the Surface offset controls below the table.

The row value remains within `[nominal - Tol -, nominal + Tol +]`. The preview
uses its deviation from nominal. Diameter and Position are separate link modes;
position linking is one-dimensional motion along a fitted in-plane axis.

### Colors and combined behavior

| Color | Layer |
|---|---|
| Orange | Current offset |
| Blue | Lower limit |
| Violet | Upper limit |

Show limits controls the boundary layers; a coincident boundary/current layer
is drawn once. In Stack this visibility setting applies to the rebuilt linked
previews; Reverse direction applies to the selected surface-offset row.
Several normal-offset rows on one feature combine their deviations and bounds.
Diameter/position contributions remain at their current values while normal
limits are shown. Stack signs affect analysis and extreme-value snaps, not the
chosen geometric preview direction.

Worst-case and MC snap actions choose linked row values for those stack
scenarios. The MC snap action samples separately from the Results histogram.
Numeric values, direction reversals, visibility, and panel layout are session
state, not saved manufacturing definitions.

Surfaces translate along a fitted direction. They are not curved-surface
inflations, material envelopes, or proof of clearance/interference.

## Datums and their origin

1. Assign **A · Primary**, **B · Secondary**, and **C · Tertiary** using the
   feature context menu or Pick A/B/C in GD&T.
2. Inspect the colored geometry and camera-facing datum labels.
3. Click **Build datum reference frame** to display its origin and X/Y/Z axes.

| Datum/axis | Color |
|---|---|
| A / primary | Cyan |
| B / secondary | Violet |
| C / tertiary | Gold |
| X, Y, Z axes | Red, green, blue |

The O marker is local `(0, 0, 0)` of the datum reference frame (DRF). Its model
coordinates appear in the panel. This is the coordinate frame used for pattern
calculations, not the placement of a feature-control-frame annotation box.
Show A/B/C, Show origin + axes, and Marker size control the inspection graphics.
Hidden/back-facing features may require rotating the model to inspect them.

Reassigning or clearing a datum invalidates the existing frame and removes its
axes. Build it again before evaluating a pattern. Restoring a complete saved
datum system rebuilds its frame against rematched geometry.

### Cylindrical datums

An analytic cylindrical STEP face supplies its exact axis and radius, including
trimmed/partial cylinders. The viewport labels its axis, and the panel identifies
it as a cylindrical face. A recognized circular edge supplies a fitted axis.
Spline-defined cylinders and other unsupported curved faces are not silently
converted to planar datums.

For A/B as plane–axis or axis–plane, the plane must be perpendicular to the axis.
Their intersection fixes the origin. C fixes rotation using a side-plane normal
or a separate parallel axis. Concentric axes or a second end plane do not fix
that remaining rotation. Other supported combinations and restrictions are in
[GD&T semantics](gdt-semantics.md#datum-reference-frames).

## Position patterns and Eclipse

After building a frame, pick circular pattern features and enter drawing basic
X/Y coordinates. Actual X/Y are derived from geometry in the current frame.
Set the base diametral position tolerance, feature kind, material modifier,
size limits, and sampling inputs; use nominal or Monte Carlo evaluation.
Size and position must both conform. See [calculation semantics](gdt-semantics.md).

This is CAD-based evaluation/prediction. Use Study for supplied measurements of
an actual part. The Study random seed in Results also applies to CAD-position
Monte Carlo; XY process variation is a sampling input distinct from the drawing's
diametral position acceptance zone. Validate the as-modeled pattern before
comparing predicted size and position failure rates.

Pattern cells can display rounded numbers while calculations and project files
retain their full precision. Opening a cell editor shows its full value;
accepting an unchanged value preserves it.

Eclipse estimates light blockage by two circular apertures using their diameters
and relative offset. It can reuse measured diameters/offsets and run full-zone
worst-case and Monte Carlo analyses. The worst-case range includes interior
diameter extrema and is evaluated numerically. It is a circular-aperture model,
not optical ray tracing.

Use finite numbers, nonnegative tolerance magnitudes, positive diameter ranges,
and a positive Cpk when supplied. The threshold is a percentage from 0 to 100.
An invalid run clears the previous results and reports the input error. Normal
sampling remains unbounded; a generated nonpositive diameter rejects the run
and asks you to review the diameter/Cpk assumptions.

## Saving and reopening

Use File > Save Project / Save Project As for `.tolforge.json`. The project
stores engineering definitions and CAD source paths; it does not embed the STEP
geometry. Keep those source files accessible. Open Project restores definitions
and loads its CAD source when available; otherwise load the source manually.

Project saving also stores Study requirements/assumptions, analysis settings,
units confirmation, inspection references, measurement rows, and scope/alignment
confirmations, drawing-control definitions and imported source descriptors.
Reopening restores inputs; run evaluation again for a current
report. Older schema-1 projects without Study settings remain supported.

An asterisk in the title marks unsaved project changes. **New Project**, opening
a project/previous version/recovery draft, and closing offer **Save / Discard /
Cancel**. A canceled or failed save keeps the current work open. Invalid target
files are checked before the current project is replaced.

Incomplete text, partial datum selections and unresolved feature links can be
preserved with **File > Save Recovery Draft**. This separate `.recovery.json`
format retains raw editor inputs and persistent IDs without accepting them as
validated engineering definitions. Drafts contain no analysis results. **File >
Recover Incomplete Work** restores them as unsaved work; review inputs, reload
geometry and rebuild the frame before evaluating or saving a project.

TolForge also saves recovery drafts after edits. Source runs keep them in the
checkout's ignored `.tolforge/drafts` directory; installed executables use
`%LOCALAPPDATA%/TolForge/drafts`. Startup offers the latest draft left by an
interrupted session. Successful project saves or deliberate discard remove
the associated automatic draft. Manual recovery files remain where you saved
them. A draft does not make incomplete work valid or replace CAD source files.

Save the dimension bank separately. Camera position, preview controls, current
measurement slots, histogram samples, and Eclipse settings are not a complete
saved session. Build a complete, valid datum system before saving it; the bridge
only synchronizes a full A/B/C set. Signature matching is heuristic: a changed
or ambiguous feature may need manual reassignment.

Project and bank saves revalidate current data, including changes made after
creation. Nonfinite numbers and malformed identities or geometric signatures
are rejected. Saves stage the new file before replacing the destination; a
failed save keeps the previous file and reports the error. Project success
messages and the saved-file title update only after the save completes.

When replacing a valid saved project, bank, annotation file or JSON report, the
previous version is kept beside it with `.bak` appended, for example
`part.tolforge.json.bak`. An already-corrupt file does not overwrite that recovery
copy. One previous version is retained; this is not a full revision history.

To recover a project, choose **File > Open Previous Saved Version** and select
the original project file. TolForge validates its backup and opens it as an
unsaved recovered project. Choose **Save Project As** to keep the recovered
version. Merely opening the previous version does not modify either saved file.
For a bank, choose **Load bank** and select its `.json.bak` file. A missing or
invalid recovery copy produces an error. Complete geometry/datum requirements
still apply when saving a recovered project.

## Known limitations

- Keep CAD/input units consistent. Project units support length mm/in and angle
  deg/rad, but there is no complete GUI conversion workflow; some older displays
  still label measurements as mm/deg.
- Datum frames are a limited geometric construction, without material-boundary
  simulators, datum shift, skew-axis handling, or general assembly constraints.
- Only the documented position/size checks are calculated; icons for other GD&T
  characteristics do not imply those solvers are implemented.
- STEP objects are individually tessellated/pickable; very large assemblies may
  load slowly. Source recognition is independent of display mesh quality.
- Running another checkout or an older executable will not show current source
  edits. See [troubleshooting](development.md#troubleshooting).
