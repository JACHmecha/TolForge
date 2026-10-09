"""Projected circular hole/pin interference in a common cross-sectional plane.

Area fractions refer to the pin, not the smaller circle. Radial clearance
is positive for a gap, zero for contact and negative for interference.
This model does not include tilt, insertion depth, deformation or GD&T.
"""

from dataclasses import dataclass
from math import ulp

import numpy as np

from .eclipse import (
    EclipseInputs, ToleranceInput, _box_distance_extremes,
    _overlap_fraction, _positive_iterations, _random_stream,
)
from .models import finite_number, parse_optional_cpk


_MIN_NORMAL_LENGTH = np.finfo(float).tiny


def _radial_clearance_from_radii(hole_radius: float, pin_radius: float, distance: float) -> float:
    """Internal scalar arithmetic on validated radii, without length squaring."""
    headroom = hole_radius - pin_radius
    clearance = headroom - distance
    if headroom >= _MIN_NORMAL_LENGTH and distance >= _MIN_NORMAL_LENGTH:
        roundoff = ulp(hole_radius) + ulp(pin_radius) + ulp(distance)
        if roundoff < min(headroom, distance) and abs(clearance) <= roundoff:
            return 0.0
    return clearance


def _radial_clearances_from_radii(hole_radius, pin_radius, distance) -> np.ndarray:
    """Vector equivalent of the scalar numerical-contact convention."""
    with np.errstate(over="ignore", invalid="ignore"):
        headroom = hole_radius - pin_radius
        clearance = headroom - distance
        roundoff = np.spacing(hole_radius) + np.spacing(pin_radius) + np.spacing(distance)
        contact = ((headroom >= _MIN_NORMAL_LENGTH) & (distance >= _MIN_NORMAL_LENGTH)
                   & (roundoff < np.minimum(headroom, distance)) & (np.abs(clearance) <= roundoff))
    return np.where(contact, 0.0, clearance)


def radial_clearance(hole_diameter: float, pin_diameter: float, distance: float) -> float:
    """Minimum radial clearance, with a bounded numerical-contact convention.

    Positive values mean a gap and negative values mean interference. Near
    internal tangency, positive radial headroom and distance can nearly
    cancel after floating-point unit conversion. A residual no larger than
    the sum of the three radius/distance operand ULPs is treated as contact.
    This is numerical roundoff, not an engineering acceptance tolerance.

    Centered oversized pins, equal-diameter offsets, and penetrations beyond
    that bound retain their signs. Subnormal headroom/distances are never
    snapped, nor are cases where the bound dominates the contact geometry.
    """
    hole = finite_number(hole_diameter, "Hole diameter")
    pin = finite_number(pin_diameter, "Pin diameter")
    distance = finite_number(distance, "Center distance")
    if hole <= 0 or pin <= 0:
        raise ValueError("Circle diameters must be greater than 0.")
    if distance < 0:
        raise ValueError("Center distance must be nonnegative.")
    return finite_number(_radial_clearance_from_radii(hole / 2, pin / 2, distance), "Radial clearance")


@dataclass
class PinHoleInputs:
    hole_diameter: ToleranceInput
    pin_diameter: ToleranceInput
    offset_x: ToleranceInput
    offset_y: ToleranceInput

    def validate(self):
        EclipseInputs(self.hole_diameter, self.pin_diameter,
                      self.offset_x, self.offset_y).validate()


def pin_outside_fraction(hole_radius: float, pin_radius: float, distance: float) -> float:
    """Fraction of the pin's projected area outside the hole, in [0, 1]."""
    hole_radius = finite_number(hole_radius, "Hole radius")
    pin_radius = finite_number(pin_radius, "Pin radius")
    distance = finite_number(distance, "Center distance")
    overlap, smaller = _overlap_fraction(hole_radius, pin_radius, distance)
    if _radial_clearance_from_radii(hole_radius, pin_radius, distance) >= 0:
        return 0.0
    # Normalize by the pin without squaring physical lengths (overflow).
    return float(np.clip(1 - overlap * (smaller / pin_radius)**2, 0, 1))


@dataclass
class SampleStatistics:
    samples: np.ndarray

    def __post_init__(self):
        try:
            self.samples = np.array(self.samples, dtype=float, copy=True)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("Samples must be finite numbers.") from exc
        self.validate()

    def validate(self):
        if self.samples.ndim != 1 or not self.samples.size or not np.all(np.isfinite(self.samples)):
            raise ValueError("Samples must be a nonempty one-dimensional array of finite numbers.")

    @property
    def mean(self):
        scale = float(np.max(np.abs(self.samples)))
        return 0.0 if scale == 0 else float(np.mean(self.samples / scale) * scale)

    @property
    def std_dev(self):
        # Scale first to avoid overflow when squaring finite physical lengths.
        scale = float(np.max(np.abs(self.samples)))
        return 0.0 if scale == 0 else float(np.std(self.samples / scale) * scale)

    @property
    def minimum(self):
        return float(np.min(self.samples))

    @property
    def maximum(self):
        return float(np.max(self.samples))


@dataclass
class PinHoleMonteCarloResult:
    area: SampleStatistics
    clearance: SampleStatistics

    def __post_init__(self):
        self.validate()

    def validate(self):
        self.area.validate()
        self.clearance.validate()
        if self.area.samples.shape != self.clearance.samples.shape:
            raise ValueError("Area and clearance must describe the same samples.")
        if np.any((self.area.samples < 0) | (self.area.samples > 1)):
            raise ValueError("Pin outside fractions must be from 0 to 1.")

    def probability_above(self, threshold: float) -> float:
        self.validate()
        threshold = finite_number(threshold, "Projected interference threshold")
        if not 0 <= threshold <= 1:
            raise ValueError("Projected interference threshold must be from 0 to 1.")
        return float(np.mean(self.area.samples > threshold))

    @property
    def interference_probability(self) -> float:
        self.validate()
        return float(np.mean(self.clearance.samples < 0))


def run_pin_hole_monte_carlo(
    inputs: PinHoleInputs, iterations: int = 10000, default_cpk: float | None = None, *,
    seed: int | None = None, rng: np.random.Generator | None = None,
) -> PinHoleMonteCarloResult:
    """Sample independent uniform/Cpk inputs, rejecting invalid draws.

    Seeded runs and explicit Generators are isolated from NumPy's global
    stream. With neither argument, legacy np.random.seed() behavior remains.
    """
    iterations = _positive_iterations(iterations)
    default_cpk = parse_optional_cpk(default_cpk, "Global Cpk")
    random = _random_stream(seed, rng)
    inputs.validate()
    sample_rng = None if random is np.random else random
    hole = inputs.hole_diameter.sample(iterations, default_cpk, rng=sample_rng)
    pin = inputs.pin_diameter.sample(iterations, default_cpk, rng=sample_rng)
    dx = inputs.offset_x.sample(iterations, default_cpk, rng=sample_rng)
    dy = inputs.offset_y.sample(iterations, default_cpk, rng=sample_rng)
    if np.any(hole <= 0) or np.any(pin <= 0):
        raise ValueError("Generated diameters must be greater than 0; review the diameter/Cpk assumptions.")
    with np.errstate(over="ignore", invalid="ignore"):
        distance = np.hypot(dx, dy)
        clearance = _radial_clearances_from_radii(hole / 2, pin / 2, distance)
    if not np.all(np.isfinite(distance)) or not np.all(np.isfinite(clearance)):
        raise ValueError("Generated distances or clearances exceed the finite numeric range.")
    area = np.array([pin_outside_fraction(h / 2, p / 2, d)
                     for h, p, d in zip(hole, pin, distance)])
    return PinHoleMonteCarloResult(SampleStatistics(area), SampleStatistics(clearance))


def radial_clearance_bounds(inputs: PinHoleInputs) -> tuple[float, float]:
    """Full-zone radial clearance bounds, using the numerical-contact convention."""
    inputs.validate()
    hole_min, hole_max = inputs.hole_diameter.corners()
    pin_min, pin_max = inputs.pin_diameter.corners()
    nearest, farthest = _box_distance_extremes(inputs.offset_x.corners(), inputs.offset_y.corners())
    return (
        radial_clearance(hole_min, pin_max, farthest),
        radial_clearance(hole_max, pin_min, nearest),
    )
