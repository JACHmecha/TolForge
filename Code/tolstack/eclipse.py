"""Circle-circle occlusion ("eclipse") analysis.

Built for a specific real problem: a light-emitting aperture (e.g. an LED
hole in an injection-molded part) covered by a second aperture (e.g. a
decorative sticker hole) that may be offset in position and/or a
different diameter due to manufacturing tolerances on both parts. This
module answers "how much of the light gets blocked, given the tolerance
stack-up on both hole diameters and their relative position?"

Both apertures are modeled as circles lying in the same plane
(perpendicular to the shared optical axis, e.g. the LED's axis). The
overlapping ("open") area between them is computed with the standard
closed-form circle-circle intersection ("lens") area formula - no
iterative solver, no dependency beyond numpy.

The eclipse fraction is defined relative to the smaller of the two
apertures (the theoretical maximum light-through area achievable for
that diameter pair, i.e. perfectly concentric):
    0.0 = fully open (as good as it can be for these two diameters)
    1.0 = fully blocked (centers far enough apart that the circles don't
          overlap at all)

This intentionally does NOT reuse tolstack.stack.Stack directly - Stack
is built around a linear signed sum of dimensions (worst_case/rss/monte
carlo all assume the stack combines via addition/subtraction), whereas
eclipse fraction is a nonlinear function of four independent inputs
(two diameters, two position-offset components). What IS reused is the
same per-dimension sampling convention (uniform when no Cpk is given,
Cpk-calibrated split-normal otherwise) via ToleranceInput.sample(),
mirroring Stack.monte_carlo's own per-dimension sampling so results from
both tools are apples-to-apples if compared.
"""

from dataclasses import dataclass
from math import hypot
import numpy as np

from .models import finite_number, parse_optional_cpk
from .analysis import parse_seed


def _positive_iterations(iterations: int) -> int:
    if isinstance(iterations, (bool, np.bool_)) or not isinstance(iterations, (int, np.integer)) or iterations <= 0:
        raise ValueError("Iterations must be a positive integer.")
    return int(iterations)


def _random_stream(seed=None, rng: np.random.Generator | None = None):
    """Resolve an explicit generator, retaining the legacy stream by default."""
    if seed is not None and rng is not None:
        raise ValueError("Provide either a seed or a random generator, not both.")
    seed = parse_seed(seed)
    if rng is not None and not isinstance(rng, np.random.Generator):
        raise ValueError("rng must be a NumPy Generator.")
    return rng if rng is not None else (np.random.default_rng(seed) if seed is not None else np.random)


def _overlap_fraction(r1: float, r2: float, d: float) -> tuple[float, float]:
    """Return overlap / smaller-circle area without squaring physical lengths."""
    r1 = finite_number(r1, "First radius")
    r2 = finite_number(r2, "Second radius")
    d = finite_number(d, "Center distance")
    if r1 <= 0 or r2 <= 0:
        raise ValueError("Circle radii must be greater than 0.")
    if d < 0:
        raise ValueError("Center distance must be nonnegative.")

    smaller_radius = min(r1, r2)
    larger_radius = max(r1, r2)
    # Compare differences instead of radius sums; the latter can overflow
    # or round away a small aperture at the large aperture's edge.
    if d >= larger_radius and d - larger_radius >= smaller_radius:
        return 0.0, smaller_radius
    if d < larger_radius and larger_radius - d >= smaller_radius:
        return 1.0, smaller_radius

    # Scale all lengths before sums/products: finite lengths can otherwise
    # overflow even when their dimensionless eclipse fraction is valid.
    scale = max(r1, r2, d)
    a, b, distance = smaller_radius / scale, larger_radius / scale, d / scale
    smaller = a
    if smaller <= 0:
        raise ValueError("Circle geometry is too small relative to its scale to evaluate.")

    # Reorder the two small differences and multiply square roots instead
    # of taking sqrt(product), keeping subnormal but valid ratios usable.
    chord_term = (
        np.sqrt(max(a + (b - distance), 0.0))
        * np.sqrt(max(a + (distance - b), 0.0))
        * np.sqrt(max(b + (distance - a), 0.0))
        * np.sqrt(distance + a + b)
    )
    # Summing the two circular segments avoids subtracting a large triangle
    # from a tiny overlap when one aperture is much smaller than the other.
    # Near-equal radii require the radius difference first, to retain d^2
    # for tiny offsets. Unequal radii require the distance difference first.
    radius_difference = (a - b) * (a + b)
    denominator_a = distance**2 + radius_difference if a >= b / 2 else (distance - b) * (distance + b) + a**2
    denominator_b = distance**2 - radius_difference
    angle_a = np.arctan2(chord_term, denominator_a)
    angle_b = np.arctan2(chord_term, denominator_b)

    def segment_fraction(radius, angle):
        if angle < 1e-3:
            # theta - sin(theta) cos(theta), evaluated without cancellation.
            # Combining the radius ratio with theta first also avoids
            # squaring an enormous ratio or underflowing theta cubed.
            return (radius * angle / smaller)**2 * angle * (
                2 / 3 - angle**2 * (2 / 15 - angle**2 * 4 / 315)
            ) / np.pi
        return (radius / smaller)**2 * (angle - np.sin(angle) * np.cos(angle)) / np.pi

    overlap = finite_number(
        segment_fraction(a, angle_a) + segment_fraction(b, angle_b),
        "Circle overlap fraction",
    )
    return float(np.clip(overlap, 0.0, 1.0)), smaller_radius


def circle_intersection_area(r1: float, r2: float, d: float) -> float:
    """Area of overlap between two circles of radius r1, r2 whose centers
    are `d` apart (the classic "circular segment" / lens-area formula).
    """
    overlap, smaller_radius = _overlap_fraction(r1, r2, d)
    if overlap == 0:
        return 0.0
    with np.errstate(over="ignore", under="ignore", invalid="ignore"):
        area = finite_number(overlap * np.pi * smaller_radius * smaller_radius, "Circle intersection area")
    if area == 0:
        raise ValueError("Circle intersection area is too small to represent.")
    return area


def eclipse_fraction(r1: float, r2: float, d: float) -> float:
    """Fraction of the theoretical max aperture (the smaller circle, fully
    concentric) that is blocked given the actual center distance `d`.
    """
    overlap, _ = _overlap_fraction(r1, r2, d)
    return 1.0 - overlap


@dataclass
class ToleranceInput:
    """One randomly-varying quantity for the eclipse analysis: a diameter
    or a positional offset component. Same uniform-vs-Cpk sampling
    convention as tolstack.stack.Stack.monte_carlo.
    """

    name: str
    nominal: float
    tol_plus: float
    tol_minus: float
    cpk: float | None = None

    def __post_init__(self):
        self._validated_values()

    def _validated_values(self) -> tuple[float, float, float, float | None]:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("Tolerance input name must not be empty.")
        nominal = finite_number(self.nominal, f"{self.name}: nominal")
        plus = finite_number(self.tol_plus, f"{self.name}: positive tolerance")
        minus = finite_number(self.tol_minus, f"{self.name}: negative tolerance")
        if plus < 0 or minus < 0:
            raise ValueError(f"{self.name}: tolerance magnitudes must be nonnegative.")
        finite_number(nominal - minus, f"{self.name}: lower tolerance limit")
        finite_number(nominal + plus, f"{self.name}: upper tolerance limit")
        return nominal, plus, minus, parse_optional_cpk(self.cpk, f"{self.name}: Cpk")

    def sample(
        self, iterations: int, default_cpk: float | None = None, *,
        rng: np.random.Generator | None = None,
    ) -> np.ndarray:
        """Sample from an explicit Generator or the legacy NumPy stream.

        Cpk normal draws remain unbounded in either case.
        """
        iterations = _positive_iterations(iterations)
        nominal, plus, minus, input_cpk = self._validated_values()
        default_cpk = parse_optional_cpk(default_cpk, "Global Cpk")
        random = _random_stream(rng=rng)
        cpk = input_cpk if input_cpk is not None else default_cpk
        try:
            with np.errstate(over="raise", invalid="raise", divide="raise"):
                if cpk is None:
                    values = random.uniform(nominal - minus, nominal + plus, iterations)
                else:
                    # Dividing successively avoids overflowing 3 * large Cpk.
                    sigma_plus = finite_number(plus / 3 / cpk, f"{self.name}: positive sampling deviation")
                    sigma_minus = finite_number(minus / 3 / cpk, f"{self.name}: negative sampling deviation")
                    z = random.standard_normal(iterations)
                    offsets = np.where(z >= 0, z * sigma_plus, z * sigma_minus)
                    values = nominal + offsets
        except (FloatingPointError, OverflowError) as exc:
            raise ValueError(f"{self.name}: sampling exceeds the finite numeric range.") from exc
        if not np.all(np.isfinite(values)):
            raise ValueError(f"{self.name}: generated samples must be finite.")
        return values

    def corners(self) -> tuple:
        """The two extreme values of this input's tolerance range - used
        by worst_case() below, since for an axis-aligned rectangular
        tolerance zone the extreme of any monotonic function always
        lands on a corner."""
        nominal, plus, minus, _ = self._validated_values()
        return (nominal - minus, nominal + plus)


@dataclass
class EclipseInputs:
    handle_diameter: ToleranceInput
    sticker_diameter: ToleranceInput
    offset_x: ToleranceInput
    offset_y: ToleranceInput

    def validate(self):
        for name in ("handle_diameter", "sticker_diameter", "offset_x", "offset_y"):
            value = getattr(self, name)
            if not isinstance(value, ToleranceInput):
                raise ValueError(f"{name} must be a ToleranceInput.")
            lower, _ = value.corners()
            if name.endswith("diameter") and lower <= 0:
                raise ValueError(f"{value.name}: diameter and its full tolerance range must be greater than 0.")


@dataclass
class EclipseMonteCarloResult:
    samples: np.ndarray  # eclipse fraction per iteration, each in [0, 1]
    mean: float
    std_dev: float
    minimum: float
    maximum: float

    def __post_init__(self):
        self._validated_samples()

    def _validated_samples(self) -> np.ndarray:
        try:
            samples = np.asarray(self.samples, dtype=float)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("Eclipse samples must be finite fractions from 0 to 1.") from exc
        if samples.ndim != 1 or samples.size == 0 or not np.all(np.isfinite(samples)) or np.any((samples < 0) | (samples > 1)):
            raise ValueError("Eclipse samples must be a nonempty array of finite fractions from 0 to 1.")
        expected = (np.mean(samples), np.std(samples), np.min(samples), np.max(samples))
        for name, actual in zip(("mean", "std_dev", "minimum", "maximum"), expected):
            statistic = finite_number(getattr(self, name), f"Eclipse {name}")
            if not np.isclose(statistic, actual, rtol=1e-12, atol=1e-15):
                raise ValueError(f"Eclipse {name} does not match its samples.")
        return samples

    def probability_above(self, threshold: float) -> float:
        """Fraction of samples whose eclipse fraction exceeds `threshold`
        (e.g. threshold=0.3 -> "chance of losing more than 30% of the
        light-through area to misalignment")."""
        threshold = finite_number(threshold, "Eclipse threshold")
        if not 0 <= threshold <= 1:
            raise ValueError("Eclipse threshold must be from 0 to 1.")
        return float(np.mean(self._validated_samples() > threshold))


def run_monte_carlo(
    inputs: EclipseInputs, iterations: int = 10000, default_cpk: float | None = None, *,
    seed: int | None = None, rng: np.random.Generator | None = None,
) -> EclipseMonteCarloResult:
    """Sample positive aperture diameters without repairing invalid draws.

    The specified diameter tolerance ranges must be wholly positive. Cpk
    sampling remains unbounded: any nonpositive draw invalidates the run,
    rather than being clipped to zero or silently sampled again.

    Pass a seed for repeatable studies or a Generator for a caller-owned
    isolated stream. With neither, existing np.random.seed() callers retain
    their original sampling sequence.
    """
    iterations = _positive_iterations(iterations)
    default_cpk = parse_optional_cpk(default_cpk, "Global Cpk")
    random = _random_stream(seed, rng)
    inputs.validate()
    sample_rng = None if random is np.random else random
    d_handle = inputs.handle_diameter.sample(iterations, default_cpk, rng=sample_rng)
    d_sticker = inputs.sticker_diameter.sample(iterations, default_cpk, rng=sample_rng)
    dx = inputs.offset_x.sample(iterations, default_cpk, rng=sample_rng)
    dy = inputs.offset_y.sample(iterations, default_cpk, rng=sample_rng)

    if np.any(d_handle <= 0) or np.any(d_sticker <= 0):
        raise ValueError("Generated diameters must be greater than 0; review the diameter/Cpk assumptions.")
    r1 = d_handle / 2
    r2 = d_sticker / 2
    with np.errstate(over="ignore", invalid="ignore"):
        d = np.hypot(dx, dy)
    if not np.all(np.isfinite(d)):
        raise ValueError("Generated center distances exceed the finite numeric range.")

    # circle_intersection_area/eclipse_fraction aren't vectorized (the
    # branching on d vs r1+r2/|r1-r2| doesn't translate cleanly to numpy
    # without np.select noise) - a plain Python loop over `iterations`
    # samples is simple and correct; if this becomes the bottleneck for
    # very large iteration counts, it's the first thing worth vectorizing.
    samples = np.empty(iterations)
    for i in range(iterations):
        samples[i] = eclipse_fraction(r1[i], r2[i], d[i])

    return EclipseMonteCarloResult(
        samples=samples,
        mean=float(np.mean(samples)),
        std_dev=float(np.std(samples)),
        minimum=float(np.min(samples)),
        maximum=float(np.max(samples)),
    )


def _box_distance_extremes(x_range: tuple, y_range: tuple) -> tuple[float, float]:
    """Given axis-aligned (min, max) ranges for x and y, return the
    (nearest, farthest) distance from the origin to any point in that
    box.

    Farthest point from the origin in an axis-aligned box is always at
    one of the 4 corners. Nearest point is NOT always at a corner - if
    the box straddles the origin (as an offset tolerance zone centered
    near 0 typically does), the nearest point is the origin itself
    (distance 0), not any corner. The general nearest-point formula is
    just clamping (0, 0) into the box componentwise.
    """
    x_min, x_max = x_range
    y_min, y_max = y_range
    corners = [(x_min, y_min), (x_min, y_max), (x_max, y_min), (x_max, y_max)]
    farthest = finite_number(max(hypot(cx, cy) for cx, cy in corners), "Farthest center distance")
    nearest_x = min(max(0.0, x_min), x_max)
    nearest_y = min(max(0.0, y_min), y_max)
    nearest = finite_number(hypot(nearest_x, nearest_y), "Nearest center distance")
    return nearest, farthest


def worst_case(inputs: EclipseInputs) -> tuple[float, float]:
    """Numerical (min, max) eclipse fraction over the whole tolerance zone.

    Diameter corners, equal-diameter interior points and possible
    stationary smaller-diameter minima are evaluated. The larger aperture
    always improves coverage when enlarged; smaller-aperture normalization
    means diameter corners alone do not bound the fraction.
    For the position offset (dx, dy), eclipse_fraction only depends on
    their combined magnitude d = sqrt(dx^2+dy^2), which - unlike the
    per-axis tolerance corners - has its true min/max computed via
    _box_distance_extremes() rather than assumed to land on a (dx, dy)
    corner (see that function's docstring for why the naive corner
    assumption is wrong for the minimum).
    """
    inputs.validate()
    d_min, d_max = _box_distance_extremes(inputs.offset_x.corners(), inputs.offset_y.corners())

    handle_range = inputs.handle_diameter.corners()
    sticker_range = inputs.sticker_diameter.corners()
    fractions = []
    for dh in handle_range:
        for ds in sticker_range:
            for d in (d_min, d_max):
                r1, r2 = dh / 2, ds / 2
                fractions.append(eclipse_fraction(r1, r2, d))

    # For a fixed smaller circle the larger circle improves coverage
    # monotonically. Thus the maximum can also lie where diameters match;
    # the smallest common diameter has the largest normalized offset.
    common_lower = max(handle_range[0], sticker_range[0])
    common_upper = min(handle_range[1], sticker_range[1])
    if common_lower <= common_upper:
        for diameter in (common_lower, common_upper):
            for d in (d_min, d_max):
                fractions.append(eclipse_fraction(diameter / 2, diameter / 2, d))

    # The minimum uses the nearest offset and a largest permitted outer
    # aperture. If its center lies outside that aperture, the smaller
    # radius can have an interior minimum. For outer radius R, offset d
    # and outer-circle half-angle beta, stationarity is beta/sin(beta)=d/R.
    for larger, smaller_range in ((handle_range[1], sticker_range), (sticker_range[1], handle_range)):
        candidate = _stationary_smaller_radius(larger / 2, d_min)
        if candidate is not None and smaller_range[0] / 2 <= candidate <= smaller_range[1] / 2:
            fractions.append(eclipse_fraction(candidate, larger / 2, d_min))
    return min(fractions), max(fractions)


def _stationary_smaller_radius(larger: float, distance: float) -> float | None:
    if distance <= larger or distance - larger >= larger:
        return None
    ratio = distance / larger
    beta_upper = np.arccos(ratio / 2)

    def excess(beta):
        if beta < 1e-3:
            return beta**2 * (1 / 6 + beta**2 * (7 / 360 + beta**2 * 31 / 15120))
        return beta / np.sin(beta) - 1

    target = (distance - larger) / larger
    if excess(beta_upper) < target:
        return None
    beta_lower = 0.0
    for _ in range(64):
        beta = (beta_lower + beta_upper) / 2
        if excess(beta) < target:
            beta_lower = beta
        else:
            beta_upper = beta
    beta = (beta_lower + beta_upper) / 2
    radius_ratio = np.sqrt(target**2 + 4 * ratio * np.sin(beta / 2)**2)
    return float(larger * radius_ratio)
