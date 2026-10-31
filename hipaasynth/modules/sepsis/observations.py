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

"""Deterministic sepsis observation generator — HipAAsynth v1.0.3

This is a real engine extension: it generates synthetic sepsis observation fields
inside the engine using the patient RNG and already-generated patient state.
It does not consume external APIs and does not change the anchor-rooted RNG path.

Important boundary:
- These values are synthetic modeled observations.
- They are clinically anchored by sepsis threshold logic, but they are not claimed
  to be region-validated epidemiologic estimates.

Calibration sources:
  [S1] Singer M et al. Sepsis-3. JAMA. 2016;315(8):801-810.
  [S2] Gavazzi G, Krause KH. Lancet Infect Dis. 2002;2(11):659-666. (Afebrile elderly)
  [S3] Novosad SA et al. Vital Signs: Epidemiology of Sepsis. MMWR 2016;65(33):864-869
       (PMID 27559759): adult sources pneumonia 35%, urinary 25%, GI 11%, skin/soft tissue 11%.
  [S4] Evans L et al. Surviving Sepsis Campaign 2021. Crit Care Med. 2021;49(11):e1063-e1143.
       Initial fluid resuscitation 30 mL/kg; vasopressor targets; O2 management.
  [S5] Frat JP et al. NEJM. 2015;372(23):2185-2196. (HFNC vs NIV in hypoxemic ARF)
  [S6] Bellani G et al. JAMA. 2016;315(8):788-800. (LUNG SAFE: ventilation modes)
  [S7] KDIGO Clinical Practice Guideline for Acute Kidney Injury. Kidney Int Suppl
       2012;2(1):1-138: oliguria criterion urine output < 0.5 mL/kg/h.
  [S8] Cecconi M et al. Intensive Care Med. 2014;40(12):1795-1815. (Fluid balance)
  [S9] Internal calibration review, 2026-04-22.
       Respiratory context, urine output, fluid balance, deterioration realism,
       floor artefact reduction, contradictory bedside signals.
  [S10] O'Driscoll BR et al. Thorax. 2017;72(Suppl 1):ii1-ii90. (BTS O2 guidelines)
        GOLD 2024. Target SpO2 88-92% in COPD; avoid hypercapnic drive suppression.

Changes in v1.0.2 (internal review 2026 [S9]):
  - Added oxygen_device, fio2_percent, ventilation_mode fields.
  - Added urine_output_ml_hr, fluid_input_6h_ml, fluid_balance_6h_ml fields.
  - Added deterioration_pattern field (gradual/sudden/stable_then_crash/fluctuating).
  - Added contradictory signal flags: cryptic_shock_flag,
    normal_wbc_elevated_lactate_flag, afebrile_tachycardic_flag.
  - Glucose floor jitter: values clamped at floor now randomised ±2 to reduce
    exact floor artefact.
  - observation_hook_version updated to sepsis_generator_v3_bedside.

Changes in v1.0.3 (internal review 2026 [S9][S10]):
  - ventilation_mode now populated for NRB (NRB / NRB_escalation_indicated when
    FiO2 >= 70%) and HFNC (HFNC), resolving gap flagged in bedside review.
  - Vasopressor probability tightened: severe oliguria (<0.3 mL/kg/hr) combined
    with lactate >= 2.0 and/or DM+HTN+CKD stack now materially increases pressor
    likelihood, closing the clinically implausible no-pressor-in-shock gap.
  - Added spo2_target_range field: COPD patients assigned 88-92 per BTS/GOLD [S10];
    all others 94-98. Provides context for SpO2 interpretation at bedside.
  - UO computation moved before pressor logic to allow oliguria-informed probability.
"""
from __future__ import annotations

import math
from typing import Any
from hipaasynth.core.profile_loader import profile_rurality


def _clamp(value: float, low: float, high: float, digits: int = 1):
    return round(max(low, min(high, value)), digits)


def _normal(rng, mean: float, std: float) -> float:
    u1 = max(rng.random(), 1e-12)
    u2 = rng.random()
    z0 = math.sqrt(-2.0 * math.log(u1)) * math.cos(2.0 * math.pi * u2)
    return mean + z0 * std


def _lab_lookup(visits: list, lab_name: str):
    for visit in visits:
        for lab in getattr(visit, "labs", []):
            if getattr(lab, "lab_name", None) == lab_name:
                return getattr(lab, "value", None)
    return None


def _pick_infection_source(
    rng, age: int, sex: str, ckd: bool, diabetes: bool, copd: bool, rural: bool
) -> str:
    weights: list[list] = [
        ["pneumonia", 0.34],
        ["uti", 0.21],
        ["intra_abdominal", 0.16],
        ["skin_soft_tissue", 0.11],
        ["other", 0.18],
    ]
    if age >= 65:
        for row in weights:
            if row[0] == "uti":
                row[1] += 0.08
            if row[0] == "pneumonia":
                row[1] += 0.04
    if sex == "female":
        for row in weights:
            if row[0] == "uti":
                row[1] += 0.06
    if diabetes:
        for row in weights:
            if row[0] == "skin_soft_tissue":
                row[1] += 0.05
            if row[0] == "uti":
                row[1] += 0.02
    if copd:
        for row in weights:
            if row[0] == "pneumonia":
                row[1] += 0.08
    if ckd:
        for row in weights:
            if row[0] == "uti":
                row[1] += 0.03
    if rural:
        for row in weights:
            if row[0] == "pneumonia":
                row[1] += 0.02
    total = sum(w for _, w in weights)
    x = rng.random() * total
    acc = 0.0
    for label, weight in weights:
        acc += weight
        if x <= acc:
            return str(label)
    return str(weights[-1][0])


def _oxygen_support(
    rng, spo2: int, severity: float, copd: bool, chf: bool, infection_source: str
) -> tuple[str, float, Any]:
    """
    Determine oxygen device, FiO2, and ventilation mode based on SpO2 and severity.
    Returns (oxygen_device, fio2_percent, ventilation_mode).

    Sources: Surviving Sepsis Campaign 2021 [S4]; Frat 2015 [S5]; Bellani 2016 [S6].

    Clinical note: SpO2 without support context is meaningless in ICU.
    A 90% SpO2 on room air vs. HFNC at 80% FiO2 implies entirely different physiology.
    """
    if spo2 >= 95 and severity < 0.35:
        device = "nasal_cannula"
        fio2 = round(_clamp(_normal(rng, 30.0, 5.0), 24.0, 44.0), 0)
        mode = None
    elif spo2 >= 92 or severity < 0.50:
        r = rng.random()
        if r < 0.55:
            device = "simple_face_mask"
            fio2 = round(_clamp(_normal(rng, 42.0, 8.0), 35.0, 55.0), 0)
            mode = None
        else:
            device = "non_rebreather_mask"
            fio2 = round(_clamp(_normal(rng, 78.0, 8.0), 60.0, 95.0), 0)
            # FiO2 >= 70% on NRB: escalation to intubation typically considered [S4]
            mode = "NRB_escalation_indicated" if fio2 >= 70 else "NRB"
    elif spo2 >= 88 or severity < 0.65:
        r = rng.random()
        if r < 0.55:
            device = "high_flow_nasal_cannula"
            fio2 = round(_clamp(_normal(rng, 72.0, 12.0), 50.0, 100.0), 0)
            mode = "HFNC"
        else:
            device = "noninvasive_ventilation"
            fio2 = round(_clamp(_normal(rng, 65.0, 12.0), 40.0, 90.0), 0)
            mode = "BiPAP" if rng.random() < 0.65 else "CPAP"
    else:
        device = "mechanical_ventilation"
        fio2 = round(_clamp(_normal(rng, 80.0, 12.0), 50.0, 100.0), 0)
        mode = "CMV_AC" if rng.random() < 0.70 else "SIMV"

    # COPD: prefer NIV over mechanical when possible (avoid barotrauma)
    if copd and device == "mechanical_ventilation" and rng.random() < 0.30:
        device = "noninvasive_ventilation"
        mode = "BiPAP"
        fio2 = round(_clamp(_normal(rng, 55.0, 10.0), 35.0, 80.0), 0)

    return device, float(fio2), mode


def _urine_output(
    rng, weight_kg: float, severity: float, delayed_hypotension: bool, ckd: bool
) -> float:
    """
    Hourly urine output in mL/hr. Oliguria threshold: <0.5 mL/kg/hr [S7].
    Oliguria is a key early marker of renal hypoperfusion in sepsis.

    Source: Surviving Sepsis Campaign 2021 [S4]; see [S7].
    """
    oliguria_threshold = 0.5 * weight_kg
    if severity > 0.60 or (delayed_hypotension and severity > 0.40) or ckd:
        uo_mean = max(5.0, oliguria_threshold * (0.55 - 0.35 * severity))
        uo = _clamp(
            _normal(rng, uo_mean, max(4.0, uo_mean * 0.3)), 3.0, oliguria_threshold - 0.5, 1
        )
    else:
        uo_mean = oliguria_threshold + (1.0 - severity) * 35.0
        uo = _clamp(_normal(rng, uo_mean, 14.0), oliguria_threshold, 100.0, 1)
    return float(uo)


def _fluid_balance(
    rng, weight_kg: float, severity: float, ckd: bool, chf: bool, urine_output_ml_hr: float
) -> tuple[float, float]:
    """
    Returns (fluid_input_6h_ml, fluid_balance_6h_ml).
    Fluid input based on SSC 30 mL/kg resuscitation [S4]; conserved for CKD/CHF.
    Balance = input - (UO * 6 + estimated insensible losses).
    Source: Cecconi 2014 [S8]; Surviving Sepsis Campaign 2021 [S4].
    """
    if ckd or chf:
        input_mean = 1500.0 + severity * 800.0
        fluid_input = _clamp(_normal(rng, input_mean, 350.0), 500.0, 3000.0, 0)
    else:
        input_mean = 2800.0 + severity * 1800.0
        fluid_input = _clamp(_normal(rng, input_mean, 600.0), 800.0, 6500.0, 0)

    total_output_6h = urine_output_ml_hr * 6.0 + max(
        80.0, _clamp(_normal(rng, 220.0, 70.0), 80.0, 500.0, 0)
    )
    fluid_balance = round(fluid_input - total_output_6h, 0)
    return float(fluid_input), float(fluid_balance)


def build_sepsis_observations(
    *, rng, demographics, anthropometrics, conditions, visits, cfg
) -> dict[str, Any]:
    names = {c.name for c in conditions}
    age = demographics.age
    sex = demographics.sex
    age_group = "65_plus" if age >= 65 else "18_64"
    profile = getattr(cfg, "_resolved_profile", None) or {}
    region_label = profile.get("profile_name") if isinstance(profile, dict) else None
    rural = bool(profile_rurality(profile))

    has_sepsis = (cfg.required_condition == "sepsis") or ("sepsis" in names)
    diabetes = "type2_diabetes" in names
    hypertension = "hypertension" in names
    ckd = "chronic_kidney_disease" in names
    copd = "copd" in names
    chf = "congestive_heart_failure" in names
    obesity = anthropometrics.bmi >= 30.0
    weight_kg = anthropometrics.weight_kg
    first_visit = visits[0] if visits else None

    wbc = _lab_lookup(visits, "WBC")
    creatinine = _lab_lookup(visits, "Creatinine")
    glucose = _lab_lookup(visits, "Glucose")

    if not has_sepsis:
        return {
            "region_profile": region_label,
            "age_group": age_group,
            "sepsis_flag": False,
            "suspected_infection_source": None,
            "temperature_c_initial": None,
            "heart_rate_initial": None,
            "resp_rate_initial": None,
            "sbp_initial": None,
            "dbp_initial": None,
            "spo2_initial": None,
            "spo2_target_range": None,
            "oxygen_device": None,
            "fio2_percent": None,
            "ventilation_mode": None,
            "urine_output_ml_hr": None,
            "fluid_input_6h_ml": None,
            "fluid_balance_6h_ml": None,
            "wbc_initial": wbc,
            "creatinine_initial": creatinine,
            "glucose_initial": glucose,
            "lactate_initial": None,
            "diabetes_flag": diabetes,
            "hypertension_flag": hypertension,
            "ckd_flag": ckd,
            "dm_htn_ckd_stack_flag": diabetes and hypertension and ckd,
            "afebrile_flag": None,
            "altered_mental_status_only_flag": None,
            "delayed_hypotension_flag": None,
            "deterioration_pattern": None,
            "hours_to_hypotension": None,
            "hours_to_icu": None,
            "hours_to_vasopressors": None,
            "cryptic_shock_flag": None,
            "normal_wbc_elevated_lactate_flag": None,
            "afebrile_tachycardic_flag": None,
            "observation_hook_version": "sepsis_generator_v3_bedside",
            "unsupported_fields_emitted_as_null": False,
            "source_visit_id": getattr(first_visit, "visit_id", None),
            "source_visit_date": getattr(first_visit, "visit_date", None),
        }

    severity = 0.15
    severity += 0.18 if age >= 65 else 0.0
    severity += 0.10 if ckd else 0.0
    severity += 0.07 if diabetes else 0.0
    severity += 0.06 if hypertension else 0.0
    severity += 0.05 if copd else 0.0
    severity += 0.08 if chf else 0.0
    severity += 0.04 if obesity else 0.0
    severity += rng.random() * 0.18
    severity = min(severity, 0.88)

    afebrile_prob = 0.10 + (0.18 if age >= 65 else 0.0) + (0.05 if ckd else 0.0)
    afebrile_prob = min(afebrile_prob, 0.45)
    afebrile = rng.random() < afebrile_prob

    ams_prob = 0.08 + (0.20 if age >= 65 else 0.0) + (0.05 if ckd else 0.0) + (0.04 if chf else 0.0)
    ams_prob = min(ams_prob, 0.50)
    altered_mental_status = rng.random() < ams_prob

    delayed_hypotension_prob = (
        0.18 + (0.10 if age >= 65 else 0.0) + (0.04 if diabetes else 0.0) + (0.04 if ckd else 0.0)
    )
    delayed_hypotension_prob = min(delayed_hypotension_prob, 0.55)
    delayed_hypotension = rng.random() < delayed_hypotension_prob

    # ----------------------------------------------------------------
    # DETERIORATION PATTERN — internal review 2026 [S9]
    # Real ICU sepsis deterioration is not smooth or predictable.
    # Four archetypes modeled: gradual, sudden, deceptive stability, fluctuating.
    # ----------------------------------------------------------------
    r_deter = rng.random()
    if r_deter < 0.18:
        deterioration_pattern = "sudden_collapse"
    elif r_deter < 0.42:
        deterioration_pattern = "stable_then_crash"
    elif r_deter < 0.72:
        deterioration_pattern = "gradual_decline"
    else:
        deterioration_pattern = "fluctuating"

    # Sudden-collapse pattern: compress time-to-event fields dramatically
    sudden = deterioration_pattern == "sudden_collapse"

    if afebrile:
        temp = _clamp(_normal(rng, 37.1 + 0.3 * severity, 0.45), 35.4, 38.0)
    else:
        temp = _clamp(_normal(rng, 38.2 + 0.6 * severity, 0.5), 36.0, 40.8)

    heart_rate = int(
        round(max(82, min(156, _normal(rng, 101 + 22 * severity + (4 if temp >= 38.5 else 0), 10))))
    )
    resp_rate = int(
        round(max(20, min(38, _normal(rng, 22 + 8 * severity + (2 if copd else 0), 3.2))))
    )

    if delayed_hypotension:
        sbp = int(
            round(max(94, min(126, _normal(rng, 109 - 4 * severity - (5 if age >= 65 else 0), 7))))
        )
        if sudden:
            hours_to_hypotension = int(max(0, min(4, round(_normal(rng, 1.5, 1.0)))))
        else:
            hours_to_hypotension = int(
                max(1, min(24, round(_normal(rng, 7 + 8 * (1 - severity), 4.0))))
            )
    else:
        sbp = int(
            round(max(72, min(102, _normal(rng, 93 - 9 * severity - (4 if age >= 65 else 0), 7))))
        )
        if sudden:
            hours_to_hypotension = int(max(0, min(2, round(_normal(rng, 0.5, 0.5)))))
        else:
            hours_to_hypotension = int(
                max(0, min(8, round(_normal(rng, 2.0 + 3.5 * (1 - severity), 1.8))))
            )

    map_target = max(52, min(78, 64 - 5 * severity + (2 if delayed_hypotension else -2)))
    dbp = int(round(max(40, min(82, (3 * map_target - sbp) / 2))))

    baseline_spo2 = 95.0 - 2.6 * severity - (2.0 if copd else 0.0) - (1.0 if chf else 0.0)
    spo2 = int(round(max(84, min(99, _normal(rng, baseline_spo2, 2.2)))))

    # SpO2 target range — COPD: permissive hypoxemia per BTS/GOLD [S10].
    # A 93% SpO2 is stable for most patients but indicates risk in COPD
    # where suppression of hypercapnic drive can precipitate respiratory failure.
    spo2_target_range = "88-92" if copd else "94-98"

    wbc_initial = wbc
    if wbc_initial is None:
        wbc_initial = _clamp(_normal(rng, 11.5 + 4.0 * severity, 2.8), 3.0, 24.0, 1)
    else:
        wbc_initial = float(wbc_initial)

    creat_initial = creatinine
    if creat_initial is None:
        base_creat = 1.0 + 0.55 * severity + (0.7 if ckd else 0.0)
        creat_initial = _clamp(_normal(rng, base_creat, 0.35), 0.5, 5.5, 2)
    else:
        creat_initial = float(creat_initial)

    # ----------------------------------------------------------------
    # GLUCOSE — floor jitter applied to reduce exact floor artefact [S9]
    # ----------------------------------------------------------------
    glucose_initial = glucose
    if glucose_initial is None:
        glucose_mean = 118 + 36 * severity + (55 if diabetes else 0)
        glucose_raw = _normal(rng, glucose_mean, 28)
        if glucose_raw < 70.0:
            glucose_initial = round(70.0 + rng.random() * 4.5, 1)
        else:
            glucose_initial = _clamp(glucose_raw, 70, 430, 1)
    else:
        glucose_initial = float(glucose_initial)

    lactate_mean = (
        1.9 + 1.7 * severity + (0.4 if delayed_hypotension else 0.0) + (0.3 if ckd else 0.0)
    )
    lactate_initial = _clamp(_normal(rng, lactate_mean, 0.7), 0.8, 8.0, 2)

    # ----------------------------------------------------------------
    # URINE OUTPUT — computed here so oliguria can inform pressor logic [S7][S9]
    # Moved before ICU/pressor block in v1.0.3.
    # ----------------------------------------------------------------
    urine_output_ml_hr = _urine_output(rng, weight_kg, severity, delayed_hypotension, ckd)

    # ----------------------------------------------------------------
    # ICU TRANSFER AND VASOPRESSORS
    # ----------------------------------------------------------------
    icu_base = 1.0 + 6.0 * severity
    if sudden:
        hours_to_icu = int(max(0, min(4, round(_normal(rng, 0.8, 0.6)))))
    elif delayed_hypotension:
        hours_to_icu = int(max(0, min(12, round(_normal(rng, icu_base, 1.8)))))
    else:
        hours_to_icu = int(max(0, min(18, round(_normal(rng, icu_base + 2.0, 2.4)))))

    # Severe oliguria (<0.3 mL/kg/hr) with high lactate is a near-mandatory
    # pressor trigger; DM+HTN+CKD stack compounds the shock physiology [S4][S9].
    # Lactate >= 4.0 with any organ dysfunction: near-universal pressor requirement.
    severe_oliguria = urine_output_ml_hr < (0.3 * weight_kg)
    dm_htn_ckd = diabetes and hypertension and ckd
    pressor_probability = min(
        0.03
        + 0.60 * severity
        + (0.10 if lactate_initial >= 2.0 else 0.0)
        + (0.18 if (severe_oliguria and lactate_initial >= 2.0) else 0.0)
        + (0.12 if (dm_htn_ckd and lactate_initial >= 2.0) else 0.0)
        + (0.25 if lactate_initial >= 4.0 else 0.0),
        0.95,
    )
    if rng.random() < pressor_probability:
        pressor_base = 1.2 + 5.0 * severity + (2.5 if delayed_hypotension else 0.0)
        if sudden:
            pressor_base = max(0.5, pressor_base * 0.25)
        hours_to_vasopressors = int(max(0, min(24, round(_normal(rng, pressor_base, 2.0)))))
    else:
        hours_to_vasopressors = None

    infection_source = _pick_infection_source(rng, age, sex, ckd, diabetes, copd, rural)

    ams_only = altered_mental_status and afebrile and temp < 38.0

    # ----------------------------------------------------------------
    # RESPIRATORY SUPPORT CONTEXT — internal review 2026 [S9]
    # SpO2 alone is clinically uninterpretable without support device and FiO2.
    # Sources: SSC 2021 [S4]; Frat 2015 [S5]; Bellani 2016 [S6].
    # ----------------------------------------------------------------
    oxygen_device, fio2_percent, ventilation_mode = _oxygen_support(
        rng, spo2, severity, copd, chf, infection_source
    )

    # ----------------------------------------------------------------
    # FLUID BALANCE — internal review 2026 [S9]
    # UO already computed above (before pressor logic). Fluid balance needs RNG.
    # Sources: Cecconi 2014 [S8]; SSC 2021 [S4]; see [S7].
    # ----------------------------------------------------------------
    fluid_input_6h_ml, fluid_balance_6h_ml = _fluid_balance(
        rng, weight_kg, severity, ckd, chf, urine_output_ml_hr
    )

    # ----------------------------------------------------------------
    # CONTRADICTORY BEDSIDE SIGNALS — internal review 2026 [S9]
    # Real ICU sepsis often presents with conflicting data that forces
    # reassessment. These flags mark clinically coherent but contradictory
    # signal patterns that should not be "cleaned" by downstream models.
    # ----------------------------------------------------------------
    # Cryptic shock: preserved BP but tissue hypoperfusion (lactate ≥2)
    cryptic_shock = (
        (sbp >= 90) and (lactate_initial >= 2.0) and (not delayed_hypotension) and (severity > 0.45)
    )
    # Sepsis without leukocytosis (normal or low WBC)
    normal_wbc_elevated_lactate = (wbc_initial < 11.0) and (lactate_initial >= 2.0)
    # Afebrile but clearly tachycardic (atypical presentation, common in elderly)
    afebrile_tachycardic = afebrile and heart_rate >= 110

    return {
        "region_profile": region_label,
        "age_group": age_group,
        "sepsis_flag": True,
        "suspected_infection_source": infection_source,
        "temperature_c_initial": temp,
        "heart_rate_initial": heart_rate,
        "resp_rate_initial": resp_rate,
        "sbp_initial": sbp,
        "dbp_initial": dbp,
        "spo2_initial": spo2,
        "spo2_target_range": spo2_target_range,
        # Respiratory support context (v1.0.2)
        "oxygen_device": oxygen_device,
        "fio2_percent": fio2_percent,
        "ventilation_mode": ventilation_mode,
        # Urine output and fluid balance (v1.0.2)
        "urine_output_ml_hr": urine_output_ml_hr,
        "fluid_input_6h_ml": fluid_input_6h_ml,
        "fluid_balance_6h_ml": fluid_balance_6h_ml,
        # Labs
        "wbc_initial": round(float(wbc_initial), 2),
        "creatinine_initial": round(float(creat_initial), 2),
        "glucose_initial": round(float(glucose_initial), 2),
        "lactate_initial": lactate_initial,
        # Comorbidity flags
        "diabetes_flag": diabetes,
        "hypertension_flag": hypertension,
        "ckd_flag": ckd,
        "dm_htn_ckd_stack_flag": diabetes and hypertension and ckd,
        # Presentation pattern
        "afebrile_flag": afebrile,
        "altered_mental_status_only_flag": ams_only,
        "delayed_hypotension_flag": delayed_hypotension,
        # Deterioration context (v1.0.2)
        "deterioration_pattern": deterioration_pattern,
        # Timeline
        "hours_to_hypotension": hours_to_hypotension,
        "hours_to_icu": hours_to_icu,
        "hours_to_vasopressors": hours_to_vasopressors,
        # Contradictory signals (v1.0.2)
        "cryptic_shock_flag": cryptic_shock,
        "normal_wbc_elevated_lactate_flag": normal_wbc_elevated_lactate,
        "afebrile_tachycardic_flag": afebrile_tachycardic,
        # Metadata
        "observation_hook_version": "sepsis_generator_v3_bedside",
        "unsupported_fields_emitted_as_null": False,
        "source_visit_id": getattr(first_visit, "visit_id", None),
        "source_visit_date": getattr(first_visit, "visit_date", None),
    }
