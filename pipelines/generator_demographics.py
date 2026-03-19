# Copyright (c) 2026 Cody Carlson
# Licensed under the Apache License, Version 2.0

"""
Demographics generator module for Synthetic Clinical Cohort Engine.

This module handles generation of patient demographic information including
age, sex, and ethnicity using deterministic random number generation.
"""

import random
from typing import Optional

from core.schema import Demographics
from core.config import DEFAULT_ETHNICITY_WEIGHTS


def _derive_patient_seed(base_seed: Optional[int], idx: int) -> int:
    """
    Derive a deterministic per-patient seed from the base seed and patient index.
    
    Uses the formula: (base_seed * 1000003 + idx) & 0xFFFFFFFF
    to ensure consistent, reproducible seeds across runs.
    
    Args:
        base_seed: Global seed from config, or None for random
        idx: Patient index (0-based)
        
    Returns:
        Deterministic 32-bit integer seed for this patient
    """
    if base_seed is None:
        # Use a random base if no seed provided
        base_seed = random.randint(0, 0xFFFFFFFF)
    return (base_seed * 1000003 + idx) & 0xFFFFFFFF


def _generate_patient_id(patient_seed: int) -> str:
    """
    Generate a deterministic patient ID from the patient seed.
    
    Format: SYN-{patient_seed:08x} (hexadecimal, zero-padded to 8 digits)
    
    Args:
        patient_seed: The per-patient deterministic seed
        
    Returns:
        Synthetic patient identifier string
    """
    return f"SYN-{patient_seed:08x}"


def _weighted_choice(rng: random.Random, options: list[str], weights: dict[str, float]) -> str:
    """
    Make a weighted random choice from options using provided weights.
    
    Args:
        rng: Random number generator instance
        options: List of possible choices
        weights: Dictionary mapping each option to its weight (0.0-1.0)
        
    Returns:
        Selected option based on weighted probability
    """
    weight_list = [weights.get(opt, 0.0) for opt in options]
    total = sum(weight_list)
    if total == 0:
        return options[0]  # Fallback to first option
    
    # Normalize weights
    normalized = [w / total for w in weight_list]
    
    # Cumulative distribution
    cumulative = []
    cumsum = 0.0
    for w in normalized:
        cumsum += w
        cumulative.append(cumsum)
    
    # Random selection
    r = rng.random()
    for i, cum in enumerate(cumulative):
        if r <= cum:
            return options[i]
    return options[-1]  # Fallback to last option


def generate_demographics(
    base_seed: Optional[int],
    idx: int,
    age_min: int,
    age_max: int,
    sex_ratio_female: float,
    ethnicity_weights: Optional[dict[str, float]],
    age_band_weights: Optional[list[tuple[int, int, float]]] = None,
) -> Demographics:
    """
    Generate demographic information for a single synthetic patient.
    
    Uses deterministic random number generation based on the patient seed
    derived from base_seed and patient index.
    
    Args:
        base_seed: Global seed from config (or None for non-deterministic)
        idx: Patient index for seed derivation
        age_min: Minimum age (inclusive)
        age_max: Maximum age (inclusive)
        sex_ratio_female: Probability of female sex (0.0-1.0)
        ethnicity_weights: Weights for ethnicity selection (or None for defaults)
        
    Returns:
        Demographics object with generated values
    """
    # Derive patient-specific seed and RNG
    patient_seed = _derive_patient_seed(base_seed, idx)
    rng = random.Random(patient_seed)
    
    # Generate patient ID
    patient_id = _generate_patient_id(patient_seed)
    
    default_age_bands = [(18, 44, 0.45), (45, 64, 0.33), (65, 80, 0.22)]
    age_bands = age_band_weights if age_band_weights is not None else default_age_bands

    r = rng.random()
    cumulative = 0.0
    band_lo, band_hi = age_min, age_max

    for lo, hi, weight in age_bands:
        cumulative += weight
        if r <= cumulative:
            band_lo = max(lo, age_min)
            band_hi = min(hi, age_max)
            break
    if band_lo > band_hi:
        band_lo, band_hi = band_hi, band_lo

    age = rng.randint(band_lo, band_hi)
    
    # Generate sex based on ratio
    sex = "female" if rng.random() < sex_ratio_female else "male"
    
    # Generate ethnicity using weighted choice
    weights = ethnicity_weights if ethnicity_weights is not None else DEFAULT_ETHNICITY_WEIGHTS
    ethnicity_options = ["white", "black", "hispanic", "asian", "native", "other"]
    ethnicity = _weighted_choice(rng, ethnicity_options, weights)
    
    return Demographics(
        patient_id=patient_id,
        seed=patient_seed,
        age=age,
        sex=sex,
        ethnicity=ethnicity,
    )
