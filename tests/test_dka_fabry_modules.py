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

"""Tests for the DKA (diabetes) and Fabry-referral observation modules and
their integration into the pipeline, ground-truth, and polymorphic forms."""

from hipaasynth.core.config import DEFAULT_SYNTHETIC_DISCLAIMER, GenerationConfig
from hipaasynth.dif import DIFConfig, run_audit
from hipaasynth.dif.model_interface import (
    MockBiasedModel,
    MockFairModel,
    _ground_truth,
)
from hipaasynth.pipelines.population_pipeline import (
    generate_patients,
    stream_patients,
)
from hipaasynth.polymorphic.forms import Form, PolymorphicFormEngine


def _cohort(condition, n=60, seed=42):
    cfg = GenerationConfig(
        patient_count=n,
        seed=seed,
        required_condition=condition,
        synthetic_disclaimer=DEFAULT_SYNTHETIC_DISCLAIMER,
    )
    return list(stream_patients(cfg))


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------
class TestRouting:
    def test_dka_routing_sets_flag(self) -> None:
        for p in _cohort("dka", n=10):
            assert "dka_flag" in p.observations
            assert "dka_observation_version" in p.observations
            assert "stroke_flag" not in p.observations
            assert "sepsis_flag" not in p.observations

    def test_fabry_routing_sets_flag(self) -> None:
        for p in _cohort("fabry", n=10):
            assert "fabry_referral_flag" in p.observations
            assert "fabry_observation_version" in p.observations

    def test_existing_conditions_unaffected(self) -> None:
        assert "stroke_flag" in _cohort("stroke", n=5)[0].observations
        # Default (no required_condition) still routes to sepsis.
        assert "sepsis_flag" in _cohort(None, n=5)[0].observations


# ---------------------------------------------------------------------------
# Ground truth
# ---------------------------------------------------------------------------
class TestGroundTruth:
    def test_dka_ground_truth_matches_flag(self) -> None:
        for p in _cohort("dka"):
            assert _ground_truth(p) == bool(p.observations["dka_flag"])

    def test_fabry_ground_truth_matches_flag(self) -> None:
        for p in _cohort("fabry"):
            assert _ground_truth(p) == bool(p.observations["fabry_referral_flag"])

    def test_cohorts_carry_both_decision_classes(self) -> None:
        # A useful audit needs both positive and negative ground-truth cases.
        for cond in ("dka", "fabry"):
            gts = {_ground_truth(p) for p in _cohort(cond)}
            assert gts == {True, False}, f"{cond} should yield both classes"


# ---------------------------------------------------------------------------
# Clinical coherence of the ground-truth rule
# ---------------------------------------------------------------------------
class TestDKACriteria:
    def test_positive_cases_meet_ada_acidosis_criteria(self) -> None:
        for p in _cohort("dka"):
            o = p.observations
            if o["dka_flag"]:
                assert o["arterial_ph"] < 7.30
                assert o["bicarbonate_meq_l"] < 18.0
                assert o["anion_gap"] >= 16
                assert o["dka_severity"] in {"mild", "moderate", "severe"}

    def test_negative_cases_are_non_acidotic(self) -> None:
        for p in _cohort("dka"):
            o = p.observations
            if not o["dka_flag"]:
                assert o["arterial_ph"] >= 7.30
                assert o["bicarbonate_meq_l"] >= 18.0
                assert o["dka_severity"] is None


class TestFabryRule:
    def test_referral_rule_is_consistent_with_fields(self) -> None:
        for p in _cohort("fabry"):
            o = p.observations
            organ = o["proteinuria"] or o["left_ventricular_hypertrophy"] or o[
                "cryptogenic_stroke_young"
            ]
            pathognomonic = o["cornea_verticillata"] or o["angiokeratoma"]
            expected = (
                o["red_flag_count"] >= 2
                or pathognomonic
                or (o["family_history_fabry"] and organ)
            )
            assert o["fabry_referral_flag"] == bool(expected)

    def test_referral_reason_only_when_referred(self) -> None:
        for p in _cohort("fabry"):
            o = p.observations
            if o["fabry_referral_flag"]:
                assert o["referral_reason"] is not None
            else:
                assert o["referral_reason"] is None


# ---------------------------------------------------------------------------
# Determinism (byte-identical observations for a fixed seed)
# ---------------------------------------------------------------------------
class TestDeterminism:
    def test_dka_deterministic(self) -> None:
        a = [p.observations for p in _cohort("dka")]
        b = [p.observations for p in _cohort("dka")]
        assert a == b

    def test_fabry_deterministic(self) -> None:
        a = [p.observations for p in _cohort("fabry")]
        b = [p.observations for p in _cohort("fabry")]
        assert a == b


# ---------------------------------------------------------------------------
# Polymorphic rendering — the whole point: all seven forms express the finding
# ---------------------------------------------------------------------------
class TestPolymorphicRendering:
    def test_all_forms_render_for_new_conditions(self) -> None:
        engine = PolymorphicFormEngine()
        for cond in ("dka", "fabry"):
            for p in _cohort(cond, n=6):
                rendered = engine.express_all(p)
                assert len(rendered) == 7

    def test_clinician_acuity_line_mentions_condition(self) -> None:
        engine = PolymorphicFormEngine()
        for p in _cohort("dka", n=8):
            soap = engine.express(p, Form.PHYSICIAN_SOAP)["full_text"]
            assert "DKA" in soap
        for p in _cohort("fabry", n=8):
            soap = engine.express(p, Form.PHYSICIAN_SOAP)["full_text"]
            assert "Fabry" in soap


# ---------------------------------------------------------------------------
# DIF audit end to end
# ---------------------------------------------------------------------------
class TestDIFAudit:
    def _audit(self, model, cond, n=12, seed=7):
        cfg = GenerationConfig(
            patient_count=n,
            seed=seed,
            required_condition=cond,
            synthetic_disclaimer=DEFAULT_SYNTHETIC_DISCLAIMER,
        )
        return run_audit(model, generate_patients, cfg, DIFConfig(
            device_name="Test", device_version="1.0.0"))

    def test_fair_model_passes_new_conditions(self) -> None:
        for cond in ("dka", "fabry"):
            passports = self._audit(MockFairModel(), cond)
            assert len(passports) == 12
            assert all(p.passed() for p in passports)

    def test_biased_model_produces_passports(self) -> None:
        for cond in ("dka", "fabry"):
            passports = self._audit(MockBiasedModel(), cond)
            assert len(passports) == 12
            for p in passports:
                assert len(p.decisions) == 7
