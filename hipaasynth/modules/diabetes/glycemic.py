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
HipAAsynth Diabetes Pack - Glycemic History Module

Pure Python implementation (deterministic, no numpy/pandas)

Generates:
- HbA1c current + trajectory
- Time in range (CGM)
- Hypoglycemia
- Variability metrics
"""

import math
from typing import List, Dict


class GlycemicGenerator:
    """
    Deterministic glycemic generator.

    Args:
        rng: random.Random instance (shared across engine)
    """

    def __init__(self, rng):
        self.rng = rng

    def generate(self, population: List[Dict]) -> List[Dict]:
        """Generate glycemic features for each patient."""

        for p in population:
            self._generate_hba1c(p)
            self._generate_trajectory(p)
            self._generate_cgm(p)
            self._generate_hypoglycemia(p)
            self._generate_variability(p)

        return population

    # -----------------------------
    # HbA1c
    # -----------------------------

    def _normal(self, mean, std):
        return self.rng.gauss(mean, std)

    def _clip(self, x, lo, hi):
        return max(lo, min(hi, x))

    def _generate_hba1c(self, p: Dict):

        if p["diabetes_type"] == "type1":
            base = self._normal(7.6, 1.2)
        else:
            base = self._normal(6.9, 0.9)

        duration_effect = 0.04 * min(p["diabetes_duration_years"], 20)

        if p["current_age"] > 75:
            age_effect = -0.3
        elif p["current_age"] < 30:
            age_effect = 0.2
        else:
            age_effect = 0

        if p["race"] == "Black":
            race_effect = 0.3
        elif p["race"] == "Hispanic":
            race_effect = 0.2
        else:
            race_effect = 0

        hba1c = base + duration_effect + age_effect + race_effect
        hba1c = self._clip(hba1c, 5.0, 14.0)

        p["hba1c_current"] = round(hba1c, 1)

        # Control category
        if hba1c < 7:
            p["glycemic_control"] = "tight"
        elif hba1c < 8:
            p["glycemic_control"] = "moderate"
        elif hba1c < 9:
            p["glycemic_control"] = "poor"
        else:
            p["glycemic_control"] = "very_poor"

        # Target A1C
        if p["current_age"] < 65 and p["diabetes_duration_years"] < 10:
            p["hba1c_target"] = 7.0
        elif p["current_age"] > 75 or p.get("hypoglycemia_unawareness", False):
            p["hba1c_target"] = 8.0
        else:
            p["hba1c_target"] = 7.5

    # -----------------------------
    # Trajectory
    # -----------------------------

    def _generate_trajectory(self, p: Dict):

        if p["diabetes_type"] == "type1":
            diag = self._normal(10.5, 2.0)
        else:
            diag = self._normal(8.5, 1.5)

        diag = self._clip(diag, 5.5, 16.0)
        p["hba1c_at_diagnosis"] = round(diag, 1)

        years = p["diabetes_duration_years"]

        improvement = min(years / 2, 1.0)
        mean_val = diag - (diag - p["hba1c_current"]) * improvement * 0.5 + 0.02 * years

        p["hba1c_mean_historical"] = round(self._clip(mean_val, 6.0, 13.0), 1)

        variability = (
            0.5
            + (0.3 if p["diabetes_type"] == "type1" else 0.0)
            + 0.1 * min(years / 10, 1.0)
            + abs(self._normal(0, 0.3))
        )

        p["hba1c_variability_sd"] = round(variability, 2)

        if p["diabetes_type"] == "type1":
            tests = int(self._clip(self.rng.randint(2, 6), 2, 6))
        else:
            tests = int(self._clip(self.rng.randint(1, 4), 1, 4))

        p["hba1c_tests_per_year"] = tests

    # -----------------------------
    # CGM
    # -----------------------------

    def _generate_cgm(self, p: Dict):

        prob = 0.30
        if p["diabetes_type"] == "type1":
            prob += 0.40
        if p["current_age"] < 45:
            prob += 0.10
        if p["current_age"] > 75:
            prob -= 0.10

        prob = self._clip(prob, 0, 0.9)

        has_cgm = self.rng.random() < prob
        p["has_cgm"] = has_cgm

        if not has_cgm:
            p["time_in_range_pct"] = None
            p["time_below_range_pct"] = None
            p["time_above_range_pct"] = None
            p["gmi"] = None
            return

        base_tir = 85 - 10 * (p["hba1c_current"] - 7.0)
        tir = self._clip(base_tir + self._normal(0, 8), 30, 95)

        tbr = max(0, 5 + 0.5 * (p["hba1c_current"] - 7) + self._normal(0, 2))
        tar = max(0, 100 - tir - tbr)

        p["time_in_range_pct"] = round(tir, 1)
        p["time_below_range_pct"] = round(tbr, 1)
        p["time_above_range_pct"] = round(tar, 1)

        gmi = 3.31 + 0.02392 * (180 - 1.8 * tir)
        p["gmi"] = round(gmi, 1)

    # -----------------------------
    # Hypoglycemia
    # -----------------------------

    def _poisson(self, lam):
        # Simple Knuth algorithm (deterministic)
        L = math.exp(-lam)
        k = 0
        p = 1.0

        while p > L:
            k += 1
            p *= self.rng.random()

        return k - 1

    def _generate_hypoglycemia(self, p: Dict):

        base = 0.30 if p["diabetes_type"] == "type1" else 0.05

        age_risk = 2.0 if p["current_age"] > 75 else 1.0
        a1c_risk = 2.0 if p["hba1c_current"] < 6.5 else 1.0

        rate = base * age_risk * a1c_risk

        severe = min(self._poisson(rate), 10)

        p["severe_hypoglycemia_annual"] = severe
        p["severe_hypoglycemia_history"] = severe > 0

        unaware_prob = 0.05

        if p["diabetes_type"] == "type1" and p["diabetes_duration_years"] > 20:
            unaware_prob += 0.15

        if severe > 2:
            unaware_prob += 0.10

        unaware_prob = self._clip(unaware_prob, 0, 0.4)
        p["hypoglycemia_unawareness"] = self.rng.random() < unaware_prob

        doc_rate = rate * 10
        p["documented_hypoglycemia_annual"] = min(self._poisson(doc_rate), 50)

    # -----------------------------
    # Variability
    # -----------------------------

    def _generate_variability(self, p: Dict):

        base = 38 if p["diabetes_type"] == "type1" else 28

        if 13 <= p["current_age"] <= 19:
            base += 5

        cv = self._clip(base + self._normal(0, 5), 15, 60)
        p["glucose_cv"] = round(cv, 1)

        if p["has_cgm"]:
            gri = 3.0 * (p.get("time_below_range_pct") or 0) + 1.5 * (
                p.get("time_above_range_pct") or 0
            )
            p["glycemic_risk_index"] = round(gri, 1)

    # -----------------------------
    # Validation
    # -----------------------------

    def get_validation_stats(self, population: List[Dict]) -> Dict:

        n = len(population)

        mean_a1c = sum(p["hba1c_current"] for p in population) / n
        type1 = [p for p in population if p["diabetes_type"] == "type1"]
        type2 = [p for p in population if p["diabetes_type"] == "type2"]

        return {
            "mean_hba1c": mean_a1c,
            "type1_mean": sum(p["hba1c_current"] for p in type1) / len(type1) if type1 else 0,
            "type2_mean": sum(p["hba1c_current"] for p in type2) / len(type2) if type2 else 0,
            "cgm_rate": sum(1 for p in population if p["has_cgm"]) / n,
        }
