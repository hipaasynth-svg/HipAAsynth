#!/usr/bin/env python3
# Copyright 2026 Cody Carlson
# Licensed under the Apache License, Version 2.0

"""
HipAASynth CLI
Generate synthetic patient cohorts from the command line.
"""

import argparse
import time
from datetime import date
from pathlib import Path

from core.config import GenerationConfig, DEFAULT_SYNTHETIC_DISCLAIMER
from pipelines.population_pipeline import generate_patients
from exporters.exporters import (
    export_json,
    export_csv,
    export_fhir,
    summary_stats,
    print_summary,
    profile_fit_stats,
    print_profile_fit,
)
from core.profile_loader import load_population_profile


def build_parser():
    parser = argparse.ArgumentParser(
        description="Generate synthetic healthcare cohorts with HipAASynth"
    )

    parser.add_argument(
        "--demo",
        action="store_true",
        help="Run in demo mode (uses current timestamp in output folder)",
    )

    parser.add_argument(
        "--count",
        type=int,
        default=2000,
        help="Number of patients to generate (default: 2000)",
    )

    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for deterministic generation (default: 42)",
    )

    parser.add_argument(
        "--out",
        type=str,
        default="output",
        help="Output directory (default: output/)",
    )

    parser.add_argument(
        "--profile",
        type=str,
        default=None,
        help="Path to a population profile JSON (e.g. profiles/minot_nd.json)",
    )

    return parser


def main():

    parser = build_parser()
    args = parser.parse_args()

    if args.demo:
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir = Path(args.out) / f"demo_{timestamp}"
    else:
        output_dir = Path(args.out)

    output_dir.mkdir(parents=True, exist_ok=True)

    json_path = output_dir / "cohort.json"
    csv_path = output_dir / "cohort.csv"
    fhir_path = output_dir / "cohort_fhir.json"

    print("\n" + "=" * 50)
    print("SYNTHETIC COHORT ENGINE — DEMO MODE" if args.demo else "HIPAASYNTH ENGINE")
    print("=" * 50)
    print()

    profile_data = None
    if args.profile is not None:
        profile_data = load_population_profile(args.profile)
        print(f"  Using population profile: {profile_data['profile_name']}")
        if "actual_population" in profile_data:
            print(f"  Actual population: {profile_data['actual_population']:,}")

    print(f"  Cohort size: {args.count}")
    print(f"  Sampling fraction: {args.count / profile_data['actual_population']:.4f}" if profile_data and "actual_population" in profile_data else "")
    print(f"  Patients : {args.count}")
    print(f"  Seed     : {args.seed}")
    print(f"  Output   : {output_dir}/")
    print()

    start_time = time.time()

    cfg = GenerationConfig(
        patient_count=args.count,
        seed=args.seed,
        age_min=18,
        age_max=90,
        required_condition=None,
        sex_ratio_female=profile_data["sex_ratio_female"] if profile_data else 0.5,
        ethnicity_weights=profile_data["ethnicity_weights"] if profile_data else None,
        include_visits=True,
        include_labs=True,
        visits_min=1,
        visits_max=3,
        synthetic_disclaimer=DEFAULT_SYNTHETIC_DISCLAIMER,
        run_date=date.today().isoformat(),
        age_band_weights=profile_data["age_band_weights"] if profile_data else None,
        population_profile_path=args.profile,
        profile_name=profile_data["profile_name"] if profile_data else None,
    )

    patients = generate_patients(cfg)

    gen_time = time.time()

    export_json(patients, str(json_path))
    export_csv(patients, str(csv_path))
    export_fhir(patients, str(fhir_path))

    export_time = time.time()

    stats = summary_stats(patients)
    print("=" * 50)
    print("SYNTHETIC COHORT SUMMARY")
    print("=" * 50)
    print_summary(stats)

    profile_stats = profile_fit_stats(patients, cfg)
    print()
    print("=" * 60)
    print("PROFILE FIT REPORT")
    print("=" * 60)
    print_profile_fit(profile_stats)

    print()
    print("-" * 50)
    print("DEMO COMPLETE" if args.demo else "Run Complete")
    print("-" * 50)
    print(f"  Patients generated : {args.count}")
    print(f"  Seed               : {args.seed}")
    print(f"  Runtime            : {round(export_time-start_time,2)}s")
    print(f"  JSON               : {json_path} ({json_path.stat().st_size:,} bytes)")
    print(f"  CSV                : {csv_path} ({csv_path.stat().st_size:,} bytes)")
    print(f"  FHIR               : {fhir_path} ({fhir_path.stat().st_size:,} bytes)")
    print(f"  Output directory   : {output_dir}/")

    csv_lines = len(csv_path.read_text().splitlines()) - 1
    print(f"  CSV rows verified  : {csv_lines}")
    print()


if __name__ == "__main__":
    main()