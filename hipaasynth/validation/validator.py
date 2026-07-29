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

"""
Validator module for Synthetic Clinical Cohort Engine.

This module provides post-generation validation to ensure patient records
meet clinical and logical constraints, such as age-appropriate conditions.
"""

from hipaasynth.core.schema import Patient, Condition, Visit


# Conditions that are not clinically appropriate for young children
# These conditions are removed if patient age < 10
AGE_RESTRICTED_CONDITIONS = {
    "hypertension",
    "type2_diabetes",
    "coronary_artery_disease",
    "chronic_kidney_disease",
}

# Minimum age for age-restricted conditions
MIN_AGE_FOR_RESTRICTED_CONDITIONS = 10


# ─────────────────────────────────────────────────────────────────────────────
# Lab-vs-diagnosis consistency (Tier 4, step 2).
#
# The engine couples certain diagnoses to certain labs in
# ``generator_numerics.CONDITION_LAB_MODIFIERS`` by drawing the lab as
# ``max(baseline, elevated_draw)``. For three of those couplings the elevated
# draw has a hard *lower bound*, so a patient carrying the diagnosis can NEVER
# have the coupled lab below that value if the record came from this engine:
#
#   * chronic_kidney_disease → Creatinine ≥ 1.05 mg/dL   (draw U(1.05, 1.25))
#   * hyperlipidemia         → LDL        ≥ 160  mg/dL   (draw U(160, 260))
#   * sepsis                 → WBC        ≥ 11   K/uL    (draw U(11, 19))
#
# A coupled lab BELOW its floor is therefore an internal contradiction — it can
# only appear in a record that was corrupted, hand-edited, or merged from an
# external source, and it would also be clinically implausible for an *untreated*
# case. This rule flags it.
#
# NOTE — type2_diabetes → Glucose is deliberately NOT in this table. The diabetic
# modifier ``max(baseline, N(164, 40))`` does not guarantee a value above the
# normal reference range on every draw (a low diabetic draw leaves the normal
# baseline in place), so there is no honest hard floor to assert for glucose. The
# *statistical* diabetes→glucose association is checked instead by
# ``hipaasynth.validation.fidelity.linked_lab_correlations``.
# ─────────────────────────────────────────────────────────────────────────────
LAB_DIAGNOSIS_FLOORS = {
    "chronic_kidney_disease": ("Creatinine", 1.05),
    "hyperlipidemia": ("LDL", 160.0),
    "sepsis": ("WBC", 11.0),
}


def _deduplicate_conditions(conditions: list[Condition]) -> list[Condition]:
    """
    Deduplicate conditions by name, keeping the earliest onset age.
    
    Args:
        conditions: List of conditions (may contain duplicates)
        
    Returns:
        Deduplicated list of conditions
    """
    condition_map: dict[str, Condition] = {}
    
    for cond in conditions:
        if cond.name not in condition_map:
            condition_map[cond.name] = cond
        else:
            # Keep the one with earlier onset age
            existing = condition_map[cond.name]
            if cond.onset_age < existing.onset_age:
                condition_map[cond.name] = cond
    
    return list(condition_map.values())


def _validate_visit_diagnoses(visits: list[Visit]) -> list[Visit]:
    """
    Ensure every visit has a non-empty primary_diagnosis.
    
    If a visit has an empty primary_diagnosis, it is replaced with "routine_check".
    
    Args:
        visits: List of visits to validate
        
    Returns:
        List of validated visits
    """
    validated = []
    for visit in visits:
        if not visit.primary_diagnosis or visit.primary_diagnosis.strip() == "":
            # Create new visit with fallback diagnosis
            validated.append(Visit(
                visit_id=visit.visit_id,
                visit_type=visit.visit_type,
                visit_date=visit.visit_date,
                primary_diagnosis="routine_check",
                labs=visit.labs,
            ))
        else:
            validated.append(visit)
    return validated


def validate_patient(patient: Patient) -> Patient:
    """
    Validate and clean a patient record.
    
    Performs the following validations:
    1. Removes age-inappropriate conditions for patients under 10
    2. Deduplicates conditions after modifications
    3. Ensures all visits have a non-empty primary_diagnosis
    
    Args:
        patient: Patient record to validate
        
    Returns:
        Validated patient record (may be modified)
    """
    age = patient.demographics.age
    conditions = patient.conditions
    visits = patient.visits
    
    # Remove age-restricted conditions for young patients
    if age < MIN_AGE_FOR_RESTRICTED_CONDITIONS:
        conditions = [
            cond for cond in conditions
            if cond.name not in AGE_RESTRICTED_CONDITIONS
        ]
    
    # Deduplicate conditions after modifications
    conditions = _deduplicate_conditions(conditions)
    
    # Validate visit diagnoses
    visits = _validate_visit_diagnoses(visits)
    
    # Return validated patient (create new instance since dataclasses are frozen)
    return Patient(
        demographics=patient.demographics,
        anthropometrics=patient.anthropometrics,
        conditions=conditions,
        visits=visits,
        engine_version=patient.engine_version,
        schema_version=patient.schema_version,
        synthetic=patient.synthetic,
        disclaimer=patient.disclaimer,
        observations=patient.observations,
    )


def validate_patients(patients: list[Patient]) -> list[Patient]:
    """
    Validate a list of patient records.
    
    Args:
        patients: List of patient records to validate
        
    Returns:
        List of validated patient records
    """
    return [validate_patient(p) for p in patients]


def validate_cohort(patients: list) -> list:
    """Validate a full cohort. Raises ValueError on first failure."""
    for patient in patients:
        validate_patient(patient)
    return patients


# ─────────────────────────────────────────────────────────────────────────────
# Clinical-plausibility checks (Tier 4, step 2).
#
# These are DETECTION functions: they return a list of findings rather than
# mutating the patient. Unlike the age-restricted rule (which drops a
# clearly-wrong condition during generation), a lab-vs-diagnosis contradiction
# has no single obvious repair — should the lab be discarded or the diagnosis? —
# so the honest, non-destructive behavior is to surface it and let the caller
# decide. They never fire on engine-generated data (the generator guarantees the
# floors); they exist to catch corrupted, hand-edited, or externally-merged
# records before they reach an exporter or an audit.
# ─────────────────────────────────────────────────────────────────────────────
def check_lab_diagnosis_consistency(patient: Patient) -> list[dict]:
    """Flag coupled labs that contradict a carried diagnosis.

    For every ``(condition, (lab, floor))`` in :data:`LAB_DIAGNOSIS_FLOORS`, if
    the patient carries ``condition`` and has any measurement of ``lab`` below
    ``floor``, a finding is recorded. Returns an empty list for a consistent
    record (including any record with no coupled diagnoses).
    """
    carried = {c.name for c in patient.conditions}
    findings: list[dict] = []
    for condition, (lab_name, floor) in LAB_DIAGNOSIS_FLOORS.items():
        if condition not in carried:
            continue
        for visit in patient.visits:
            for lab in visit.labs:
                if lab.lab_name == lab_name and lab.value < floor:
                    findings.append({
                        "patient_id": patient.demographics.patient_id,
                        "kind": "lab_below_diagnosis_floor",
                        "condition": condition,
                        "lab": lab_name,
                        "value": lab.value,
                        "floor": floor,
                        "visit_id": visit.visit_id,
                    })
    return findings


def check_medication_timeline(patient: Patient) -> list[dict]:
    """Flag medications that cannot be placed on a plausible timeline.

    **Scope note (traced, not assumed).** The core ``Medication`` schema carries
    only ``name`` and ``active`` — there is NO start/stop/onset field — and the
    anchor-rooted population pipeline attaches no medications at all, so a true
    medication *timeline* (ordering of starts/stops, overlap with a diagnosis
    window) is not modeled anywhere and cannot be validated at this layer. In the
    OMOP export, a drug exposure's date is pinned to the patient's earliest visit
    date (``drug_exposure_start_date == end_date``, a single-day exposure inside
    the observation-period span), so it is plausible *by construction*.

    The one honest, checkable medication-timing invariant that remains: a
    medication needs at least one visit to anchor that exposure date to. A
    patient carrying a medication but with **no visits** would export a
    ``drug_exposure`` row with an empty ``drug_exposure_start_date``, which
    violates OMOP CDM 5.4's NOT NULL requirement. This rule flags exactly that.
    """
    meds = list(getattr(patient, "medications", ()) or ())
    if meds and not patient.visits:
        return [{
            "patient_id": patient.demographics.patient_id,
            "kind": "medication_without_anchoring_visit",
            "medications": [m.name for m in meds],
            "detail": "medication present but no visit to anchor a drug-exposure "
                      "date; OMOP drug_exposure_start_date would be NULL",
        }]
    return []


def check_clinical_plausibility(patient: Patient) -> list[dict]:
    """Run every clinical-plausibility rule and return the combined findings."""
    return (
        check_lab_diagnosis_consistency(patient)
        + check_medication_timeline(patient)
    )


def find_clinical_plausibility_issues(patients: list[Patient]) -> list[dict]:
    """Cohort-level sweep: all clinical-plausibility findings across patients."""
    findings: list[dict] = []
    for patient in patients:
        findings.extend(check_clinical_plausibility(patient))
    return findings
