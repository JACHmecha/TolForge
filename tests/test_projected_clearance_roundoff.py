"""Unit-invariant numerical contact without an engineering clearance tolerance."""

import math

import numpy as np
import pytest

from tolstack.eclipse import ToleranceInput
from tolstack.length_units import convert_length
from tolstack.projected_interference import (
    PinHoleInputs, pin_outside_fraction, radial_clearance,
    radial_clearance_bounds, run_pin_hole_monte_carlo,
)


def constant_inputs(hole, pin, distance):
    return PinHoleInputs(*(ToleranceInput(name, value, 0, 0) for name, value in
                           (("Hole", hole), ("Pin", pin), ("X", distance), ("Y", 0))))


@pytest.mark.parametrize("pin", [9, 9.5, 9.99, 9.999])
@pytest.mark.parametrize("units", ["mm", "in"])
def test_exact_contact_stays_zero_after_unit_conversion_in_all_analysis_outputs(pin, units):
    # Construct an exact floating-point contact before conversion; this also
    # covers subtraction of nearly equal diameters where gap ULPs are too tight.
    hole = 10.0
    distance = (hole - pin) / 2
    hole, pin, distance = [convert_length(value, "mm", units) for value in (hole, pin, distance)]
    assert radial_clearance(hole, pin, distance) == 0
    assert pin_outside_fraction(hole / 2, pin / 2, distance) == 0
    data = constant_inputs(hole, pin, distance)
    result = run_pin_hole_monte_carlo(data, 10, seed=0)
    np.testing.assert_array_equal(result.clearance.samples, np.zeros(10))
    np.testing.assert_array_equal(result.area.samples, np.zeros(10))
    assert result.interference_probability == 0
    assert radial_clearance_bounds(data) == (0, 0)


@pytest.mark.parametrize("pin", [9, 9.999])
@pytest.mark.parametrize("units", ["mm", "in"])
def test_real_small_penetration_beyond_operand_roundoff_remains_interference(pin, units):
    hole, distance = 10.0, (10.0 - pin) / 2 + 1e-12
    hole, pin, distance = [convert_length(value, "mm", units) for value in (hole, pin, distance)]
    expected = hole / 2 - pin / 2 - distance
    assert expected < 0
    assert radial_clearance(hole, pin, distance) == expected
    data = constant_inputs(hole, pin, distance)
    result = run_pin_hole_monte_carlo(data, 10, seed=0)
    assert result.interference_probability == 1
    np.testing.assert_array_equal(result.clearance.samples, np.full(10, expected))
    assert radial_clearance_bounds(data) == (expected, expected)


def test_tolerance_zone_penetration_beyond_roundoff_keeps_negative_minimum():
    data = constant_inputs(10 / 25.4, 9 / 25.4, .5 / 25.4)
    data.offset_x.tol_plus = 1e-10 / 25.4
    lower, upper = radial_clearance_bounds(data)
    assert lower < 0
    assert lower == data.hole_diameter.nominal / 2 - data.pin_diameter.nominal / 2 - data.offset_x.corners()[1]
    assert upper == 0


def test_centered_one_ulp_oversized_pin_is_not_normalized_to_contact():
    hole, pin = 10.0, math.nextafter(10.0, math.inf)
    expected = hole / 2 - pin / 2
    assert expected < 0
    assert radial_clearance(hole, pin, 0) == expected
    assert pin_outside_fraction(hole / 2, pin / 2, 0) > 0
    result = run_pin_hole_monte_carlo(constant_inputs(hole, pin, 0), 10, seed=0)
    assert result.interference_probability == 1
    np.testing.assert_array_equal(result.clearance.samples, np.full(10, expected))


@pytest.mark.parametrize("distance", [1e-12, 1e-200, math.ulp(0.0)])
def test_equal_diameter_any_representable_offset_remains_negative(distance):
    assert radial_clearance(10, 10, distance) == -distance
    result = run_pin_hole_monte_carlo(constant_inputs(10, 10, distance), 10, seed=0)
    assert result.interference_probability == 1
    assert radial_clearance_bounds(constant_inputs(10, 10, distance)) == (-distance, -distance)


def test_subnormal_geometry_keeps_physically_significant_penetration():
    smallest = math.ulp(0.0)
    hole, pin, distance = 8 * smallest, 4 * smallest, 3 * smallest
    assert radial_clearance(hole, pin, distance) == -smallest
    assert pin_outside_fraction(hole / 2, pin / 2, distance) > 0
    data = constant_inputs(hole, pin, distance)
    result = run_pin_hole_monte_carlo(data, 10, seed=0)
    assert result.interference_probability == 1
    np.testing.assert_array_equal(result.clearance.samples, np.full(10, -smallest))
    assert radial_clearance_bounds(data) == (-smallest, -smallest)


def test_operand_roundoff_does_not_dominate_a_tiny_positive_gap_geometry():
    hole, pin = 10.0, math.nextafter(10.0, 0)
    headroom = (hole - pin) / 2
    distance = math.nextafter(headroom, math.inf)
    expected = headroom - distance
    assert expected < 0
    assert radial_clearance(hole, pin, distance) == expected


@pytest.mark.parametrize("values", [(0, 2, 0), (2, -1, 0), (2, 1, -1),
                                    (math.inf, 1, 0), (2, math.nan, 0), (2, 1, True)])
def test_public_clearance_rejects_invalid_geometry(values):
    with pytest.raises(ValueError):
        radial_clearance(*values)


def test_radius_based_area_normalization_never_doubles_large_radii():
    largest = np.finfo(float).max
    assert pin_outside_fraction(largest, largest / 2, 0) == 0
