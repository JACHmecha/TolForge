# Engineering domain

TolForge project files use `tolstack.project.Project` as their source of truth.
Qt widgets, renderer objects, OpenCASCADE wrappers, and transient face/edge
indices must not be stored in this model.

## Object graph

- A `PartDefinition` identifies one design and its source CAD file.
- A `PartOccurrence` places an instance of a part in an assembly with a rigid
  transform. Multiple occurrences may reference the same part definition.
- A `FeatureDefinition` gives engineering meaning to geometry on a part. Its
  optional signature is the persistent fingerprint used to re-find CAD
  geometry after a reload.
- A `ToleranceDefinition` describes one source of variation and its
  distribution. Correlated sources share a correlation-group name.
- A `DatumReference` binds a datum label and modifier to a feature.
- A `DatumSystem` lists datum references in precedence order.
- An `AssemblyConstraint` records design intent between features on two
  occurrences. It does not solve the relationship.
- A `ResponseDefinition` describes the key characteristic an analysis must
  calculate, such as clearance or distance.

All relationships use stable IDs. Display names are deliberately not keys.

## Persistence rules

The project JSON format declares a `schema_version` and explicit units.
`Project.load()` validates every cross-reference before returning. Unversioned
dimension-bank and annotation JSON files are not silently treated as projects;
they will need explicit importers so their meaning cannot be guessed.

The desktop bridge in `gui/project_mixin.py` owns the current project. The
File menu saves and opens complete project JSON files. Stack-table rows become
`ToleranceDefinition` and `StackTerm` objects, while geometry links and datum
selections reference `FeatureDefinition.id`. On a STEP reload, geometric
signatures are matched back to current scene entities; face and edge indices
are retained only as transient renderer information.

Future format changes belong in `migrate_project_data()`. Domain constructors
should only need to understand the current schema.

## Solver boundary

The project model is declarative. A deterministic solver will consume a
validated `Project`, resolve constraints and datum precedence, and calculate
responses. A variation engine will sample tolerances and invoke that solver.
Neither solver should read values directly from GUI widgets.

The first solver slice should be a two-occurrence pin/hole assembly with a
concentric constraint, MMC size tolerances, and a clearance response.
