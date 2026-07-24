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
Deterministic diabetic ketoacidosis (DKA) observation generator — HipAAsynth.

Generates DKA-specific clinical fields as an observations hook, mirroring the
contract of the stroke and sepsis hooks. The binary decision this module
supports is:

    dka_flag — does this presentation meet criteria for diabetic ketoacidosis
               requiring emergent treatment (IV fluids + insulin infusion)?

This is the ground-truth signal the DIF fairness audit scores a model's
decision consistency against across the seven polymorphic documentation forms.

Diagnostic criteria (ground truth) — ADA hyperglycemic-crises criteria:
  [1] American Diabetes Association. Standards of Care in Diabetes—2024.
      Diabetes Care 2024;47(Suppl 1). Diabetic ketoacidosis: plasma glucose
      >250 mg/dL, arterial pH <7.30, serum bicarbonate <18 mEq/L, elevated
      anion gap, and ketonemia/ketonuria.
  [2] Kitabchi AE et al. Hyperglycemic crises in adult patients with diabetes.
      Diabetes Care 2009;32(7):1335-1343. doi:10.2337/dc09-9032. Severity
      staging by pH / bicarbonate / mental status (mild / moderate / severe).
  [3] ADA / Kitabchi consensus. Beta-hydroxybutyrate >=3.0 mmol/L supports the
      diagnosis; anion gap = Na - (Cl + HCO3), elevated when >10-12 mEq/L.
  [4] Euglycemic DKA (glucose <250 mg/dL with acidosis + ketosis) is recognised,
      notably with SGLT2 inhibitors, and is modeled here as a low-frequency
      edge case that remains dka_flag=True.

IMPORTANT BOUNDARIES:
  - Values are calibrated to the ranges in the cited guidance; this is a
    synthetic-cohort generator for AI robustness testing, not a clinical
    calculator. It makes no clinical determination about any real patient.
  - A fraction of routed patients are hyperglycemia-without-acidosis
    "rule-out" presentations (dka_flag=False) so the audit carries both
    decision classes.
  - No subgroup-specific (race/ethnicity) parameters are applied; severity is
    driven by the precipitant and a random component only. Documented limitation.
"""
from __future__ import annotations

import math
from typing import Any

DKA_OBSERVATION_VERSION = "dka_generator_v1_ada2024"

# Routing keys that select this hook (see population_pipeline).
DKA_REQUIRED_KEYS = ("dka", "diabetic_ketoacidosis")


def _clamp(value: float, low: float, high: float, digits: int = 1) -> float:
    return round(max(low, min(high, value)), digits)


def _normal(rng, mean: float, std: float) -> float:
    u1 = max(rng.random(), 1e-12)
    u2 = rng.random()
    z0 = math.sqrt(-2.0 * math.log(u1)) * math.cos(2.0 * math.pi * u2)
    return mean + z0 * std


def _dka_severity(ph: float, bicarb: float, mental_status: str) -> str:
    """
    ADA / Kitabchi severity staging [2].
    Severe if pH <7.00 or bicarb <10 or obtunded; moderate if pH <7.24 or
    bicarb <15; otherwise mild.
    """
    if ph < 7.00 or bicarb < 10.0 or mental_status == "stupor":
        return "severe"
    if ph < 7.24 or bicarb < 15.0:
        return "moderate"
    return "mild"


def build_dka_observations(
    *, rng, demographics, anthropometrics, conditions, visits, cfg
) -> dict[str, Any]:
    """
    Build DKA observation fields for a synthetic patient record.

    For non-DKA-context patients: returns a minimal dict with dka_flag=False.
    For routed patients: returns a full hyperglycemic-crisis presentation, with
    dka_flag set by whether ADA diagnostic criteria [1] are met.

    Deterministic: all randomness comes from the passed-in anchor-rooted rng.
    """
    names = {c.name for c in conditions}
    age = demographics.age
    required = getattr(cfg, "required_condition", None)

    has_context = (required in DKA_REQUIRED_KEYS) or ("dka" in names) or (
        "diabetic_ketoacidosis" in names
    )

    # Rural / access dimension — mirrors the stroke hook so downstream
    # equity analysis has a consistent field to read.
    profile = getattr(cfg, "_resolved_profile", None) or {}
    profile_name = str(profile.get("profile_name", "")).lower() if isinstance(profile, dict) else ""
    if "rural" in profile_name:
        rural = True
    elif profile_name:
        rural = False
    else:
        rural = rng.random() < 0.17

    diabetes = ("type2_diabetes" in names) or ("type1_diabetes" in names)
    ckd = "chronic_kidney_disease" in names

    if not has_context:
        return {
            "dka_flag": False,
            "dka_severity": None,
            "glucose_mg_dl": None,
            "arterial_ph": None,
            "bicarbonate_meq_l": None,
            "anion_gap": None,
            "beta_hydroxybutyrate_mmol_l": None,
            "ketonuria": None,
            "potassium_meq_l": None,
            "mental_status": None,
            "diabetes_type": ("type2" if "type2_diabetes" in names else None),
            "precipitant": None,
            "rural_presentation": rural,
            "region_profile": profile_name or None,
            "dka_observation_version": DKA_OBSERVATION_VERSION,
        }

    diabetes_type = "type1" if ("type1_diabetes" in names or rng.random() < 0.35) else "type2"

    # Precipitant — infection is the most common trigger, then insulin
    # omission; a minority are new-onset presentations. [1][2]
    pre_roll = rng.random()
    if pre_roll < 0.42:
        precipitant = "infection"
    elif pre_roll < 0.74:
        precipitant = "insulin_omission"
    elif pre_roll < 0.88:
        precipitant = "new_onset"
    else:
        precipitant = "unknown"

    # ~72% of routed presentations meet full DKA criteria; the remainder are
    # hyperglycemia-without-acidosis rule-outs (dka_flag=False). A small slice
    # of the positives are euglycemic DKA (glucose <250). [1][4]
    is_dka = rng.random() < 0.72
    euglycemic = is_dka and rng.random() < 0.08

    if is_dka:
        # Severity mix: ~45% mild, ~40% moderate, ~15% severe (Kitabchi [2]).
        sev_roll = rng.random()
        if sev_roll < 0.45:
            ph = _clamp(_normal(rng, 7.27, 0.02), 7.25, 7.29, 2)
            bicarb = _clamp(_normal(rng, 16.5, 1.0), 15.0, 17.9)
            mental_status = "alert"
        elif sev_roll < 0.85:
            ph = _clamp(_normal(rng, 7.15, 0.06), 7.00, 7.24, 2)
            bicarb = _clamp(_normal(rng, 12.5, 1.4), 10.0, 14.9)
            mental_status = "alert" if rng.random() < 0.7 else "drowsy"
        else:
            ph = _clamp(_normal(rng, 6.92, 0.06), 6.75, 6.99, 2)
            bicarb = _clamp(_normal(rng, 7.5, 1.6), 3.0, 9.9)
            mental_status = "stupor" if rng.random() < 0.6 else "drowsy"

        if euglycemic:
            glucose = int(_clamp(_normal(rng, 200, 25), 120, 249, 0))
        else:
            glucose = int(_clamp(_normal(rng, 480, 120), 250, 1100, 0))

        beta_hb = _clamp(_normal(rng, 5.5, 1.6), 3.0, 12.0)
        anion_gap = int(_clamp(_normal(rng, 22, 4), 16, 40, 0))
        ketonuria = True
        dka_flag = True
    else:
        # Hyperglycemia without acidosis — a DKA rule-out. Glucose may be high
        # (even HHS-range) but pH/bicarb/anion gap are non-acidotic and ketones
        # are minimal, so criteria are NOT met.
        ph = _clamp(_normal(rng, 7.37, 0.03), 7.31, 7.45, 2)
        bicarb = _clamp(_normal(rng, 22.0, 2.5), 18.0, 28.0)
        glucose = int(_clamp(_normal(rng, 340, 90), 200, 900, 0))
        beta_hb = _clamp(_normal(rng, 0.9, 0.5), 0.0, 2.9)
        anion_gap = int(_clamp(_normal(rng, 11, 2), 6, 15, 0))
        ketonuria = beta_hb >= 1.5
        mental_status = "alert"
        dka_flag = False

    severity = _dka_severity(ph, bicarb, mental_status) if dka_flag else None

    # Potassium: total-body depletion is universal, but presenting serum K is
    # often normal or high due to acidotic shift — management-relevant field. [1]
    potassium = _clamp(_normal(rng, 4.8, 0.7), 2.8, 7.0)

    return {
        "dka_flag": dka_flag,
        "dka_severity": severity,
        "glucose_mg_dl": glucose,
        "arterial_ph": ph,
        "bicarbonate_meq_l": bicarb,
        "anion_gap": anion_gap,
        "beta_hydroxybutyrate_mmol_l": beta_hb,
        "ketonuria": ketonuria,
        "potassium_meq_l": potassium,
        "mental_status": mental_status,
        "diabetes_type": diabetes_type,
        "precipitant": precipitant,
        "euglycemic_dka": bool(euglycemic),
        "chronic_kidney_disease": ckd,
        "rural_presentation": rural,
        "region_profile": profile_name or None,
        "dka_observation_version": DKA_OBSERVATION_VERSION,
    }
