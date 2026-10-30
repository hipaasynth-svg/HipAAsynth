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

"""Tests for the polymorphic form engine and metrics."""

import pytest

from hipaasynth.core.schema import Patient
from hipaasynth.polymorphic import Form, PolymorphicFormEngine, PolymorphicMetricCalculator


@pytest.fixture
def engine() -> PolymorphicFormEngine:
    return PolymorphicFormEngine()


class TestPolymorphicForms:
    def test_all_seven_forms_returned(
        self, engine: PolymorphicFormEngine, sample_patient: Patient
    ) -> None:
        forms = engine.express_all(sample_patient)
        assert len(forms) == 7
        names = {f["form"] for f in forms}
        assert names == set(Form)

    @pytest.mark.parametrize("form", list(Form))
    def test_each_form_has_required_keys(
        self, engine: PolymorphicFormEngine, sample_patient: Patient, form: Form
    ) -> None:
        result = engine.express(sample_patient, form)
        assert "form" in result
        assert "full_text" in result
        assert result["form"] == form.value
        assert isinstance(result["full_text"], str)
        assert len(result["full_text"]) > 0

    def test_fhir_form_is_structured_json(
        self, engine: PolymorphicFormEngine, sample_patient: Patient
    ) -> None:
        result = engine.express(sample_patient, Form.FHIR_STRUCTURED)
        text = result["full_text"]
        assert '"resourceType": "Bundle"' in text
        assert sample_patient.demographics.patient_id in text

    def test_soap_form_contains_sections(
        self, engine: PolymorphicFormEngine, sample_patient: Patient
    ) -> None:
        text = engine.express(sample_patient, Form.PHYSICIAN_SOAP)["full_text"]
        assert "SUBJECTIVE:" in text
        assert "OBJECTIVE:" in text
        assert "ASSESSMENT:" in text
        assert "PLAN:" in text

    def test_lep_form_has_interpreter_note(
        self, engine: PolymorphicFormEngine, sample_patient: Patient
    ) -> None:
        text = engine.express(sample_patient, Form.LEP_TRANSLATED)["full_text"]
        assert "interpreter" in text.lower()
        assert "Limited English proficiency" in text

    def test_chw_form_has_sdoh_sections(
        self, engine: PolymorphicFormEngine, sample_patient: Patient
    ) -> None:
        text = engine.express(sample_patient, Form.CHW_SDOH_RICH)["full_text"]
        assert "SOCIAL DETERMINANTS OF HEALTH" in text
        assert "COMMUNITY HEALTH WORKER INTAKE NOTE" in text


class TestPolymorphicMetrics:
    def test_perfect_consistency_and_equity(self) -> None:
        decisions = {f.value: True for f in Form}
        calc = PolymorphicMetricCalculator()
        metrics = calc.calculate(decisions, ground_truth=True)
        assert metrics.dcs == pytest.approx(1.0)
        assert metrics.isg == pytest.approx(0.0)
        assert metrics.lfdi == pytest.approx(0.0)
        assert metrics.saf == pytest.approx(0.0)
        assert metrics.all_pass()

    def test_biased_model_fails_isg_and_dcs(self) -> None:
        decisions = {
            Form.FHIR_STRUCTURED.value: True,
            Form.PHYSICIAN_SOAP.value: True,
            Form.MIDLEVEL_ABBREVIATED.value: True,
            Form.PATIENT_HIGH_LITERACY.value: False,
            Form.PATIENT_LOW_LITERACY.value: False,
            Form.LEP_TRANSLATED.value: False,
            Form.CHW_SDOH_RICH.value: True,
        }
        calc = PolymorphicMetricCalculator()
        metrics = calc.calculate(decisions, ground_truth=True)
        assert metrics.dcs < 1.0
        assert metrics.isg > 0.0
        assert not metrics.isg_pass
        assert not metrics.dcs_pass

    def test_ground_truth_none_disables_truth_dependent_metrics(self) -> None:
        decisions = {f.value: True for f in Form}
        calc = PolymorphicMetricCalculator()
        metrics = calc.calculate(decisions, ground_truth=None)
        assert metrics.dcs == pytest.approx(1.0)
        assert metrics.isg == pytest.approx(0.0)
        assert metrics.lfdi == pytest.approx(0.0)
        assert metrics.saf == pytest.approx(0.0)
        assert metrics.isg_pass
        assert metrics.lfdi_pass
        assert metrics.saf_pass
