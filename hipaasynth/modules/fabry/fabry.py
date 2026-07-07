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
Fabry Module — Fabry Disease Synthetic Cohort Generator
Copyright (c) 2026 Cody Carlson
Version: 0.1.0-FABRY
Calibration: Fabry Registry, FOS (Fabry Outcome Survey), FDA label

Stdlib-only (no numpy/pandas). Anchor-compatible.
"""

import random
import math
import hashlib
from dataclasses import dataclass
from typing import List, Dict, Optional, Tuple

from hipaasynth.core.config import DEFAULT_SYNTHETIC_DISCLAIMER


FABRY_PHENOTYPES = ["classic", "late_cardiac", "late_renal", "asymptomatic"]

MUTATION_TYPES = ["missense", "nonsense", "splice", "rearrangement"]

MISSENSE_HOTSPOTS = ["p.N215S", "p.R301Q", "p.G328R", "p.A143T"]


@dataclass
class FabryParameters:
    male_classic_rate: float = 0.60
    male_late_cardiac_rate: float = 0.20
    male_late_renal_rate: float = 0.15
    male_asymptomatic_rate: float = 0.05

    female_classic_rate: float = 0.10
    female_late_cardiac_rate: float = 0.35
    female_late_renal_rate: float = 0.25
    female_asymptomatic_rate: float = 0.30

    classic_onset_mean: float = 6.0
    classic_onset_std: float = 2.5
    late_cardiac_onset_mean: float = 40.0
    late_cardiac_onset_std: float = 8.0
    late_renal_onset_mean: float = 35.0
    late_renal_onset_std: float = 7.0

    pain_onset_mean: float = 8.0
    pain_severity_mean: float = 7.5
    pain_episodes_per_month: float = 12.0

    lvh_onset_classic_mean: float = 25.0
    lvh_onset_late_cardiac_mean: float = 45.0
    lvh_progression_rate: float = 0.5

    proteinuria_onset_mean: float = 20.0
    esrd_onset_classic_mean: float = 42.0
    esrd_onset_late_renal_mean: float = 55.0

    tia_stroke_risk_by_50: float = 0.25

    ert_esrd_delay_years: float = 15.0
    ert_survival_extension_years: float = 10.0
    ert_cardiac_stabilization: float = 0.80

    missense_rate: float = 0.60
    nonsense_rate: float = 0.15
    splice_rate: float = 0.10
    rearrangement_rate: float = 0.15

    classic_male_enzyme_mean: float = 5.0
    classic_female_enzyme_mean: float = 35.0
    late_onset_enzyme_mean: float = 25.0

    lyso_gb3_classic_mean: float = 150.0
    lyso_gb3_late_mean: float = 45.0
    lyso_gb3_normal: float = 2.0


def _clamp(val, lo, hi):
    return max(lo, min(hi, val))


def _weighted_choice(rng, options, weights):
    r = rng.random()
    cumulative = 0.0
    for opt, w in zip(options, weights):
        cumulative += w
        if r <= cumulative:
            return opt
    return options[-1]


def _poisson(rng, lam):
    L = math.exp(-lam)
    k = 0
    p = 1.0
    while True:
        k += 1
        p *= rng.random()
        if p < L:
            return k - 1


class FabryCohortGenerator:
    def __init__(self, seed=42, params=None, treatment_rate=0.55):
        self.seed = seed
        self.params = params or FabryParameters()
        self.treatment_rate = treatment_rate
        self._rng = random.Random(seed)
        self.call_count = 0

    def _tracked_random(self):
        self.call_count += 1
        return self._rng.random()

    def _tracked_gauss(self, mu, sigma):
        self.call_count += 1
        return self._rng.gauss(mu, sigma)

    def _tracked_uniform(self, a, b):
        self.call_count += 1
        return self._rng.uniform(a, b)

    def _tracked_exponential(self, scale):
        self.call_count += 1
        u = self._rng.random()
        return -scale * math.log(1 - u + 1e-30)

    def _tracked_lognormal(self, mu, sigma):
        self.call_count += 1
        return math.exp(self._rng.gauss(mu, sigma))

    def _tracked_choice(self, options, weights):
        self.call_count += 1
        return _weighted_choice(self._rng, options, weights)

    def _tracked_poisson(self, lam):
        self.call_count += 1
        return _poisson(self._rng, lam)

    def fingerprint(self):
        return hashlib.sha256(f"{self.seed}:{self.call_count}".encode()).hexdigest()[:16]

    def generate(self, n=1000, include_biomarkers=True, include_organ_progression=True):
        cohort = []
        for i in range(n):
            patient = self._generate_patient(
                patient_id=f"FABRY-{self.seed}-{i:05d}",
                include_biomarkers=include_biomarkers,
                include_organ_progression=include_organ_progression
            )
            cohort.append(patient)
        return cohort

    def _generate_patient(self, patient_id, include_biomarkers, include_organ_progression):
        p = self.params

        sex = "M" if self._tracked_random() < 0.55 else "F"

        phenotype = self._assign_phenotype(sex)

        mutation_type = self._tracked_choice(
            MUTATION_TYPES,
            [p.missense_rate, p.nonsense_rate, p.splice_rate, p.rearrangement_rate]
        )

        if mutation_type == "missense":
            specific_mutation = self._tracked_choice(MISSENSE_HOTSPOTS, [0.25, 0.25, 0.25, 0.25])
        elif mutation_type == "nonsense":
            aa = self._tracked_choice(["W", "R", "Q"], [0.34, 0.33, 0.33])
            pos = int(self._tracked_uniform(100, 400))
            specific_mutation = f"p.{aa}{pos}X"
        else:
            pos = int(self._tracked_uniform(1, 800))
            specific_mutation = f"c.{pos}{mutation_type[:3]}"

        onset_age = self._calculate_onset_age(phenotype)
        diagnosis_delay = self._calculate_diagnosis_delay(sex, phenotype)
        diagnosis_age = onset_age + diagnosis_delay

        on_ert = self._tracked_random() < self.treatment_rate
        ert_type = self._tracked_choice(["agalsidase_alfa", "agalsidase_beta"], [0.5, 0.5]) if on_ert else None
        if not on_ert:
            self.call_count += 1
            self._rng.random()

        organ_data = {}
        if include_organ_progression:
            organ_data = self._model_organ_involvement(phenotype, sex, onset_age, on_ert)

        biomarker_data = {}
        if include_biomarkers:
            biomarker_data = self._model_biomarkers(phenotype, sex, on_ert)

        survival_years, vital_status = self._model_survival(
            phenotype, sex, onset_age, on_ert, organ_data
        )

        age_at_death_or_censor = onset_age + survival_years

        record = {
            "patient_id": patient_id,
            "synthetic": True,
            "disclaimer": DEFAULT_SYNTHETIC_DISCLAIMER,
            "sex": sex,
            "phenotype": phenotype,
            "mutation_type": mutation_type,
            "specific_mutation": specific_mutation,
            "age_at_onset_years": round(onset_age, 2),
            "age_at_diagnosis_years": round(diagnosis_age, 2),
            "diagnosis_delay_years": round(diagnosis_delay, 2),
            "on_enzyme_replacement_therapy": on_ert,
            "ert_type": ert_type,
            "age_at_death_or_censor_years": round(age_at_death_or_censor, 2),
            "vital_status": vital_status,
            "rng_calls": self.call_count,
        }
        record.update(organ_data)
        record.update(biomarker_data)

        return record

    def _assign_phenotype(self, sex):
        p = self.params
        if sex == "M":
            return self._tracked_choice(
                FABRY_PHENOTYPES,
                [p.male_classic_rate, p.male_late_cardiac_rate, p.male_late_renal_rate, p.male_asymptomatic_rate]
            )
        else:
            return self._tracked_choice(
                FABRY_PHENOTYPES,
                [p.female_classic_rate, p.female_late_cardiac_rate, p.female_late_renal_rate, p.female_asymptomatic_rate]
            )

    def _calculate_onset_age(self, phenotype):
        p = self.params
        if phenotype == "classic":
            return max(2.0, self._tracked_gauss(p.classic_onset_mean, p.classic_onset_std))
        elif phenotype == "late_cardiac":
            return max(20.0, self._tracked_gauss(p.late_cardiac_onset_mean, p.late_cardiac_onset_std))
        elif phenotype == "late_renal":
            return max(18.0, self._tracked_gauss(p.late_renal_onset_mean, p.late_renal_onset_std))
        else:
            return self._tracked_uniform(30, 60)

    def _calculate_diagnosis_delay(self, sex, phenotype):
        base_delay = self._tracked_exponential(2)
        if sex == "F":
            base_delay *= 2.5
        if phenotype in ("late_cardiac", "late_renal"):
            base_delay *= 1.5
        return base_delay

    def _model_organ_involvement(self, phenotype, sex, onset_age, on_ert):
        p = self.params
        data = {}

        if phenotype == "classic":
            data["has_neuropathic_pain"] = True
            data["age_pain_onset_years"] = round(onset_age + self._tracked_exponential(2), 2)
            data["pain_severity_0_10"] = round(_clamp(self._tracked_gauss(p.pain_severity_mean, 1.5), 1, 10), 1)
            data["pain_episodes_per_month"] = max(0, self._tracked_poisson(p.pain_episodes_per_month))
        else:
            data["has_neuropathic_pain"] = False
            data["age_pain_onset_years"] = None
            data["pain_severity_0_10"] = None
            data["pain_episodes_per_month"] = None

        if phenotype == "classic":
            lvh_onset = self._tracked_gauss(p.lvh_onset_classic_mean, 5)
        elif phenotype == "late_cardiac":
            lvh_onset = self._tracked_gauss(p.lvh_onset_late_cardiac_mean, 6)
        else:
            lvh_onset = self._tracked_gauss(50, 10) if self._tracked_random() < 0.3 else None

        has_lvh = lvh_onset is not None
        data["has_left_ventricular_hypertrophy"] = has_lvh
        data["age_lvh_onset_years"] = round(lvh_onset, 2) if has_lvh else None
        data["ivs_thickness_mm"] = round(self._tracked_gauss(15, 3) if has_lvh else self._tracked_gauss(9, 1), 1)

        if phenotype in ("classic", "late_renal"):
            if phenotype == "classic":
                proteinuria_onset = self._tracked_gauss(p.proteinuria_onset_mean, 5)
                esrd_onset = self._tracked_gauss(p.esrd_onset_classic_mean, 8) if self._tracked_random() < 0.50 else None
            else:
                proteinuria_onset = self._tracked_gauss(40, 8)
                esrd_onset = self._tracked_gauss(p.esrd_onset_late_renal_mean, 10) if self._tracked_random() < 0.30 else None

            if esrd_onset is not None and on_ert:
                esrd_onset += p.ert_esrd_delay_years

            data["has_proteinuria"] = True
            data["age_proteinuria_onset_years"] = round(proteinuria_onset, 2)
            data["progressed_to_esrd"] = esrd_onset is not None
            data["age_esrd_onset_years"] = round(esrd_onset, 2) if esrd_onset else None
        else:
            data["has_proteinuria"] = False
            data["age_proteinuria_onset_years"] = None
            data["progressed_to_esrd"] = False
            data["age_esrd_onset_years"] = None

        stroke_base_risk = 0.25 if phenotype == "classic" else 0.10
        if sex == "F":
            stroke_base_risk *= 0.6

        had_stroke_tia = self._tracked_random() < stroke_base_risk
        data["had_stroke_or_tia"] = had_stroke_tia
        data["age_stroke_tia_years"] = round(self._tracked_gauss(45, 10), 2) if had_stroke_tia else None
        if not had_stroke_tia:
            self.call_count += 1
            self._rng.random()

        return data

    def _model_biomarkers(self, phenotype, sex, on_ert):
        p = self.params

        if sex == "M":
            if phenotype == "classic":
                enzyme_level = max(0.1, self._tracked_gauss(p.classic_male_enzyme_mean, 3))
            else:
                enzyme_level = max(5.0, self._tracked_gauss(p.late_onset_enzyme_mean, 10))
        else:
            if phenotype == "classic":
                enzyme_level = max(5.0, self._tracked_gauss(p.classic_female_enzyme_mean, 15))
            else:
                enzyme_level = max(15.0, self._tracked_gauss(50, 20))

        if phenotype == "classic":
            lyso_gb3 = max(5.0, self._tracked_lognormal(math.log(p.lyso_gb3_classic_mean), 0.5))
        elif phenotype == "asymptomatic":
            lyso_gb3 = self._tracked_gauss(p.lyso_gb3_normal, 2)
        else:
            lyso_gb3 = max(5.0, self._tracked_lognormal(math.log(p.lyso_gb3_late_mean), 0.6))

        if on_ert:
            lyso_gb3 *= 0.5

        return {
            "alpha_galactosidase_a_percent_normal": round(enzyme_level, 2),
            "lyso_gb3_ng_ml": round(lyso_gb3, 2),
            "urinary_gb3_present": lyso_gb3 > 10,
        }

    def _model_survival(self, phenotype, sex, onset_age, on_ert, organ_data):
        p = self.params

        if phenotype == "classic":
            if sex == "M":
                base_survival = self._tracked_exponential(35)
            else:
                base_survival = self._tracked_exponential(50)
        elif phenotype == "late_renal":
            base_survival = self._tracked_exponential(40)
        elif phenotype == "late_cardiac":
            base_survival = self._tracked_exponential(35)
        else:
            base_survival = self._tracked_exponential(60)

        if on_ert:
            base_survival += p.ert_survival_extension_years

        if organ_data.get("progressed_to_esrd") and organ_data.get("age_esrd_onset_years"):
            base_survival = min(base_survival, organ_data["age_esrd_onset_years"] - onset_age + 10)

        if organ_data.get("had_stroke_or_tia"):
            base_survival *= 0.9

        if base_survival > (85 - onset_age):
            return (85 - onset_age), "censored"
        else:
            return base_survival, "deceased"


def _cohort_checksum(cohort, seed):
    key_data = "|".join(
        f"{r['patient_id']}:{r['sex']}:{r['phenotype']}:{r['age_at_onset_years']}"
        for r in cohort
    )
    return hashlib.sha256(f"{key_data}:{seed}".encode()).hexdigest()[:32]


def main():
    gen = FabryCohortGenerator(seed=42)
    cohort = gen.generate(n=1000)

    print(f"Fabry Cohort Generated: {len(cohort)} patients")

    pheno_counts = {}
    sex_counts = {}
    for r in cohort:
        pheno_counts[r["phenotype"]] = pheno_counts.get(r["phenotype"], 0) + 1
        sex_counts[r["sex"]] = sex_counts.get(r["sex"], 0) + 1

    print("\nPhenotype Distribution:")
    for k, v in sorted(pheno_counts.items()):
        print(f"  {k}: {v} ({v / len(cohort) * 100:.1f}%)")

    print("\nSex Distribution:")
    for k, v in sorted(sex_counts.items()):
        print(f"  {k}: {v} ({v / len(cohort) * 100:.1f}%)")

    males = [r for r in cohort if r["sex"] == "M"]
    females = [r for r in cohort if r["sex"] == "F"]
    male_classic_pct = sum(1 for r in males if r["phenotype"] == "classic") / len(males) * 100 if males else 0
    female_classic_pct = sum(1 for r in females if r["phenotype"] == "classic") / len(females) * 100 if females else 0

    classic_lyso = sorted([r["lyso_gb3_ng_ml"] for r in cohort if r["phenotype"] == "classic"])
    late_lyso = sorted([r["lyso_gb3_ng_ml"] for r in cohort if r["phenotype"] in ("late_cardiac", "late_renal")])

    def _median(vals):
        n = len(vals)
        if n == 0:
            return 0
        s = sorted(vals)
        return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2

    print(f"\nMale classic rate: {male_classic_pct:.1f}%  (target ~60%)")
    print(f"Female classic rate: {female_classic_pct:.1f}%  (target ~10%)")
    print(f"Lyso-Gb3 classic median: {_median(classic_lyso):.1f} ng/mL  (target ~150)")
    print(f"Lyso-Gb3 late-onset median: {_median(late_lyso):.1f} ng/mL  (target ~45)")

    print(f"\nChecksum: {_cohort_checksum(cohort, 42)}")
    print(f"Fingerprint: {gen.fingerprint()}")
    print(f"RNG calls: {gen.call_count}")


if __name__ == "__main__":
    main()
