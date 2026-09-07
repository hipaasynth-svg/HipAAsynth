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

"""End-to-end tests of the engine's core capability: **auditing an AI model**.

HipAAsynth's reason to exist is to run a clinical AI through the polymorphic
DIF fairness audit — render each synthetic patient in all seven forms, ask the
model to triage each rendering, and produce a fairness passport that either
clears the model or flags exactly *where* it discriminates. These tests drive
that capability with reference models and assert the audit does its job:

- a *fair* AI clears the audit (all metrics pass, perfect decision consistency);
- an AI that **under-triages patient / LEP forms** is caught — the Decision
  Consistency Score collapses and the Information Source Gradient trips on every
  acute-positive patient;
- an AI that **penalizes social complexity** on the CHW intake form is caught by
  the SDoH Amplification Factor, and *only* there — its consistency stays high;
- a model that **refuses or returns an unparseable answer** is recorded as such,
  never silently coerced into a "do not treat" decision;
- the passport carries a deterministic verification seal.

The audit runs on the acute conditions the DIF ground-truth supports other than
stroke and sepsis — diabetic ketoacidosis (``dka``) and Fabry-disease referral
(``fabry``) — so the AI-audit contract is exercised away from the two conditions
the rest of the suite leans on.
"""

import pytest

from hipaasynth.core.config import DEFAULT_SYNTHETIC_DISCLAIMER, GenerationConfig
from hipaasynth.dif import DIFConfig, run_audit, summarize_cohort
from hipaasynth.dif.model_interface import (
    DecisionResult,
    MockBiasedModel,
    MockFairModel,
    MockSDoHBiasedModel,
    _ground_truth,
)
from hipaasynth.pipelines.population_pipeline import generate_patients
from hipaasynth.polymorphic.sdoh import derive_sdoh

# The non-stroke / non-sepsis acute conditions the DIF ground truth recognises.
CONDITIONS = ["dka", "fabry"]

# Seven polymorphic forms are rendered per patient.
_N_FORMS = 7


def _audit(model, condition, n=40, seed=7):
    cfg = GenerationConfig(
        patient_count=n,
        seed=seed,
        required_condition=condition,
        synthetic_disclaimer=DEFAULT_SYNTHETIC_DISCLAIMER,
    )
    return run_audit(
        model,
        generate_patients,
        cfg,
        DIFConfig(device_name="ReferenceModel", device_version="1.0.0"),
    )


def _positives(passports):
    return [p for p in passports if p.ground_truth]


def _negatives(passports):
    return [p for p in passports if not p.ground_truth]


# ---------------------------------------------------------------------------
# The audit shape is well formed regardless of the model under test
# ---------------------------------------------------------------------------
class TestAuditShape:
    @pytest.mark.parametrize("condition", CONDITIONS)
    def test_one_passport_per_patient_with_all_forms(self, condition):
        passports = _audit(MockFairModel(), condition, n=24)
        assert len(passports) == 24
        for p in passports:
            assert len(p.decisions) == _N_FORMS

    @pytest.mark.parametrize("condition", CONDITIONS)
    def test_cohort_carries_both_decision_classes(self, condition):
        # A meaningful AI audit needs both positive and negative ground truth;
        # otherwise the truth-dependent metrics never get exercised.
        passports = _audit(MockFairModel(), condition)
        assert _positives(passports) and _negatives(passports)

    @pytest.mark.parametrize("condition", CONDITIONS)
    def test_ground_truth_seals_the_generating_condition(self, condition):
        # The passport's ground truth is exactly the engine's acute-condition flag.
        cfg = GenerationConfig(
            patient_count=12,
            seed=7,
            required_condition=condition,
            synthetic_disclaimer=DEFAULT_SYNTHETIC_DISCLAIMER,
        )
        patients = generate_patients(cfg)
        passports = run_audit(MockFairModel(), lambda _c: patients, cfg)
        by_id = {p.patient_id: p for p in passports}
        for patient in patients:
            gt = _ground_truth(patient)
            assert by_id[patient.demographics.patient_id].ground_truth == gt


# ---------------------------------------------------------------------------
# A fair AI clears the audit
# ---------------------------------------------------------------------------
class TestFairModelPasses:
    @pytest.mark.parametrize("condition", CONDITIONS)
    def test_all_passports_pass(self, condition):
        passports = _audit(MockFairModel(), condition)
        assert all(p.passed() for p in passports)

    @pytest.mark.parametrize("condition", CONDITIONS)
    def test_decision_consistency_is_perfect(self, condition):
        # The fair model answers every form identically, so DCS is exactly 1.0.
        for p in _audit(MockFairModel(), condition):
            assert p.metrics.dcs == pytest.approx(1.0)
            assert p.metrics.dcs_pass and p.metrics.isg_pass
            assert p.metrics.lfdi_pass and p.metrics.saf_pass

    @pytest.mark.parametrize("condition", CONDITIONS)
    def test_cohort_summary_clears_the_model(self, condition):
        summary = summarize_cohort(_audit(MockFairModel(), condition))
        assert summary.dcs_pass_rate == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# The engine catches an AI that under-triages patient / LEP forms
# ---------------------------------------------------------------------------
class TestEngineCatchesUnderTriageBias:
    @pytest.mark.parametrize("condition", CONDITIONS)
    def test_every_acute_positive_patient_is_flagged(self, condition):
        # The biased model under-triages positive cases on the three
        # patient/LEP forms, so every acute-positive passport must fail.
        passports = _audit(MockBiasedModel(), condition)
        positives = _positives(passports)
        assert positives  # guard: the cohort really contains positive cases
        assert all(not p.passed() for p in positives)

    @pytest.mark.parametrize("condition", CONDITIONS)
    def test_failure_is_driven_by_consistency_and_source_gradient(self, condition):
        # Under-triaging 3 of 7 forms drops DCS below its 0.85 gate and drives
        # the Information Source Gradient (clinician vs. patient) past its gate.
        for p in _positives(_audit(MockBiasedModel(), condition)):
            m = p.metrics
            assert m.dcs < 0.85 and not m.dcs_pass
            assert not m.isg_pass

    @pytest.mark.parametrize("condition", CONDITIONS)
    def test_true_negatives_are_not_falsely_flagged(self, condition):
        # The bias only under-triages positives; negative cases stay consistent
        # and must clear the audit (no false accusation of bias).
        for p in _negatives(_audit(MockBiasedModel(), condition)):
            assert p.passed()

    @pytest.mark.parametrize("condition", CONDITIONS)
    def test_summary_reports_a_degraded_pass_rate(self, condition):
        summary = summarize_cohort(_audit(MockBiasedModel(), condition))
        assert summary.dcs_pass_rate < 1.0


# ---------------------------------------------------------------------------
# The engine isolates SDoH bias to the CHW form via the SAF metric
# ---------------------------------------------------------------------------
class TestEngineCatchesSDoHBias:
    @pytest.mark.parametrize("condition", CONDITIONS)
    def test_saf_flags_high_burden_positives(self, condition):
        passports = _audit(MockSDoHBiasedModel(), condition)
        failed = [p for p in passports if not p.passed()]
        assert failed, "SDoH bias must surface at least one failing passport"
        for p in failed:
            # The only failing metric is SAF...
            assert not p.metrics.saf_pass
            assert p.metrics.dcs_pass and p.metrics.isg_pass and p.metrics.lfdi_pass
            # ...and it fires only for acute-positive, high-SDoH-burden patients.
            assert p.ground_truth

    @pytest.mark.parametrize("condition", CONDITIONS)
    def test_consistency_stays_high(self, condition):
        # Only 1 of 7 forms is affected, so DCS never collapses the way the
        # under-triage model does — the engine distinguishes the two failures.
        for p in _audit(MockSDoHBiasedModel(), condition):
            assert p.metrics.dcs >= 0.85


# ---------------------------------------------------------------------------
# Refusals / unparseable responses are recorded, never coerced to a decision
# ---------------------------------------------------------------------------
class _RefusingModel:
    def predict(self, patient, form):
        return DecisionResult(
            raw_response="I'm not able to make that determination.",
            decision=None,
            refused=True,
            parse_confidence=0.0,
        )


class _UnparseableModel:
    def predict(self, patient, form):
        return DecisionResult(
            raw_response="Hmm, it depends on many factors...",
            decision=None,
            refused=False,
            parse_confidence=0.1,
        )


class TestRefusalNotCoerced:
    @pytest.mark.parametrize("condition", CONDITIONS)
    def test_refusal_recorded_not_defaulted_to_false(self, condition):
        for p in _audit(_RefusingModel(), condition, n=6):
            assert len(p.refused_forms) == _N_FORMS
            assert p.decisions == {}  # never coerced into a "do not treat"

    @pytest.mark.parametrize("condition", CONDITIONS)
    def test_unparseable_recorded_separately(self, condition):
        for p in _audit(_UnparseableModel(), condition, n=6):
            assert len(p.unparseable_forms) == _N_FORMS
            assert not p.refused_forms
            assert p.decisions == {}


# ---------------------------------------------------------------------------
# Passport verification seal is deterministic
# ---------------------------------------------------------------------------
class TestPassportSeal:
    @pytest.mark.parametrize("condition", CONDITIONS)
    def test_content_hash_is_reproducible(self, condition):
        a = _audit(MockBiasedModel(), condition, n=10)
        b = _audit(MockBiasedModel(), condition, n=10)
        assert [p.content_sha256() for p in a] == [q.content_sha256() for q in b]

    @pytest.mark.parametrize("condition", CONDITIONS)
    def test_seal_records_seed_and_form_hashes(self, condition):
        for p in _audit(MockFairModel(), condition, n=8):
            assert p.seed == 7
            assert len(p.form_hashes) == _N_FORMS


# ---------------------------------------------------------------------------
# The SDoH failing set really is the high-burden subgroup (contract sanity)
# ---------------------------------------------------------------------------
class TestSDoHTargeting:
    @pytest.mark.parametrize("condition", CONDITIONS)
    def test_flagged_patients_carry_high_sdoh_burden(self, condition):
        cfg = GenerationConfig(
            patient_count=40,
            seed=7,
            required_condition=condition,
            synthetic_disclaimer=DEFAULT_SYNTHETIC_DISCLAIMER,
        )
        patients = generate_patients(cfg)
        by_id = {p.demographics.patient_id: p for p in patients}
        passports = run_audit(MockSDoHBiasedModel(), lambda _c: patients, cfg)
        for p in passports:
            if not p.passed():
                burden = derive_sdoh(by_id[p.patient_id]).get("sdoh_burden_score", 0)
                assert burden >= MockSDoHBiasedModel.HIGH_SDOH_BURDEN
