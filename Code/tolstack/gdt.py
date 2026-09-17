"""GD&T position tolerance (ASME Y14.5 / ISO 1101 style) evaluation.

Scope, stated explicitly rather than implied:
- Datums are referenced RFS (no datum-feature-shift / floating datum
  reference frame). Real Y14.5 allows datum features to carry their own
  MMC/LMC modifiers, which lets the datum reference frame itself shift/
  rotate within a simulator boundary - that's a meaningfully harder
  problem (it couples the datum fit to the feature fit) and is
  deliberately NOT modeled here.
- Single-segment position tolerancing only - one diametral zone (T)
  shared by the whole pattern, referenced to one datum reference frame.
  Composite/multiple-single-segment position tolerancing (nested zones
  at different precedence) isn't modeled.
- Assumes each toleranced feature's own axis is parallel (or close to
  it) to the datum reference frame's Z axis - true for the very common
  case of a hole perpendicular to its primary datum plane. If a feature
  is tilted relative to the DRF, projecting its center into the DRF's
  XY plane the way this module does isn't quite measuring position in
  the plane actually perpendicular to that feature's own axis.

A "datum feature" here is just (point, direction) - a point on/in the
feature and its unit normal/axis. That's deliberately the same shape as
what MeasurementMixin already produces: centroid+normal for a face
(_fit_normal_or_direction) or center+normal for a circular edge/hole
(_fit_circle) - no new geometry extraction needed, just reused.
"""

from dataclasses import dataclass
from typing import Literal
import numpy as np


# ----------------------------------------------------------------------
# Datum reference frame
# ----------------------------------------------------------------------

@dataclass
class DatumFeature:
    point: np.ndarray
    direction: np.ndarray  # unit vector

    def __post_init__(self):
        self.point = np.asarray(self.point, dtype=float)
        direction = np.asarray(self.direction, dtype=float)
        norm = np.linalg.norm(direction)
        if norm == 0:
            raise ValueError("Datum feature direction cannot be a zero vector.")
        self.direction = direction / norm


@dataclass
class DatumReferenceFrame:
    origin: np.ndarray
    x_axis: np.ndarray
    y_axis: np.ndarray
    z_axis: np.ndarray

    def to_local_xy(self, world_point) -> tuple:
        """Projects a world-space point into this frame's XY plane -
        the plane in which position error is measured (see the module
        docstring's note on the feature-axis-parallel-to-Z assumption).
        """
        delta = np.asarray(world_point, dtype=float) - self.origin
        x = float(np.dot(delta, self.x_axis))
        y = float(np.dot(delta, self.y_axis))
        return x, y


def build_datum_reference_frame(
    primary: DatumFeature, secondary: DatumFeature, tertiary: DatumFeature
) -> DatumReferenceFrame:
    """Builds a right-handed orthonormal datum reference frame from three
    datum features, in precedence order (primary constrains orientation
    the most, tertiary just fixes the one remaining translational DOF).

    - Z axis = primary's direction.
    - X axis = secondary's direction, Gram-Schmidt-orthogonalized against
      Z (i.e. secondary only needs to be roughly perpendicular to
      primary - which real datum features should be by design intent -
      not exactly, since Gram-Schmidt removes whatever component of
      secondary's direction already lies along Z).
    - Y axis = Z x X, completing the right-handed frame.
    - Origin: primary and secondary each pin down one plane (a point p
      lies on datum i's plane iff dot(p - feature_i.point, feature_i.
      direction) == 0); those two plane constraints leave one free
      parameter along Y, which tertiary's point fixes - this works
      whether tertiary is a planar face (its own plane's Y-projection)
      or a point-like feature such as a hole center used as a locator,
      per the user's own "faces + edge midpoint/normal" datum vocabulary.

      Solved as a 3x3 linear system with rows [Z, X, Y] (each already
      unit vectors) and right-hand side [Z.p1, X.p2, Y.p3] - since those
      three rows are themselves an orthonormal basis, the system is
      guaranteed well-conditioned (its own transpose is its inverse), no
      degenerate-matrix risk from the construction itself.
    """
    z_axis = primary.direction

    x_raw = secondary.direction - np.dot(secondary.direction, z_axis) * z_axis
    x_norm = np.linalg.norm(x_raw)
    if x_norm < 1e-9:
        raise ValueError(
            "Secondary datum's direction is (nearly) parallel to the primary "
            "datum's - can't establish an orientation from these two. Pick a "
            "secondary datum feature that isn't parallel to the primary."
        )
    x_axis = x_raw / x_norm
    y_axis = np.cross(z_axis, x_axis)

    basis = np.array([z_axis, x_axis, y_axis])  # orthonormal, rows
    rhs = np.array([
        np.dot(z_axis, primary.point),
        np.dot(x_axis, secondary.point),
        np.dot(y_axis, tertiary.point),
    ])
    origin = basis.T @ rhs  # exact since `basis` is orthonormal (basis.T == basis^-1)

    return DatumReferenceFrame(origin=origin, x_axis=x_axis, y_axis=y_axis, z_axis=z_axis)


# ----------------------------------------------------------------------
# Bonus tolerance (MMC / LMC) and position evaluation
# ----------------------------------------------------------------------

Modifier = Literal["RFS", "MMC", "LMC"]
FeatureKind = Literal["hole", "pin"]


def size_limits(mmc_size: float, lmc_size: float, feature_kind: FeatureKind) -> tuple[float, float]:
    """Return conventional (lower, upper) size limits and validate MMC/LMC order."""
    mmc_size, lmc_size = float(mmc_size), float(lmc_size)
    if feature_kind == "hole":
        if mmc_size > lmc_size:
            raise ValueError("For a hole, MMC must be less than or equal to LMC.")
        return mmc_size, lmc_size
    if feature_kind == "pin":
        if lmc_size > mmc_size:
            raise ValueError("For a pin, LMC must be less than or equal to MMC.")
        return lmc_size, mmc_size
    raise ValueError(f"Unknown feature kind '{feature_kind}'.")


def size_margin(
    actual_size: float, mmc_size: float, lmc_size: float, feature_kind: FeatureKind,
) -> float:
    """Signed distance to the nearest size limit; negative means out of size."""
    lower, upper = size_limits(mmc_size, lmc_size, feature_kind)
    return min(float(actual_size) - lower, upper - float(actual_size))


def virtual_condition(
    mmc_size: float, geometric_tolerance_diameter: float, feature_kind: FeatureKind,
) -> float:
    """Worst-case mating boundary for a feature controlled at MMC.

    An internal feature loses usable diameter to geometric error; an external
    feature gains an equivalent outer boundary.
    """
    mmc_size = float(mmc_size)
    tolerance = float(geometric_tolerance_diameter)
    if tolerance < 0:
        raise ValueError("Geometric tolerance cannot be negative.")
    if feature_kind == "hole":
        return mmc_size - tolerance
    if feature_kind == "pin":
        return mmc_size + tolerance
    raise ValueError(f"Unknown feature kind '{feature_kind}'.")


def actual_mating_boundary(
    actual_size: float, diametral_geometric_error: float, feature_kind: FeatureKind,
) -> float:
    """Effective mating boundary of one manufactured feature."""
    if diametral_geometric_error < 0:
        raise ValueError("Geometric error cannot be negative.")
    if feature_kind == "hole":
        return float(actual_size) - float(diametral_geometric_error)
    if feature_kind == "pin":
        return float(actual_size) + float(diametral_geometric_error)
    raise ValueError(f"Unknown feature kind '{feature_kind}'.")


def bonus_tolerance(
    actual_size: float, mmc_size: float, lmc_size: float,
    modifier: Modifier, feature_kind: FeatureKind = "hole",
) -> float:
    """Bonus (extra) position tolerance earned from the feature's actual
    size departing from its material-condition boundary.

    MMC (maximum material condition) = the size with the MOST material
    present: smallest allowed diameter for a hole, largest allowed
    diameter for a pin/boss. LMC is the opposite extreme. `feature_kind`
    controls which direction of departure earns bonus - getting this
    backwards for a pin vs. a hole is a classic GD&T mistake, so it's an
    explicit, required parameter rather than an assumption.
    """
    if modifier == "RFS":
        return 0.0

    if feature_kind == "hole":
        if modifier == "MMC":  # MMC = smallest hole; bonus grows as it gets bigger
            return max(0.0, actual_size - mmc_size)
        elif modifier == "LMC":  # LMC = largest hole; bonus grows as it gets smaller
            return max(0.0, lmc_size - actual_size)
    elif feature_kind == "pin":
        if modifier == "MMC":  # MMC = largest pin; bonus grows as it gets smaller
            return max(0.0, mmc_size - actual_size)
        elif modifier == "LMC":  # LMC = smallest pin; bonus grows as it gets bigger
            return max(0.0, actual_size - lmc_size)

    raise ValueError(f"Unknown modifier/feature_kind combination: {modifier}/{feature_kind}")


def position_error(dx: float, dy: float) -> float:
    """Diametral position error - the position tolerance zone is a
    diameter, so the error is 2x the radial center offset, not the
    offset itself."""
    return 2.0 * float(np.hypot(dx, dy))


@dataclass
class PositionEvaluation:
    position_error: float
    bonus_tolerance: float
    allowed_tolerance: float
    margin: float  # worst of size and position margins
    passes: bool
    position_margin: float
    size_margin: float
    position_conforming: bool
    size_conforming: bool
    virtual_condition: float | None
    actual_mating_boundary: float


def evaluate_position(
    dx: float, dy: float, base_tolerance_diameter: float,
    actual_size: float, mmc_size: float, lmc_size: float,
    modifier: Modifier = "RFS", feature_kind: FeatureKind = "hole",
) -> PositionEvaluation:
    error = position_error(dx, dy)
    lower_size, upper_size = size_limits(mmc_size, lmc_size, feature_kind)
    bounded_size = float(np.clip(actual_size, lower_size, upper_size))
    bonus = bonus_tolerance(bounded_size, mmc_size, lmc_size, modifier, feature_kind)
    allowed = base_tolerance_diameter + bonus
    position_margin_value = allowed - error
    size_margin_value = size_margin(actual_size, mmc_size, lmc_size, feature_kind)
    position_conforming = position_margin_value >= 0
    size_conforming = size_margin_value >= 0
    return PositionEvaluation(
        position_error=error, bonus_tolerance=bonus, allowed_tolerance=allowed,
        margin=min(position_margin_value, size_margin_value),
        passes=position_conforming and size_conforming,
        position_margin=position_margin_value,
        size_margin=size_margin_value,
        position_conforming=position_conforming,
        size_conforming=size_conforming,
        virtual_condition=(
            virtual_condition(mmc_size, base_tolerance_diameter, feature_kind)
            if modifier == "MMC" else None
        ),
        actual_mating_boundary=actual_mating_boundary(actual_size, error, feature_kind),
    )


@dataclass
class PinHoleClearanceEvaluation:
    hole_virtual_condition: float
    pin_virtual_condition: float
    guaranteed_clearance: float
    guaranteed_assembly: bool
    actual_effective_clearance: float | None = None


def evaluate_pin_hole_clearance(
    hole_mmc_size: float,
    hole_position_tolerance: float,
    pin_mmc_size: float,
    pin_position_tolerance: float,
    *,
    hole_actual_size: float | None = None,
    hole_position_error: float = 0.0,
    pin_actual_size: float | None = None,
    pin_position_error: float = 0.0,
) -> PinHoleClearanceEvaluation:
    """Evaluate diametral clearance between one hole and one pin at MMC.

    ``guaranteed_clearance`` compares the two virtual-condition boundaries.
    Optional actual sizes/errors additionally report the effective clearance
    for one manufactured pair.
    """
    hole_boundary = virtual_condition(hole_mmc_size, hole_position_tolerance, "hole")
    pin_boundary = virtual_condition(pin_mmc_size, pin_position_tolerance, "pin")
    guaranteed_clearance = hole_boundary - pin_boundary
    actual_clearance = None
    if (hole_actual_size is None) != (pin_actual_size is None):
        raise ValueError("Provide both actual sizes or neither.")
    if hole_actual_size is not None:
        actual_clearance = actual_mating_boundary(
            hole_actual_size, hole_position_error, "hole"
        ) - actual_mating_boundary(pin_actual_size, pin_position_error, "pin")
    return PinHoleClearanceEvaluation(
        hole_virtual_condition=hole_boundary,
        pin_virtual_condition=pin_boundary,
        guaranteed_clearance=guaranteed_clearance,
        guaranteed_assembly=guaranteed_clearance >= 0,
        actual_effective_clearance=actual_clearance,
    )


# ----------------------------------------------------------------------
# Pattern-level definition and Monte Carlo
# ----------------------------------------------------------------------

@dataclass
class PatternFeature:
    """One feature within a pattern position control.

    basic_x/basic_y: theoretically-exact (untoleranced) location in the
    datum reference frame, per the drawing.
    actual_x/actual_y: as-measured (or as-modeled, for a nominal STEP
    check) location in the same frame - dx/dy = actual - basic is what
    feeds position_error().
    size_nominal/size_tol_plus/size_tol_minus/size_cpk: the feature's own
    diameter and its tolerance/distribution, for Monte Carlo sampling
    and for computing MMC/LMC bonus at each sampled size.
    """

    name: str
    basic_x: float
    basic_y: float
    actual_x: float
    actual_y: float
    size_nominal: float
    size_tol_plus: float
    size_tol_minus: float
    size_cpk: float | None = None
    position_tol_plus_x: float = 0.0
    position_tol_minus_x: float = 0.0
    position_tol_plus_y: float = 0.0
    position_tol_minus_y: float = 0.0
    position_cpk: float | None = None

    def _sample(self, nominal, tol_plus, tol_minus, cpk, default_cpk, iterations):
        cpk = cpk if cpk is not None else default_cpk
        if cpk is None:
            return np.random.uniform(nominal - tol_minus, nominal + tol_plus, iterations)
        if cpk <= 0:
            raise ValueError(f"Cpk for '{self.name}' must be > 0, not {cpk}.")
        sigma_plus, sigma_minus = tol_plus / (3 * cpk), tol_minus / (3 * cpk)
        z = np.random.standard_normal(iterations)
        return nominal + np.where(z >= 0, z * sigma_plus, z * sigma_minus)

    def sample_size(self, iterations: int, default_cpk: float | None = None) -> np.ndarray:
        return self._sample(
            self.size_nominal, self.size_tol_plus, self.size_tol_minus,
            self.size_cpk, default_cpk, iterations,
        )

    def sample_position(self, iterations: int, default_cpk: float | None = None) -> tuple:
        """Samples the manufactured position AROUND this feature's actual
        (as-measured/as-modeled) location - i.e. this treats `actual_x/y`
        as the process's own nominal aim point, with
        position_tol_plus/minus_x/y as its own manufacturing variation.
        Set the position tolerances to 0 to evaluate a single, exact
        (non-statistical) as-measured location instead.
        """
        cpk = self.position_cpk if self.position_cpk is not None else default_cpk
        x = self._sample(self.actual_x, self.position_tol_plus_x, self.position_tol_minus_x, cpk, default_cpk, iterations)
        y = self._sample(self.actual_y, self.position_tol_plus_y, self.position_tol_minus_y, cpk, default_cpk, iterations)
        return x, y


@dataclass
class PatternPositionControl:
    features: list  # list[PatternFeature]
    base_tolerance_diameter: float
    modifier: Modifier = "RFS"
    mmc_size: float = 0.0
    lmc_size: float = 0.0
    feature_kind: FeatureKind = "hole"


def evaluate_pattern_nominal(control: PatternPositionControl) -> list:
    """Deterministic, single-point evaluation (no sampling) - each
    feature's as-measured/as-modeled location and nominal size checked
    once against the callout. Useful for validating a single STEP/CAD
    model or a single inspected part, as opposed to predicting
    production conformance."""
    results = []
    for feature in control.features:
        dx = feature.actual_x - feature.basic_x
        dy = feature.actual_y - feature.basic_y
        evaluation = evaluate_position(
            dx, dy, control.base_tolerance_diameter,
            feature.size_nominal, control.mmc_size, control.lmc_size,
            control.modifier, control.feature_kind,
        )
        results.append((feature.name, evaluation))
    return results


@dataclass
class PatternMonteCarloResult:
    per_feature_fail_rate: dict  # name -> fraction of samples that failed
    per_feature_size_fail_rate: dict
    per_feature_position_fail_rate: dict
    pattern_fail_rate: float  # fraction of samples where >=1 feature failed
    worst_feature_margin: np.ndarray  # per-sample minimum margin across the pattern


def run_pattern_monte_carlo(
    control: PatternPositionControl, iterations: int = 10000, default_cpk: float | None = None
) -> PatternMonteCarloResult:
    """Each feature's position and size are sampled independently (no
    shared/common-cause variation across the pattern is modeled - e.g. a
    single molding-shift-affecting-all-4-holes-together effect isn't
    captured here; see the module docstring's datum-shift scope note,
    which is the same underlying simplification). The pattern fails a
    given sample if ANY feature in it is out of tolerance for that
    sample - that's the correct definition of pattern conformance, even
    though each feature is sampled independently.
    """
    n = len(control.features)
    margins = np.empty((n, iterations))
    per_feature_fail_rate = {}
    per_feature_size_fail_rate = {}
    per_feature_position_fail_rate = {}

    lower_size, upper_size = size_limits(
        control.mmc_size, control.lmc_size, control.feature_kind
    )

    for i, feature in enumerate(control.features):
        sizes = feature.sample_size(iterations, default_cpk)
        xs, ys = feature.sample_position(iterations, default_cpk)
        dxs = xs - feature.basic_x
        dys = ys - feature.basic_y

        errors = 2.0 * np.hypot(dxs, dys)
        bounded_sizes = np.clip(sizes, lower_size, upper_size)
        if control.modifier == "RFS":
            bonuses = np.zeros(iterations)
        else:
            bonuses = np.array([
                bonus_tolerance(s, control.mmc_size, control.lmc_size, control.modifier, control.feature_kind)
                for s in bounded_sizes
            ])
        allowed = control.base_tolerance_diameter + bonuses
        position_margins = allowed - errors
        size_margins = np.minimum(sizes - lower_size, upper_size - sizes)
        margin = np.minimum(position_margins, size_margins)
        margins[i] = margin
        per_feature_fail_rate[feature.name] = float(np.mean(margin < 0))
        per_feature_size_fail_rate[feature.name] = float(np.mean(size_margins < 0))
        per_feature_position_fail_rate[feature.name] = float(np.mean(position_margins < 0))

    worst_feature_margin = margins.min(axis=0)
    pattern_fail_rate = float(np.mean(worst_feature_margin < 0))

    return PatternMonteCarloResult(
        per_feature_fail_rate=per_feature_fail_rate,
        per_feature_size_fail_rate=per_feature_size_fail_rate,
        per_feature_position_fail_rate=per_feature_position_fail_rate,
        pattern_fail_rate=pattern_fail_rate,
        worst_feature_margin=worst_feature_margin,
    )
