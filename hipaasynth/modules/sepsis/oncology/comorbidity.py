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
HipAAsynth Oncology Comorbidity Module (stdlib version)

No numpy, no pandas.
Deterministic via random.Random.
"""

import random
import math


class ComorbidityModule:
    def __init__(self, n: int, rng: random.Random):
        self.n = n
        self.rng = rng

    def generate(self, ages, sexes, races, sites, biomarkers=None):
        data = self._empty()

        for i in range(self.n):
            age = ages[i]
            sex = sexes[i]
            race = races[i]
            site = sites[i]

            never_smoker = False
            if biomarkers and "never_smoker" in biomarkers:
                never_smoker = biomarkers["never_smoker"][i]

            # ---------------- CARDIO ----------------
            htn_prob = 1 / (1 + math.exp(-0.08 * (age - 55)))
            hypertension = self.rng.random() < htn_prob

            cad_prob = (
                0.05
                + max(0, (age - 50)) * 0.001
                + (0.05 if sex == "M" else 0)
                + (0.10 if not never_smoker else 0)
                + (0.08 if self.rng.random() < 0.15 else 0)
                + (0.05 if hypertension else 0)
            )
            cad = self.rng.random() < min(cad_prob, 0.6)

            prior_mi = cad and (self.rng.random() < 0.4)

            hf_prob = (
                0.02
                + max(0, (age - 60)) * 0.001
                + (0.15 if cad else 0)
                + (0.20 if prior_mi else 0)
                + (0.05 if hypertension else 0)
            )
            heart_failure = self.rng.random() < min(hf_prob, 0.4)

            hf_type = None
            if heart_failure:
                hfpef_prob = min(0.5 + (age - 70) * 0.01 + (0.1 if sex == "F" else 0), 0.8)
                hf_type = "HFpEF" if self.rng.random() < hfpef_prob else "HFrEF"

            af_prob = (
                0.02
                + max(0, (age - 60)) * 0.002
                + (0.05 if sex == "M" else 0)
                + (0.15 if heart_failure else 0)
            )
            afib = self.rng.random() < min(af_prob, 0.25)

            stroke_prob = (
                0.03
                + max(0, (age - 65)) * 0.001
                + (0.10 if afib else 0)
                + (0.05 if hypertension else 0)
            )
            stroke = self.rng.random() < min(stroke_prob, 0.2)

            # ---------------- METABOLIC ----------------
            dm_prob = (
                0.05 + max(0, (age - 45)) * 0.002 + (0.05 if race in ["Black", "Hispanic"] else 0)
            )
            diabetes = self.rng.random() < min(dm_prob, 0.35)

            diabetes_type = None
            if diabetes:
                diabetes_type = "Type1" if age < 30 else "Type2"

            bmi = self.rng.gauss(32, 6) if diabetes else self.rng.gauss(28, 5)
            bmi = max(18, min(50, bmi))

            lipid_prob = (
                0.20 + max(0, (age - 50)) * 0.001 + (0.15 if cad else 0) + (0.20 if diabetes else 0)
            )
            dyslipidemia = self.rng.random() < min(lipid_prob, 0.7)

            # ---------------- PULMONARY ----------------
            if biomarkers and "never_smoker" in biomarkers:
                ever_smoked = not never_smoker
            else:
                ever_smoked = self.rng.random() < (0.15 + (0.2 if sex == "M" else 0))

            copd_prob = 0.05 + (0.15 if ever_smoked else 0) + max(0, (age - 60)) * 0.002
            copd = self.rng.random() < min(copd_prob, 0.4)

            asthma_prob = max(0, 0.08 - 0.001 * max(0, (age - 30)))
            asthma = self.rng.random() < min(asthma_prob, 0.15)

            pack_years = 0
            if ever_smoked:
                pack_years = int(self.rng.gammavariate(2, 10))
                if copd:
                    pack_years += 10

            asbestos = (site == "lung") and (self.rng.random() < 0.10)

            # ---------------- RENAL ----------------
            egfr = 120 - 0.8 * max(0, (age - 30))
            if diabetes:
                egfr -= 15
            if hypertension:
                egfr -= 10
            egfr += self.rng.gauss(0, 10)
            egfr = int(max(10, min(150, egfr)))

            if egfr >= 90:
                ckd = "G1"
            elif egfr >= 60:
                ckd = "G2"
            elif egfr >= 45:
                ckd = "G3a"
            elif egfr >= 30:
                ckd = "G3b"
            elif egfr >= 15:
                ckd = "G4"
            else:
                ckd = "G5"

            dialysis = (ckd == "G5") and (self.rng.random() < 0.2)

            # ---------------- HEPATIC ----------------
            liver_prob = 0.03 + (0.05 if bmi > 30 else 0)
            liver = self.rng.random() < min(liver_prob, 0.15)

            hep_prob = 0.02 + (0.03 if race == "Asian" else 0)
            hepatitis = self.rng.random() < hep_prob

            hep_type = None
            if hepatitis:
                hep_type = "HBV" if race == "Asian" and self.rng.random() < 0.7 else "HCV"

            lft = liver and (self.rng.random() < 0.6)

            # ---------------- CCI ----------------
            cci = 0
            cci += int(prior_mi)
            cci += int(cad)
            cci += int(heart_failure)
            cci += int(stroke)
            cci += int(copd)
            cci += int(diabetes)
            cci += 2 if ckd in ["G4", "G5"] else 0
            cci += int(dialysis)
            cci += int(liver)
            cci += int(age >= 50)
            cci += int(age >= 60)
            cci += int(age >= 70)

            # ---------------- STORE ----------------
            data["hypertension"][i] = hypertension
            data["cad"][i] = cad
            data["prior_mi"][i] = prior_mi
            data["heart_failure"][i] = heart_failure
            data["hf_type"][i] = hf_type
            data["atrial_fibrillation"][i] = afib
            data["prior_stroke"][i] = stroke

            data["diabetes"][i] = diabetes
            data["diabetes_type"][i] = diabetes_type
            data["bmi"][i] = round(bmi, 1)
            data["dyslipidemia"][i] = dyslipidemia

            data["copd"][i] = copd
            data["asthma"][i] = asthma
            data["pack_years"][i] = pack_years
            data["asbestos_exposure"][i] = asbestos

            data["egfr"][i] = egfr
            data["ckd_stage"][i] = ckd
            data["on_dialysis"][i] = dialysis

            data["chronic_liver_disease"][i] = liver
            data["hepatitis"][i] = hepatitis
            data["hepatitis_type"][i] = hep_type
            data["lft_abnormal"][i] = lft

            data["charlson_index"][i] = cci

        return data

    def _empty(self):
        return {
            "hypertension": [False] * self.n,
            "cad": [False] * self.n,
            "prior_mi": [False] * self.n,
            "heart_failure": [False] * self.n,
            "hf_type": [None] * self.n,
            "atrial_fibrillation": [False] * self.n,
            "prior_stroke": [False] * self.n,
            "diabetes": [False] * self.n,
            "diabetes_type": [None] * self.n,
            "bmi": [0] * self.n,
            "dyslipidemia": [False] * self.n,
            "copd": [False] * self.n,
            "asthma": [False] * self.n,
            "pack_years": [0] * self.n,
            "asbestos_exposure": [False] * self.n,
            "egfr": [0] * self.n,
            "ckd_stage": [None] * self.n,
            "on_dialysis": [False] * self.n,
            "chronic_liver_disease": [False] * self.n,
            "hepatitis": [False] * self.n,
            "hepatitis_type": [None] * self.n,
            "lft_abnormal": [False] * self.n,
            "charlson_index": [0] * self.n,
        }
