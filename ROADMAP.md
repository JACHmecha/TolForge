# TolForge roadmap

This is a capability roadmap, not a release schedule. The package version in
`setup.py` is currently `0.1.0`; completed items below do not imply that a
separate release or installer has been published.

## Implemented

- [x] Signed 1D stacks: Worst Case, RSS, Monte Carlo, asymmetric tolerances.
- [x] Uniform and Cpk-driven split-normal stack sampling.
- [x] Dimension bank, stack editor, histogram, and acceptance-range statistics.
- [x] Versioned project JSON and stable feature/tolerance/datum IDs.
- [x] STEP tessellation, per-entity picking, solid grouping, and mesh controls.
- [x] Contextual inspection and mesh-based measurement.
- [x] Resizable workspaces and a shared dark application/chart theme.
- [x] Stack links for diameter, position, and surface-offset previews.
- [x] Live surface controls, tolerance layers, and worst-case/MC preview snaps.
- [x] Datum face colors, A/B/C labels, origin/axes, and visibility controls.
- [x] Analytic plane/cylinder recognition from STEP, including trimmed cylinders.
- [x] Plane/axis datum frames for the configurations documented in
  [GD&T semantics](docs/gdt-semantics.md#datum-reference-frames).
- [x] Single-segment position-pattern evaluation with size checks and
  RFS/MMC/LMC feature modifiers.
- [x] Pin/hole mating-boundary calculation helpers.
- [x] Circular-aperture occlusion calculations and Monte Carlo visualization.
- [x] SVG characteristic/modifier assets and a Windows packaging workflow.

## Next: robustness and usability

- [ ] Align package metadata, source runtime guidance, and optional CAD dependencies.
- [ ] Replace machine-specific DLL paths with portable configuration.
- [ ] Consistent unit conversion and labels across CAD, measurement, and analysis.
- [ ] More explicit unresolved-link and incomplete-datum save workflows.
- [ ] Persist preview/layout preferences where useful.
- [ ] Reproducible native graphics checks across supported environments.
- [ ] Larger-assembly performance work and clearer numerical error reporting.

## Analysis and data exchange

- [ ] CSV/Excel import and export.
- [ ] Engineering reports and PDF export.
- [ ] Sensitivity analysis and cumulative/probability-density plots.
- [ ] Solver support for triangular/custom distributions and correlation.
- [ ] Broader process-capability and yield reporting.

The domain schema can already describe additional distributions and correlation
groups; the current numerical engines do not implement every schema option.

## CAD and GD&T expansion

- [ ] Cylinder fitting for spline-defined surfaces and broader analytic recognition.
- [ ] Automatic dimension/chain extraction and richer CAD annotation workflows.
- [ ] General axis/axis, skew, and material-boundary datum simulators.
- [ ] Datum feature shift, composite position controls, and orientation coupling.
- [ ] Flatness, parallelism, perpendicularity, circularity, cylindricity, and profile solvers.
- [ ] Full feature-control-frame editing and drawing generation.

An icon or schema type does not mean the corresponding solver exists.
Cylindrical datum recognition is implemented; cylindricity evaluation is not.

## Assembly variation and platform work

- [ ] Solve occurrence constraints and calculate assembly responses.
- [ ] Automatic chain detection, constraint graphs, and loop handling.
- [ ] Contact sequencing, deformation, and full 3D variation analysis.
- [ ] DXF exchange, plugins, collaboration, and optimization workflows.

The current occurrence/constraint model records design intent. It does not
provide a general assembly solver; the proposed first slice remains a
pin/hole assembly with a clearance response.
