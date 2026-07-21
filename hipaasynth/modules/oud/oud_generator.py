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
HipAAsynth — Opioid Use Disorder (OUD) Module
===============================================
Generates deterministic synthetic OUD patient cohorts calibrated to:
  - SAMHSA NSDUH 2022 (National Survey on Drug Use and Health)
  - CDC Drug Overdose Surveillance 2022-2023
  - NIDA Opioid Overdose Crisis statistics
  - DSM-5-TR OUD diagnostic criteria
  - PCSS-MATS clinical guidance (buprenorphine/methadone/naltrexone)
  - ASAM Clinical Practice Guideline 2023 (OUD treatment)
  - AHRQ MOUD evidence review 2021
  - Rural-urban OUD disparity data (Mack KA et al. MMWR 2017)
  - IHS/tribal OUD burden (Sequist TD. NEJM 2021)

Critical gap targeted: Rural, IHS, and frontier OUD populations are
massively underrepresented in AI model training data. This module
specifically stress-tests AI models that were trained on urban/suburban
clinical datasets.

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
import os
import sys
from datetime import datetime

from hipaasynth.core.config import ENGINE_VERSION, SCHEMA_VERSION, DEFAULT_SYNTHETIC_DISCLAIMER
MODULE_NAME    = "oud"
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
# OUD prevalence: ~2.7M US adults meeting DSM-5 criteria (NSDUH 2022)
# Higher rural prevalence rates; AI/AN populations severely affected
# Source: SAMHSA. NSDUH 2022 Annual Report. HHS Publication No. PEP23-07-01-006.
PROFILE = {
    "label":     "us_oud_national",
    "source":    "SAMHSA NSDUH 2022, CDC Drug Overdose Surveillance 2023, NIDA",
    "age_range": (18, 65),
    "age_weights": {
        (18, 24): 0.15,
        (25, 34): 0.28,
        (35, 44): 0.25,
        (45, 54): 0.20,
        (55, 65): 0.12,
    },
    # OUD: slight male predominance but gap closing
    # Source: Substance Abuse and Mental Health Services Administration, 2022.
    "sex_dist": {"male": 0.57, "female": 0.43},
    # Rural/frontier overrepresentation
    "ethnicity": {
        "white":    0.68,
        "black":    0.12,
        "hispanic": 0.10,
        "asian":    0.02,
        "native":   0.06,    # AI/AN disproportionate burden
        "other":    0.02,
    },
    # Rurality distribution (OUD overrepresented in rural areas)
    # Source: Mack KA et al. MMWR 2017;66(19):506-512.
    "rurality": {
        "urban":    0.42,
        "suburban": 0.25,
        "rural":    0.22,
        "frontier": 0.11,    # <6 persons/sq mile; ND/WY/MT typical
    },
}

# ── DSM-5 OUD severity ────────────────────────────────────────────────────────
# Mild: 2-3 criteria; Moderate: 4-5; Severe: 6+
# Source: American Psychiatric Association. DSM-5-TR. 2022.
OUD_SEVERITY = {
    "mild":     0.18,
    "moderate": 0.28,
    "severe":   0.54,    # Most treatment-seeking patients are severe
}

# ── Primary opioid type ───────────────────────────────────────────────────────
# Source: Jones CM et al. Drug Alcohol Depend 2020;214:108174.
PRIMARY_OPIOID = {
    "heroin":                  0.28,
    "illicit_fentanyl":        0.35,    # Now dominant — polysubstance fentanyl
    "prescription_opioid":     0.22,    # Rx pain pills (oxycodone, hydrocodone)
    "fentanyl_analog":         0.08,    # Carfentanil, acetylfentanyl
    "methadone_illicit":       0.04,
    "other_opioid":            0.03,
}

# ── Route of administration ───────────────────────────────────────────────────
# Source: Cicero TJ et al. NEJM 2014;371(22):2063-2066.
ROUTE_OF_ADMIN = {
    "injection_iv":    0.32,
    "intranasal":      0.28,
    "smoking":         0.18,
    "oral":            0.16,
    "transdermal":     0.04,
    "other":           0.02,
}

# ── Years of opioid use ────────────────────────────────────────────────────────
YEARS_USE_BY_SEVERITY = {
    "mild":     (0.5, 4.0),
    "moderate": (1.0, 8.0),
    "severe":   (2.0, 20.0),
}

# ── MOUD (Medications for OUD) status ────────────────────────────────────────
# Treatment gap: ~18% of people with OUD receive MOUD
# Source: Jones CM et al. JAMA Psychiatry 2022;79(5):512-520.
MOUD_STATUS = {
    "buprenorphine":      0.12,    # Most accessible in primary care
    "methadone_otp":      0.05,    # Opioid Treatment Program (clinic-based)
    "naltrexone_oral":    0.02,
    "naltrexone_xr_im":   0.03,    # Vivitrol (monthly injection)
    "no_moud":            0.78,    # Treatment gap — critical AI validation target
}

# Buprenorphine dose ranges (mg/day)
BUPRENORPHINE_DOSE = (4.0, 32.0)    # Standard range; 16 mg/day mean
METHADONE_DOSE     = (20.0, 120.0)  # mg/day; mean ~75 mg

# ── Naloxone access ───────────────────────────────────────────────────────────
# Rural areas have significantly lower naloxone access
# Source: Rando J et al. J Rural Health 2021;37(3):526-534.
NALOXONE_ACCESS_BY_RURALITY = {
    "urban":    0.62,
    "suburban": 0.50,
    "rural":    0.32,
    "frontier": 0.18,    # Major gap — high AI validation interest
}

# ── Prior overdose history ────────────────────────────────────────────────────
# Source: Larochelle MR et al. Ann Intern Med 2018;169(3):137-145.
PRIOR_OVERDOSE_BY_SEVERITY = {
    "mild":     0.12,
    "moderate": 0.28,
    "severe":   0.52,
}

# ── Comorbidities ─────────────────────────────────────────────────────────────
# Source: Substance Abuse and Mental Health Services Administration, 2022.
#         Edelman EJ et al. Drug Alcohol Depend 2019;200:14-23.
COMORBIDITY_RATES = {
    "depression":              0.55,
    "anxiety":                 0.48,
    "ptsd":                    0.35,
    "bipolar_disorder":        0.18,
    "adhd":                    0.22,
    "schizophrenia_spectrum":  0.08,
    "alcohol_use_disorder":    0.38,
    "stimulant_use_disorder":  0.28,    # Co-occurring stimulant (meth, cocaine)
    "cannabis_use_disorder":   0.32,
    "tobacco_use_disorder":    0.72,    # Extremely high in OUD population
    "hepatitis_c":             0.38,    # PWID — injection-associated
    "hepatitis_b":             0.08,
    "hiv":                     0.06,
    "endocarditis_history":    0.05,    # IV drug use complication
    "chronic_pain":            0.55,    # Frequent precipitant
    "traumatic_brain_injury":  0.22,
    "homelessness_unstable_housing": 0.28,
    "incarceration_history":   0.38,
    "adverse_childhood_experiences": 0.72,  # ACEs strongly associated
}

# ── Social determinants ───────────────────────────────────────────────────────
EMPLOYMENT_STATUS = {
    "employed_full":   0.22,
    "employed_part":   0.14,
    "unemployed":      0.38,
    "disabled":        0.18,
    "other":           0.08,
}

INSURANCE_STATUS = {
    "medicaid":        0.42,    # Dominant payer for OUD treatment
    "medicare":        0.10,
    "commercial":      0.18,
    "uninsured":       0.24,
    "va_ihs":          0.06,
}

HOUSING_STATUS = {
    "stable_housed":   0.52,
    "unstable":        0.24,
    "shelter":         0.12,
    "unsheltered":     0.08,
    "unknown":         0.04,
}

# ── ED / hospitalization history ─────────────────────────────────────────────
# Source: White AM et al. Drug Alcohol Depend 2021;227:109002.
ED_VISITS_PRIOR_YR_BY_SEVERITY = {
    "mild":     (0, 2),
    "moderate": (0, 4),
    "severe":   (1, 8),
}

# ── Withdrawal severity (COWS score) ─────────────────────────────────────────
# Clinical Opiate Withdrawal Scale: 0-4 minimal, 5-12 mild, 13-24 moderate, 25-36 moderately severe, 36+ severe
# Source: Wesson DR, Ling W. J Psychoactive Drugs 2003;35(2):253-259.
COWS_BY_SEVERITY = {
    "mild":     (5,  18),
    "moderate": (10, 26),
    "severe":   (15, 36),
}

# ── Vital signs during active use / withdrawal ────────────────────────────────
def gen_vitals_oud(rng, cows_score):
    """Vitals calibrated to opioid withdrawal presentation."""
    # Tachycardia during withdrawal
    if cows_score >= 25:
        hr = round(rng.gauss(102, 14), 0)
    elif cows_score >= 13:
        hr = round(rng.gauss(92, 12), 0)
    else:
        hr = round(rng.gauss(82, 10), 0)
    hr = max(50.0, min(140.0, hr))

    # BP elevation during withdrawal
    if cows_score >= 25:
        sbp = round(rng.gauss(148, 22), 0)
    elif cows_score >= 13:
        sbp = round(rng.gauss(132, 18), 0)
    else:
        sbp = round(rng.gauss(118, 16), 0)
    sbp = max(80.0, min(200.0, sbp))

    # RR elevation
    if cows_score >= 13:
        rr = round(rng.gauss(20, 4), 0)
    else:
        rr = round(rng.gauss(16, 3), 0)
    rr = max(10.0, min(36.0, rr))

    temp = round(rng.gauss(37.2, 0.5), 1)
    temp = max(36.0, min(39.5, temp))

    return hr, sbp, rr, temp

# ── Labs ──────────────────────────────────────────────────────────────────────
def gen_labs_oud(rng, hcv, hiv, iv_use, comorbidities):
    # ALT/AST elevated in HCV and heavy alcohol use
    liver_risk = hcv or comorbidities.get("alcohol_use_disorder", False)
    alt = round(rng.uniform(8, 280) if liver_risk else rng.uniform(8, 45), 1)
    ast = round(rng.uniform(10, 250) if liver_risk else rng.uniform(10, 40), 1)

    # CMP
    creatinine = round(rng.gauss(0.95, 0.25), 2)
    creatinine = max(0.4, min(6.0, creatinine))
    sodium     = round(rng.gauss(139, 4.0), 1)
    sodium     = max(122.0, min(150.0, sodium))
    potassium  = round(rng.gauss(3.8, 0.5), 1)
    potassium  = max(2.5, min(6.5, potassium))

    # Hemoglobin (anemia common in PWID/HCV)
    hgb = round(rng.gauss(11.8 if (hcv or iv_use) else 13.2, 2.0), 1)
    hgb = max(6.0, min(18.0, hgb))

    # WBC (endocarditis, infection)
    wbc = round(rng.gauss(10.5 if comorbidities.get("endocarditis_history") else 8.2, 2.5), 1)
    wbc = max(2.0, min(30.0, wbc))

    # Urine drug screen positive (reflects current use pattern)
    uds_opioid     = True
    uds_benzo      = rng.random() < 0.38    # Common co-use; overdose risk amplified
    uds_stimulant  = rng.random() < 0.28
    uds_cannabis   = rng.random() < 0.45
    uds_alcohol    = rng.random() < 0.35

    return {
        "alt_ul": alt, "ast_ul": ast,
        "creatinine_mgdl": creatinine, "sodium_meql": sodium,
        "potassium_meql": potassium, "hemoglobin_gdl": hgb,
        "wbc_per_nl": wbc,
        "uds_opioid": uds_opioid, "uds_benzodiazepine": uds_benzo,
        "uds_stimulant": uds_stimulant, "uds_cannabis": uds_cannabis,
        "uds_alcohol": uds_alcohol,
    }

def gen_anthropometrics(rng, sex):
    if sex == "male":
        height = rng.gauss(176.0, 7.5)
        weight = rng.gauss(78.0, 18.0)   # Slightly lower than general population
    else:
        height = rng.gauss(162.5, 6.5)
        weight = rng.gauss(66.0, 17.0)
    height = max(148.0, min(204.0, round(height, 1)))
    weight = max(38.0,  min(155.0, round(weight, 1)))
    bmi    = round(weight / ((height/100)**2), 1)
    if bmi < 18.5:   bmi_cat = "Underweight"
    elif bmi < 25.0: bmi_cat = "Normal weight"
    elif bmi < 30.0: bmi_cat = "Overweight"
    else:            bmi_cat = "Obese"
    return height, weight, bmi, bmi_cat

def make_patient_id(rng):
    hex_part = ''.join(rng.choices('0123456789abcdef', k=8))
    return f"SYN-OUD-{hex_part}"

# ── Core generator ────────────────────────────────────────────────────────────
def generate_oud_cohort(seed: int, n: int, label: str = "us_oud_national") -> tuple:
    anchor = make_anchor(seed, MODULE_NAME, n)

    rng_demo  = derive_rng(anchor, "demographics")
    rng_clin  = derive_rng(anchor, "clinical")
    rng_comor = derive_rng(anchor, "comorbidities")
    rng_sdoh  = derive_rng(anchor, "social_determinants")
    rng_labs  = derive_rng(anchor, "labs")
    rng_meds  = derive_rng(anchor, "medications")
    rng_hist  = derive_rng(anchor, "history")
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

        rural_list = list(PROFILE["rurality"].keys())
        rural_wts  = list(PROFILE["rurality"].values())
        rurality   = rng_demo.choices(rural_list, weights=rural_wts, k=1)[0]

        # ── OUD severity and history ──────────────────────────────────────────
        sev_list  = list(OUD_SEVERITY.keys())
        sev_wts   = list(OUD_SEVERITY.values())
        severity  = rng_clin.choices(sev_list, weights=sev_wts, k=1)[0]

        dsm5_criteria_count = {
            "mild":     rng_clin.randint(2, 3),
            "moderate": rng_clin.randint(4, 5),
            "severe":   rng_clin.randint(6, 11),
        }[severity]

        opioid_list  = list(PRIMARY_OPIOID.keys())
        opioid_wts   = list(PRIMARY_OPIOID.values())
        primary_opioid = rng_clin.choices(opioid_list, weights=opioid_wts, k=1)[0]

        route_list  = list(ROUTE_OF_ADMIN.keys())
        route_wts   = list(ROUTE_OF_ADMIN.values())
        route       = rng_clin.choices(route_list, weights=route_wts, k=1)[0]
        iv_use      = route == "injection_iv"

        yrs_min, yrs_max = YEARS_USE_BY_SEVERITY[severity]
        years_of_use     = round(rng_clin.uniform(yrs_min, yrs_max), 1)

        # ── MOUD ──────────────────────────────────────────────────────────────
        moud_list = list(MOUD_STATUS.keys())
        moud_wts  = list(MOUD_STATUS.values())
        moud      = rng_meds.choices(moud_list, weights=moud_wts, k=1)[0]

        bup_dose_mgd  = round(rng_meds.uniform(*BUPRENORPHINE_DOSE), 1) if moud == "buprenorphine" else None
        meth_dose_mgd = round(rng_meds.uniform(*METHADONE_DOSE), 1)     if moud == "methadone_otp" else None

        # Naloxone access depends on rurality
        naloxone_access = rng_meds.random() < NALOXONE_ACCESS_BY_RURALITY[rurality]

        # ── Prior overdoses ───────────────────────────────────────────────────
        prior_od_rate = PRIOR_OVERDOSE_BY_SEVERITY[severity]
        prior_overdose = rng_hist.random() < prior_od_rate
        prior_od_count = rng_hist.randint(1, 4) if prior_overdose else 0

        prior_od_naloxone_reversed = prior_overdose and (rng_hist.random() < 0.62)

        # ── Comorbidities ─────────────────────────────────────────────────────
        comorbidities = {}
        for cond, rate in COMORBIDITY_RATES.items():
            # IV use amplifies HCV, endocarditis risk
            if cond == "hepatitis_c" and iv_use:
                adjusted = min(rate * 1.8, 0.95)
            elif cond == "endocarditis_history" and iv_use:
                adjusted = min(rate * 2.2, 0.30)
            elif cond == "hiv" and iv_use:
                adjusted = min(rate * 1.5, 0.20)
            # Frontier/rural: higher ACEs, incarceration, trauma
            elif cond in ("adverse_childhood_experiences","incarceration_history") and rurality in ("rural","frontier"):
                adjusted = min(rate * 1.15, 0.95)
            else:
                adjusted = rate
            comorbidities[cond] = rng_comor.random() < adjusted

        condition_list = ["opioid_use_disorder"] + [c for c, v in comorbidities.items() if v]

        # ── Social determinants ───────────────────────────────────────────────
        emp_list = list(EMPLOYMENT_STATUS.keys())
        emp_wts  = list(EMPLOYMENT_STATUS.values())
        employment = rng_sdoh.choices(emp_list, weights=emp_wts, k=1)[0]

        ins_list = list(INSURANCE_STATUS.keys())
        ins_wts  = list(INSURANCE_STATUS.values())
        insurance = rng_sdoh.choices(ins_list, weights=ins_wts, k=1)[0]

        house_list = list(HOUSING_STATUS.keys())
        house_wts  = list(HOUSING_STATUS.values())
        housing    = rng_sdoh.choices(house_list, weights=house_wts, k=1)[0]

        # Distance to nearest MOUD provider (rural/frontier critical metric)
        # Source: Andrilla CHA et al. J Rural Health 2019;35(1):8-25.
        dist_to_moud = {
            "urban":    round(rng_sdoh.uniform(0.5, 8.0), 1),
            "suburban": round(rng_sdoh.uniform(2.0, 20.0), 1),
            "rural":    round(rng_sdoh.uniform(15.0, 65.0), 1),
            "frontier": round(rng_sdoh.uniform(40.0, 180.0), 1),
        }[rurality]

        # ── Withdrawal score ──────────────────────────────────────────────────
        cows_min, cows_max = COWS_BY_SEVERITY[severity]
        cows_score = rng_clin.randint(cows_min, cows_max)

        # ── Vitals ────────────────────────────────────────────────────────────
        hr, sbp, rr, temp = gen_vitals_oud(rng_clin, cows_score)

        # ── Labs ──────────────────────────────────────────────────────────────
        height, weight, bmi, bmi_cat = gen_anthropometrics(rng_demo, sex)
        labs = gen_labs_oud(rng_labs, comorbidities["hepatitis_c"],
                            comorbidities["hiv"], iv_use, comorbidities)

        # ── ED/hospitalization history ────────────────────────────────────────
        ed_min, ed_max = ED_VISITS_PRIOR_YR_BY_SEVERITY[severity]
        ed_visits_1yr  = rng_hist.randint(ed_min, ed_max)
        hx_inpatient_detox = rng_hist.random() < (0.12 if severity=="mild" else 0.28 if severity=="moderate" else 0.48)
        hx_residential_tx  = rng_hist.random() < (0.08 if severity=="mild" else 0.18 if severity=="moderate" else 0.35)

        # ── Fentanyl exposure risk ────────────────────────────────────────────
        # Illicit fentanyl now contaminates most illicit opioid supply
        # Source: CDC. Drug Overdose Deaths. 2023.
        fentanyl_exposure_risk = primary_opioid in ("illicit_fentanyl","fentanyl_analog","heroin")

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

            # OUD extension fields
            "cohort_label":         label,
            "anchor_hash":          anchor,
            "rurality":             rurality,

            # OUD clinical
            "oud_severity":         severity,
            "dsm5_criteria_count":  dsm5_criteria_count,
            "primary_opioid":       primary_opioid,
            "route_of_admin":       route,
            "iv_drug_use":          iv_use,
            "years_of_opioid_use":  years_of_use,
            "fentanyl_exposure_risk": fentanyl_exposure_risk,
            "cows_score":           cows_score,

            # MOUD
            # moud_type: the specific medication (or "no_moud" if untreated)
            # moud_current: clean boolean — True means the patient is on MOUD.
            # Use moud_current for boolean checks; "no_moud" is truthy in Python
            # and would silently count untreated patients as treated.
            "moud_type":            moud,
            "moud_current":         moud != "no_moud",
            "buprenorphine_dose_mgd": bup_dose_mgd,
            "methadone_dose_mgd":   meth_dose_mgd,
            "naloxone_access":      naloxone_access,
            "distance_to_moud_provider_miles": dist_to_moud,

            # Prior history
            "prior_overdose":       prior_overdose,
            "prior_overdose_count": prior_od_count,
            "prior_od_naloxone_reversed": prior_od_naloxone_reversed,
            "ed_visits_prior_yr":   ed_visits_1yr,
            "hx_inpatient_detox":   hx_inpatient_detox,
            "hx_residential_tx":    hx_residential_tx,

            # Vitals (withdrawal presentation)
            "heart_rate_bpm":       hr,
            "systolic_bp_mmhg":     sbp,
            "resp_rate":            rr,
            "temperature_c":        temp,

            # Labs
            "alt_ul":               labs["alt_ul"],
            "ast_ul":               labs["ast_ul"],
            "creatinine_mgdl":      labs["creatinine_mgdl"],
            "sodium_meql":          labs["sodium_meql"],
            "potassium_meql":       labs["potassium_meql"],
            "hemoglobin_gdl":       labs["hemoglobin_gdl"],
            "wbc_per_nl":           labs["wbc_per_nl"],
            "uds_opioid":           labs["uds_opioid"],
            "uds_benzodiazepine":   labs["uds_benzodiazepine"],
            "uds_stimulant":        labs["uds_stimulant"],
            "uds_cannabis":         labs["uds_cannabis"],
            "uds_alcohol":          labs["uds_alcohol"],

            # Comorbidities
            "depression":           comorbidities["depression"],
            "anxiety":              comorbidities["anxiety"],
            "ptsd":                 comorbidities["ptsd"],
            "bipolar_disorder":     comorbidities["bipolar_disorder"],
            "alcohol_use_disorder": comorbidities["alcohol_use_disorder"],
            "stimulant_use_disorder": comorbidities["stimulant_use_disorder"],
            "tobacco_use_disorder": comorbidities["tobacco_use_disorder"],
            "hepatitis_c":          comorbidities["hepatitis_c"],
            "hiv":                  comorbidities["hiv"],
            "endocarditis_history": comorbidities["endocarditis_history"],
            "chronic_pain":         comorbidities["chronic_pain"],
            "adverse_childhood_experiences": comorbidities["adverse_childhood_experiences"],

            # Social determinants
            "employment_status":    employment,
            "insurance_status":     insurance,
            "housing_status":       housing,
            "incarceration_history": comorbidities["incarceration_history"],
            "homelessness_unstable_housing": comorbidities["homelessness_unstable_housing"],
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

    print("Generating OUD HuggingFace cohort (n=50, seed=5001)...")
    pts_50, anchor_50 = generate_oud_cohort(seed=5001, n=50, label="us_oud_hf_public")
    j50, c50, m50 = save_cohort(pts_50, anchor_50,
                                 os.path.join(BASE, "oud_50"),
                                 "oud_hf_public")
    print(f"  JSON:   {j50}\n  Anchor: {anchor_50[:32]}...")

    print("Generating OUD calibration cohort (n=1000, seed=5002)...")
    pts_1k, anchor_1k = generate_oud_cohort(seed=5002, n=1000, label="us_oud_calibration")
    j1k, c1k, m1k = save_cohort(pts_1k, anchor_1k,
                                  os.path.join(BASE, "oud_1000"),
                                  "oud_calibration")
    print(f"  JSON:   {j1k}\n  Anchor: {anchor_1k[:32]}...")
    print("OUD module complete.")
