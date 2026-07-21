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
HipAAsynth — Source-aware calibration verifier
================================================
Reads calibration targets from an EXTERNAL targets file (e.g. copd_targets.json)
rather than from the generator's own constants, so a passing check is a claim
about a cited reference — not a tautology against the sampler's inputs.

Two things it reports, separately:
  1. PROVENANCE STATUS of every target (confirmed / value_mismatch /
     citation_mismatch / unsourced / not_yet_verified ...). This is the audit
     of whether each coded number is actually backed by its cited source.
  2. SAMPLING CHECK: for targets whose status is `confirmed`, if a cohort CSV
     is available, measure the empirical value and compare to the target within
     tolerance. A target that is not `confirmed` is NEVER counted as passing —
     you cannot calibrate to a number you have not verified.

Usage:
    python3 -m hipaasynth.modules.calibration.verify_against_targets \
        --targets hipaasynth/modules/calibration/copd_targets.json \
        [--cohort path/to/cohort.csv]
"""
import argparse
import csv
import json
import os
import statistics


PASSING_PROVENANCE = {"confirmed", "definitional"}


def load_targets(path):
    with open(path) as f:
        return json.load(f)


def load_cohort(path):
    if not path or not os.path.exists(path):
        return None
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def _measure(rows, field):
    """Very small measurement helper for `col==value` or numeric-mean fields.

    Returns (actual, kind) or (None, None) if the field isn't directly
    measurable from the CSV with this minimal parser.
    """
    if rows is None:
        return None, None
    if "==" in field:
        col, val = field.split("==", 1)
        col, val = col.strip(), val.strip()
        if not rows or col not in rows[0]:
            return None, None
        n = len(rows)
        hits = sum(1 for r in rows if str(r.get(col, "")).lower() == val.lower())
        return hits / n if n else 0.0, "proportion"
    # bare boolean column
    if rows and field in rows[0]:
        n = len(rows)
        vals = [str(r.get(field, "")).lower() for r in rows]
        if set(v for v in vals if v) <= {"true", "false", "1", "0", "yes", "no"}:
            hits = sum(1 for v in vals if v in ("true", "1", "yes"))
            return hits / n if n else 0.0, "proportion"
        nums = []
        for v in vals:
            try:
                nums.append(float(v))
            except ValueError:
                pass
        return (statistics.mean(nums) if nums else None), "mean"
    return None, None


def run(targets_path, cohort_path=None):
    spec = load_targets(targets_path)
    rows = load_cohort(cohort_path or spec.get("cohort_reference"))

    by_status = {}
    sampling = {"pass": 0, "fail": 0, "unmeasured": 0, "skipped_unverified": 0}

    print(f"\n{'='*70}\n  CALIBRATION VERIFICATION — module: {spec.get('module')}\n{'='*70}")
    print(f"  targets file: {targets_path}")
    print(f"  cohort:       {cohort_path or spec.get('cohort_reference')} "
          f"({'loaded' if rows else 'not found — provenance-only'})\n")

    for t in spec["targets"]:
        status = t.get("status", "not_yet_verified")
        by_status.setdefault(status, []).append(t["id"])

        line = f"  [{status:>20}] {t['id']:<26} field={t.get('field')}"
        print(line)

        if status not in PASSING_PROVENANCE:
            if t.get("value") is not None:
                sampling["skipped_unverified"] += 1
            continue

        actual, kind = _measure(rows, t.get("field", ""))
        if actual is None or t.get("value") is None or t.get("tolerance") is None:
            sampling["unmeasured"] += 1
            continue
        diff = abs(actual - t["value"])
        ok = diff <= t["tolerance"]
        sampling["pass" if ok else "fail"] += 1
        print(f"        -> actual={actual:.4f} target={t['value']:.4f} "
              f"diff={diff:.4f} tol={t['tolerance']} [{'PASS' if ok else 'FAIL'}]")

    print(f"\n{'-'*70}\n  PROVENANCE SUMMARY")
    for status in sorted(by_status):
        print(f"    {status:>20}: {len(by_status[status])}  ({', '.join(by_status[status])})")

    verified = sum(len(v) for k, v in by_status.items() if k in PASSING_PROVENANCE)
    total = sum(len(v) for v in by_status.values())
    print(f"\n  {verified}/{total} targets have verified provenance "
          f"(confirmed/definitional).")
    print(f"  SAMPLING (verified targets only): "
          f"{sampling['pass']} pass / {sampling['fail']} fail / "
          f"{sampling['unmeasured']} unmeasured; "
          f"{sampling['skipped_unverified']} targets skipped (unverified provenance).")
    print(f"{'='*70}\n")

    return {"by_status": by_status, "sampling": sampling}


def main():
    ap = argparse.ArgumentParser()
    default_targets = os.path.join(os.path.dirname(__file__), "copd_targets.json")
    ap.add_argument("--targets", default=default_targets)
    ap.add_argument("--cohort", default=None)
    args = ap.parse_args()
    run(args.targets, args.cohort)


if __name__ == "__main__":
    main()
