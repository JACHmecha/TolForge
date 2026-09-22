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

Relationships use stable IDs rather than display names. Pattern members have
separate size, X-position, and Y-position sources; actual XY comes from current
geometry in the datum frame. Declaring an occurrence, constraint, distribution,
or response does not imply the GUI or solver executes every option.

## Persistence rules

`Project.load()` validates cross-references. Future schema changes belong in
`migrate_project_data()`. Unversioned dimension-bank and annotation JSON are not
automatically treated as projects. Length units allow mm/in and angle units
allow deg/rad, but the application does not implement complete unit conversion.

`gui/project_mixin.py` owns the desktop bridge. File-menu project saving captures
stack definitions, geometry links, complete datum selections, and position
controls. Evaluation adapts validated project objects into the numerical GD&T
engine. Actual pattern XY values are recalculated against rematched CAD/frame
geometry rather than being permanent measured coordinates in the file.

Project files reference CAD paths; geometry is not embedded. The dimension bank
is saved separately. Camera/layout, measurement slots, live offset deviations,
direction/visibility controls, histogram samples, and Eclipse settings are not
a full persisted session. Datum synchronization requires a complete A/B/C set;
an incomplete UI selection does not replace a previously stored datum system.

## Geometric identity and recognition

`FeatureSignature` supports circle, cylinder, plane, point, and generic kinds.
It stores center, normal/axis, optional radius, point count, and bounding-box
scale. Cylinder signatures use the midpoint of the axial extent, the analytic
axis direction, and radius. Their center is independent of the CAD kernel's
arbitrary choice of a point on that axis.

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

## Solver boundary

Current numerical engines calculate scalar stacks, supported geometric datum
frames, position/size checks, and pin/hole mating-boundary clearance. They do
not solve a general constrained assembly or simulate contact. Occurrence
transforms and assembly constraints remain declarative in that workflow.

The domain can describe fixed, uniform, normal, and triangular distributions
and correlation groups. Current runtime stack/pattern sampling uses its
uniform/split-normal conventions; a schema field does not enable correlated
or arbitrary distribution execution.

A future assembly solver should consume a validated `Project`, resolve
constraints and datum precedence, calculate responses, and expose that
calculation to the variation engine without reading GUI widgets. See the
[roadmap](../ROADMAP.md) for remaining work.
