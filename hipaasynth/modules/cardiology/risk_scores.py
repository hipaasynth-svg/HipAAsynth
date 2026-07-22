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
HipAAsynth Cardiology Risk Scores (stdlib)

Calculates:
- ASCVD 10-year risk (simplified logistic model calibrated to PCE distributions)
- CHA2DS2-VASc
- HAS-BLED
- HEART score

ASCVD risk tiers follow the ACC/AHA Pooled Cohort Equations thresholds
(Goff DC et al. Circulation 2014;129(25 Suppl 2):S49-S73): low <5%,
borderline 5-7.5%, intermediate 7.5-20%, high >=20%. The simplified logistic
below is tuned so that, over a CV-risk-enriched cardiology population, the
low (<5%) and high (>=20%) tails land at the PCE-consistent ~25% and ~16%
respectively; the wide intermediate band (a 2.7x risk span) is descriptive
rather than asserted (see docs/calibration/CITATIONS.md § Cardiology).

Source: Goff DC et al. 2014 ACC/AHA Guideline on the Assessment of
Cardiovascular Risk. Circulation 2014. https://doi.org/10.1161/01.cir.0000437741.48606.98
"""

import math


class CardioRiskScores:
    def __init__(self, n):
        self.n = n

    def calculate(self, data):
        ascvd_risks = self._ascvd(data)
        return {
            "ascvd_10yr": ascvd_risks,
            "ascvd_category": self.ascvd_category,
            "cha2ds2_vasc": self._cha2ds2(data),
            "has_bled": self._has_bled(data),
            "heart_score": self._heart(data)
        }

    def _ascvd(self, data):
        risks = []
        cats = []

        for i in range(self.n):
            age = data["age"][i]
            sex = data["sex"][i]
            tc = data.get("total_cholesterol", [200]*self.n)[i]
            hdl = data.get("hdl_cholesterol", [50]*self.n)[i]
            sbp = data.get("systolic_bp", [120]*self.n)[i]
            smoker = data.get("smoking_status", ["never"]*self.n)[i] == "current"
            diabetes = data.get("diabetes", [False]*self.n)[i]

            # Intercept and age slope tuned so the low/high PCE tails match
            # published proportions over a CV-risk-enriched cohort (see docstring).
            logit = (
                -3.6
                + 0.06 * (age - 40)
                + 0.004 * (tc - 180)
                - 0.008 * (hdl - 45)
                + 0.008 * (sbp - 110)
                + (0.6 if smoker else 0.0)
                + (0.5 if diabetes else 0.0)
                + (-0.3 if sex == "female" else 0.0)
            )

            risk = 1.0 / (1.0 + math.exp(-logit))

            if age < 40:
                risk *= max(0.1, (age - 20) / 20.0)

            risk = max(0.005, min(0.75, risk))

            if risk < 0.05:
                cat = "low"
            elif risk < 0.075:
                cat = "borderline"
            elif risk < 0.20:
                cat = "intermediate"
            else:
                cat = "high"

            risks.append(round(risk, 4))
            cats.append(cat)

        self.ascvd_category = cats
        return risks

    def _cha2ds2(self, data):
        scores = []

        for i in range(self.n):
            age = data["age"][i]
            sex = data["sex"][i]

            score = 0

            if data.get("heart_failure", [False]*self.n)[i]:
                score += 1

            if data.get("hypertension", [False]*self.n)[i]:
                score += 1

            if age >= 75:
                score += 2
            elif age >= 65:
                score += 1

            if data.get("diabetes", [False]*self.n)[i]:
                score += 1

            if sex == "female":
                score += 1

            scores.append(score)

        return scores

    def _has_bled(self, data):
        scores = []

        for i in range(self.n):
            score = 0

            if data.get("systolic_bp", [120]*self.n)[i] > 160:
                score += 1

            if data["age"][i] > 65:
                score += 1

            scores.append(score)

        return scores

    def _heart(self, data):
        scores = []

        for i in range(self.n):
            age = data["age"][i]
            diabetes = data.get("diabetes", [False]*self.n)[i]
            smoker = data.get("smoking_status", ["never"]*self.n)[i] == "current"

            score = 0

            if age > 65 and (diabetes or smoker):
                score += 2
            elif age > 50 or diabetes or smoker:
                score += 1

            if age >= 65:
                score += 2
            elif age >= 45:
                score += 1

            risk_count = (
                int(data.get("hypertension", [False]*self.n)[i]) +
                int(diabetes) +
                int(smoker)
            )

            if risk_count >= 3:
                score += 2
            elif risk_count >= 1:
                score += 1

            scores.append(score)

        return scores
