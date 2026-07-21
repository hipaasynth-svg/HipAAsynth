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
HipAAsynth — Calibration Validator
=====================================
Runs statistical calibration checks on COPD, CHF, and OUD 1000-patient cohorts.
Compares generated distributions against published reference targets.
Produces calibration report with pass/fail per metric and population statistics.

Usage: python3 calibration_validator.py
"""

import json
import csv
import statistics
import os
from datetime import datetime

# ── Tolerance ─────────────────────────────────────────────────────────────────
TOLERANCE = 0.08   # ±8% absolute tolerance on prevalence/proportion targets

def load_csv(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))

def pct(rows, key, val):
    """Proportion of rows where key==val (or bool True)."""
    total = len(rows)
    if total == 0: return 0.0
    if isinstance(val, bool):
        count = sum(1 for r in rows if r[key].lower() in ("true","1","yes"))
    else:
        count = sum(1 for r in rows if r[key] == val)
    return count / total

def mean_field(rows, key):
    vals = []
    for r in rows:
        try: vals.append(float(r[key]))
        except: pass
    return statistics.mean(vals) if vals else None

def check(label, actual, target, tol=TOLERANCE):
    diff = abs(actual - target)
    status = "PASS" if diff <= tol else "FAIL"
    return {"metric": label, "actual": round(actual, 4),
            "target": round(target, 4), "diff": round(diff, 4),
            "tolerance": tol, "status": status}

# ════════════════════════════════════════════════════════════════════════════
# COPD CALIBRATION
# Reference: NHANES 2017-2020, GOLD 2024, CDC BRFSS 2022
# ════════════════════════════════════════════════════════════════════════════
def validate_copd(path):
    rows = load_csv(path)
    results = []

    # Age: mean should be ~62-64 (COPD diagnosed population)
    age_mean = mean_field(rows, "age")
    results.append(check("COPD age mean (target 62-66)", age_mean, 64.0, tol=4.0))

    # Sex distribution
    results.append(check("COPD female proportion (target 0.52)", pct(rows,"sex","female"), 0.52))

    # GOLD stage distribution
    results.append(check("GOLD_1 proportion (target 0.20)", pct(rows,"gold_stage","GOLD_1"), 0.20))
    results.append(check("GOLD_2 proportion (target 0.38)", pct(rows,"gold_stage","GOLD_2"), 0.38))
    results.append(check("GOLD_3 proportion (target 0.28)", pct(rows,"gold_stage","GOLD_3"), 0.28))
    results.append(check("GOLD_4 proportion (target 0.14)", pct(rows,"gold_stage","GOLD_4"), 0.14))

    # Smoking
    results.append(check("COPD current smoker (target 0.38)", pct(rows,"smoking_status","current"), 0.38))
    results.append(check("COPD former smoker (target 0.47)",  pct(rows,"smoking_status","former"),  0.47))
    results.append(check("COPD never smoker (target 0.15)",   pct(rows,"smoking_status","never"),   0.15))

    # Comorbidities
    results.append(check("COPD hypertension (target 0.55)",   pct(rows,"hypertension",True), 0.55, tol=0.10))
    results.append(check("COPD T2DM (target 0.22)",           pct(rows,"type2_diabetes",True), 0.22, tol=0.10))
    results.append(check("COPD depression (target 0.27)",     pct(rows,"depression",True), 0.27, tol=0.10))

    # FEV1 mean by GOLD (approximate cross-check)
    gold2 = [r for r in rows if r["gold_stage"]=="GOLD_2"]
    if gold2:
        fev1_g2 = mean_field(gold2, "fev1_pct_predicted")
        results.append(check("GOLD_2 FEV1% mean (target 64.5)", fev1_g2, 64.5, tol=6.0))

    # LTOT in GOLD_4
    gold4 = [r for r in rows if r["gold_stage"]=="GOLD_4"]
    if gold4:
        ltot_g4 = pct(gold4, "ltot", True)
        results.append(check("GOLD_4 LTOT rate (target 0.42)", ltot_g4, 0.42, tol=0.12))

    # SpO2 mean (should be <96% across population)
    spo2_mean = mean_field(rows, "spo2_pct")
    results.append(check("COPD SpO2 mean (target 93-96)", spo2_mean, 94.5, tol=2.5))

    return results

# ════════════════════════════════════════════════════════════════════════════
# CHF CALIBRATION
# Reference: AHA 2021 Stats, NHANES, CMS HRRP, MAGGIC
# ════════════════════════════════════════════════════════════════════════════
def validate_chf(path):
    rows = load_csv(path)
    results = []

    # Age mean ~72-74 in hospitalized HF
    age_mean = mean_field(rows, "age")
    results.append(check("CHF age mean (target 72-76)", age_mean, 74.0, tol=4.0))

    # Sex
    results.append(check("CHF male proportion (target 0.52)", pct(rows,"sex","male"), 0.52))

    # Ethnicity: Black Americans ~20%
    results.append(check("CHF Black ethnicity (target 0.20)", pct(rows,"ethnicity","black"), 0.20, tol=0.10))

    # HF phenotype
    results.append(check("HFrEF proportion (target 0.48)",  pct(rows,"hf_phenotype","HFrEF"),  0.48))
    results.append(check("HFpEF proportion (target 0.38)",  pct(rows,"hf_phenotype","HFpEF"),  0.38))
    results.append(check("HFmrEF proportion (target 0.14)", pct(rows,"hf_phenotype","HFmrEF"), 0.14))

    # NYHA class III/IV dominant in hospitalized HF
    nyha34 = pct(rows,"nyha_class","III") + pct(rows,"nyha_class","IV")
    results.append(check("NYHA III+IV proportion (target 0.83)", nyha34, 0.83, tol=0.08))

    # EF mean for HFrEF should be ~25-30%
    hfref_rows = [r for r in rows if r["hf_phenotype"]=="HFrEF"]
    if hfref_rows:
        ef_mean = mean_field(hfref_rows, "ejection_fraction_pct")
        results.append(check("HFrEF EF mean (target 24-34)", ef_mean, 29.0, tol=6.0))

    # Comorbidities
    results.append(check("CHF hypertension (target 0.73)",   pct(rows,"hypertension",True), 0.73, tol=0.10))
    results.append(check("CHF T2DM (target 0.45)",           pct(rows,"type2_diabetes",True), 0.45, tol=0.10))
    results.append(check("CHF afib (target 0.45)",           pct(rows,"afib",True), 0.45, tol=0.10))
    results.append(check("CHF CKD (target 0.48)",            pct(rows,"ckd",True), 0.48, tol=0.10))

    # BNP: NYHA III mean should be 300-1200 → mean ~600-750
    nyha3 = [r for r in rows if r["nyha_class"]=="III"]
    if nyha3:
        bnp3 = mean_field(nyha3, "bnp_pgml")
        results.append(check("NYHA III BNP mean (target 400-900)", bnp3, 650.0, tol=250.0))

    # Sodium: some hyponatremia expected
    na_mean = mean_field(rows, "sodium_meql")
    results.append(check("CHF sodium mean (target 136-140)", na_mean, 138.0, tol=3.0))

    # 30-day readmission risk mean ~22% (CMS benchmark)
    readmit_mean = mean_field(rows, "readmission_risk_30d")
    results.append(check("30-day readmission risk mean (target 0.20-0.28)", readmit_mean, 0.24, tol=0.06))

    # GDMT: beta blocker use in HFrEF ~82%
    if hfref_rows:
        bb = pct(hfref_rows, "med_beta_blocker", True)
        results.append(check("HFrEF beta blocker (target 0.82)", bb, 0.82, tol=0.10))

    return results

# ════════════════════════════════════════════════════════════════════════════
# OUD CALIBRATION
# Reference: SAMHSA NSDUH 2022, CDC 2023, NIDA, ASAM
# ════════════════════════════════════════════════════════════════════════════
def validate_oud(path):
    rows = load_csv(path)
    results = []

    # Age mean ~35-40 (NSDUH treatment-seeking population)
    age_mean = mean_field(rows, "age")
    results.append(check("OUD age mean (target 35-42)", age_mean, 38.0, tol=5.0))

    # Sex
    results.append(check("OUD male proportion (target 0.57)", pct(rows,"sex","male"), 0.57))

    # Rurality
    rural_frontier = pct(rows,"rurality","rural") + pct(rows,"rurality","frontier")
    results.append(check("OUD rural+frontier (target 0.33)", rural_frontier, 0.33, tol=0.08))

    # Severity: severe dominant
    results.append(check("OUD severe proportion (target 0.54)", pct(rows,"oud_severity","severe"), 0.54))

    # Primary opioid: fentanyl now dominant
    results.append(check("Illicit fentanyl (target 0.35)", pct(rows,"primary_opioid","illicit_fentanyl"), 0.35))

    # IV use
    results.append(check("IV drug use (target 0.32)", pct(rows,"iv_drug_use",True), 0.32, tol=0.08))

    # MOUD treatment gap: ~78% untreated
    results.append(check("No MOUD (treatment gap, target 0.78)", pct(rows,"moud_type","no_moud"), 0.78, tol=0.08))

    # Comorbidities
    results.append(check("OUD depression (target 0.55)",   pct(rows,"depression",True), 0.55, tol=0.10))
    results.append(check("OUD tobacco (target 0.72)",      pct(rows,"tobacco_use_disorder",True), 0.72, tol=0.10))
    results.append(check("OUD HCV (target ~0.38)",         pct(rows,"hepatitis_c",True), 0.38, tol=0.12))
    results.append(check("OUD AUD comorbid (target 0.38)", pct(rows,"alcohol_use_disorder",True), 0.38, tol=0.10))
    results.append(check("OUD PTSD (target 0.35)",         pct(rows,"ptsd",True), 0.35, tol=0.10))

    # Prior overdose in severe OUD
    severe = [r for r in rows if r["oud_severity"]=="severe"]
    if severe:
        pod = pct(severe, "prior_overdose", True)
        results.append(check("Severe OUD prior overdose (target 0.52)", pod, 0.52, tol=0.12))

    # Naloxone access: frontier should be low
    frontier = [r for r in rows if r["rurality"]=="frontier"]
    if frontier:
        nalox_f = pct(frontier, "naloxone_access", True)
        results.append(check("Frontier naloxone access (target 0.18)", nalox_f, 0.18, tol=0.12))

    # UDS benzo co-use ~38%
    results.append(check("Benzo co-use on UDS (target 0.38)", pct(rows,"uds_benzodiazepine",True), 0.38, tol=0.10))

    # Medicaid dominant payer ~42%
    results.append(check("Medicaid insurance (target 0.42)", pct(rows,"insurance_status","medicaid"), 0.42, tol=0.10))

    return results


# ── Master runner ─────────────────────────────────────────────────────────────
def run_all():
    report = {
        "generated_utc": datetime.utcnow().isoformat() + "Z",
        "engine_version": "1.1.0",
        "tolerance_default": TOLERANCE,
        "modules": {}
    }

    # v1.0.2: paths are now relative to this file's location, not hardcoded
    # to the original dev environment. BASE matches the `output/` directory
    # that run_all_modules.py writes to.
    BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")

    modules = [
        ("copd", os.path.join(BASE, "copd_1000", "copd_calibration_n1000.csv"), validate_copd),
        ("chf",  os.path.join(BASE, "chf_1000",  "chf_calibration_n1000.csv"),  validate_chf),
        ("oud",  os.path.join(BASE, "oud_1000",  "oud_calibration_n1000.csv"),  validate_oud),
    ]

    total_pass = 0
    total_fail = 0

    for module_name, csv_path, validator in modules:
        print(f"\n{'='*60}")
        print(f"  {module_name.upper()} CALIBRATION  (n=1000)")
        print(f"{'='*60}")

        results = validator(csv_path)
        mod_pass = sum(1 for r in results if r["status"]=="PASS")
        mod_fail = sum(1 for r in results if r["status"]=="FAIL")
        total_pass += mod_pass
        total_fail += mod_fail

        for r in results:
            symbol = "✓" if r["status"]=="PASS" else "✗"
            print(f"  {symbol} {r['metric']}")
            print(f"      actual={r['actual']:.4f}  target={r['target']:.4f}  diff={r['diff']:.4f}  [{r['status']}]")

        print(f"\n  Module result: {mod_pass} PASS / {mod_fail} FAIL")
        report["modules"][module_name] = {
            "csv": csv_path,
            "checks": results,
            "pass": mod_pass,
            "fail": mod_fail,
        }

    print(f"\n{'='*60}")
    print(f"  TOTAL: {total_pass} PASS / {total_fail} FAIL")
    print(f"{'='*60}")

    report["summary"] = {"total_pass": total_pass, "total_fail": total_fail}

    out_path = os.path.join(BASE, "calibration_report.json")
    with open(out_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"\nCalibration report saved: {out_path}")
    return report


if __name__ == "__main__":
    run_all()
