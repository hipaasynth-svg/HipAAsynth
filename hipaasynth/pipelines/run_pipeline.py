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
pipelines/run_pipeline.py
─────────────────────────
Adapter: bridges the adversarial temporal loop to the canonical engine.

Passes the FULL patient dict (not just three numbers) so the evaluator
can use real clinical ground truth and send real clinical prompts to
the target model.

Each returned dict contains:
    patient_id     (str)   — for timeline grouping
    age            (int)   — kept for perturbation engine compatibility
    comorbidities  (int)   — kept for perturbation engine compatibility
    treatment      (int)   — kept for perturbation engine compatibility
    _patient_dict  (dict)  — full serialized patient for evaluator use
    _meta          (dict)  — injected by TemporalEngine
"""

from datetime import date

from hipaasynth.core.config import GenerationConfig, DEFAULT_SYNTHETIC_DISCLAIMER
from hipaasynth.pipelines.population_pipeline import generate_patients

_PATIENTS_PER_YEAR = 50

_TREATMENT_CONDITIONS = {
    "hypertension",
    "type2_diabetes",
    "coronary_artery_disease",
    "congestive_heart_failure",
    "atrial_fibrillation",
    "chronic_kidney_disease",
}


def run_pipeline(config=None, context=None) -> list[dict]:
    seed = getattr(context, "seed", 42)
    metadata = getattr(context, "metadata", {})

    # Allow profile and condition routing via metadata
    profile = metadata.get("profile_path", None)
    condition = metadata.get("required_condition", None)

    cfg = GenerationConfig(
        patient_count=_PATIENTS_PER_YEAR,
        seed=seed,
        age_min=18,
        age_max=90,
        required_condition=condition,
        sex_ratio_female=0.5,
        ethnicity_weights=None,
        include_visits=True,  # visits needed for lab values in obs prompts
        include_labs=True,
        visits_min=1,
        visits_max=2,
        synthetic_disclaimer=DEFAULT_SYNTHETIC_DISCLAIMER,
        run_date=date.today().isoformat(),
        population_profile_path=profile,
    )

    patients = generate_patients(cfg)
    rows = []

    for p in patients:
        active = [c for c in p.conditions if c.active]
        cond_names = {c.name for c in active}
        has_treat = int(bool(cond_names & _TREATMENT_CONDITIONS))

        rows.append(
            {
                "patient_id": p.demographics.patient_id,
                "age": p.demographics.age,
                "comorbidities": len(active),
                "treatment": has_treat,
                "_patient_dict": p.to_dict(),  # full schema for evaluator
                "_meta": metadata,
            }
        )

    return rows
