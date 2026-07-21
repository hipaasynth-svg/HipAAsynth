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

"""Tests for the concept-map validator (validate.py).

We can't reach ATHENA from CI, so these build a tiny synthetic CONCEPT table in
the OMOP column layout and prove the validator both passes a correct map and
catches each class of defect.
"""

import csv

import pytest

from hipaasynth.vocabulary import concept_map
from hipaasynth.vocabulary.validate import (
    load_concept_table,
    validate_map,
    main,
)

_CONCEPT_COLUMNS = [
    "concept_id", "concept_name", "domain_id", "vocabulary_id",
    "concept_class_id", "standard_concept", "concept_code",
    "valid_start_date", "valid_end_date", "invalid_reason",
]


def _row(concept_id, name, domain, vocab, code, standard="S"):
    return {
        "concept_id": concept_id, "concept_name": name, "domain_id": domain,
        "vocabulary_id": vocab, "concept_class_id": "Clinical Finding",
        "standard_concept": standard, "concept_code": code,
        "valid_start_date": "20000101", "valid_end_date": "20991231",
        "invalid_reason": "",
    }


def _build_concept_csv(path, rows, delimiter="\t"):
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=_CONCEPT_COLUMNS, delimiter=delimiter)
        writer.writeheader()
        for r in rows:
            writer.writerow(r)


def _full_valid_table():
    """A CONCEPT row for every concept_id in the shipped map, all correct."""
    raw = concept_map._raw_map()
    rows = []
    seen = set()
    for section, domain in (("conditions", "Condition"),
                            ("measurements", "Measurement"),
                            ("visits", "Visit")):
        for term, entry in raw[section].items():
            cid = entry["omop_concept_id"]
            if cid in seen:
                continue
            seen.add(cid)
            if section == "conditions":
                vocab, code = "SNOMED", entry["snomed_code"]
            elif section == "measurements":
                vocab, code = "LOINC", entry["loinc"]
            else:
                vocab, code = "Visit", "OP"
            rows.append(_row(cid, entry.get("omop_concept_name", term), domain, vocab, code))
    return rows


def test_full_map_validates_against_correct_table(tmp_path):
    path = tmp_path / "CONCEPT.csv"
    _build_concept_csv(path, _full_valid_table())
    table = load_concept_table(path)
    findings = validate_map(table)
    assert findings == [], "\n".join(str(f) for f in findings)


def test_detects_missing_concept(tmp_path):
    rows = [r for r in _full_valid_table() if int(r["concept_id"]) != 316139]
    path = tmp_path / "CONCEPT.csv"
    _build_concept_csv(path, rows)
    findings = validate_map(load_concept_table(path))
    assert any("not found" in f.problem and f.concept_id == 316139 for f in findings)


def test_detects_non_standard_concept(tmp_path):
    rows = _full_valid_table()
    for r in rows:
        if int(r["concept_id"]) == 316139:
            r["standard_concept"] = ""  # non-standard
    path = tmp_path / "CONCEPT.csv"
    _build_concept_csv(path, rows)
    findings = validate_map(load_concept_table(path))
    assert any("not a standard concept" in f.problem for f in findings)


def test_detects_domain_mismatch(tmp_path):
    rows = _full_valid_table()
    for r in rows:
        if int(r["concept_id"]) == 316139:
            r["domain_id"] = "Measurement"  # wrong domain for a condition
    path = tmp_path / "CONCEPT.csv"
    _build_concept_csv(path, rows)
    findings = validate_map(load_concept_table(path))
    assert any("domain mismatch" in f.problem for f in findings)


def test_detects_code_mismatch(tmp_path):
    rows = _full_valid_table()
    for r in rows:
        if int(r["concept_id"]) == 316139:
            r["concept_code"] = "99999999"  # wrong SNOMED code
    path = tmp_path / "CONCEPT.csv"
    _build_concept_csv(path, rows)
    findings = validate_map(load_concept_table(path))
    assert any("concept_code mismatch" in f.problem for f in findings)


def test_comma_delimited_is_accepted(tmp_path):
    path = tmp_path / "CONCEPT.csv"
    _build_concept_csv(path, _full_valid_table(), delimiter=",")
    findings = validate_map(load_concept_table(path))
    assert findings == []


def test_missing_required_columns_raises(tmp_path):
    path = tmp_path / "bad.csv"
    with open(path, "w", newline="", encoding="utf-8") as f:
        f.write("concept_id\tconcept_name\n1\tfoo\n")
    with pytest.raises(ValueError):
        load_concept_table(path)


def test_cli_returns_zero_on_success(tmp_path, capsys):
    path = tmp_path / "CONCEPT.csv"
    _build_concept_csv(path, _full_valid_table())
    rc = main(["--concept-csv", str(path)])
    assert rc == 0
    assert "OK: all" in capsys.readouterr().out


def test_cli_returns_one_on_failure(tmp_path):
    rows = [r for r in _full_valid_table() if int(r["concept_id"]) != 316139]
    path = tmp_path / "CONCEPT.csv"
    _build_concept_csv(path, rows)
    assert main(["--concept-csv", str(path)]) == 1


def test_cli_missing_file_returns_two(tmp_path):
    assert main(["--concept-csv", str(tmp_path / "nope.csv")]) == 2


def test_write_status_flips_metadata(tmp_path, monkeypatch):
    # Redirect the map path to a temp copy so we don't mutate the shipped file.
    import json
    original = concept_map._raw_map()
    temp_map = tmp_path / "concept_map.json"
    temp_map.write_text(json.dumps(original, indent=2), encoding="utf-8")

    from hipaasynth.vocabulary import validate as validate_mod
    monkeypatch.setattr(validate_mod, "_MAP_PATH", temp_map)

    concept_csv = tmp_path / "CONCEPT.csv"
    _build_concept_csv(concept_csv, _full_valid_table())
    rc = main(["--concept-csv", str(concept_csv), "--write-status", "--release", "ATHENA 2026-07"])
    assert rc == 0
    updated = json.loads(temp_map.read_text())
    assert updated["metadata"]["validation_status"] == "validated"
    assert updated["metadata"]["vocabulary_release"] == "ATHENA 2026-07"
