#!/usr/bin/env python3
"""
Standalone extractor: pull the ~65 rows HipAAsynth needs out of a full ATHENA
CONCEPT.csv, so the concept-map validation can be completed without shipping the
whole (multi-GB, license-gated) vocabulary bundle anywhere.

This file is intentionally self-contained: stdlib only, no HipAAsynth import, no
dependencies. Run it wherever you unpacked your ATHENA download.

    python athena_extract.py /path/to/CONCEPT.csv

It writes ``concept_subset.csv`` next to this script: the CONCEPT header plus
only the rows whose concept_id, or (vocabulary_id, concept_code), are referenced
by the HipAAsynth concept map. That small file is a valid CONCEPT.csv (same
columns, fewer rows) and feeds straight into:

    python -m hipaasynth.vocabulary.validate --concept-csv concept_subset.csv

ATHENA ships CONCEPT.csv tab-delimited; comma-delimited files are also accepted.
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

# concept_ids referenced by the conditions/measurements/visits sections.
WANTED_IDS = {
    722455, 9201, 9202, 9203, 132797, 201826, 255573, 313217, 319835, 316866,
    317009, 317576, 321052, 381316, 432867, 439777, 440383, 313459, 3000905,
    3000963, 3004501, 3011960, 3016407, 3016723, 3019550, 3023103, 3028288,
    3049187, 194984, 4329847, 42529224, 46271022,
}

# (vocabulary_id, concept_code) pairs referenced by the medications section,
# whose concept_id is resolved from the code (RxNorm ingredients, ATC classes).
WANTED_CODES = {
    ("ATC", "A10A"), ("ATC", "A10BB"), ("ATC", "A10BH"), ("ATC", "A10BJ"),
    ("ATC", "A10BK"), ("ATC", "B01A"), ("ATC", "C03A"), ("ATC", "C03C"),
    ("ATC", "C03DA"), ("ATC", "C07"), ("ATC", "C08"), ("ATC", "C09"),
    ("ATC", "C09A"), ("ATC", "C09C"), ("ATC", "C10AA"), ("ATC", "H02AB"),
    ("ATC", "R03AC"), ("ATC", "R03AK"), ("ATC", "R03AL"), ("ATC", "R03BB"),
    ("RxNorm", "1091652"), ("RxNorm", "1191"), ("RxNorm", "1649480"),
    ("RxNorm", "1819"), ("RxNorm", "1863556"), ("RxNorm", "2358846"),
    ("RxNorm", "2390935"), ("RxNorm", "3407"), ("RxNorm", "5470"),
    ("RxNorm", "6058"), ("RxNorm", "6809"), ("RxNorm", "6813"), ("RxNorm", "7243"),
}


def _sniff_delimiter(sample: str) -> str:
    return "\t" if sample.count("\t") >= sample.count(",") else ","


def extract(concept_csv: Path, out_csv: Path) -> tuple[int, int]:
    """Write matching rows to out_csv. Returns (rows_written, rows_scanned)."""
    with open(concept_csv, encoding="utf-8", newline="") as f:
        first = f.readline()
        delim = _sniff_delimiter(first)
        f.seek(0)
        reader = csv.DictReader(f, delimiter=delim)
        fields = reader.fieldnames or []
        for required in ("concept_id", "vocabulary_id", "concept_code"):
            if required not in fields:
                raise SystemExit(
                    f"error: {concept_csv} has no '{required}' column; is this an "
                    f"ATHENA CONCEPT.csv? Found columns: {fields}")

        written = scanned = 0
        with open(out_csv, "w", encoding="utf-8", newline="") as out:
            writer = csv.DictWriter(out, fieldnames=fields, delimiter="\t")
            writer.writeheader()
            for row in reader:
                scanned += 1
                keep = False
                try:
                    if int(row["concept_id"]) in WANTED_IDS:
                        keep = True
                except (TypeError, ValueError):
                    pass
                if not keep:
                    pair = ((row.get("vocabulary_id") or "").strip(),
                            (row.get("concept_code") or "").strip())
                    if pair in WANTED_CODES:
                        keep = True
                if keep:
                    writer.writerow(row)
                    written += 1
    return written, scanned


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print(__doc__)
        print("usage: python athena_extract.py /path/to/CONCEPT.csv", file=sys.stderr)
        return 2
    concept_csv = Path(argv[0])
    if not concept_csv.exists():
        print(f"error: file not found: {concept_csv}", file=sys.stderr)
        return 2

    out_csv = Path(__file__).with_name("concept_subset.csv")
    written, scanned = extract(concept_csv, out_csv)
    expected = len(WANTED_IDS) + len(WANTED_CODES)
    print(f"scanned {scanned:,} CONCEPT rows")
    print(f"wrote {written} matching row(s) -> {out_csv}")
    if written < expected:
        print(f"NOTE: expected up to {expected} rows but found {written}. "
              f"Missing rows usually mean a vocabulary (SNOMED / LOINC / RxNorm / "
              f"ATC) was not included in this ATHENA download.")
    print("\nSend concept_subset.csv back, or validate it directly with:")
    print("  python -m hipaasynth.vocabulary.validate --concept-csv "
          f"{out_csv.name} --write-status --release \"ATHENA <date>\"")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
