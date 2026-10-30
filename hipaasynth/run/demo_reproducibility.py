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

"""Proves determinism: same seed = identical output, different seed = different output."""
import sys
import os
import json
import hashlib

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from hipaasynth.core.config import GenerationConfig, DEFAULT_SYNTHETIC_DISCLAIMER
from hipaasynth.pipelines.population_pipeline import generate_patients


def run(seed, n=100):
    cfg = GenerationConfig(
        patient_count=n,
        seed=seed,
        age_min=18,
        age_max=90,
        required_condition=None,
        sex_ratio_female=0.5,
        ethnicity_weights=None,
        include_visits=True,
        include_labs=True,
        visits_min=1,
        visits_max=2,
        synthetic_disclaimer=DEFAULT_SYNTHETIC_DISCLAIMER,
        run_date="2026-05-06",
    )
    patients = generate_patients(cfg)
    raw = json.dumps([p.to_dict() for p in patients], sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


if __name__ == "__main__":
    print("HipAAsynth Determinism Proof")
    print("=" * 40)
    h1 = run(42)
    h2 = run(42)
    h3 = run(43)
    print(f"Run A (seed=42): {h1[:16]}...")
    print(f"Run B (seed=42): {h2[:16]}...")
    print(f"Run C (seed=43): {h3[:16]}...")
    same = h1 == h2
    diff = h1 != h3
    print(f"\nSame seed match:      {same}")
    print(f"Different seed match: {not diff}")
    if same and diff:
        print("RESULT: DETERMINISM VERIFIED")
    else:
        print("RESULT: DETERMINISM FAILED")
        sys.exit(1)
