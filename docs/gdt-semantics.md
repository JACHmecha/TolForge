# GD&T calculation semantics

TolForge treats feature size and geometric conformance as separate mandatory
checks. A feature passes a position control only when both checks pass.

## Size and bonus tolerance

For a hole, MMC is the lower size limit and LMC is the upper limit. For a pin,
LMC is the lower limit and MMC is the upper limit. An actual size outside that
interval fails regardless of its position result.

MMC bonus tolerance is calculated from departure from MMC but capped at the
valid LMC departure. This prevents an out-of-size feature from earning an
unbounded position tolerance.

Monte Carlo analysis uses the worse of the sampled size margin and position
margin. Results report total, size-only, and position-only failure rates.

## Diametral mating boundaries

Position error and geometric tolerances are diametral values.

- Hole virtual condition: `hole MMC - hole position tolerance`
- Pin virtual condition: `pin MMC + pin position tolerance`
- Guaranteed diametral clearance: `hole VC - pin VC`

A nonnegative guaranteed clearance means the two perfect-form boundaries can
assemble at their respective virtual conditions. For one manufactured pair:

- Effective hole boundary: `actual hole size - hole position error`
- Effective pin boundary: `actual pin size + pin position error`
- Actual effective clearance: `effective hole - effective pin`

These calculations cover the mating-boundary question only. Datum mobility,
form error, orientation coupling, contact sequencing, and deformation remain
outside the current solver scope.
