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
from hipaasynth.exporters.exporters import export_fhir_ndjson
from hipaasynth.exporters.fhir_validate import (
    main as fhir_validate_main,
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


def test_broken_condition_clinical_status_is_flagged():
    """Condition.clinicalStatus is a CodeableConcept — an empty one is an error.

    Previously unchecked: clinicalStatus was not in _CODEABLE_CONCEPT_FIELDS, so
    an empty {} sailed through.
    """
    bad = {"resourceType": "Condition", "id": "c",
           "subject": {"reference": "urn:uuid:p"},
           "code": {"text": "asthma"},
           "clinicalStatus": {}}
    errors = validate_resource(bad)
    assert any("clinicalStatus" in e for e in errors), errors


def test_broken_condition_verification_status_is_flagged():
    """verificationStatus.coding missing a code must be flagged."""
    bad = {"resourceType": "Condition", "id": "c",
           "subject": {"reference": "urn:uuid:p"},
           "code": {"text": "asthma"},
           "verificationStatus": {"coding": [{"system": "http://x"}]}}  # no code
    errors = validate_resource(bad)
    assert any("verificationStatus" in e and "code" in e for e in errors), errors


def test_broken_encounter_class_is_flagged():
    """Encounter.class is a *list* of CodeableConcept — a coding missing its
    code must be flagged (list-at-path handling)."""
    bad = {"resourceType": "Encounter", "id": "e", "status": "completed",
           "class": [{"coding": [{"system": "http://x"}]}],  # missing code
           "type": [{"text": "ambulatory"}]}
    errors = validate_resource(bad)
    assert any("class" in e and "code" in e for e in errors), errors


def test_broken_encounter_type_is_flagged():
    """Encounter.type (list of CodeableConcept): an element with neither coding
    nor text is an error."""
    bad = {"resourceType": "Encounter", "id": "e", "status": "completed",
           "class": [{"coding": [{"system": "http://x", "code": "AMB"}]}],
           "type": [{}]}  # neither coding nor text
    errors = validate_resource(bad)
    assert any("type" in e for e in errors), errors


def test_valid_encounter_class_and_type_pass():
    """A well-formed Encounter (class coding + text-only type) must not error —
    guards against false positives from the new list handling."""
    good = {"resourceType": "Encounter", "id": "e", "status": "completed",
            "class": [{"coding": [{"system": "http://x", "code": "AMB"}]}],
            "type": [{"text": "ambulatory"}]}
    assert validate_resource(good) == []


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


def test_cli_main_bundle_returns_zero_for_clean_cohort(patients, tmp_path):
    """The CLI entry point (main) exits 0 on a clean exported Bundle."""
    path = tmp_path / "bundle.json"
    export_fhir(patients, str(path))
    assert fhir_validate_main(["--bundle", str(path)]) == 0


def test_cli_main_bundle_returns_one_for_broken_bundle(tmp_path):
    """main() exits 1 when the Bundle has a structural error."""
    import json
    bad_bundle = {
        "resourceType": "Bundle", "id": "b", "type": "collection",
        "entry": [{"resource": {"resourceType": "Observation", "id": "o",
                                 "status": "final"}}],  # missing required 'code'
    }
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(bad_bundle))
    assert fhir_validate_main(["--bundle", str(path)]) == 1


def test_cli_main_writes_json_report(patients, tmp_path):
    """main(--json ...) writes a JSON report file with the expected keys."""
    import json
    path = tmp_path / "bundle.json"
    export_fhir(patients, str(path))
    report_path = tmp_path / "report.json"
    rc = fhir_validate_main(["--bundle", str(path), "--json", str(report_path)])
    assert rc == 0
    assert report_path.exists()
    report = json.loads(report_path.read_text())
    for key in ("total_resources", "error_count", "ok", "errors", "disclaimer"):
        assert key in report
    assert report["ok"] is True
    assert report["error_count"] == 0


def test_cli_main_ndjson_dir(patients, tmp_path):
    """main(--ndjson-dir ...) validates a bulk-export directory and exits 0."""
    out_dir = tmp_path / "ndjson"
    export_fhir_ndjson(patients, str(out_dir))
    assert fhir_validate_main(["--ndjson-dir", str(out_dir)]) == 0
