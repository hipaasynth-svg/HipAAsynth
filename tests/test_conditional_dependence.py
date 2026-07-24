# HipAAsynth — Synthetic health data fairness testing for invisible populations.
# Copyright (C) 2026 HipAAsynth Contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published
# by the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.

"""Joint-fidelity + marginal-calibration tests for conditional dependence.

These tests guard the comorbidity dependence introduced in v1.2.1 (COPD by GOLD
stage, CHF by NYHA class via ``hipaasynth.core.dependence``). They assert three
distinct properties, and are designed to FAIL if the dependence structure is
removed or broken:

  1. MARGINAL PRESERVATION — the severity-conditional rates still reproduce the
     published national marginals (both analytically and in sampled cohorts).
  2. JOINT FIDELITY — known associations appear in the correct direction and
     approximate strength (higher GOLD/NYHA severity -> elevated comorbidity
     rates and worse functional scores). The gradient thresholds here are far
     above sampling noise, so reverting to independent draws (flat gradient)
     drives the measured spread to ~0 and fails these tests.
  3. DETERMINISM — identical seed + n reproduces byte-identical cohorts, and the
     draw helpers consume exactly one RNG value per comorbidity in a fixed order
     (the anchor-rooted RNG-stream contract).
"""

import json
import random

import pytest

from hipaasynth.core import dependence as dep
from hipaasynth.modules.copd.copd_generator import generate_copd_cohort
from hipaasynth.modules.chf.chf_generator import generate_chf_cohort

# Cohort size for sampled (statistical) assertions. Large enough that per-stratum
# proportions are stable to ~±0.02, well inside every tolerance below.
N = 4000
COPD_SEED = 3002
CHF_SEED = 4002

# Marginal tolerance for sampled cohorts. Tighter than the legacy calibration
# validator's 0.10 band — because the conditional model is marginal-preserving
# by construction, only sampling error remains.
MARGINAL_TOL = 0.05


def _present(row, key):
    """True if comorbidity ``key`` is set on a record — via its own boolean
    column when emitted, else via membership in the ``conditions`` string
    (some comorbidities, e.g. CHF liver_disease, appear only in the latter)."""
    if key in row:
        return row[key] is True
    return key in str(row.get("conditions", "")).split(";")


def _rate(rows, key, stratum=None):
    """Proportion of rows where ``key`` is present, optionally within a stratum
    ``(field, value)``."""
    subset = rows if stratum is None else [r for r in rows if r[stratum[0]] == stratum[1]]
    if not subset:
        return 0.0
    return sum(1 for r in subset if _present(r, key)) / len(subset)


def _mean(rows, key, stratum=None):
    subset = rows if stratum is None else [r for r in rows if r[stratum[0]] == stratum[1]]
    vals = [float(r[key]) for r in subset if r[key] is not None]
    return sum(vals) / len(vals) if vals else None


@pytest.fixture(scope="module")
def copd_cohort():
    rows, _ = generate_copd_cohort(seed=COPD_SEED, n=N)
    return rows


@pytest.fixture(scope="module")
def chf_cohort():
    rows, _ = generate_chf_cohort(seed=CHF_SEED, n=N)
    return rows


# ─────────────────────────────────────────────────────────────────────────────
# 1a. Marginal preservation — analytic (exact, no sampling)
# ─────────────────────────────────────────────────────────────────────────────
class TestRateTableInvariants:
    def test_copd_weighted_mean_equals_marginal(self):
        table = dep.COPD_RATES_BY_GOLD
        for comorbidity, (marginal, _shape) in dep.COPD_COMORBIDITY_MODEL.items():
            wmean = sum(
                w * table[comorbidity][s]
                for s, w in zip(dep.COPD_GOLD_STRATA, dep.COPD_GOLD_WEIGHTS)
            )
            assert wmean == pytest.approx(
                marginal, abs=1e-6
            ), f"COPD {comorbidity}: GOLD-weighted mean {wmean} != marginal {marginal}"

    def test_chf_weighted_mean_equals_marginal(self):
        table = dep.CHF_RATES_BY_NYHA
        for comorbidity, (marginal, _shape) in dep.CHF_COMORBIDITY_MODEL.items():
            wmean = sum(
                w * table[comorbidity][s] for s, w in zip(dep.CHF_NYHA_STRATA, dep.CHF_NYHA_WEIGHTS)
            )
            assert wmean == pytest.approx(
                marginal, abs=1e-6
            ), f"CHF {comorbidity}: NYHA-weighted mean {wmean} != marginal {marginal}"

    def test_no_rate_exceeds_cap(self):
        for table in (dep.COPD_RATES_BY_GOLD, dep.CHF_RATES_BY_NYHA):
            for comorbidity, stratum_rates in table.items():
                for stratum, rate in stratum_rates.items():
                    assert (
                        0.0 <= rate <= dep._RATE_CAP
                    ), f"{comorbidity}/{stratum} rate {rate} outside [0, {dep._RATE_CAP}]"

    def test_gradients_are_monotonic_increasing(self):
        # Every comorbidity rate must rise (or hold) with severity — the shape
        # that encodes dependence. A flat/independent model would be constant.
        for table, strata in (
            (dep.COPD_RATES_BY_GOLD, dep.COPD_GOLD_STRATA),
            (dep.CHF_RATES_BY_NYHA, dep.CHF_NYHA_STRATA),
        ):
            for comorbidity, stratum_rates in table.items():
                seq = [stratum_rates[s] for s in strata]
                assert all(
                    a <= b for a, b in zip(seq, seq[1:])
                ), f"{comorbidity} not monotonic across severity: {seq}"
                assert seq[-1] > seq[0], f"{comorbidity} has no severity gradient: {seq}"

    def test_locale_override_recenters_marginal(self):
        # The "marginal knob": a locale profile override must be reproduced
        # exactly by the weighted mean, with the gradient re-centered on it.
        override = {"type2_diabetes": 0.35, "pulmonary_hypertension": 0.30}
        table = dep.copd_comorbidity_rate_table(override)
        for comorbidity, new_marginal in override.items():
            wmean = sum(
                w * table[comorbidity][s]
                for s, w in zip(dep.COPD_GOLD_STRATA, dep.COPD_GOLD_WEIGHTS)
            )
            assert wmean == pytest.approx(new_marginal, abs=1e-6)
        # Untouched comorbidities keep their national marginal.
        assert table["osteoporosis"] == dep.COPD_RATES_BY_GOLD["osteoporosis"]


# ─────────────────────────────────────────────────────────────────────────────
# 1b. Marginal preservation — sampled cohorts
# ─────────────────────────────────────────────────────────────────────────────
class TestMarginalCalibration:
    def test_copd_marginals_preserved(self, copd_cohort):
        for comorbidity, (marginal, _shape) in dep.COPD_COMORBIDITY_MODEL.items():
            observed = _rate(copd_cohort, comorbidity)
            assert observed == pytest.approx(marginal, abs=MARGINAL_TOL), (
                f"COPD {comorbidity} marginal drifted: observed {observed:.3f} "
                f"vs target {marginal:.3f}"
            )

    def test_chf_marginals_preserved(self, chf_cohort):
        # 'cad' is intentionally excluded: ischemic cardiomyopathy deterministically
        # forces cad=True (pre-existing behavior), lifting its marginal above the
        # comorbidity-model value by design.
        for comorbidity, (marginal, _shape) in dep.CHF_COMORBIDITY_MODEL.items():
            if comorbidity == "cad":
                continue
            observed = _rate(chf_cohort, comorbidity)
            assert observed == pytest.approx(marginal, abs=MARGINAL_TOL), (
                f"CHF {comorbidity} marginal drifted: observed {observed:.3f} "
                f"vs target {marginal:.3f}"
            )


# ─────────────────────────────────────────────────────────────────────────────
# 2. Joint fidelity — directional associations + anti-tamper thresholds
# ─────────────────────────────────────────────────────────────────────────────
class TestJointAssociations:
    # These gradient thresholds are ~5-10x sampling noise. Reverting to
    # independent Bernoulli draws collapses each spread toward 0 and fails here.
    COPD_GRADIENT_MIN = 0.12
    CHF_GRADIENT_MIN = 0.10

    @pytest.mark.parametrize(
        "comorbidity", ["pulmonary_hypertension", "cardiovascular_disease", "osteoporosis"]
    )
    def test_copd_comorbidity_rises_with_gold_stage(self, copd_cohort, comorbidity):
        g1 = _rate(copd_cohort, comorbidity, ("gold_stage", "GOLD_1"))
        g4 = _rate(copd_cohort, comorbidity, ("gold_stage", "GOLD_4"))
        assert g4 - g1 > self.COPD_GRADIENT_MIN, (
            f"{comorbidity}: GOLD_4 ({g4:.3f}) not sufficiently above GOLD_1 "
            f"({g1:.3f}); dependence may be broken/flattened"
        )

    def test_copd_functional_scores_worsen_with_gold_stage(self, copd_cohort):
        # Functional status is already GOLD-conditional; this cross-checks that
        # the sequential order (severity -> functional) holds end to end.
        mwd_g1 = _mean(copd_cohort, "six_min_walk_m", ("gold_stage", "GOLD_1"))
        mwd_g4 = _mean(copd_cohort, "six_min_walk_m", ("gold_stage", "GOLD_4"))
        assert (
            mwd_g4 < mwd_g1 - 100
        ), f"6MWD should fall with severity: GOLD_1 {mwd_g1:.0f} vs GOLD_4 {mwd_g4:.0f}"
        mmrc_g1 = _mean(copd_cohort, "mmrc_dyspnea_grade", ("gold_stage", "GOLD_1"))
        mmrc_g4 = _mean(copd_cohort, "mmrc_dyspnea_grade", ("gold_stage", "GOLD_4"))
        assert mmrc_g4 > mmrc_g1, "mMRC dyspnea should rise with GOLD stage"

    @pytest.mark.parametrize("comorbidity", ["ckd", "anemia", "afib"])
    def test_chf_comorbidity_rises_with_nyha_class(self, chf_cohort, comorbidity):
        n2 = _rate(chf_cohort, comorbidity, ("nyha_class", "II"))
        n4 = _rate(chf_cohort, comorbidity, ("nyha_class", "IV"))
        assert n4 - n2 > self.CHF_GRADIENT_MIN, (
            f"{comorbidity}: NYHA IV ({n4:.3f}) not sufficiently above NYHA II "
            f"({n2:.3f}); dependence may be broken/flattened"
        )


# ─────────────────────────────────────────────────────────────────────────────
# 3. Determinism — byte-identical output + RNG-stream contract
# ─────────────────────────────────────────────────────────────────────────────
class TestDeterminism:
    def test_copd_byte_identical(self):
        a, anchor_a = generate_copd_cohort(seed=COPD_SEED, n=300)
        b, anchor_b = generate_copd_cohort(seed=COPD_SEED, n=300)
        assert anchor_a == anchor_b
        assert json.dumps(a, default=str) == json.dumps(b, default=str)

    def test_chf_byte_identical(self):
        a, _ = generate_chf_cohort(seed=CHF_SEED, n=300)
        b, _ = generate_chf_cohort(seed=CHF_SEED, n=300)
        assert json.dumps(a, default=str) == json.dumps(b, default=str)

    def test_copd_draw_consumes_exactly_one_per_comorbidity(self):
        # The RNG-stream contract: swapping independent draws for conditional
        # ones must not change how many RNG values are consumed, or all
        # downstream draws shift and determinism breaks.
        seed = 987654321
        n_draws = len(dep.COPD_COMORBIDITY_MODEL)
        reference = random.Random(seed)
        for _ in range(n_draws):
            reference.random()
        expected_next = reference.random()

        rng = random.Random(seed)
        dep.draw_copd_comorbidities(rng, "GOLD_3")
        assert rng.random() == expected_next, "COPD draw consumed != one value per comorbidity"

    def test_chf_draw_consumes_exactly_one_per_comorbidity(self):
        seed = 123456789
        n_draws = len(dep.CHF_COMORBIDITY_MODEL)
        reference = random.Random(seed)
        for _ in range(n_draws):
            reference.random()
        expected_next = reference.random()

        rng = random.Random(seed)
        dep.draw_chf_comorbidities(rng, "III")
        assert rng.random() == expected_next, "CHF draw consumed != one value per comorbidity"

    def test_draw_helpers_are_deterministic(self):
        assert dep.draw_copd_comorbidities(
            random.Random(7), "GOLD_2"
        ) == dep.draw_copd_comorbidities(random.Random(7), "GOLD_2")
        assert dep.draw_chf_comorbidities(random.Random(7), "III") == dep.draw_chf_comorbidities(
            random.Random(7), "III"
        )


# ─────────────────────────────────────────────────────────────────────────────
# 4. Life-outcomes stage-7 scaffold
# ─────────────────────────────────────────────────────────────────────────────
class TestLifeOutcomesScaffold:
    def test_fields_present_and_deterministic(self):
        kwargs = dict(functional_status=0.7, condition_count=2, age=45, sex="female")
        a = dep.draw_life_outcomes(random.Random(11), **kwargs)
        b = dep.draw_life_outcomes(random.Random(11), **kwargs)
        assert a == b
        for field in dep.LIFE_OUTCOME_FIELDS:
            assert field in a
        assert a["life_outcome_stage_status"] == "provisional_uncalibrated"

    def test_direction_high_vs_low_function(self):
        # Higher function -> more stable relationships, more employment, higher
        # income. Checked statistically over many working-age draws.
        def summarize(fs):
            stable = employed = high_income = 0
            trials = 1500
            for i in range(trials):
                out = dep.draw_life_outcomes(
                    random.Random(i),
                    functional_status=fs,
                    condition_count=2,
                    age=40,
                    sex="male",
                )
                stable += out["relationship_stability"] == "stable"
                employed += out["employment_status"] == "employed"
                high_income += out["income_band"] in ("upper_middle", "high")
            return stable / trials, employed / trials, high_income / trials

        hi_stable, hi_emp, hi_income = summarize(0.9)
        lo_stable, lo_emp, lo_income = summarize(0.15)
        assert hi_stable > lo_stable
        assert hi_emp > lo_emp
        assert hi_income > lo_income
