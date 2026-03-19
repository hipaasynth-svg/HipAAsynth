# Copyright (c) 2026 Cody Carlson
# Licensed under the Apache License, Version 2.0

"""
Pipeline module for Synthetic Clinical Cohort Engine.

This module provides the main generation pipeline functions for creating
synthetic patient records with full determinism and reproducibility.

Architecture: ONE master_rng per cohort, ONE rng per patient.
No module creates its own RNG. Every random call flows from the master seed.
"""

import random

from core.config import GenerationConfig, ENGINE_VERSION, SCHEMA_VERSION
from core.schema import Patient, Demographics, Condition, Visit
from pipelines.generator_demographics import generate_demographics
from pipelines.generator_anthropometrics import generate_anthropometrics
from pipelines.generator_conditions import generate_conditions
from pipelines.generator_numerics import generate_visits
from validation.validator import validate_patient
from core.profile_loader import load_population_profile


def _derive_patient_seed(master_rng: random.Random) -> int:
    return master_rng.randint(0, 0xFFFFFFFF)


def stream_patients(cfg):
    """
    Yield patients one at a time.
    """
    if cfg.patient_count < 1:
        raise ValueError("patient_count must be at least 1")
    if cfg.age_max < cfg.age_min:
        raise ValueError("age_max must be >= age_min")

    if cfg.population_profile_path:
        profile = load_population_profile(cfg.population_profile_path)
        object.__setattr__(cfg, '_resolved_profile', profile)

    master_rng = random.Random(cfg.seed)
    for i in range(cfg.patient_count):
        patient_seed = _derive_patient_seed(master_rng)
        yield _generate_one(cfg, patient_seed)


def _generate_one(cfg: GenerationConfig, patient_seed: int) -> Patient:
    """
    Generate a single synthetic patient record.

    ONE rng per patient. Created here, passed to every module.
    No module creates its own RNG instance.
    """
    rng = random.Random(patient_seed)

    profile = getattr(cfg, '_resolved_profile', None)
    age_band_weights = cfg.age_band_weights
    sex_ratio = cfg.sex_ratio_female
    eth_weights = cfg.ethnicity_weights

    if profile:
        if not age_band_weights:
            age_band_weights = [
                (b["min"], b["max"], b["weight"])
                for b in profile.get("age_bands", [])
            ]
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

    patient = Patient(
        demographics=demographics,
        anthropometrics=anthropometrics,
        conditions=conditions,
        visits=visits,
        engine_version=ENGINE_VERSION,
        schema_version=SCHEMA_VERSION,
        synthetic=True,
        disclaimer=cfg.synthetic_disclaimer,
    )

    validated_patient = validate_patient(patient)
    return validated_patient


def generate_one_patient(cfg: GenerationConfig, idx: int) -> Patient:
    """
    Backward-compatible wrapper: generate patient at index idx.
    Uses master_rng to derive the same patient_seed as generate_patients.
    """
    master_rng = random.Random(cfg.seed)
    for _ in range(idx + 1):
        patient_seed = _derive_patient_seed(master_rng)
    return _generate_one(cfg, patient_seed)


def generate_patients(cfg: GenerationConfig) -> list[Patient]:
    """
    Generate multiple synthetic patient records.

    Fully deterministic: same config + same seed = identical outputs.
    ONE master_rng seeds everything. No global random state touched.
    """
    return list(stream_patients(cfg))
