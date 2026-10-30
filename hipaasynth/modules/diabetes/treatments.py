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
HipAAsynth Diabetes Pack - Treatments Module

Pure Python implementation (deterministic, no numpy/pandas)

Generates:
- Medication regimens (Type 1 + Type 2)
- Intensification logic (ADA-style progression)
- Insulin dosing
- Adherence & satisfaction
"""

from typing import List, Dict


class TreatmentGenerator:
    """
    Deterministic treatment generator.

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
            self._init_fields(p)

            if p["diabetes_type"] == "type1":
                self._type1(p)
            else:
                self._type2(p)

            self._totals(p)
            self._insulin_dose(p)
            self._adherence(p)

        return population

    # -----------------------------
    # Init
    # -----------------------------

    def _init_fields(self, p: Dict):
        p.update(
            {
                "on_metformin": False,
                "on_sulfonylurea": False,
                "on_dpp4_inhibitor": False,
                "on_glp1_agonist": False,
                "on_sglt2_inhibitor": False,
                "on_insulin": False,
                "insulin_type": None,
                "on_cgm": False,
                "number_of_oral_agents": 0,
                "number_of_injectables": 0,
                "years_to_intensification": None,
                "basal_insulin_dose": None,
                "bolus_insulin_dose": None,
                "total_daily_insulin": None,
                "insulin_units_per_kg": None,
            }
        )

    # -----------------------------
    # Type 1
    # -----------------------------

    def _type1(self, p: Dict):

        p["on_insulin"] = True

        r = self.rng.random()
        if r < 0.50:
            regimen = "basal_bolus"
            injectables = 2
        elif r < 0.80:
            regimen = "pump"
            injectables = 1
        else:
            regimen = "mixed"
            injectables = 1

        p["insulin_type"] = regimen
        p["number_of_injectables"] = injectables

        # CGM
        prob = 0.70 - 0.01 * max(0, p["current_age"] - 30)
        p["on_cgm"] = self.rng.random() < max(0, min(prob, 0.95))

        # Adjuncts
        if self.rng.random() < 0.10:
            p["on_metformin"] = True

        if p.get("bmi", 25) > 27 and self.rng.random() < 0.20:
            p["on_glp1_agonist"] = True

    # -----------------------------
    # Type 2
    # -----------------------------

    def _type2(self, p: Dict):

        duration = p["diabetes_duration_years"]
        a1c = p["hba1c_current"]
        target = p.get("hba1c_target", 7.0)
        bmi = p.get("bmi", 28)
        egfr = p.get("egfr_current", 90)

        has_cvd = p.get("cvd_any", False)
        has_hf = p.get("heart_failure", False)
        has_ckd = p.get("ckd_stage", "G1") in ["G3a", "G3b", "G4", "G5"]

        # Step 1: Metformin
        if egfr >= 30:
            p["on_metformin"] = True
        else:
            p["on_sulfonylurea"] = True

        # Step 2
        needs_second = duration > 3 and a1c > target + 0.5 or a1c > 9 or has_cvd or has_hf

        if needs_second:
            if has_cvd or has_hf or has_ckd:
                if egfr >= 30:
                    p["on_sglt2_inhibitor"] = True
                else:
                    p["on_glp1_agonist"] = True
            elif bmi > 30:
                p["on_glp1_agonist"] = True
            else:
                if self.rng.random() < 0.4:
                    p["on_sulfonylurea"] = True
                else:
                    p["on_dpp4_inhibitor"] = True

        # Step 3
        if duration > 5 and a1c > target + 0.5:
            if not p["on_glp1_agonist"] and bmi > 28:
                p["on_glp1_agonist"] = True
            elif not p["on_sglt2_inhibitor"] and egfr >= 30:
                p["on_sglt2_inhibitor"] = True
            else:
                p["on_sulfonylurea"] = True

        # Step 4: Insulin
        # Threshold A: very poor control → immediate insulin regardless of duration
        # ADA Standards of Care 2024, Section 9 (pharmacologic approaches)
        if a1c > 9.0:
            p["on_insulin"] = True
            p["insulin_type"] = "intensive" if a1c > 10.5 else "basal"
            p["number_of_injectables"] = 2 if a1c > 10.5 else 1

        # Threshold B: progressive beta-cell failure with long duration
        # UKPDS showed ~50% of newly diagnosed T2DM required insulin within 10 years
        # to maintain glycemic targets (Turner RC et al. JAMA 1999;281:2005-2012).
        # ~26% of adults with treated T2DM use insulin: no verified source
        # (citation removed in the 2026-10 source audit; see docs/calibration/SOURCE_AUDIT.md).
        elif a1c > 7.5 and duration > 10:
            insulin_prob = min(0.60 + 0.025 * (duration - 10), 0.75)
            if self.rng.random() < insulin_prob:
                p["on_insulin"] = True
                p["insulin_type"] = "basal"
                p["number_of_injectables"] = 1

        # Counts
        p["number_of_oral_agents"] = sum(
            [p["on_metformin"], p["on_sulfonylurea"], p["on_dpp4_inhibitor"]]
        )

        if p["on_insulin"] or p["number_of_oral_agents"] >= 2:
            years = duration * 0.6 + self.rng.gauss(0, 2)
            p["years_to_intensification"] = max(0, min(years, duration - 1))

    # -----------------------------
    # Totals
    # -----------------------------

    def _totals(self, p: Dict):

        p["total_diabetes_meds"] = sum(
            [
                p["on_metformin"],
                p["on_sulfonylurea"],
                p["on_dpp4_inhibitor"],
                p["on_glp1_agonist"],
                p["on_sglt2_inhibitor"],
                p["on_insulin"],
            ]
        )

    # -----------------------------
    # Insulin dosing
    # -----------------------------

    def _insulin_dose(self, p: Dict):

        if not p["on_insulin"]:
            return

        weight = p.get("bmi", 28) * (1.65**2)

        t = p["insulin_type"]

        if t == "basal":
            d = weight * self.rng.uniform(0.2, 0.5)
            p["basal_insulin_dose"] = round(d)
            p["total_daily_insulin"] = round(d)

        elif t in ["basal_bolus", "intensive"]:
            b = weight * self.rng.uniform(0.2, 0.4)
            bol = weight * self.rng.uniform(0.3, 0.6)
            p["basal_insulin_dose"] = round(b)
            p["bolus_insulin_dose"] = round(bol)
            p["total_daily_insulin"] = round(b + bol)

        elif t == "mixed":
            total = weight * self.rng.uniform(0.4, 0.6)
            p["total_daily_insulin"] = round(total)

        elif t == "pump":
            total = weight * self.rng.uniform(0.5, 0.8)
            p["total_daily_insulin"] = round(total)

        if p["total_daily_insulin"]:
            p["insulin_units_per_kg"] = round(p["total_daily_insulin"] / weight, 2)

    # -----------------------------
    # Adherence
    # -----------------------------

    def _adherence(self, p: Dict):

        complexity = p["total_diabetes_meds"] + p["number_of_injectables"]
        hypo = p.get("severe_hypoglycemia_annual", 0)

        base = 0.85 - 0.05 * complexity + self.rng.gauss(0, 0.1)
        p["medication_adherence_estimate"] = round(max(0.4, min(base, 0.95)), 2)

        score = 7.0
        if p["on_glp1_agonist"]:
            score += 1.0
        if p["on_sglt2_inhibitor"]:
            score += 0.5
        if p["on_insulin"]:
            score -= 1.0

        score -= 0.5 * min(hypo, 3)

        score += self.rng.gauss(0, 1)

        p["treatment_satisfaction_score"] = round(max(1, min(score, 10)), 1)

    # -----------------------------
    # Validation
    # -----------------------------

    def get_validation_stats(self, population: List[Dict]) -> Dict:

        def avg(lst, key):
            vals = [p[key] for p in lst if p.get(key) is not None]
            return sum(vals) / len(vals) if vals else 0

        t1 = [p for p in population if p["diabetes_type"] == "type1"]
        t2 = [p for p in population if p["diabetes_type"] == "type2"]

        return {
            "t1_insulin": avg(t1, "on_insulin"),
            "t2_insulin": avg(t2, "on_insulin"),
            "t2_glp1": avg(t2, "on_glp1_agonist"),
            "t2_sglt2": avg(t2, "on_sglt2_inhibitor"),
            "mean_adherence": avg(population, "medication_adherence_estimate"),
            "mean_satisfaction": avg(population, "treatment_satisfaction_score"),
        }
