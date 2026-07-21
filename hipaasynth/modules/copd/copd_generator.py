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
HipAAsynth — COPD Primary Module
==================================
Generates deterministic synthetic COPD patient cohorts calibrated to:
  - NHANES 2017-2020 spirometry and prevalence data
  - CDC BRFSS 2022 state-level COPD burden
  - GOLD 2024 COPD management guidelines
  - ATS/ERS spirometric reference equations (GLI-2012)
  - NHLBI COPD National Action Plan epidemiology

Engine: HipAAsynth v1.0.2
Schema: v1.0.0
Author: HipAAsynth / Cody Carlson
License: CC-BY-NC-4.0

Zero PHI. Zero external dependencies. Pure Python stdlib.
SHA-256 anchor-rooted deterministic randomness.
"""

import hashlib
import json
import csv
import random
import math
import uuid
import os
import sys
from datetime import datetime

# ── Engine constants ──────────────────────────────────────────────────────────
from hipaasynth.core.config import ENGINE_VERSION, SCHEMA_VERSION, DEFAULT_SYNTHETIC_DISCLAIMER
MODULE_NAME     = "copd"
# Canonical synthetic-data disclaimer, shared across all generators (issue #31).
DISCLAIMER      = DEFAULT_SYNTHETIC_DISCLAIMER

# ── Anchor (SHA-256 rooted determinism) ───────────────────────────────────────
def make_anchor(seed: int, module: str, n: int) -> str:
    payload = json.dumps({"seed": seed, "module": module, "n": n}, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()

def derive_rng(anchor: str, namespace: str) -> random.Random:
    combined = f"{anchor}:{namespace}"
    derived   = int(hashlib.sha256(combined.encode()).hexdigest(), 16) % (10**9)
    rng       = random.Random()
    rng.seed(derived)
    return rng

# ── Population profile ────────────────────────────────────────────────────────
# Calibrated to US national COPD burden (NHANES / CDC BRFSS 2022)
# COPD prevalence ~6.2% adults overall; higher in rural, older, lower SES
# Age distribution among diagnosed COPD patients: predominantly 45+
# Source: Wheaton AG et al. MMWR 2015;64(SS-7):1-20.
PROFILE = {
    "label":      "us_copd_national",
    "source":     "NHANES 2017-2020, CDC BRFSS 2022, GOLD 2024",
    "age_range":  (40, 85),
    # Age weights among COPD-diagnosed adults (NHANES)
    "age_weights": {
        (40, 49): 0.12,
        (50, 59): 0.22,
        (60, 69): 0.30,
        (70, 79): 0.25,
        (80, 85): 0.11,
    },
    "sex_dist":   {"male": 0.48, "female": 0.52},  # NHANES COPD sex distribution
    "ethnicity":  {
        "white":    0.71,
        "black":    0.11,
        "hispanic": 0.09,
        "asian":    0.03,
        "native":   0.04,
        "other":    0.02,
    },
}

# ── GOLD staging calibration ──────────────────────────────────────────────────
# GOLD 1-4 prevalence in diagnosed COPD population
# Source: Buist AS et al. International variation in the prevalence of COPD
#         (BOLD Study). Lancet 2007;370(9589):741-750.
#         doi:10.1016/S0140-6736(07)61377-4. GOLD 2024 staging framework.
GOLD_DIST = {
    "GOLD_1": 0.20,  # Mild:      FEV1 ≥80% predicted
    "GOLD_2": 0.38,  # Moderate:  50≤FEV1<80%
    "GOLD_3": 0.28,  # Severe:    30≤FEV1<50%
    "GOLD_4": 0.14,  # Very Severe: FEV1<30%
}

# FEV1 % predicted ranges by GOLD stage
GOLD_FEV1 = {
    "GOLD_1": (80, 99),
    "GOLD_2": (50, 79),
    "GOLD_3": (30, 49),
    "GOLD_4": (15, 29),
}

# FEV1/FVC ratio (all COPD patients have ratio <0.70 post-bronchodilator)
# Source: GOLD 2024 Global Strategy for COPD
GOLD_FEV1_FVC = {
    "GOLD_1": (0.55, 0.69),
    "GOLD_2": (0.45, 0.62),
    "GOLD_3": (0.35, 0.52),
    "GOLD_4": (0.25, 0.42),
}

# ── Smoking history calibration ───────────────────────────────────────────────
# COPD patients: ~85% have significant smoking history
# Source: Salvi SS, Barnes PJ. Lancet 2009;374(9691):733-743.
SMOKING = {
    "current":  0.38,
    "former":   0.47,
    "never":    0.15,   # nonsmoker COPD (biomass, occupational, alpha-1)
}

# Pack-years by smoking status
PACK_YEARS = {
    "current": (20, 80),
    "former":  (15, 60),
    "never":   (0, 5),
}

# ── Comorbidity prevalence in COPD patients ───────────────────────────────────
# Sources:
#   Cardiovascular: Sin DD et al. Chest 2006;129(6):1483-1489
#   T2DM: Mirrakhimov AE. Cardiovasc Diabetol 2012;11:97
#   Depression/Anxiety: Yohannes AM et al. Respir Care 2014;59(7):1112-1120
#   OSA: Shawon MS et al. Respir Med 2017;131:79-90
#   Pulm HTN: Chaouat A et al. Eur Respir J 2008;32(5):1371-1385
COMORBIDITY_RATES = {
    "hypertension":         0.55,
    "cardiovascular_disease": 0.25,
    "type2_diabetes":       0.22,
    "depression":           0.27,
    "anxiety":              0.19,
    "osa":                  0.15,
    "pulmonary_hypertension": 0.18,
    "osteoporosis":         0.24,
    "lung_cancer_history":  0.04,
}

# ── Exacerbation history calibration ─────────────────────────────────────────
# Exacerbations per year by GOLD stage
# Source: Hurst JR et al. NEJM 2010;363(12):1128-1138.
EXACERBATIONS_PER_YEAR = {
    "GOLD_1": (0.0, 0.8),
    "GOLD_2": (0.5, 1.5),
    "GOLD_3": (1.0, 2.5),
    "GOLD_4": (1.5, 4.0),
}

# Hospitalizations in prior year (subset of exacerbations)
HOSPITALIZATION_RATES = {
    "GOLD_1": 0.05,
    "GOLD_2": 0.12,
    "GOLD_3": 0.28,
    "GOLD_4": 0.45,
}

# ── mMRC dyspnea scale calibration ────────────────────────────────────────────
# Source: Jones PW et al. ERJ 2009;34(3):648-654.
MMRC_BY_GOLD = {
    "GOLD_1": {"weights": [0.40, 0.35, 0.15, 0.07, 0.03], "grades": [0, 1, 2, 3, 4]},
    "GOLD_2": {"weights": [0.15, 0.30, 0.30, 0.18, 0.07], "grades": [0, 1, 2, 3, 4]},
    "GOLD_3": {"weights": [0.05, 0.15, 0.32, 0.33, 0.15], "grades": [0, 1, 2, 3, 4]},
    "GOLD_4": {"weights": [0.02, 0.08, 0.22, 0.38, 0.30], "grades": [0, 1, 2, 3, 4]},
}

# ── CAT score calibration (COPD Assessment Test) ──────────────────────────────
# Range 0-40; <10 low impact, 10-20 medium, 20-30 high, >30 very high
# Source: Jones PW et al. ERJ 2009;34(3):648-654.
CAT_BY_GOLD = {
    "GOLD_1": (4, 14),
    "GOLD_2": (10, 22),
    "GOLD_3": (16, 30),
    "GOLD_4": (20, 38),
}

# ── Medication calibration ────────────────────────────────────────────────────
# GOLD 2024 pharmacotherapy recommendations
MEDICATIONS = {
    "GOLD_1": {
        "saba_prn":           0.70,
        "laba":               0.25,
        "lama":               0.20,
        "ics_laba":           0.10,
        "triple_therapy":     0.02,
        "oral_corticosteroid": 0.03,
        "roflumilast":        0.01,
    },
    "GOLD_2": {
        "saba_prn":           0.75,
        "laba":               0.50,
        "lama":               0.55,
        "ics_laba":           0.25,
        "triple_therapy":     0.08,
        "oral_corticosteroid": 0.06,
        "roflumilast":        0.03,
    },
    "GOLD_3": {
        "saba_prn":           0.80,
        "laba":               0.70,
        "lama":               0.72,
        "ics_laba":           0.48,
        "triple_therapy":     0.30,
        "oral_corticosteroid": 0.12,
        "roflumilast":        0.10,
    },
    "GOLD_4": {
        "saba_prn":           0.90,
        "laba":               0.82,
        "lama":               0.80,
        "ics_laba":           0.65,
        "triple_therapy":     0.55,
        "oral_corticosteroid": 0.22,
        "roflumilast":        0.18,
    },
}

# ── Oxygen therapy ────────────────────────────────────────────────────────────
# LTOT indication: PaO2 ≤55 mmHg or SaO2 ≤88%
# Source: NOTT Trial; ATS statement on LTOT
LTOT_RATES = {
    "GOLD_1": 0.01,
    "GOLD_2": 0.04,
    "GOLD_3": 0.15,
    "GOLD_4": 0.42,
}

# ── SpO2 calibration ──────────────────────────────────────────────────────────
SPO2_BY_GOLD = {
    "GOLD_1": (94, 99),
    "GOLD_2": (91, 97),
    "GOLD_3": (87, 94),
    "GOLD_4": (82, 91),
}

# ── 6-minute walk distance (6MWD) ─────────────────────────────────────────────
# Source: Enright PL, Sherrill DL. Am J Respir Crit Care Med 1998;158(5):1384-1387.
SIX_MWD_BY_GOLD = {
    "GOLD_1": (380, 500),
    "GOLD_2": (280, 420),
    "GOLD_3": (180, 320),
    "GOLD_4": (80, 220),
}

# ── Lab value calibration ─────────────────────────────────────────────────────
# Hemoglobin: secondary polycythemia in advanced COPD
# Source: Cote C et al. Chest 2007;131(6):1635-1643.
HGB_MALE_BY_GOLD   = {"GOLD_1":(13.5,16.5),"GOLD_2":(13.0,17.0),"GOLD_3":(13.0,18.5),"GOLD_4":(13.5,19.5)}
HGB_FEMALE_BY_GOLD = {"GOLD_1":(11.5,15.0),"GOLD_2":(11.0,15.5),"GOLD_3":(11.0,17.0),"GOLD_4":(11.5,18.0)}

# BNP elevation in COPD with pulmonary hypertension
# Source: Stolz D et al. Chest 2008;133(4):952-960.
BNP_BY_GOLD = {
    "GOLD_1": (5,  40),
    "GOLD_2": (10, 80),
    "GOLD_3": (20, 200),
    "GOLD_4": (50, 500),
}

# ── Patient ID generator ──────────────────────────────────────────────────────
def make_patient_id(rng: random.Random) -> str:
    hex_part = ''.join(rng.choices('0123456789abcdef', k=8))
    return f"SYN-COPD-{hex_part}"

# ── Height/weight/BMI ─────────────────────────────────────────────────────────
# NHANES anthropometric means for COPD population (slightly lower BMI in GOLD 3-4)
def gen_anthropometrics(rng, sex, gold_stage):
    if sex == "male":
        height = rng.gauss(175.5, 7.2)
        if gold_stage in ("GOLD_3","GOLD_4"):
            weight = rng.gauss(76.0, 18.0)   # weight loss common in severe COPD
        else:
            weight = rng.gauss(84.0, 18.0)
    else:
        height = rng.gauss(162.0, 6.8)
        if gold_stage in ("GOLD_3","GOLD_4"):
            weight = rng.gauss(65.0, 16.0)
        else:
            weight = rng.gauss(74.0, 17.0)
    height = max(148.0, min(205.0, round(height, 1)))
    weight = max(38.0,  min(160.0, round(weight, 1)))
    bmi    = round(weight / ((height/100)**2), 1)
    if bmi < 18.5:   bmi_cat = "Underweight"
    elif bmi < 25.0: bmi_cat = "Normal weight"
    elif bmi < 30.0: bmi_cat = "Overweight"
    else:            bmi_cat = "Obese"
    return height, weight, bmi, bmi_cat

# ── Core generator ────────────────────────────────────────────────────────────
def generate_copd_cohort(seed: int, n: int, label: str = "us_copd_national") -> list:
    anchor = make_anchor(seed, MODULE_NAME, n)

    rng_demo   = derive_rng(anchor, "demographics")
    rng_gold   = derive_rng(anchor, "gold_staging")
    rng_smoke  = derive_rng(anchor, "smoking")
    rng_comor  = derive_rng(anchor, "comorbidities")
    rng_labs   = derive_rng(anchor, "labs")
    rng_meds   = derive_rng(anchor, "medications")
    rng_func   = derive_rng(anchor, "functional")
    rng_exac   = derive_rng(anchor, "exacerbations")
    rng_id     = derive_rng(anchor, "patient_ids")

    patients = []

    for i in range(n):

        # ── Demographics ──────────────────────────────────────────────────────
        # Age: weighted sampling from COPD age distribution
        age_bands = list(PROFILE["age_weights"].keys())
        age_wts   = list(PROFILE["age_weights"].values())
        band      = rng_demo.choices(age_bands, weights=age_wts, k=1)[0]
        age       = rng_demo.randint(band[0], band[1])

        sex_roll  = rng_demo.random()
        sex       = "male" if sex_roll < PROFILE["sex_dist"]["male"] else "female"

        ethnicities = list(PROFILE["ethnicity"].keys())
        eth_weights = list(PROFILE["ethnicity"].values())
        ethnicity   = rng_demo.choices(ethnicities, weights=eth_weights, k=1)[0]

        # ── GOLD staging ──────────────────────────────────────────────────────
        gold_stages = list(GOLD_DIST.keys())
        gold_wts    = list(GOLD_DIST.values())
        gold_stage  = rng_gold.choices(gold_stages, weights=gold_wts, k=1)[0]

        # ── Spirometry ────────────────────────────────────────────────────────
        fev1_min, fev1_max = GOLD_FEV1[gold_stage]
        fev1_pct_pred      = round(rng_labs.uniform(fev1_min, fev1_max), 1)

        fvc_min, fvc_max   = GOLD_FEV1_FVC[gold_stage]
        fev1_fvc_ratio     = round(rng_labs.uniform(fvc_min, fvc_max), 3)

        # Absolute FEV1 (GLI-2012 reference; sex/age/height adjusted)
        height, weight, bmi, bmi_cat = gen_anthropometrics(rng_demo, sex, gold_stage)
        if sex == "male":
            fev1_ref_l = max(0.5, (-0.0214 * age) + (0.0407 * height) - 2.190)
        else:
            fev1_ref_l = max(0.3, (-0.0185 * age) + (0.0332 * height) - 1.499)
        fev1_abs_l = round(fev1_ref_l * (fev1_pct_pred / 100), 2)

        # ── Smoking ───────────────────────────────────────────────────────────
        smoke_cats   = list(SMOKING.keys())
        smoke_wts    = list(SMOKING.values())
        smoking_status = rng_smoke.choices(smoke_cats, weights=smoke_wts, k=1)[0]

        py_min, py_max = PACK_YEARS[smoking_status]
        pack_years     = round(rng_smoke.uniform(py_min, py_max), 1)

        # ── Comorbidities ─────────────────────────────────────────────────────
        comorbidities = {}
        for cond, rate in COMORBIDITY_RATES.items():
            # GOLD 3-4 have higher comorbidity burden
            adjusted_rate = rate * (1.3 if gold_stage in ("GOLD_3","GOLD_4") else 1.0)
            adjusted_rate = min(adjusted_rate, 0.95)
            comorbidities[cond] = rng_comor.random() < adjusted_rate

        condition_list = ["copd"] + [c for c, v in comorbidities.items() if v]

        # ── Medications ───────────────────────────────────────────────────────
        med_profile = MEDICATIONS[gold_stage]
        medications = {med: rng_meds.random() < prob for med, prob in med_profile.items()}
        ltot        = rng_meds.random() < LTOT_RATES[gold_stage]

        # ── Functional status ─────────────────────────────────────────────────
        mmrc_info  = MMRC_BY_GOLD[gold_stage]
        mmrc_grade = rng_func.choices(mmrc_info["grades"], weights=mmrc_info["weights"], k=1)[0]

        cat_min, cat_max = CAT_BY_GOLD[gold_stage]
        cat_score        = rng_func.randint(cat_min, cat_max)

        mwd_min, mwd_max = SIX_MWD_BY_GOLD[gold_stage]
        six_mwd          = round(rng_func.uniform(mwd_min, mwd_max), 0)

        # ── Exacerbations ─────────────────────────────────────────────────────
        exac_min, exac_max = EXACERBATIONS_PER_YEAR[gold_stage]
        exac_rate          = round(rng_exac.uniform(exac_min, exac_max), 1)
        exac_count_yr      = max(0, round(rng_exac.gauss(exac_rate, 0.5)))

        hospitalized_yr = rng_exac.random() < HOSPITALIZATION_RATES[gold_stage]
        icu_admit_yr    = hospitalized_yr and (rng_exac.random() < 0.22)  # ~22% of COPD hospitalizations → ICU

        # ── Labs ──────────────────────────────────────────────────────────────
        spo2_min, spo2_max = SPO2_BY_GOLD[gold_stage]
        spo2               = round(rng_labs.uniform(spo2_min, spo2_max), 1)
        on_ltot_now        = ltot

        hgb_range = HGB_MALE_BY_GOLD[gold_stage] if sex == "male" else HGB_FEMALE_BY_GOLD[gold_stage]
        hemoglobin = round(rng_labs.gauss((hgb_range[0]+hgb_range[1])/2, (hgb_range[1]-hgb_range[0])/4), 1)
        hemoglobin = max(hgb_range[0], min(hgb_range[1], hemoglobin))

        bnp_min, bnp_max = BNP_BY_GOLD[gold_stage]
        bnp              = round(rng_labs.uniform(bnp_min, bnp_max), 1)

        # Standard metabolic panel
        creatinine = round(rng_labs.gauss(1.05, 0.22), 2)
        creatinine = max(0.4, min(4.0, creatinine))

        sodium     = round(rng_labs.gauss(139.5, 3.0), 1)
        sodium     = max(128.0, min(150.0, sodium))

        glucose    = round(rng_labs.gauss(
            105.0 if comorbidities.get("type2_diabetes") else 88.0, 18.0), 1)
        glucose    = max(55.0, min(350.0, glucose))

        # ── ABCD grouping (GOLD 2023+) ────────────────────────────────────────
        # Group E = frequent exacerbator; A/B based on symptoms
        if exac_count_yr >= 2 or hospitalized_yr:
            abcd_group = "E"
        elif mmrc_grade >= 2 or cat_score >= 10:
            abcd_group = "B"
        else:
            abcd_group = "A"

        # ── Assemble patient record ───────────────────────────────────────────
        patient_id = make_patient_id(rng_id)

        row = {
            # Core schema
            "patient_id":           patient_id,
            "age":                  age,
            "sex":                  sex,
            "ethnicity":            ethnicity,
            "height_cm":            height,
            "weight_kg":            weight,
            "bmi":                  bmi,
            "bmi_category":         bmi_cat,
            "conditions":           ";".join(condition_list),
            "engine_version":       ENGINE_VERSION,
            "schema_version":       SCHEMA_VERSION,
            "synthetic":            True,
            "disclaimer":           DISCLAIMER,

            # COPD extension fields
            "cohort_label":         label,
            "anchor_hash":          anchor,
            "gold_stage":           gold_stage,
            "gold_abcd_group":      abcd_group,
            "fev1_pct_predicted":   fev1_pct_pred,
            "fev1_fvc_ratio":       fev1_fvc_ratio,
            "fev1_absolute_l":      fev1_abs_l,

            # Smoking
            "smoking_status":       smoking_status,
            "pack_years":           pack_years,

            # Comorbidities
            "hypertension":         comorbidities["hypertension"],
            "cardiovascular_disease": comorbidities["cardiovascular_disease"],
            "type2_diabetes":       comorbidities["type2_diabetes"],
            "depression":           comorbidities["depression"],
            "anxiety":              comorbidities["anxiety"],
            "osa":                  comorbidities["osa"],
            "pulmonary_hypertension": comorbidities["pulmonary_hypertension"],
            "osteoporosis":         comorbidities["osteoporosis"],
            "lung_cancer_history":  comorbidities["lung_cancer_history"],

            # Medications
            "med_saba_prn":         medications["saba_prn"],
            "med_laba":             medications["laba"],
            "med_lama":             medications["lama"],
            "med_ics_laba":         medications["ics_laba"],
            "med_triple_therapy":   medications["triple_therapy"],
            "med_oral_corticosteroid": medications["oral_corticosteroid"],
            "med_roflumilast":      medications["roflumilast"],
            "ltot":                 ltot,

            # Functional
            "mmrc_dyspnea_grade":   mmrc_grade,
            "cat_score":            cat_score,
            "six_min_walk_m":       six_mwd,

            # Exacerbations
            "exacerbations_prior_yr":  exac_count_yr,
            "hospitalized_prior_yr":   hospitalized_yr,
            "icu_admit_prior_yr":      icu_admit_yr,

            # Labs / vitals
            "spo2_pct":             spo2,
            "hemoglobin_gdl":       hemoglobin,
            "bnp_pgml":             bnp,
            "creatinine_mgdl":      creatinine,
            "sodium_meql":          sodium,
            "glucose_mgdl":         glucose,
        }
        patients.append(row)

    return patients, anchor


class CohortSaveError(RuntimeError):
    """Raised when a cohort cannot be written to disk."""


def save_cohort(patients, anchor, output_dir, prefix):
    try:
        os.makedirs(output_dir, exist_ok=True)
    except OSError as e:
        raise CohortSaveError(f"Cannot create output directory {output_dir}: {e}") from e

    n = len(patients)

    # JSON
    json_path = os.path.join(output_dir, f"{prefix}_n{n}.json")
    try:
        with open(json_path, "w") as f:
            json.dump({
                "module":         MODULE_NAME,
                "n":              n,
                "engine_version": ENGINE_VERSION,
                "anchor_hash":    anchor,
                "patients":       patients
            }, f, indent=2, default=str)
    except OSError as e:
        raise CohortSaveError(f"Cannot write JSON cohort {json_path}: {e}") from e

    # CSV
    csv_path = os.path.join(output_dir, f"{prefix}_n{n}.csv")
    if patients:
        try:
            with open(csv_path, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=list(patients[0].keys()))
                writer.writeheader()
                writer.writerows(patients)
        except OSError as e:
            raise CohortSaveError(f"Cannot write CSV cohort {csv_path}: {e}") from e

    # Manifest
    manifest_path = os.path.join(output_dir, f"{prefix}_manifest.json")
    manifest = {
        "module":         MODULE_NAME,
        "n":              n,
        "engine_version": ENGINE_VERSION,
        "anchor_hash":    anchor,
        "generated_utc":  datetime.utcnow().isoformat() + "Z",
        "files": {
            "json": os.path.basename(json_path),
            "csv":  os.path.basename(csv_path),
        },
        "sha256": {
            "json": hashlib.sha256(open(json_path,"rb").read()).hexdigest(),
            "csv":  hashlib.sha256(open(csv_path,"rb").read()).hexdigest() if os.path.exists(csv_path) else None,
        }
    }
    try:
        with open(manifest_path, "w") as f:
            json.dump(manifest, f, indent=2)
    except OSError as e:
        raise CohortSaveError(f"Cannot write manifest {manifest_path}: {e}") from e

    return json_path, csv_path, manifest_path


if __name__ == "__main__":
    _ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if _ROOT not in sys.path:
        sys.path.insert(0, _ROOT)
    BASE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "output"))

    # ── HuggingFace public cohort: 50 patients, seed=3001 ────────────────────
    print("Generating COPD HuggingFace cohort (n=50, seed=3001)...")
    pts_50, anchor_50 = generate_copd_cohort(seed=3001, n=50, label="us_copd_hf_public")
    j50, c50, m50 = save_cohort(pts_50, anchor_50,
                                 os.path.join(BASE, "copd_50"),
                                 "copd_hf_public")
    print(f"  JSON:     {j50}")
    print(f"  CSV:      {c50}")
    print(f"  Anchor:   {anchor_50[:32]}...")

    # ── Calibration cohort: 1000 patients, seed=3002 ─────────────────────────
    print("Generating COPD calibration cohort (n=1000, seed=3002)...")
    pts_1k, anchor_1k = generate_copd_cohort(seed=3002, n=1000, label="us_copd_calibration")
    j1k, c1k, m1k = save_cohort(pts_1k, anchor_1k,
                                  os.path.join(BASE, "copd_1000"),
                                  "copd_calibration")
    print(f"  JSON:     {j1k}")
    print(f"  CSV:      {c1k}")
    print(f"  Anchor:   {anchor_1k[:32]}...")
    print("COPD module complete.")
