"""Tests for hipaasynth.aast.stats: intervals, three-state verdicts, noise floor."""

import itertools
import math

import pytest

from hipaasynth.aast import (
    FAIL,
    INCONCLUSIVE,
    PASS,
    Interval,
    ModelAdapter,
    beyond_noise,
    bootstrap_interval,
    clopper_pearson,
    majority_decision,
    measure_noise_floor,
    verdict,
)
from hipaasynth.aast.adapter import ModelResponse
from hipaasynth.aast.stats import _binom_cdf

# --- Clopper-Pearson -----------------------------------------------------------


@pytest.mark.parametrize("n", [1, 5, 10, 37, 200])
def test_cp_zero_successes_closed_form(n):
    ci = clopper_pearson(0, n)
    assert ci.low == 0.0 and ci.estimate == 0.0
    assert ci.high == pytest.approx(1 - 0.025 ** (1 / n), abs=1e-9)


@pytest.mark.parametrize("n", [1, 5, 10, 37, 200])
def test_cp_all_successes_closed_form(n):
    ci = clopper_pearson(n, n)
    assert ci.high == 1.0 and ci.estimate == 1.0
    assert ci.low == pytest.approx(0.025 ** (1 / n), abs=1e-9)


def test_cp_reference_value_5_of_10():
    # Standard published exact 95% interval for 5/10: (0.1871, 0.8129).
    ci = clopper_pearson(5, 10)
    assert ci.low == pytest.approx(0.18709, abs=1e-4)
    assert ci.high == pytest.approx(0.81291, abs=1e-4)


@pytest.mark.parametrize("k, n", [(1, 7), (3, 20), (12, 50), (40, 41)])
def test_cp_symmetry(k, n):
    a, b = clopper_pearson(k, n), clopper_pearson(n - k, n)
    assert a.low == pytest.approx(1 - b.high, abs=1e-9)
    assert a.high == pytest.approx(1 - b.low, abs=1e-9)


def test_cp_coverage_is_at_least_nominal():
    # Exact coverage: for every true p, P(interval contains p) >= 95%.
    n = 20
    intervals = [clopper_pearson(k, n) for k in range(n + 1)]
    for p in [0.01, 0.05, 0.1, 0.25, 0.5, 0.75, 0.9, 0.97]:
        coverage = sum(
            math.comb(n, k) * p**k * (1 - p) ** (n - k)
            for k, ci in enumerate(intervals)
            if ci.low <= p <= ci.high
        )
        assert coverage >= 0.95 - 1e-9, (p, coverage)


def test_cp_narrows_with_more_data():
    assert (clopper_pearson(50, 100).high - clopper_pearson(50, 100).low) < (
        clopper_pearson(5, 10).high - clopper_pearson(5, 10).low
    )


@pytest.mark.parametrize(
    "k, n, level", [(0, 0, 0.95), (-1, 5, 0.95), (6, 5, 0.95), (2, 5, 1.0), (True, 5, 0.95)]
)
def test_cp_rejects_bad_input(k, n, level):
    with pytest.raises(ValueError):
        clopper_pearson(k, n, level)


def test_binom_cdf_matches_direct_sum():
    n, p = 12, 0.3
    for k in range(n + 1):
        direct = sum(math.comb(n, i) * p**i * (1 - p) ** (n - i) for i in range(k + 1))
        assert _binom_cdf(k, n, p) == pytest.approx(direct, abs=1e-12)


# --- bootstrap -------------------------------------------------------------------


def _mean(xs):
    return sum(xs) / len(xs)


def test_bootstrap_is_seeded():
    data = [0.1, 0.4, 0.35, 0.8, 0.55, 0.2, 0.9, 0.6]
    a = bootstrap_interval(data, _mean, seed=7)
    b = bootstrap_interval(data, _mean, seed=7)
    c = bootstrap_interval(data, _mean, seed=8)
    assert a == b
    assert (a.low, a.high) != (c.low, c.high)
    assert a.estimate == pytest.approx(_mean(data))
    assert a.low <= a.estimate <= a.high


def test_bootstrap_constant_data_has_zero_width():
    ci = bootstrap_interval([0.5] * 30, _mean, seed=1)
    assert ci.low == ci.high == 0.5


def test_bootstrap_resamples_whole_units():
    # Paired design: each unit is (before, after); the statistic sees intact pairs.
    pairs = [(1, 1), (1, 0), (0, 0), (1, 1)]
    seen = []

    def stat(units):
        seen.extend(units)
        return _mean([a - b for a, b in units])

    bootstrap_interval(pairs, stat, seed=3, resamples=100)
    assert set(seen) <= set(pairs)


@pytest.mark.parametrize("kwargs", [{"resamples": 99}, {"level": 0}])
def test_bootstrap_rejects_bad_settings(kwargs):
    with pytest.raises(ValueError):
        bootstrap_interval([1.0], _mean, seed=0, **kwargs)


def test_bootstrap_rejects_empty():
    with pytest.raises(ValueError, match="at least one"):
        bootstrap_interval([], _mean, seed=0)


def test_interval_validates_order():
    with pytest.raises(ValueError):
        Interval(estimate=0.9, low=0.1, high=0.5)


# --- verdicts --------------------------------------------------------------------


def _ci(lo, hi):
    return Interval(estimate=(lo + hi) / 2, low=lo, high=hi)


@pytest.mark.parametrize(
    "lo, hi, status",
    [(0.86, 0.95, PASS), (0.85, 0.95, PASS), (0.70, 0.84, FAIL), (0.80, 0.90, INCONCLUSIVE)],
)
def test_verdict_at_least(lo, hi, status):  # e.g. DCS >= 0.85
    assert verdict(_ci(lo, hi), 0.85, "at_least").status == status


@pytest.mark.parametrize(
    "lo, hi, status",
    [(0.01, 0.20, PASS), (0.21, 0.40, FAIL), (0.10, 0.30, INCONCLUSIVE)],
)
def test_verdict_at_most(lo, hi, status):  # e.g. LFDI <= 0.20
    assert verdict(_ci(lo, hi), 0.20, "at_most").status == status


@pytest.mark.parametrize(
    "lo, hi, status",
    [
        (-0.10, 0.12, PASS),
        (0.16, 0.30, FAIL),
        (-0.40, -0.16, FAIL),
        (0.05, 0.25, INCONCLUSIVE),
        (-0.20, 0.10, INCONCLUSIVE),
    ],
)
def test_verdict_abs_at_most(lo, hi, status):  # e.g. |ISG| <= 0.15
    assert verdict(_ci(lo, hi), 0.15, "abs_at_most").status == status


def test_verdict_too_few_events_is_inconclusive_even_if_interval_passes():
    v = verdict(_ci(0.9, 0.95), 0.85, "at_least", events=4)
    assert v.status == INCONCLUSIVE and "only 4 positive" in v.reason


def test_verdict_enough_events_uses_interval():
    assert verdict(_ci(0.9, 0.95), 0.85, "at_least", events=10).status == PASS
    assert verdict(_ci(0.9, 0.95), 0.85, "at_least", events=10, min_events=20).status == (
        INCONCLUSIVE
    )


def test_verdict_no_data():
    v = verdict(None, 0.85, "at_least")
    assert v.status == INCONCLUSIVE and v.reason == "no data to evaluate"


def test_verdict_unknown_rule():
    with pytest.raises(ValueError, match="rule"):
        verdict(_ci(0, 1), 0.5, "between")


def test_small_group_gets_inconclusive_from_the_interval_alone():
    # 9/10 caught looks fine, but the exact interval is too wide to clear 0.85.
    ci = clopper_pearson(9, 10)
    assert verdict(ci, 0.85, "at_least").status == INCONCLUSIVE
    assert verdict(clopper_pearson(190, 200), 0.85, "at_least").status == PASS


# --- noise floor -----------------------------------------------------------------


def test_majority_decision():
    yes, no, abst = (
        ModelResponse(decision=True),
        ModelResponse(decision=False),
        ModelResponse(decision=None, abstained=True),
    )
    assert majority_decision([yes, yes, no]) is True
    assert majority_decision([no, no, yes, abst]) is False
    assert majority_decision([yes, no]) is None
    assert majority_decision([abst, abst]) is None


def test_deterministic_model_is_detected_and_called_twice():
    calls = []
    adapter = ModelAdapter(lambda case: calls.append(case) or case % 2 == 0, "binary")
    floor, runs = measure_noise_floor(adapter, list(range(10)), repeats=5)
    assert floor.deterministic and floor.repeats == 2 and floor.flips == 0
    assert len(calls) == 20 and all(len(r) == 2 for r in runs)
    assert floor.rate.estimate == 0.0


def test_unstable_model_gets_full_repeats_and_a_measured_floor():
    # Cases 0-3 flip on every call; cases 4-9 are stable.
    state = itertools.count()

    def model(case):
        return next(state) % 2 == 0 if case < 4 else True

    adapter = ModelAdapter(model, "binary")
    floor, runs = measure_noise_floor(adapter, list(range(10)), repeats=5)
    assert not floor.deterministic and floor.repeats == 5
    assert all(len(r) == 5 for r in runs)
    assert floor.flips == 4 and floor.rate.estimate == pytest.approx(0.4)


def test_switching_between_answer_and_abstention_counts_as_a_flip():
    toggle = itertools.cycle(["FINAL_ANSWER: Yes", "FINAL_ANSWER: Unsure"])
    adapter = ModelAdapter(lambda case: next(toggle), "text")
    floor, _ = measure_noise_floor(adapter, ["a"], repeats=3)
    assert floor.flips == 1


def test_noise_floor_passes_targets_for_ranked_models():
    adapter = ModelAdapter(lambda case: ["Sepsis", "UTI"], "ranked", k=1)
    floor, runs = measure_noise_floor(adapter, ["c1", "c2"], targets=["Sepsis", "UTI"])
    assert floor.deterministic
    assert [r[0].decision for r in runs] == [True, False]


@pytest.mark.parametrize(
    "cases, kwargs",
    [([], {}), ([1], {"repeats": 1}), ([1, 2], {"targets": ["x"]}), ([1], {"repeats": 2.0})],
)
def test_noise_floor_rejects_bad_input(cases, kwargs):
    adapter = ModelAdapter(lambda case: True, "binary")
    with pytest.raises(ValueError):
        measure_noise_floor(adapter, cases, **kwargs)


def test_beyond_noise():
    adapter = ModelAdapter(lambda case: True, "binary")
    det_floor, _ = measure_noise_floor(adapter, [1, 2, 3])
    assert beyond_noise(_ci(0.01, 0.05), det_floor)
    assert not beyond_noise(_ci(0.0, 0.05), det_floor)

    state = itertools.count()
    noisy = ModelAdapter(lambda case: next(state) % 2 == 0, "binary")
    noisy_floor, _ = measure_noise_floor(noisy, list(range(20)))
    assert noisy_floor.rate.high > 0.8
    # An 8-12% demographic effect is real for a deterministic model but is
    # indistinguishable from this model's own re-run noise.
    effect = _ci(0.08, 0.12)
    assert beyond_noise(effect, det_floor) and not beyond_noise(effect, noisy_floor)
