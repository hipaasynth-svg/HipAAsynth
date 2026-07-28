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
  * observation_period.csv
  * condition_occurrence.csv
  * visit_occurrence.csv
  * measurement.csv
  * drug_exposure.csv

Column sets follow the OMOP CDM v5.4 specification: every CDM 5.4 required
(NOT NULL) column is present, along with high-value optional columns (visit
linkage via ``visit_occurrence_id``, ``*_source_concept_id`` fields, measurement
numeric ranges, and temporal end dates). Columns HipAAsynth does not model are
emitted empty so a loader sees the full schema.

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
import re
from pathlib import Path

from hipaasynth.vocabulary import (
    lookup_condition,
    lookup_measurement,
    lookup_medication,
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

# OMOP condition status, driven by HipAAsynth's Condition.active (bool) — the same
# field the FHIR exporter turns into a clinicalStatus coding (active/inactive).
# Each entry is (condition_status_concept_id, condition_status_source_value).
#
# ⚠️ UNVALIDATED — same convention as the rest of this map (see module docstring):
# these standard concept_ids are **best-effort SNOMED clinical-status concepts**
# and MUST be confirmed against a pinned ATHENA release before production use. The
# active/inactive text is preserved in condition_status_source_value so a consumer
# can re-resolve them offline. Note: OMOP's dedicated "Condition Status" vocabulary
# encodes diagnosis *position* (primary/secondary/admission/discharge), NOT
# active/inactive; the active/inactive distinction lives in SNOMED clinical-status,
# which is what is used here.
_CONDITION_STATUS_CONCEPT = {
    True: (4230911, "active"),    # SNOMED clinical-status "Active" (best-effort)
    False: (4033240, "inactive"),  # SNOMED clinical-status "Inactive" (best-effort)
}


def _condition_status(active) -> tuple:
    """Return (condition_status_concept_id, source_value) for a Condition.active.

    Mirrors :func:`_gender_concept_id`: a small closed lookup from a modeled field
    to a standard OMOP concept. Falls back to (0, "") for an unknown/None value.
    """
    return _CONDITION_STATUS_CONCEPT.get(bool(active), (_NO_CONCEPT, "")) \
        if active is not None else (_NO_CONCEPT, "")
# Type concept: "EHR" (32817) — records the provenance of the row. Synthetic
# data stands in for EHR-sourced records for tooling purposes. Also used as the
# OBSERVATION_PERIOD period_type_concept_id ("Period covering healthcare
# encounters" is 44814724, but EHR provenance is the honest label here).
_TYPE_CONCEPT_EHR = 32817

# Numeric reference range like "70-99" or "0.6-1.3" (not "<100", which has no low
# bound and is left unparsed).
_RANGE_RE = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*-\s*(-?\d+(?:\.\d+)?)\s*$")

# Column sets align with the OMOP CDM v5.4 table specification. All CDM 5.4
# required (NOT NULL) columns are present; high-value optional columns
# (visit linkage, source_concept_ids, numeric ranges, temporal end dates) are
# included so the output is usable by OHDSI tooling. Columns HipAAsynth does not
# model are written empty rather than omitted, so a loader sees the full schema.
_PERSON_COLUMNS = [
    "person_id", "gender_concept_id", "year_of_birth",
    "month_of_birth", "day_of_birth", "birth_datetime",
    "race_concept_id", "ethnicity_concept_id",
    "location_id", "provider_id", "care_site_id",
    "person_source_value",
    "gender_source_value", "gender_source_concept_id",
    "race_source_value", "race_source_concept_id",
    "ethnicity_source_value", "ethnicity_source_concept_id",
]
_CONDITION_COLUMNS = [
    "condition_occurrence_id", "person_id", "condition_concept_id",
    "condition_start_date", "condition_start_datetime",
    "condition_end_date", "condition_end_datetime",
    "condition_type_concept_id", "condition_status_concept_id",
    "stop_reason", "provider_id", "visit_occurrence_id", "visit_detail_id",
    "condition_source_value", "condition_source_concept_id",
    "condition_status_source_value",
]
_VISIT_COLUMNS = [
    "visit_occurrence_id", "person_id", "visit_concept_id",
    "visit_start_date", "visit_start_datetime",
    "visit_end_date", "visit_end_datetime",
    "visit_type_concept_id", "provider_id", "care_site_id",
    "visit_source_value", "visit_source_concept_id",
    "admitted_from_concept_id", "admitted_from_source_value",
    "discharged_to_concept_id", "discharged_to_source_value",
    "preceding_visit_occurrence_id",
]
_MEASUREMENT_COLUMNS = [
    "measurement_id", "person_id", "measurement_concept_id",
    "measurement_date", "measurement_datetime", "measurement_time",
    "measurement_type_concept_id", "operator_concept_id",
    "value_as_number", "value_as_concept_id", "unit_concept_id",
    "range_low", "range_high",
    "provider_id", "visit_occurrence_id", "visit_detail_id",
    "measurement_source_value", "measurement_source_concept_id",
    "unit_source_value", "unit_source_concept_id", "value_source_value",
]
_DRUG_COLUMNS = [
    "drug_exposure_id", "person_id", "drug_concept_id",
    "drug_exposure_start_date", "drug_exposure_start_datetime",
    "drug_exposure_end_date", "drug_exposure_end_datetime",
    "verbatim_end_date", "drug_type_concept_id", "stop_reason",
    "refills", "quantity", "days_supply", "sig", "route_concept_id",
    "lot_number", "provider_id", "visit_occurrence_id", "visit_detail_id",
    "drug_source_value", "drug_source_concept_id",
    "route_source_value", "dose_unit_source_value",
]
_OBSERVATION_PERIOD_COLUMNS = [
    "observation_period_id", "person_id",
    "observation_period_start_date", "observation_period_end_date",
    "period_type_concept_id",
]


def _parse_reference_range(ref):
    """Parse a HipAAsynth reference-range string into (range_low, range_high).

    Returns ("", "") when the string is not a plain numeric ``low-high`` range
    (e.g. ``"<100"``), so unparseable ranges are left empty rather than guessed.
    """
    if not ref:
        return "", ""
    match = _RANGE_RE.match(str(ref))
    if not match:
        return "", ""
    return match.group(1), match.group(2)

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
    drug_rows = []
    observation_period_rows = []

    condition_seq = 0
    visit_seq = 0
    measurement_seq = 0
    drug_seq = 0
    observation_period_seq = 0

    for person_id, patient in enumerate(patients, start=1):
        demo = patient.demographics
        year_of_birth = _BIRTH_YEAR_REF - int(demo.age)
        person_rows.append({
            "person_id": person_id,
            "gender_concept_id": _gender_concept_id(demo.sex),
            "year_of_birth": year_of_birth,
            "month_of_birth": "",
            "day_of_birth": "",
            "birth_datetime": "",
            "race_concept_id": _NO_CONCEPT,
            "ethnicity_concept_id": _NO_CONCEPT,
            "location_id": "",
            "provider_id": "",
            "care_site_id": "",
            "person_source_value": demo.patient_id,
            "gender_source_value": demo.sex,
            "gender_source_concept_id": _NO_CONCEPT,
            # HipAAsynth models a single demographic category ("ethnicity"), which
            # is race-like; preserve it in race_source_value so it is not dropped.
            # Standard race/ethnicity concept mapping stays 0 (unmapped) — see the
            # roadmap change log for this modeling note.
            "race_source_value": demo.ethnicity,
            "race_source_concept_id": _NO_CONCEPT,
            "ethnicity_source_value": "",
            "ethnicity_source_concept_id": _NO_CONCEPT,
        })

        # VISIT_OCCURRENCE first, so conditions/drugs/measurements can link to a
        # visit_occurrence_id and OBSERVATION_PERIOD can be derived from the span.
        first_visit_id = ""
        visit_dates = []
        for visit in patient.visits:
            visit_seq += 1
            if not first_visit_id:
                first_visit_id = visit_seq
            visit_dates.append(visit.visit_date)
            vmap = lookup_visit(visit.visit_type)
            visit_rows.append({
                "visit_occurrence_id": visit_seq,
                "person_id": person_id,
                "visit_concept_id": vmap.omop_concept_id if vmap else _NO_CONCEPT,
                "visit_start_date": visit.visit_date,
                "visit_start_datetime": "",
                "visit_end_date": visit.visit_date,
                "visit_end_datetime": "",
                "visit_type_concept_id": _TYPE_CONCEPT_EHR,
                "provider_id": "",
                "care_site_id": "",
                "visit_source_value": visit.visit_type,
                "visit_source_concept_id": _NO_CONCEPT,
                "admitted_from_concept_id": _NO_CONCEPT,
                "admitted_from_source_value": "",
                "discharged_to_concept_id": _NO_CONCEPT,
                "discharged_to_source_value": "",
                "preceding_visit_occurrence_id": "",
            })
            for lab in visit.labs:
                measurement_seq += 1
                mmap = lookup_measurement(lab.lab_name)
                range_low, range_high = _parse_reference_range(lab.reference_range)
                measurement_rows.append({
                    "measurement_id": measurement_seq,
                    "person_id": person_id,
                    "measurement_concept_id": mmap.omop_concept_id if mmap else _NO_CONCEPT,
                    "measurement_date": lab.date_recorded or visit.visit_date,
                    "measurement_datetime": "",
                    "measurement_time": "",
                    "measurement_type_concept_id": _TYPE_CONCEPT_EHR,
                    "operator_concept_id": _NO_CONCEPT,
                    "value_as_number": lab.value,
                    "value_as_concept_id": _NO_CONCEPT,
                    "unit_concept_id": _NO_CONCEPT,
                    "range_low": range_low,
                    "range_high": range_high,
                    "provider_id": "",
                    "visit_occurrence_id": visit_seq,
                    "visit_detail_id": "",
                    "measurement_source_value": lab.lab_name,
                    "measurement_source_concept_id": _NO_CONCEPT,
                    "unit_source_value": lab.unit,
                    "unit_source_concept_id": _NO_CONCEPT,
                    "value_source_value": lab.value,
                })

        # Condition start dates are not modeled per-condition in the schema; use
        # the earliest visit date when available, else leave blank (DQD-visible).
        default_date = visit_dates[0] if visit_dates else ""
        for cond in patient.conditions:
            condition_seq += 1
            mapping = lookup_condition(cond.name)
            status_concept_id, status_source_value = _condition_status(
                getattr(cond, "active", None)
            )
            condition_rows.append({
                "condition_occurrence_id": condition_seq,
                "person_id": person_id,
                "condition_concept_id": mapping.omop_concept_id if mapping else _NO_CONCEPT,
                "condition_start_date": default_date,
                "condition_start_datetime": "",
                "condition_end_date": "",
                "condition_end_datetime": "",
                "condition_type_concept_id": _TYPE_CONCEPT_EHR,
                "condition_status_concept_id": status_concept_id,
                "stop_reason": "",
                "provider_id": "",
                "visit_occurrence_id": first_visit_id,
                "visit_detail_id": "",
                "condition_source_value": cond.name,
                "condition_source_concept_id": _NO_CONCEPT,
                "condition_status_source_value": status_source_value,
            })

        # DRUG_EXPOSURE. Medications live on the Patient (schema 1.1.0+); older
        # patients without the field simply produce no drug rows. Class-level
        # terms (ATC) and combinations have no standard drug concept, so they
        # carry drug_concept_id 0 with the source value preserved — the OMOP
        # convention for "no standard mapping", which DQD can surface.
        for med in getattr(patient, "medications", ()) or ():
            drug_seq += 1
            dmap = lookup_medication(med.name)
            concept_id = (dmap.omop_concept_id if dmap and dmap.omop_concept_id else _NO_CONCEPT)
            drug_rows.append({
                "drug_exposure_id": drug_seq,
                "person_id": person_id,
                "drug_concept_id": concept_id,
                "drug_exposure_start_date": default_date,
                "drug_exposure_start_datetime": "",
                # 5.4 requires drug_exposure_end_date NOT NULL. Duration is not
                # modeled, so a single-day exposure (end == start) is the honest
                # default rather than a fabricated span.
                "drug_exposure_end_date": default_date,
                "drug_exposure_end_datetime": "",
                "verbatim_end_date": "",
                "drug_type_concept_id": _TYPE_CONCEPT_EHR,
                "stop_reason": "",
                "refills": "",
                "quantity": "",
                "days_supply": "",
                "sig": "",
                "route_concept_id": _NO_CONCEPT,
                "lot_number": "",
                "provider_id": "",
                "visit_occurrence_id": first_visit_id,
                "visit_detail_id": "",
                "drug_source_value": med.name,
                "drug_source_concept_id": _NO_CONCEPT,
                "route_source_value": "",
                "dose_unit_source_value": "",
            })

        # OBSERVATION_PERIOD — required by OHDSI cohort tooling (ATLAS/ACHILLES).
        # One period per person spanning the earliest to latest recorded visit.
        if visit_dates:
            observation_period_seq += 1
            observation_period_rows.append({
                "observation_period_id": observation_period_seq,
                "person_id": person_id,
                "observation_period_start_date": min(visit_dates),
                "observation_period_end_date": max(visit_dates),
                "period_type_concept_id": _TYPE_CONCEPT_EHR,
            })

    return {
        "person": person_rows,
        "observation_period": observation_period_rows,
        "condition_occurrence": condition_rows,
        "visit_occurrence": visit_rows,
        "measurement": measurement_rows,
        "drug_exposure": drug_rows,
    }


_TABLE_COLUMNS = {
    "person": _PERSON_COLUMNS,
    "observation_period": _OBSERVATION_PERIOD_COLUMNS,
    "condition_occurrence": _CONDITION_COLUMNS,
    "visit_occurrence": _VISIT_COLUMNS,
    "measurement": _MEASUREMENT_COLUMNS,
    "drug_exposure": _DRUG_COLUMNS,
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
