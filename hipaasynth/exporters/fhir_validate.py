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
Structural FHIR validator for HipAAsynth exporter output.

This is a self-contained, offline, pure-Python **structural / schema-level**
validator for the FHIR resources emitted by :mod:`hipaasynth.exporters.exporters`.
It checks, against **FHIR R5** shapes (the dialect the exporter emits):

  * ``resourceType`` present and one of the types HipAAsynth produces;
  * required (1..1) fields present per resource type;
  * a few value-set-bound fields carry a valid code (Patient.gender,
    Observation.status, Encounter.status, MedicationStatement.status,
    MedicationRequest.status/intent);
  * ``CodeableConcept`` fields carry at least a ``coding`` or a ``text``, and each
    ``coding`` carries a ``system`` and ``code``;
  * **referential integrity**: every intra-bundle ``urn:uuid:`` reference resolves
    to a resource present in the same set.

⚠️ **This is NOT a substitute for the official HL7 FHIR IG validator.** It does not
load StructureDefinitions, does not check terminology bindings against live
terminology servers, does not evaluate FHIRPath invariants, and does not verify
US Core / any Implementation Guide profile conformance. Before making any
conformance claim, run the official validator
(https://validator.fhir.org / the HL7 ``validator_cli.jar``) against the exported
artifacts. This module is a fast, dependency-free pre-flight check that catches
the structural mistakes an exporter is most likely to make.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

# Resource types HipAAsynth's exporter produces.
_KNOWN_TYPES = {
    "Patient",
    "Condition",
    "Observation",
    "Encounter",
    "MedicationStatement",
    "MedicationRequest",
    "Bundle",
}

# Required (1..1) fields per resource type, as emitted (FHIR R5). Kept
# deliberately to the fields that are genuinely required in R5 so the validator
# never reports a false positive against a spec-conformant resource.
_REQUIRED_FIELDS = {
    "Patient": (),
    "Condition": ("subject",),
    "Observation": ("status", "code"),
    "Encounter": ("status",),
    "MedicationStatement": ("status", "subject", "medication"),
    "MedicationRequest": ("status", "intent", "subject", "medication"),
}

# Value-set-bound fields we can check offline (small, closed code systems).
_GENDER_VALUES = {"male", "female", "other", "unknown"}
_OBSERVATION_STATUS = {
    "registered", "preliminary", "final", "amended", "corrected",
    "cancelled", "entered-in-error", "unknown",
}
# R5 Encounter.status value set.
_ENCOUNTER_STATUS = {
    "planned", "in-progress", "on-hold", "discharged", "completed",
    "cancelled", "discontinued", "entered-in-error", "unknown",
}
# R5 MedicationStatement.status value set.
_MEDSTATEMENT_STATUS = {"recorded", "entered-in-error", "draft"}
# R5 MedicationRequest.status / .intent value sets.
_MEDREQUEST_STATUS = {
    "active", "on-hold", "ended", "stopped", "completed", "cancelled",
    "entered-in-error", "draft", "unknown",
}
_MEDREQUEST_INTENT = {
    "proposal", "plan", "order", "original-order", "reflex-order",
    "filler-order", "instance-order", "option",
}

# CodeableConcept-typed fields to check per resource type. Nested paths use a
# tuple of keys (e.g. medication.concept).
_CODEABLE_CONCEPT_FIELDS = {
    "Condition": (("code",),),
    "Observation": (("code",),),
    "MedicationStatement": (("medication", "concept"),),
    "MedicationRequest": (("medication", "concept"),),
}


@dataclass
class FhirValidationReport:
    """Result of validating a set of FHIR resources."""

    total: int = 0
    errors: list = field(default_factory=list)  # list[{resourceType, id, message}]

    @property
    def ok(self) -> bool:
        return not self.errors

    def as_dict(self) -> dict:
        return {
            "total_resources": self.total,
            "error_count": len(self.errors),
            "ok": self.ok,
            "errors": self.errors,
            "disclaimer": (
                "Structural R5 check only — NOT a substitute for the official "
                "HL7 FHIR IG validator."
            ),
        }


def _get_path(obj: dict, path: tuple):
    """Walk a nested dict by a tuple of keys; return None if any hop is absent."""
    cur = obj
    for key in path:
        if not isinstance(cur, dict) or key not in cur:
            return None
        cur = cur[key]
    return cur


def _check_codeable_concept(cc, label: str) -> list[str]:
    errors = []
    if not isinstance(cc, dict):
        errors.append(f"{label}: CodeableConcept must be an object")
        return errors
    codings = cc.get("coding")
    text = cc.get("text")
    if not codings and not text:
        errors.append(f"{label}: CodeableConcept must carry a coding[] or a text")
    if codings is not None:
        if not isinstance(codings, list):
            errors.append(f"{label}: coding must be an array")
        else:
            for idx, coding in enumerate(codings):
                if not isinstance(coding, dict):
                    errors.append(f"{label}.coding[{idx}]: must be an object")
                    continue
                if not coding.get("system"):
                    errors.append(f"{label}.coding[{idx}]: missing system")
                if not coding.get("code"):
                    errors.append(f"{label}.coding[{idx}]: missing code")
    return errors


def _check_value_sets(resource: dict, rtype: str) -> list[str]:
    errors = []
    if rtype == "Patient" and "gender" in resource:
        if resource["gender"] not in _GENDER_VALUES:
            errors.append(
                f"gender '{resource['gender']}' not in AdministrativeGender value set"
            )
    if rtype == "Observation" and "status" in resource:
        if resource["status"] not in _OBSERVATION_STATUS:
            errors.append(f"status '{resource['status']}' not a valid Observation status")
    if rtype == "Encounter" and "status" in resource:
        if resource["status"] not in _ENCOUNTER_STATUS:
            errors.append(f"status '{resource['status']}' not a valid R5 Encounter status")
    if rtype == "MedicationStatement" and "status" in resource:
        if resource["status"] not in _MEDSTATEMENT_STATUS:
            errors.append(
                f"status '{resource['status']}' not a valid R5 MedicationStatement status"
            )
    if rtype == "MedicationRequest":
        if resource.get("status") not in _MEDREQUEST_STATUS:
            errors.append(
                f"status '{resource.get('status')}' not a valid R5 MedicationRequest status"
            )
        if resource.get("intent") not in _MEDREQUEST_INTENT:
            errors.append(
                f"intent '{resource.get('intent')}' not a valid MedicationRequest intent"
            )
    return errors


def validate_resource(resource: dict) -> list[str]:
    """Validate one resource in isolation; return a list of error strings.

    Referential integrity is *not* checked here (it needs the whole set) — use
    :func:`validate_resources` for that.
    """
    errors: list[str] = []
    if not isinstance(resource, dict):
        return ["resource is not a JSON object"]

    rtype = resource.get("resourceType")
    if not rtype:
        return ["missing resourceType"]
    if rtype not in _KNOWN_TYPES:
        errors.append(f"unknown resourceType '{rtype}'")
        return errors

    for req in _REQUIRED_FIELDS.get(rtype, ()):  # required (1..1) fields
        value = resource.get(req)
        if value is None or value == "" or value == [] or value == {}:
            errors.append(f"{rtype}: missing required field '{req}'")

    for path in _CODEABLE_CONCEPT_FIELDS.get(rtype, ()):  # CodeableConcept shape
        cc = _get_path(resource, path)
        if cc is not None:
            errors.extend(_check_codeable_concept(cc, ".".join(path)))

    errors.extend(_check_value_sets(resource, rtype))
    return errors


def _iter_references(obj) -> Iterable[str]:
    """Yield every ``reference`` string found anywhere in a resource."""
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key == "reference" and isinstance(value, str):
                yield value
            else:
                yield from _iter_references(value)
    elif isinstance(obj, list):
        for item in obj:
            yield from _iter_references(item)


def validate_resources(resources: Iterable[dict]) -> FhirValidationReport:
    """Validate a set of resources, including cross-resource referential integrity.

    Every ``urn:uuid:`` reference must resolve to a resource ``id`` present in the
    set. References that are not ``urn:uuid:`` (e.g. external absolute URLs) are
    left unchecked — resolving those needs a live server, which is out of scope.
    """
    resources = list(resources)
    report = FhirValidationReport(total=len(resources))

    ids = {r.get("id") for r in resources if isinstance(r, dict) and r.get("id")}

    for resource in resources:
        rtype = resource.get("resourceType") if isinstance(resource, dict) else None
        rid = resource.get("id") if isinstance(resource, dict) else None
        for message in validate_resource(resource):
            report.errors.append({"resourceType": rtype, "id": rid, "message": message})
        # Referential integrity for intra-bundle urn:uuid references.
        for ref in _iter_references(resource):
            if ref.startswith("urn:uuid:"):
                target = ref[len("urn:uuid:"):]
                if target not in ids:
                    report.errors.append({
                        "resourceType": rtype, "id": rid,
                        "message": f"dangling reference '{ref}' (no such resource in set)",
                    })
    return report


def validate_bundle(bundle: dict) -> FhirValidationReport:
    """Validate a FHIR Bundle dict (as written by ``export_fhir``)."""
    if not isinstance(bundle, dict) or bundle.get("resourceType") != "Bundle":
        report = FhirValidationReport(total=0)
        report.errors.append({"resourceType": None, "id": None,
                              "message": "not a FHIR Bundle"})
        return report
    resources = [e.get("resource", {}) for e in bundle.get("entry", [])]
    return validate_resources(resources)


def validate_ndjson_dir(ndjson_dir) -> FhirValidationReport:
    """Validate a directory of ``{ResourceType}.ndjson`` files (from the bulk export)."""
    base = Path(ndjson_dir)
    resources: list[dict] = []
    for path in sorted(base.glob("*.ndjson")):
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    resources.append(json.loads(line))
    return validate_resources(resources)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Structural FHIR validator for HipAAsynth exporter output. "
                    "NOT a substitute for the official HL7 FHIR IG validator.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--bundle", type=Path, help="Path to a FHIR Bundle JSON file.")
    group.add_argument("--ndjson-dir", type=Path,
                       help="Directory of {ResourceType}.ndjson files.")
    parser.add_argument("--json", type=Path, default=None,
                        help="Write the full JSON report to this path.")
    args = parser.parse_args(argv)

    if args.bundle:
        report = validate_bundle(json.loads(args.bundle.read_text(encoding="utf-8")))
    else:
        report = validate_ndjson_dir(args.ndjson_dir)

    if args.json:
        args.json.write_text(json.dumps(report.as_dict(), indent=2), encoding="utf-8")
        print(f"Wrote JSON report to {args.json}")

    print(f"Validated {report.total} resources: "
          f"{'PASS' if report.ok else f'{len(report.errors)} error(s)'}")
    print("NOTE: structural R5 check only — run the official HL7 FHIR IG "
          "validator before any conformance claim.")
    for err in report.errors[:50]:
        print(f"  [{err['resourceType']}/{err['id']}] {err['message']}")
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
