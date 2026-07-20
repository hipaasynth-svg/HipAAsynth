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
HipAAsynth — Extended Calibration Validator
===========================================
Adds population-level calibration for the self-contained cohort generators that
were previously validated only by smoke tests:

    stroke, diabetes, SMA, DMD, Fabry

Each validator drives the module's own generator (n=1000), then checks that the
emitted distribution reproduces the published epidemiological anchor. Every
target here has a source recorded in ``docs/calibration/CITATIONS.md`` — the
"where to look" registry — so each row can be verified one by one.

Notes on scope:
  - stroke is an *observation hook* layered on the base population pipeline;
    fields that depend on the base cohort's comorbidity mix (AF, HTN overlay)
    are validated here with a clean base so the numbers reflect the stroke
    module's own intrinsic calibration. Anchors that depend on pipeline
    integration (tPA-within-window, SBP>185 fraction) are documented in
    CITATIONS.md as known gaps rather than asserted as PASS.
  - sepsis is a physiological observation generator (not a prevalence model);
    its sources are catalogued in CITATIONS.md but it has no population
    prevalence rows to calibrate here.
"""

import csv
import os
import random
import statistics
from types import SimpleNamespace

from hipaasynth.modules.calibration_validator import check

from hipaasynth.modules.stroke.observations import build_stroke_observations
from hipaasynth.modules.diabetes.population import DiabetesPopulationGenerator
from hipaasynth.modules.sma.sma import SMACohortGenerator, SMA_TYPES
from hipaasynth.modules.dmd.dmd import DMDCohortGenerator
from hipaasynth.modules.fabry.fabry import FabryCohortGenerator


# ── dict-row helpers ──────────────────────────────────────────────────────────
def dprop(rows, key, val):
    n = len(rows)
    if not n:
        return 0.0
    if val is True:
        return sum(1 for r in rows if r.get(key) is True) / n
    return sum(1 for r in rows if r.get(key) == val) / n


def dmean(rows, key):
    vals = [r[key] for r in rows if isinstance(r.get(key), (int, float)) and not isinstance(r.get(key), bool)]
    return statistics.mean(vals) if vals else None


def dmedian(rows, key):
    vals = [r[key] for r in rows if isinstance(r.get(key), (int, float)) and not isinstance(r.get(key), bool)]
    return statistics.median(vals) if vals else None


def save_cohort_csv(rows, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    keys = []
    for r in rows:
        for k in r:
            if k not in keys:
                keys.append(k)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=keys)
        w.writeheader()
        for r in rows:
            w.writerow(r)
    return path


# ════════════════════════════════════════════════════════════════════════════
# STROKE  (intrinsic anchors; clean base — see CITATIONS.md § Stroke)
# Ren 2025; Winder 2023; Feng 2018; Bergh 2022
# ════════════════════════════════════════════════════════════════════════════
def generate_stroke_cohort(seed=9002, n=1000):
    rng = random.Random(seed)
    cfg = SimpleNamespace(required_condition="stroke", _resolved_profile=None)
    rows = []
    for _ in range(n):
        r = rng.random()
        # stroke cohort age skew: mostly elderly (mean ~68)
        if r < 0.62:
            age = rng.randint(65, 90)
        elif r < 0.90:
            age = rng.randint(45, 64)
        else:
            age = rng.randint(18, 44)
        demo = SimpleNamespace(age=age, sex="male" if rng.random() < 0.52 else "female")
        obs = build_stroke_observations(
            rng=rng, demographics=demo, anthropometrics=None,
            conditions=[], visits=[], cfg=cfg,
        )
        rows.append(obs)
    return rows


def validate_stroke(rows):
    results = []
    results.append(check("Ischemic stroke proportion (target 0.84)", dprop(rows, "stroke_type", "ischemic"), 0.84, tol=0.06))
    results.append(check("Hemorrhagic stroke proportion (target 0.13)", dprop(rows, "stroke_type", "hemorrhagic"), 0.13, tol=0.05))
    results.append(check("TIA proportion (target 0.05)", dprop(rows, "stroke_type", "tia"), 0.05, tol=0.04))
    results.append(check("NIHSS mild category proportion (target 0.50)", dprop(rows, "nihss_category", "mild"), 0.50, tol=0.10))
    results.append(check("Atrial fibrillation in stroke (target 0.28)", dprop(rows, "atrial_fibrillation", True), 0.28, tol=0.08))
    otd = dmedian(rows, "onset_to_door_minutes")
    results.append(check("Onset-to-door median minutes (target 83)", otd, 83.0, tol=22.0))
    return results


# ════════════════════════════════════════════════════════════════════════════
# DIABETES  (population module; CDC/NHANES — see CITATIONS.md § Diabetes)
# ════════════════════════════════════════════════════════════════════════════
def generate_diabetes_cohort(seed=8002, n=1000):
    return DiabetesPopulationGenerator(n=n, seed=seed).generate()


def validate_diabetes(rows):
    results = []
    results.append(check("Type 1 diabetes proportion (target 0.06)", dprop(rows, "diabetes_type", "type1"), 0.06, tol=0.03))
    results.append(check("Type 2 diabetes proportion (target 0.94)", dprop(rows, "diabetes_type", "type2"), 0.94, tol=0.03))
    results.append(check("White proportion (target 0.55)", dprop(rows, "race", "White"), 0.55, tol=0.08))
    results.append(check("Black proportion (target 0.18)", dprop(rows, "race", "Black"), 0.18, tol=0.07))
    results.append(check("Hispanic proportion (target 0.15)", dprop(rows, "race", "Hispanic"), 0.15, tol=0.07))
    results.append(check("Asian proportion (target 0.08)", dprop(rows, "race", "Asian"), 0.08, tol=0.05))
    results.append(check("Diabetes current-age mean (target 50-60)", dmean(rows, "current_age"), 55.0, tol=6.0))
    return results


# ════════════════════════════════════════════════════════════════════════════
# SMA  (SMArtCARE registry / natural history — see CITATIONS.md § SMA)
# ════════════════════════════════════════════════════════════════════════════
def generate_sma_cohort(seed=5002, n=1000):
    return SMACohortGenerator(seed=seed, treatment_rate=0.65).generate(n=n)


def validate_sma(rows):
    results = []
    results.append(check("SMA-I proportion (target 0.55)", dprop(rows, "sma_type", "SMA-I"), 0.55, tol=0.08))
    results.append(check("SMA-II proportion (target 0.30)", dprop(rows, "sma_type", "SMA-II"), 0.30, tol=0.08))
    results.append(check("SMA-III proportion (target 0.14)", dprop(rows, "sma_type", "SMA-III"), 0.14, tol=0.06))
    results.append(check("On DMT / nusinersen (target 0.65)", dprop(rows, "on_disease_modifying_therapy", True), 0.65, tol=0.08))
    sma2 = [r for r in rows if r["sma_type"] == "SMA-II"]
    results.append(check("SMA-II scoliosis (target 0.60)", dprop(sma2, "scoliosis", True), 0.60, tol=0.12))
    sma1 = [r for r in rows if r["sma_type"] == "SMA-I"]
    results.append(check("SMA-I feeding support (target 0.85)", dprop(sma1, "feeding_support", True), 0.85, tol=0.12))
    return results


# ════════════════════════════════════════════════════════════════════════════
# DMD  (TREAT-NMD / CINRG natural history — see CITATIONS.md § DMD)
# ════════════════════════════════════════════════════════════════════════════
def generate_dmd_cohort(seed=6002, n=1000):
    return DMDCohortGenerator(seed=seed).generate(n)


def validate_dmd(rows):
    results = []
    results.append(check("Male proportion (X-linked, target 1.0)", dprop(rows, "sex", "male"), 1.0, tol=0.001))
    results.append(check("Deletion mutation (target 0.65)", dprop(rows, "mutation_type", "deletion"), 0.65, tol=0.08))
    results.append(check("Duplication mutation (target 0.10)", dprop(rows, "mutation_type", "duplication"), 0.10, tol=0.05))
    results.append(check("Point mutation (target 0.25)", dprop(rows, "mutation_type", "point_mutation"), 0.25, tol=0.08))
    results.append(check("On corticosteroids (target 0.70)", dprop(rows, "on_steroids", True), 0.70, tol=0.08))
    results.append(check("Diagnosis age mean years (target 4.5)", dmean(rows, "diagnosis_age"), 4.5, tol=1.0))
    results.append(check("Ambulation-loss age mean years (target 11-14)", dmean(rows, "ambulation_loss_age"), 12.5, tol=2.0))
    return results


# ════════════════════════════════════════════════════════════════════════════
# FABRY  (Fabry Registry / FOS — see CITATIONS.md § Fabry)
# ════════════════════════════════════════════════════════════════════════════
def generate_fabry_cohort(seed=7002, n=1000):
    return FabryCohortGenerator(seed=seed, treatment_rate=0.55).generate(n=n)


def validate_fabry(rows):
    results = []
    males = [r for r in rows if r["sex"] == "M"]
    females = [r for r in rows if r["sex"] == "F"]
    results.append(check("Male classic phenotype (target 0.60)", dprop(males, "phenotype", "classic"), 0.60, tol=0.10))
    results.append(check("Female late-cardiac phenotype (target 0.35)", dprop(females, "phenotype", "late_cardiac"), 0.35, tol=0.10))
    results.append(check("Missense mutation (target 0.60)", dprop(rows, "mutation_type", "missense"), 0.60, tol=0.08))
    results.append(check("Nonsense mutation (target 0.15)", dprop(rows, "mutation_type", "nonsense"), 0.15, tol=0.06))
    results.append(check("On enzyme replacement therapy (target 0.55)", dprop(rows, "on_enzyme_replacement_therapy", True), 0.55, tol=0.08))
    results.append(check("Stroke/TIA history (target 0.15)", dprop(rows, "had_stroke_or_tia", True), 0.15, tol=0.08))
    return results


# ── extended runner ───────────────────────────────────────────────────────────
EXT_MODULES = [
    ("stroke",   generate_stroke_cohort,   validate_stroke),
    ("diabetes", generate_diabetes_cohort, validate_diabetes),
    ("sma",      generate_sma_cohort,      validate_sma),
    ("dmd",      generate_dmd_cohort,      validate_dmd),
    ("fabry",    generate_fabry_cohort,    validate_fabry),
]


def run_extended(base_dir):
    """Generate + validate the extended modules; save CSVs; return report dict."""
    modules = {}
    for name, gen, validator in EXT_MODULES:
        rows = gen(n=1000)
        csv_path = os.path.join(base_dir, f"{name}_1000", f"{name}_calibration_n1000.csv")
        save_cohort_csv(rows, csv_path)
        results = validator(rows)
        modules[name] = {
            "csv": csv_path,
            "checks": results,
            "pass": sum(1 for r in results if r["status"] == "PASS"),
            "fail": sum(1 for r in results if r["status"] == "FAIL"),
        }
    return modules


if __name__ == "__main__":
    base = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")
    mods = run_extended(base)
    for name, md in mods.items():
        print(f"\n{name.upper()}  {md['pass']} PASS / {md['fail']} FAIL")
        for r in md["checks"]:
            sym = "✓" if r["status"] == "PASS" else "✗"
            print(f"  {sym} {r['metric']}  actual={r['actual']} target={r['target']} [{r['status']}]")
