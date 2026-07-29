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

"""Statistical-fidelity checks (Tier 4, step 1).

Per ground rule 5, the correlation statistic itself is verified against
*constructed* reference cases (perfectly correlated / anti-correlated /
independent / degenerate) — not merely "it ran" — before it is trusted to judge
the engine's clinically-linked variables.
"""
import math

import pytest

from hipaasynth.core.config import GenerationConfig
from hipaasynth.core.schema import (
    Anthropometrics,
    Condition,
    Demographics,
    LabResult,
    Patient,
    Visit,
)
from hipaasynth.pipelines.population_pipeline import generate_patients
from hipaasynth.validation.fidelity import (
    condition_prevalence,
    fidelity_report,
    lab_value_marginals,
    linked_lab_correlations,
    pearson_correlation,
    temporal_consistency,
    visit_order_report,
)


# ─────────────────────────────────────────────────────────────────────────────
# The statistic, against constructed reference cases (ground rule 5).
# ─────────────────────────────────────────────────────────────────────────────
def test_pearson_perfectly_correlated_is_one():
    assert pearson_correlation([1, 2, 3, 4], [2, 4, 6, 8]) == pytest.approx(1.0)


def test_pearson_perfectly_anticorrelated_is_minus_one():
    assert pearson_correlation([1, 2, 3, 4], [8, 6, 4, 2]) == pytest.approx(-1.0)


def test_pearson_independent_is_near_zero():
    # A deliberately independent construction: y alternates regardless of x.
    xs = list(range(20))
    ys = [1.0 if i % 2 == 0 else 0.0 for i in range(20)]
    r = pearson_correlation(xs, ys)
    assert r is not None
    assert abs(r) < 0.15


def test_pearson_constant_variable_is_none():
    # Zero variance in a variable → correlation undefined → None (not a crash).
    assert pearson_correlation([1, 1, 1, 1], [1, 2, 3, 4]) is None
    assert pearson_correlation([5], [7]) is None  # < 2 points


def test_pearson_mismatched_lengths_raises():
    with pytest.raises(ValueError):
        pearson_correlation([1, 2, 3], [1, 2])


# ─────────────────────────────────────────────────────────────────────────────
# Marginal distributions.
# ─────────────────────────────────────────────────────────────────────────────
def _cohort(**overrides):
    base = dict(
        patient_count=150, seed=7, age_min=40, age_max=90,
        include_visits=True, include_labs=True, visits_min=1, visits_max=2,
    )
    base.update(overrides)
    return generate_patients(GenerationConfig(**base))


def test_lab_marginals_cover_generated_analytes():
    marginals = lab_value_marginals(_cohort())
    # The four calibrated analytes from generator_numerics must all appear.
    for analyte in ("Glucose", "Creatinine", "LDL", "WBC"):
        assert analyte in marginals
        summ = marginals[analyte]
        assert summ["n"] > 0
        assert summ["min"] <= summ["median"] <= summ["max"]
    # Physiological floors from the generator must hold in the marginal.
    assert marginals["Glucose"]["min"] >= 65.0
    assert marginals["Creatinine"]["min"] >= 0.4


def test_condition_prevalence_sums_are_sane():
    prev = condition_prevalence(_cohort())
    assert "hypertension" in prev
    for name, stats in prev.items():
        assert 0.0 <= stats["prevalence"] <= 1.0
        assert stats["count"] >= 1


# ─────────────────────────────────────────────────────────────────────────────
# Clinically-linked variable correlations — the engine's own couplings.
# ─────────────────────────────────────────────────────────────────────────────
def test_diabetes_glucose_coupling_is_detected():
    corrs = {c.condition: c for c in linked_lab_correlations(_cohort())}
    dm = corrs["type2_diabetes"]
    assert dm.n_with > 0 and dm.n_without > 0
    # Engine draws diabetic glucose as max(baseline, N(164,40)): diabetics must
    # sit well above non-diabetics, with a strong positive point-biserial.
    assert dm.mean_with > dm.mean_without
    assert dm.mean_shift > 20.0
    assert dm.direction_ok is True
    assert dm.point_biserial is not None and dm.point_biserial > 0.3


def test_ckd_and_hyperlipidemia_couplings_are_detected():
    corrs = {c.condition: c for c in linked_lab_correlations(_cohort())}
    ckd = corrs["chronic_kidney_disease"]
    assert ckd.n_with > 0 and ckd.n_without > 0
    assert ckd.direction_ok is True
    assert ckd.mean_with >= 1.05  # engine floor for CKD creatinine

    lipid = corrs["hyperlipidemia"]
    assert lipid.n_with > 0 and lipid.n_without > 0
    assert lipid.direction_ok is True
    assert lipid.mean_with >= 160.0  # engine floor for hyperlipidemia LDL


def test_sepsis_wbc_coupling_elevates_marginal():
    # Sepsis is a required-condition module; every patient carries it, so there
    # is no "without" group — instead assert the coupled WBC marginal is lifted
    # into the leukocytosis range the engine encodes (11-19 K/uL).
    septic = _cohort(patient_count=60, seed=3, required_condition="sepsis")
    corrs = {c.condition: c for c in linked_lab_correlations(septic)}
    sep = corrs["sepsis"]
    assert sep.n_with == 60
    assert sep.mean_with is not None and sep.mean_with >= 11.0
    # Non-septic baseline WBC mean is ~7; the septic cohort must be clearly above.
    assert sep.mean_with > 10.0


def test_direction_ok_is_none_when_a_group_is_empty():
    # A default cohort has no sepsis patients, so the sepsis coupling can't be
    # evaluated — direction_ok must be None (unknown), never False (a real fail).
    corrs = {c.condition: c for c in linked_lab_correlations(_cohort())}
    assert corrs["sepsis"].direction_ok is None
    assert corrs["sepsis"].mean_shift is None


# ─────────────────────────────────────────────────────────────────────────────
# Temporal consistency.
# ─────────────────────────────────────────────────────────────────────────────
def test_generated_cohort_is_temporally_consistent():
    report = temporal_consistency(_cohort())
    assert report.ok
    assert report.violations == 0
    assert report.n_conditions_checked > 0
    assert report.n_measurements_checked > 0


def _hand_patient(*, age, onset_age, lab_date, visit_date="2024-06-01"):
    demo = Demographics(patient_id="H1", seed=1, age=age, sex="male", ethnicity="white")
    anth = Anthropometrics(height_cm=170, weight_kg=70, bmi=24.2, bmi_category="normal")
    cond = Condition(name="type2_diabetes", onset_age=onset_age, active=True)
    visit = Visit(
        visit_id="V1", visit_type="outpatient", visit_date=visit_date,
        primary_diagnosis="type2_diabetes",
        labs=[LabResult(lab_name="Glucose", value=120.0, unit="mg/dL",
                        reference_range="70-99", date_recorded=lab_date)],
    )
    return Patient(demographics=demo, anthropometrics=anth, conditions=[cond],
                   visits=[visit], engine_version="x", schema_version="y")


def test_temporal_check_fires_on_onset_after_age():
    bad = _hand_patient(age=30, onset_age=45, lab_date="2024-06-01")
    report = temporal_consistency([bad])
    assert not report.ok
    assert len(report.onset_after_age) == 1
    assert report.onset_after_age[0]["condition"] == "type2_diabetes"


def test_temporal_check_fires_on_measurement_outside_span():
    bad = _hand_patient(age=50, onset_age=40, lab_date="1999-01-01")
    report = temporal_consistency([bad])
    assert not report.ok
    assert len(report.measurement_outside_span) == 1
    assert report.measurement_outside_span[0]["measurement_date"] == "1999-01-01"


def test_temporal_check_does_not_false_positive_on_valid_hand_patient():
    good = _hand_patient(age=50, onset_age=40, lab_date="2024-06-01")
    report = temporal_consistency([good])
    assert report.ok


def test_visit_order_report_is_descriptive_not_a_failure():
    report = visit_order_report(_cohort())
    assert "ordered_fraction" in report
    # Purely informational — no assertion that visits are ordered.
    assert report["multi_visit_patients"] >= 0


# ─────────────────────────────────────────────────────────────────────────────
# Top-level report.
# ─────────────────────────────────────────────────────────────────────────────
def test_fidelity_report_shape():
    report = fidelity_report(_cohort())
    assert report["n_patients"] == 150
    assert set(report) >= {
        "lab_marginals", "condition_prevalence", "linked_lab_correlations",
        "temporal_consistency", "visit_order",
    }
    assert report["temporal_consistency"]["ok"] is True
    assert isinstance(report["linked_lab_correlations"], list)


def test_fidelity_report_rejects_empty_cohort():
    with pytest.raises(ValueError):
        fidelity_report([])
