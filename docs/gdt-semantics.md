# GD&T calculation semantics

[Documentation home](../README.md)

These notes describe the implemented numerical models in `Code/tolstack/gdt.py`
and `Code/tolstack/inspection.py`.
They do not establish general drawing-standard conformance.

## Two sources of position data

**Study** evaluates measurements supplied by an inspection system. Each feature
has drawing basic XY, measured XY, a measured diameter, size bounds, a diametral
position tolerance, RFS/MMC/LMC modifier, and hole/pin kind. The coordinates must
already share the stated measurement datum frame; the app does not fit measured
datums or estimate an alignment transform. Drawing/revision, measurement source,
datum alignment, units, and explicit scope confirmation accompany the result.

**GD&T** derives pattern coordinates from CAD geometry projected into a supported
constructed frame, then evaluates that geometry or samples assumed process
variation. CAD coordinates are not substituted for measured part data. The same
size/position equations below serve both paths, but their evidence and intended
use differ.

Inspection accepts a consistent dataset in mm or in without conversion. The
CAD/GD&T workspace currently requires mm and deg. Axes must be parallel to datum
Z, and the position control must be single-segment without datum mobility. The
provided diameter check does not establish complete feature-of-size form/envelope
conformance. No uncertainty guard band or decision rule is applied. A reported
pass means only that the requested supported check passes this bounded model.
With an inventory, Study evaluates `position` and `size` separately using each
control's specification, stable ID and measured-feature link. A position datum
reference must match the dataset frame. Unsupported, unlinked and unverified
alignment controls remain explicit coverage gaps. Without an inventory, each
row retains the older combined size/position result and drawing coverage is
unknown. Other drawing controls require their own evaluation.

Reports retain the exact evaluation-time controls, submitted measurements,
effective inputs and constructed CAD frame separately from live editor state.
Their evidence identifies project/study, settings, units, input digest, source
hash availability and software/runtime versions. A referenced STEP hash alone
does not verify the revision of geometry already loaded in memory. See
[report traceability](user-guide.md#report-traceability).

## Datum reference frames

A `DatumFeature` has a point, unit direction, and kind (`plane` or `axis`).
Omitted kind defaults to plane for compatibility. Analytic STEP cylinders use
their axes; analytic planes use their normals. Circular edges supply fitted
axes. Unsupported curved faces are not treated as planar datums.

| Primary A | Secondary B | Tertiary C | Construction |
|---|---|---|---|
| Plane | Plane | Plane | Existing orthogonalized three-plane construction |
| Plane | Plane | Axis parallel to A normal | Axis point fixes the remaining Y location |
| Axis | Perpendicular plane | Clocking plane or distinct parallel axis | Line-plane origin; C fixes rotation |
| Plane | Perpendicular axis | Clocking plane or distinct parallel axis | Line-plane origin; C fixes rotation |

For plane A/B, Z is A's normal, X is B's normal projected perpendicular to Z,
and Y is `Z cross X`. The origin is
`Z * dot(Z, pA) + X * dot(X, pB) + Y * dot(Y, pC)`.
This orthogonalized construction is not a general three-plane intersection
solver for arbitrary oblique faces.

For plane/axis A/B, the axis must be parallel to the plane normal (absolute
unit-vector dot product at least `1 - 1e-6`). Their line-plane intersection is
the origin. Z follows the primary direction. C's plane normal projected into
XY, or the displacement to a distinct parallel C axis projected into XY,
defines X; Y is `Z cross X`. A concentric C axis or an end plane with no XY
normal cannot resolve rotation. Skew axes and axis/axis A/B are unsupported.

The inspection O marker is this frame's local `(0, 0, 0)`, with model coordinates
reported in the panel. It is not the location of a drawn feature-control-frame
box. Changing datum assignments invalidates the previous frame.

The GUI datum construction has no material-boundary simulator or datum shift,
even though the domain can store datum modifiers. Pattern evaluation uses
circular feature centers projected into the frame's XY plane and assumes
feature axes parallel to Z; it does not evaluate general axis orientation.

## Size and bonus tolerance

A feature passes only when both size and position checks pass. Hole MMC is the
lower size limit and LMC the upper; pin LMC is the lower limit and MMC the upper.
The size margin is the smaller distance to those two limits.

Position error is diametral: `2 * hypot(actual_x - basic_x, actual_y - basic_y)`.
Allowed diametral tolerance is base tolerance plus bonus:

| Modifier | Hole bonus | Pin bonus |
|---|---|---|
| RFS | 0 | 0 |
| MMC | actual size - MMC | MMC - actual size |
| LMC | LMC - actual size | actual size - LMC |

Bonus is nonnegative. `evaluate_position()` and pattern Monte Carlo clip size
to the valid interval **for bonus calculation only**. Out-of-size features
still fail the independent size check. The lower-level `bonus_tolerance()`
helper does not itself cap departure at the opposite size limit.

Position margin is allowed tolerance minus position error. Overall margin is
`min(size_margin, position_margin)`; nonnegative means pass. Monte Carlo reports
total failure plus separate size and position failure rates. The latter can
overlap and should not be added together.

Sampling uses uniform bounds when no Cpk applies, otherwise split-normal
sampling with separate positive/negative sigmas. Normal samples can fall
outside size limits; the acceptance checks still apply to those samples.

XY process sampling bounds are independent inputs; a drawing's diametral
position zone does not define an XY probability distribution. A Cpk input is a
sampling assumption, not capability estimated from inspection data. A recorded
seed supports repeatable comparisons for unchanged inputs. Predicted failure
rates are empirical sample estimates, and zero observed failures is not a
six-sigma qualification.

For inspection, edits invalidate the previous result. JSON export includes the
input snapshot, per-feature evaluations, source/alignment references, and model
limitations so reviewers can distinguish the supported checks from disposition
of the entire part.

## Diametral mating boundaries

For the MMC virtual-condition calculation:

- Hole VC: `hole MMC - hole base position tolerance`.
- Pin VC: `pin MMC + pin base position tolerance`.
- Guaranteed diametral clearance: `hole VC - pin VC`.

For a manufactured pair:

- Effective hole boundary: `actual hole size - hole position error`.
- Effective pin boundary: `actual pin size + pin position error`.
- Actual effective clearance: `effective hole - effective pin`.

Nonnegative boundary clearance expresses assembly within this perfect-form
boundary model. It does not establish independent feature conformance or solve
contact, datum mobility, form error, orientation coupling, sequencing, or
deformation. Measure's sampled distances and surface-offset layers are separate
visual tools, not these mating-boundary calculations.
