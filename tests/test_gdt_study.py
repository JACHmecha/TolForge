import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Code"))
from tolstack.gdt import PatternFeature, PatternPositionControl, run_pattern_monte_carlo, evaluate_pattern_nominal


def control():
    return PatternPositionControl([
        PatternFeature("H1", 0, 0, .02, .01, 10.1, .1, .1,
                       position_tol_plus_x=.05, position_tol_minus_x=.05,
                       position_tol_plus_y=.05, position_tol_minus_y=.05)
    ], .08, "MMC", 10., 10.2, "hole")


def test_pattern_seed_is_repeatable_and_isolated_from_global_rng():
    np.random.seed(472)
    before = np.random.get_state()
    first = run_pattern_monte_carlo(control(), 1000, seed=123)
    second = run_pattern_monte_carlo(control(), 1000, seed=123)
    np.testing.assert_array_equal(first.worst_feature_margin, second.worst_feature_margin)
    after = np.random.get_state()
    np.testing.assert_array_equal(before[1], after[1])
    assert before[2:] == after[2:]


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1])
def test_invalid_pattern_tolerance_is_rejected_by_both_methods(value):
    pattern = control()
    pattern.features[0].position_tol_plus_x = value
    with pytest.raises(ValueError):
        evaluate_pattern_nominal(pattern)
    with pytest.raises(ValueError):
        run_pattern_monte_carlo(pattern, 100, seed=0)


@pytest.mark.parametrize("kwargs", [{"iterations": 0}, {"iterations": True},
                                    {"seed": -1}, {"seed": 2**32},
                                    {"default_cpk": float("nan")}])
def test_invalid_pattern_run_settings_are_rejected(kwargs):
    with pytest.raises(ValueError):
        run_pattern_monte_carlo(control(), **kwargs)


def test_empty_and_duplicate_named_patterns_are_rejected():
    pattern = control()
    pattern.features.append(pattern.features[0])
    with pytest.raises(ValueError, match="unique"):
        run_pattern_monte_carlo(pattern)
    pattern.features.clear()
    with pytest.raises(ValueError, match="at least one"):
        evaluate_pattern_nominal(pattern)
