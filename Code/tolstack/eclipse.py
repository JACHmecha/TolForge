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

from dataclasses import dataclass, field
import numpy as np


def circle_intersection_area(r1: float, r2: float, d: float) -> float:
    """Area of overlap between two circles of radius r1, r2 whose centers
    are `d` apart (the classic "circular segment" / lens-area formula).
    """
    r1, r2, d = float(r1), float(r2), float(abs(d))
    if r1 <= 0 or r2 <= 0:
        return 0.0
    if d >= r1 + r2:
        return 0.0
    if d <= abs(r1 - r2):
        # Smaller circle entirely inside the larger one.
        return float(np.pi * min(r1, r2) ** 2)

    a1 = np.arccos(np.clip((d**2 + r1**2 - r2**2) / (2 * d * r1), -1.0, 1.0))
    a2 = np.arccos(np.clip((d**2 + r2**2 - r1**2) / (2 * d * r2), -1.0, 1.0))
    triangle_term = 0.5 * np.sqrt(
        max((-d + r1 + r2) * (d + r1 - r2) * (d - r1 + r2) * (d + r1 + r2), 0.0)
    )
    return float(r1**2 * a1 + r2**2 * a2 - triangle_term)


def eclipse_fraction(r1: float, r2: float, d: float) -> float:
    """Fraction of the theoretical max aperture (the smaller circle, fully
    concentric) that is blocked given the actual center distance `d`.
    """
    reference_area = np.pi * min(r1, r2) ** 2
    if reference_area <= 0:
        return 1.0
    overlap = circle_intersection_area(r1, r2, d)
    return float(np.clip(1.0 - overlap / reference_area, 0.0, 1.0))


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

    def sample(self, iterations: int, default_cpk: float | None = None) -> np.ndarray:
        cpk = self.cpk if self.cpk is not None else default_cpk
        if cpk is None:
            return np.random.uniform(
                self.nominal - self.tol_minus, self.nominal + self.tol_plus, iterations
            )
        if cpk <= 0:
            raise ValueError(f"Cpk for '{self.name}' must be > 0, not {cpk}.")
        sigma_plus = self.tol_plus / (3 * cpk)
        sigma_minus = self.tol_minus / (3 * cpk)
        z = np.random.standard_normal(iterations)
        offsets = np.where(z >= 0, z * sigma_plus, z * sigma_minus)
        return self.nominal + offsets

    def corners(self) -> tuple:
        """The two extreme values of this input's tolerance range - used
        by worst_case() below, since for an axis-aligned rectangular
        tolerance zone the extreme of any monotonic function always
        lands on a corner."""
        return (self.nominal - self.tol_minus, self.nominal + self.tol_plus)


@dataclass
class EclipseInputs:
    handle_diameter: ToleranceInput
    sticker_diameter: ToleranceInput
    offset_x: ToleranceInput
    offset_y: ToleranceInput


@dataclass
class EclipseMonteCarloResult:
    samples: np.ndarray  # eclipse fraction per iteration, each in [0, 1]
    mean: float
    std_dev: float
    minimum: float
    maximum: float

    def probability_above(self, threshold: float) -> float:
        """Fraction of samples whose eclipse fraction exceeds `threshold`
        (e.g. threshold=0.3 -> "chance of losing more than 30% of the
        light-through area to misalignment")."""
        return float(np.mean(self.samples > threshold))


def run_monte_carlo(
    inputs: EclipseInputs, iterations: int = 10000, default_cpk: float | None = None
) -> EclipseMonteCarloResult:
    d_handle = inputs.handle_diameter.sample(iterations, default_cpk)
    d_sticker = inputs.sticker_diameter.sample(iterations, default_cpk)
    dx = inputs.offset_x.sample(iterations, default_cpk)
    dy = inputs.offset_y.sample(iterations, default_cpk)

    r1 = np.clip(d_handle, 0, None) / 2
    r2 = np.clip(d_sticker, 0, None) / 2
    d = np.sqrt(dx**2 + dy**2)

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
    farthest = max((cx**2 + cy**2) ** 0.5 for cx, cy in corners)
    nearest_x = min(max(0.0, x_min), x_max)
    nearest_y = min(max(0.0, y_min), y_max)
    nearest = (nearest_x**2 + nearest_y**2) ** 0.5
    return nearest, farthest


def worst_case(inputs: EclipseInputs) -> tuple[float, float]:
    """Exact (min, max) eclipse fraction over the whole tolerance zone.

    For the two diameters, eclipse_fraction's dependence on each isn't
    simply monotonic enough to trust without proof, so both of their
    corners are enumerated exhaustively (only 2x2=4 combinations, cheap).
    For the position offset (dx, dy), eclipse_fraction only depends on
    their combined magnitude d = sqrt(dx^2+dy^2), which - unlike the
    per-axis tolerance corners - has its true min/max computed via
    _box_distance_extremes() rather than assumed to land on a (dx, dy)
    corner (see that function's docstring for why the naive corner
    assumption is wrong for the minimum).
    """
    d_min, d_max = _box_distance_extremes(inputs.offset_x.corners(), inputs.offset_y.corners())

    fractions = []
    for dh in inputs.handle_diameter.corners():
        for ds in inputs.sticker_diameter.corners():
            for d in (d_min, d_max):
                r1, r2 = dh / 2, ds / 2
                fractions.append(eclipse_fraction(r1, r2, d))
    return min(fractions), max(fractions)
