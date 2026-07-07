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
DMD Module — Duchenne Muscular Dystrophy Synthetic Cohort Generator

Pure Python deterministic version
No numpy / pandas

Reproducible, seed-driven cohort generation
"""

import random
import math
import hashlib
from dataclasses import dataclass
from typing import List, Dict, Optional

from hipaasynth.core.config import DEFAULT_SYNTHETIC_DISCLAIMER


# =============================
# PARAMETERS
# =============================

@dataclass
class DMDParameters:
    male_ratio: float = 1.0
    median_diagnosis_age: float = 4.5
    diagnosis_age_std: float = 1.2

    median_ambulation_loss_age: float = 10.5
    ambulation_loss_std: float = 1.5

    steroid_ambulation_gain: float = 3.0
    steroid_survival_gain: float = 7.5

    cardiac_onset_mean: float = 18.0
    cardiac_onset_std: float = 3.0

    ventilation_threshold: float = 25.0

    ck_diagnostic_mean: float = 15000
    ck_diagnostic_std: float = 5000
    ck_decline_rate: float = 0.15

    deletion_rate: float = 0.65
    duplication_rate: float = 0.10
    point_mutation_rate: float = 0.25


# =============================
# DETERMINISTIC RNG
# =============================

class DeterministicRNG:
    def __init__(self, seed: int):
        self.seed = seed
        self.rng = random.Random(seed)
        self.call_count = 0

    def normal(self, mu, sigma):
        self.call_count += 1
        return self.rng.gauss(mu, sigma)

    def uniform(self, low, high):
        self.call_count += 1
        return self.rng.uniform(low, high)

    def choice(self, items, probs=None):
        self.call_count += 1
        if probs:
            r = self.rng.random()
            cumulative = 0
            for item, p in zip(items, probs):
                cumulative += p
                if r <= cumulative:
                    return item
        return self.rng.choice(items)

    def exponential(self, scale):
        self.call_count += 1
        return self.rng.expovariate(1 / scale)

    def random(self):
        self.call_count += 1
        return self.rng.random()

    def fingerprint(self):
        return hashlib.sha256(f"{self.seed}:{self.call_count}".encode()).hexdigest()[:16]


# =============================
# MAIN GENERATOR
# =============================

class DMDCohortGenerator:

    def __init__(self, seed: int = 42, params: Optional[DMDParameters] = None):
        self.params = params or DMDParameters()
        self.rng = DeterministicRNG(seed)

    # =============================
    # PUBLIC
    # =============================

    def generate(self, n: int) -> List[Dict]:

        cohort = []

        for i in range(n):
            p = {}

            p['patient_id'] = f"DMD-{i+1}"
            p['synthetic'] = True
            p['disclaimer'] = DEFAULT_SYNTHETIC_DISCLAIMER

            self._demographics(p)
            self._genetics(p)
            self._disease_timeline(p)
            self._biomarkers(p)

            cohort.append(p)

        return cohort

    # =============================
    # DEMOGRAPHICS
    # =============================

    def _demographics(self, p):

        p['sex'] = 'male'  # DMD is X-linked
        p['current_age'] = self._clip(self.rng.normal(12, 6), 2, 40)

        diagnosis = self._clip(
            self.rng.normal(self.params.median_diagnosis_age, self.params.diagnosis_age_std),
            1,
            10
        )

        p['diagnosis_age'] = diagnosis
        p['disease_duration'] = max(0, p['current_age'] - diagnosis)

    # =============================
    # GENETICS
    # =============================

    def _genetics(self, p):

        p['mutation_type'] = self.rng.choice(
            ['deletion', 'duplication', 'point_mutation'],
            [
                self.params.deletion_rate,
                self.params.duplication_rate,
                self.params.point_mutation_rate
            ]
        )

    # =============================
    # DISEASE PROGRESSION
    # =============================

    def _disease_timeline(self, p):

        steroid = self.rng.random() < 0.7
        p['on_steroids'] = steroid

        ambulation_loss = self.rng.normal(
            self.params.median_ambulation_loss_age,
            self.params.ambulation_loss_std
        )

        if steroid:
            ambulation_loss += self.params.steroid_ambulation_gain

        p['ambulation_loss_age'] = self._clip(ambulation_loss, 6, 20)

        p['non_ambulatory'] = p['current_age'] >= p['ambulation_loss_age']

        # Cardiac
        cardiac_age = self.rng.normal(
            self.params.cardiac_onset_mean,
            self.params.cardiac_onset_std
        )

        p['cardiomyopathy'] = p['current_age'] >= cardiac_age

        # Respiratory
        p['requires_ventilation'] = p['current_age'] >= self.params.ventilation_threshold

        # Survival
        base_survival = 28

        if steroid:
            base_survival += self.params.steroid_survival_gain

        p['predicted_survival_age'] = self._clip(base_survival + self.rng.normal(0, 3), 18, 50)

    # =============================
    # BIOMARKERS
    # =============================

    def _biomarkers(self, p):

        ck = self.rng.normal(
            self.params.ck_diagnostic_mean,
            self.params.ck_diagnostic_std
        )

        years = p['disease_duration']

        decline = (1 - self.params.ck_decline_rate) ** years

        p['ck_level'] = int(self._clip(ck * decline, 200, 50000))

    # =============================
    # UTILS
    # =============================

    def _clip(self, x, lo, hi):
        return max(lo, min(hi, x))


# =============================
# TEST BLOCK
# =============================

if __name__ == "__main__":

    gen = DMDCohortGenerator(seed=42)
    cohort = gen.generate(10)

    print("DMD COHORT SAMPLE")
    print("=================")

    for p in cohort[:5]:
        print(p)

    print("\nFingerprint:", gen.rng.fingerprint())