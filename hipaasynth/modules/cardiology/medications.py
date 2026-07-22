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
HipAAsynth Cardiology Medications Module (stdlib)

Generates:
- antihypertensives
- statins
- anticoagulants
- antiplatelets
- HF meds
- diabetes meds
"""

class CardioMedications:
    def __init__(self, n, rng):
        self.n = n
        self.rng = rng

    def generate(self, data):
        out = self._empty()

        for i in range(self.n):
            age = data["age"][i]
            risk = data.get("ascvd_10yr", [0.05]*self.n)[i]
            risk = risk if risk is not None else 0.05
            diabetes = data.get("diabetes", [False]*self.n)[i]
            smoker = data.get("smoking_status", ["never"]*self.n)[i] == "current"

            htn = data.get("hypertension", [False]*self.n)[i]
            prior_ascvd = data.get("prior_ascvd", [False]*self.n)[i]
            af = data.get("atrial_fibrillation", [False]*self.n)[i]
            hf = data.get("heart_failure", [False]*self.n)[i]
            ckd = data.get("ckd", [False]*self.n)[i]

            # ---------------- BP MEDS ----------------
            if htn and self.rng.random() < 0.7:
                out["on_antihypertensive"][i] = True

                meds = []

                if age > 65 and self.rng.random() < 0.6:
                    meds.append("thiazide")

                if diabetes or ckd or hf:
                    if self.rng.random() < 0.8:
                        meds.append(self._choice(["ace_inhibitor", "arb"]))

                if hf or af:
                    if self.rng.random() < 0.7:
                        meds.append("beta_blocker")

                if not meds:
                    meds.append(self._choice(["thiazide", "ace_inhibitor", "ccb"]))

                out["htn_meds"][i] = ",".join(meds)

            # ---------------- STATINS ----------------
            # Statin uptake among guideline-eligible adults ~55%; secondary
            # prevention (prior ASCVD) treated at a higher rate than primary.
            # Emergent among-eligible rate lands ~0.55, matching Salami JA et al.
            # JAMA Cardiol 2017;2(1):56-65 (statin use in eligible US adults).
            if prior_ascvd or risk > 0.075 or (diabetes and 40 <= age <= 75):
                treated = (
                    (prior_ascvd and self.rng.random() < 0.8) or
                    (not prior_ascvd and self.rng.random() < 0.5)
                )

                if treated:
                    out["on_statin"][i] = True

                    if prior_ascvd or risk > 0.2:
                        out["statin_intensity"][i] = "high"
                    else:
                        out["statin_intensity"][i] = "moderate"

            # ---------------- ANTICOAG ----------------
            # Oral anticoagulation in AF with elevated stroke risk
            # (CHA2DS2-VASc >= 2) ~70%; DOACs now dominate over warfarin.
            # Source: Freedman B et al. JAMA Cardiol 2017;2(4):442-451
            # (guideline-indicated OAC undertreatment in AF).
            if af and self.rng.random() < 0.72:
                out["on_anticoagulant"][i] = True
                out["anticoagulant_type"][i] = (
                    "doac" if self.rng.random() < 0.8 else "warfarin"
                )

            # ---------------- ANTIPLATELET ----------------
            if prior_ascvd and self.rng.random() < 0.9:
                out["on_antiplatelet"][i] = True
                out["antiplatelet_type"][i] = (
                    "dual" if self.rng.random() < 0.3 else "aspirin"
                )

            elif risk > 0.10 and self.rng.random() < 0.2:
                out["on_antiplatelet"][i] = True
                out["antiplatelet_type"][i] = "aspirin"

            # ---------------- HF MEDS ----------------
            if hf and self.rng.random() < 0.85:
                out["on_hf_therapy"][i] = True

                meds = []

                if self.rng.random() < 0.9:
                    meds.append(self._choice(["ace_inhibitor", "arb"]))

                if self.rng.random() < 0.9:
                    meds.append("beta_blocker")

                if self.rng.random() < 0.6:
                    meds.append("mra")

                if diabetes or prior_ascvd or self.rng.random() < 0.5:
                    meds.append("sglt2_inhibitor")

                out["hf_meds"][i] = ",".join(meds)

            # ---------------- DIABETES ----------------
            if diabetes and self.rng.random() < 0.9:
                out["on_diabetes_meds"][i] = True

                meds = ["metformin"]

                if prior_ascvd or hf:
                    meds.append("sglt2_inhibitor")
                else:
                    meds.append(self._choice([
                        "sglt2_inhibitor",
                        "glp1_agonist",
                        "dpp4_inhibitor",
                        "sulfonylurea"
                    ]))

                out["diabetes_meds"][i] = ",".join(meds)

            # ---------------- COUNT ----------------
            out["total_meds"][i] = (
                int(out["on_antihypertensive"][i]) +
                int(out["on_statin"][i]) +
                int(out["on_anticoagulant"][i]) +
                int(out["on_antiplatelet"][i]) +
                int(out["on_hf_therapy"][i]) +
                int(out["on_diabetes_meds"][i])
            )

        return out

    def _choice(self, options):
        return options[self.rng.randrange(len(options))]

    def _empty(self):
        return {
            "on_antihypertensive": [False]*self.n,
            "htn_meds": [None]*self.n,

            "on_statin": [False]*self.n,
            "statin_intensity": [None]*self.n,

            "on_anticoagulant": [False]*self.n,
            "anticoagulant_type": [None]*self.n,

            "on_antiplatelet": [False]*self.n,
            "antiplatelet_type": [None]*self.n,

            "on_hf_therapy": [False]*self.n,
            "hf_meds": [None]*self.n,

            "on_diabetes_meds": [False]*self.n,
            "diabetes_meds": [None]*self.n,

            "total_meds": [0]*self.n
        }