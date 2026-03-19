# Copyright (c) 2026 Cody Carlson
# Licensed under the Apache License, Version 2.0

"""
Demographics generator module for Synthetic Clinical Cohort Engine.

This module handles generation of patient demographic information including
age, sex, and ethnicity using deterministic random number generation.

All randomness comes from a single rng instance passed in by the pipeline.
No module creates its own RNG — the pipeline owns the seed.
"""

import random
from typing import Optional

from core.schema import Demographics
from core.config import DEFAULT_ETHNICITY_WEIGHTS


def _generate_patient_id(patient_seed: int) -> str:
    return f"SYN-{patient_seed:08x}"


def _weighted_choice(rng: random.Random, options: list[str], weights: dict[str, float]) -> str:
    weight_list = [weights.get(opt, 0.0) for opt in options]
    total = sum(weight_list)
    if total == 0:
        return options[0]

    normalized = [w / total for w in weight_list]

    cumulative = []
    cumsum = 0.0
    for w in normalized:
        cumsum += w
        cumulative.append(cumsum)

    r = rng.random()
    for i, cum in enumerate(cumulative):
        if r <= cum:
            return options[i]
    return options[-1]


def generate_demographics(
    rng: random.Random,
    patient_seed: int,
    age_min: int,
    age_max: int,
    sex_ratio_female: float,
    ethnicity_weights: Optional[dict[str, float]],
    age_band_weights: Optional[list[tuple[int, int, float]]] = None,
) -> Demographics:
    """
    Generate demographic information for a single synthetic patient.

    Uses the passed-in rng instance for all randomness. The pipeline owns
    the seed — this module never creates its own RNG.

    Args:
        rng: Random number generator instance (owned by pipeline)
        patient_seed: Deterministic seed for this patient (used for ID only)
        age_min: Minimum age (inclusive)
        age_max: Maximum age (inclusive)
        sex_ratio_female: Probability of female sex (0.0-1.0)
        ethnicity_weights: Weights for ethnicity selection (or None for defaults)
        age_band_weights: Optional age band distribution weights

    Returns:
        Demographics object with generated values
    """
    patient_id = _generate_patient_id(patient_seed)

    default_age_bands = [(18, 44, 0.45), (45, 64, 0.33), (65, 80, 0.22)]
    age_bands = age_band_weights if age_band_weights is not None else default_age_bands

    valid_bands = []
    for lo, hi, weight in age_bands:
        clamped_lo = max(lo, age_min)
        clamped_hi = min(hi, age_max)
        if clamped_lo <= clamped_hi:
            valid_bands.append((clamped_lo, clamped_hi, weight))

    r = rng.random()

    if valid_bands:
        total_weight = sum(w for _, _, w in valid_bands)
        cumulative = 0.0
        band_lo, band_hi = valid_bands[0][0], valid_bands[0][1]
        for lo, hi, weight in valid_bands:
            cumulative += weight / total_weight
            if r <= cumulative:
                band_lo, band_hi = lo, hi
                break
    else:
        band_lo, band_hi = age_min, age_max

    age = rng.randint(band_lo, band_hi)

    sex = "female" if rng.random() < sex_ratio_female else "male"

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
