# Copyright 2026 Cody Carlson
# Licensed under the Apache License, Version 2.0

"""
HipAAsynth — Generate Auditable Sample

Every record gets:
  - synthetic: true
  - disclaimer text
  - anchor_hash (verifiable fingerprint)

Output includes anchor manifest for full audit trail.

Usage:
  python run/generate_sample.py --count 100 --seed 42
  python run/generate_sample.py --count 100 --seed 42 --profile profiles/minot_nd.json
"""

import sys
import os
import json
import csv
import argparse
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timezone
from collections import Counter

from core.config import GenerationConfig, DEFAULT_SYNTHETIC_DISCLAIMER, ENGINE_VERSION, SCHEMA_VERSION
from core.anchor import Anchor
from core.anchor_stamp import build_metadata
from core.profile_loader import load_population_profile
from pipelines.population_pipeline import generate_patients
from exporters.exporters import summary_stats, export_fhir

MODULE_VERSIONS = {
    "population_pipeline": "v1.0",
    "generator_demographics": "v1.0",
    "generator_anthropometrics": "v1.0",
    "generator_conditions": "v1.0",
    "generator_numerics": "v1.0",
}


def generate_auditable_sample(count=100, seed=42, profile_path="profiles/us_default.json"):
    profile_data = load_population_profile(profile_path)

    anchor = Anchor(
        seed=seed,
        config={"population": count, "pipeline": "general_population", "profile": profile_path},
        modules=MODULE_VERSIONS,
    )

    cfg = GenerationConfig(
        patient_count=count,
        seed=seed,
        age_min=18,
        age_max=90,
        required_condition=None,
        sex_ratio_female=profile_data.get("sex_ratio_female", 0.5),
        ethnicity_weights=profile_data.get("ethnicity_weights"),
        include_visits=True,
        include_labs=True,
        visits_min=1,
        visits_max=3,
        synthetic_disclaimer=DEFAULT_SYNTHETIC_DISCLAIMER,
        run_date=date.today().isoformat(),
        age_band_weights=profile_data.get("age_band_weights"),
        population_profile_path=profile_path,
        profile_name=profile_data.get("profile_name"),
    )

    patients = generate_patients(cfg)

    records = []
    for p in patients:
        rec = p.to_dict()
        rec["anchor_hash"] = anchor.anchor_hash
        records.append(rec)

    ages = [p.demographics.age for p in patients]
    bmis = [p.anthropometrics.bmi for p in patients]
    n = len(patients)
    female_pct = sum(1 for p in patients if p.demographics.sex == "female") / n * 100
    mean_age = sum(ages) / n
    mean_bmi = sum(bmis) / n
    overweight_pct = sum(1 for b in bmis if 25 <= b < 30) / n * 100
    obese_pct = sum(1 for b in bmis if b >= 30) / n * 100

    conditions = Counter()
    for p in patients:
        for c in p.conditions:
            conditions[c.name] += 1
    diabetes_pct = conditions.get("type2_diabetes", 0) / n * 100
    htn_pct = conditions.get("hypertension", 0) / n * 100
    hl_pct = conditions.get("hyperlipidemia", 0) / n * 100
    ckd_pct = conditions.get("chronic_kidney_disease", 0) / n * 100

    eth_dist = {k: round(v / n * 100, 1) for k, v in Counter(p.demographics.ethnicity for p in patients).items()}

    nhanes_benchmarks = {
        "female_pct":    {"value": round(female_pct, 1),    "nhanes_target": 50.5,  "source": "CDC NHANES 2017-2020"},
        "mean_age":      {"value": round(mean_age, 1),      "nhanes_target": 48.0,  "source": "CDC NHANES 2017-2020"},
        "mean_bmi":      {"value": round(mean_bmi, 1),      "nhanes_target": 29.5,  "source": "CDC NHANES 2017-2020"},
        "overweight_pct":{"value": round(overweight_pct, 1),"nhanes_target": 31.5,  "source": "CDC NHANES 2017-2020"},
        "obese_pct":     {"value": round(obese_pct, 1),     "nhanes_target": 41.5,  "source": "CDC NHANES 2017-2020"},
        "diabetes_pct":  {"value": round(diabetes_pct, 1),  "nhanes_target": 13.5,  "source": "CDC National Diabetes Statistics 2022"},
        "htn_pct":       {"value": round(htn_pct, 1),       "nhanes_target": 33.5,  "source": "AHA Heart Disease & Stroke Statistics 2024"},
        "hyperlipid_pct":{"value": round(hl_pct, 1),        "nhanes_target": 28.5,  "source": "CDC NHANES 2017-2020"},
        "ckd_pct":       {"value": round(ckd_pct, 1),       "nhanes_target": 14.5,  "source": "USRDS Annual Data Report 2023"},
    }

    for key, entry in nhanes_benchmarks.items():
        target = entry["nhanes_target"]
        val = entry["value"]
        entry["error_pct"] = round(abs(val - target) / target * 100, 1)

    errors = [v["error_pct"] for v in nhanes_benchmarks.values()]
    mean_error = round(sum(errors) / len(errors), 1)

    metadata = build_metadata(anchor, {
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "engine_version": ENGINE_VERSION,
        "schema_version": SCHEMA_VERSION,
        "rows": len(records),
        "profile": profile_path,
        "profile_name": profile_data.get("profile_name"),
        "description": f"General population cohort ({count} patients)",
        "deterministic": True,
        "synthetic": True,
        "disclaimer": DEFAULT_SYNTHETIC_DISCLAIMER,
        "generation_parameters": {
            "count": count,
            "seed": seed,
            "age_range": [18, 90],
            "visits": True,
            "labs": True,
        },
        "cohort_statistics": {
            "female_pct": round(female_pct, 1),
            "mean_age": round(mean_age, 1),
            "mean_bmi": round(mean_bmi, 1),
            "overweight_pct": round(overweight_pct, 1),
            "obese_pct": round(obese_pct, 1),
            "condition_prevalence": {k: round(v / n * 100, 1) for k, v in conditions.most_common()},
            "ethnicity_distribution": eth_dist,
        },
        "nhanes_benchmarks": nhanes_benchmarks,
        "mean_absolute_error": mean_error,
    })

    return records, metadata, patients


def save_json(records, metadata, path):
    output = {
        "metadata": metadata,
        "records": records,
    }
    with open(path, "w") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)


def save_csv(records, path):
    if not records:
        return
    flat_rows = []
    for r in records:
        demo = r.get("demographics", {})
        anthro = r.get("anthropometrics", {})
        conditions = r.get("conditions", [])
        visits = r.get("visits", [])
        flat_rows.append({
            "patient_id": demo.get("patient_id"),
            "seed": demo.get("seed"),
            "age": demo.get("age"),
            "sex": demo.get("sex"),
            "ethnicity": demo.get("ethnicity"),
            "height_cm": anthro.get("height_cm"),
            "weight_kg": anthro.get("weight_kg"),
            "bmi": anthro.get("bmi"),
            "bmi_category": anthro.get("bmi_category"),
            "conditions": ";".join(c.get("name", "") for c in conditions),
            "num_visits": len(visits),
            "num_labs": sum(len(v.get("labs", [])) for v in visits),
            "engine_version": r.get("engine_version"),
            "schema_version": r.get("schema_version"),
            "synthetic": r.get("synthetic"),
            "disclaimer": r.get("disclaimer"),
            "anchor_hash": r.get("anchor_hash"),
        })
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=flat_rows[0].keys())
        writer.writeheader()
        writer.writerows(flat_rows)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate auditable synthetic sample")
    parser.add_argument("--count", type=int, default=100)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--profile", default="profiles/us_default.json")
    args = parser.parse_args()

    print(f"Generating {args.count} patients (seed={args.seed})...")
    records, metadata, patients = generate_auditable_sample(args.count, args.seed, args.profile)

    anchor_hash = metadata.get("anchor_hash", records[0].get("anchor_hash", "?"))
    print(f"Anchor hash: {anchor_hash[:16]}...")
    print()

    json_path = f"sample_{args.count}_general_population.json"
    csv_path = f"sample_{args.count}_general_population.csv"
    fhir_path = f"sample_{args.count}_fhir_bundle.json"
    manifest_path = f"sample_{args.count}_anchor_manifest.json"

    save_json(records, metadata, json_path)
    save_csv(records, csv_path)
    export_fhir(patients, fhir_path)
    with open(manifest_path, "w") as f:
        json.dump(metadata, f, indent=2)

    all_stamped = all(r.get("anchor_hash") for r in records)
    all_synthetic = all(r.get("synthetic") == True for r in records)
    all_disclaimed = all(r.get("disclaimer") for r in records)

    print(f"Every record anchor_hash:  {all_stamped}")
    print(f"Every record synthetic:    {all_synthetic}")
    print(f"Every record disclaimer:   {all_disclaimed}")
    print()
    print(f"Saved: {json_path}")
    print(f"Saved: {csv_path}")
    print(f"Saved: {fhir_path}")
    print(f"Saved: {manifest_path}")
