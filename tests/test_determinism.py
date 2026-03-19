# Copyright (c) 2026 Cody Carlson
# Licensed under the Apache License, Version 2.0

"""
Determinism Test Script - 100 Runs.
Focus: 1-21 year old males, 100 iterations to verify zero drift.
"""
import statistics
import hashlib
import json
from datetime import date
from core.config import GenerationConfig, DEFAULT_SYNTHETIC_DISCLAIMER
from pipelines.population_pipeline import generate_patients

TODAY = date.today().isoformat()

def run_determinism_test(iterations=100):
    print(f"--- Running {iterations} Iterations for Determinism ---")
    print("Scenario: 99+ year old females with Type 2 Diabetes")
    
    cfg_dict = dict(
        patient_count=1000, # 1000 per run to keep it fast but statistically significant
        seed=999,
        age_min=99,
        age_max=120,
        required_condition="type2_diabetes",
        sex_ratio_female=1.0, # All female
        ethnicity_weights=None,
        include_visits=True,
        include_labs=True,
        visits_min=1,
        visits_max=2,
        synthetic_disclaimer=DEFAULT_SYNTHETIC_DISCLAIMER,
        run_date=TODAY
    )
    
    first_hash = None
    matches = 0
    
    for i in range(iterations):
        cfg = GenerationConfig(**cfg_dict)
        patients = generate_patients(cfg)
        
        # Create a stable fingerprint of the entire cohort
        cohort_data = []
        for p in patients:
            cohort_data.append({
                "id": p.demographics.patient_id,
                "age": p.demographics.age,
                "conds": [c.name for c in p.conditions],
                "labs": [[l.value for l in v.labs] for v in p.visits]
            })
        
        current_hash = hashlib.sha256(json.dumps(cohort_data, sort_keys=True).encode()).hexdigest()
        
        if first_hash is None:
            first_hash = current_hash
            matches += 1
            # Initial stats from first run
            ages = [p.demographics.age for p in patients]
            cond_counts = [len(p.conditions) for p in patients]
            print(f"Initial Run Stats:")
            print(f"  Avg Age: {statistics.mean(ages):.2f}")
            print(f"  Avg Conditions: {statistics.mean(cond_counts):.4f}")
            print(f"  Initial Hash: {first_hash[:16]}...")
        elif current_hash == first_hash:
            matches += 1
            
        if (i + 1) % 20 == 0:
            print(f"  Completed {i+1}/{iterations}...")

    print(f"\nResults:")
    print(f"  Total Runs: {iterations}")
    print(f"  Matches: {matches}")
    print(f"  Determinism Rate: {(matches/iterations)*100:.1f}%")
    
    if matches == iterations:
        print("  ✅ PERFECT DETERMINISM CONFIRMED")
    else:
        print("  ❌ DRIFT DETECTED")

if __name__ == "__main__":
    run_determinism_test(100)
