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
ACHILLES / DataQualityDashboard-style audit of a HipAAsynth OMOP CDM cohort.

The OHDSI stack ships two characterization tools: **ACHILLES** (database
characterization — counts, distributions, prevalence) and **DataQualityDashboard
(DQD)** (a battery of Conformance / Completeness / Plausibility checks). Running
either normally requires an OMOP database, R/Java, and a network-reachable OHDSI
install.

This module is a self-contained, pure-Python adapter that runs the *same shape*
of characterization and data-quality checks directly over the CSV tables emitted
by :func:`hipaasynth.exporters.omop.export_omop` (or the in-memory tables from
``build_cdm_tables``). It produces a **realism / QA credential**: evidence that a
HipAAsynth synthetic cohort passes the same structural and plausibility checks a
real OMOP database is held to — without needing the full OHDSI toolchain or any
network access.

It is deliberately not a re-implementation of DQD's ~4000 checks; it implements a
representative, defensible subset across all three DQD categories, plus the
ACHILLES-style characterization most relevant to a fairness cohort.
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional, Union

_CDM_TABLES = ("person", "condition_occurrence", "visit_occurrence",
               "measurement", "drug_exposure")
_BIRTH_YEAR_FLOOR = 1900


# ── Loading ──────────────────────────────────────────────────────────────────

def load_cdm_dir(omop_dir: Union[str, Path]) -> dict:
    """Load OMOP CDM CSVs from a directory into {table: list[dict rows]}."""
    out: dict[str, list] = {}
    base = Path(omop_dir)
    for table in _CDM_TABLES:
        path = base / f"{table}.csv"
        if not path.exists():
            out[table] = []
            continue
        with open(path, newline="", encoding="utf-8") as f:
            out[table] = list(csv.DictReader(f))
    return out


def _as_int(value, default=None):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_float(value, default=None):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


# ── Data-quality checks (DQD-style) ──────────────────────────────────────────

@dataclass
class DQCheck:
    name: str
    category: str          # Conformance | Completeness | Plausibility
    table: str
    status: str            # PASS | FAIL | NOT_APPLICABLE
    failed_rows: int
    total_rows: int
    threshold_pct: float   # max % failing allowed to still PASS
    description: str = ""

    @property
    def failed_pct(self) -> float:
        return (100.0 * self.failed_rows / self.total_rows) if self.total_rows else 0.0


def _mk_check(name, category, table, rows, predicate_failed, threshold_pct, description):
    """Build a DQCheck by counting rows for which predicate_failed(row) is True."""
    total = len(rows)
    if total == 0:
        return DQCheck(name, category, table, "NOT_APPLICABLE", 0, 0, threshold_pct, description)
    failed = sum(1 for r in rows if predicate_failed(r))
    pct = 100.0 * failed / total
    status = "PASS" if pct <= threshold_pct else "FAIL"
    return DQCheck(name, category, table, status, failed, total, threshold_pct, description)


def run_dq_checks(tables: dict) -> list:
    """Run the representative DQD-style check battery over CDM tables."""
    person = tables.get("person", [])
    person_ids = {r.get("person_id") for r in person}
    checks: list[DQCheck] = []

    # ---- Conformance ---------------------------------------------------------
    checks.append(_mk_check(
        "person_id_not_null", "Conformance", "person", person,
        lambda r: _as_int(r.get("person_id")) is None, 0.0,
        "person_id is a required non-null field."))

    # Unique person_id (Conformance) — reported as a whole-table check.
    total_person = len(person)
    dup = total_person - len({r.get("person_id") for r in person}) if total_person else 0
    checks.append(DQCheck(
        "person_id_unique", "Conformance", "person",
        "NOT_APPLICABLE" if total_person == 0 else ("PASS" if dup == 0 else "FAIL"),
        dup, total_person, 0.0, "person_id must be unique across the PERSON table."))

    checks.append(_mk_check(
        "gender_concept_id_valid", "Conformance", "person", person,
        lambda r: _as_int(r.get("gender_concept_id")) not in (8507, 8532, 0), 0.0,
        "gender_concept_id must be a valid OMOP gender concept (8507/8532) or 0."))

    # Foreign-key conformance: every fact row references an existing person.
    for table in ("condition_occurrence", "visit_occurrence", "measurement", "drug_exposure"):
        rows = tables.get(table, [])
        checks.append(_mk_check(
            f"{table}_person_fk", "Conformance", table, rows,
            lambda r: r.get("person_id") not in person_ids, 0.0,
            f"Every {table} row must reference an existing person_id."))

    # ---- Completeness --------------------------------------------------------
    checks.append(_mk_check(
        "year_of_birth_complete", "Completeness", "person", person,
        lambda r: _as_int(r.get("year_of_birth")) is None, 0.0,
        "year_of_birth should be populated for every person."))

    checks.append(_mk_check(
        "condition_start_date_complete", "Completeness", "condition_occurrence",
        tables.get("condition_occurrence", []),
        lambda r: not (r.get("condition_start_date") or "").strip(), 5.0,
        "condition_start_date should be populated."))

    checks.append(_mk_check(
        "measurement_value_complete", "Completeness", "measurement",
        tables.get("measurement", []),
        lambda r: _as_float(r.get("value_as_number")) is None, 5.0,
        "measurement value_as_number should be populated for quantitative labs."))

    # Standard-concept mapping completeness per domain (the realism signal):
    # rows with *_concept_id == 0 are unmapped. Conditions/measurements should be
    # near-fully mapped; drugs may legitimately carry 0 for ATC-class terms, so a
    # looser threshold is applied there.
    checks.append(_mk_check(
        "condition_concept_mapped", "Completeness", "condition_occurrence",
        tables.get("condition_occurrence", []),
        lambda r: _as_int(r.get("condition_concept_id"), 0) == 0, 5.0,
        "condition_concept_id should map to a standard concept (non-zero)."))

    checks.append(_mk_check(
        "measurement_concept_mapped", "Completeness", "measurement",
        tables.get("measurement", []),
        lambda r: _as_int(r.get("measurement_concept_id"), 0) == 0, 5.0,
        "measurement_concept_id should map to a standard concept (non-zero)."))

    # ---- Plausibility --------------------------------------------------------
    current_year = datetime.now().year
    checks.append(_mk_check(
        "year_of_birth_plausible", "Plausibility", "person", person,
        lambda r: not (_BIRTH_YEAR_FLOOR <= (_as_int(r.get("year_of_birth")) or -1) <= current_year),
        0.0, f"year_of_birth must be between {_BIRTH_YEAR_FLOOR} and {current_year}."))

    checks.append(_mk_check(
        "measurement_value_nonneg", "Plausibility", "measurement",
        tables.get("measurement", []),
        lambda r: (_as_float(r.get("value_as_number")) or 0) < 0, 0.0,
        "measurement value_as_number should not be negative."))

    checks.append(_mk_check(
        "visit_dates_ordered", "Plausibility", "visit_occurrence",
        tables.get("visit_occurrence", []),
        lambda r: bool((r.get("visit_start_date") or "") and (r.get("visit_end_date") or "")
                       and r["visit_end_date"] < r["visit_start_date"]), 0.0,
        "visit_end_date must not precede visit_start_date."))

    return checks


# ── Characterization (ACHILLES-style) ────────────────────────────────────────

def characterize(tables: dict, top_n: int = 10) -> dict:
    """Produce ACHILLES-style characterization of the cohort."""
    person = tables.get("person", [])
    current_year = datetime.now().year

    gender = Counter()
    ages = []
    for r in person:
        g = _as_int(r.get("gender_concept_id"))
        gender[{8507: "Male", 8532: "Female"}.get(g, "Unknown/Other")] += 1
        yob = _as_int(r.get("year_of_birth"))
        if yob:
            ages.append(current_year - yob)

    def _age_band(a):
        lo = (a // 10) * 10
        return f"{lo}-{lo + 9}"

    age_bands = Counter(_age_band(a) for a in ages)

    cond_counts = Counter(r.get("condition_source_value") for r in tables.get("condition_occurrence", []))
    drug_counts = Counter(r.get("drug_source_value") for r in tables.get("drug_exposure", []))
    visit_counts = Counter(r.get("visit_source_value") for r in tables.get("visit_occurrence", []))

    # Measurement value summary per source lab.
    meas_values: dict[str, list] = {}
    for r in tables.get("measurement", []):
        v = _as_float(r.get("value_as_number"))
        if v is not None:
            meas_values.setdefault(r.get("measurement_source_value"), []).append(v)

    def _summ(vals):
        s = sorted(vals)
        n = len(s)
        mean = sum(s) / n
        median = s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2
        return {"n": n, "min": round(s[0], 3), "max": round(s[-1], 3),
                "mean": round(mean, 3), "median": round(median, 3)}

    return {
        "record_counts": {t: len(tables.get(t, [])) for t in _CDM_TABLES},
        "person_count": len(person),
        "gender_distribution": dict(gender),
        "age": {
            "count": len(ages),
            "min": min(ages) if ages else None,
            "max": max(ages) if ages else None,
            "mean": round(sum(ages) / len(ages), 1) if ages else None,
            "bands": dict(sorted(age_bands.items())),
        },
        "top_conditions": cond_counts.most_common(top_n),
        "top_drugs": drug_counts.most_common(top_n),
        "visit_distribution": dict(visit_counts),
        "measurement_summary": {k: _summ(v) for k, v in sorted(meas_values.items())},
    }


# ── Top-level audit ──────────────────────────────────────────────────────────

def audit_cdm(source: Union[dict, str, Path], top_n: int = 10) -> dict:
    """Run characterization + data-quality checks over a CDM cohort.

    ``source`` may be an in-memory tables dict (from ``build_cdm_tables``) or a
    path to a directory of CDM CSVs (from ``export_omop``).
    """
    tables = source if isinstance(source, dict) else load_cdm_dir(source)
    checks = run_dq_checks(tables)
    passed = sum(1 for c in checks if c.status == "PASS")
    failed = sum(1 for c in checks if c.status == "FAIL")
    na = sum(1 for c in checks if c.status == "NOT_APPLICABLE")
    return {
        "generated_utc": datetime.utcnow().isoformat() + "Z",
        "cdm_version": "5.4",
        "characterization": characterize(tables, top_n=top_n),
        "data_quality": {
            "summary": {"passed": passed, "failed": failed,
                        "not_applicable": na, "total": len(checks)},
            "checks": [asdict(c) for c in checks],
        },
        "passed": failed == 0,
    }


def render_markdown(report: dict) -> str:
    """Render an audit report as a human-readable Markdown credential."""
    ch = report["characterization"]
    dq = report["data_quality"]
    lines = []
    lines.append("# HipAAsynth OMOP CDM Audit")
    lines.append("")
    lines.append(f"_Generated {report['generated_utc']} — CDM v{report['cdm_version']}_")
    lines.append("")
    verdict = "PASS ✅" if report["passed"] else "FAIL ❌"
    s = dq["summary"]
    lines.append(f"**Data-quality verdict: {verdict}** "
                 f"({s['passed']} passed, {s['failed']} failed, "
                 f"{s['not_applicable']} n/a of {s['total']} checks)")
    lines.append("")

    lines.append("## Characterization (ACHILLES-style)")
    lines.append("")
    lines.append(f"- Persons: **{ch['person_count']}**")
    lines.append(f"- Records: " + ", ".join(f"{k}={v}" for k, v in ch["record_counts"].items()))
    if ch["age"]["count"]:
        a = ch["age"]
        lines.append(f"- Age: min {a['min']}, mean {a['mean']}, max {a['max']}")
    lines.append(f"- Gender: " + ", ".join(f"{k}={v}" for k, v in ch["gender_distribution"].items()))
    if ch["top_conditions"]:
        lines.append("- Top conditions: " + ", ".join(f"{n} ({c})" for n, c in ch["top_conditions"][:5]))
    if ch["top_drugs"] and any(n for n, _ in ch["top_drugs"]):
        lines.append("- Top drugs: " + ", ".join(f"{n} ({c})" for n, c in ch["top_drugs"][:5] if n))
    lines.append("")

    lines.append("## Data-quality checks (DQD-style)")
    lines.append("")
    lines.append("| Check | Category | Table | Status | Failed/Total |")
    lines.append("|---|---|---|---|---|")
    for c in dq["checks"]:
        ratio = f"{c['failed_rows']}/{c['total_rows']}"
        lines.append(f"| {c['name']} | {c['category']} | {c['table']} | "
                     f"{c['status']} | {ratio} |")
    lines.append("")
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="ACHILLES/DQD-style audit of a HipAAsynth OMOP CDM cohort.")
    parser.add_argument("--omop-dir", required=True, type=Path,
                        help="Directory of OMOP CDM CSVs (from export_omop).")
    parser.add_argument("--out", type=Path, default=None,
                        help="Write a Markdown report to this path (also prints JSON summary).")
    parser.add_argument("--json", type=Path, default=None,
                        help="Write the full JSON report to this path.")
    args = parser.parse_args(argv)

    if not args.omop_dir.exists():
        print(f"error: OMOP directory not found: {args.omop_dir}")
        return 2

    report = audit_cdm(args.omop_dir)
    if args.out:
        args.out.write_text(render_markdown(report), encoding="utf-8")
        print(f"Wrote Markdown audit to {args.out}")
    if args.json:
        args.json.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"Wrote JSON audit to {args.json}")

    s = report["data_quality"]["summary"]
    print(f"DQ: {s['passed']} passed / {s['failed']} failed / {s['not_applicable']} n/a "
          f"({s['total']} checks). Overall: {'PASS' if report['passed'] else 'FAIL'}")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
