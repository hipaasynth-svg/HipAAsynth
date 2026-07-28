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

"""FHIR interoperability build (Tier 1 roadmap).

Covers the completed FHIR resource set (MedicationRequest alongside
MedicationStatement) and the R5 required-field contract for the core resources.
"""
import dataclasses
import json

import pytest

from hipaasynth.core.config import GenerationConfig
from hipaasynth.core.schema import Medication
from hipaasynth.exporters.exporters import (
    _patient_to_fhir,
    export_fhir,
    export_fhir_ndjson,
)
from hipaasynth.pipelines.population_pipeline import generate_patients


@pytest.fixture
def patients():
    return generate_patients(GenerationConfig(patient_count=5, seed=42))


# ── MedicationRequest (roadmap step 1) ───────────────────────────────────────

def test_medication_request_emitted_alongside_statement(patients):
    """Each medication yields BOTH a MedicationStatement and a MedicationRequest.

    The two carry distinct FHIR semantics (a recorded fact vs. an order), and
    US Core / USCDI consumers key medications off MedicationRequest, so the
    exporter emits both rather than replacing one with the other.
    """
    p = dataclasses.replace(patients[0], medications=[Medication(name="statin")])
    resources = _patient_to_fhir(p)
    statements = [r for r in resources if r["resourceType"] == "MedicationStatement"]
    requests = [r for r in resources if r["resourceType"] == "MedicationRequest"]
    assert len(statements) == 1
    assert len(requests) == 1


def test_medication_request_required_fields_and_coding(patients):
    """MedicationRequest carries the R5-required fields and the ATC coding."""
    p = dataclasses.replace(patients[0], medications=[Medication(name="statin")])
    resources = _patient_to_fhir(p)
    req = next(r for r in resources if r["resourceType"] == "MedicationRequest")
    # R5 MedicationRequest required (1..1) fields: status, intent, subject,
    # medication.
    assert req["status"] == "active"
    assert req["intent"] == "order"
    assert req["subject"]["reference"].startswith("urn:uuid:")
    assert req["medication"]["concept"]["coding"], "expected a standard coding"
    assert any(
        c["system"] == "http://www.whocc.no/atc"
        for c in req["medication"]["concept"]["coding"]
    )


def test_inactive_medication_request_is_stopped(patients):
    """An inactive medication maps to MedicationRequest.status = 'stopped'."""
    p = dataclasses.replace(patients[0], medications=[Medication(name="statin", active=False)])
    resources = _patient_to_fhir(p)
    req = next(r for r in resources if r["resourceType"] == "MedicationRequest")
    assert req["status"] == "stopped"


def test_medication_request_id_is_deterministic(patients):
    """Resource ids are deterministic across runs (SHA-anchored generation)."""
    p = dataclasses.replace(patients[0], medications=[Medication(name="statin")])
    first = next(r for r in _patient_to_fhir(p) if r["resourceType"] == "MedicationRequest")
    second = next(r for r in _patient_to_fhir(p) if r["resourceType"] == "MedicationRequest")
    assert first["id"] == second["id"]


# ── NDJSON bulk export (roadmap step 2) ──────────────────────────────────────

def test_ndjson_export_one_file_per_resource_type(patients, tmp_path):
    """$export convention: one {ResourceType}.ndjson file per resource type."""
    out = tmp_path / "bulk"
    counts = export_fhir_ndjson(patients, str(out))
    # Core resource types the cohort always produces.
    assert (out / "Patient.ndjson").exists()
    assert (out / "Condition.ndjson").exists()
    for resource_type, count in counts.items():
        path = out / f"{resource_type}.ndjson"
        assert path.exists()
        lines = [ln for ln in path.read_text().splitlines() if ln.strip()]
        # One resource per line; every line is a standalone JSON object of the
        # correct resourceType.
        assert len(lines) == count
        for ln in lines:
            obj = json.loads(ln)
            assert obj["resourceType"] == resource_type


def test_ndjson_one_patient_line_per_patient(patients, tmp_path):
    out = tmp_path / "bulk"
    export_fhir_ndjson(patients, str(out))
    lines = [ln for ln in (out / "Patient.ndjson").read_text().splitlines() if ln.strip()]
    assert len(lines) == len(patients)


def test_ndjson_matches_bundle_resource_set(patients, tmp_path):
    """NDJSON export and single-Bundle export cover the same resources."""
    out = tmp_path / "bulk"
    counts = export_fhir_ndjson(patients, str(out))
    bundle_path = tmp_path / "bundle.json"
    export_fhir(patients, str(bundle_path))
    bundle = json.loads(bundle_path.read_text())
    from collections import Counter
    bundle_counts = Counter(e["resource"]["resourceType"] for e in bundle["entry"])
    assert dict(counts) == dict(bundle_counts)


def test_ndjson_fails_loud_on_io_error(patients, tmp_path):
    occupied = tmp_path / "occupied"
    occupied.write_text("x")  # a file where a dir is needed
    with pytest.raises((RuntimeError, OSError, NotADirectoryError, FileExistsError)):
        export_fhir_ndjson(patients, str(occupied / "sub"))


# ── Encounter.actualPeriod (Tier 2 review fix 5) ─────────────────────────────

def test_encounter_actual_period_has_end_equal_to_start(patients):
    """Encounter.actualPeriod carries an `end`, equal to `start`, matching the
    OMOP exporter's documented same-day-visit convention (visit_end_date =
    visit_start_date). Previously only `start` was emitted.
    """
    encounters = [
        r for p in patients for r in _patient_to_fhir(p)
        if r["resourceType"] == "Encounter"
    ]
    assert encounters  # the fixture cohort has visits
    for enc in encounters:
        period = enc["actualPeriod"]
        assert "end" in period, "actualPeriod is missing 'end'"
        assert period["end"] == period["start"]
