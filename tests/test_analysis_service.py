import json
import math
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Code"))

from tolstack import Dimension, Stack
from tolstack.analysis import (
    AnalysisSettings, analyze_stack, assess_acceptance, build_stack,
    parse_seed, rank_contributions, update_report_limits,
)
from tolstack.models import MonteCarloResult, StackResult


def test_plain_rows_are_validated_and_normalized_without_qt():
    stack = build_stack([
        {"name": " Housing ", "nominal": "10", "tol_plus": "0.2", "tol_minus": "0.1", "cpk": ""},
        {"name": "Pin", "nominal": "9", "tol_plus": "0.05", "tol_minus": "0.1", "sign": "-", "cpk": "1.33"},
    ])
    assert stack.dimensions[0].name == "Housing"
    assert stack.dimensions[0].cpk is None
    assert stack.dimensions[1].cpk == 1.33
    result = stack.worst_case()
    assert result.nominal == 1
    assert result.lower_limit == pytest.approx(0.85)
    assert result.upper_limit == pytest.approx(1.3)


@pytest.mark.parametrize("field,value", [
    ("nominal", "nan"), ("nominal", "inf"), ("nominal", True),
    ("tol_plus", "nan"), ("tol_plus", -0.1), ("tol_minus", -1),
    ("tol_minus", float("inf")), ("cpk", "nan"), ("cpk", "inf"),
    ("cpk", 0), ("cpk", -1), ("name", " "), ("sign", "?"), ("sign", True),
])
def test_invalid_rows_name_the_failing_row(field, value):
    row = dict(name="A", nominal=10, tol_plus=0.1, tol_minus=0.2, sign="+", cpk=None)
    row[field] = value
    with pytest.raises(ValueError, match="Row 1"):
        build_stack([row])


@pytest.mark.parametrize("method", ["worst_case", "rss", "monte_carlo"])
def test_direct_stack_api_also_rejects_invalid_dimensions(method):
    stack = Stack([Dimension("A", 10, -1, 0.2)])
    with pytest.raises(ValueError, match="nonnegative"):
        getattr(stack, method)()


def test_seed_is_repeatable_and_does_not_change_global_random_stream():
    stack = Stack([Dimension("A", 10, 0.5, 0.2), Dimension("B", 9, 0.4, 0.6, "-", 1.33)])
    first = stack.monte_carlo(1000, seed=123).samples
    second = stack.monte_carlo(1000, seed=123).samples
    np.testing.assert_array_equal(first, second)
    assert not np.array_equal(first, stack.monte_carlo(1000, seed=124).samples)
    np.random.seed(74)
    expected = np.random.random(10)
    np.random.seed(74)
    stack.monte_carlo(1000, seed=123)
    np.testing.assert_array_equal(np.random.random(10), expected)


def test_explicit_generator_and_legacy_global_rng_remain_supported():
    stack = Stack([Dimension("A", 10, 1, 1)])
    np.testing.assert_array_equal(
        stack.monte_carlo(50, rng=np.random.default_rng(6)).samples,
        stack.monte_carlo(50, seed=6).samples,
    )
    np.random.seed(42)
    expected = stack.monte_carlo(50).samples
    np.random.seed(42)
    np.testing.assert_array_equal(stack.monte_carlo(50).samples, expected)
    with pytest.raises(ValueError, match="either"):
        stack.monte_carlo(50, seed=6, rng=np.random.default_rng(6))


@pytest.mark.parametrize("kwargs", [
    {"iterations": 0}, {"iterations": -1}, {"iterations": 1.5}, {"iterations": True},
    {"seed": -1}, {"seed": 1.5}, {"seed": True}, {"seed": 2**32}, {"default_cpk": float("nan")},
    {"default_cpk": 0}, {"rng": "invalid"},
])
def test_invalid_sampling_options_fail_before_sampling(kwargs):
    with pytest.raises(ValueError):
        Stack([Dimension("A", 1, 0.1, 0.1)]).monte_carlo(**kwargs)


def test_acceptance_limits_and_fit_at_zero_are_independent():
    stack = Stack([Dimension("Clearance", 1, 0.2, 0.2)])
    report = analyze_stack(stack, AnalysisSettings(lower_limit=0.9, upper_limit=1.1))
    assert report.fit_at_zero.verdict == "gap"
    assert report.acceptance.status == "overlaps_limits"
    assert report.acceptance.rejection_probability is None
    narrowed = update_report_limits(report, 0.5, 1.5)
    assert narrowed.result is report.result
    assert narrowed.acceptance.status == "within_limits"
    assert report.settings.lower_limit == 0.9


def test_acceptance_includes_boundary_samples_and_supports_one_sided_limits():
    samples = np.array([0.0, 1.0, 2.0, 3.0])
    result = MonteCarloResult(samples, 1.5, float(np.std(samples)), 0, 3)
    assessment = assess_acceptance(result, 1, 2)
    assert assessment.rejected_count == 2
    assert assessment.rejection_ppm == 500000
    assert assess_acceptance(result, None, 3).status == "all_samples_within"
    assert assess_acceptance(result, 2, None).rejected_count == 2
    assert assess_acceptance(result, None, None).status == "not_specified"
    assert assess_acceptance(StackResult(1, 2, 0), 3, None).status == "outside_limits"


def test_exact_variance_ranking_accounts_for_asymmetric_normal_mean_shift():
    stack = Stack([
        Dimension("Uniform", 10, 4, 2),
        Dimension("Normal", 5, 6, 3, "-", 1),
        Dimension("Fixed", 2, 0, 0),
    ])
    ranked = rank_contributions(stack)
    by_name = {item.name: item for item in ranked}
    assert ranked[0].name == "Uniform"
    assert by_name["Uniform"].source_variance == 3
    assert by_name["Uniform"].expected_source_value == 11
    assert by_name["Normal"].source_variance == pytest.approx(2.5 - 1 / (2 * math.pi))
    assert by_name["Normal"].expected_source_value == pytest.approx(5 + 1 / math.sqrt(2 * math.pi))
    assert by_name["Normal"].sensitivity == -1
    assert by_name["Normal"].response_variance == by_name["Normal"].source_variance
    assert sum(item.variance_fraction for item in ranked) == pytest.approx(1)
    assert by_name["Fixed"].variance_fraction == 0
    mc = stack.monte_carlo(200000, seed=28)
    assert mc.mean == pytest.approx(sum(item.sensitivity * item.expected_source_value for item in ranked), abs=0.025)
    assert mc.std_dev ** 2 == pytest.approx(sum(item.response_variance for item in ranked), rel=0.02)


def test_default_cpk_and_per_dimension_override_match_sampling_contract():
    ranked = rank_contributions(Stack([
        Dimension("Default", 0, 3, 3), Dimension("Override", 0, 3, 3, cpk=2),
    ]), default_cpk=1)
    assert ranked[0].name == "Default"
    assert ranked[0].source_variance == 1
    assert ranked[1].source_variance == 0.25
    assert rank_contributions(Stack([Dimension("Fixed", 2, 0, 0)]))[0].variance_fraction == 0


def test_report_is_json_serializable_and_snapshots_analysis_inputs():
    dimension = Dimension("A", 1, 0.1, 0.2)
    report = analyze_stack(Stack([dimension]), AnalysisSettings(
        method="monte_carlo", lower_limit=0.8, upper_limit=1.1, seed=23,
        response_name="Assembly gap", iterations=100,
    ))
    dimension.nominal = 100
    payload = json.loads(json.dumps(report.to_dict(), allow_nan=False))
    assert payload["dimensions"][0]["nominal"] == 1
    assert payload["settings"]["seed"] == 23
    assert payload["settings"]["response_name"] == "Assembly gap"
    assert payload["result"]["sample_count"] == 100
    assert "samples" not in payload["result"]
    assert payload["acceptance"]["rejected_count"] == 0
    assert any("zero observed" in item for item in payload["assumptions"])


@pytest.mark.parametrize("kwargs", [
    {"lower_limit": float("nan")}, {"upper_limit": float("inf")},
    {"lower_limit": 2, "upper_limit": 1}, {"method": "unknown"},
    {"response_name": ""}, {"iterations": 0}, {"default_cpk": -1},
])
def test_invalid_study_settings_are_rejected(kwargs):
    with pytest.raises(ValueError):
        AnalysisSettings(**kwargs)


def test_seed_parsing_and_empty_study_validation():
    assert parse_seed(" 123 ") == 123
    assert parse_seed("") is None
    with pytest.raises(ValueError):
        parse_seed("2.5")
    with pytest.raises(ValueError, match="at least one"):
        analyze_stack(Stack())


def test_shared_seed_bounds_allow_saved_study_boundary_and_reject_overflow():
    assert parse_seed("0") == 0
    assert parse_seed(str(2**32 - 1)) == 2**32 - 1
    assert parse_seed(np.uint64(2**32 - 1)) == 2**32 - 1
    for value in (2**32, str(2**32), np.uint64(2**32), -1, True, "１２"):
        with pytest.raises(ValueError, match="4294967295"):
            parse_seed(value)
    result = analyze_stack(Stack([Dimension("A", 0, 1, 1)]), AnalysisSettings(
        method="monte_carlo", seed=2**32 - 1, iterations=5,
    ))
    assert len(result.result.samples) == 5


@pytest.mark.parametrize("method", ["worst_case", "rss", "monte_carlo"])
def test_unrepresentable_variance_fails_as_validation_error(method):
    with pytest.raises(ValueError, match="finite number"):
        analyze_stack(Stack([Dimension("A", 0, 1e200, 1e200)]), AnalysisSettings(
            method=method, seed=10, iterations=5,
        ))


def test_rss_avoids_intermediate_square_overflow():
    result = Stack([Dimension("A", 0, 1e200, 1e200)]).rss()
    assert result.upper_limit == 1e200
    assert result.lower_limit == -1e200


def test_extreme_cpk_does_not_overflow_denominator_to_zero_variation():
    contribution = rank_contributions(Stack([Dimension("A", 0, 1e200, 1e200, cpk=1e308)]))[0]
    assert contribution.source_variance > 0
    result = Stack([Dimension("A", 0, 1e200, 1e200, cpk=1e308)]).monte_carlo(20, seed=10)
    assert np.any(result.samples != 0)


def test_rss_report_does_not_claim_guaranteed_bounds_or_yield():
    report = analyze_stack(Stack([Dimension("A", 1, 0.1, 0.1)]), AnalysisSettings(method="rss"))
    assert any("not a guaranteed bound" in item for item in report.assumptions)
    assert report.acceptance.rejection_probability is None
