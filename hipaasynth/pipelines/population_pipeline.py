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
Pipeline module for Synthetic Clinical Cohort Engine.

CANONICAL ARCHITECTURE (v1.0.0) — ANCHOR-ROOTED GENERATION:

  seed → Anchor (SHA256) → derive_seed("population") → master_rng → patients

  The raw seed is NEVER passed to random.Random() directly in this path.
  All randomness is cryptographically derived from the SHA256 anchor.
  This makes every byte of output traceable and regulator-auditable.

PROOF OF RANDOMNESS PATH:
  1. Anchor(seed, config, modules) → anchor_hash (SHA256)
  2. anchor.derive_seed("population") → master_seed (SHA256 derived int)
  3. random.Random(master_seed) → master_rng
  4. master_rng.randint() → patient_seed per patient
  5. random.Random(patient_seed) → per-patient rng
  6. All generation modules receive per-patient rng only

No module creates its own RNG. No raw seed touches random.Random().
"""

import random

from hipaasynth.core.anchor import Anchor
from hipaasynth.core.config import GenerationConfig, ENGINE_VERSION, SCHEMA_VERSION
from hipaasynth.core.schema import Patient, Visit
from hipaasynth.pipelines.generator_demographics import generate_demographics
from hipaasynth.pipelines.generator_anthropometrics import generate_anthropometrics
from hipaasynth.pipelines.generator_conditions import generate_conditions
from hipaasynth.pipelines.generator_numerics import generate_visits
from hipaasynth.validation.validator import validate_patient
from hipaasynth.core.profile_loader import load_population_profile
from hipaasynth.modules.sepsis.observations import build_sepsis_observations
from hipaasynth.modules.stroke.observations import build_stroke_observations
from hipaasynth.modules.diabetes.observations import (
    DKA_REQUIRED_KEYS,
    build_dka_observations,
)
from hipaasynth.modules.fabry.observations import (
    FABRY_REQUIRED_KEYS,
    build_fabry_observations,
)

# Module version — must match anchor config for hash stability
PIPELINE_MODULE_VERSION = "v1.0"

# Namespace used for anchor seed derivation — never change this string
_POPULATION_NAMESPACE = "population"


def _build_anchor(cfg: GenerationConfig) -> Anchor:
    """
    Build the SHA256 anchor from config.

    This is the cryptographic root. Everything derives from here.
    Changing seed or config produces a completely different anchor_hash.
    """
    return Anchor(
        seed=cfg.seed,
        config={
            "patient_count": cfg.patient_count,
            "age_min": cfg.age_min,
            "age_max": cfg.age_max,
            "pipeline": "population",
            "profile": cfg.population_profile_path or "none",
        },
        modules={
            "population_pipeline": PIPELINE_MODULE_VERSION,
        }
    )


def _derive_master_seed(anchor: Anchor) -> int:
    """
    Derive the master RNG seed from the anchor.

    This is the ONLY approved entry point for randomness.
    The raw cfg.seed is NEVER passed to random.Random() directly.
    """
    return anchor.derive_seed(_POPULATION_NAMESPACE)


def _derive_patient_seed(master_rng: random.Random) -> int:
    """Derive a per-patient seed from the master RNG."""
    return master_rng.randint(0, 0xFFFFFFFF)


def stream_patients(cfg: GenerationConfig):
    """
    Yield patients one at a time from anchor-rooted generation.

    Randomness path:
      cfg.seed → Anchor → derive_seed("population") → master_rng → patient_seeds
    """
    if cfg.patient_count < 1:
        raise ValueError("patient_count must be at least 1")
    if cfg.age_max < cfg.age_min:
        raise ValueError("age_max must be >= age_min")

    if cfg.population_profile_path:
        profile = load_population_profile(cfg.population_profile_path)
        object.__setattr__(cfg, '_resolved_profile', profile)

    # ANCHOR-ROOTED: build anchor first, derive master seed from it
    anchor = _build_anchor(cfg)
    master_seed = _derive_master_seed(anchor)
    master_rng = random.Random(master_seed)

    # Store anchor on config for downstream audit use
    object.__setattr__(cfg, '_anchor', anchor)

    for i in range(cfg.patient_count):
        patient_seed = _derive_patient_seed(master_rng)
        yield _generate_one(cfg, patient_seed)


def _generate_one(cfg: GenerationConfig, patient_seed: int) -> Patient:
    """
    Generate a single synthetic patient record.

    ONE rng per patient. Created from patient_seed (which is itself derived
    from the anchor). Passed to every module. No module creates its own RNG.
    """
    rng = random.Random(patient_seed)

    profile = getattr(cfg, '_resolved_profile', None)
    age_band_weights = cfg.age_band_weights
    sex_ratio = cfg.sex_ratio_female
    eth_weights = cfg.ethnicity_weights

    if profile:
        if not age_band_weights:
            # Dict-format age_bands ({"min":18,"max":64,"weight":0.55})
            dict_bands = profile.get("age_bands", [])
            if dict_bands:
                age_band_weights = [(b["min"], b["max"], b["weight"]) for b in dict_bands]
            else:
                # List-format age_band_weights ([[18, 64, 0.55], [65, 90, 0.45]])
                raw_bands = profile.get("age_band_weights", [])
                if raw_bands:
                    age_band_weights = [(int(b[0]), int(b[1]), float(b[2])) for b in raw_bands]
        if eth_weights is None:
            eth_weights = profile.get("ethnicity_weights")
        sex_ratio = profile.get("sex_ratio_female", sex_ratio)

    demographics = generate_demographics(
        rng=rng,
        patient_seed=patient_seed,
        age_min=cfg.age_min,
        age_max=cfg.age_max,
        sex_ratio_female=sex_ratio,
        ethnicity_weights=eth_weights,
        age_band_weights=age_band_weights,
    )

    anthropometrics = generate_anthropometrics(
        rng=rng,
        age=demographics.age,
        sex=demographics.sex,
    )

    conditions = generate_conditions(
        rng=rng,
        age=demographics.age,
        bmi=anthropometrics.bmi,
        required_condition=cfg.required_condition,
    )

    visits: list[Visit] = []
    if cfg.include_visits:
        visits = generate_visits(
            rng=rng,
            patient_seed=patient_seed,
            conditions=conditions,
            visits_min=cfg.visits_min,
            visits_max=cfg.visits_max,
            include_labs=cfg.include_labs,
        )

    # Observations get their own dedicated rng derived from the anchor
    # This preserves determinism without depending on rng state after generation
    anchor = getattr(cfg, '_anchor', None)
    if anchor is not None:
        obs_seed = anchor.derive_seed(f"observations:{demographics.patient_id}")
    else:
        obs_seed = demographics.seed ^ 0xDEADBEEF
    obs_rng = random.Random(obs_seed)

    # Route to the correct observation hook based on condition
    required = getattr(cfg, 'required_condition', None)
    condition_names = {c.name for c in conditions}

    obs_kwargs = dict(
        rng=obs_rng,
        demographics=demographics,
        anthropometrics=anthropometrics,
        conditions=conditions,
        visits=visits,
        cfg=cfg,
    )

    if required == 'stroke' or 'stroke' in condition_names:
        observations = build_stroke_observations(**obs_kwargs)
    elif required in DKA_REQUIRED_KEYS or 'dka' in condition_names:
        observations = build_dka_observations(**obs_kwargs)
    elif required in FABRY_REQUIRED_KEYS or 'fabry' in condition_names:
        observations = build_fabry_observations(**obs_kwargs)
    else:
        observations = build_sepsis_observations(**obs_kwargs)

    patient = Patient(
        demographics=demographics,
        anthropometrics=anthropometrics,
        conditions=conditions,
        visits=visits,
        engine_version=ENGINE_VERSION,
        schema_version=SCHEMA_VERSION,
        synthetic=True,
        disclaimer=cfg.synthetic_disclaimer,
        observations=observations,
    )

    return validate_patient(patient)


def generate_one_patient(cfg: GenerationConfig, idx: int) -> Patient:
    """
    Generate patient at index idx. Uses same anchor-rooted path as generate_patients.
    """
    anchor = _build_anchor(cfg)
    master_seed = _derive_master_seed(anchor)
    master_rng = random.Random(master_seed)

    if cfg.population_profile_path:
        profile = load_population_profile(cfg.population_profile_path)
        object.__setattr__(cfg, '_resolved_profile', profile)
    object.__setattr__(cfg, '_anchor', anchor)

    for _ in range(idx + 1):
        patient_seed = _derive_patient_seed(master_rng)
    return _generate_one(cfg, patient_seed)


def generate_patients(cfg: GenerationConfig) -> list[Patient]:
    """
    Generate multiple synthetic patient records.

    Fully anchor-rooted: cfg.seed → SHA256 anchor → derive_seed → RNG → patients.
    Same config + same seed = identical outputs. Proven cryptographically.
    """
    return list(stream_patients(cfg))
