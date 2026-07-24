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

"""Polymorphic-fidelity tests (audit findings F1-F6).

Guards the properties that make the polymorphic subsystem a credible fairness
stress-test:

  F1 — fact invariance: every form encodes the same clinical facts in
       ``same_facts`` mode; missingness is measured, not silent, in
       ``realistic_missingness`` mode.
  F2 — verifiability: forms are versioned + content-hashed, the passport is
       hash-sealed and byte-identical across runs, and ``verify()`` re-renders
       to confirm (and detect tampering).
  F3 — patient-specific SDoH gives the SAF metric a real, demonstrable signal.
  F4 — cohort aggregation summarizes fairness across many passports.
  F5 — truth-free runs report NOT EVALUATED, never a silent PASS.
  F6 — LEP register shift.
"""


import pytest

from hipaasynth.core.config import GenerationConfig
from hipaasynth.dif import DIFConfig, run_audit, summarize_cohort
from hipaasynth.dif.model_interface import (
    MockBiasedModel,
    MockFairModel,
    MockSDoHBiasedModel,
)
from hipaasynth.pipelines.population_pipeline import generate_patients
from hipaasynth.polymorphic.facts import extract_fact_set, fact_coverage, structured_fact_coverage
from hipaasynth.polymorphic.forms import (
    FORM_ENGINE_VERSION,
    INFO_MODE_REALISTIC_MISSINGNESS,
    INFO_MODE_SAME_FACTS,
    Form,
    PolymorphicFormEngine,
)
from hipaasynth.polymorphic.metrics import PolymorphicMetricCalculator
from hipaasynth.polymorphic.sdoh import derive_sdoh

SEED = 4242
RUN_DATE = "2026-07-24"


def _cfg(condition, n=40, seed=SEED):
    return GenerationConfig(
        patient_count=n,
        seed=seed,
        required_condition=condition,
        include_visits=True,
        include_labs=True,
        visits_min=1,
        visits_max=2,
        run_date=RUN_DATE,
    )


# ─────────────────────────────────────────────────────────────────────────────
# F1 — fact invariance + measured missingness
# ─────────────────────────────────────────────────────────────────────────────
class TestFactInvariance:
    @pytest.mark.parametrize("condition", ["stroke", "sepsis", None])
    def test_same_facts_mode_every_form_encodes_every_fact(self, condition):
        patients = generate_patients(_cfg(condition, n=25))
        engine = PolymorphicFormEngine(information_mode=INFO_MODE_SAME_FACTS)
        for patient in patients:
            facts = extract_fact_set(patient)
            for rendered in engine.express_all(patient):
                assert rendered["omitted_fact_categories"] == [], (
                    f"{rendered['form']} dropped facts in same_facts mode: "
                    f"{rendered['omitted_fact_categories']}"
                )
                # Cross-check the coverage directly (narrative vs structured).
                if rendered["form"] == Form.FHIR_STRUCTURED.value:
                    cov = structured_fact_coverage(rendered["full_text"], facts)
                else:
                    cov = fact_coverage(rendered["full_text"], facts)
                assert cov["conditions"]["covered"]
                assert cov["labs"]["covered"]

    def test_realistic_missingness_is_measured_not_silent(self):
        patients = generate_patients(_cfg("stroke", n=10))
        engine = PolymorphicFormEngine(information_mode=INFO_MODE_REALISTIC_MISSINGNESS)
        for patient in patients:
            omissions = {
                r["form"]: r["omitted_fact_categories"] for r in engine.express_all(patient)
            }
            # Patient/LEP/CHW forms omit labs; the omission is recorded.
            assert "labs" in omissions[Form.PATIENT_LOW_LITERACY.value]
            assert "labs" in omissions[Form.LEP_TRANSLATED.value]
            assert "labs" in omissions[Form.CHW_SDOH_RICH.value]
            # Clinician forms never omit facts.
            assert omissions[Form.PHYSICIAN_SOAP.value] == []
            assert omissions[Form.MIDLEVEL_ABBREVIATED.value] == []
            # Conditions (always-present) are never dropped, even here.
            for form_name, omitted in omissions.items():
                assert "conditions" not in omitted, f"{form_name} dropped conditions"

    def test_invalid_information_mode_rejected(self):
        with pytest.raises(ValueError):
            PolymorphicFormEngine(information_mode="nonsense")


# ─────────────────────────────────────────────────────────────────────────────
# F2 — versioning, hashing, sealed + verifiable passport
# ─────────────────────────────────────────────────────────────────────────────
class TestVerifiability:
    def test_forms_are_versioned_and_hashed(self):
        patient = generate_patients(_cfg("stroke", n=1))[0]
        for rendered in PolymorphicFormEngine().express_all(patient):
            assert rendered["form_engine_version"] == FORM_ENGINE_VERSION
            assert len(rendered["content_sha256"]) == 64  # sha256 hex

    def test_form_hash_changes_when_text_changes(self):
        patients = generate_patients(_cfg("stroke", n=2))
        h0 = PolymorphicFormEngine().express(patients[0], Form.PHYSICIAN_SOAP)
        h1 = PolymorphicFormEngine().express(patients[1], Form.PHYSICIAN_SOAP)
        assert h0["content_sha256"] != h1["content_sha256"]

    def test_passport_seal_is_byte_identical_across_runs(self):
        cfg, dif = _cfg("stroke"), DIFConfig(device_name="D", device_version="1.0.0")
        a = run_audit(MockBiasedModel(), generate_patients, cfg, dif)
        b = run_audit(MockBiasedModel(), generate_patients, cfg, dif)
        assert [p.content_sha256() for p in a] == [p.content_sha256() for p in b]
        # Markdown is deterministic too (no wall-clock test_date).
        assert a[0].to_markdown() == b[0].to_markdown()

    def test_passport_seal_records_provenance(self):
        cfg, dif = _cfg("stroke", n=3), DIFConfig(device_name="D", device_version="1.0.0")
        passports = run_audit(MockFairModel(), generate_patients, cfg, dif)
        p = passports[0]
        assert p.seed == SEED
        assert p.run_date == RUN_DATE
        assert p.anchor_hash and len(p.anchor_hash) == 64
        assert p.form_engine_version == FORM_ENGINE_VERSION
        assert set(p.form_hashes) == {f.value for f in Form}

    def test_verify_matches_and_detects_tampering(self):
        cfg, dif = _cfg("stroke", n=5), DIFConfig(device_name="D", device_version="1.0.0")
        passports = run_audit(MockFairModel(), generate_patients, cfg, dif)
        patients = {p.demographics.patient_id: p for p in generate_patients(cfg)}
        p = passports[0]
        patient = patients[p.patient_id]
        assert p.verify(patient) is True
        # Tamper with one sealed hash -> verification fails.
        p.form_hashes[Form.PHYSICIAN_SOAP.value] = "0" * 64
        assert p.verify(patient) is False


# ─────────────────────────────────────────────────────────────────────────────
# F3 — patient-specific SDoH powers the SAF metric
# ─────────────────────────────────────────────────────────────────────────────
class TestSDoH:
    def test_sdoh_is_deterministic_per_patient(self):
        patient = generate_patients(_cfg("stroke", n=1))[0]
        assert derive_sdoh(patient) == derive_sdoh(patient)

    def test_sdoh_varies_across_patients(self):
        patients = generate_patients(_cfg("stroke", n=60))
        burdens = {derive_sdoh(p)["sdoh_burden_score"] for p in patients}
        assert len(burdens) > 1, "SDoH burden should vary across patients"

    def test_locale_profile_raises_sdoh_burden(self):
        patients = generate_patients(_cfg("stroke", n=120))
        base = [derive_sdoh(p)["sdoh_burden_score"] for p in patients]
        high_locale = {
            "sdoh_adverse_rates": {
                "housing_insecure": 0.9,
                "transport_barrier": 0.9,
                "food_insecure": 0.9,
                "uninsured": 0.9,
            }
        }
        raised = [derive_sdoh(p, high_locale)["sdoh_burden_score"] for p in patients]
        assert sum(raised) > sum(base)

    def test_saf_signal_demonstrable_only_with_sdoh_bias(self):
        cfg, dif = _cfg("stroke", n=60), DIFConfig(device_name="D", device_version="1.0.0")
        fair = summarize_cohort(run_audit(MockFairModel(), generate_patients, cfg, dif))
        biased = summarize_cohort(run_audit(MockSDoHBiasedModel(), generate_patients, cfg, dif))
        assert fair.saf_mean == pytest.approx(0.0)
        assert biased.saf_mean > 0.0
        assert biased.worst_form == Form.CHW_SDOH_RICH.value


# ─────────────────────────────────────────────────────────────────────────────
# F4 — cohort aggregation
# ─────────────────────────────────────────────────────────────────────────────
class TestCohortAggregation:
    def test_summary_reports_expected_fields(self):
        cfg, dif = _cfg("stroke", n=30), DIFConfig(device_name="Dev", device_version="9.9")
        summary = summarize_cohort(run_audit(MockBiasedModel(), generate_patients, cfg, dif))
        assert summary.n == 30
        assert summary.device_name == "Dev"
        assert 0.0 <= summary.overall_pass_rate <= 1.0
        assert summary.worst_form in {f.value for f in Form}
        assert "Cohort Fairness Summary" in summary.to_markdown()

    def test_biased_cohort_worst_form_is_a_disadvantaged_form(self):
        cfg, dif = _cfg("stroke", n=40), DIFConfig(device_name="D", device_version="1.0.0")
        summary = summarize_cohort(run_audit(MockBiasedModel(), generate_patients, cfg, dif))
        # MockBiasedModel under-triages patient/LEP forms.
        assert summary.worst_form in {
            Form.PATIENT_HIGH_LITERACY.value,
            Form.PATIENT_LOW_LITERACY.value,
            Form.LEP_TRANSLATED.value,
        }

    def test_empty_cohort_rejected(self):
        with pytest.raises(ValueError):
            summarize_cohort([])


# ─────────────────────────────────────────────────────────────────────────────
# F5 — not-evaluated vs silent pass
# ─────────────────────────────────────────────────────────────────────────────
class TestNotEvaluated:
    def test_truth_free_metrics_are_flagged_not_evaluated(self):
        decisions = {f.value: True for f in Form}
        m = PolymorphicMetricCalculator().calculate(decisions, ground_truth=None)
        assert m.truth_evaluated is False
        # Back-compat: the pass flags remain True (metric value is 0).
        assert m.isg_pass and m.lfdi_pass and m.saf_pass

    def test_passport_markdown_shows_not_evaluated(self):
        from hipaasynth.dif.report import FairnessPassport

        decisions = {f.value: True for f in Form}
        m = PolymorphicMetricCalculator().calculate(decisions, ground_truth=None)
        md = FairnessPassport.build(
            device_name="d",
            device_version="v",
            patient_id="SYN-TEST-0001",
            ground_truth=False,
            decisions=decisions,
            metrics=m,
        ).to_markdown()
        assert "NOT EVALUATED" in md

    def test_truth_present_still_evaluates(self):
        decisions = {f.value: True for f in Form}
        m = PolymorphicMetricCalculator().calculate(decisions, ground_truth=True)
        assert m.truth_evaluated is True


# ─────────────────────────────────────────────────────────────────────────────
# F6 — LEP register shift
# ─────────────────────────────────────────────────────────────────────────────
class TestLEPRegister:
    def test_lep_form_keeps_interpreter_marker(self):
        patient = generate_patients(_cfg("stroke", n=1))[0]
        text = PolymorphicFormEngine().express(patient, Form.LEP_TRANSLATED)["full_text"]
        assert "Limited English proficiency" in text
        assert "interpreter" in text.lower()

    def test_lep_form_uses_short_sentences(self):
        patient = generate_patients(_cfg("stroke", n=1))[0]
        text = PolymorphicFormEngine().express(patient, Form.LEP_TRANSLATED)["full_text"]
        sentences = [s for s in text.split(".") if s.strip()]
        avg_words = sum(len(s.split()) for s in sentences) / len(sentences)
        # Register shift: interpreter-relayed intake reads in short clauses.
        assert avg_words < 12, f"LEP sentences too long (avg {avg_words:.1f} words)"
