#!/usr/bin/env python3
"""
Resolve the concept-map stragglers by NAME against a real ATHENA CONCEPT.csv:
the 10 lab measurements and the single-agent drugs whose curated code was wrong
or absent. Where ``concept_diagnose.py`` looks up by the recorded code, this one
searches by clinical name, so it finds the right concept even when the recorded
code was wrong.

Stdlib only; auto-locates CONCEPT.csv near the working dir (or takes a path).

    python tools/concept_resolve.py [path/to/CONCEPT.csv]
"""
from __future__ import annotations

import csv
import sys
from glob import glob
from pathlib import Path

csv.field_size_limit(2147483647 if sys.maxsize > 2**32 else 2**31 - 1)

# Measurements: (label, required-substrings-all-present). Case-insensitive.
MEAS_QUERIES = [
    ("Glucose",        ["glucose", "serum or plasma"]),
    ("Creatinine",     ["creatinine", "serum or plasma"]),
    ("WBC",            ["leukocytes", "blood"]),
    ("BNP",            ["natriuretic peptide.b"]),
    ("NT-proBNP",      ["natriuretic peptide b prohormone"]),
    ("Troponin I hs",  ["troponin i", "high sensitivity"]),
    ("Sodium",         ["sodium", "serum or plasma"]),
    ("Potassium",      ["potassium", "serum or plasma"]),
    ("Hemoglobin",     ["hemoglobin", "blood"]),
    ("eGFR",           ["glomerular filtration"]),
]
# also try looser fallbacks if the strict query returns nothing
MEAS_FALLBACK = {
    "Glucose": ["glucose"], "Creatinine": ["creatinine"], "WBC": ["leukocytes"],
    "BNP": ["natriuretic peptide"], "NT-proBNP": ["nt-probnp"],
    "Troponin I hs": ["troponin i"], "Sodium": ["sodium"], "Potassium": ["potassium"],
    "Hemoglobin": ["hemoglobin"], "eGFR": ["gfr"],
}
# Single-agent drugs to resolve by ingredient name.
DRUG_NAMES = ["ivabradine", "roflumilast", "nusinersen", "risdiplam",
              "onasemnogene"]


def find_concept_csv() -> Path:
    for root in (Path.cwd(), Path.cwd().parent):
        hits = glob(str(root / "**" / "CONCEPT.csv"), recursive=True)
        hits.sort(key=lambda p: ("Encrypted" in p, "vocabulary_download" not in p))
        if hits:
            return Path(hits[0])
    sys.exit("error: no CONCEPT.csv found; pass the path explicitly.")


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    path = Path(argv[0]) if argv else find_concept_csv()
    if not path.exists():
        sys.exit(f"error: not found: {path}")

    meas_hits = {lbl: [] for lbl, _ in MEAS_QUERIES}
    meas_fallback_hits = {lbl: [] for lbl in MEAS_FALLBACK}
    drug_hits = {d: [] for d in DRUG_NAMES}

    # utf-8-sig strips a leading BOM if present (common in ATHENA exports that
    # have passed through Excel/Windows tooling); a no-op otherwise.
    with open(path, encoding="utf-8-sig", newline="") as f:
        delim = "\t" if f.readline().count("\t") >= 1 else ","
        f.seek(0)
        # Tab-delimited ATHENA CONCEPT.csv is unquoted but concept_name values
        # carry bare double-quotes; default quoting turns those into runaway
        # fields that swallow subsequent rows (see validate.py for the same fix).
        quoting = csv.QUOTE_NONE if delim == "\t" else csv.QUOTE_MINIMAL
        for row in csv.DictReader(f, delimiter=delim, quoting=quoting):
            name = (row.get("concept_name") or "")
            low = name.lower()
            dom = (row.get("domain_id") or "").strip()
            vocab = (row.get("vocabulary_id") or "").strip()
            std = (row.get("standard_concept") or "").strip()
            cclass = (row.get("concept_class_id") or "").strip()
            if dom == "Measurement" and vocab == "LOINC" and std == "S":
                for lbl, subs in MEAS_QUERIES:
                    if all(s.replace(".", " ") in low or s in low for s in subs):
                        if len(meas_hits[lbl]) < 6:
                            meas_hits[lbl].append((row.get("concept_id"), name, row.get("concept_code")))
                for lbl, subs in MEAS_FALLBACK.items():
                    if all(s in low for s in subs) and len(meas_fallback_hits[lbl]) < 8:
                        meas_fallback_hits[lbl].append((row.get("concept_id"), name, row.get("concept_code")))
            if dom == "Drug" and vocab == "RxNorm":
                for d in DRUG_NAMES:
                    # always keep ingredient-level rows; cap only the drug-product noise
                    is_ingr = cclass in ("Ingredient", "Precise Ingredient")
                    if d in low and (is_ingr or len(drug_hits[d]) < 12):
                        drug_hits[d].append((row.get("concept_id"), name, cclass, std, row.get("concept_code")))

    print(f"\nCONCEPT.csv : {path}")
    print("\n===== MEASUREMENTS by name (standard LOINC Measurement concepts) =====")
    for lbl, _ in MEAS_QUERIES:
        print(f"\n [{lbl}] strict:")
        for cid, nm, code in meas_hits[lbl]:
            print(f"    id={cid} code={code} {nm!r}")
        if not meas_hits[lbl]:
            print("    (none strict) fallback:")
            for cid, nm, code in meas_fallback_hits.get(lbl, [])[:8]:
                print(f"    id={cid} code={code} {nm!r}")

    print("\n===== SINGLE-AGENT DRUGS by ingredient name =====")
    for d in DRUG_NAMES:
        print(f"\n [{d}]:")
        ingr = [h for h in drug_hits[d] if h[2] in ("Ingredient", "Precise Ingredient")]
        show = ingr if ingr else drug_hits[d]
        for cid, nm, cclass, std, code in show[:8]:
            print(f"    id={cid} code={code} class={cclass} std={std!r} {nm!r}")
        if not drug_hits[d]:
            print("    <no RxNorm concept with that name — not in this release>")

    print("\nDONE — send this whole output back.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
