"""Independent geometry, tolerance bounds and sampling checks for hole/pin."""

import math

import numpy as np
import pytest

from tolstack.eclipse import ToleranceInput, eclipse_fraction
from tolstack.projected_interference import (
    PinHoleInputs, PinHoleMonteCarloResult, SampleStatistics,
    pin_outside_fraction, radial_clearance_bounds, run_pin_hole_monte_carlo,
)


def quantity(value, plus=0, minus=0, cpk=None):
    return ToleranceInput("Input", value, plus, minus, cpk)


def inputs(hole=4, pin=2, x=0, y=0):
    return PinHoleInputs(quantity(hole), quantity(pin), quantity(x), quantity(y))


@pytest.mark.parametrize("hole,pin,distance,expected", [
    (2, 1, 0, 0), (1, 1, 0, 0), (1, 2, 0, .75),
    (2, 1, 1, 0), (1, 1, 2, 1), (1, 1, 3, 1),
    (1, 1, 1, 1 - (2 * math.pi / 3 - math.sqrt(3) / 2) / math.pi),
])
def test_pin_normalization_and_circle_boundaries(hole, pin, distance, expected):
    assert pin_outside_fraction(hole, pin, distance) == pytest.approx(expected)


def test_oversized_pin_differs_from_legacy_smaller_aperture_normalization():
    assert eclipse_fraction(1, 2, 0) == 0
    assert pin_outside_fraction(1, 2, 0) == .75


@pytest.mark.parametrize("scale", [1e-200, 1, 1e200])
def test_dimensionless_area_is_scale_invariant(scale):
    assert pin_outside_fraction(scale, 2 * scale, 0) == pytest.approx(.75)
    assert pin_outside_fraction(scale, scale, scale) == pytest.approx(pin_outside_fraction(1, 1, 1))


@pytest.mark.parametrize("hole,pin,distance", [(0, 1, 0), (1, -1, 0), (1, 1, -1),
                                               (math.nan, 1, 0), (1, math.inf, 0), (1, 1, math.inf)])
def test_invalid_circle_geometry(hole, pin, distance):
    with pytest.raises(ValueError):
        pin_outside_fraction(hole, pin, distance)


@pytest.mark.parametrize("hole,pin,x,clearance,area,risk", [
    (4, 2, 0, 1, 0, 0), (2, 2, 0, 0, 0, 0),
    (2, 4, 0, -1, .75, 1), (4, 2, 1, 0, 0, 0),
    (2, 2, 3, -3, 1, 1),
])
def test_zero_tolerance_samples_and_contact_exclusion(hole, pin, x, clearance, area, risk):
    data = inputs(hole, pin, x)
    result = run_pin_hole_monte_carlo(data, 10)
    assert result.area.mean == pytest.approx(area)
    assert result.area.std_dev == pytest.approx(0)
    assert result.clearance.mean == pytest.approx(clearance)
    assert result.interference_probability == risk
    assert radial_clearance_bounds(data) == pytest.approx((clearance, clearance))
    assert result.probability_above(area) == 0


def test_full_zone_bounds_include_interior_origin_and_asymmetric_tolerances():
    data = PinHoleInputs(quantity(10, 2, 1), quantity(4, 1, .5),
                         quantity(.1, .4, .3), quantity(-.1, .3, .3))
    expected_min = (9 - 5) / 2 - math.hypot(.5, .4)
    expected_max = (12 - 3.5) / 2  # nearest offset is zero, inside the box
    assert radial_clearance_bounds(data) == pytest.approx((expected_min, expected_max))
    result = run_pin_hole_monte_carlo(data, 200)
    assert result.clearance.minimum >= expected_min
    assert result.clearance.maximum <= expected_max


def test_full_zone_bounds_when_offset_box_excludes_origin():
    data = inputs()
    data.offset_x = quantity(3, 1, 1)
    data.offset_y = quantity(-5, 1, 1)
    assert radial_clearance_bounds(data) == pytest.approx((1 - math.hypot(4, 6), 1 - math.hypot(2, 4)))


def test_seeded_samples_match_independently_sampled_inputs():
    data = PinHoleInputs(quantity(4, .2, .1, 1.1), quantity(3, .3, .2),
                         quantity(.5, .1, .2), quantity(.1, .2, .1))
    np.random.seed(123)
    result = run_pin_hole_monte_carlo(data, 80, default_cpk=1.3)
    np.random.seed(123)
    hole, pin, x, y = [q.sample(80, 1.3) for q in
                       (data.hole_diameter, data.pin_diameter, data.offset_x, data.offset_y)]
    distance = np.hypot(x, y)
    np.testing.assert_allclose(result.clearance.samples, (hole - pin) / 2 - distance)
    np.testing.assert_allclose(result.area.samples, [pin_outside_fraction(h / 2, p / 2, d)
                                                   for h, p, d in zip(hole, pin, distance)])
    assert result.interference_probability == np.mean(result.clearance.samples < 0)
    assert result.probability_above(.2) == np.mean(result.area.samples > .2)


@pytest.mark.parametrize("iterations", [0, -1, 1.5, True])
def test_invalid_iterations(iterations):
    with pytest.raises(ValueError):
        run_pin_hole_monte_carlo(inputs(), iterations)


@pytest.mark.parametrize("field,value", [("nominal", math.nan), ("tol_plus", -1),
                                          ("cpk", 0), ("cpk", math.inf), ("tol_minus", 4)])
def test_mutated_invalid_input_rejected_in_sampling_and_bounds(field, value):
    data = inputs()
    setattr(data.hole_diameter, field, value)
    for operation in (run_pin_hole_monte_carlo, radial_clearance_bounds):
        with pytest.raises(ValueError):
            operation(data)


def test_nonpositive_cpk_draw_is_not_clipped_or_resampled(monkeypatch):
    monkeypatch.setattr(np.random, "standard_normal", lambda n: np.full(n, -100.0))
    data = inputs()
    data.pin_diameter = quantity(2, .1, .1, 1)
    with pytest.raises(ValueError, match="Generated diameters"):
        run_pin_hole_monte_carlo(data, 10)


@pytest.mark.parametrize("threshold", [-.01, 1.01, math.nan, math.inf])
def test_invalid_area_threshold(threshold):
    with pytest.raises(ValueError):
        run_pin_hole_monte_carlo(inputs(), 10).probability_above(threshold)


def test_result_validation_and_threshold_endpoints():
    result = PinHoleMonteCarloResult(SampleStatistics([0, .75, 1]), SampleStatistics([0, -1, -2]))
    assert result.probability_above(0) == pytest.approx(2 / 3)
    assert result.probability_above(1) == 0
    assert result.interference_probability == pytest.approx(2 / 3)
    result.area.samples[0] = 2
    with pytest.raises(ValueError):
        result.probability_above(.5)
    with pytest.raises(ValueError):
        PinHoleMonteCarloResult(SampleStatistics([0]), SampleStatistics([0, 1]))


@pytest.mark.parametrize("samples", [[], [[0]], [math.nan], [math.inf]])
def test_invalid_statistics_samples(samples):
    with pytest.raises(ValueError):
        SampleStatistics(samples)


def test_statistics_do_not_overflow_for_large_finite_clearances():
    stats = SampleStatistics([1e308, 1e308])
    assert stats.mean == 1e308
    assert stats.std_dev == 0
