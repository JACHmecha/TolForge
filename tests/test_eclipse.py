"""Eclipse validation, geometry boundaries and sampling regressions."""

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Code"))

from tolstack.eclipse import (
    EclipseInputs, EclipseMonteCarloResult, ToleranceInput,
    circle_intersection_area, eclipse_fraction, run_monte_carlo, worst_case,
)


@pytest.fixture(autouse=True)
def preserve_legacy_random_stream():
    state = np.random.get_state()
    yield
    np.random.set_state(state)


def inputs():
    return EclipseInputs(
        ToleranceInput("handle", 4, 0.1, 0.1),
        ToleranceInput("sticker", 3, 0.1, 0.1),
        ToleranceInput("offset_x", 0.7, 0.2, 0.1),
        ToleranceInput("offset_y", 0, 0.1, 0.1),
    )


@pytest.mark.parametrize("field", ["nominal", "tol_plus", "tol_minus", "cpk"])
@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf"), True])
def test_nonfinite_or_boolean_input_rejected(field, bad):
    values = dict(name="aperture", nominal=2, tol_plus=0.1, tol_minus=0.1, cpk=1.33)
    values[field] = bad
    with pytest.raises(ValueError, match="finite"):
        ToleranceInput(**values)


@pytest.mark.parametrize("field", ["tol_plus", "tol_minus"])
def test_negative_tolerance_rejected(field):
    values = dict(name="aperture", nominal=2, tol_plus=0.1, tol_minus=0.1)
    values[field] = -0.1
    with pytest.raises(ValueError, match="nonnegative"):
        ToleranceInput(**values)


@pytest.mark.parametrize("bad", [0, -1, float("nan"), float("inf"), True])
def test_invalid_cpk_rejected_for_input_and_default(bad):
    with pytest.raises(ValueError, match="Cpk"):
        ToleranceInput("test", 1, 0.1, 0.1, cpk=bad)
    for operation in (lambda: inputs().offset_x.sample(3, bad), lambda: run_monte_carlo(inputs(), 3, bad)):
        with pytest.raises(ValueError, match="Cpk"):
            operation()


@pytest.mark.parametrize("bad", [0, -1, 1.5, 2.0, True, np.bool_(True), float("nan"), float("inf"), "10", None])
def test_invalid_iterations_rejected(bad):
    for operation in (lambda: inputs().offset_x.sample(bad), lambda: run_monte_carlo(inputs(), bad)):
        with pytest.raises(ValueError, match="positive integer"):
            operation()


def test_numpy_integer_iteration_count_is_valid():
    assert run_monte_carlo(inputs(), np.int64(2)).samples.shape == (2,)


@pytest.mark.parametrize("field,bad", [("nominal", float("nan")), ("tol_minus", -1), ("cpk", float("inf"))])
def test_mutated_inputs_are_revalidated_at_all_analysis_boundaries(field, bad):
    data = inputs()
    setattr(data.offset_x, field, bad)
    for operation in (lambda: data.offset_x.sample(2), lambda: run_monte_carlo(data, 2), lambda: worst_case(data)):
        with pytest.raises(ValueError):
            operation()


@pytest.mark.parametrize("nominal,tol_minus", [(0, 0), (-1, 0), (1, 1), (1, 2)])
def test_diameter_tolerance_range_must_remain_positive(nominal, tol_minus):
    data = inputs()
    data.handle_diameter = ToleranceInput("handle", nominal, 0, tol_minus)
    for operation in (lambda: run_monte_carlo(data, 2), lambda: worst_case(data)):
        with pytest.raises(ValueError, match="diameter"):
            operation()


@pytest.mark.parametrize("r1,r2,d,expected_fraction,expected_area", [
    (1, 1, 2, 1, 0),       # External tangency.
    (2, 1, 1, 0, np.pi),   # Internal tangency.
    (2, 1, 0.5, 0, np.pi), # Containment.
    (1, 1, 3, 1, 0),       # Non-overlap.
    (1, 1, 0, 0, np.pi),   # Concentric.
    (1, 1, 1, 1 - (2 * np.pi / 3 - np.sqrt(3) / 2) / np.pi, 2 * np.pi / 3 - np.sqrt(3) / 2),
])
def test_circle_geometry_reference_cases(r1, r2, d, expected_fraction, expected_area):
    assert eclipse_fraction(r1, r2, d) == pytest.approx(expected_fraction, abs=1e-14)
    assert circle_intersection_area(r1, r2, d) == pytest.approx(expected_area, abs=1e-14)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf"), True])
@pytest.mark.parametrize("index", [0, 1, 2])
def test_geometry_rejects_nonfinite_values(index, bad):
    values = [1, 1, 1]
    values[index] = bad
    for operation in (eclipse_fraction, circle_intersection_area):
        with pytest.raises(ValueError, match="finite"):
            operation(*values)


@pytest.mark.parametrize("values", [(0, 1, 0), (-1, 1, 0), (1, 0, 0), (1, 1, -1)])
def test_geometry_rejects_nonphysical_values(values):
    with pytest.raises(ValueError):
        eclipse_fraction(*values)


@pytest.mark.parametrize("scale", [1e200, 1e-200])
def test_fraction_is_scale_invariant_without_intermediate_overflow(scale):
    assert eclipse_fraction(scale, scale, scale) == pytest.approx(eclipse_fraction(1, 1, 1))


@pytest.mark.parametrize("radius", [1e-10, 1e-150, 1e-300])
def test_tiny_circle_at_large_circle_edge_retains_half_its_aperture(radius):
    assert eclipse_fraction(radius, 1, 1) == pytest.approx(0.5, abs=1e-9)
    assert eclipse_fraction(1, radius, 1) == pytest.approx(0.5, abs=1e-9)


def test_small_equal_circle_offset_preserves_nonzero_occlusion():
    distance = 1e-8
    assert eclipse_fraction(1, 1, distance) == pytest.approx(2 * distance / np.pi, abs=2e-16)


def test_unrepresentable_radius_ratio_rejected_instead_of_false_containment():
    with pytest.raises(ValueError, match="geometry"):
        eclipse_fraction(5e-324, 1e308, 1e308)


@pytest.mark.parametrize("radius", [1e200, 1e-200])
def test_unrepresentable_absolute_area_rejected(radius):
    with pytest.raises(ValueError, match="area"):
        circle_intersection_area(radius, radius, 0)


def test_finite_large_offset_uses_hypot_not_squared_lengths():
    data = EclipseInputs(
        ToleranceInput("handle", 2e200, 0, 0), ToleranceInput("sticker", 2e200, 0, 0),
        ToleranceInput("x", 1e200, 0, 0), ToleranceInput("y", 1e200, 0, 0),
    )
    expected = eclipse_fraction(1, 1, np.sqrt(2))
    assert run_monte_carlo(data, 2).samples == pytest.approx([expected, expected])
    assert worst_case(data) == pytest.approx((expected, expected))


def test_unrepresentable_tolerance_limits_rejected():
    with pytest.raises(ValueError, match="upper tolerance limit"):
        ToleranceInput("huge", 1e308, 1e308, 0)


def test_unrepresentable_uniform_span_rejected():
    value = ToleranceInput("huge", 0, 1e308, 1e308)
    with pytest.raises(ValueError):
        value.sample(2)


def test_unrepresentable_sampling_sigma_rejected():
    value = ToleranceInput("wide", 0, 1, 1, cpk=5e-324)
    with pytest.raises(ValueError, match="sampling deviation"):
        value.sample(2)


def test_large_finite_cpk_does_not_overflow_three_times_cpk():
    value = ToleranceInput("wide", 0, 1e308, 1e308, cpk=1e308)
    np.random.seed(82)
    assert np.any(value.sample(5) != 0)


def test_nonfinite_generated_samples_are_rejected(monkeypatch):
    monkeypatch.setattr(np.random, "uniform", lambda low, high, count: np.full(count, np.nan))
    with pytest.raises(ValueError, match="generated samples must be finite"):
        run_monte_carlo(inputs(), 2)


def test_negative_normal_diameter_is_rejected_without_clipping_or_resampling(monkeypatch):
    data = inputs()
    data.handle_diameter.cpk = 1
    monkeypatch.setattr(np.random, "standard_normal", lambda count: np.full(count, -1000.0))
    with pytest.raises(ValueError, match="Generated diameters.*Cpk"):
        run_monte_carlo(data, 2)


def test_unrepresentable_generated_center_distance_rejected():
    data = inputs()
    data.offset_x = ToleranceInput("x", 1.7e308, 0, 0)
    data.offset_y = ToleranceInput("y", 1.7e308, 0, 0)
    with pytest.raises(ValueError, match="center distances"):
        run_monte_carlo(data, 2)
    with pytest.raises(ValueError, match="center distance"):
        worst_case(data)


def test_uniform_sampling_retains_legacy_seeded_stream():
    value = ToleranceInput("offset", 2, 0.7, 0.2)
    np.random.seed(16)
    expected = np.random.uniform(1.8, 2.7, 6)
    np.random.seed(16)
    assert np.array_equal(value.sample(6), expected)


def test_cpk_sampling_retains_unbounded_sign_scaled_normal_stream():
    value = ToleranceInput("offset", 2, 0.7, 0.2, cpk=1.33)
    np.random.seed(23)
    z = np.random.standard_normal(6)
    expected = 2 + np.where(z >= 0, z * (0.7 / 3 / 1.33), z * (0.2 / 3 / 1.33))
    np.random.seed(23)
    assert np.array_equal(value.sample(6), expected)


def test_seeded_eclipse_matches_independently_sampled_circle_geometry():
    data = inputs()
    data.sticker_diameter.cpk = 1.33
    np.random.seed(417)
    handle = data.handle_diameter.sample(20)
    sticker = data.sticker_diameter.sample(20)
    dx, dy = data.offset_x.sample(20), data.offset_y.sample(20)
    expected = np.array([eclipse_fraction(h / 2, s / 2, np.hypot(x, y)) for h, s, x, y in zip(handle, sticker, dx, dy)])
    np.random.seed(417)
    result = run_monte_carlo(data, 20)
    assert np.array_equal(result.samples, expected)
    np.random.seed(417)
    assert np.array_equal(run_monte_carlo(data, 20).samples, expected)
    assert result.minimum <= result.mean <= result.maximum
    assert result.probability_above(0) == np.mean(expected > 0)
    assert result.probability_above(1) == 0


def test_worst_case_nearest_point_is_inside_offset_rectangle():
    data = EclipseInputs(
        ToleranceInput("handle", 2, 0, 0), ToleranceInput("sticker", 2, 0, 0),
        ToleranceInput("x", 0, 1, 1), ToleranceInput("y", 0, 1, 1),
    )
    assert worst_case(data) == pytest.approx((0, eclipse_fraction(1, 1, np.sqrt(2))))


def test_worst_case_includes_equal_diameter_interior_maximum():
    data = EclipseInputs(
        ToleranceInput("handle", 1.5, 0.1, 0.1), ToleranceInput("sticker", 1.5, 0, 0),
        ToleranceInput("x", 0.4, 0, 0), ToleranceInput("y", 0, 0, 0),
    )
    _, maximum = worst_case(data)
    assert maximum == pytest.approx(0.33546242676551696)
    assert maximum == pytest.approx(eclipse_fraction(0.75, 0.75, 0.4))


def test_worst_case_includes_unequal_diameter_interior_minimum():
    data = EclipseInputs(
        ToleranceInput("handle", 1.001, 0.999, 0.999), ToleranceInput("sticker", 2, 0, 0),
        ToleranceInput("x", 1.05, 0, 0), ToleranceInput("y", 0, 0, 0),
    )
    minimum, maximum = worst_case(data)
    # Independent one-dimensional dense scan brackets the stationary
    # minimum: it must be strictly below either diameter endpoint.
    interior = [eclipse_fraction(radius, 1, 1.05) for radius in np.linspace(0.53, 0.57, 1001)]
    assert minimum == pytest.approx(min(interior), abs=2e-10)
    assert minimum < eclipse_fraction(1, 1, 1.05)
    assert maximum == 1


def test_worst_case_bounds_all_sampled_diameter_pairs_and_offsets():
    data = EclipseInputs(
        ToleranceInput("handle", 2, 1, 1), ToleranceInput("sticker", 2.1, 0.2, 0.2),
        ToleranceInput("x", 1.05, 0.1, 0.05), ToleranceInput("y", 0, 0.05, 0.05),
    )
    minimum, maximum = worst_case(data)
    np.random.seed(189)
    result = run_monte_carlo(data, 2000)
    assert np.all(result.samples >= minimum - 1e-14)
    assert np.all(result.samples <= maximum + 1e-14)


@pytest.mark.parametrize("ranges,distance", [
    (((1.4, 1.6), (1.5, 1.5)), 0.4),
    (((0.002, 2), (2, 2)), 1.05),
    (((1, 3), (1.9, 2.3)), 1.05),
    (((1, 3), (0.5, 0.9)), 0.4),
])
def test_full_zone_extrema_bound_independent_diameter_grid(ranges, distance):
    handle, sticker = ranges
    data = EclipseInputs(
        ToleranceInput("handle", handle[0], handle[1] - handle[0], 0),
        ToleranceInput("sticker", sticker[0], sticker[1] - sticker[0], 0),
        ToleranceInput("x", distance, 0, 0), ToleranceInput("y", 0, 0, 0),
    )
    minimum, maximum = worst_case(data)
    grid = [
        eclipse_fraction(dh / 2, ds / 2, distance)
        for dh in np.linspace(*handle, 101) for ds in np.linspace(*sticker, 101)
    ]
    assert minimum <= min(grid) + 1e-14
    assert maximum >= max(grid) - 1e-14


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -0.01, 1.01, True, "bad"])
def test_invalid_threshold_never_returns_zero_probability(bad):
    result = run_monte_carlo(inputs(), 2)
    with pytest.raises(ValueError, match="threshold"):
        result.probability_above(bad)


@pytest.mark.parametrize("bad_samples", [[], [np.nan], [np.inf], [-0.1], [1.1], [[0.5]]])
def test_invalid_result_samples_rejected(bad_samples):
    with pytest.raises(ValueError, match="samples"):
        EclipseMonteCarloResult(np.array(bad_samples), 0, 0, 0, 0)


@pytest.mark.parametrize("field", ["mean", "std_dev", "minimum", "maximum"])
def test_mutated_nonfinite_statistics_cannot_produce_probability(field):
    result = run_monte_carlo(inputs(), 2)
    setattr(result, field, np.nan)
    with pytest.raises(ValueError, match="finite"):
        result.probability_above(0.3)


def test_mutated_result_samples_cannot_produce_probability():
    result = run_monte_carlo(inputs(), 2)
    result.samples[0] = np.nan
    with pytest.raises(ValueError, match="samples"):
        result.probability_above(0.3)


def test_statistics_must_match_result_samples():
    with pytest.raises(ValueError, match="mean.*match"):
        EclipseMonteCarloResult(np.array([0.5]), 0, 0, 0.5, 0.5)
