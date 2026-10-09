# Engineering domain

[Documentation home](../README.md)

`tolstack.project.Project` stores engineering definitions. Qt widgets, renderer
objects, OCCT wrappers, and transient face/edge indices do not belong in it.
The current JSON schema version is **1**; package versioning is separate.

## Object graph

| Object | Meaning |
|---|---|
| `PartDefinition` | Design identity and source CAD file path |
| `PartOccurrence` | Instance of a part with a rigid transform |
| `FeatureDefinition` | Engineering feature with an optional geometric signature |
| `ToleranceDefinition` | Variation source and distribution definition |
| `LinearStackDefinition` / `StackTerm` | Signed references to tolerance sources |
| `DatumReference` / `DatumSystem` | Feature-bound datum labels and precedence |
| `PositionControlDefinition` | Feature pattern tied to a datum system |
| `AssemblyConstraint` | Declarative relationship between occurrence features |
| `ResponseDefinition` | Requested characteristic, such as clearance or distance |
| `Project.study` | Optional workflow settings, inspection references/rows, and confirmation state |

Relationships use stable IDs rather than display names. Pattern members have
separate size, X-position, and Y-position sources; actual XY comes from current
geometry in the datum frame. Declaring an occurrence, constraint, distribution,
or response does not imply the GUI or solver executes every option.

## Persistence rules

`Project.validate()` rechecks current entity fields, nested definitions,
collection keys and cross-references, including mutations after construction.
Add/load/save boundaries use the same entity rules. Project and dimension-bank
JSON reject nonfinite values at every depth and duplicate object keys. Saves
complete validation and strict serialization, write and flush/fsync a temporary
sibling, then replace the destination. A prior valid JSON/domain version is
retained at `<filename>.bak`; an invalid existing destination does not overwrite
an already-valid recovery copy. Serialization, write, flush or replacement
failures leave the previous destination intact, and failed GUI project saves
restore the pre-save domain state before reporting an error. This is protection
against ordinary save failures, not concurrent-writer locking or a universal
power-loss guarantee.

`Project.load_previous()`, `DimensionBank.load_previous()` and
`AnnotationSet.load_previous()` validate the retained backup. File > Open
Previous Saved Version opens a project backup as an unsaved recovered project;
Save As chooses where to keep it without automatically replacing the current
file. Bank Load accepts `.json.bak`. Report and annotation exports use the same
Qt-independent `tolstack.persistence.save_json()` boundary.
Future schema changes belong in
`migrate_project_data()`. Unversioned dimension-bank and annotation JSON are not
automatically treated as projects. Length units allow mm/in and angle units
allow deg/rad, but the application does not implement complete unit conversion.

`gui/project_mixin.py` owns the desktop bridge. File-menu project saving captures
stack definitions, geometry links, complete datum selections, and position
controls. Evaluation adapts validated project objects into the numerical GD&T
engine. Actual pattern XY values are recalculated against rematched CAD/frame
geometry rather than being permanent measured coordinates in the file.

The optional `study` object extends schema 1 without changing its version;
older files default to empty study settings. It records requirement/assumptions,
response name, method, functional limits, Monte Carlo seed/iterations/Cpk,
CAD-unit confirmation, and the measured-part inspection input block. That block
holds drawing/source/alignment references, units, confirmations, and row inputs.
Stable measurement IDs and row ancestry live at
`study.inspection.row_metadata`, parallel to input rows. Imported records include
the captured source hash/row, optional external feature ID, import ID, units,
external alignment and fitting method; manual rows have their own stable IDs.
Legacy projects/drafts gain manual IDs when restored without inventing import
ancestry. Imported CSV descriptors live at `study.inspection.source_files`; the optional
inventory lives at `study.drawing_controls`:
stable ID, balloon, drawing/revision, characteristic, specification, datum
references and measured-feature link. Only definitions are persisted;
calculated status and coverage are report outputs. `tolstack.characteristics`
validates identity, balloon uniqueness per drawing/revision and supported
specification grammar (`position`: nonnegative diameter; `size`: positive
ordered `minimum:maximum`). Unsupported callout text remains representable.
Inspection coordinates are externally measured data and remain separate from
CAD pattern positions and geometry rematching. Reports are exported snapshots,
not cached results silently restored as current after loading a project.

Project files reference CAD paths; geometry is not embedded. The dimension bank
is saved separately. Camera/layout, measurement slots, live offset deviations,
direction/visibility controls and histogram samples are not a full persisted
session. The optional `study.projected_interference` block stores validated
inputs, mode, local length units, seed, iterations, area threshold and CAD
projection metadata. `tolstack.projected_study` validates this block on save
and load. Analysis samples/results are not restored. Recovery drafts preserve
incomplete raw module text separately. Datum synchronization requires a complete A/B/C set;
an incomplete UI selection does not replace a previously stored datum system.

`gui/project_lifecycle.py` tracks domain and raw editor changes, guards project
replacement/close with Save/Discard/Cancel, and preserves failed-save work.
`tolstack.drafts` owns a separate recovery schema containing a validated domain
snapshot plus raw input strings, link IDs and partial datum selections. Its
tables exclude derived outputs. Draft loading never evaluates inputs, relaxes
Project validation or writes an engineering project. Recovered work requires
review and Save As; geometry links may still be unresolved. Automatic drafts
use the existing atomic persistence boundary and are local to the source
checkout or the frozen application's user-data directory.

## Geometric identity and recognition

`FeatureSignature` supports circle, cylinder, plane, point, and generic kinds.
It stores center, normal/axis, optional radius, point count, and bounding-box
scale. Cylinder signatures use the midpoint of the axial extent, the analytic
axis direction, and radius. Their center is independent of the CAD kernel's
arbitrary choice of a point on that axis.

Saved signatures validate their finite 3D vectors, positive optional aperture
radius, nonnegative integer point count and nonnegative size scale before
matching. Arbitrary finite JSON metadata remains supported.

On STEP loading, the worker recognizes analytic plane/cylinder surfaces and
passes serializable metadata to scene entity information. Datum extraction
uses it to distinguish a plane reference from an axis reference. Circular
edges use validated circle fits. Unsupported curved faces are rejected as
datums; absent metadata only permits a validated planar fallback. A signature
kind is a matching aid, not independent proof that a face is a valid datum.

Saved signatures are compared to current geometry by proximity and size rather
than transient scene indices. Matching reports exact/good/ambiguous/none;
ambiguous or revised geometry can require manual relinking. Legacy signatures
remain usable, but a signature is not a durable CAD topology identifier.

`tolstack.relinking` plans candidate matches without Qt or scene mutation.
Automatic collisions remain unresolved. The relinking panel exposes candidates,
scores/reasons and occupancy; explicit same-kind manual assignments update the
signature while preserving feature, datum, pattern-member and tolerance IDs.
Missing definitions/rows are retained. Source paths resolve against the project
or recovery anchor, and Save As rebases them to preserve the physical target.
The STEP worker hashes source bytes before and after extraction and rejects a
source that changes during loading. A changed/unverified revision against a
saved hash remains pending until explicit acceptance; pending revisions cannot
attach features or pass CAD/save readiness. Loaded-byte evidence remains
separate from stored expected hashes and later evaluation-time file hashes.

## Solver boundary

Current numerical engines calculate scalar stacks, supported geometric datum
frames, position/size checks, and pin/hole mating-boundary clearance. They do
not solve a general constrained assembly or simulate contact. Occurrence
transforms and assembly constraints remain declarative in that workflow.

The domain can describe fixed, uniform, normal, and triangular distributions
and correlation groups. Current runtime stack/pattern sampling uses its
uniform/split-normal conventions; a schema field does not enable correlated
or arbitrary distribution execution.

`workflow.validate_workspace_project()` rejects unsupported distributions,
parameters, correlation groups, and repeated use of a single stack tolerance
source before loading a model into a workspace that cannot preserve those
semantics. Repeated-source sampling requires shared random variables; treating
each use as independent would give a different calculation.
The CAD editor also rejects datum material-boundary modifiers and pattern-source
definitions it cannot round-trip: its editable sources use symmetric bounds with
global Cpk sampling, rather than per-source asymmetric/normal definitions.

## Application services

`tolstack.analysis` validates plain stack inputs and settings, executes the
selected scalar method, assesses functional acceptance, and ranks independent
source variances. `AnalysisReport` retains a validated input snapshot and exposes
a JSON-safe summary. Acceptance-bound edits can reassess existing samples without
rerunning the simulation. The fit-at-zero result remains separate from functional
response acceptance. A supplied seed makes sampling repeatable for unchanged
inputs and the same numerical environment.

`tolstack.inspection` evaluates supplied measured XY centers/diameters against
per-feature size and single-segment position controls. It requires drawing,
measurement-source, and datum-alignment references plus explicit alignment and
scope confirmation. It does not infer a measured datum frame from CAD geometry.
With a drawing inventory it evaluates each supported linked control against
that control's own specification. Position references must match the recorded
dataset frame; mismatch/blank reference and absent links are unevaluated.
Unsupported characteristics remain explicit. Coverage counts all requested
controls; it applies only to the declared inventory. With no inventory the
legacy combined size/position row evaluation remains available and coverage
is unknown.

`tolstack.reporting` captures immutable, detached evaluation-time evidence for
scalar, inspection and CAD-position JSON reports. The envelope includes report
and input-snapshot IDs, UTC evaluation time, canonical strict-JSON input digest,
project/study IDs, settings, units, scope, referenced-file SHA256 or explicit
unavailability, runtime versions and source revision/dirty state. A manifest
identifies available numerical source bytes; it does not identify a frozen
binary. Exact submitted measurements, effective controls and actual datum
frames remain in snapshots. Source file hashes do not by themselves establish
that loaded CAD geometry came from that file revision. CSV import digests
make subsequent source-file mismatches visible. Scalar acceptance reassessment
creates new evidence while retaining original result time and captured sources;
export never rereads source files. Verified loader evidence can establish
`matches_loaded_geometry`; a changed referenced file records
`differs_from_loaded_geometry`, while absent/unverified evidence remains
explicit. Stored expected hashes alone cannot establish this relationship.

`tolstack.inspection_import` captures UTF-8 CSV bytes once, then produces a
detached all-row preview from configurable columns/constants and explicit
external alignment. It supports one feature per row, decimal-point numbers and
comma/semicolon/tab separators. Stable row IDs derive from the captured revision
and accepted import settings plus external ID or source row. The GUI revalidates
current dataset constraints before an atomic append. Mapping, unit, frame and
identity errors block import/evaluation; no unit conversion, coordinate fitting
or vendor-specific qualification is implied.

`tolstack.workflow` validates study settings and produces actionable CAD-study
readiness findings. `gui/study_mixin.py` handles editing, CSV import, report
export, and the study persistence bridge; the numerical services do not read Qt
widgets. `gui/stack_table.py` owns stack values through a `QAbstractTableModel`
and `QTableView`, with a compatibility facade for existing link/project callers.
`gui/viewport_adapter.py` provides the scene/context boundary for renderer
operations while existing geometry preparation remains in the STEP worker.

A future assembly solver should consume a validated `Project`, resolve
constraints and datum precedence, calculate responses, and expose that
calculation to the variation engine without reading GUI widgets. See the
[roadmap](../ROADMAP.md) for remaining work.
