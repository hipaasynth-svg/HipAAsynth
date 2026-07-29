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

"""Clinical-plausibility rules (Tier 4, step 2).

Each rule follows the AGE_RESTRICTED_CONDITIONS pattern: a test that it *fires*
on a constructed implausible record, and a test that it does *not* false-positive
on valid engine-generated data.
"""
from hipaasynth.core.config import GenerationConfig
from hipaasynth.core.schema import (
    Anthropometrics,
    Condition,
    Demographics,
    LabResult,
    Medication,
    Patient,
    Visit,
)
from hipaasynth.pipelines.population_pipeline import generate_patients
from hipaasynth.validation.validator import (
    check_clinical_plausibility,
    check_lab_diagnosis_consistency,
    check_medication_timeline,
    find_clinical_plausibility_issues,
)


def _patient(*, conditions, labs, medications=(), visits=None, pid="P1"):
    demo = Demographics(patient_id=pid, seed=1, age=60, sex="male", ethnicity="white")
    anth = Anthropometrics(height_cm=175, weight_kg=85, bmi=27.8, bmi_category="overweight")
    if visits is None:
        visits = [Visit(visit_id="V1", visit_type="outpatient", visit_date="2024-06-01",
                        primary_diagnosis=conditions[0].name if conditions else "routine_check",
                        labs=list(labs))]
    return Patient(
        demographics=demo, anthropometrics=anth,
        conditions=list(conditions), visits=list(visits),
        engine_version="x", schema_version="y", medications=list(medications),
    )


def _lab(name, value):
    return LabResult(lab_name=name, value=value, unit="u", reference_range="r",
                     date_recorded="2024-06-01")


# ─────────────────────────────────────────────────────────────────────────────
# Lab-vs-diagnosis consistency.
# ─────────────────────────────────────────────────────────────────────────────
def test_ckd_with_low_creatinine_fires():
    # CKD patients can never have creatinine < 1.05 from the engine (draw floor).
    p = _patient(
        conditions=[Condition("chronic_kidney_disease", onset_age=55, active=True)],
        labs=[_lab("Creatinine", 0.7)],
    )
    findings = check_lab_diagnosis_consistency(p)
    assert len(findings) == 1
    assert findings[0]["condition"] == "chronic_kidney_disease"
    assert findings[0]["lab"] == "Creatinine"
    assert findings[0]["value"] == 0.7


def test_hyperlipidemia_with_low_ldl_fires():
    p = _patient(
        conditions=[Condition("hyperlipidemia", onset_age=50, active=True)],
        labs=[_lab("LDL", 90.0)],
    )
    findings = check_lab_diagnosis_consistency(p)
    assert len(findings) == 1
    assert findings[0]["lab"] == "LDL"


def test_sepsis_with_low_wbc_fires():
    p = _patient(
        conditions=[Condition("sepsis", onset_age=60, active=True)],
        labs=[_lab("WBC", 6.0)],
    )
    findings = check_lab_diagnosis_consistency(p)
    assert len(findings) == 1
    assert findings[0]["lab"] == "WBC"


def test_diabetes_low_glucose_does_not_fire():
    # Diabetes is deliberately excluded: the engine does not guarantee elevated
    # glucose on every draw, so a normal glucose is not a contradiction.
    p = _patient(
        conditions=[Condition("type2_diabetes", onset_age=50, active=True)],
        labs=[_lab("Glucose", 88.0)],
    )
    assert check_lab_diagnosis_consistency(p) == []


def test_ckd_with_normal_creatinine_does_not_fire():
    # At/above the floor is consistent — no false positive.
    p = _patient(
        conditions=[Condition("chronic_kidney_disease", onset_age=55, active=True)],
        labs=[_lab("Creatinine", 1.20)],
    )
    assert check_lab_diagnosis_consistency(p) == []


def test_lab_floor_only_applies_when_condition_is_carried():
    # A low creatinine with NO CKD diagnosis is perfectly fine.
    p = _patient(
        conditions=[Condition("hypertension", onset_age=55, active=True)],
        labs=[_lab("Creatinine", 0.7)],
    )
    assert check_lab_diagnosis_consistency(p) == []


def test_generated_cohort_has_no_lab_diagnosis_contradictions():
    # The engine guarantees the floors, so a real cohort must be clean.
    cfg = GenerationConfig(patient_count=200, seed=11, age_min=40, age_max=90,
                           include_visits=True, include_labs=True,
                           visits_min=1, visits_max=3)
    patients = generate_patients(cfg)
    all_findings = []
    for p in patients:
        all_findings.extend(check_lab_diagnosis_consistency(p))
    assert all_findings == []


def test_generated_sepsis_cohort_has_no_contradictions():
    cfg = GenerationConfig(patient_count=60, seed=5, required_condition="sepsis",
                           include_visits=True, include_labs=True,
                           visits_min=1, visits_max=2)
    patients = generate_patients(cfg)
    assert find_clinical_plausibility_issues(patients) == []


# ─────────────────────────────────────────────────────────────────────────────
# Medication timeline / anchoring.
# ─────────────────────────────────────────────────────────────────────────────
def test_medication_without_any_visit_fires():
    p = _patient(
        conditions=[Condition("hypertension", onset_age=55, active=True)],
        labs=[],
        medications=[Medication(name="lisinopril", active=True)],
        visits=[],  # no visit to anchor a drug-exposure date
    )
    findings = check_medication_timeline(p)
    assert len(findings) == 1
    assert findings[0]["kind"] == "medication_without_anchoring_visit"
    assert "lisinopril" in findings[0]["medications"]


def test_medication_with_a_visit_does_not_fire():
    p = _patient(
        conditions=[Condition("hypertension", onset_age=55, active=True)],
        labs=[_lab("Glucose", 95.0)],
        medications=[Medication(name="lisinopril", active=True)],
    )
    assert check_medication_timeline(p) == []


def test_no_medications_does_not_fire():
    # Core-pipeline patients carry no medications; the rule must be a no-op.
    p = _patient(
        conditions=[Condition("hypertension", onset_age=55, active=True)],
        labs=[],
        visits=[],
    )
    assert check_medication_timeline(p) == []


def test_check_clinical_plausibility_combines_rules():
    p = _patient(
        conditions=[Condition("chronic_kidney_disease", onset_age=55, active=True)],
        labs=[_lab("Creatinine", 0.6)],
        medications=[Medication(name="furosemide", active=True)],
        visits=[Visit(visit_id="V1", visit_type="outpatient", visit_date="2024-06-01",
                      primary_diagnosis="chronic_kidney_disease",
                      labs=[_lab("Creatinine", 0.6)])],
    )
    findings = check_clinical_plausibility(p)
    kinds = {f["kind"] for f in findings}
    assert "lab_below_diagnosis_floor" in kinds
    # A visit exists, so no medication-anchoring finding.
    assert "medication_without_anchoring_visit" not in kinds
