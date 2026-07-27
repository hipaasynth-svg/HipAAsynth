#!/usr/bin/env python3
"""
Reconcile the HipAAsynth concept map against a real ATHENA CONCEPT.csv and report,
for every mapping, the authoritative concept the stable code resolves to — so the
curated ``omop_concept_id`` values can be corrected where they drifted.

This is the companion to ``hipaasynth.vocabulary.validate``: where the validator
says *whether* a mapping is right, this says *what the right answer is*. It keys
off the stable terminology codes (SNOMED / LOINC / RxNorm / ATC) that don't drift
between releases, and prints the concept_id/name/domain/standard flag each code
actually carries in the bundle.

Stdlib only; no HipAAsynth import. It finds ``concept_map.json`` next to the repo
and, if you don't pass a path, auto-locates ``CONCEPT.csv`` under the folders near
the current directory.

    python tools/concept_diagnose.py [path/to/CONCEPT.csv]
"""
from __future__ import annotations

import csv
import json
import sys
from glob import glob
from pathlib import Path

csv.field_size_limit(2147483647 if sys.maxsize > 2**32 else 2**31 - 1)


def find_map() -> Path:
    here = Path(__file__).resolve()
    for cand in (Path.cwd() / "hipaasynth" / "vocabulary" / "concept_map.json",
                 here.parent.parent / "hipaasynth" / "vocabulary" / "concept_map.json"):
        if cand.exists():
            return cand
    hits = glob(str(Path.cwd() / "**" / "concept_map.json"), recursive=True)
    if hits:
        return Path(hits[0])
    sys.exit("error: could not locate hipaasynth/vocabulary/concept_map.json "
             "(run this from the repo root).")


def find_concept_csv() -> Path:
    roots = [Path.cwd(), Path.cwd().parent]
    for root in roots:
        hits = glob(str(root / "**" / "CONCEPT.csv"), recursive=True)
        # prefer a real ATHENA bundle folder, and a non-'Encrypted' copy
        hits.sort(key=lambda p: ("Encrypted" in p, "vocabulary_download" not in p))
        if hits:
            return Path(hits[0])
    sys.exit("error: no CONCEPT.csv found near this folder. Pass the path "
             "explicitly:  python tools/concept_diagnose.py C:\\path\\to\\CONCEPT.csv")


def load_concept(path: Path):
    vc: dict[str, int] = {}
    by_id: dict[int, dict] = {}
    by_code: dict[tuple, dict] = {}
    visit_names: list[tuple] = []
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
            v = (row.get("vocabulary_id") or "").strip()
            vc[v] = vc.get(v, 0) + 1
            try:
                cid = int(row["concept_id"])
            except (TypeError, ValueError):
                continue
            by_id[cid] = row
            code = (row.get("concept_code") or "").strip()
            if v and code:
                by_code[(v, code)] = row
            if (row.get("domain_id") or "").strip() == "Visit":
                visit_names.append((cid, row.get("concept_name") or "", code,
                                    row.get("standard_concept")))
    return vc, by_id, by_code, visit_names


def fmt(r) -> str:
    if not r:
        return "<not in CONCEPT table>"
    return ("id=%s name=%r domain=%s std=%r vocab=%s code=%s"
            % (r.get("concept_id"), r.get("concept_name"), r.get("domain_id"),
               r.get("standard_concept"), r.get("vocabulary_id"),
               r.get("concept_code")))


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    concept_csv = Path(argv[0]) if argv else find_concept_csv()
    if not concept_csv.exists():
        sys.exit(f"error: CONCEPT.csv not found: {concept_csv}")
    m = json.loads(find_map().read_text(encoding="utf-8"))
    vc, by_id, by_code, visit_names = load_concept(concept_csv)

    print(f"\nCONCEPT.csv : {concept_csv}")
    print("\n===== VOCABULARY ROW COUNTS =====")
    for v in ("SNOMED", "LOINC", "RxNorm", "ATC", "Visit"):
        print("  %-8s %s" % (v, "{:,} rows".format(vc[v]) if vc.get(v) else "MISSING"))

    print("\n===== CONDITIONS  (my concept_id  vs  the concept carrying my SNOMED code) =====")
    for t, e in m.get("conditions", {}).items():
        cid, code = e.get("omop_concept_id"), e.get("snomed_code")
        print(f" [{t}]")
        print("   my id   ->", fmt(by_id.get(int(cid)) if cid else None))
        print("   my code ->", fmt(by_code.get(("SNOMED", str(code))) if code else None))

    print("\n===== MEASUREMENTS  (correct concept_id = the one carrying my LOINC code) =====")
    for t, e in m.get("measurements", {}).items():
        cid, code = e.get("omop_concept_id"), e.get("loinc")
        print(f" [{t}] my id {cid}, loinc {code} -> "
              + fmt(by_code.get(("LOINC", str(code))) if code else None))

    print("\n===== VISITS =====")
    for t, e in m.get("visits", {}).items():
        cid = e.get("omop_concept_id")
        print(f" [{t}] my id {cid} -> " + fmt(by_id.get(int(cid)) if cid else None))
        if cid and int(cid) not in by_id:
            kw = t.split("_")[0].lower()
            cands = [c for c in visit_names if kw in c[1].lower()][:8]
            for c in cands:
                print("     candidate: id=%s %r code=%s std=%r" % c)

    print("\n===== MEDICATIONS =====")
    for t, e in m.get("medications", {}).items():
        ct = e.get("concept_type")
        checks = []
        if ct == "rxnorm_ingredient":
            checks = [("RxNorm", e.get("rxnorm"))]
        elif ct == "atc_class":
            checks = [("ATC", e.get("atc"))]
        elif ct == "combination":
            checks = [("RxNorm", c.get("rxnorm")) for c in e.get("components", [])]
        for vocab, ccode in checks:
            print(f" [{t}] {vocab} {ccode} -> "
                  + fmt(by_code.get((vocab, str(ccode))) if ccode else None))

    print("\nDONE — send this whole output back.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
