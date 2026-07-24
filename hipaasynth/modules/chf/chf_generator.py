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
HipAAsynth — Congestive Heart Failure (CHF) Readmission Module
================================================================
Generates deterministic synthetic CHF patient cohorts calibrated to:
  - AHA/ACC 2022 Heart Failure Guidelines
  - NHANES 2017-2020 cardiovascular data
  - CMS Hospital Readmissions Reduction Program (HRRP) benchmarks
  - MAGGIC meta-analysis (39,372 patients) for mortality/readmission risk
  - OPTIMIZE-HF registry (heart failure phenotyping)
  - ESC Heart Failure Long-Term Registry

Focus: 30-day and 90-day readmission risk modeling
CMS HRRP penalizes hospitals for excess HF readmissions (national ~22% 30-day rate)

IMPORTANT — COHORT FRAMING:
  This module simulates a HOSPITALIZED / ACUTE heart failure cohort, NOT a
  community or outpatient HF population.  The NYHA severity distribution
  (Class I: 8%, II: 9%, III: 54%, IV: 29%) is intentionally skewed toward
  severe disease and directly mirrors the OPTIMIZE-HF registry of 48,612
  hospitalized HF admissions (Fonarow GC et al. JAMA 2007;297(1):61-70).

  Community HF prevalence studies show a much milder NYHA profile (~40-50%
  Class I/II).  The Class III/IV predominance here is not a calibration
  error — it correctly reflects the acuity of patients presenting for
  inpatient care.  Do not compare these distributions to outpatient or
  population-based HF registries.

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
import os
import sys
from datetime import datetime

from hipaasynth.core.config import ENGINE_VERSION, SCHEMA_VERSION, DEFAULT_SYNTHETIC_DISCLAIMER
from hipaasynth.core.dependence import draw_chf_comorbidities
MODULE_NAME    = "chf_readmission"
# Canonical synthetic-data disclaimer, shared across all generators (issue #31).
DISCLAIMER     = DEFAULT_SYNTHETIC_DISCLAIMER

# ── Anchor ────────────────────────────────────────────────────────────────────
def make_anchor(seed, module, n):
    payload = json.dumps({"seed": seed, "module": module, "n": n}, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()

def derive_rng(anchor, namespace):
    combined = f"{anchor}:{namespace}"
    derived  = int(hashlib.sha256(combined.encode()).hexdigest(), 16) % (10**9)
    rng      = random.Random()
    rng.seed(derived)
    return rng

# ── Population profile ────────────────────────────────────────────────────────
# HF prevalence: ~6.7M US adults; 50% HFrEF, 50% HFpEF
# Age: median ~72 in hospitalized HF populations
# Source: Virani SS et al. Circulation 2021;143:e254-e743.
PROFILE = {
    "label":     "us_chf_national",
    "source":    "AHA Heart Disease Statistics 2021, NHANES 2017-2020, CMS HRRP 2023",
    "age_range": (45, 90),
    "age_weights": {
        (45, 54): 0.08,
        (55, 64): 0.17,
        (65, 74): 0.28,
        (75, 84): 0.32,
        (85, 90): 0.15,
    },
    "sex_dist":  {"male": 0.52, "female": 0.48},
    "ethnicity": {
        "white":    0.62,
        "black":    0.20,    # Black Americans have disproportionate HF burden
        "hispanic": 0.10,
        "asian":    0.04,
        "native":   0.02,
        "other":    0.02,
    },
}

# ── HF phenotype ──────────────────────────────────────────────────────────────
# HFrEF: EF <40%; HFmrEF: EF 40-49%; HFpEF: EF ≥50%
# Source: McDonagh TA et al. Eur Heart J 2021;42(36):3599-3726.
HF_PHENOTYPE = {
    "HFrEF":  0.48,   # EF <40%
    "HFmrEF": 0.14,   # EF 40-49%
    "HFpEF":  0.38,   # EF ≥50%
}

# EF ranges by phenotype
EF_RANGES = {
    "HFrEF":  (10, 39),
    "HFmrEF": (40, 49),
    "HFpEF":  (50, 75),
}

# ── NYHA classification distribution in hospitalized HF ──────────────────────
# Source: Fonarow GC et al. JAMA 2007;297(1):61-70. (OPTIMIZE-HF)
NYHA_DIST = {
    "I":   0.03,
    "II":  0.14,
    "III": 0.54,
    "IV":  0.29,
}

# ── ACC/AHA HF Stage ──────────────────────────────────────────────────────────
STAGE_DIST = {
    "B": 0.08,   # Structural disease, no symptoms
    "C": 0.72,   # Symptomatic HF
    "D": 0.20,   # Advanced/refractory HF
}

# ── Etiology ──────────────────────────────────────────────────────────────────
# Source: Gheorghiade M, Bonow RO. Circulation 1998;97(3):282-289.
ETIOLOGY = {
    "ischemic_cardiomyopathy":    0.42,
    "hypertensive_cardiomyopathy": 0.22,
    "dilated_cardiomyopathy":     0.12,
    "valvular_disease":           0.10,
    "diabetic_cardiomyopathy":    0.08,
    "other":                      0.06,
}

# ── Comorbidities (hospitalized HF population) ────────────────────────────────
# NOTE (v1.2.1 — conditional dependence): comorbidities are no longer drawn as
# independent Bernoulli trials against these flat marginals. They are drawn
# CONDITIONAL ON NYHA CLASS by hipaasynth.core.dependence, which tilts each
# marginal across NYHA I-IV with a literature-shaped, marginal-preserving
# gradient (the class-weighted mean of each conditional rate still equals the
# marginal below). This dict is retained as the documented national marginal
# reference; the canonical conditional model lives in
# core.dependence.CHF_COMORBIDITY_MODEL (same values, same key order).
# Source: Dharmarajan K et al. JAMA 2013;309(4):355-363.
#         Rich MW et al. J Am Geriatr Soc 2013;61(6):917-925.
COMORBIDITY_RATES = {
    "hypertension":             0.73,
    "type2_diabetes":           0.45,
    "ckd":                      0.48,    # CKD stage 3+ common in HF
    "afib":                     0.45,    # Most common arrhythmia in HF
    "copd":                     0.28,
    "cad":                      0.55,    # Coronary artery disease
    "prior_mi":                 0.32,
    "prior_cabg_or_pci":        0.28,
    "anemia":                   0.37,
    "sleep_apnea":              0.24,
    "depression":               0.22,
    "peripheral_vascular_disease": 0.18,
    "stroke_tia_history":       0.14,
    "liver_disease":            0.08,
}

# ── Lab calibration ───────────────────────────────────────────────────────────
# Source: Maisel AS et al. NEJM 2002;347(3):161-167. (BNP in acute HF)
#         Januzzi JL et al. Am J Cardiol 2005;95(8):948-954. (NT-proBNP)
#         Felker GM et al. NEJM 2011;364(9):797-805. (DOSE trial)
BNP_BY_NYHA = {
    "I":   (35,  200),
    "II":  (100, 500),
    "III": (300, 1200),
    "IV":  (600, 4000),
}

NTPROBNP_BY_NYHA = {
    "I":   (125,   800),
    "II":  (400,  2000),
    "III": (1000, 8000),
    "IV":  (3000, 35000),
}

# Troponin elevation (high-sensitivity troponin I, ng/L)
# Elevated in ~50% of acute HF hospitalizations
# Source: Peacock WF et al. Am Heart J 2008;155(2):284-290.
TROPONIN_I_HS = {
    "normal":   (3,  25),     # <26 ng/L upper reference limit
    "elevated": (26, 400),
}

# Sodium (hyponatremia is a readmission risk factor)
# Source: Gheorghiade M et al. Arch Intern Med 2007;167(18):1998-2005.
SODIUM_BY_NYHA = {
    "I":   (137, 145),
    "II":  (135, 144),
    "III": (132, 142),
    "IV":  (128, 140),
}

# Creatinine (cardiorenal syndrome common)
# Source: Ronco C et al. J Am Coll Cardiol 2008;52(19):1527-1539.
CREATININE_BY_STAGE = {
    "B": (0.8, 1.4),
    "C": (0.9, 2.2),
    "D": (1.2, 4.5),
}

# ── Medications (AHA/ACC 2022 guideline-directed) ─────────────────────────────
# Source: Heidenreich PA et al. Circulation 2022;145(18):e895-e1032.
MEDS_BY_PHENOTYPE = {
    "HFrEF": {
        "acei_arb_arni":  0.78,    # Cornerstone HFrEF therapy
        "beta_blocker":   0.82,
        "mra":            0.52,    # Mineralocorticoid receptor antagonist
        "sglt2i":         0.42,    # Emerging standard of care
        "loop_diuretic":  0.82,
        "digoxin":        0.12,
        "hydralazine_nitrate": 0.14,
        "ivabradine":     0.08,
        "anticoagulant":  0.45,
        "statin":         0.62,
        "aspirin":        0.48,
    },
    "HFmrEF": {
        "acei_arb_arni":  0.62,
        "beta_blocker":   0.70,
        "mra":            0.38,
        "sglt2i":         0.38,
        "loop_diuretic":  0.75,
        "digoxin":        0.06,
        "hydralazine_nitrate": 0.08,
        "ivabradine":     0.04,
        "anticoagulant":  0.45,
        "statin":         0.60,
        "aspirin":        0.48,
    },
    "HFpEF": {
        "acei_arb_arni":  0.52,
        "beta_blocker":   0.65,
        "mra":            0.30,
        "sglt2i":         0.42,    # EMPEROR-Preserved / DELIVER evidence
        "loop_diuretic":  0.72,
        "digoxin":        0.04,
        "hydralazine_nitrate": 0.05,
        "ivabradine":     0.02,
        "anticoagulant":  0.48,
        "statin":         0.60,
        "aspirin":        0.50,
    },
}

# ── Device therapy ────────────────────────────────────────────────────────────
# ICD/CRT primarily for HFrEF with EF ≤35%
# Source: Moss AJ et al. NEJM 2002;346(12):877-883. (MADIT-CRT)
DEVICE_RATES = {
    "HFrEF":  {"icd": 0.45, "crt_d": 0.28, "crt_p": 0.08, "lvad": 0.04, "iabp_prior": 0.06},
    "HFmrEF": {"icd": 0.18, "crt_d": 0.10, "crt_p": 0.05, "lvad": 0.01, "iabp_prior": 0.03},
    "HFpEF":  {"icd": 0.08, "crt_d": 0.04, "crt_p": 0.03, "lvad": 0.00, "iabp_prior": 0.02},
}

# ── Readmission risk score components ─────────────────────────────────────────
# LACE index: Length of stay, Acuity, Charlson, ED visits
# Source: van Walraven C et al. CMAJ 2010;182(6):551-557.
# MAGGIC risk score
# Source: Pocock SJ et al. Eur Heart J 2013;34(19):1404-1413.
def compute_maggic_risk(age, ef, nyha, systolic_bp, bmi, creatinine,
                        diabetes, copd, afib, non_smoker):
    """
    Simplified MAGGIC 1-year mortality risk score.
    Full model: Pocock et al. Eur Heart J 2013;34:1404-1413.
    """
    score = 0
    # EF
    if ef < 20: score += 7
    elif ef < 25: score += 6
    elif ef < 30: score += 5
    elif ef < 35: score += 3
    elif ef < 40: score += 2
    # Age (men baseline; women subtract 1)
    if age < 55: score += 0
    elif age < 60: score += 1
    elif age < 65: score += 2
    elif age < 70: score += 4
    elif age < 75: score += 6
    elif age < 80: score += 8
    else: score += 10
    # Systolic BP
    if systolic_bp < 110: score += 5
    elif systolic_bp < 120: score += 4
    elif systolic_bp < 130: score += 3
    elif systolic_bp < 140: score += 2
    elif systolic_bp < 150: score += 1
    # BMI
    if bmi < 15: score += 6
    elif bmi < 20: score += 5
    elif bmi < 25: score += 3
    elif bmi < 30: score += 2
    # Creatinine
    if creatinine >= 2.5: score += 8
    elif creatinine >= 2.0: score += 6
    elif creatinine >= 1.5: score += 3
    elif creatinine >= 1.0: score += 1
    # NYHA
    nyha_map = {"I": 0, "II": 3, "III": 6, "IV": 8}
    score += nyha_map.get(nyha, 3)
    # Comorbidities
    if diabetes: score += 3
    if copd: score += 2
    if afib: score += 1
    return min(score, 40)

# ── 30-day readmission risk ───────────────────────────────────────────────────
# Calibrated to national CMS HRRP mean ~22%
def compute_readmission_risk_30d(nyha, stage, ckd, afib, sodium, prior_admissions, age):
    base = 0.15
    if nyha == "IV": base += 0.07
    elif nyha == "III": base += 0.04
    if stage == "D": base += 0.05
    if ckd: base += 0.03
    if afib: base += 0.02
    if sodium < 130: base += 0.05
    elif sodium < 135: base += 0.02
    if prior_admissions >= 2: base += 0.04
    if age >= 80: base += 0.02
    return round(min(base, 0.70), 3)

# ── Anthropometrics ───────────────────────────────────────────────────────────
def gen_anthropometrics(rng, sex, hf_phenotype):
    # HFpEF patients tend to be more obese
    if sex == "male":
        height = rng.gauss(175.0, 7.0)
        weight_mean = 98.0 if hf_phenotype == "HFpEF" else 85.0
        weight = rng.gauss(weight_mean, 20.0)
    else:
        height = rng.gauss(161.5, 6.5)
        weight_mean = 92.0 if hf_phenotype == "HFpEF" else 75.0
        weight = rng.gauss(weight_mean, 20.0)
    height = max(145.0, min(200.0, round(height, 1)))
    weight = max(35.0,  min(180.0, round(weight, 1)))
    bmi    = round(weight / ((height/100)**2), 1)
    if bmi < 18.5:   bmi_cat = "Underweight"
    elif bmi < 25.0: bmi_cat = "Normal weight"
    elif bmi < 30.0: bmi_cat = "Overweight"
    else:            bmi_cat = "Obese"
    return height, weight, bmi, bmi_cat

def make_patient_id(rng):
    hex_part = ''.join(rng.choices('0123456789abcdef', k=8))
    return f"SYN-CHF-{hex_part}"

# ── Core generator ────────────────────────────────────────────────────────────
def generate_chf_cohort(seed: int, n: int, label: str = "us_chf_national") -> tuple:
    anchor = make_anchor(seed, MODULE_NAME, n)

    rng_demo  = derive_rng(anchor, "demographics")
    rng_pheno = derive_rng(anchor, "phenotype")
    rng_comor = derive_rng(anchor, "comorbidities")
    rng_labs  = derive_rng(anchor, "labs")
    rng_meds  = derive_rng(anchor, "medications")
    rng_risk  = derive_rng(anchor, "risk_scores")
    rng_admit = derive_rng(anchor, "admissions")
    rng_id    = derive_rng(anchor, "patient_ids")

    patients = []

    for i in range(n):

        # ── Demographics ──────────────────────────────────────────────────────
        age_bands = list(PROFILE["age_weights"].keys())
        age_wts   = list(PROFILE["age_weights"].values())
        band      = rng_demo.choices(age_bands, weights=age_wts, k=1)[0]
        age       = rng_demo.randint(band[0], band[1])

        sex       = "male" if rng_demo.random() < PROFILE["sex_dist"]["male"] else "female"

        eth_list  = list(PROFILE["ethnicity"].keys())
        eth_wts   = list(PROFILE["ethnicity"].values())
        ethnicity = rng_demo.choices(eth_list, weights=eth_wts, k=1)[0]

        # ── HF Phenotype ──────────────────────────────────────────────────────
        pheno_list = list(HF_PHENOTYPE.keys())
        pheno_wts  = list(HF_PHENOTYPE.values())
        hf_pheno   = rng_pheno.choices(pheno_list, weights=pheno_wts, k=1)[0]

        ef_min, ef_max = EF_RANGES[hf_pheno]
        ejection_fraction = rng_pheno.randint(ef_min, ef_max)

        nyha_classes = list(NYHA_DIST.keys())
        nyha_wts     = list(NYHA_DIST.values())
        nyha_class   = rng_pheno.choices(nyha_classes, weights=nyha_wts, k=1)[0]

        stage_list = list(STAGE_DIST.keys())
        stage_wts  = list(STAGE_DIST.values())
        hf_stage   = rng_pheno.choices(stage_list, weights=stage_wts, k=1)[0]

        etiology_list = list(ETIOLOGY.keys())
        etiology_wts  = list(ETIOLOGY.values())
        hf_etiology   = rng_pheno.choices(etiology_list, weights=etiology_wts, k=1)[0]

        # ── Anthropometrics ───────────────────────────────────────────────────
        height, weight, bmi, bmi_cat = gen_anthropometrics(rng_demo, sex, hf_pheno)

        # ── Vitals ────────────────────────────────────────────────────────────
        # SBP lower in HFrEF, higher in HFpEF (hypertensive)
        if hf_pheno == "HFrEF":
            sbp = round(rng_labs.gauss(105.0, 18.0), 0)
        elif hf_pheno == "HFpEF":
            sbp = round(rng_labs.gauss(142.0, 22.0), 0)
        else:
            sbp = round(rng_labs.gauss(122.0, 20.0), 0)
        sbp = max(70.0, min(220.0, sbp))

        # Heart rate
        hr = round(rng_labs.gauss(82.0, 16.0), 0)
        hr = max(45.0, min(140.0, hr))

        # SpO2
        spo2_mean = 92.0 if nyha_class == "IV" else 95.0 if nyha_class == "III" else 97.0
        spo2 = round(rng_labs.gauss(spo2_mean, 2.5), 1)
        spo2 = max(82.0, min(100.0, spo2))

        # Weight gain (fluid retention)
        weight_gain_kg = round(rng_labs.uniform(0.5, 8.0) if nyha_class in ("III","IV") else rng_labs.uniform(0, 3.0), 1)

        # ── Comorbidities (CONDITIONAL ON NYHA CLASS) ─────────────────────────
        # Replaces the former independent Bernoulli loop. core.dependence tilts
        # each national marginal across NYHA I-IV with a literature-shaped,
        # marginal-preserving gradient (e.g. CKD climbs ~0.26 -> ~0.60 NYHA I ->
        # NYHA IV while its overall prevalence stays 0.48). One rng.random() per
        # comorbidity in a fixed order, so the anchor-rooted RNG stream structure
        # is unchanged. hf_stage / hf_pheno passed for forward compatibility.
        comorbidities = draw_chf_comorbidities(
            rng_comor, nyha_class, hf_stage=hf_stage, hf_phenotype=hf_pheno
        )

        # Ensure ischemic patients have CAD
        if hf_etiology == "ischemic_cardiomyopathy":
            comorbidities["cad"] = True

        condition_list = ["congestive_heart_failure"] + [c for c, v in comorbidities.items() if v]

        # ── Labs ──────────────────────────────────────────────────────────────
        bnp_min, bnp_max     = BNP_BY_NYHA[nyha_class]
        bnp                  = round(rng_labs.uniform(bnp_min, bnp_max), 1)

        ntprobnp_min, ntprobnp_max = NTPROBNP_BY_NYHA[nyha_class]
        ntprobnp             = round(rng_labs.uniform(ntprobnp_min, ntprobnp_max), 1)

        # Troponin
        troponin_elevated    = rng_labs.random() < 0.48
        trop_range           = TROPONIN_I_HS["elevated"] if troponin_elevated else TROPONIN_I_HS["normal"]
        troponin_i_hs        = round(rng_labs.uniform(trop_range[0], trop_range[1]), 1)

        sodium_min, sodium_max = SODIUM_BY_NYHA[nyha_class]
        sodium               = round(rng_labs.uniform(sodium_min, sodium_max), 1)

        creat_min, creat_max = CREATININE_BY_STAGE[hf_stage]
        creatinine           = round(rng_labs.uniform(creat_min, creat_max), 2)
        creatinine           = max(0.4, creatinine)

        egfr = round(max(5.0, 186 * (creatinine**-1.154) * (age**-0.203) * (0.742 if sex == "female" else 1.0)), 1)

        potassium = round(rng_labs.gauss(4.1, 0.55), 1)
        potassium = max(2.8, min(6.5, potassium))

        hemoglobin_mean = 11.2 if comorbidities.get("anemia") else (13.8 if sex == "male" else 12.2)
        hemoglobin = round(rng_labs.gauss(hemoglobin_mean, 1.5), 1)
        hemoglobin = max(6.0, min(18.0, hemoglobin))

        # ── Prior admissions ──────────────────────────────────────────────────
        # Source: Krumholz HM et al. Circ Heart Fail 2009;2(5):543-550.
        prior_hf_admissions_1yr = rng_admit.choices([0,1,2,3,4],
                                    weights=[0.38,0.30,0.18,0.09,0.05], k=1)[0]
        prior_any_admissions_1yr = prior_hf_admissions_1yr + rng_admit.choices([0,1,2],
                                    weights=[0.55,0.30,0.15], k=1)[0]
        index_los_days = rng_admit.choices([1,2,3,4,5,6,7,8,9,10,11,12,13,14],
                          weights=[0.04,0.10,0.16,0.18,0.16,0.12,0.09,0.06,0.04,0.02,0.01,0.01,0.005,0.005],
                          k=1)[0]

        # ── Medications ───────────────────────────────────────────────────────
        med_profile = MEDS_BY_PHENOTYPE[hf_pheno]
        medications = {med: rng_meds.random() < prob for med, prob in med_profile.items()}

        device_profile = DEVICE_RATES[hf_pheno]
        devices = {dev: rng_meds.random() < prob for dev, prob in device_profile.items()}

        # ── Risk scores ───────────────────────────────────────────────────────
        maggic = compute_maggic_risk(
            age=age, ef=ejection_fraction, nyha=nyha_class, systolic_bp=sbp,
            bmi=bmi, creatinine=creatinine,
            diabetes=comorbidities.get("type2_diabetes", False),
            copd=comorbidities.get("copd", False),
            afib=comorbidities.get("afib", False),
            non_smoker=True
        )

        readmit_30d = compute_readmission_risk_30d(
            nyha=nyha_class, stage=hf_stage,
            ckd=comorbidities.get("ckd", False),
            afib=comorbidities.get("afib", False),
            sodium=sodium,
            prior_admissions=prior_hf_admissions_1yr,
            age=age
        )

        # CHA2DS2-VASc for afib patients
        cha2ds2_vasc = 0
        if comorbidities.get("afib"):
            if comorbidities.get("stroke_tia_history"): cha2ds2_vasc += 2
            if age >= 75: cha2ds2_vasc += 2
            elif age >= 65: cha2ds2_vasc += 1
            if comorbidities.get("type2_diabetes"): cha2ds2_vasc += 1
            if comorbidities.get("hypertension"): cha2ds2_vasc += 1
            if sex == "female": cha2ds2_vasc += 1
            cha2ds2_vasc += 1  # HF itself

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

            # CHF extension fields
            "cohort_label":             label,
            "anchor_hash":              anchor,

            # HF phenotype
            "hf_phenotype":             hf_pheno,
            "ejection_fraction_pct":    ejection_fraction,
            "nyha_class":               nyha_class,
            "acc_aha_stage":            hf_stage,
            "hf_etiology":              hf_etiology,

            # Vitals
            "systolic_bp_mmhg":         sbp,
            "heart_rate_bpm":           hr,
            "spo2_pct":                 spo2,
            "acute_weight_gain_kg":     weight_gain_kg,

            # Comorbidities
            "hypertension":             comorbidities["hypertension"],
            "type2_diabetes":           comorbidities["type2_diabetes"],
            "ckd":                      comorbidities["ckd"],
            "afib":                     comorbidities["afib"],
            "copd":                     comorbidities["copd"],
            "cad":                      comorbidities["cad"],
            "prior_mi":                 comorbidities["prior_mi"],
            "prior_cabg_or_pci":        comorbidities["prior_cabg_or_pci"],
            "anemia":                   comorbidities["anemia"],
            "sleep_apnea":              comorbidities["sleep_apnea"],
            "depression":               comorbidities["depression"],
            "peripheral_vascular_disease": comorbidities["peripheral_vascular_disease"],
            "stroke_tia_history":       comorbidities["stroke_tia_history"],

            # Labs
            "bnp_pgml":                 bnp,
            "ntprobnp_pgml":            ntprobnp,
            "troponin_i_hs_ngl":        troponin_i_hs,
            "troponin_elevated":        troponin_elevated,
            "sodium_meql":              sodium,
            "creatinine_mgdl":          creatinine,
            "egfr_ml_min_173m2":        egfr,
            "potassium_meql":           potassium,
            "hemoglobin_gdl":           hemoglobin,

            # Admissions
            "prior_hf_admissions_1yr":  prior_hf_admissions_1yr,
            "prior_any_admissions_1yr": prior_any_admissions_1yr,
            "index_los_days":           index_los_days,

            # Medications
            "med_acei_arb_arni":        medications["acei_arb_arni"],
            "med_beta_blocker":         medications["beta_blocker"],
            "med_mra":                  medications["mra"],
            "med_sglt2i":               medications["sglt2i"],
            "med_loop_diuretic":        medications["loop_diuretic"],
            "med_digoxin":              medications["digoxin"],
            "med_anticoagulant":        medications["anticoagulant"],
            "med_statin":               medications["statin"],

            # Devices
            "device_icd":               devices["icd"],
            "device_crt_d":             devices["crt_d"],
            "device_lvad":              devices["lvad"],

            # Risk scores
            "maggic_1yr_risk_score":    maggic,
            "readmission_risk_30d":     readmit_30d,
            "cha2ds2_vasc":             cha2ds2_vasc if comorbidities.get("afib") else None,
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

    json_path = os.path.join(output_dir, f"{prefix}_n{n}.json")
    try:
        with open(json_path, "w") as f:
            json.dump({
                "module": MODULE_NAME, "n": n,
                "engine_version": ENGINE_VERSION, "anchor_hash": anchor,
                "patients": patients
            }, f, indent=2, default=str)
    except OSError as e:
        raise CohortSaveError(f"Cannot write JSON cohort {json_path}: {e}") from e

    csv_path = os.path.join(output_dir, f"{prefix}_n{n}.csv")
    if patients:
        try:
            with open(csv_path, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=list(patients[0].keys()))
                writer.writeheader()
                writer.writerows(patients)
        except OSError as e:
            raise CohortSaveError(f"Cannot write CSV cohort {csv_path}: {e}") from e

    manifest_path = os.path.join(output_dir, f"{prefix}_manifest.json")
    manifest = {
        "module": MODULE_NAME, "n": n,
        "engine_version": ENGINE_VERSION, "anchor_hash": anchor,
        "generated_utc": datetime.utcnow().isoformat() + "Z",
        "files": {"json": os.path.basename(json_path), "csv": os.path.basename(csv_path)},
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

    print("Generating CHF HuggingFace cohort (n=50, seed=4001)...")
    pts_50, anchor_50 = generate_chf_cohort(seed=4001, n=50, label="us_chf_hf_public")
    j50, c50, m50 = save_cohort(pts_50, anchor_50,
                                 os.path.join(BASE, "chf_50"),
                                 "chf_hf_public")
    print(f"  JSON:   {j50}\n  Anchor: {anchor_50[:32]}...")

    print("Generating CHF calibration cohort (n=1000, seed=4002)...")
    pts_1k, anchor_1k = generate_chf_cohort(seed=4002, n=1000, label="us_chf_calibration")
    j1k, c1k, m1k = save_cohort(pts_1k, anchor_1k,
                                  os.path.join(BASE, "chf_1000"),
                                  "chf_calibration")
    print(f"  JSON:   {j1k}\n  Anchor: {anchor_1k[:32]}...")
    print("CHF module complete.")
