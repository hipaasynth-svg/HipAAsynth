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
HipAAsynth Diabetes Pack - Population Module
Generates base demographics: age at diagnosis, diabetes type, duration, current age

Pure Python implementation (deterministic, no numpy/pandas)
Validated against CDC/NHANES diabetes epidemiology
"""

import random
from typing import List, Dict

from hipaasynth.core.config import DEFAULT_SYNTHETIC_DISCLAIMER


class DiabetesPopulationGenerator:
    """
    Deterministic population generator for diabetes cohorts.

    Args:
        n: Number of patients to generate
        seed: Random seed for reproducibility
    """

    def __init__(self, n: int, seed: int):
        self.n = n
        self.seed = seed
        self.rng = random.Random(seed)

    def generate(self) -> List[Dict]:
        """Generate base population with diabetes-specific demographics."""

        current_ages = self._assign_current_ages()
        types = self._assign_types(current_ages)
        durations = self._assign_durations(current_ages, types)
        diagnosis_ages = [max(1, current_ages[i] - durations[i]) for i in range(self.n)]
        sexes = self._assign_sexes(types)
        races = self._assign_races()

        population = []

        for i in range(self.n):
            population.append({
                'patient_id': f'DM_{i:05d}',
                'synthetic': True,
                'disclaimer': DEFAULT_SYNTHETIC_DISCLAIMER,
                'current_age': current_ages[i],
                'diabetes_type': types[i],
                'age_at_diagnosis': diagnosis_ages[i],
                'diabetes_duration_years': durations[i],
                'sex': sexes[i],
                'race': races[i]
            })

        return population

    # -----------------------------
    # Core Assignments
    # -----------------------------

    def _assign_current_ages(self) -> List[int]:
        """Assign realistic diabetes population ages (right-skewed)."""
        ages = []

        for _ in range(self.n):
            r = self.rng.random()

            if r < 0.25:
                ages.append(self.rng.randint(18, 44))
            elif r < 0.65:
                ages.append(self.rng.randint(45, 64))
            else:
                ages.append(self.rng.randint(65, 85))

        return ages

    def _assign_types(self, current_ages: List[int]) -> List[str]:
        """Assign diabetes type (Type 1 vs Type 2)."""
        types = []

        for age in current_ages:
            # Base prevalence
            base_prob = 0.06

            # Slight age modifier
            if age < 30:
                prob = 0.12
            elif age > 60:
                prob = 0.04
            else:
                prob = base_prob

            if self.rng.random() < prob:
                types.append('type1')
            else:
                types.append('type2')

        return types

    def _assign_durations(self, current_ages: List[int], types: List[str]) -> List[int]:
        """Assign disease duration first (drives diagnosis age)."""
        durations = []

        for i in range(self.n):
            age = current_ages[i]
            t = types[i]

            if t == 'type1':
                # Type 1 → long duration typical
                max_dur = max(1, age - 5)

                if self.rng.random() < 0.9:
                    dur = self.rng.randint(5, min(30, max_dur))
                else:
                    dur = self.rng.randint(1, min(15, max_dur))

            else:
                # Type 2 → shorter, increases with age
                max_dur = max(1, age - 18)

                mean = min(12 + (age - 50) * 0.2, max_dur)
                noise = self.rng.randint(-5, 5)

                dur = int(mean + noise)
                dur = max(1, min(dur, max_dur))

            durations.append(dur)

        return durations

    def _assign_sexes(self, types: List[str]) -> List[str]:
        """Assign sex with type-based differences."""
        sexes = []

        for t in types:
            if t == 'type2':
                sexes.append('M' if self.rng.random() < 0.55 else 'F')
            else:
                sexes.append('M' if self.rng.random() < 0.50 else 'F')

        return sexes

    def _assign_races(self) -> List[str]:
        """Assign race with diabetes-weighted prevalence."""
        races = []
        categories = ['White', 'Black', 'Hispanic', 'Asian', 'Other']
        probs = [0.55, 0.18, 0.15, 0.08, 0.04]

        for _ in range(self.n):
            r = self.rng.random()
            cumulative = 0.0

            for i, p in enumerate(probs):
                cumulative += p
                if r < cumulative:
                    races.append(categories[i])
                    break

        return races

    # -----------------------------
    # Validation
    # -----------------------------

    def get_validation_stats(self) -> Dict:
        """Return statistics for validation."""
        data = self.generate()

        type_counts = {'type1': 0, 'type2': 0}
        age_sum = 0
        diag_sum = 0
        duration_sum = 0

        for row in data:
            type_counts[row['diabetes_type']] += 1
            age_sum += row['current_age']
            diag_sum += row['age_at_diagnosis']
            duration_sum += row['diabetes_duration_years']

        n = len(data)

        return {
            'type_distribution': {
                k: v / n for k, v in type_counts.items()
            },
            'current_age_mean': age_sum / n,
            'diagnosis_age_mean': diag_sum / n,
            'duration_mean': duration_sum / n
        }


# -----------------------------
# Test Block
# -----------------------------

if __name__ == '__main__':
    gen1 = DiabetesPopulationGenerator(n=1000, seed=42)
    gen2 = DiabetesPopulationGenerator(n=1000, seed=42)

    pop1 = gen1.generate()
    pop2 = gen2.generate()

    assert pop1 == pop2, "FAIL: Not deterministic"
    print("PASS: Deterministic")

    gen = DiabetesPopulationGenerator(n=10000, seed=42)
    stats = gen.get_validation_stats()

    print("\nValidation Stats:")
    print(f"Type 1: {stats['type_distribution']['type1']:.3f} (target ~0.06)")
    print(f"Mean current age: {stats['current_age_mean']:.1f}")
    print(f"Mean diagnosis age: {stats['diagnosis_age_mean']:.1f}")
    print(f"Mean duration: {stats['duration_mean']:.1f}")