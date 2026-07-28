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

"""HipAAsynth CLI — Generate synthetic patient cohorts.

Backwards-compatible surface: every flag that existed before Tier 2
(``--demo --count --seed --out --profile``) behaves exactly as it did, and with no
``--format`` given the CLI writes the same JSON + CSV + FHIR-bundle triple to the
same filenames as before. Tier 2 adds ``--format`` (one or more of
``json csv fhir-bundle ndjson parquet omop``) and ``--validate`` (runs the
structural FHIR validator over the generated cohort) purely additively.
"""
import argparse
import time
from datetime import date, datetime
from pathlib import Path
from hipaasynth.core.config import GenerationConfig, DEFAULT_SYNTHETIC_DISCLAIMER, ENGINE_VERSION
from hipaasynth.pipelines.population_pipeline import generate_patients
from hipaasynth.exporters.exporters import (
    export_json, export_csv, export_fhir, export_fhir_ndjson, export_parquet,
    _patient_to_fhir,
    summary_stats, print_summary, profile_fit_stats, print_profile_fit,
)
from hipaasynth.exporters.omop import export_omop
from hipaasynth.exporters.fhir_validate import (
    validate_bundle, validate_ndjson_dir, validate_resources,
)
from hipaasynth.core.profile_loader import load_population_profile

# Supported --format values, in a stable order for deterministic output.
FORMATS = ("json", "csv", "fhir-bundle", "ndjson", "parquet", "omop")

def build_parser():
    parser = argparse.ArgumentParser(description="Generate synthetic healthcare cohorts")
    parser.add_argument("--demo", action="store_true")
    parser.add_argument("--count", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out", type=str, default="output")
    parser.add_argument("--profile", type=str, default=None)
    parser.add_argument(
        "--format", nargs="+", choices=FORMATS, default=None, metavar="FORMAT",
        help="One or more export formats: " + " ".join(FORMATS) + ". "
             "Omit to keep the legacy behavior (json + csv + fhir-bundle).",
    )
    parser.add_argument(
        "--validate", action="store_true",
        help="Run the structural FHIR validator over the generated cohort. "
             "Exits non-zero if the FHIR resources fail structural validation. "
             "NOT a substitute for the official HL7 FHIR IG validator.",
    )
    return parser


def _export_one(fmt, patients, output_dir):
    """Write one export format; return a human-readable label of what was written."""
    if fmt == "json":
        path = output_dir / "cohort.json"
        export_json(patients, str(path))
        return f"JSON        : {path}"
    if fmt == "csv":
        path = output_dir / "cohort.csv"
        export_csv(patients, str(path))
        return f"CSV         : {path}"
    if fmt == "fhir-bundle":
        path = output_dir / "cohort_fhir.json"
        export_fhir(patients, str(path))
        return f"FHIR bundle : {path}"
    if fmt == "ndjson":
        path = output_dir / "cohort_fhir_ndjson"
        export_fhir_ndjson(patients, str(path))
        return f"FHIR NDJSON : {path}/"
    if fmt == "parquet":
        path = output_dir / "cohort.parquet"
        export_parquet(patients, str(path))  # lazily imports pyarrow (optional extra)
        return f"Parquet     : {path}"
    if fmt == "omop":
        path = output_dir / "omop_cdm"
        export_omop(patients, str(path))
        return f"OMOP CDM    : {path}/"
    raise ValueError(f"unknown format: {fmt}")  # unreachable (argparse choices)


def _run_validation(patients, formats, output_dir):
    """Validate the cohort's FHIR view. Returns the FhirValidationReport.

    Prefers validating a FHIR artifact that was actually written (bundle or
    NDJSON dir); otherwise builds an in-memory bundle from the same patients so
    ``--validate`` is meaningful regardless of which format(s) were exported.
    """
    if "fhir-bundle" in formats:
        import json
        bundle = json.loads((output_dir / "cohort_fhir.json").read_text(encoding="utf-8"))
        report = validate_bundle(bundle)
        source = "written FHIR bundle"
    elif "ndjson" in formats:
        report = validate_ndjson_dir(output_dir / "cohort_fhir_ndjson")
        source = "written NDJSON export"
    else:
        resources = [r for p in patients for r in _patient_to_fhir(p)]
        report = validate_resources(resources)
        source = "in-memory FHIR resources"
    status = "PASS" if report.ok else f"{len(report.errors)} error(s)"
    print(f"\n  FHIR validation ({source}): {report.total} resources — {status}")
    print("  NOTE: structural R5 check only — run the official HL7 FHIR IG "
          "validator before any conformance claim.")
    for err in report.errors[:20]:
        print(f"    [{err['resourceType']}/{err['id']}] {err['message']}")
    return report


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.demo:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir = Path(args.out) / f"demo_{timestamp}"
    else:
        output_dir = Path(args.out)
    output_dir.mkdir(parents=True, exist_ok=True)
    print("\n" + "=" * 50)
    print(f"HIPAASYNTH ENGINE v{ENGINE_VERSION}")
    print("=" * 50)
    profile_data = None
    if args.profile is not None:
        profile_data = load_population_profile(args.profile)
        print(f"  Profile: {profile_data['profile_name']}")
    # Legacy default: no --format means json + csv + fhir-bundle (unchanged).
    formats = args.format if args.format is not None else ["json", "csv", "fhir-bundle"]
    print(f"  Patients : {args.count}")
    print(f"  Seed     : {args.seed}")
    print(f"  Output   : {output_dir}/")
    print(f"  Formats  : {' '.join(formats)}")
    print()
    start_time = time.time()
    cfg = GenerationConfig(
        patient_count=args.count, seed=args.seed,
        age_min=18, age_max=90, required_condition=None,
        sex_ratio_female=profile_data["sex_ratio_female"] if profile_data else 0.5,
        ethnicity_weights=profile_data["ethnicity_weights"] if profile_data else None,
        include_visits=True, include_labs=True, visits_min=1, visits_max=3,
        synthetic_disclaimer=DEFAULT_SYNTHETIC_DISCLAIMER,
        run_date=date.today().isoformat(),
        age_band_weights=profile_data.get("age_band_weights") if profile_data else None,
        population_profile_path=args.profile,
        profile_name=profile_data["profile_name"] if profile_data else None,
    )
    patients = generate_patients(cfg)
    # Export in the canonical FORMATS order so output is deterministic.
    written = [_export_one(fmt, patients, output_dir)
               for fmt in FORMATS if fmt in formats]
    elapsed = round(time.time() - start_time, 2)
    stats = summary_stats(patients)
    print_summary(stats)
    print_profile_fit(profile_fit_stats(patients, cfg))
    print(f"\n  Runtime  : {elapsed}s")
    for line in written:
        print(f"  {line}")
    exit_code = 0
    if args.validate:
        report = _run_validation(patients, formats, output_dir)
        if not report.ok:
            exit_code = 1
    return exit_code

if __name__ == "__main__":
    raise SystemExit(main())
