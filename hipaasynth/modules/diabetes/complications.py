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
HipAAsynth Diabetes Pack - Complications Module

Pure Python implementation (deterministic, no numpy/pandas)

Generates:
- Retinopathy
- Nephropathy
- Neuropathy
- Cardiovascular disease
"""

import math
from typing import List, Dict


class ComplicationGenerator:
    """
    Deterministic complication generator.

    Args:
        rng: random.Random instance
    """

    def __init__(self, rng):
        self.rng = rng

    # -----------------------------
    # Public
    # -----------------------------

    def generate(self, population: List[Dict]) -> List[Dict]:

        for p in population:
            self._retinopathy(p)
            self._nephropathy(p)
            self._neuropathy(p)
            self._cvd(p)

            p["any_complication"] = (
                p["retinopathy_any"] or p["nephropathy_any"] or p["neuropathy_any"] or p["cvd_any"]
            )

            p["microvascular_complications"] = (
                int(p["retinopathy_any"]) + int(p["nephropathy_any"]) + int(p["neuropathy_any"])
            )

        return population

    # -----------------------------
    # Helpers
    # -----------------------------

    def _clip(self, x, lo, hi):
        return max(lo, min(hi, x))

    def _exp_prob(self, score):
        return 1 - math.exp(-score)

    def _poisson(self, lam):
        L = math.exp(-lam)
        k = 0
        p = 1.0
        while p > L:
            k += 1
            p *= self.rng.random()
        return k - 1

    # -----------------------------
    # Retinopathy
    # -----------------------------

    def _retinopathy(self, p: Dict):

        duration = p["diabetes_duration_years"]
        a1c = p["hba1c_current"]
        bp = p.get("systolic_bp", 130)

        score = 0.03 * duration + 0.06 * max(0, a1c - 7.0) + 0.01 * max(0, bp - 130) / 10

        if p["race"] in ["Black", "Hispanic"]:
            score += 0.10

        prob = self._exp_prob(score)

        p["retinopathy_any"] = self.rng.random() < prob

        p["retinopathy_severity"] = None
        p["diabetic_macular_edema"] = False
        p["laser_photocoagulation"] = False
        p["anti_vegf_treatment"] = False
        p["visual_impairment"] = False
        p["legal_blindness"] = False

        if not p["retinopathy_any"]:
            return

        severity_score = 0.5 * duration / 10 + 0.3 * max(0, a1c - 7)

        r = self.rng.random()

        if r < math.exp(-severity_score):
            sev = "mild_npdr"
        elif r < math.exp(-severity_score * 0.7):
            sev = "moderate_npdr"
        elif r < math.exp(-severity_score * 0.4):
            sev = "severe_npdr"
        else:
            sev = "pdr"

        p["retinopathy_severity"] = sev

        if sev in ["moderate_npdr", "severe_npdr", "pdr"]:
            if self.rng.random() < 0.30:
                p["diabetic_macular_edema"] = True

        if sev in ["severe_npdr", "pdr"]:
            if self.rng.random() < 0.60:
                p["laser_photocoagulation"] = True

        if p["diabetic_macular_edema"] and self.rng.random() < 0.70:
            p["anti_vegf_treatment"] = True

        if p["diabetic_macular_edema"] or sev in ["severe_npdr", "pdr"]:
            if self.rng.random() < 0.25:
                p["visual_impairment"] = True

        if p["visual_impairment"] and self.rng.random() < 0.20:
            p["legal_blindness"] = True

    # -----------------------------
    # Nephropathy
    # -----------------------------

    def _nephropathy(self, p: Dict):

        duration = p["diabetes_duration_years"]
        a1c = p["hba1c_current"]
        bp = p.get("systolic_bp", 130)

        score = 0.02 * duration + 0.05 * max(0, a1c - 7) + 0.02 * max(0, bp - 130) / 10

        if p["race"] in ["Black", "Native American"]:
            score += 0.12

        normo = math.exp(-score)
        micro = normo * (1 - math.exp(-score * 0.8))
        _macro = max(0, 1 - normo - micro)

        r = self.rng.random()

        if r < normo:
            stage = "A1_normo"
        elif r < normo + micro:
            stage = "A2_micro"
        else:
            stage = "A3_macro"

        p["albuminuria_stage"] = stage
        p["nephropathy_any"] = stage != "A1_normo"

        if stage == "A2_micro":
            decline = self.rng.gauss(-2, 1)
        elif stage == "A3_macro":
            decline = self.rng.gauss(-5, 2)
        else:
            decline = self.rng.gauss(-1, 0.5)

        years = duration
        base_egfr = 100 - 0.5 * max(0, p["current_age"] - 30)
        loss = max(0, -decline * years)

        egfr = base_egfr - loss + self.rng.gauss(0, 5)
        egfr = int(self._clip(egfr, 10, 150))

        p["egfr_current"] = egfr

        if egfr >= 90:
            stage = "G1"
        elif egfr >= 60:
            stage = "G2"
        elif egfr >= 45:
            stage = "G3a"
        elif egfr >= 30:
            stage = "G3b"
        elif egfr >= 15:
            stage = "G4"
        else:
            stage = "G5"

        p["ckd_stage"] = stage

        p["on_dialysis"] = (stage == "G5") and (self.rng.random() < 0.40)
        p["prior_transplant"] = (stage == "G5") and (self.rng.random() < 0.15)

    # -----------------------------
    # Neuropathy
    # -----------------------------

    def _neuropathy(self, p: Dict):

        duration = p["diabetes_duration_years"]
        a1c = p["hba1c_current"]

        risk = 1 - math.exp(-0.04 * duration)
        risk *= 1 + 0.08 * max(0, a1c - 7)
        risk = self._clip(risk, 0, 0.95)

        p["neuropathy_any"] = self.rng.random() < risk

        p["distal_symmetric_polyneuropathy"] = False
        p["autonomic_neuropathy"] = False
        p["gastroparesis"] = False
        p["foot_ulcer_history"] = False
        p["prior_amputation"] = False

        if not p["neuropathy_any"]:
            return

        if self.rng.random() < 0.75:
            p["distal_symmetric_polyneuropathy"] = True

        auto_prob = 0.20 * min(duration / 20, 1.0)
        if self.rng.random() < auto_prob:
            p["autonomic_neuropathy"] = True

        if p["autonomic_neuropathy"] and self.rng.random() < 0.25:
            p["gastroparesis"] = True

        smoking = p.get("smoking_status", "never")

        foot_risk = (
            (a1c > 8.0) or (p.get("systolic_bp", 120) > 140) or (smoking in ["current", "former"])
        )

        if foot_risk and self.rng.random() < 0.15:
            p["foot_ulcer_history"] = True

        if p["foot_ulcer_history"] and self.rng.random() < 0.10:
            p["prior_amputation"] = True

    # -----------------------------
    # CVD
    # -----------------------------

    def _cvd(self, p: Dict):

        duration = p["diabetes_duration_years"]
        a1c = p["hba1c_current"]
        age = p["current_age"]

        score = 0.02 * duration + 0.05 * max(0, a1c - 7) + 0.03 * max(0, age - 50) / 10

        if p["sex"] == "M":
            score += 0.15

        if p.get("smoking_status", "never") in ["current", "former"]:
            score += 0.10

        score += 0.02 * max(0, p.get("systolic_bp", 120) - 130) / 10
        score += 0.01 * max(0, p.get("ldl_cholesterol", 100) - 100) / 10

        prob = self._exp_prob(score)

        p["cvd_any"] = self.rng.random() < prob

        p["coronary_artery_disease"] = False
        p["prior_mi"] = False
        p["prior_stroke"] = False
        p["peripheral_artery_disease"] = False
        p["heart_failure"] = False
        p["silent_mi"] = False
        p["prior_pci"] = False
        p["prior_cabg"] = False

        if not p["cvd_any"]:
            return

        r = self.rng.random()

        if r < 0.40:
            cad = True
            pad = False
            hf = False
            stroke = False
        elif r < 0.55:
            cad = True
            pad = True
            hf = False
            stroke = False
        elif r < 0.65:
            cad = True
            hf = True
            pad = False
            stroke = False
        elif r < 0.80:
            cad = False
            stroke = True
            pad = False
            hf = False
        elif r < 0.90:
            cad = False
            pad = True
            stroke = False
            hf = False
        else:
            cad = False
            hf = True
            pad = False
            stroke = False

        p["coronary_artery_disease"] = cad
        p["peripheral_artery_disease"] = pad
        p["prior_stroke"] = stroke
        p["heart_failure"] = hf

        if cad and self.rng.random() < 0.50:
            p["prior_mi"] = True

        if p["prior_mi"] and self.rng.random() < 0.20:
            p["silent_mi"] = True

        if cad and self.rng.random() < 0.40:
            p["prior_pci"] = True

        if cad and not p["prior_pci"] and self.rng.random() < 0.15:
            p["prior_cabg"] = True

    # -----------------------------
    # Validation
    # -----------------------------

    def get_validation_stats(self, population: List[Dict]) -> Dict:

        n = len(population)

        def rate(key):
            return sum(1 for p in population if p.get(key)) / n

        return {
            "retinopathy_any": rate("retinopathy_any"),
            "nephropathy_any": rate("nephropathy_any"),
            "neuropathy_any": rate("neuropathy_any"),
            "cvd_any": rate("cvd_any"),
            "any_complication": rate("any_complication"),
            "mean_microvascular": sum(p["microvascular_complications"] for p in population) / n,
        }
