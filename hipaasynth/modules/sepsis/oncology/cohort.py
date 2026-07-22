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
HipAAsynth Oncology Cohort Orchestrator
=======================================
The six oncology sub-modules (population, staging, biomarkers, comorbidity,
treatment, outcomes) were each written to plug into "the engine" via a shared
RNG, but nothing wired them together, gave them a seed, or emitted flat
per-patient rows — so the sub-package produced no cohort on its own and had no
place in the calibration pipeline.

This orchestrator closes that gap. It owns a single ``random.Random(seed)`` and
drives the six modules in dependency order, then flattens their columnar output
into one self-describing dict per patient (``synthetic``/``disclaimer`` stamped,
matching the DMD/Fabry/SMA generators). Same ``(seed, n)`` reproduces a
byte-identical cohort.

Calibration targets for every numeric constant in the sub-modules are recorded
in ``docs/calibration/CITATIONS.md`` (§ Oncology) and validated in
``calibration_validator_ext.py``.

    from hipaasynth.modules.sepsis.oncology.cohort import generate_oncology_cohort
    cohort = generate_oncology_cohort(seed=42, n=1000)   # list[dict], one per patient
"""

import random

from hipaasynth.core.config import DEFAULT_SYNTHETIC_DISCLAIMER

from hipaasynth.modules.sepsis.oncology.population import PopulationModule
from hipaasynth.modules.sepsis.oncology.staging import StagingModule
from hipaasynth.modules.sepsis.oncology.biomarkers import BiomarkerModule
from hipaasynth.modules.sepsis.oncology.comorbidity import ComorbidityModule
from hipaasynth.modules.sepsis.oncology.treatment import TreatmentModule
from hipaasynth.modules.sepsis.oncology.outcomes import OutcomesModule


class OncologyCohortGenerator:
    """Deterministic driver over the six oncology sub-modules.

    Args:
        seed (int): seeds the single shared RNG; fixes the whole cohort.
        population_config / staging_config (dict | None): optional overrides
            passed straight through to the respective sub-modules.
    """

    def __init__(self, seed=42, population_config=None, staging_config=None):
        self.seed = seed
        self.population_config = population_config
        self.staging_config = staging_config

    def generate(self, n=1000):
        rng = random.Random(self.seed)

        population = PopulationModule(n, rng, config=self.population_config).generate()
        sites = population["site"]
        ages = population["age"]
        sexes = population["sex"]
        races = population["race"]

        staging = StagingModule(n, rng, config=self.staging_config).generate(sites)
        biomarkers = BiomarkerModule(n, rng).generate(sites, ages, races)
        comorbidity = ComorbidityModule(n, rng).generate(ages, sexes, races, sites, biomarkers)
        treatment = TreatmentModule(n, rng).generate(sites, staging["stage"], biomarkers)
        outcomes = OutcomesModule(n, rng).generate(
            sites, staging["stage"], treatment, biomarkers, comorbidity
        )

        # Flatten the columnar module outputs into one row per patient. Every
        # block is keyed by column name → list-of-length-n, so index i is
        # patient i across all of them.
        blocks = [population, staging, biomarkers, comorbidity, treatment, outcomes]
        cohort = []
        for i in range(n):
            record = {
                "patient_id": f"ONC-{self.seed}-{i:05d}",
                "synthetic": True,
                "disclaimer": DEFAULT_SYNTHETIC_DISCLAIMER,
            }
            for block in blocks:
                for key, column in block.items():
                    record[key] = column[i]
            cohort.append(record)
        return cohort


def generate_oncology_cohort(seed=42, n=1000):
    """Convenience wrapper mirroring the other modules' functional entry point."""
    return OncologyCohortGenerator(seed=seed).generate(n=n)


def main():
    cohort = generate_oncology_cohort(seed=42, n=1000)
    print(f"Oncology cohort generated: {len(cohort)} patients")

    site_counts = {}
    for r in cohort:
        site_counts[r["site"]] = site_counts.get(r["site"], 0) + 1
    print("\nSite distribution:")
    for k, v in sorted(site_counts.items()):
        print(f"  {k}: {v} ({v / len(cohort) * 100:.1f}%)")


if __name__ == "__main__":
    main()
