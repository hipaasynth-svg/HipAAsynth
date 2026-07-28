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

"""Structural FHIR validator (roadmap step 3).

NOTE: this validates R5 *structure* (required fields, valid resourceType,
value-set membership for a few bound fields, and referential integrity). It is
NOT a substitute for the official HL7 FHIR IG validator — see the module
docstring and the roadmap change log.
"""
import dataclasses

import pytest

from hipaasynth.core.config import GenerationConfig
from hipaasynth.core.schema import Medication
from hipaasynth.exporters.exporters import _patient_to_fhir, export_fhir
from hipaasynth.exporters.fhir_validate import (
    validate_bundle,
    validate_resource,
    validate_resources,
)
from hipaasynth.pipelines.population_pipeline import generate_patients


@pytest.fixture
def patients():
    return generate_patients(GenerationConfig(patient_count=5, seed=42))


def test_generated_cohort_passes_structural_validation(patients):
    """A full generated cohort (with meds) validates clean."""
    p = dataclasses.replace(patients[0], medications=[Medication(name="statin")])
    resources = []
    for pt in [p] + list(patients[1:]):
        resources.extend(_patient_to_fhir(pt))
    report = validate_resources(resources)
    assert report.ok, report.errors


def test_missing_required_field_is_flagged():
    """An Observation without the required 'code' is an error."""
    bad = {"resourceType": "Observation", "id": "x", "status": "final",
           "subject": {"reference": "urn:uuid:p"}}
    errors = validate_resource(bad)
    assert any("code" in e for e in errors)


def test_unknown_resource_type_is_flagged():
    errors = validate_resource({"resourceType": "Wizard", "id": "z"})
    assert any("resourceType" in e for e in errors)


def test_invalid_gender_value_set_is_flagged():
    bad = {"resourceType": "Patient", "id": "p", "gender": "yes"}
    errors = validate_resource(bad)
    assert any("gender" in e for e in errors)


def test_codeable_concept_without_coding_or_text_is_flagged():
    bad = {"resourceType": "Condition", "id": "c",
           "subject": {"reference": "urn:uuid:p"}, "code": {}}
    errors = validate_resource(bad)
    assert any("code" in e.lower() for e in errors)


def test_dangling_reference_is_flagged(patients):
    """Referential integrity: a reference to an absent resource is an error."""
    resources = []
    for pt in patients:
        resources.extend(_patient_to_fhir(pt))
    # Point the first Condition's subject at a non-existent patient.
    cond = next(r for r in resources if r["resourceType"] == "Condition")
    cond["subject"]["reference"] = "urn:uuid:does-not-exist"
    report = validate_resources(resources)
    assert not report.ok
    assert any("reference" in e["message"].lower() for e in report.errors)


def test_validate_bundle_accepts_exported_bundle(patients, tmp_path):
    import json
    path = tmp_path / "bundle.json"
    export_fhir(patients, str(path))
    bundle = json.loads(path.read_text())
    report = validate_bundle(bundle)
    assert report.ok, report.errors
