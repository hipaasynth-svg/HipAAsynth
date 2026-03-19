# Copyright (c) 2026 Cody Carlson
# Licensed under the Apache License, Version 2.0

"""
Pipeline module for Synthetic Clinical Cohort Engine.

This module provides the main generation pipeline functions for creating
synthetic patient records with full determinism and reproducibility.
"""

import random
from typing import Optional

from core.config import GenerationConfig, ENGINE_VERSION, SCHEMA_VERSION
from core.schema import Patient, Demographics, Condition, Visit
from pipelines.generator_demographics import generate_demographics, _derive_patient_seed
from pipelines.generator_anthropometrics import generate_anthropometrics
from pipelines.generator_conditions import generate_conditions
from pipelines.generator_numerics import generate_visits
from validation.validator import validate_patient
from core.profile_loader import load_population_profile


def stream_patients(cfg):
    """
    Yield patients one at a time.
    """
    for i in range(cfg.patient_count):
        yield generate_one_patient(cfg, i)


def generate_one_patient(cfg: GenerationConfig, idx: int) -> Patient:
    """
    Generate a single synthetic patient record.

    This function creates a complete patient record including demographics,
    anthropometrics, conditions, and optionally visits with lab results.
    The generation is deterministic based on the config seed and patient index.

    Args:
        cfg: Generation configuration
        idx: Patient index (0-based) for seed derivation

    Returns:
        Complete Patient record
    """
    # Derive patient-specific seed
    patient_seed = _derive_patient_seed(cfg.seed, idx)

    # Generate demographics (profile overrides are passed via _resolved_profile)
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
        base_seed=cfg.seed,
        idx=idx,
        age_min=cfg.age_min,
        age_max=cfg.age_max,
        sex_ratio_female=sex_ratio,
        ethnicity_weights=eth_weights,
        age_band_weights=age_band_weights,
    )

    # Generate anthropometrics
    anthropometrics = generate_anthropometrics(
        patient_seed=demographics.seed,
        age=demographics.age,
        sex=demographics.sex,
    )

    rng = random.Random(patient_seed ^ 0xA5A5A5A5)

    # Generate conditions
    conditions = generate_conditions(
        rng=rng,
        age=demographics.age,
        bmi=anthropometrics.bmi,
        required_condition=cfg.required_condition,
    )

    # Generate visits if requested
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

    # Create patient record
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

    # Validate the patient record
    validated_patient = validate_patient(patient)

    return validated_patient


def generate_patients(cfg: GenerationConfig) -> list[Patient]:
    """
    Generate multiple synthetic patient records.
    
    Generates N patient records according to the configuration. The generation
    is fully deterministic: same config + same seed = identical outputs.
    
    Args:
        cfg: Generation configuration
        
    Returns:
        List of Patient records
        
    Raises:
        ValueError: If config validation fails
    """
    # Validate config
    if cfg.patient_count < 1:
        raise ValueError("patient_count must be at least 1")
    if cfg.age_max < cfg.age_min:
        raise ValueError("age_max must be >= age_min")
    
    # Load population profile once if specified
    if cfg.population_profile_path:
        profile = load_population_profile(cfg.population_profile_path)
        object.__setattr__(cfg, '_resolved_profile', profile)

    patients = []
    for i in range(cfg.patient_count):
        patient = generate_one_patient(cfg, i)
        patients.append(patient)
    
    return patients
