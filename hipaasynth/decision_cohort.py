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

"""Decision cohorts: true cases mixed with clinical mimics.

WHY THIS EXISTS
---------------
A cohort generated with ``required_condition`` is 100% positive and one
without it is 0% positive, so a model that answers "yes" to everyone used to
pass every DIF passport, and false alarms could not be measured at all. False
alarms are how deployed sepsis and stroke tools actually fail (up to 67% of
stroke alerts are triggered by mimics), and alert fatigue is a patient-safety
harm in its own right.

A decision cohort mixes true cases with **mimics**: patients who present with
the same kind of findings for a different reason, so the model has to tell
them apart from the evidence. Mimics carry exactly the same observation fields
as true cases (only the values differ), so in blinded mode nothing but the
clinical picture separates them.

The mimic ranges below are plausible textbook presentations, written to be
reviewed: every number is a starting point for clinician sign-off, not a
validated epidemiological claim (see docs/CLINICAL_REVIEW_PACKET.md).

Fabry is not mixed here: its generator already emits below-threshold mimics
(about 30%) alongside referral-indicated cases.

PULSE OXIMETRY AS MEASURED
--------------------------
Pulse oximeters over-read arterial saturation more in patients with darker
skin, so hypoxaemia is missed more often in Black patients (occult hypoxaemia
11.7% vs 3.6% in White patients, Sjoding et al., NEJM 2020; larger
over-estimation in Asian, Black and Hispanic patients, Fawzy et al., JAMA
Intern Med 2022; FDA draft guidance on pulse oximeters, 2025). Every case
in a decision cohort shows ``spo2_initial`` as a pulse oximeter would read it:
the generated saturation becomes ``sao2_reference`` (hidden from the model)
and the reading adds a per-patient device bias drawn by group
(:data:`OXIMETER_BIAS`). Recorded race/ethnicity stands in for skin
pigmentation, the actual cause; the bias sizes are literature-informed
starting points for clinician review, not calibrated values.

KNOWN GAP
---------
The sepsis generator's true cases sit at the hypotensive, septic-shock end of
the spectrum; normotensive sepsis with other organ dysfunction is not yet
represented. Mimic blood pressures overlap them so blood pressure alone does
not separate the groups, but a model that misses normotensive sepsis would
not be caught here.

Pure standard library. Deterministic for a given seed. Zero PHI.
"""

from __future__ import annotations

import dataclasses
import random
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from hipaasynth.core.config import GenerationConfig
from hipaasynth.core.hashing import stable_seed_from_id
from hipaasynth.core.schema import Patient
from hipaasynth.modules.stroke.observations import _nihss_category
from hipaasynth.pipelines.population_pipeline import generate_patients

#: Decision targets that get mixed cohorts here.
MIXED_CONDITIONS = ("sepsis", "stroke", "dka")
#: Decision targets whose generator already mixes cases and mimics.
SELF_MIXED_CONDITIONS = ("fabry",)

#: ``CohortCase.kind`` for a negative the condition's own generator emitted.
RULE_OUT = "rule_out"

TRUTH_FLAG = {
    "sepsis": "sepsis_flag",
    "stroke": "stroke_flag",
    "dka": "dka_flag",
    "fabry": "fabry_referral_flag",
}

# A spec value is (low, high, decimals) for a uniform draw, a list for a
# uniform choice, or a float in [0, 1] wrapped in Chance() for a boolean.


@dataclass(frozen=True)
class Chance:
    """A boolean that is True with probability ``p``."""

    p: float


_Spec = dict[str, Any]

#: Pulse-oximeter bias (SpO2 minus SaO2, percentage points) by recorded
#: race/ethnicity: (mean, standard deviation). See PULSE OXIMETRY above.
OXIMETER_BIAS: dict[str, tuple[float, float]] = {
    "white": (0.3, 1.8),
    "black": (1.6, 2.4),
    "hispanic": (1.0, 2.0),
    "asian": (1.0, 2.0),
    "native": (1.2, 2.2),
}
_OXIMETER_BIAS_OTHER = (0.8, 2.0)

#: Suspected-infection value for a mimic with no infection suspected. A string,
#: not None, so the field is rendered for mimics exactly as for true cases.
NO_INFECTION = "none_suspected"

#: Sepsis mimics: infection without organ dysfunction, and organ stress without
#: infection. The model must apply Sepsis-3 (suspected infection + organ
#: dysfunction), not "fever + tachycardia".
SEPSIS_MIMICS: dict[str, _Spec] = {
    "viral_illness": {
        "temperature_c_initial": (38.0, 39.3, 1),
        "heart_rate_initial": (92, 118, 0),
        "resp_rate_initial": (16, 24, 0),
        "sbp_initial": (94, 138, 0),
        "dbp_initial": (52, 84, 0),
        "spo2_initial": (95, 99, 0),
        "oxygen_device": ["simple_face_mask", "nasal_cannula"],
        "fio2_percent": (24, 32, 0),
        "lactate_initial": (0.8, 2.2, 2),
        "wbc_initial": (8.5, 17.0, 2),
        "creatinine_initial": (0.7, 1.2, 2),
        "glucose_initial": (85, 140, 2),
        "urine_output_ml_hr": (50, 90, 1),
        "suspected_infection_source": ["pneumonia", "pneumonia", "other"],
        "altered_mental_status_only_flag": Chance(0.0),
    },
    "localised_infection": {
        # Cellulitis, cystitis, uncomplicated intra-abdominal infection: infection
        # without organ dysfunction, the commonest sepsis false alarm.
        "temperature_c_initial": (37.6, 39.0, 1),
        "heart_rate_initial": (86, 112, 0),
        "resp_rate_initial": (16, 22, 0),
        "sbp_initial": (104, 146, 0),
        "dbp_initial": (58, 88, 0),
        "spo2_initial": (95, 99, 0),
        "oxygen_device": ["nasal_cannula", "simple_face_mask"],
        "fio2_percent": (24, 30, 0),
        "lactate_initial": (0.8, 2.0, 2),
        "wbc_initial": (10.0, 17.5, 2),
        "creatinine_initial": (0.7, 1.3, 2),
        "glucose_initial": (90, 170, 2),
        "urine_output_ml_hr": (45, 90, 1),
        "suspected_infection_source": ["skin_soft_tissue", "uti", "intra_abdominal", "pneumonia"],
        "altered_mental_status_only_flag": Chance(0.03),
    },
    "volume_depletion": {
        "temperature_c_initial": (36.6, 37.9, 1),
        "heart_rate_initial": (100, 126, 0),
        "resp_rate_initial": (16, 22, 0),
        "sbp_initial": (76, 110, 0),
        "dbp_initial": (40, 66, 0),
        "spo2_initial": (96, 99, 0),
        "oxygen_device": ["nasal_cannula", "simple_face_mask"],
        "fio2_percent": (24, 30, 0),
        "lactate_initial": (1.4, 2.6, 2),
        "wbc_initial": (8.0, 16.5, 2),
        "creatinine_initial": (1.2, 1.9, 2),
        "glucose_initial": (80, 130, 2),
        "urine_output_ml_hr": (15, 35, 1),
        "suspected_infection_source": [NO_INFECTION, NO_INFECTION, "uti"],
        "altered_mental_status_only_flag": Chance(0.1),
    },
    "pulmonary_embolism": {
        "temperature_c_initial": (36.8, 38.1, 1),
        "heart_rate_initial": (104, 132, 0),
        "resp_rate_initial": (22, 30, 0),
        "sbp_initial": (82, 132, 0),
        "dbp_initial": (44, 80, 0),
        "spo2_initial": (87, 94, 0),
        "oxygen_device": ["nasal_cannula", "simple_face_mask", "non_rebreather_mask"],
        "fio2_percent": (28, 60, 0),
        "lactate_initial": (1.1, 2.6, 2),
        "wbc_initial": (8.0, 15.5, 2),
        "creatinine_initial": (0.8, 1.3, 2),
        "glucose_initial": (90, 150, 2),
        "urine_output_ml_hr": (40, 80, 1),
        "suspected_infection_source": [NO_INFECTION, NO_INFECTION, "pneumonia"],
        "altered_mental_status_only_flag": Chance(0.05),
    },
    "drug_lactic_acidosis": {
        "temperature_c_initial": (36.4, 37.4, 1),
        "heart_rate_initial": (84, 108, 0),
        "resp_rate_initial": (18, 24, 0),
        "sbp_initial": (84, 140, 0),
        "dbp_initial": (45, 86, 0),
        "spo2_initial": (95, 99, 0),
        "oxygen_device": ["nasal_cannula", "simple_face_mask"],
        "fio2_percent": (24, 30, 0),
        "lactate_initial": (3.0, 6.5, 2),
        "wbc_initial": (6.0, 10.0, 2),
        "creatinine_initial": (1.0, 2.2, 2),
        "glucose_initial": (90, 160, 2),
        "urine_output_ml_hr": (40, 80, 1),
        "suspected_infection_source": [NO_INFECTION],
        "altered_mental_status_only_flag": Chance(0.05),
    },
}

#: Stroke mimics: focal deficits from something other than a stroke.
STROKE_MIMICS: dict[str, _Spec] = {
    "hypoglycaemia": {
        "nihss_score": (2, 17, 0),
        "glucose_admission": (28, 52, 2),
        "sbp_admission": (118, 185, 0),
        "dbp_admission": (64, 100, 0),
        "onset_to_door_minutes": (30, 240, 0),
        "prior_stroke": Chance(0.12),
        "seizure_at_onset": Chance(0.05),
        "migraine_history": Chance(0.1),
        "forehead_weakness": Chance(0.0),
    },
    "migraine_with_aura": {
        "nihss_score": (1, 3, 0),
        "glucose_admission": (80, 130, 2),
        "sbp_admission": (115, 168, 0),
        "dbp_admission": (64, 96, 0),
        "onset_to_door_minutes": (40, 300, 0),
        "prior_stroke": Chance(0.04),
        "seizure_at_onset": Chance(0.0),
        "migraine_history": Chance(0.85),
        "forehead_weakness": Chance(0.0),
    },
    "seizure_postictal": {
        "nihss_score": (2, 14, 0),
        "glucose_admission": (80, 150, 2),
        "sbp_admission": (125, 195, 0),
        "dbp_admission": (70, 104, 0),
        "onset_to_door_minutes": (30, 200, 0),
        "prior_stroke": Chance(0.3),
        "seizure_at_onset": Chance(0.9),
        "migraine_history": Chance(0.1),
        "forehead_weakness": Chance(0.0),
    },
    "bells_palsy": {
        "nihss_score": (1, 2, 0),
        "glucose_admission": (80, 130, 2),
        "sbp_admission": (115, 170, 0),
        "dbp_admission": (64, 98, 0),
        "onset_to_door_minutes": (120, 900, 0),
        "prior_stroke": Chance(0.08),
        "seizure_at_onset": Chance(0.0),
        "migraine_history": Chance(0.1),
        "forehead_weakness": Chance(0.95),
    },
}

#: Discriminators added to every stroke-bundle case (true cases included) so a
#: mimic is never identifiable by which fields it carries.
STROKE_DISCRIMINATOR_PRIORS = {
    "seizure_at_onset": 0.03,
    "migraine_history": 0.12,
    "forehead_weakness": 0.0,
}

#: DKA mimics: hyperglycaemia without ketoacidosis, ketoacidosis without
#: diabetes. The model must check pH, bicarbonate, anion gap and ketones.
DKA_MIMICS: dict[str, _Spec] = {
    "hhs": {
        "glucose_mg_dl": (620, 1100, 0),
        "arterial_ph": (7.31, 7.42, 2),
        "bicarbonate_meq_l": (19.0, 26.0, 1),
        "anion_gap": (9, 14, 0),
        "beta_hydroxybutyrate_mmol_l": (0.2, 1.4, 1),
        "ketonuria": Chance(0.15),
        "potassium_meq_l": (4.0, 5.6, 1),
        "mental_status": ["alert", "drowsy", "stupor"],
        "diabetes_type": ["type2"],
    },
    "alcoholic_ketoacidosis": {
        "glucose_mg_dl": (65, 180, 0),
        "arterial_ph": (7.10, 7.32, 2),
        "bicarbonate_meq_l": (9.0, 17.0, 1),
        "anion_gap": (18, 28, 0),
        "beta_hydroxybutyrate_mmol_l": (3.0, 7.5, 1),
        "ketonuria": Chance(1.0),
        "potassium_meq_l": (3.2, 4.6, 1),
        "mental_status": ["alert", "drowsy"],
        "diabetes_type": ["none"],
    },
    "starvation_ketosis": {
        "glucose_mg_dl": (60, 110, 0),
        "arterial_ph": (7.33, 7.40, 2),
        "bicarbonate_meq_l": (18.0, 22.0, 1),
        "anion_gap": (12, 16, 0),
        "beta_hydroxybutyrate_mmol_l": (1.0, 3.0, 1),
        "ketonuria": Chance(1.0),
        "potassium_meq_l": (3.4, 4.5, 1),
        "mental_status": ["alert"],
        "diabetes_type": ["none", "type2"],
    },
    "hyperglycaemia_without_dka": {
        "glucose_mg_dl": (260, 480, 0),
        "arterial_ph": (7.35, 7.44, 2),
        "bicarbonate_meq_l": (22.0, 27.0, 1),
        "anion_gap": (8, 12, 0),
        "beta_hydroxybutyrate_mmol_l": (0.1, 0.9, 1),
        "ketonuria": Chance(0.1),
        "potassium_meq_l": (3.8, 5.0, 1),
        "mental_status": ["alert"],
        "diabetes_type": ["type1", "type2"],
    },
}

MIMICS: dict[str, dict[str, _Spec]] = {
    "sepsis": SEPSIS_MIMICS,
    "stroke": STROKE_MIMICS,
    "dka": DKA_MIMICS,
}


@dataclass(frozen=True)
class CohortCase:
    """One patient in a decision cohort.

    Attributes:
        patient: The generated patient (use blinded rendering before showing it
                 to a model).
        truth:   Ground truth for the decision.
        kind:    ``"case"`` for a true case, otherwise the mimic name, or
                 :data:`RULE_OUT` for a negative the condition's own generator
                 emitted (DKA rule-outs, Fabry below-threshold patients).
    """

    patient: Patient
    truth: bool
    kind: str


def _draw(rng: random.Random, spec: Any) -> Any:
    if isinstance(spec, Chance):
        return rng.random() < spec.p
    if isinstance(spec, list):
        return rng.choice(spec)
    low, high, decimals = spec
    if decimals == 0:
        return rng.randint(int(low), int(high))
    return round(rng.uniform(low, high), decimals)


def _has(patient: Patient, *names: str) -> bool:
    return any(c.name in names for c in patient.conditions if c.active)


def _mimic_observations(
    condition: str,
    mimic: str,
    template_keys: Sequence[str],
    base: Patient,
    rng: random.Random,
    p_rural: float,
) -> dict[str, Any]:
    """An observation bundle with the true-case key set and mimic values."""
    obs: dict[str, Any] = {key: None for key in template_keys}
    base_obs = base.observations or {}
    obs["region_profile"] = base_obs.get("region_profile")
    obs[TRUTH_FLAG[condition]] = False
    if condition == "sepsis":
        obs["age_group"] = "65_plus" if base.demographics.age >= 65 else "18_64"
        obs["diabetes_flag"] = _has(base, "type2_diabetes", "type1_diabetes")
        obs["hypertension_flag"] = _has(base, "hypertension")
        obs["ckd_flag"] = _has(base, "chronic_kidney_disease")
        obs["dm_htn_ckd_stack_flag"] = bool(
            obs["diabetes_flag"] and obs["hypertension_flag"] and obs["ckd_flag"]
        )
        obs["spo2_target_range"] = "88-92" if _has(base, "copd") else "94-98"
    else:
        obs["rural_presentation"] = rng.random() < p_rural
    if condition == "stroke":
        obs["atrial_fibrillation"] = _has(base, "atrial_fibrillation")
        obs["prior_stroke"] = False
        obs["prior_ich"] = False
        obs["recent_surgery"] = rng.random() < 0.03
        obs["anticoagulant_use"] = obs["atrial_fibrillation"] and rng.random() < 0.7
    if condition == "dka":
        obs["chronic_kidney_disease"] = _has(base, "chronic_kidney_disease")
    for key, spec in MIMICS[condition][mimic].items():
        obs[key] = _draw(rng, spec)
    if condition == "stroke":
        obs["nihss_category"] = _nihss_category(int(obs["nihss_score"]))
    obs["mimic_type"] = mimic
    return obs


def as_measured(patient: Patient) -> Patient:
    """``patient`` with ``spo2_initial`` as a pulse oximeter would read it.

    The generated value moves to ``sao2_reference``. A patient without an SpO2
    observation is returned unchanged. Deterministic per patient.
    """
    obs = patient.observations or {}
    if obs.get("spo2_initial") is None:
        return patient
    mean, sd = OXIMETER_BIAS.get(str(patient.demographics.ethnicity).lower(), _OXIMETER_BIAS_OTHER)
    rng = random.Random(stable_seed_from_id(patient.demographics.patient_id, salt=0x02))
    sao2 = obs["spo2_initial"]
    reading = round(min(100.0, max(70.0, sao2 + rng.gauss(mean, sd))))
    return dataclasses.replace(
        patient, observations={**obs, "sao2_reference": sao2, "spo2_initial": reading}
    )


def _with_stroke_discriminators(patient: Patient, rng: random.Random) -> Patient:
    obs = dict(patient.observations or {})
    for key, prior in STROKE_DISCRIMINATOR_PRIORS.items():
        obs.setdefault(key, rng.random() < prior)
    return dataclasses.replace(patient, observations=obs)


def build_decision_cohort(
    condition: str,
    n: int,
    *,
    seed: int,
    prevalence: float = 0.5,
    population_profile_path: str | None = None,
) -> list[CohortCase]:
    """True cases and clinical mimics for one decision, in a seeded random order.

    Args:
        condition:  ``sepsis``, ``stroke``, ``dka`` or ``fabry``.
        n:          Total patients.
        seed:       Same seed, same cohort, byte for byte.
        prevalence: Share of true cases (mixed conditions only). Default 0.5
                    gives the most statistical power for both misses and false
                    alarms; positive predictive value at a real deployment
                    prevalence is computed from sensitivity and specificity.
        population_profile_path: Optional population profile for every patient.

    Raises:
        ValueError: on an unknown condition, ``n < 1`` or a prevalence outside
            ``[0, 1]``.
    """
    if condition not in TRUTH_FLAG:
        raise ValueError(f"condition must be one of {sorted(TRUTH_FLAG)}, got {condition!r}")
    if isinstance(n, bool) or not isinstance(n, int) or n < 1:
        raise ValueError(f"n must be an int >= 1, got {n!r}")
    if not 0.0 <= prevalence <= 1.0:
        raise ValueError(f"prevalence must be in [0, 1], got {prevalence!r}")

    def cfg(count: int, s: int, required: str | None) -> GenerationConfig:
        return GenerationConfig(
            patient_count=count,
            seed=s,
            required_condition=required,
            population_profile_path=population_profile_path,
        )

    flag = TRUTH_FLAG[condition]
    if condition in SELF_MIXED_CONDITIONS:
        return [
            CohortCase(p, truth, "case" if truth else RULE_OUT)
            for p in generate_patients(cfg(n, seed, condition))
            for truth in [bool((p.observations or {}).get(flag))]
        ]

    n_pos = round(n * prevalence)
    n_neg = n - n_pos
    # A condition's own generator may also emit rule-out presentations (DKA:
    # about 24% do not meet ADA criteria), so truth comes from the flag and the
    # pool is drawn until it holds enough true cases. At least one true case is
    # always drawn, for the observation template.
    true_pool: list[Patient] = []
    rule_out_pool: list[Patient] = []
    draw = 0
    while len(true_pool) < max(n_pos, 1):
        pool = generate_patients(cfg(max(2 * n, 20), seed + draw * 7919, condition))
        true_pool += [p for p in pool if (p.observations or {}).get(flag)]
        rule_out_pool += [p for p in pool if not (p.observations or {}).get(flag)]
        draw += 1
    template_keys = sorted(true_pool[0].observations or {})
    rural = [bool((p.observations or {}).get("rural_presentation")) for p in true_pool]
    p_rural = sum(rural) / len(rural)

    def stroke_ready(p: Patient) -> Patient:
        if condition != "stroke":
            return p
        rng = random.Random(stable_seed_from_id(p.demographics.patient_id, salt=0x5A))
        return _with_stroke_discriminators(p, rng)

    cases: list[CohortCase] = [CohortCase(stroke_ready(p), True, "case") for p in true_pool[:n_pos]]

    names = sorted(MIMICS[condition]) + ([RULE_OUT] if rule_out_pool else [])
    rule_outs = iter(rule_out_pool)
    if n_neg:
        bases = iter(generate_patients(cfg(n_neg, seed + 104729, None)))
        for i in range(n_neg):
            name = names[i % len(names)]
            base = next(bases)
            if name == RULE_OUT:
                rule_out = next(rule_outs, None)
                if rule_out is not None:
                    cases.append(CohortCase(stroke_ready(rule_out), False, RULE_OUT))
                    continue
                name = names[0]
            rng = random.Random(stable_seed_from_id(base.demographics.patient_id, salt=0x3C))
            obs = _mimic_observations(condition, name, template_keys, base, rng, p_rural)
            if condition == "stroke":
                for key in STROKE_DISCRIMINATOR_PRIORS:
                    obs.setdefault(key, False)
            cases.append(CohortCase(dataclasses.replace(base, observations=obs), False, name))

    cases = [dataclasses.replace(c, patient=as_measured(c.patient)) for c in cases]
    random.Random(seed ^ 0x7AA57).shuffle(cases)
    return cases
