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
Exporters — FHIR R5, JSON, CSV.

FHIR fix applied:
  bundle ID uses os.path.basename(filename) not full path.
  This ensures FHIR bundle IDs are path-independent.
"""
import csv
import json
import os
import uuid
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, List

from hipaasynth.core.schema import Patient
from hipaasynth.vocabulary import (
    lookup_condition,
    lookup_measurement,
    lookup_medication,
    lookup_visit,
)

_NS = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")
_BIRTH_YEAR_REF = datetime.now().year


def _duuid(key: str) -> str:
    return str(uuid.uuid5(_NS, key))


def _ensure_parent_dir(path: str) -> None:
    """Create parent directories for a file path if they do not exist."""
    parent = Path(path).parent
    if parent:
        parent.mkdir(parents=True, exist_ok=True)


def _collect_observation_keys(patients: Iterable[Patient]) -> List[str]:
    """
    Collect the union of all observation keys across patients while preserving
    a stable order. This prevents silently dropping observation fields that are
    not in a hard-coded list (e.g., stroke observations being dropped by the
    sepsis-oriented CSV exporter).
    """
    seen = []
    seen_set = set()
    for p in patients:
        for key in getattr(p, "observations", {}) or {}:
            if key not in seen_set:
                seen.append(key)
                seen_set.add(key)
    return seen


def export_csv_stream(patient_iter, filepath):
    """
    Stream patients to a CSV file.

    Writes one row per patient with core demographic and condition fields.

    The output path is trusted operator input: the engine writes exactly where
    directed and does not sandbox the path — containment is the deploying host's
    responsibility (see docs/DEPLOYMENT.md). Fails loud — any I/O error raises
    RuntimeError rather than leaving a silent partial file. Records are synthetic
    (no PHI).
    """
    _ensure_parent_dir(filepath)
    try:
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
    except OSError as exc:
        raise RuntimeError(f"Failed to write CSV stream: {filepath}") from exc


def export_json(patients, filename="output.json"):
    """Export patients to JSON.

    Output path is trusted operator input (not sandboxed — see
    docs/DEPLOYMENT.md); fails loud with RuntimeError on any I/O error rather
    than leaving a partial file. Records are synthetic (no PHI).
    """
    _ensure_parent_dir(filename)
    try:
        data = [p.to_dict() for p in patients]
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except OSError as exc:
        raise RuntimeError(f"Failed to write JSON: {filename}") from exc


def _flat_patient_rows(patients):
    """Build the flat patient table shared by the CSV and Parquet exporters.

    Returns ``(fieldnames, rows)`` where ``rows`` is a list of dicts keyed by
    ``fieldnames``. Observation columns are discovered dynamically (the union
    across patients) so condition-specific fields (sepsis, stroke, etc.) are not
    silently dropped. Keeping this in one place guarantees the CSV and Parquet
    exporters emit identical columns and values.
    """
    base_fields = [
        "patient_id",
        "seed",
        "age",
        "sex",
        "ethnicity",
        "height_cm",
        "weight_kg",
        "bmi",
        "bmi_category",
        "conditions",
        "num_visits",
        "num_labs",
        "engine_version",
        "schema_version",
        "synthetic",
        "disclaimer",
    ]
    observation_fields = _collect_observation_keys(patients)
    fieldnames = [*base_fields, *observation_fields]

    rows = []
    for p in patients:
        row = {
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
        }
        row.update(getattr(p, "observations", {}) or {})
        rows.append(row)
    return fieldnames, rows


def export_csv(patients, filename="output.csv"):
    """
    Export patients to CSV including all observation fields.

    Observation columns are discovered dynamically so that condition-specific
    fields (sepsis, stroke, etc.) are not silently dropped.

    Output path is trusted operator input (not sandboxed — see
    docs/DEPLOYMENT.md); fails loud with RuntimeError on any I/O error rather
    than leaving a partial file. Records are synthetic (no PHI).
    """
    _ensure_parent_dir(filename)
    patients = list(patients)
    fieldnames, rows = _flat_patient_rows(patients)

    try:
        with open(filename, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            for row in rows:
                writer.writerow(row)
    except OSError as exc:
        raise RuntimeError(f"Failed to write CSV: {filename}") from exc


def export_parquet(patients, filename="output.parquet"):
    """Export the flat patient table to Apache Parquet (columnar).

    Mirrors :func:`export_csv`'s columns and values exactly (both go through
    ``_flat_patient_rows``), but writes a columnar Parquet file suited to
    analytics engines (DuckDB, Spark, pandas, the Seismometer adapter).

    Parquet is an **optional** feature: the engine core is pure-Python/standard
    library, so ``pyarrow`` is imported lazily and only when this function is
    called. If it is not installed, a clear ``RuntimeError`` explains how to get
    it (``pip install 'hipaasynth[parquet]'``). See docs/ROADMAP_CHANGELOG.md.

    Output path is trusted operator input (not sandboxed — see
    docs/DEPLOYMENT.md); fails loud with RuntimeError on any I/O error. Records
    are synthetic (no PHI).
    """
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise RuntimeError(
            "Parquet export requires the optional 'pyarrow' dependency, which is "
            "not installed. Install it with: pip install 'hipaasynth[parquet]'"
        ) from exc

    _ensure_parent_dir(filename)
    patients = list(patients)
    fieldnames, rows = _flat_patient_rows(patients)

    columns = {}
    for name in fieldnames:
        values = [row.get(name) for row in rows]
        try:
            columns[name] = pa.array(values)
        except (pa.ArrowInvalid, pa.ArrowTypeError):
            # Heterogeneously-typed observation column — fall back to strings so
            # the export never fails on a mixed column.
            columns[name] = pa.array([None if v is None else str(v) for v in values])
    table = pa.table(columns)

    try:
        pq.write_table(table, filename)
    except OSError as exc:
        raise RuntimeError(f"Failed to write Parquet: {filename}") from exc
    print(f"Parquet written to {filename} ({table.num_rows} rows, {table.num_columns} cols)")


def summary_stats(patients):
    if not patients:
        return {
            "count": 0,
            "age_min": None,
            "age_max": None,
            "age_mean": None,
            "height_mean_cm": None,
            "weight_mean_kg": None,
            "bmi_mean": None,
            "sex_counts": {},
            "ethnicity_counts": {},
            "bmi_category_counts": {},
            "condition_counts": {},
        }
    count = len(patients)
    ages = [p.demographics.age for p in patients]
    heights = [p.anthropometrics.height_cm for p in patients]
    weights = [p.anthropometrics.weight_kg for p in patients]
    bmis = [p.anthropometrics.bmi for p in patients]
    condition_counts = Counter()
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


def profile_fit_stats(patients, cfg):
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
            observed_age_bands.append({"min": lo, "max": hi, "target_weight": weight, "observed_weight": count / total})
    max_err = abs(observed_female - cfg.sex_ratio_female) * 100
    for category, target_weight in (cfg.ethnicity_weights or {}).items():
        err = abs(observed_ethnicity.get(category, 0.0) - target_weight) * 100
        if err > max_err:
            max_err = err
    for band in observed_age_bands:
        err = abs(band["observed_weight"] - band["target_weight"]) * 100
        if err > max_err:
            max_err = err
    return {
        "profile_name": cfg.profile_name,
        "target_female_ratio": cfg.sex_ratio_female,
        "observed_female_ratio": observed_female,
        "ethnicity_fit": [
            {"category": cat, "target_weight": tw, "observed_weight": observed_ethnicity.get(cat, 0.0)}
            for cat, tw in (cfg.ethnicity_weights or {}).items()
        ],
        "age_band_fit": observed_age_bands,
        "max_abs_error_pts": round(max_err, 1),
        "generated_count": total,
    }


def print_summary(stats):
    if not stats or stats.get("count", 0) == 0:
        print("Total Patients: 0")
        return
    count = stats["count"]
    print(f"Total Patients: {count}")
    print(f"Age: min={stats['age_min']} max={stats['age_max']} mean={stats['age_mean']}")
    print(f"BMI mean: {stats['bmi_mean']}")
    for sex, count in sorted(stats["sex_counts"].items()):
        pct = (count / stats["count"]) * 100 if stats["count"] > 0 else 0
        print(f"  {sex}: {count} ({pct:.1f}%)")
    for cond, count in sorted(stats["condition_counts"].items()):
        pct = (count / stats["count"]) * 100 if stats["count"] > 0 else 0
        print(f"  {cond}: {count} ({pct:.1f}%)")


def print_profile_fit(profile_stats):
    if profile_stats is None:
        return
    print(f"PROFILE FIT: {profile_stats['profile_name']} | max error: {profile_stats['max_abs_error_pts']} pts")


def _normalize_gender(sex):
    value = str(sex or "").strip().lower()
    if value in {"male", "m"}:
        return "male"
    if value in {"female", "f"}:
        return "female"
    if value == "other":
        return "other"
    return "unknown"


def _codeable_concept(mapping, fallback_text):
    """Build a FHIR CodeableConcept from a vocabulary mapping.

    Always carries a human-readable ``text``. When a standard-concept mapping
    exists, attaches SNOMED/LOINC/ICD-10-CM ``coding[]`` entries so the resource
    is queryable by coding-aware consumers. Unmapped terms degrade gracefully to
    text-only (the pre-vocabulary behavior).
    """
    display_text = fallback_text
    concept = {"text": display_text}
    if mapping is not None:
        codings = mapping.fhir_coding()
        if codings:
            concept["coding"] = codings
        if mapping.omop_concept_name:
            concept["text"] = mapping.omop_concept_name
        else:
            concept["text"] = display_text
    return concept


def _patient_to_fhir(patient):
    demo = patient.demographics
    pid = str(demo.patient_id)
    patient_uuid = _duuid(f"patient::{pid}")
    birth_year = _BIRTH_YEAR_REF - demo.age
    resources = []
    resources.append(
        {
            "resourceType": "Patient",
            "id": patient_uuid,
            "identifier": [{"system": "https://hipaasynth.local/patient-id", "value": pid}],
            "gender": _normalize_gender(demo.sex),
            "birthDate": f"{birth_year}-01-01",
        }
    )
    for i, cond in enumerate(patient.conditions):
        condition_uuid = _duuid(f"condition::{pid}::{cond.name}::{i}")
        resources.append(
            {
                "resourceType": "Condition",
                "id": condition_uuid,
                "clinicalStatus": {
                    "coding": [
                        {
                            "system": "http://terminology.hl7.org/CodeSystem/condition-clinical",
                            "code": "active" if cond.active else "inactive",
                        }
                    ]
                },
                "verificationStatus": {
                    "coding": [
                        {
                            "system": "http://terminology.hl7.org/CodeSystem/condition-ver-status",
                            "code": "confirmed",
                        }
                    ]
                },
                "subject": {"reference": f"urn:uuid:{patient_uuid}"},
                "code": _codeable_concept(lookup_condition(cond.name), cond.name),
            }
        )
    for i, med in enumerate(getattr(patient, "medications", ()) or ()):
        med_concept = _codeable_concept(lookup_medication(med.name), med.name)
        is_active = getattr(med, "active", True)
        med_uuid = _duuid(f"medication::{pid}::{med.name}::{i}")
        resources.append(
            {
                "resourceType": "MedicationStatement",
                "id": med_uuid,
                "status": "recorded" if is_active else "entered-in-error",
                "subject": {"reference": f"urn:uuid:{patient_uuid}"},
                "medication": {"concept": med_concept},
            }
        )
        # MedicationRequest — the order/intent that stands behind the statement.
        # US Core / USCDI consumers key the "Medications" data class off
        # MedicationRequest, so it is emitted alongside MedicationStatement
        # (additive; see docs/ROADMAP_CHANGELOG.md for the keep-both rationale).
        medreq_uuid = _duuid(f"medicationrequest::{pid}::{med.name}::{i}")
        resources.append(
            {
                "resourceType": "MedicationRequest",
                "id": medreq_uuid,
                "status": "active" if is_active else "stopped",
                "intent": "order",
                "subject": {"reference": f"urn:uuid:{patient_uuid}"},
                "medication": {"concept": med_concept},
            }
        )
    for visit in patient.visits:
        visit_id = str(visit.visit_id)
        encounter_uuid = _duuid(f"encounter::{pid}::{visit_id}")
        is_telehealth = str(visit.visit_type).strip().lower() == "telehealth"
        encounter = {
            "resourceType": "Encounter",
            "id": encounter_uuid,
            "status": "completed",
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
            "actualPeriod": {"start": visit.visit_date},
            "type": [{"text": str(visit.visit_type)}],
        }
        if visit.primary_diagnosis:
            encounter["reason"] = [{"value": [{"concept": {"text": str(visit.primary_diagnosis)}}]}]
        resources.append(encounter)
        for j, lab in enumerate(visit.labs):
            observation_uuid = _duuid(f"observation::{pid}::{visit_id}::{lab.lab_name}::{j}")
            obs = {
                "resourceType": "Observation",
                "id": observation_uuid,
                "status": "final",
                "subject": {"reference": f"urn:uuid:{patient_uuid}"},
                "encounter": {"reference": f"urn:uuid:{encounter_uuid}"},
                "code": _codeable_concept(lookup_measurement(lab.lab_name), str(lab.lab_name)),
                "valueQuantity": {"value": lab.value, "unit": str(lab.unit)},
            }
            if lab.date_recorded:
                obs["effectiveDateTime"] = lab.date_recorded
                obs["issued"] = f"{lab.date_recorded}T00:00:00Z"
            if lab.reference_range:
                obs["referenceRange"] = [{"text": str(lab.reference_range)}]
            resources.append(obs)
    return resources


def export_fhir(patients, filename="fhir_bundle.json"):
    """
    Export FHIR R5 Bundle. Bundle ID uses os.path.basename for path-independence.
    Fix applied: bundle::{basename}::{count} not full path.

    Output path is trusted operator input (not sandboxed — see
    docs/DEPLOYMENT.md); fails loud with RuntimeError on any I/O error rather
    than leaving a partial file. Records are synthetic (no PHI).
    """
    _ensure_parent_dir(filename)
    bundle = {
        "resourceType": "Bundle",
        "id": _duuid(f"bundle::{os.path.basename(filename)}::{len(patients)}"),
        "type": "collection",
        "entry": [],
    }
    for patient in patients:
        for resource in _patient_to_fhir(patient):
            bundle["entry"].append({"fullUrl": f"urn:uuid:{resource['id']}", "resource": resource})
    try:
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(bundle, f, indent=2, ensure_ascii=False)
    except OSError as exc:
        raise RuntimeError(f"Failed to write FHIR bundle: {filename}") from exc
    print(f"FHIR bundle written to {filename} ({len(bundle['entry'])} resources)")


def export_fhir_ndjson(patients, output_dir="fhir_ndjson"):
    """Export FHIR resources as newline-delimited JSON, one file per type.

    Implements the FHIR Bulk Data Access ("$export") layout: resources are
    grouped by ``resourceType`` and written to ``{output_dir}/{ResourceType}.ndjson``,
    one resource per line. This is the shape bulk-ingestion consumers expect, and
    it is **additive** — the single-Bundle :func:`export_fhir` is unchanged and
    both cover the same resource set.

    The output directory is trusted operator input (not sandboxed — see
    docs/DEPLOYMENT.md); fails loud with RuntimeError on any I/O error rather than
    leaving partial files. Records are synthetic (no PHI).

    Returns:
        dict mapping resourceType -> number of resources written.
    """
    grouped: dict[str, list] = {}
    for patient in patients:
        for resource in _patient_to_fhir(patient):
            grouped.setdefault(resource["resourceType"], []).append(resource)

    out = Path(output_dir)
    try:
        out.mkdir(parents=True, exist_ok=True)
        counts = {}
        for resource_type, resources in grouped.items():
            path = out / f"{resource_type}.ndjson"
            with open(path, "w", encoding="utf-8") as f:
                for resource in resources:
                    f.write(json.dumps(resource, ensure_ascii=False))
                    f.write("\n")
            counts[resource_type] = len(resources)
    except OSError as exc:
        raise RuntimeError(f"Failed to write FHIR NDJSON export: {output_dir}") from exc

    total = sum(counts.values())
    print(f"FHIR NDJSON written to {out}/ ({total} resources across {len(counts)} files)")
    return counts
