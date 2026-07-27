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
from hipaasynth.exporters.exporters import _patient_to_fhir, export_fhir
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
