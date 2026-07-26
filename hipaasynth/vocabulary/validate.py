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
Validate the HipAAsynth concept map against an OMOP CONCEPT table.

The concept_ids shipped in ``concept_map.json`` are curated best-effort and
flagged ``curated-pending-athena``. This module turns that manual checklist into
a single command: point it at the ``CONCEPT.csv`` from an ATHENA vocabulary
download and it verifies, for every mapped concept_id, that the concept:

  * exists in the CONCEPT table,
  * is a standard concept (``standard_concept == 'S'``),
  * has the ``domain_id`` we expect (Condition / Measurement / Visit), and
  * (for coded domains) has a ``concept_code`` equal to the terminology code we
    recorded (SNOMED for conditions, LOINC for measurements).

Why a downloaded file rather than a live API call: ATHENA vocabulary bundles are
license-gated (register, accept per-vocabulary terms, receive a bundle). This
tool runs against that bundle wherever you have it — no network access required
at runtime, so it works in restricted environments.

ATHENA ships ``CONCEPT.csv`` as a tab-delimited file with the standard OMOP CDM
vocabulary columns. Both tab- and comma-delimited files are accepted.

CLI
---
    python -m hipaasynth.vocabulary.validate --concept-csv /path/to/CONCEPT.csv
    python -m hipaasynth.vocabulary.validate --concept-csv CONCEPT.csv --write-status

Exit code is non-zero if any mapping fails validation, so this can gate CI.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .concept_map import _MAP_PATH, _raw_map

# CONCEPT columns we rely on (OMOP CDM vocabulary spec).
_REQUIRED_COLUMNS = {
    "concept_id", "concept_name", "domain_id",
    "vocabulary_id", "standard_concept", "concept_code",
}
# Which recorded terminology code to compare against concept_code, per section.
# Visits carry no terminology code in our map, so their code check is skipped.
_CODE_FIELD_BY_SECTION = {
    "conditions": "snomed_code",
    "measurements": "loinc",
}


@dataclass
class Finding:
    section: str
    source_term: str
    concept_id: Optional[int]
    problem: str

    def __str__(self) -> str:
        cid = self.concept_id if self.concept_id is not None else "?"
        return f"[{self.section}] {self.source_term} (concept_id={cid}): {self.problem}"


def _sniff_delimiter(sample: str) -> str:
    # ATHENA uses tabs; hand-made fixtures often use commas.
    return "\t" if sample.count("\t") >= sample.count(",") else ","


@dataclass
class ConceptTable:
    """An OMOP CONCEPT table indexed for validation.

    ``by_id`` maps concept_id -> row; ``by_code`` maps
    (vocabulary_id, concept_code) -> row, used to resolve medication concept_ids
    from the RxNorm/ATC codes we ship (their concept_id is intentionally null in
    the map).
    """
    by_id: dict
    by_code: dict


def load_concept_table(concept_csv: Path) -> ConceptTable:
    """Load CONCEPT.csv into a :class:`ConceptTable`, keeping needed columns."""
    # utf-8-sig strips a leading BOM if present (common in ATHENA exports that
    # have passed through Excel/Windows tooling) without affecting plain UTF-8
    # files, so the header's first column always reads as "concept_id".
    with open(concept_csv, encoding="utf-8-sig", newline="") as f:
        first_line = f.readline()
        delim = _sniff_delimiter(first_line)
        f.seek(0)
        reader = csv.DictReader(f, delimiter=delim)
        header = set(reader.fieldnames or [])
        missing = _REQUIRED_COLUMNS - header
        if missing:
            raise ValueError(
                f"CONCEPT file {concept_csv} is missing required columns: "
                f"{sorted(missing)}"
            )
        by_id: dict[int, dict] = {}
        by_code: dict[tuple, dict] = {}
        for row in reader:
            try:
                cid = int(row["concept_id"])
            except (TypeError, ValueError):
                continue
            by_id[cid] = row
            vocab = (row.get("vocabulary_id") or "").strip()
            code = (row.get("concept_code") or "").strip()
            if vocab and code:
                by_code[(vocab, code)] = row
    return ConceptTable(by_id=by_id, by_code=by_code)


def _validate_id_sections(table: ConceptTable, findings: list) -> None:
    """Validate conditions/measurements/visits by their recorded concept_id."""
    raw = _raw_map()
    for section in ("conditions", "measurements", "visits"):
        code_field = _CODE_FIELD_BY_SECTION.get(section)
        expected_domain = {"conditions": "Condition",
                           "measurements": "Measurement",
                           "visits": "Visit"}[section]

        for term, entry in raw.get(section, {}).items():
            cid = entry.get("omop_concept_id")
            if cid is None:
                findings.append(Finding(section, term, None, "no omop_concept_id recorded"))
                continue

            row = table.by_id.get(int(cid))
            if row is None:
                findings.append(Finding(section, term, cid, "concept_id not found in CONCEPT table"))
                continue

            if (row.get("standard_concept") or "").strip().upper() != "S":
                findings.append(Finding(
                    section, term, cid,
                    f"not a standard concept (standard_concept="
                    f"{row.get('standard_concept')!r})"))

            actual_domain = (row.get("domain_id") or "").strip()
            if actual_domain != expected_domain:
                findings.append(Finding(
                    section, term, cid,
                    f"domain mismatch: expected {expected_domain}, got {actual_domain!r}"))

            if code_field:
                expected_code = entry.get(code_field)
                actual_code = (row.get("concept_code") or "").strip()
                if expected_code and actual_code and expected_code != actual_code:
                    findings.append(Finding(
                        section, term, cid,
                        f"concept_code mismatch: map says {code_field}="
                        f"{expected_code!r}, CONCEPT says {actual_code!r}"))


def _med_lookups(term: str, entry: dict) -> list:
    """Return the (vocabulary_id, code, expected_standard) checks for a med term.

    An ingredient resolves to one standard RxNorm concept; an ATC class resolves
    to one classification concept; a combination resolves each of its component
    ingredients. ``expected_standard`` is 'S' for standard drug concepts and 'C'
    for ATC classification concepts.
    """
    ctype = entry.get("concept_type")
    if ctype == "rxnorm_ingredient":
        return [("RxNorm", entry.get("rxnorm"), "S")]
    if ctype == "atc_class":
        return [("ATC", entry.get("atc"), "C")]
    if ctype == "combination":
        return [("RxNorm", comp.get("rxnorm"), "S") for comp in entry.get("components", [])]
    return []


def _validate_medications(table: ConceptTable, findings: list) -> None:
    """Validate medications by resolving their RxNorm/ATC codes in CONCEPT.

    Medication concept_ids are null by design; we confirm each code exists in
    the target vocabulary, sits in the Drug domain, and has the expected
    standard/classification flag.
    """
    raw = _raw_map()
    for term, entry in raw.get("medications", {}).items():
        checks = _med_lookups(term, entry)
        if not checks:
            findings.append(Finding("medications", term, None,
                                    f"unknown concept_type {entry.get('concept_type')!r}"))
            continue
        for vocab, code, expected_standard in checks:
            if not code:
                findings.append(Finding("medications", term, None,
                                        f"no {vocab} code recorded"))
                continue
            row = table.by_code.get((vocab, code))
            if row is None:
                findings.append(Finding("medications", term, None,
                                        f"{vocab} code {code!r} not found in CONCEPT table"))
                continue
            actual_domain = (row.get("domain_id") or "").strip()
            if actual_domain != "Drug":
                findings.append(Finding("medications", term, int(row["concept_id"]),
                                        f"domain mismatch: expected Drug, got {actual_domain!r}"))
            actual_standard = (row.get("standard_concept") or "").strip().upper()
            if actual_standard != expected_standard:
                findings.append(Finding("medications", term, int(row["concept_id"]),
                                        f"{vocab} {code} standard_concept expected "
                                        f"{expected_standard!r}, got {actual_standard!r}"))


def validate_map(concept_table: ConceptTable) -> list[Finding]:
    """Return a list of findings; empty means the whole map validated cleanly."""
    findings: list[Finding] = []
    _validate_id_sections(concept_table, findings)
    _validate_medications(concept_table, findings)
    return findings


def resolve_medication_concept_ids(table: ConceptTable) -> dict[str, int]:
    """Resolve each single-concept medication term to its concept_id via code.

    Only ``rxnorm_ingredient`` and ``atc_class`` terms resolve to one concept;
    combinations have no single concept and are skipped. Returns {term:
    concept_id} for those that resolve cleanly.
    """
    raw = _raw_map()
    resolved: dict[str, int] = {}
    for term, entry in raw.get("medications", {}).items():
        if entry.get("concept_type") not in ("rxnorm_ingredient", "atc_class"):
            continue
        checks = _med_lookups(term, entry)
        if len(checks) != 1:
            continue
        vocab, code, _ = checks[0]
        row = table.by_code.get((vocab, code)) if code else None
        if row is not None:
            try:
                resolved[term] = int(row["concept_id"])
            except (TypeError, ValueError, KeyError):
                pass
    return resolved


def write_validated_status(vocabulary_release: str,
                           medication_concept_ids: Optional[dict] = None) -> None:
    """Flip the map metadata to validated against the given ATHENA release.

    If ``medication_concept_ids`` is given, fill each term's resolved
    ``omop_concept_id`` in place — this is how medication concept_ids get
    populated (from their RxNorm/ATC codes) rather than being hand-entered.
    """
    data = json.loads(_MAP_PATH.read_text(encoding="utf-8"))
    data["metadata"]["validation_status"] = "validated"
    data["metadata"]["vocabulary_release"] = vocabulary_release
    if medication_concept_ids:
        meds = data.get("medications", {})
        for term, cid in medication_concept_ids.items():
            if term in meds:
                meds[term]["omop_concept_id"] = cid
    _MAP_PATH.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate the HipAAsynth concept map against an OMOP CONCEPT table.")
    parser.add_argument("--concept-csv", required=True, type=Path,
                        help="Path to ATHENA CONCEPT.csv (tab- or comma-delimited).")
    parser.add_argument("--write-status", action="store_true",
                        help="On success, flip map metadata to validated.")
    parser.add_argument("--release", default=None,
                        help="Vocabulary release label to record with --write-status "
                             "(e.g. 'ATHENA 2026-07'). Defaults to the CONCEPT file's "
                             "parent directory name.")
    args = parser.parse_args(argv)

    if not args.concept_csv.exists():
        print(f"error: CONCEPT file not found: {args.concept_csv}", file=sys.stderr)
        return 2

    table = load_concept_table(args.concept_csv)
    findings = validate_map(table)

    if findings:
        print(f"FAILED: {len(findings)} concept-map validation issue(s):")
        for f in findings:
            print(f"  - {f}")
        return 1

    total = sum(len(_raw_map().get(s, {}))
                for s in ("conditions", "measurements", "visits", "medications"))
    print(f"OK: all {total} mapped concepts validated against {args.concept_csv}")

    if args.write_status:
        release = args.release or args.concept_csv.resolve().parent.name
        resolved = resolve_medication_concept_ids(table)
        write_validated_status(release, resolved)
        print(f"Updated concept_map.json metadata: validation_status=validated, "
              f"vocabulary_release={release!r}")
        if resolved:
            print(f"Resolved {len(resolved)} medication concept_id(s) from RxNorm/ATC codes.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
