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

"""Generate auditable sample cohort with anchor manifest."""
import sys
import os
import json
import argparse
from datetime import date, datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from hipaasynth.core.config import (
    GenerationConfig,
    DEFAULT_SYNTHETIC_DISCLAIMER,
    ENGINE_VERSION,
)
from hipaasynth.core.anchor import Anchor
from hipaasynth.core.anchor_stamp import build_metadata
from hipaasynth.core.profile_loader import load_population_profile
from hipaasynth.pipelines.population_pipeline import generate_patients
from hipaasynth.exporters.exporters import export_fhir

MODULE_VERSIONS = {
    "population_pipeline": "v1.0",
    "generator_demographics": "v1.0",
    "generator_anthropometrics": "v1.0",
    "generator_conditions": "v1.0",
    "generator_numerics": "v1.0",
}


def generate_auditable_sample(count=100, seed=42, profile_path="profiles/us_default.json"):
    profile_data = load_population_profile(profile_path)
    anchor = Anchor(
        seed=seed,
        config={"population": count, "pipeline": "general_population", "profile": profile_path},
        modules=MODULE_VERSIONS,
    )
    cfg = GenerationConfig(
        patient_count=count,
        seed=seed,
        age_min=18,
        age_max=90,
        required_condition=None,
        sex_ratio_female=profile_data.get("sex_ratio_female", 0.5),
        ethnicity_weights=profile_data.get("ethnicity_weights"),
        include_visits=True,
        include_labs=True,
        visits_min=1,
        visits_max=3,
        synthetic_disclaimer=DEFAULT_SYNTHETIC_DISCLAIMER,
        run_date=date.today().isoformat(),
        age_band_weights=profile_data.get("age_band_weights"),
        population_profile_path=profile_path,
        profile_name=profile_data.get("profile_name"),
    )
    patients = generate_patients(cfg)
    records = []
    for p in patients:
        rec = p.to_dict()
        rec["anchor_hash"] = anchor.anchor_hash
        records.append(rec)
    metadata = build_metadata(
        anchor,
        {
            "generated_at": datetime.now(tz=timezone.utc).isoformat(),
            "engine_version": ENGINE_VERSION,
            "rows": len(records),
            "deterministic": True,
            "synthetic": True,
        },
    )
    return records, metadata, patients


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=100)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--profile", default="profiles/us_default.json")
    args = parser.parse_args()
    records, metadata, patients = generate_auditable_sample(args.count, args.seed, args.profile)
    print(f"Anchor: {metadata['anchor_hash'][:16]}...")
    json_path = f"sample_{args.count}.json"
    with open(json_path, "w") as f:
        json.dump({"metadata": metadata, "records": records}, f, indent=2)
    export_fhir(patients, f"sample_{args.count}_fhir.json")
    print(f"Saved: {json_path}")
