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
HipAAsynth — Calibration CAP Stamp
==================================
Stamps the calibration cohorts and report with SHA-256 hashes chained into a
single tamper-evident certification (Cryptographic Audit Pipeline, CAP v1.0).

This is the calibration analogue of ``cap_pipeline.py`` in the research repo:
instead of chaining module result hashes (psf/dif/cc/adv), it chains the
per-module calibration cohort CSV hashes plus the calibration report hash.

Any edit to a cohort CSV or the report changes the chain hash, so the
certification is only valid when the recomputed chain hash matches the value
recorded in ``calibration_stamp.json`` / ``calibration_chain_hash.txt``.

Usage:
    python3 docs/calibration/stamp_calibration.py \
        --output_dir hipaasynth/modules/output \
        --stamp_dir docs/calibration

If ``--output_dir`` is omitted, the freshly generated cohorts under
``hipaasynth/modules/output`` are used. Run ``run_all_modules.py`` first to
regenerate cohorts and the report.
"""

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone

def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def canonical_report_hash(report):
    """
    SHA-256 of the report's calibration *content*, excluding volatile fields.

    ``generated_utc`` is a genuine wall-clock timestamp that changes every run,
    so it is dropped and the CSV ``csv`` paths (absolute, machine-specific) are
    normalized to basenames. What remains — targets, actuals, tolerances,
    statuses, pass/fail counts — is deterministic for a fixed engine + seeds,
    which is what makes the chain hash reproducible tamper-evidence.
    """
    canon = {
        "engine_version": report.get("engine_version"),
        "tolerance_default": report.get("tolerance_default"),
        "summary": report.get("summary"),
        "modules": {},
    }
    for name, md in report.get("modules", {}).items():
        canon["modules"][name] = {
            "csv": os.path.basename(md.get("csv", "")),
            "checks": md.get("checks"),
            "pass": md.get("pass"),
            "fail": md.get("fail"),
        }
    blob = json.dumps(canon, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def build_stamp(output_dir):
    report_path = os.path.join(output_dir, "calibration_report.json")
    if not os.path.isfile(report_path):
        raise SystemExit(f"error: {report_path} not found. Run run_all_modules.py first.")

    with open(report_path, encoding="utf-8") as fh:
        report = json.load(fh)

    # Modules (and their cohort CSV paths) come from the report itself, so the
    # stamp automatically covers every calibrated module — the original
    # COPD/CHF/OUD plus the extended stroke/diabetes/SMA/DMD/Fabry modules.
    module_order = list(report["modules"].keys())
    cohort_hashes = {}
    for module in module_order:
        csv_field = report["modules"][module].get("csv", "")
        # report stores an absolute path from the generating run; resolve by
        # basename under output_dir so the stamp is portable across machines.
        rel = os.path.join(f"{module}_1000", os.path.basename(csv_field)) if csv_field else ""
        csv_path = os.path.join(output_dir, rel)
        if not os.path.isfile(csv_path):
            raise SystemExit(f"error: {csv_path} not found. Run run_all_modules.py first.")
        cohort_hashes[module] = sha256_file(csv_path)

    # Deterministic content hash (excludes the wall-clock timestamp) — this is
    # what the chain hash is built on, so re-running the pipeline reproduces it.
    report_hash = canonical_report_hash(report)
    chain_input = "".join(cohort_hashes[m] for m in module_order) + report_hash
    chain_hash = hashlib.sha256(chain_input.encode("utf-8")).hexdigest()

    return report, cohort_hashes, report_hash, chain_hash


def write_statement(stamp_dir, report, cohort_hashes, report_hash, chain_hash):
    os.makedirs(stamp_dir, exist_ok=True)
    utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    summary = report["summary"]

    with open(os.path.join(stamp_dir, "calibration_chain_hash.txt"), "w", encoding="utf-8") as fh:
        fh.write(chain_hash + "\n")

    lines = [
        "=" * 56,
        "HIPAASYNTH CALIBRATION CERTIFICATION — CAP v1.0",
        "=" * 56,
        f"Certification Date: {utc}",
        f"Engine Version:     {report['engine_version']}",
        f"Default Tolerance:  +/-{report['tolerance_default']}",
        "Cohort Size:        n=1000 per module",
        "",
        "CALIBRATION RESULT:",
        f"  TOTAL: {summary['total_pass']} PASS / {summary['total_fail']} FAIL",
        "",
        "MODULE RESULTS:",
    ]
    module_order = list(report["modules"].keys())
    for module in module_order:
        md = report["modules"][module]
        lines.append(f"  {module.upper():9s}  {md['pass']} PASS / {md['fail']} FAIL")
    lines += ["", "COHORT CSV HASHES (SHA-256):"]
    for module in module_order:
        lines.append(f"  {module.upper():9s} {cohort_hashes[module]}")
    lines += [
        "",
        "CALIBRATION REPORT CONTENT HASH (SHA-256, excl. timestamp):",
        f"  {report_hash}",
        "",
        "CHAIN HASH (SHA-256 of all cohort CSV hashes + report content hash):",
        f"  {chain_hash}",
        "",
        "CHAIN INTEGRITY:",
        "Any modification to any cohort CSV or the calibration",
        "report will produce a different chain hash. This statement",
        "is valid only when the chain hash matches the independently",
        "computed value.",
        "",
        "OPENTIMESTAMPS ANCHOR: PENDING",
        "Submit calibration_chain_hash.txt to opentimestamps.org to",
        "anchor this certification to the Bitcoin blockchain for",
        "permanent tamper evidence.",
        "",
        "All statistical anchors from public sources. Zero PHI.",
        "HIPAASYNTH — Minot, North Dakota",
        "=" * 56,
    ]
    with open(os.path.join(stamp_dir, "calibration_cap_statement.txt"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")

    stamp = {
        "cap_version": "1.0",
        "certified_utc": utc,
        "engine_version": report["engine_version"],
        "cohort_size": 1000,
        "summary": summary,
        "module_results": {
            m: {"pass": report["modules"][m]["pass"], "fail": report["modules"][m]["fail"]}
            for m in module_order
        },
        "cohort_csv_sha256": cohort_hashes,
        "calibration_report_sha256": report_hash,
        "chain_hash_sha256": chain_hash,
        "opentimestamps_anchor": "PENDING",
    }
    with open(os.path.join(stamp_dir, "calibration_stamp.json"), "w", encoding="utf-8") as fh:
        json.dump(stamp, fh, indent=2)

    return "\n".join(lines)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="HipAAsynth Calibration CAP Stamp v1.0")
    parser.add_argument("--output_dir", default="hipaasynth/modules/output",
                        help="Directory containing calibration_report.json and cohort CSVs.")
    parser.add_argument("--stamp_dir", default="docs/calibration",
                        help="Directory where CAP stamp artifacts are written.")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    report, cohort_hashes, report_hash, chain_hash = build_stamp(args.output_dir)
    text = write_statement(args.stamp_dir, report, cohort_hashes, report_hash, chain_hash)
    print(text)
    print(f"\nStamp written to: {args.stamp_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
