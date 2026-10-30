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

"""Tests for the DIF audit framework and mock models."""

from hipaasynth.core.config import GenerationConfig
from hipaasynth.dif import run_audit
from hipaasynth.dif.model_interface import MockBiasedModel, MockFairModel
from hipaasynth.pipelines.population_pipeline import generate_patients
from hipaasynth.polymorphic.forms import Form


class TestDIFAudit:
    def test_run_audit_returns_one_passport_per_patient(
        self, gen_config: GenerationConfig, fair_model: MockFairModel, dif_config
    ) -> None:
        passports = run_audit(fair_model, generate_patients, gen_config, dif_config)
        assert len(passports) == gen_config.patient_count
        for passport in passports:
            assert passport.device_name == dif_config.device_name
            assert passport.device_version == dif_config.device_version
            assert len(passport.decisions) == 7

    def test_fair_model_passes_all_patients(
        self, gen_config: GenerationConfig, fair_model: MockFairModel, dif_config
    ) -> None:
        passports = run_audit(fair_model, generate_patients, gen_config, dif_config)
        for passport in passports:
            assert passport.passed()
            assert passport.metrics.dcs == 1.0

    def test_biased_model_fails_on_acute_positive_patients(
        self,
    ) -> None:
        # Generate patients with a high likelihood of acute positive ground truth.
        gen_config = GenerationConfig(
            patient_count=5,
            seed=42,
            age_min=18,
            age_max=90,
            required_condition="stroke",
            sex_ratio_female=0.5,
            ethnicity_weights=None,
            include_visits=True,
            include_labs=True,
            visits_min=1,
            visits_max=2,
            synthetic_disclaimer="synthetic",
            run_date="2026-06-24",
        )
        from hipaasynth.dif import DIFConfig

        dif_config = DIFConfig(device_name="BiasedTest", device_version="0.1.0")
        passports = run_audit(MockBiasedModel(), generate_patients, gen_config, dif_config)
        acute_positive_passports = [p for p in passports if p.ground_truth]
        assert len(acute_positive_passports) > 0
        for passport in acute_positive_passports:
            assert not passport.passed()
            # Under-triage should make at least some patient/LEP decisions wrong.
            assert any(
                [
                    passport.decisions[Form.PATIENT_HIGH_LITERACY.value] != passport.ground_truth,
                    passport.decisions[Form.PATIENT_LOW_LITERACY.value] != passport.ground_truth,
                    passport.decisions[Form.LEP_TRANSLATED.value] != passport.ground_truth,
                ]
            )

    def test_passport_markdown_contains_required_sections(self, dif_config) -> None:
        from hipaasynth.core.config import DEFAULT_SYNTHETIC_DISCLAIMER, GenerationConfig
        from hipaasynth.dif import run_audit

        gen_config = GenerationConfig(
            patient_count=1,
            seed=123,
            age_min=18,
            age_max=90,
            required_condition="stroke",
            sex_ratio_female=0.5,
            ethnicity_weights=None,
            include_visits=True,
            include_labs=True,
            visits_min=1,
            visits_max=2,
            synthetic_disclaimer=DEFAULT_SYNTHETIC_DISCLAIMER,
            run_date="2026-06-24",
        )
        passports = run_audit(MockFairModel(), generate_patients, gen_config, dif_config)
        md = passports[0].to_markdown()
        assert "# HipAAsynth Fairness Passport" in md
        assert "## FDA TPLC Compliance Mapping" in md
        assert "## EU AI Act Compliance Mapping" in md
        assert "## Remediation Recommendations" in md
