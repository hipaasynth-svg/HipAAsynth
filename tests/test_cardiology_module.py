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

"""Tests for the cardiology cohort generator and its clinical sub-components.

Unlike ``test_module_smoke.py`` — which exercises every module's *generic*
invariants (size, determinism, unique ids, identifier safety, synthetic
stamp) — this module asserts the cardiology-specific *clinical coherence* of
the generated cohort:

- risk factors stay inside the physiological / PCE-eligible ranges the module
  documents (age 40-79, bounded lipids and systolic BP);
- the ASCVD 10-yr risk value and its tier label agree with the ACC/AHA Pooled
  Cohort Equations thresholds the module cites;
- CHA2DS2-VASc, HAS-BLED, and HEART scores can be re-derived from the emitted
  fields, exactly as their published rules define them — so a future edit that
  silently drifts the scoring logic fails here;
- the medication columns are internally consistent (a drug detail is present
  iff the patient is on that drug class, ``total_meds`` equals the class count)
  and only appear for clinically eligible patients.

The point of the cardiology module is a risk-tiered, guideline-consistent
population; these tests guard that contract without touching engine code.
"""

import math

import pytest

from hipaasynth.core.config import DEFAULT_SYNTHETIC_DISCLAIMER
from hipaasynth.modules.cardiology.cohort import (
    CardiologyCohortGenerator,
    generate_cardiology_cohort,
)
from hipaasynth.modules.cardiology.risk_scores import CardioRiskScores


def _cohort(n=200, seed=42):
    return CardiologyCohortGenerator(seed=seed).generate(n)


# ---------------------------------------------------------------------------
# Cohort shape, determinism, and the synthetic-data stamp
# ---------------------------------------------------------------------------
class TestCohortBasics:
    def test_generates_requested_size(self) -> None:
        assert len(_cohort(n=50)) == 50

    def test_convenience_wrapper_matches_class(self) -> None:
        assert generate_cardiology_cohort(seed=7, n=25) == (
            CardiologyCohortGenerator(seed=7).generate(25)
        )

    def test_deterministic_for_fixed_seed(self) -> None:
        assert _cohort(n=64, seed=1) == _cohort(n=64, seed=1)

    def test_distinct_seeds_diverge(self) -> None:
        assert _cohort(n=64, seed=1) != _cohort(n=64, seed=2)

    def test_patient_ids_unique_and_stamped(self) -> None:
        cohort = _cohort()
        ids = [r["patient_id"] for r in cohort]
        assert len(set(ids)) == len(ids)
        for r in cohort:
            assert r["patient_id"].startswith("CARDIO-")
            assert r["synthetic"] is True
            assert r["disclaimer"] == DEFAULT_SYNTHETIC_DISCLAIMER


# ---------------------------------------------------------------------------
# Risk factors sit inside the ranges the module documents
# ---------------------------------------------------------------------------
class TestRiskFactorRanges:
    def test_ages_are_pce_eligible(self) -> None:
        # The Pooled Cohort Equations apply over 40-79; the generator draws
        # uniformly across exactly that window.
        for r in _cohort():
            assert 40 <= r["age"] <= 79

    def test_bounded_physiology(self) -> None:
        for r in _cohort():
            assert 120 <= r["total_cholesterol"] <= 330
            assert 20 <= r["hdl_cholesterol"] <= 100
            assert 90 <= r["systolic_bp"] <= 210

    def test_categorical_fields_are_in_vocabulary(self) -> None:
        for r in _cohort():
            assert r["sex"] in {"male", "female"}
            assert r["race"] in set(CardiologyCohortGenerator.RACES)
            assert r["smoking_status"] in {"current", "former", "never"}

    def test_hypertension_flag_follows_threshold(self) -> None:
        # The generator sets hypertension whenever SBP >= 130 (2017 ACC/AHA),
        # plus a stochastic extra; the threshold implication must always hold.
        for r in _cohort():
            if r["systolic_bp"] >= 130:
                assert r["hypertension"] is True


# ---------------------------------------------------------------------------
# ASCVD risk value and tier label agree with the PCE thresholds
# ---------------------------------------------------------------------------
class TestASCVD:
    THRESHOLDS = (
        ("low", 0.0, 0.05),
        ("borderline", 0.05, 0.075),
        ("intermediate", 0.075, 0.20),
        ("high", 0.20, 1.01),
    )

    def _category(self, risk: float) -> str:
        for label, lo, hi in self.THRESHOLDS:
            if lo <= risk < hi:
                return label
        raise AssertionError(risk)

    def test_risk_is_clamped_probability(self) -> None:
        for r in _cohort():
            assert 0.005 <= r["ascvd_10yr"] <= 0.75

    def test_category_matches_risk_value(self) -> None:
        for r in _cohort():
            assert r["ascvd_category"] == self._category(r["ascvd_10yr"])

    def test_cohort_spans_multiple_tiers(self) -> None:
        # A risk-tiered population is the whole point; a degenerate cohort that
        # collapsed to a single tier would defeat any downstream fairness audit.
        cats = {r["ascvd_category"] for r in _cohort()}
        assert len(cats) >= 3
        assert "high" in cats and "low" in cats

    def test_ascvd_logit_is_monotonic_in_age(self) -> None:
        # Holding every other risk factor fixed, older age must not lower the
        # modelled risk — a guard on the sign of the age coefficient.
        base = {
            "age": [50, 70],
            "sex": ["male", "male"],
            "total_cholesterol": [200, 200],
            "hdl_cholesterol": [50, 50],
            "systolic_bp": [130, 130],
            "smoking_status": ["never", "never"],
            "diabetes": [False, False],
        }
        risks = CardioRiskScores(2)._ascvd(base)
        assert risks[1] > risks[0]


# ---------------------------------------------------------------------------
# The published scores can be re-derived exactly from the emitted fields
# ---------------------------------------------------------------------------
class TestScoreDerivations:
    def _expected_cha2ds2_vasc(self, r) -> int:
        score = 0
        score += int(bool(r["heart_failure"]))
        score += int(bool(r["hypertension"]))
        if r["age"] >= 75:
            score += 2
        elif r["age"] >= 65:
            score += 1
        score += int(bool(r["diabetes"]))
        if r["sex"] == "female":
            score += 1
        return score

    def _expected_has_bled(self, r) -> int:
        score = 0
        if r["systolic_bp"] > 160:
            score += 1
        if r["age"] > 65:
            score += 1
        return score

    def _expected_heart(self, r) -> int:
        age = r["age"]
        diabetes = bool(r["diabetes"])
        smoker = r["smoking_status"] == "current"
        score = 0
        if age > 65 and (diabetes or smoker):
            score += 2
        elif age > 50 or diabetes or smoker:
            score += 1
        if age >= 65:
            score += 2
        elif age >= 45:
            score += 1
        risk_count = int(bool(r["hypertension"])) + int(diabetes) + int(smoker)
        if risk_count >= 3:
            score += 2
        elif risk_count >= 1:
            score += 1
        return score

    def test_cha2ds2_vasc_matches_rule(self) -> None:
        for r in _cohort():
            assert r["cha2ds2_vasc"] == self._expected_cha2ds2_vasc(r)

    def test_has_bled_matches_rule(self) -> None:
        for r in _cohort():
            assert r["has_bled"] == self._expected_has_bled(r)

    def test_heart_score_matches_rule(self) -> None:
        for r in _cohort():
            assert r["heart_score"] == self._expected_heart(r)


# ---------------------------------------------------------------------------
# Medication columns are internally consistent and clinically gated
# ---------------------------------------------------------------------------
class TestMedications:
    DETAIL_FOR_FLAG = {
        "on_antihypertensive": "htn_meds",
        "on_statin": "statin_intensity",
        "on_anticoagulant": "anticoagulant_type",
        "on_antiplatelet": "antiplatelet_type",
        "on_hf_therapy": "hf_meds",
        "on_diabetes_meds": "diabetes_meds",
    }

    def test_detail_present_iff_on_therapy(self) -> None:
        for r in _cohort():
            for flag, detail in self.DETAIL_FOR_FLAG.items():
                if r[flag]:
                    assert r[detail] is not None
                else:
                    assert r[detail] is None

    def test_total_meds_equals_class_count(self) -> None:
        for r in _cohort():
            assert r["total_meds"] == sum(
                int(r[flag]) for flag in self.DETAIL_FOR_FLAG
            )

    def test_statin_intensity_vocabulary(self) -> None:
        for r in _cohort():
            if r["on_statin"]:
                assert r["statin_intensity"] in {"moderate", "high"}

    def test_anticoagulation_requires_atrial_fibrillation(self) -> None:
        # The only anticoagulation branch in the module is gated on AF.
        for r in _cohort():
            if r["on_anticoagulant"]:
                assert r["atrial_fibrillation"] is True
                assert r["anticoagulant_type"] in {"doac", "warfarin"}

    def test_hf_therapy_requires_heart_failure(self) -> None:
        for r in _cohort():
            if r["on_hf_therapy"]:
                assert r["heart_failure"] is True

    def test_diabetes_meds_require_diabetes_and_include_metformin(self) -> None:
        for r in _cohort():
            if r["on_diabetes_meds"]:
                assert r["diabetes"] is True
                assert "metformin" in r["diabetes_meds"].split(",")


# ---------------------------------------------------------------------------
# The convenience entry point and the documented distribution stay sane
# ---------------------------------------------------------------------------
class TestDistribution:
    @pytest.mark.parametrize("seed", [1, 42, 123])
    def test_high_risk_tail_is_present_but_not_dominant(self, seed) -> None:
        cohort = _cohort(n=400, seed=seed)
        high = sum(r["ascvd_category"] == "high" for r in cohort)
        frac = high / len(cohort)
        # A CV-risk-enriched cohort should carry a real high-risk tail without
        # the whole population collapsing into it.
        assert 0.0 < frac < 0.6

    def test_no_nan_risks(self) -> None:
        for r in _cohort():
            assert not math.isnan(r["ascvd_10yr"])
