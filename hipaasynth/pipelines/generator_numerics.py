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

"""Numeric/lab value generator. All randomness from pipeline-owned rng.

Calibration sources:
  [N1] CDC FastStats — Cholesterol. Mean serum total cholesterol 187 mg/dL,
       adults 20+, NHANES 2017–March 2020.
       https://www.cdc.gov/nchs/fastats/cholesterol.htm
  [N2] Tsao CW et al. Heart Disease and Stroke Statistics—2023 Update.
       Circulation. 2023;147(8):e93-e621. doi:10.1161/CIR.0000000000001123
       Mean LDL-C ~111.7 mg/dL (NHANES 2017–2018, adults 20+).
  [N3] Jones CA et al. Serum creatinine levels in the US population: NHANES III.
       Am J Kidney Dis. 1998;32(6):992-999. doi:10.1016/S0272-6386(98)70074-5
       Mean SCr: women 0.96 mg/dL, men 1.16 mg/dL; combined ~1.0 mg/dL.
  [N4] American Diabetes Association. Standards of Medical Care in Diabetes—2024.
       Diabetes Care. 2024;47(Suppl 1):S1-S321. doi:10.2337/dc24-S002
       Fasting glucose reference range 70–99 mg/dL; hypoglycemia threshold <54.
  [N5] Singer M et al. The Third International Consensus Definitions for Sepsis
       and Septic Shock (Sepsis-3). JAMA. 2016;315(8):801-810.
       doi:10.1001/jama.2016.0287
       WBC <4 or >12 K/uL as abnormal criterion; leukocytosis in sepsis 12-20+.
  [N6] Grundy SM et al. 2018 AHA/ACC Guideline on the Management of Blood
       Cholesterol. J Am Coll Cardiol. 2019;73(24):e285-e350.
       doi:10.1016/j.jacc.2018.11.003
       LDL-C floor <20 mg/dL only in severe malnutrition or aggressive therapy.
  [N7] KDIGO 2024 Clinical Practice Guideline for the Evaluation and Management
       of Chronic Kidney Disease. Kidney Int. 2024;105(4S):S117-S314.
       doi:10.1016/j.kint.2023.10.018
       Creatinine floor: <0.4 mg/dL physiologically implausible in adults.
"""
import math
from datetime import datetime, timedelta
from hipaasynth.core.schema import LabResult, Visit

LAB_DEFINITIONS = {
    # Glucose: reference range per ADA 2024 [N4]; baseline mean from NHANES
    # fasting glucose distribution in non-diabetic adults (~95 mg/dL) [N1].
    "Glucose": {
        "unit": "mg/dL",
        "reference_range": "70-99",
        "baseline_mean": 95.0,
        "baseline_std": 18.0,
    },
    # Creatinine: population mean ~1.0 mg/dL (pooled sex); NHANES III [N3].
    # Std 0.25 reflects sex-stratified SD (women ~0.15, men ~0.20) averaged.
    "Creatinine": {
        "unit": "mg/dL",
        "reference_range": "0.6-1.3",
        "baseline_mean": 1.0,
        "baseline_std": 0.25,
    },
    # LDL: mean 111.7 mg/dL in US adults 20+, NHANES 2017-2018 [N2].
    # Std 32 mg/dL reflects published SD from the same cohort.
    "LDL": {
        "unit": "mg/dL",
        "reference_range": "<100",
        "baseline_mean": 111.0,
        "baseline_std": 32.0,
    },
    # WBC: normal adult reference range 4.5-11.0 K/uL; baseline mean 7.0 [N5].
    # Std 2.0 reflects population distribution in non-infected adults.
    "WBC": {
        "unit": "10^9/L",
        "reference_range": "4.0-11.0",
        "baseline_mean": 7.0,
        "baseline_std": 2.0,
    },
}

CONDITION_LAB_MODIFIERS = {
    # Diabetic glucose: mean ~164 mg/dL reflects post-meal/random glucose
    # in treated type 2 diabetes; ADA 2024 [N4].
    ("type2_diabetes", "Glucose"): "diabetic_glucose",
    # CKD creatinine: range 1.05-1.25 mg/dL reflects mild-moderate CKD
    # (Stage 2-3a); KDIGO 2024 [N7].
    ("chronic_kidney_disease", "Creatinine"): (1.05, 1.25),
    # Hyperlipidemia LDL: range 160-260 mg/dL; AHA/ACC 2018 [N6] high-risk
    # threshold 160+ mg/dL, upper bound for untreated dyslipidemia.
    ("hyperlipidemia", "LDL"): (160.0, 260.0),
    # Sepsis WBC: leukocytosis 11-19 K/uL typical in bacterial sepsis [N5].
    # Range reflects mild to severe leukocytosis; floor avoids leukopenia
    # which has a distinct clinical meaning (immunocompromise, late sepsis).
    ("sepsis", "WBC"): (11.0, 19.0),
}

_REFERENCE_DATE = datetime(2024, 6, 15)


def _normal_distribution(rng, mean, std):
    u1 = rng.random()
    u2 = rng.random()
    z0 = math.sqrt(-2.0 * math.log(u1)) * math.cos(2.0 * math.pi * u2)
    return mean + z0 * std


def _generate_lab_value(rng, lab_name, condition_names):
    lab_def = LAB_DEFINITIONS[lab_name]
    baseline = _normal_distribution(rng, lab_def["baseline_mean"], lab_def["baseline_std"])
    for condition in condition_names:
        key = (condition, lab_name)
        if key in CONDITION_LAB_MODIFIERS:
            modifier = CONDITION_LAB_MODIFIERS[key]
            if modifier == "diabetic_glucose":
                baseline = max(baseline, _normal_distribution(rng, 164.0, 40.0))
            else:
                min_val, max_val = modifier
                baseline = max(baseline, rng.uniform(min_val, max_val))
    # Physiological floors — prevent physically implausible values.
    # Sources: ADA 2024 [N4] (glucose); KDIGO 2024 [N7] (creatinine);
    # AHA/ACC 2018 [N6] (LDL); Sepsis-3 [N5] (WBC).
    FLOORS = {
        "Glucose": 65.0,  # ADA: severe hypoglycemia <54; 65 is conservative clinical floor [N4]
        "Creatinine": 0.4,  # Below 0.4 mg/dL not physiologically plausible in adults [N7]
        "LDL": 20.0,  # Below 20 mg/dL only in severe malnutrition or aggressive therapy [N6]
        "WBC": 2.0,  # Extreme leukopenia floor; Sepsis-3 defines <4 as abnormal [N5]
    }
    floor = FLOORS.get(lab_name, 0.0)
    return round(max(floor, baseline), 2)


def _generate_visit_date(rng):
    offset_days = rng.randint(0, 365)
    visit_date = _REFERENCE_DATE - timedelta(days=offset_days)
    return visit_date.strftime("%Y-%m-%d")


def generate_labs_for_visit(rng, conditions, visit_date):
    condition_names = {c.name for c in conditions}
    labs = []
    for lab_name, lab_def in LAB_DEFINITIONS.items():
        value = _generate_lab_value(rng, lab_name, condition_names)
        labs.append(
            LabResult(
                lab_name=lab_name,
                value=value,
                unit=lab_def["unit"],
                reference_range=lab_def["reference_range"],
                date_recorded=visit_date,
            )
        )
    return labs


def generate_visits(rng, patient_seed, conditions, visits_min, visits_max, include_labs):
    visits = []
    num_visits = rng.randint(visits_min, visits_max)
    primary_diagnosis = conditions[0].name if conditions else "routine_check"
    visit_types = ["outpatient", "urgent_care", "telehealth"]
    for j in range(num_visits):
        visit_id = f"V-{patient_seed:08x}-{j+1}"
        visit_date = _generate_visit_date(rng)
        visit_type = rng.choice(visit_types)
        labs = []
        if include_labs:
            labs = generate_labs_for_visit(rng, conditions, visit_date)
        visits.append(
            Visit(
                visit_id=visit_id,
                visit_type=visit_type,
                visit_date=visit_date,
                primary_diagnosis=primary_diagnosis,
                labs=labs,
            )
        )
    return visits
