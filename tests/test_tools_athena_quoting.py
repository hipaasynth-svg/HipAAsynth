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

"""Guard the bare-double-quote fix in the ATHENA CLI tools.

Real ATHENA CONCEPT.csv is tab-delimited and unquoted, but some concept_name
values start with a bare double-quote (e.g. inch marks). With default csv
quoting a leading quote opens a field that never closes, swallowing every row
after it into one giant field. hipaasynth/vocabulary/validate.py was fixed for
this (#77); these tools scan the same real, full ATHENA file and need the same
fix (QUOTE_NONE for tab-delimited input).
"""

from pathlib import Path

from tools import athena_extract, concept_diagnose, concept_resolve

_COLUMNS = [
    "concept_id", "concept_name", "domain_id", "vocabulary_id",
    "concept_class_id", "standard_concept", "concept_code",
    "valid_start_date", "valid_end_date", "invalid_reason",
]


def _write_tsv_with_bare_leading_quote(path: Path) -> None:
    # Row 1's concept_name starts with an unmatched bare double-quote, the
    # exact shape that triggers the runaway-field bug on tab-delimited input.
    rows = [
        _COLUMNS,
        ["1", '"6 tube', "Device", "SNOMED", "X", "S", "CODE1",
         "20000101", "20991231", ""],
        ["2", "Normal saline", "Drug", "RxNorm", "Y", "S", "CODE2",
         "20000101", "20991231", ""],
        ["3", "Troponin I.cardiac [Mass/volume] in Serum or Plasma by "
              "High sensitivity method", "Measurement", "LOINC", "Z", "S",
         "89579-7", "20000101", "20991231", ""],
    ]
    with open(path, "w", encoding="utf-8", newline="") as f:
        for row in rows:
            f.write("\t".join(row) + "\r\n")


def test_athena_extract_scans_all_rows_past_bare_quote(tmp_path):
    src = tmp_path / "CONCEPT.csv"
    _write_tsv_with_bare_leading_quote(src)
    out = tmp_path / "concept_subset.csv"
    athena_extract.WANTED_IDS.add(2)
    try:
        written, scanned = athena_extract.extract(src, out)
    finally:
        athena_extract.WANTED_IDS.discard(2)
    assert scanned == 3


def test_concept_diagnose_indexes_all_rows_past_bare_quote(tmp_path):
    src = tmp_path / "CONCEPT.csv"
    _write_tsv_with_bare_leading_quote(src)
    _, by_id, _, _ = concept_diagnose.load_concept(src)
    assert set(by_id) == {1, 2, 3}


def test_concept_resolve_finds_rows_past_bare_quote(tmp_path, capsys):
    src = tmp_path / "CONCEPT.csv"
    _write_tsv_with_bare_leading_quote(src)
    rc = concept_resolve.main([str(src)])
    assert rc == 0
    # Row 3 (Troponin I hs, LOINC 89579-7) comes after the bare-quote row; if
    # it were swallowed by a runaway field, this match would never print.
    out = capsys.readouterr().out
    assert "89579-7" in out
