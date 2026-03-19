# Copyright (c) 2026 Cody Carlson
# Licensed under the Apache License, Version 2.0

"""
Exporters module for Synthetic Clinical Cohort Engine.

This module provides functions for exporting patient data to various formats
and generating summary statistics about the cohort.

---------------------------------------------------------------------------
VERIFICATION RECORD
---------------------------------------------------------------------------
FHIR target:     R5 (validator.fhir.org v6.8.0)
Validation date: 2026-03-14
Result:          0 errors, warnings only (best-practice recommendations)

Warnings present (intentionally not addressed):
  - dom-6: resources should have narrative
    Reason: optional for machine-to-machine synthetic data use cases.
  - Observations should have a performer
    Reason: no ordering provider exists in synthetic data context.

Determinism guarantee:
  All FHIR resource IDs derived via uuid.uuid5() from stable keys.
  Same Patient input always produces byte-identical FHIR output.
  Verified by: md5sum hash comparison across independent runs.

Engine property preserved:
  No datetime.now() calls in the FHIR export path.
  Birth years anchored to _BIRTH_YEAR_REF = 2024.
  No external data sources or random calls in _patient_to_fhir().
---------------------------------------------------------------------------
"""

import csv
import json
import uuid
from collections import Counter
from datetime import datetime
from typing import Any

from core.schema import Patient


# ---------------------------------------------------------------------------
# Deterministic UUID generation
# ---------------------------------------------------------------------------
# uuid.uuid5() derives a stable UUID from a namespace + key string.
# Same input always produces the same UUID — preserving the engine's
# deterministic property across all FHIR exports.

_NS = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")


def _duuid(key: str) -> str:
    return str(uuid.uuid5(_NS, key))


# ---------------------------------------------------------------------------
# CSV / JSON exports (unchanged from original)
# ---------------------------------------------------------------------------

def export_csv_stream(patient_iter, filepath):
    """
    Stream patients directly to CSV without storing them all in memory.
    """
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = None

        for patient in patient_iter:
            row = {
                "patient_id": patient.demographics.patient_id,
                "age": patient.demographics.age,
                "sex": patient.demographics.sex,
                "ethnicity": patient.demographics.ethnicity,
                "height_cm": patient.anthropometrics.height_cm,
                "weight_kg": patient.anthropometrics.weight_kg,
                "bmi": patient.anthropometrics.bmi,
                "bmi_category": patient.anthropometrics.bmi_category,
                "conditions": ";".join([c.name for c in patient.conditions]),
            }

            if writer is None:
                writer = csv.DictWriter(f, fieldnames=row.keys())
                writer.writeheader()

            writer.writerow(row)


def export_json(patients: list[Patient], filename: str = "output.json") -> None:
    """
    Export patient records to a JSON file.
    """
    data = [p.to_dict() for p in patients]
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def export_csv(patients: list[Patient], filename: str = "output.csv") -> None:
    """
    Export patient records to a flattened CSV file.
    """
    fieldnames = [
        "patient_id", "seed", "age", "sex", "ethnicity",
        "height_cm", "weight_kg", "bmi", "bmi_category",
        "conditions", "num_visits", "num_labs",
        "engine_version", "schema_version", "synthetic", "disclaimer",
    ]

    with open(filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for p in patients:
            writer.writerow({
                "patient_id": p.demographics.patient_id,
                "seed": p.demographics.seed,
                "age": p.demographics.age,
                "sex": p.demographics.sex,
                "ethnicity": p.demographics.ethnicity,
                "height_cm": p.anthropometrics.height_cm,
                "weight_kg": p.anthropometrics.weight_kg,
                "bmi": p.anthropometrics.bmi,
                "bmi_category": p.anthropometrics.bmi_category,
                "conditions": ";".join(c.name for c in p.conditions),
                "num_visits": len(p.visits),
                "num_labs": sum(len(v.labs) for v in p.visits),
                "engine_version": p.engine_version,
                "schema_version": p.schema_version,
                "synthetic": p.synthetic,
                "disclaimer": p.disclaimer,
            })


# ---------------------------------------------------------------------------
# Summary statistics (unchanged from original)
# ---------------------------------------------------------------------------

def summary_stats(patients: list[Patient]) -> dict[str, Any]:
    """
    Calculate summary statistics for a cohort of patients.
    """
    if not patients:
        return {
            "count": 0,
            "age_min": None, "age_max": None, "age_mean": None,
            "height_mean_cm": None, "weight_mean_kg": None, "bmi_mean": None,
            "sex_counts": {}, "ethnicity_counts": {},
            "bmi_category_counts": {}, "condition_counts": {},
        }

    count = len(patients)
    ages = [p.demographics.age for p in patients]
    heights = [p.anthropometrics.height_cm for p in patients]
    weights = [p.anthropometrics.weight_kg for p in patients]
    bmis = [p.anthropometrics.bmi for p in patients]

    condition_counts: Counter = Counter()
    for patient in patients:
        for condition in patient.conditions:
            condition_counts[condition.name] += 1

    return {
        "count": count,
        "age_min": min(ages),
        "age_max": max(ages),
        "age_mean": round(sum(ages) / count, 2),
        "height_mean_cm": round(sum(heights) / count, 2),
        "weight_mean_kg": round(sum(weights) / count, 2),
        "bmi_mean": round(sum(bmis) / count, 2),
        "sex_counts": dict(Counter(p.demographics.sex for p in patients)),
        "ethnicity_counts": dict(Counter(p.demographics.ethnicity for p in patients)),
        "bmi_category_counts": dict(Counter(p.anthropometrics.bmi_category for p in patients)),
        "condition_counts": dict(condition_counts),
    }


def profile_fit_stats(patients: list[Patient], cfg) -> dict[str, Any] | None:
    """
    Compare observed cohort demographics to the requested population profile.
    """
    if not patients or not cfg.profile_name:
        return None

    total = len(patients)
    observed_female = sum(1 for p in patients if p.demographics.sex == "female") / total

    observed_ethnicity_counts = Counter(p.demographics.ethnicity for p in patients)
    observed_ethnicity = {
        key: observed_ethnicity_counts.get(key, 0) / total
        for key in (cfg.ethnicity_weights or {}).keys()
    }

    observed_age_bands = []
    if cfg.age_band_weights is not None:
        for lo, hi, weight in cfg.age_band_weights:
            count = sum(1 for p in patients if lo <= p.demographics.age <= hi)
            observed_age_bands.append({
                "min": lo, "max": hi,
                "target_weight": weight,
                "observed_weight": count / total,
            })

    actual_population = None
    if cfg.population_profile_path:
        import json as _json
        with open(cfg.population_profile_path, "r", encoding="utf-8") as _f:
            actual_population = _json.load(_f).get("actual_population")

    max_abs_error_pts = abs(observed_female - cfg.sex_ratio_female) * 100
    for category, target_weight in (cfg.ethnicity_weights or {}).items():
        err = abs(observed_ethnicity.get(category, 0.0) - target_weight) * 100
        if err > max_abs_error_pts:
            max_abs_error_pts = err
    for band in observed_age_bands:
        err = abs(band["observed_weight"] - band["target_weight"]) * 100
        if err > max_abs_error_pts:
            max_abs_error_pts = err

    return {
        "profile_name": cfg.profile_name,
        "target_female_ratio": cfg.sex_ratio_female,
        "observed_female_ratio": observed_female,
        "ethnicity_fit": [
            {
                "category": category,
                "target_weight": target_weight,
                "observed_weight": observed_ethnicity.get(category, 0.0),
            }
            for category, target_weight in (cfg.ethnicity_weights or {}).items()
        ],
        "age_band_fit": observed_age_bands,
        "max_abs_error_pts": round(max_abs_error_pts, 1),
        "actual_population": actual_population,
        "generated_count": total,
    }


def print_summary(stats: dict[str, Any]) -> None:
    """Print summary statistics in a readable format."""
    print("=" * 50)
    print("SYNTHETIC COHORT SUMMARY")
    print("=" * 50)
    print(f"Total Patients: {stats['count']}")
    print()
    print("Age Statistics:")
    print(f"  Min: {stats['age_min']}")
    print(f"  Max: {stats['age_max']}")
    print(f"  Mean: {stats['age_mean']}")
    print()
    print("Anthropometric Statistics:")
    print(f"  Mean Height (cm): {stats['height_mean_cm']}")
    print(f"  Mean Weight (kg): {stats['weight_mean_kg']}")
    print(f"  Mean BMI: {stats['bmi_mean']}")
    print()
    print("Sex Distribution:")
    for sex, count in sorted(stats["sex_counts"].items()):
        pct = (count / stats["count"]) * 100 if stats["count"] > 0 else 0
        print(f"  {sex}: {count} ({pct:.1f}%)")
    print()
    print("Ethnicity Distribution:")
    for ethnicity, count in sorted(stats["ethnicity_counts"].items()):
        pct = (count / stats["count"]) * 100 if stats["count"] > 0 else 0
        print(f"  {ethnicity}: {count} ({pct:.1f}%)")
    print()
    print("BMI Category Distribution:")
    if stats["bmi_category_counts"]:
        for category, count in sorted(stats["bmi_category_counts"].items()):
            pct = (count / stats["count"]) * 100 if stats["count"] > 0 else 0
            print(f"  {category}: {count} ({pct:.1f}%)")
    else:
        print("  No anthropometric data recorded")
    print()
    print("Condition Prevalence:")
    if stats["condition_counts"]:
        for condition, count in sorted(stats["condition_counts"].items()):
            pct = (count / stats["count"]) * 100 if stats["count"] > 0 else 0
            print(f"  {condition}: {count} ({pct:.1f}%)")
    else:
        print("  No conditions recorded")
    print("=" * 50)


def print_profile_fit(profile_stats: dict[str, Any] | None) -> None:
    """Print demographic fit against the requested population profile."""
    if profile_stats is None:
        return

    print("=" * 50)
    print(f"POPULATION PROFILE FIT: {profile_stats['profile_name']}")
    print("=" * 50)

    actual_pop = profile_stats.get("actual_population")
    generated = profile_stats.get("generated_count", 0)
    if actual_pop:
        print(f"Actual population target: {actual_pop:,}")
    print(f"Generated cohort size: {generated:,}")
    if actual_pop and generated < actual_pop:
        print("Sampling mode: synthetic sample of city profile")
    elif actual_pop and generated >= actual_pop:
        print("Sampling mode: full-city synthetic twin")
    print()

    target_female = profile_stats["target_female_ratio"] * 100
    observed_female = profile_stats["observed_female_ratio"] * 100
    print("Sex Fit:")
    print(
        f"  female: target {target_female:.1f}% | "
        f"observed {observed_female:.1f}% | "
        f"error {observed_female - target_female:+.1f} pts"
    )
    print()
    print("Ethnicity Fit:")
    for row in profile_stats["ethnicity_fit"]:
        target = row["target_weight"] * 100
        observed = row["observed_weight"] * 100
        print(
            f"  {row['category']}: target {target:.1f}% | "
            f"observed {observed:.1f}% | "
            f"error {observed - target:+.1f} pts"
        )
    print()
    print("Age Band Fit:")
    for row in profile_stats["age_band_fit"]:
        target = row["target_weight"] * 100
        observed = row["observed_weight"] * 100
        print(
            f"  {row['min']}-{row['max']}: target {target:.1f}% | "
            f"observed {observed:.1f}% | "
            f"error {observed - target:+.1f} pts"
        )
    print()
    print(f"Max absolute demographic fit error: {profile_stats['max_abs_error_pts']} pts")
    print("=" * 50)


# ---------------------------------------------------------------------------
# FHIR R5 export
# ---------------------------------------------------------------------------
# validator.fhir.org defaults to FHIR R5. Key R4→R5 field renames:
#   Encounter.period        → Encounter.actualPeriod
#   Encounter.reasonCode    → Encounter.reason (with value.concept wrapper)
#   Encounter.status 'finished' → 'completed'
#   Encounter.class Coding  → CodeableConcept (array of codings)
# All resources target R5 so the bundle passes validator.fhir.org cleanly.

# Fixed reference year — birth dates are stable across runs.
# Increment intentionally only; changing this shifts all birth dates.
_BIRTH_YEAR_REF = 2024


def _normalize_gender(sex: str) -> str:
    """Map internal sex values to FHIR gender codes."""
    value = str(sex or "").strip().lower()
    if value in {"male", "m"}:
        return "male"
    if value in {"female", "f"}:
        return "female"
    if value == "other":
        return "other"
    return "unknown"


def _patient_to_fhir(patient: Patient) -> list[dict]:
    """Convert a single Patient object to a list of FHIR R5 resources."""
    demo = patient.demographics
    pid = str(demo.patient_id)

    patient_uuid = _duuid(f"patient::{pid}")
    birth_year = _BIRTH_YEAR_REF - demo.age

    resources = []

    # --- Patient ---
    resources.append({
        "resourceType": "Patient",
        "id": patient_uuid,
        "identifier": [
            {
                "system": "https://hipaasynth.local/patient-id",
                "value": pid,
            }
        ],
        "gender": _normalize_gender(demo.sex),
        "birthDate": f"{birth_year}-01-01",
    })

    # --- Conditions ---
    for i, cond in enumerate(patient.conditions):
        condition_uuid = _duuid(f"condition::{pid}::{cond.name}::{i}")
        condition: dict = {
            "resourceType": "Condition",
            "id": condition_uuid,
            "clinicalStatus": {
                "coding": [
                    {
                        "system": "http://terminology.hl7.org/CodeSystem/condition-clinical",
                        "code": "active" if cond.active else "inactive",
                        "display": "Active" if cond.active else "Inactive",
                    }
                ]
            },
            "verificationStatus": {
                "coding": [
                    {
                        "system": "http://terminology.hl7.org/CodeSystem/condition-ver-status",
                        "code": "confirmed",
                        "display": "Confirmed",
                    }
                ]
            },
            "subject": {"reference": f"urn:uuid:{patient_uuid}"},
            "code": {"text": cond.name},
        }
        if hasattr(cond, "onset_age") and cond.onset_age is not None:
            condition["onsetAge"] = {
                "value": cond.onset_age,
                "unit": "years",
                "system": "http://unitsofmeasure.org",
                "code": "a",
            }
        resources.append(condition)

    # --- Encounters + Observations ---
    for visit in patient.visits:
        visit_id = str(visit.visit_id)
        encounter_uuid = _duuid(f"encounter::{pid}::{visit_id}")
        is_telehealth = str(visit.visit_type).strip().lower() == "telehealth"

        encounter: dict = {
            "resourceType": "Encounter",
            "id": encounter_uuid,
            # R5: 'completed' (not 'finished' which was R4-only)
            "status": "completed",
            # R5: class is a CodeableConcept list (not a bare Coding)
            "class": [
                {
                    "coding": [
                        {
                            "system": "http://terminology.hl7.org/CodeSystem/v3-ActCode",
                            "code": "VR" if is_telehealth else "AMB",
                        }
                    ]
                }
            ],
            "subject": {"reference": f"urn:uuid:{patient_uuid}"},
            # R5: renamed from 'period' to 'actualPeriod'
            "actualPeriod": {"start": visit.visit_date},
            "type": [{"text": str(visit.visit_type)}],
        }

        if visit.primary_diagnosis:
            # R5: renamed from 'reasonCode' to 'reason' with value.concept wrapper
            encounter["reason"] = [
                {
                    "value": [
                        {"concept": {"text": str(visit.primary_diagnosis)}}
                    ]
                }
            ]

        resources.append(encounter)

        for j, lab in enumerate(visit.labs):
            observation_uuid = _duuid(f"observation::{pid}::{visit_id}::{lab.lab_name}::{j}")
            observation: dict = {
                "resourceType": "Observation",
                "id": observation_uuid,
                "status": "final",
                "subject": {"reference": f"urn:uuid:{patient_uuid}"},
                "encounter": {"reference": f"urn:uuid:{encounter_uuid}"},
                "code": {"text": str(lab.lab_name)},
                "valueQuantity": {
                    "value": lab.value,
                    "unit": str(lab.unit),
                },
            }
            if lab.date_recorded:
                observation["effectiveDateTime"] = lab.date_recorded
                observation["issued"] = f"{lab.date_recorded}T00:00:00Z"
            if lab.reference_range:
                observation["referenceRange"] = [{"text": str(lab.reference_range)}]

            resources.append(observation)

    return resources


def export_fhir(patients: list[Patient], filename: str = "fhir_bundle.json") -> None:
    """
    Export patient records to a FHIR R5 Bundle (JSON).

    Targets FHIR R5 to pass validator.fhir.org cleanly. Key differences
    from R4: actualPeriod, reason[].value[].concept, class as
    CodeableConcept list, status 'completed'.

    All resource IDs are deterministic — identical inputs produce
    identical UUIDs across runs, preserving the engine's core guarantee.

    Args:
        patients: List of Patient records to export
        filename: Output filename (default: "fhir_bundle.json")
    """
    bundle = {
        "resourceType": "Bundle",
        "id": _duuid(f"bundle::{filename}::{len(patients)}"),
        "type": "collection",
        "entry": [],
    }

    for patient in patients:
        for resource in _patient_to_fhir(patient):
            bundle["entry"].append({
                "fullUrl": f"urn:uuid:{resource['id']}",
                "resource": resource,
            })

    with open(filename, "w", encoding="utf-8") as f:
        json.dump(bundle, f, indent=2, ensure_ascii=False)

    print(f"FHIR bundle written to {filename} ({len(bundle['entry'])} resources)")