# Copyright 2026 Cody Carlson
# Licensed under the Apache License, Version 2.0

"""
HipAAsynth — Determinism Demo

Proves: same seed = identical output, different seed = different output.
Run from workspace root: python run/demo_reproducibility.py
"""

import sys
import os
import random
import json
import hashlib

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.anchor import Anchor
from core.anchor_stamp import stamp_population
from modules.diabetes.population import DiabetesPopulationGenerator
from modules.diabetes.glycemic import GlycemicGenerator
from modules.diabetes.complications import ComplicationGenerator
from modules.diabetes.treatments import TreatmentGenerator
from modules.diabetes.outcomes import OutcomeGenerator

MODULE_VERSIONS = {
    "diabetes_population": "v1.0",
    "glycemic": "v1.0",
    "complications": "v1.0",
    "treatments": "v1.0",
    "outcomes": "v1.0",
}


def run_diabetes_pipeline(n=1000, seed=42):
    anchor = Anchor(
        seed=seed,
        config={"population": n, "pipeline": "diabetes"},
        modules=MODULE_VERSIONS,
    )

    pop_seed  = anchor.derive_seed("population")
    gly_seed  = anchor.derive_seed("glycemic")
    comp_seed = anchor.derive_seed("complications")
    tx_seed   = anchor.derive_seed("treatments")
    out_seed  = anchor.derive_seed("outcomes")

    population = DiabetesPopulationGenerator(n=n, seed=pop_seed).generate()
    population = GlycemicGenerator(random.Random(gly_seed)).generate(population)
    population = ComplicationGenerator(random.Random(comp_seed)).generate(population)
    population = TreatmentGenerator(random.Random(tx_seed)).generate(population)
    population = OutcomeGenerator(random.Random(out_seed)).generate(population)
    population = stamp_population(population, anchor)

    return population


def hash_cohort(cohort):
    raw = json.dumps(cohort, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


if __name__ == "__main__":
    print("=" * 50)
    print("HipAAsynth Determinism Demo")
    print("=" * 50)
    print()

    print("[1/3] Generating cohort A (seed=42, n=1000)...")
    a = run_diabetes_pipeline(n=1000, seed=42)
    hash_a = hash_cohort(a)
    print(f"      Hash: {hash_a[:16]}...")

    print("[2/3] Generating cohort B (seed=42, n=1000)...")
    b = run_diabetes_pipeline(n=1000, seed=42)
    hash_b = hash_cohort(b)
    print(f"      Hash: {hash_b[:16]}...")

    print("[3/3] Generating cohort C (seed=43, n=1000)...")
    c = run_diabetes_pipeline(n=1000, seed=43)
    hash_c = hash_cohort(c)
    print(f"      Hash: {hash_c[:16]}...")

    print()
    print("-" * 50)
    same = hash_a == hash_b
    diff = hash_a != hash_c
    print(f"Same seed match:      {same}")
    print(f"Different seed match: {not diff}")
    print("-" * 50)

    if same and diff:
        print("RESULT: DETERMINISM VERIFIED")
    else:
        print("RESULT: DETERMINISM FAILED")
        sys.exit(1)
