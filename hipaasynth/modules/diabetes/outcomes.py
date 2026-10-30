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
HipAAsynth Diabetes Pack - Outcomes Module

Pure Python deterministic version
Removes numpy/pandas/scipy

Simulates:
- Complication progression
- CVD events
- Mortality
- Utilization
- Costs
- Quality of life
"""

import math
from typing import List, Dict


class OutcomeGenerator:
    def __init__(self, rng):
        self.rng = rng

    # =============================
    # MAIN
    # =============================

    def generate(self, population: List[Dict]) -> List[Dict]:

        for p in population:
            p["follow_up_months"] = 60
            p["censored"] = True

            self._complications(p)
            self._cv_events(p)
            self._mortality(p)
            self._utilization(p)
            self._costs(p)
            self._qol(p)

        return population

    # =============================
    # HELPERS
    # =============================

    def _clip(self, x, lo, hi):
        return max(lo, min(hi, x))

    def _exp_prob(self, rate, years=5):
        return 1 - math.exp(-rate * years)

    def _poisson(self, lam):
        L = math.exp(-lam)
        k = 0
        p = 1.0
        while p > L:
            k += 1
            p *= self.rng.random()
        return max(0, k - 1)

    # =============================
    # COMPLICATION PROGRESSION
    # =============================

    def _complications(self, p):

        # Retinopathy
        p["retinopathy_progressed"] = False
        p["retinopathy_worsened_date"] = None

        if p.get("retinopathy_any") and p.get("retinopathy_severity") not in ["severe_npdr", "pdr"]:
            if self.rng.random() < 0.20:
                p["retinopathy_progressed"] = True
                p["retinopathy_worsened_date"] = self.rng.randint(6, 60)

        # CKD progression
        p["ckd_progressed"] = False
        p["ckd_stage_at_5yr"] = p.get("ckd_stage")
        p["dialysis_initiated"] = False
        p["dialysis_date"] = None

        if p.get("nephropathy_any"):
            egfr = p.get("egfr_current", 90)
            decline = p.get("egfr_decline_rate", -2)

            projected = egfr + decline * 5

            if projected < 15 and egfr >= 15:
                p["ckd_stage_at_5yr"] = "G5"
                p["ckd_progressed"] = True
                p["dialysis_initiated"] = True
                p["dialysis_date"] = self.rng.randint(12, 60)

            elif projected < 30 and egfr >= 30:
                p["ckd_stage_at_5yr"] = "G4"
                p["ckd_progressed"] = True

            elif projected < 45 and egfr >= 45:
                p["ckd_stage_at_5yr"] = "G3b"
                p["ckd_progressed"] = True

        # Neuropathy / foot
        p["foot_complication_new"] = False
        p["amputation_new"] = False

        if p.get("neuropathy_any") and self.rng.random() < 0.05:
            p["foot_complication_new"] = True
            if self.rng.random() < 0.20:
                p["amputation_new"] = True

    # =============================
    # CVD EVENTS
    # =============================

    def _cv_events(self, p):

        p["mi_new"] = False
        p["stroke_new"] = False
        p["hf_hospitalization_new"] = False

        risk = (
            0.005
            + 0.010 * int(p.get("cvd_any", False))
            + 0.002 * max(0, p["hba1c_current"] - 7)
            + 0.001 * min(p["diabetes_duration_years"], 20) / 5
        )

        if self.rng.random() < self._exp_prob(risk * 1.8):
            p["mi_new"] = True
            p["mi_date"] = self.rng.randint(3, 60)

        if self.rng.random() < self._exp_prob(risk * 1.2):
            p["stroke_new"] = True
            p["stroke_date"] = self.rng.randint(3, 60)

        if self.rng.random() < self._exp_prob(risk * 1.5):
            p["hf_hospitalization_new"] = True
            p["hf_hosp_date"] = self.rng.randint(3, 60)

    # =============================
    # MORTALITY
    # =============================

    def _mortality(self, p):

        p["death"] = False
        p["death_date"] = None
        p["death_cause"] = None

        rate = (
            0.005
            + 0.002 * max(0, p["current_age"] - 50) / 10
            + 0.01 * int(p.get("cvd_any", False))
            + 0.02 * int(p.get("ckd_stage") == "G5")
            + 0.01 * int(p.get("ckd_stage") == "G4")
            + 0.005 * int(p.get("prior_mi", False))
            + 0.003 * int(p.get("prior_stroke", False))
        )

        if p["hba1c_current"] > 8:
            rate += 0.005 * (p["hba1c_current"] - 8)

        if p["hba1c_current"] < 7.5 and not p.get("any_complication"):
            rate *= 0.70

        if self.rng.random() < self._exp_prob(rate):
            p["death"] = True
            p["death_date"] = self._clip(int(self.rng.expovariate(rate)), 1, 60)
            p["follow_up_months"] = p["death_date"]
            p["censored"] = False

            if p.get("cvd_any") or p.get("mi_new") or p.get("stroke_new"):
                p["death_cause"] = "cardiovascular"
            elif p.get("ckd_stage") in ["G4", "G5"]:
                p["death_cause"] = "renal_failure"
            else:
                p["death_cause"] = self.rng.choice(
                    ["infection", "cancer", "other", "diabetes_related"]
                )

    # =============================
    # UTILIZATION
    # =============================

    def _utilization(self, p):

        base_endo = 4 if p["diabetes_type"] == "type1" else 2
        complexity = p.get("total_diabetes_meds", 1)
        comp = int(p.get("any_complication", False))

        p["endo_visits_annual"] = int(
            self._clip(base_endo + complexity * 0.5 + comp * 2 + self._poisson(1), 1, 12)
        )

        p["pc_visits_annual"] = self._poisson(3) + 1

        hosp_risk = (
            0.10
            + 0.20 * int(p["diabetes_type"] == "type1")
            + 0.15 * comp
            + 0.10 * int(p["hba1c_current"] > 9)
            + 0.20 * int(p["death"])
        )

        p["hospitalizations_5yr"] = min(self._poisson(hosp_risk * 2), 10)
        p["ed_visits_5yr"] = min(self._poisson(hosp_risk * 3), 15)

    # =============================
    # COSTS
    # =============================

    def _costs(self, p):

        base = 8000 if p["diabetes_type"] == "type1" else 5000

        meds = (
            50 * p.get("on_metformin", False)
            + 100 * p.get("on_sulfonylurea", False)
            + 300 * p.get("on_dpp4_inhibitor", False)
            + 1200 * p.get("on_glp1_agonist", False)
            + 500 * p.get("on_sglt2_inhibitor", False)
            + 3000 * p.get("on_insulin", False)
        )

        comp = (
            1000 * p.get("retinopathy_any", False)
            + 5000 * p.get("diabetic_macular_edema", False)
            + 2000 * p.get("nephropathy_any", False)
            + 80000 * p.get("on_dialysis", False)
            + 1500 * p.get("neuropathy_any", False)
            + 10000 * p.get("prior_amputation", False)
            + 5000 * p.get("cvd_any", False)
        )

        events = (
            50000 * p.get("mi_new", False)
            + 40000 * p.get("stroke_new", False)
            + 30000 * p.get("hf_hospitalization_new", False)
            + 100000 * p.get("dialysis_initiated", False)
            + 50000 * p.get("amputation_new", False)
        )

        hosp = p.get("hospitalizations_5yr", 0) * 15000
        ed = p.get("ed_visits_5yr", 0) * 2000

        annual = base + meds + comp

        total = annual * 5 + events + hosp + ed + self.rng.gauss(0, annual)

        p["total_costs_5yr"] = int(self._clip(total, 5000, 500000))
        p["annual_cost_estimate"] = int(p["total_costs_5yr"] / 5)

    # =============================
    # QOL
    # =============================

    def _qol(self, p):

        base = 0.85

        penalty = (
            0.05 * max(0, p["hba1c_current"] - 7) / 2
            + 0.03 * int(p.get("on_insulin", False))
            + 0.05 * int(p.get("retinopathy_any", False))
            + 0.08 * int(p.get("visual_impairment", False))
            + 0.05 * int(p.get("nephropathy_any", False))
            + 0.10 * int(p.get("ckd_stage") == "G5")
            + 0.05 * int(p.get("neuropathy_any", False))
            + 0.08 * int(p.get("foot_ulcer_history", False))
            + 0.15 * int(p.get("prior_amputation", False))
            + 0.10 * int(p.get("cvd_any", False))
        )

        eq = base - penalty + self.rng.gauss(0, 0.05)
        p["eq5d_index"] = round(self._clip(eq, 0.3, 1.0), 3)

        distress = (
            2.0
            + 1.5 * max(0, p["hba1c_current"] - 7)
            + 1.0 * int(p.get("any_complication", False))
            + 0.5 * int(p.get("on_insulin", False))
        )

        p["diabetes_distress_score"] = round(self._clip(distress + self.rng.gauss(0, 1), 0, 12), 1)

    # =============================
    # VALIDATION
    # =============================

    def get_validation_stats(self, population: List[Dict]):

        n = len(population)

        def rate(key):
            return sum(1 for p in population if p.get(key)) / n

        return {
            "death_5yr": rate("death"),
            "mi_5yr": rate("mi_new"),
            "stroke_5yr": rate("stroke_new"),
            "mean_cost": sum(p["total_costs_5yr"] for p in population) / n,
            "mean_qol": sum(p["eq5d_index"] for p in population) / n,
        }
