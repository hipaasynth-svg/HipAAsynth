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
OMOP CDM v5.4 exporter.

Emits a HipAAsynth cohort as OMOP Common Data Model tables (CSV), so that a
cohort can be loaded into an existing OMOP database and consumed by the OHDSI
tool ecosystem (ATLAS, ACHILLES, DataQualityDashboard, HADES) with no ETL.

Tables written:
  * person.csv
  * condition_occurrence.csv
  * visit_occurrence.csv
  * measurement.csv

Standard concepts come from ``hipaasynth.vocabulary``. Terms with no mapping are
written with ``*_concept_id = 0`` (the OMOP convention for "no matching
concept") and the original term preserved in the ``*_source_value`` column, so
nothing is silently dropped and DataQualityDashboard can surface the gap.

NOTE: The concept_id values in the shipped vocabulary map are curated
best-effort and flagged UNVALIDATED. Validate them against a pinned ATHENA
vocabulary release before using this output for anything beyond testing. See
hipaasynth/vocabulary/README.md.
"""
import csv
import os
from pathlib import Path

from hipaasynth.vocabulary import (
    lookup_condition,
    lookup_measurement,
    lookup_visit,
)

# OMOP standard concept_ids for gender (Gender vocabulary).
_GENDER_CONCEPT = {
    "male": 8507,
    "m": 8507,
    "female": 8532,
    "f": 8532,
}
# OMOP "no matching concept".
_NO_CONCEPT = 0
# Type concept: "EHR" (32817) — records the provenance of the row. Synthetic
# data stands in for EHR-sourced records for tooling purposes.
_TYPE_CONCEPT_EHR = 32817

_PERSON_COLUMNS = [
    "person_id", "gender_concept_id", "year_of_birth",
    "race_concept_id", "ethnicity_concept_id",
    "gender_source_value", "person_source_value",
]
_CONDITION_COLUMNS = [
    "condition_occurrence_id", "person_id", "condition_concept_id",
    "condition_start_date", "condition_type_concept_id",
    "condition_source_value", "condition_source_concept_id",
]
_VISIT_COLUMNS = [
    "visit_occurrence_id", "person_id", "visit_concept_id",
    "visit_start_date", "visit_end_date", "visit_type_concept_id",
    "visit_source_value",
]
_MEASUREMENT_COLUMNS = [
    "measurement_id", "person_id", "measurement_concept_id",
    "measurement_date", "measurement_type_concept_id",
    "value_as_number", "unit_source_value",
    "measurement_source_value", "measurement_source_concept_id",
]

# HipAAsynth Patient.birthDate reference year mirrors the FHIR exporter.
from datetime import datetime as _dt
_BIRTH_YEAR_REF = _dt.now().year


def _gender_concept_id(sex) -> int:
    return _GENDER_CONCEPT.get(str(sex).strip().lower(), _NO_CONCEPT)


def build_cdm_tables(patients):
    """Build in-memory OMOP CDM rows from HipAAsynth patients.

    Returns a dict mapping table name -> list[dict rows]. Integer surrogate keys
    are assigned sequentially and deterministically in patient/visit/condition
    iteration order; ``person_source_value`` preserves the original patient_id
    for traceability back to the FairnessPassport.
    """
    person_rows = []
    condition_rows = []
    visit_rows = []
    measurement_rows = []

    condition_seq = 0
    visit_seq = 0
    measurement_seq = 0

    for person_id, patient in enumerate(patients, start=1):
        demo = patient.demographics
        year_of_birth = _BIRTH_YEAR_REF - int(demo.age)
        person_rows.append({
            "person_id": person_id,
            "gender_concept_id": _gender_concept_id(demo.sex),
            "year_of_birth": year_of_birth,
            "race_concept_id": _NO_CONCEPT,
            "ethnicity_concept_id": _NO_CONCEPT,
            "gender_source_value": demo.sex,
            "person_source_value": demo.patient_id,
        })

        # Condition start dates are not modeled per-condition in the schema; use
        # the earliest visit date when available, else leave blank (DQD-visible).
        default_date = patient.visits[0].visit_date if patient.visits else ""
        for cond in patient.conditions:
            condition_seq += 1
            mapping = lookup_condition(cond.name)
            condition_rows.append({
                "condition_occurrence_id": condition_seq,
                "person_id": person_id,
                "condition_concept_id": mapping.omop_concept_id if mapping else _NO_CONCEPT,
                "condition_start_date": default_date,
                "condition_type_concept_id": _TYPE_CONCEPT_EHR,
                "condition_source_value": cond.name,
                "condition_source_concept_id": _NO_CONCEPT,
            })

        for visit in patient.visits:
            visit_seq += 1
            vmap = lookup_visit(visit.visit_type)
            visit_rows.append({
                "visit_occurrence_id": visit_seq,
                "person_id": person_id,
                "visit_concept_id": vmap.omop_concept_id if vmap else _NO_CONCEPT,
                "visit_start_date": visit.visit_date,
                "visit_end_date": visit.visit_date,
                "visit_type_concept_id": _TYPE_CONCEPT_EHR,
                "visit_source_value": visit.visit_type,
            })
            for lab in visit.labs:
                measurement_seq += 1
                mmap = lookup_measurement(lab.lab_name)
                measurement_rows.append({
                    "measurement_id": measurement_seq,
                    "person_id": person_id,
                    "measurement_concept_id": mmap.omop_concept_id if mmap else _NO_CONCEPT,
                    "measurement_date": lab.date_recorded or visit.visit_date,
                    "measurement_type_concept_id": _TYPE_CONCEPT_EHR,
                    "value_as_number": lab.value,
                    "unit_source_value": lab.unit,
                    "measurement_source_value": lab.lab_name,
                    "measurement_source_concept_id": _NO_CONCEPT,
                })

    return {
        "person": person_rows,
        "condition_occurrence": condition_rows,
        "visit_occurrence": visit_rows,
        "measurement": measurement_rows,
    }


_TABLE_COLUMNS = {
    "person": _PERSON_COLUMNS,
    "condition_occurrence": _CONDITION_COLUMNS,
    "visit_occurrence": _VISIT_COLUMNS,
    "measurement": _MEASUREMENT_COLUMNS,
}


def export_omop(patients, output_dir="omop_cdm"):
    """Write a HipAAsynth cohort as OMOP CDM v5.4 CSV tables.

    Args:
        patients: iterable of ``Patient`` records.
        output_dir: directory to write the CDM CSVs into (created if absent).

    Returns:
        dict mapping table name -> row count written.
    """
    patients = list(patients)
    tables = build_cdm_tables(patients)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    counts = {}
    for table, rows in tables.items():
        columns = _TABLE_COLUMNS[table]
        path = out / f"{table}.csv"
        try:
            with open(path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=columns)
                writer.writeheader()
                for row in rows:
                    writer.writerow(row)
        except OSError as exc:
            raise RuntimeError(f"Failed to write OMOP CDM table: {path}") from exc
        counts[table] = len(rows)

    total = sum(counts.values())
    print(f"OMOP CDM v5.4 written to {out}/ ({total} rows across {len(counts)} tables)")
    return counts
