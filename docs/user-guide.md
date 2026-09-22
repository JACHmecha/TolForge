# User guide

[Documentation home](../README.md)

## Workspace layout

The left rail selects Inspect, Library, Stack, Results, Measure, GD&T, or
Eclipse. The 3D viewport stays visible. Drag the divider to widen the workspace;
Stack, Measure, and the longer analysis panels scroll as needed.

The viewport toolbar contains Load STEP, Clear, and Analyze. Mesh quality and
selection filters are immediately below it. Analysis method, Cpk, iterations,
and acceptance bounds are in Results. Status messages appear below the viewport.

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

Clear removes geometry and active measurement/datum previews. Loading another
STEP replaces the displayed geometry. Saved feature links are reattached by
geometric signature when possible; ambiguous matches require relinking.

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

Eclipse estimates light blockage by two circular apertures using their diameters
and relative offset. It can reuse measured diameters/offsets and run corner and
Monte Carlo analyses. It is a circular-aperture model, not optical ray tracing.

## Saving and reopening

Use File > Save Project / Save Project As for `.tolforge.json`. The project
stores engineering definitions and CAD source paths; it does not embed the STEP
geometry. Keep those source files accessible. Open Project restores definitions
and loads its CAD source when available; otherwise load the source manually.

Save the dimension bank separately. Camera position, preview controls, current
measurement slots, histogram samples, and Eclipse settings are not a complete
saved session. Build a complete, valid datum system before saving it; the bridge
only synchronizes a full A/B/C set. Signature matching is heuristic: a changed
or ambiguous feature may need manual reassignment.

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
