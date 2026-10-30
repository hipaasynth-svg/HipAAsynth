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

"""HipAAsynth Diabetes Pipeline Runner — Anchor-Wired."""
import sys
import os
import random
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from hipaasynth.core.anchor import Anchor
from hipaasynth.core.anchor_stamp import stamp_population, build_metadata
from hipaasynth.modules.diabetes.population import DiabetesPopulationGenerator
from hipaasynth.modules.diabetes.glycemic import GlycemicGenerator
from hipaasynth.modules.diabetes.complications import ComplicationGenerator
from hipaasynth.modules.diabetes.treatments import TreatmentGenerator
from hipaasynth.modules.diabetes.outcomes import OutcomeGenerator

N = 1000
MASTER_SEED = 42
MODULE_VERSIONS = {
    "diabetes_population": "v1.0",
    "glycemic": "v1.0",
    "complications": "v1.0",
    "treatments": "v1.0",
    "outcomes": "v1.0",
}


def main():
    anchor = Anchor(
        seed=MASTER_SEED, config={"population": N, "pipeline": "diabetes"}, modules=MODULE_VERSIONS
    )
    print(f"Anchor: {anchor.anchor_hash[:16]}...")
    pop_seed = anchor.derive_seed("population")
    gly_seed = anchor.derive_seed("glycemic")
    comp_seed = anchor.derive_seed("complications")
    tx_seed = anchor.derive_seed("treatments")
    out_seed = anchor.derive_seed("outcomes")
    population = DiabetesPopulationGenerator(n=N, seed=pop_seed).generate()
    population = GlycemicGenerator(random.Random(gly_seed)).generate(population)
    population = ComplicationGenerator(random.Random(comp_seed)).generate(population)
    population = TreatmentGenerator(random.Random(tx_seed)).generate(population)
    population = OutcomeGenerator(random.Random(out_seed)).generate(population)
    population = stamp_population(population, anchor)
    metadata = build_metadata(
        anchor, {"rows": len(population), "description": "Diabetes cohort 5-year simulation"}
    )
    with open("diabetes_cohort.json", "w") as f:
        json.dump(population, f, indent=2)
    with open("diabetes_anchor_manifest.json", "w") as f:
        json.dump(metadata, f, indent=2)
    n = len(population)
    print(f"N={n} | Mean HbA1c={sum(p['hba1c_current'] for p in population)/n:.1f} | Done.")


if __name__ == "__main__":
    main()
