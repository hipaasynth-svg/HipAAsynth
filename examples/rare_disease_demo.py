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

"""Rare-disease DIF demo: run polymorphic fairness audit on Fabry disease patients."""

import sys
from datetime import date
from pathlib import Path

# Allow running this example without installing the package.
sys.path.insert(0, str(Path(__file__).parent.parent))

from hipaasynth.core.config import DEFAULT_SYNTHETIC_DISCLAIMER, GenerationConfig
from hipaasynth.dif import DIFConfig, run_audit
from hipaasynth.dif.model_interface import MockBiasedModel, MockFairModel
from hipaasynth.pipelines.population_pipeline import generate_patients


def main() -> None:
    cfg = GenerationConfig(
        patient_count=3,
        seed=42,
        age_min=18,
        age_max=90,
        required_condition="fabry",
        sex_ratio_female=0.5,
        ethnicity_weights=None,
        include_visits=True,
        include_labs=True,
        visits_min=1,
        visits_max=2,
        synthetic_disclaimer=DEFAULT_SYNTHETIC_DISCLAIMER,
        run_date=date.today().isoformat(),
    )

    dif_config = DIFConfig(
        device_name="RareDisease-Model",
        device_version="1.0.0",
    )

    print("=" * 70)
    print("RARE DISEASE DIF DEMO — Fabry disease patients")
    print("=" * 70)
    print(f"Generated {cfg.patient_count} synthetic Fabry patients")
    print()

    # Fair model
    print("--- Fair model (consistent across forms) ---")
    fair_passports = run_audit(MockFairModel(), generate_patients, cfg, dif_config)
    passing = sum(1 for p in fair_passports if p.passed())
    print(f"Passports: {passing}/{len(fair_passports)} pass all polymorphic fairness metrics")
    for p in fair_passports:
        print(f"  {p.patient_id}: DCS={p.metrics.dcs:.3f} ISG={p.metrics.isg:.3f} "
              f"LFDI={p.metrics.lfdi:.3f} SAF={p.metrics.saf:.3f} -> "
              f"{'PASS' if p.passed() else 'FAIL'}")
    print()

    # Biased model
    print("--- Biased model (under-triages patient/LEP forms) ---")
    biased_passports = run_audit(MockBiasedModel(), generate_patients, cfg, dif_config)
    passing = sum(1 for p in biased_passports if p.passed())
    print(f"Passports: {passing}/{len(biased_passports)} pass all polymorphic fairness metrics")
    for p in biased_passports:
        print(f"  {p.patient_id}: DCS={p.metrics.dcs:.3f} ISG={p.metrics.isg:.3f} "
              f"LFDI={p.metrics.lfdi:.3f} SAF={p.metrics.saf:.3f} -> "
              f"{'PASS' if p.passed() else 'FAIL'}")


if __name__ == "__main__":
    main()
