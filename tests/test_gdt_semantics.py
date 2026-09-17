import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Code"))

from tolstack.gdt import (
    PatternFeature, PatternPositionControl, evaluate_pin_hole_clearance,
    evaluate_position, run_pattern_monte_carlo, size_limits,
    virtual_condition,
)


def test_virtual_condition_uses_internal_and_external_boundaries():
    assert virtual_condition(10.0, 0.2, "hole") == pytest.approx(9.8)
    assert virtual_condition(9.5, 0.1, "pin") == pytest.approx(9.6)


def test_size_limit_order_depends_on_feature_kind():
    assert size_limits(10.0, 10.2, "hole") == (10.0, 10.2)
    assert size_limits(9.5, 9.3, "pin") == (9.3, 9.5)
    with pytest.raises(ValueError, match="For a hole"):
        size_limits(10.2, 10.0, "hole")


def test_position_pass_requires_size_and_geometric_conformance():
    result = evaluate_position(
        0.0, 0.0, 0.2,
        actual_size=10.3, mmc_size=10.0, lmc_size=10.2,
        modifier="MMC", feature_kind="hole",
    )
    assert result.position_conforming
    assert not result.size_conforming
    assert not result.passes
    assert result.margin == pytest.approx(-0.1)
    # Bonus is capped at the LMC departure; an out-of-size hole cannot earn
    # unlimited geometric tolerance.
    assert result.bonus_tolerance == pytest.approx(0.2)


def test_pin_hole_clearance_compares_virtual_and_actual_boundaries():
    result = evaluate_pin_hole_clearance(
        hole_mmc_size=10.0, hole_position_tolerance=0.2,
        pin_mmc_size=9.5, pin_position_tolerance=0.1,
        hole_actual_size=10.1, hole_position_error=0.05,
        pin_actual_size=9.4, pin_position_error=0.02,
    )
    assert result.hole_virtual_condition == pytest.approx(9.8)
    assert result.pin_virtual_condition == pytest.approx(9.6)
    assert result.guaranteed_clearance == pytest.approx(0.2)
    assert result.guaranteed_assembly
    assert result.actual_effective_clearance == pytest.approx(0.63)


def test_pattern_monte_carlo_reports_size_and_position_failures_separately():
    feature = PatternFeature(
        name="Hole 1", basic_x=0.0, basic_y=0.0,
        actual_x=0.0, actual_y=0.0,
        size_nominal=10.2, size_tol_plus=0.3, size_tol_minus=0.3,
    )
    control = PatternPositionControl(
        features=[feature], base_tolerance_diameter=0.2,
        modifier="RFS", mmc_size=10.0, lmc_size=10.4,
        feature_kind="hole",
    )
    result = run_pattern_monte_carlo(control, iterations=20000)
    assert 0.25 < result.per_feature_size_fail_rate["Hole 1"] < 0.4
    assert result.per_feature_position_fail_rate["Hole 1"] == 0.0
    assert result.per_feature_fail_rate["Hole 1"] == pytest.approx(
        result.per_feature_size_fail_rate["Hole 1"]
    )
