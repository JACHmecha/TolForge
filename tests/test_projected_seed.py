"""Reproducibility and random-stream ownership for both projected modes."""

import numpy as np
import pytest

from tolstack.eclipse import EclipseInputs, ToleranceInput, run_monte_carlo
from tolstack.projected_interference import PinHoleInputs, run_pin_hole_monte_carlo


@pytest.fixture(autouse=True)
def preserve_legacy_random_stream():
    state = np.random.get_state()
    yield
    np.random.set_state(state)


@pytest.fixture(params=["hole-hole", "hole-pin"])
def analysis(request):
    quantities = (
        ToleranceInput("Hole", 4, .2, .1, cpk=1.1),
        ToleranceInput("Second circle", 3, .3, .2),
        ToleranceInput("X", 1, .2, .1),
        ToleranceInput("Y", -.5, .1, .2),
    )
    if request.param == "hole-hole":
        return run_monte_carlo, EclipseInputs(*quantities), quantities
    return run_pin_hole_monte_carlo, PinHoleInputs(*quantities), quantities


def sample_arrays(result):
    if hasattr(result, "area"):
        return (result.area.samples, result.clearance.samples)
    return (result.samples,)


def assert_same_samples(first, second):
    for a, b in zip(sample_arrays(first), sample_arrays(second)):
        np.testing.assert_array_equal(a, b)


@pytest.mark.parametrize("default_cpk", [None, 1.33])
@pytest.mark.parametrize("seed", [0, 123, np.int64(42), 2**32 - 1, " 123 "])
def test_seeded_runs_are_reproducible_for_both_sampling_conventions(analysis, default_cpk, seed):
    run, inputs, _ = analysis
    first = run(inputs, 80, default_cpk, seed=seed)
    # The same result is independent of intervening global random calls.
    np.random.uniform(size=30)
    assert_same_samples(first, run(inputs, 80, default_cpk, seed=seed))


@pytest.mark.parametrize("default_cpk", [None, 1.33])
def test_different_seeds_change_results(analysis, default_cpk):
    run, inputs, _ = analysis
    first = run(inputs, 80, default_cpk, seed=123)
    second = run(inputs, 80, default_cpk, seed=456)
    assert all(not np.array_equal(a, b) for a, b in zip(sample_arrays(first), sample_arrays(second)))


@pytest.mark.parametrize("stream", ["seed", "generator"])
def test_explicit_stream_does_not_consume_global_numpy_state(analysis, stream):
    run, inputs, _ = analysis
    np.random.seed(27)
    expected = np.random.standard_normal(20)
    np.random.seed(27)
    kwargs = {"seed": 123} if stream == "seed" else {"rng": np.random.default_rng(123)}
    run(inputs, 80, **kwargs)
    np.testing.assert_array_equal(np.random.standard_normal(20), expected)


@pytest.mark.parametrize("default_cpk", [None, 1.33])
def test_caller_generator_advances_by_all_four_input_draws(analysis, default_cpk):
    run, inputs, quantities = analysis
    random = np.random.default_rng(42)
    expected_random = np.random.default_rng(42)
    result = run(inputs, 80, default_cpk, rng=random)
    expected = [quantity.sample(80, default_cpk, rng=expected_random) for quantity in quantities]
    np.testing.assert_array_equal(random.uniform(size=12), expected_random.uniform(size=12))
    if hasattr(result, "clearance"):
        hole, pin, x, y = expected
        np.testing.assert_allclose(result.clearance.samples, hole / 2 - pin / 2 - np.hypot(x, y))
    assert_same_samples(result, run(inputs, 80, default_cpk, seed=42))


@pytest.mark.parametrize("seed", [None, "", "  "])
def test_unspecified_seed_retains_legacy_global_stream_and_sequence(analysis, seed):
    run, inputs, _ = analysis
    np.random.seed(76)
    result = run(inputs, 80, seed=seed)
    np.random.seed(76)
    assert_same_samples(result, run(inputs, 80))
    # Legacy draws must still advance the shared stream.
    expected_next = np.random.uniform(size=12)
    np.random.seed(76)
    run(inputs, 80, seed=seed)
    np.testing.assert_array_equal(np.random.uniform(size=12), expected_next)


@pytest.mark.parametrize("seed", [True, np.bool_(False), -1, 2**32, 1.2,
                                  "-1", "1.2", "0x10", "１２", [], object()])
def test_invalid_seed_rejected(analysis, seed):
    run, inputs, _ = analysis
    with pytest.raises(ValueError, match="Seed must be an integer"):
        run(inputs, 10, seed=seed)


@pytest.mark.parametrize("rng", [np.random, np.random.RandomState(1), 1, True, object()])
def test_invalid_generator_rejected_for_runs_and_inputs(analysis, rng):
    run, inputs, quantities = analysis
    with pytest.raises(ValueError, match="NumPy Generator"):
        run(inputs, 10, rng=rng)
    with pytest.raises(ValueError, match="NumPy Generator"):
        quantities[0].sample(10, rng=rng)


def test_seed_and_generator_are_mutually_exclusive(analysis):
    run, inputs, _ = analysis
    with pytest.raises(ValueError, match="either a seed or a random generator"):
        run(inputs, 10, seed=0, rng=np.random.default_rng(1))


@pytest.mark.parametrize("cpk,default_cpk", [(None, None), (1.2, None), (None, 1.2), (1.7, 1.2)])
def test_tolerance_generator_sampling_matches_uniform_and_split_normal_conventions(cpk, default_cpk):
    quantity = ToleranceInput("Offset", 2, .3, .1, cpk)
    random = np.random.default_rng(135)
    expected_random = np.random.default_rng(135)
    effective_cpk = cpk if cpk is not None else default_cpk
    if effective_cpk is None:
        expected = expected_random.uniform(1.9, 2.3, 80)
    else:
        normal = expected_random.standard_normal(80)
        expected = 2 + np.where(normal >= 0, normal * (.3 / 3 / effective_cpk),
                                normal * (.1 / 3 / effective_cpk))
    np.testing.assert_array_equal(quantity.sample(80, default_cpk, rng=random), expected)


def test_explicit_generator_normal_draws_remain_unbounded():
    quantity = ToleranceInput("Offset", 2, .3, .1, cpk=.01)
    samples = quantity.sample(80, rng=np.random.default_rng(135))
    assert np.any(samples < 1.9)
    assert np.any(samples > 2.3)
