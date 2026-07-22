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
HipAAsynth Cardiology Cohort Generator
======================================
`cardiology/` shipped two *utility* classes — ``CardioRiskScores`` (ASCVD,
CHA2DS2-VASc, HAS-BLED, HEART) and ``CardioMedications`` — but no population
generator: neither could run without a caller supplying a pre-built columnar
``data`` dict, so the module produced zero patients on its own and had no place
in the calibration pipeline.

This generator supplies that missing front half. It builds a primary-prevention
adult cardiology population (ages 40-79, the range over which the ACC/AHA Pooled
Cohort Equations apply), draws the risk factors the PCE consumes (lipids, blood
pressure, smoking, diabetes) plus the comorbidities the risk scores and
medication logic need, then calls ``CardioRiskScores`` and ``CardioMedications``
as sub-components and flattens everything into one synthetic-stamped dict per
patient. Same ``(seed, n)`` reproduces a byte-identical cohort.

Every risk-factor prevalence and treatment rate is calibrated to a published
anchor recorded in ``docs/calibration/CITATIONS.md`` (§ Cardiology) and
validated in ``calibration_validator_ext.py``.

    from hipaasynth.modules.cardiology.cohort import generate_cardiology_cohort
    cohort = generate_cardiology_cohort(seed=42, n=1000)
"""

import random

from hipaasynth.core.config import DEFAULT_SYNTHETIC_DISCLAIMER

from hipaasynth.modules.cardiology.risk_scores import CardioRiskScores
from hipaasynth.modules.cardiology.medications import CardioMedications


class CardiologyCohortGenerator:
    """Deterministic primary-prevention adult cardiology cohort.

    Owns one ``random.Random(seed)`` and drives risk-factor generation →
    ``CardioRiskScores`` → ``CardioMedications``.
    """

    RACES = ["White", "Black", "Hispanic", "Asian", "Other"]
    # US adult race/ethnicity frame (US Census ACS), rounded.
    RACE_PROBS = [0.62, 0.12, 0.18, 0.06, 0.02]

    def __init__(self, seed=42):
        self.seed = seed

    def generate(self, n=1000):
        rng = random.Random(self.seed)
        data = self._generate_risk_factors(rng, n)

        # Sub-component 1: risk scores (adds ascvd_10yr + ascvd_category, etc.)
        scores = CardioRiskScores(n).calculate(data)
        data["ascvd_10yr"] = scores["ascvd_10yr"]

        # Sub-component 2: medications (consumes ascvd_10yr + comorbidities)
        meds = CardioMedications(n, rng).generate(data)

        cohort = []
        for i in range(n):
            record = {
                "patient_id": f"CARDIO-{self.seed}-{i:05d}",
                "synthetic": True,
                "disclaimer": DEFAULT_SYNTHETIC_DISCLAIMER,
                # demographics + risk factors
                "age": data["age"][i],
                "sex": data["sex"][i],
                "race": data["race"][i],
                "total_cholesterol": data["total_cholesterol"][i],
                "hdl_cholesterol": data["hdl_cholesterol"][i],
                "systolic_bp": data["systolic_bp"][i],
                "smoking_status": data["smoking_status"][i],
                "diabetes": data["diabetes"][i],
                "hypertension": data["hypertension"][i],
                "heart_failure": data["heart_failure"][i],
                "atrial_fibrillation": data["atrial_fibrillation"][i],
                "ckd": data["ckd"][i],
                "prior_ascvd": data["prior_ascvd"][i],
                # risk scores
                "ascvd_10yr": scores["ascvd_10yr"][i],
                "ascvd_category": scores["ascvd_category"][i],
                "cha2ds2_vasc": scores["cha2ds2_vasc"][i],
                "has_bled": scores["has_bled"][i],
                "heart_score": scores["heart_score"][i],
            }
            for key, column in meds.items():
                record[key] = column[i]
            cohort.append(record)
        return cohort

    def _generate_risk_factors(self, rng, n):
        age, sex, race = [], [], []
        tc, hdl, sbp = [], [], []
        smoking, diabetes, htn = [], [], []
        hf, af, ckd, prior = [], [], [], []

        for _ in range(n):
            # Age uniform over 40-79 — the window over which the ACC/AHA Pooled
            # Cohort Equations apply — so both the low-risk (younger) and
            # high-risk (older) PCE tails are populated.
            # Source: Goff DC et al. Circulation 2014;129(25 Suppl 2):S49-S73.
            a = rng.randint(40, 79)
            s = "male" if rng.random() < 0.5 else "female"
            r = rng.choices(self.RACES, weights=self.RACE_PROBS, k=1)[0]

            # Cardiometabolic burden latent (z): a single per-patient factor that
            # correlates blood pressure, lipids, diabetes, and smoking, the way
            # metabolic syndrome clusters in real patients. Independent risk
            # factors would give an implausibly unimodal risk distribution; this
            # produces the bimodal spread (a low-risk majority plus a distinct
            # high-risk tail) that the PCE tiers assume.
            z = rng.gauss(0, 1.2)

            # Lipids (NHANES adult means): total cholesterol ~192 mg/dL,
            # HDL ~53 (women) / ~47 (men); both shifted by burden z.
            # Source: Carroll MD et al. NCHS Data Brief 2017 (No. 290);
            # AHA Heart Disease & Stroke Statistics 2023.
            total_c = int(max(120, min(330, rng.gauss(192 + 18 * z, 32))))
            hdl_mean = (55 if s == "female" else 47) - 6 * z
            hdl_c = int(max(20, min(100, rng.gauss(hdl_mean, 12))))

            # Systolic BP (NHANES adult mean ~128 mmHg), shifted by burden z.
            systolic = int(max(90, min(210, rng.gauss(128 + 11 * z, 14))))

            # Smoking status among US adults: current ~14%, former ~25%
            # (current-smoking probability rises with burden z).
            # Source: CDC MMWR 2023 (adult cigarette smoking ~11-14%); AHA 2023.
            sr = rng.random()
            current_p = 0.14 + 0.06 * z
            if sr < current_p:
                smoke = "current"
            elif sr < current_p + 0.25:
                smoke = "former"
            else:
                smoke = "never"

            # Diabetes ~13-14% of US adults (CDC National Diabetes Statistics
            # Report 2022), enriched with age and burden z.
            dm = rng.random() < (0.14 + 0.09 * z + max(0, (a - 60)) * 0.003)

            # Hypertension: ~48% of US adults under the 2017 ACC/AHA threshold
            # (SBP>=130). Source: AHA Heart Disease & Stroke Statistics 2023.
            hypertension = (systolic >= 130) or (rng.random() < 0.12)

            # Heart failure ~2-3% of adults, rising with age (AHA 2023).
            heart_f = rng.random() < (0.02 + max(0, (a - 60)) * 0.003)

            # Atrial fibrillation: ~2% of adults overall, ~9% at age >=65
            # (Go AS et al. JAMA 2001;285:2370-2375 — ATRIA); enriched here for a
            # cardiology-clinic population.
            afib = rng.random() < (0.03 + max(0, (a - 55)) * 0.006)

            # CKD ~14% of US adults (CDC CKD Surveillance 2023).
            ckd_flag = rng.random() < (0.10 + max(0, (a - 60)) * 0.004)

            # Established ASCVD (secondary-prevention subset) ~8%.
            prior_ascvd = rng.random() < (0.05 + max(0, (a - 55)) * 0.003)

            age.append(a); sex.append(s); race.append(r)
            tc.append(total_c); hdl.append(hdl_c); sbp.append(systolic)
            smoking.append(smoke); diabetes.append(dm); htn.append(hypertension)
            hf.append(heart_f); af.append(afib); ckd.append(ckd_flag); prior.append(prior_ascvd)

        return {
            "age": age, "sex": sex, "race": race,
            "total_cholesterol": tc, "hdl_cholesterol": hdl, "systolic_bp": sbp,
            "smoking_status": smoking, "diabetes": diabetes, "hypertension": htn,
            "heart_failure": hf, "atrial_fibrillation": af, "ckd": ckd,
            "prior_ascvd": prior,
        }


def generate_cardiology_cohort(seed=42, n=1000):
    """Convenience wrapper mirroring the other modules' functional entry point."""
    return CardiologyCohortGenerator(seed=seed).generate(n=n)


def main():
    cohort = generate_cardiology_cohort(seed=42, n=1000)
    print(f"Cardiology cohort generated: {len(cohort)} patients")
    cats = {}
    for r in cohort:
        cats[r["ascvd_category"]] = cats.get(r["ascvd_category"], 0) + 1
    print("\nASCVD 10-yr risk category distribution:")
    for k in ("low", "borderline", "intermediate", "high"):
        v = cats.get(k, 0)
        print(f"  {k}: {v} ({v / len(cohort) * 100:.1f}%)")


if __name__ == "__main__":
    main()
