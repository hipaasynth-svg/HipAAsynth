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

"""Audit-stability metrics: concept drift, uncertainty, sensitivity (Tier 4, step 4).

Per ground rule 5, each metric is verified against a *constructed* reference case
with a known answer — a known drift, an analytic bootstrap standard error
(sqrt(p(1-p)/n)), and an analytic threshold sensitivity — not merely "it ran".
Hand-built passports are used so the inputs (and therefore the correct outputs)
are fully controlled.
"""
import math

import pytest

from hipaasynth.core.config import GenerationConfig
from hipaasynth.dif import (
    DIFConfig,
    bootstrap_uncertainty,
    concept_drift,
    run_audit,
    stability_report,
    threshold_sensitivity,
)
from hipaasynth.dif.model_interface import MockBiasedModel, MockFairModel
from hipaasynth.dif.report import FairnessPassport
from hipaasynth.pipelines.population_pipeline import generate_patients
from hipaasynth.polymorphic.metrics import PolymorphicMetrics


def _passport(dcs, overall_pass, *, isg=0.0, lfdi=0.0, saf=0.0, truth=True, pid="x"):
    """A hand-built passport with fully controlled metric values."""
    m = PolymorphicMetrics(
        dcs=dcs, isg=isg, lfdi=lfdi, saf=saf,
        dcs_pass=overall_pass, isg_pass=overall_pass,
        lfdi_pass=overall_pass, saf_pass=overall_pass,
        truth_evaluated=truth,
    )
    return FairnessPassport(
        device_name="d", device_version="1", test_date="t", patient_id=pid,
        ground_truth=True, decisions={}, metrics=m,
    )


# ─────────────────────────────────────────────────────────────────────────────
# 1. Concept drift.
# ─────────────────────────────────────────────────────────────────────────────
def test_identical_cohorts_have_zero_drift():
    a = [_passport(0.9, True, pid=f"p{i}") for i in range(10)]
    b = [_passport(0.9, True, pid=f"q{i}") for i in range(10)]
    results = {r.metric: r for r in concept_drift(a, b)}
    for r in results.values():
        assert r.drift == pytest.approx(0.0)
        assert r.drifted is False


def test_known_drift_is_measured_and_flagged():
    # Baseline all pass (rate 1.0); comparison all fail (rate 0.0) → drift -1.0.
    a = [_passport(0.9, True, pid=f"p{i}") for i in range(10)]
    b = [_passport(0.5, False, pid=f"q{i}") for i in range(10)]
    results = {r.metric: r for r in concept_drift(a, b, threshold=0.10)}
    opr = results["overall_pass_rate"]
    assert opr.baseline == pytest.approx(1.0)
    assert opr.comparison == pytest.approx(0.0)
    assert opr.drift == pytest.approx(-1.0)
    assert opr.drifted is True


def test_small_drift_below_threshold_not_flagged():
    # 10/10 pass vs 9/10 pass → drift -0.1, threshold 0.15 → not flagged.
    a = [_passport(0.9, True, pid=f"p{i}") for i in range(10)]
    b = [_passport(0.9, True, pid=f"q{i}") for i in range(9)] + [_passport(0.5, False, pid="qf")]
    results = {r.metric: r for r in concept_drift(a, b, threshold=0.15)}
    opr = results["overall_pass_rate"]
    assert opr.drift == pytest.approx(-0.1)
    assert opr.drifted is False


def test_concept_drift_requires_nonempty_cohorts():
    with pytest.raises(ValueError):
        concept_drift([], [_passport(0.9, True)])


# ─────────────────────────────────────────────────────────────────────────────
# 2. Uncertainty (bootstrap) — against an analytic standard error.
# ─────────────────────────────────────────────────────────────────────────────
def test_bootstrap_se_matches_analytic_binomial():
    # n=100, pass rate 0.5 → bootstrap SE ≈ sqrt(p(1-p)/n) = 0.05.
    ps = ([_passport(0.9, True, pid=f"p{i}") for i in range(50)]
          + [_passport(0.5, False, pid=f"q{i}") for i in range(50)])
    u = bootstrap_uncertainty(ps, metric="overall_pass_rate", n_resamples=2000, seed=0)
    assert u.point_estimate == pytest.approx(0.5)
    analytic = math.sqrt(0.5 * 0.5 / 100)
    assert u.std_error == pytest.approx(analytic, abs=0.01)
    assert u.ci95_low < 0.5 < u.ci95_high


def test_bootstrap_se_zero_for_constant_cohort():
    # Every passport identical → no resample variation → SE exactly 0.
    ps = [_passport(0.9, True, pid=f"p{i}") for i in range(30)]
    u = bootstrap_uncertainty(ps, metric="overall_pass_rate", n_resamples=200, seed=1)
    assert u.point_estimate == pytest.approx(1.0)
    assert u.std_error == pytest.approx(0.0)
    assert u.ci95_low == pytest.approx(1.0)
    assert u.ci95_high == pytest.approx(1.0)


def test_bootstrap_is_deterministic():
    ps = ([_passport(0.9, True, pid=f"p{i}") for i in range(20)]
          + [_passport(0.5, False, pid=f"q{i}") for i in range(20)])
    a = bootstrap_uncertainty(ps, seed=7, n_resamples=300)
    b = bootstrap_uncertainty(ps, seed=7, n_resamples=300)
    assert a == b


def test_bootstrap_rejects_unknown_metric_and_empty():
    with pytest.raises(ValueError):
        bootstrap_uncertainty([_passport(0.9, True)], metric="not_a_metric")
    with pytest.raises(ValueError):
        bootstrap_uncertainty([], metric="dcs_mean")


# ─────────────────────────────────────────────────────────────────────────────
# 3. Sensitivity (threshold finite difference) — against an analytic slope.
# ─────────────────────────────────────────────────────────────────────────────
def test_threshold_sensitivity_matches_analytic():
    # 60 patients at dcs=0.90, 40 at dcs=0.82; base thr 0.85, delta 0.05.
    #   at 0.80: all 100 pass → 1.0
    #   at 0.85: only the 0.90 group → 0.60
    #   at 0.90: only the 0.90 group → 0.60
    #   slope = (0.60 - 1.0) / (2*0.05) = -4.0
    ps = ([_passport(0.90, True, pid=f"a{i}") for i in range(60)]
          + [_passport(0.82, True, pid=f"b{i}") for i in range(40)])
    s = threshold_sensitivity(ps, threshold_name="dcs", base_threshold=0.85, delta=0.05)
    assert s.rate_minus == pytest.approx(1.0)
    assert s.rate_base == pytest.approx(0.6)
    assert s.rate_plus == pytest.approx(0.6)
    assert s.sensitivity == pytest.approx(-4.0)


def test_dcs_sensitivity_is_nonpositive():
    # DCS passes when value >= threshold, so raising the threshold can only lower
    # the pass rate → slope must be <= 0 for any cohort.
    ps = [_passport(0.5 + 0.4 * (i / 50), i % 2 == 0, pid=f"p{i}") for i in range(50)]
    s = threshold_sensitivity(ps, threshold_name="dcs", base_threshold=0.75, delta=0.05)
    assert s.sensitivity <= 0.0


def test_threshold_sensitivity_rejects_bad_args():
    ps = [_passport(0.9, True)]
    with pytest.raises(ValueError):
        threshold_sensitivity(ps, threshold_name="nope")
    with pytest.raises(ValueError):
        threshold_sensitivity(ps, delta=0.0)
    with pytest.raises(ValueError):
        threshold_sensitivity([], threshold_name="dcs")


# ─────────────────────────────────────────────────────────────────────────────
# Bundle + end-to-end integration with a real audit.
# ─────────────────────────────────────────────────────────────────────────────
def test_stability_report_bundle_and_markdown():
    a = [_passport(0.9, True, pid=f"p{i}") for i in range(20)]
    b = [_passport(0.5, False, pid=f"q{i}") for i in range(20)]
    report = stability_report(a, b, n_resamples=100)
    assert report.any_drift() is True
    md = report.to_markdown()
    assert "Concept Drift" in md
    assert "Uncertainty (bootstrap)" in md
    assert "Sensitivity" in md


def _audit(seed, model):
    cfg = GenerationConfig(patient_count=40, seed=seed, required_condition="stroke",
                           run_date="2026-01-01")
    return run_audit(model, generate_patients, cfg,
                     DIFConfig(device_name="M", device_version="1"))


def test_end_to_end_drift_between_biased_and_fair_model():
    # A biased and a fair model auditing the same cohort config must show large,
    # flagged drift on the fairness metrics — the audit is model-sensitive.
    biased = _audit(1, MockBiasedModel())
    fair = _audit(1, MockFairModel())
    results = {r.metric: r for r in concept_drift(biased, fair)}
    assert results["overall_pass_rate"].drifted is True
    # The fair model passes far more often than the biased one.
    assert results["overall_pass_rate"].drift > 0.5


def test_end_to_end_no_drift_across_seeds_same_model():
    # Regenerating the cohort with a different seed but the same (deterministic)
    # model must not meaningfully move the biased model's fairness metrics.
    a = _audit(1, MockBiasedModel())
    b = _audit(2, MockBiasedModel())
    for r in concept_drift(a, b):
        assert r.drifted is False
