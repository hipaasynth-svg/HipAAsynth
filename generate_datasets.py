#!/usr/bin/env python3
# Copyright 2026 Cody Carlson
# Licensed under the Apache License, Version 2.0

"""
Multi-dataset generation script using HipAAsynth pipelines.

Generates three deterministic synthetic datasets:
1. Diabetes dataset with 10,000 patients (seed=42)
2. General population dataset with 5,000 patients (seed=42)
3. Cardiology dataset with 5,000 patients (seed=42)

All outputs are fully reproducible. Same seed + same config = byte-identical results.
No new randomness introduced outside the existing seeded system.
"""

import time
from datetime import date
from pathlib import Path

from core.config import GenerationConfig, DEFAULT_SYNTHETIC_DISCLAIMER
from pipelines.population_pipeline import generate_patients
from exporters.exporters import export_json, export_csv

def generate_dataset(name: str, patient_count: int, seed: int, required_condition: str = None) -> dict:
    """
    Generate a synthetic dataset with fixed determinism.
    
    Args:
        name: Dataset name for display
        patient_count: Number of patients to generate
        seed: Random seed for full reproducibility
        required_condition: Optional condition filter (e.g., "diabetes", "heart disease")
    
    Returns:
        Dictionary with generation stats
    """
    print(f"\n{'='*60}")
    print(f"Generating {name}")
    print(f"{'='*60}")
    print(f"  Patients: {patient_count:,}")
    print(f"  Seed: {seed}")
    if required_condition:
        print(f"  Required condition: {required_condition}")
    print()
    
    start_time = time.time()
    
    cfg = GenerationConfig(
        patient_count=patient_count,
        seed=seed,
        age_min=18,
        age_max=90,
        required_condition=required_condition,
        sex_ratio_female=0.5,
        ethnicity_weights=None,
        include_visits=True,
        include_labs=True,
        visits_min=1,
        visits_max=3,
        synthetic_disclaimer=DEFAULT_SYNTHETIC_DISCLAIMER,
        run_date=date.today().isoformat(),
        age_band_weights=None,
        population_profile_path=None,
        profile_name=None,
    )
    
    patients = generate_patients(cfg)
    
    gen_time = time.time()
    
    return {
        "name": name,
        "patients": patients,
        "config": cfg,
        "generation_time": gen_time - start_time,
    }

def main():
    """Generate three deterministic datasets and export to CSV/JSON."""
    
    print("\n" + "="*60)
    print("HIPAASYNTH MULTI-DATASET GENERATOR")
    print("="*60)
    print("Deterministic synthetic clinical data engine")
    print("Zero dependencies. Fully reproducible.")
    print()    
    # Create datasets directory
    datasets_dir = Path("datasets")
    datasets_dir.mkdir(parents=True, exist_ok=True)
    
    overall_start = time.time()
    
    # Dataset 1: Diabetes
    diabetes = generate_dataset(
        name="Diabetes Dataset",
        patient_count=10000,
        seed=42,
        required_condition="diabetes"
    )
    
    # Dataset 2: General Population
    population = generate_dataset(
        name="General Population Dataset",
        patient_count=5000,
        seed=42,
        required_condition=None
    )
    
    # Dataset 3: Cardiology
    cardiology = generate_dataset(
        name="Cardiology Dataset",
        patient_count=5000,
        seed=42,
        required_condition="heart disease"
    )
    
    overall_gen_time = time.time()
    
    # Export all datasets
    print(f"\n{'='*60}")
    print("EXPORTING DATASETS")
    print(f"{'='*60}\n")
    
    datasets = [
        ("diabetes_10k", diabetes),
        ("population_5k", population),
        ("cardio_5k", cardiology),
    ]
    
    for file_prefix, dataset in datasets:
        patients = dataset["patients"]
        
        # CSV export
        csv_path = datasets_dir / f"{file_prefix}.csv"
        export_csv(patients, str(csv_path))
        print(f"✓ {file_prefix}.csv ({csv_path.stat().st_size:,} bytes)")
        
        # JSON export
        json_path = datasets_dir / f"{file_prefix}.json"
        export_json(patients, str(json_path))
        print(f"✓ {file_prefix}.json ({json_path.stat().st_size:,} bytes)")
        
        # Verification
        csv_lines = len(csv_path.read_text().splitlines()) - 1
        print(f"  Verified: {csv_lines:,} patient records\n")
    
    overall_time = time.time() - overall_start
    
    # Summary report
    print(f"{'='*60}")
    print("GENERATION COMPLETE")
    print(f"{'='*60}")
    print(f"Total runtime: {round(overall_time, 2)}s")
    print(f"Output directory: {datasets_dir.resolve()}/")
    print()    
    print("Files generated:")
    print("  • diabetes_10k.csv (10,000 patients)")
    print("  • diabetes_10k.json")
    print("  • population_5k.csv (5,000 patients)")
    print("  • population_5k.json")
    print("  • cardio_5k.csv (5,000 patients)")
    print("  • cardio_5k.json")
    print()    
    print("All datasets are deterministic with seed=42")
    print("No real patient information present in any generated output.")
    print("All outputs labeled with synthetic=true and a disclaimer.")
    print()

if __name__ == "__main__":
    main()