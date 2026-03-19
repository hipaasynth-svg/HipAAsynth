# Copyright (c) 2026 Cody Carlson
# Licensed under the Apache License, Version 2.0

"""
Anthropometrics generator module for Synthetic Clinical Cohort Engine.

This module generates deterministic adult anthropometric information including
height, BMI, derived weight, and BMI category.

All randomness comes from a single rng instance passed in by the pipeline.
No module creates its own RNG — the pipeline owns the seed.
"""

import random

from core.schema import Anthropometrics


def _clip(value: float, lower: float, upper: float) -> float:
    return min(max(value, lower), upper)


def _bmi_category(bmi: float) -> str:
    if bmi < 18.5:
        return "underweight"
    if bmi < 25.0:
        return "normal"
    if bmi < 30.0:
        return "overweight"
    if bmi < 35.0:
        return "obesity_class_1"
    if bmi < 40.0:
        return "obesity_class_2"
    return "obesity_class_3"


def _generate_height_cm(rng: random.Random, sex: str) -> float:
    if sex == "male":
        value = rng.gauss(176.0, 7.0)
    elif sex == "female":
        value = rng.gauss(162.0, 7.0)
    else:
        raise ValueError(f"Unsupported sex for anthropometric generation: {sex!r}")

    return round(_clip(value, 140.0, 205.0), 1)


def _generate_bmi(rng: random.Random, age: int, sex: str) -> float:
    if age < 18:
        raise ValueError("Adult anthropometric generation does not support age < 18.")

    mean = 29.0

    if age < 25:
        mean -= 2.0
    elif age >= 65:
        mean -= 0.5

    if sex == "female":
        mean += 0.3
    elif sex != "male":
        raise ValueError(f"Unsupported sex for BMI generation: {sex!r}")

    value = rng.gauss(mean, 5.0)
    return round(_clip(value, 15.0, 60.0), 1)


def _weight_from_height_bmi(height_cm: float, bmi: float) -> float:
    height_m = height_cm / 100.0
    return round(bmi * (height_m ** 2), 1)


def generate_anthropometrics(rng: random.Random, age: int, sex: str) -> Anthropometrics:
    """
    Generate deterministic anthropometric information for a single adult patient.

    Uses the passed-in rng instance for all randomness. The pipeline owns
    the seed — this module never creates its own RNG.

    Args:
        rng: Random number generator instance (owned by pipeline)
        age: Patient age in years
        sex: Biological sex ("female" or "male")

    Returns:
        Anthropometrics object
    """
    height_cm = _generate_height_cm(rng, sex)
    bmi = _generate_bmi(rng, age, sex)
    weight_kg = _weight_from_height_bmi(height_cm, bmi)

    return Anthropometrics(
        height_cm=height_cm,
        weight_kg=weight_kg,
        bmi=bmi,
        bmi_category=_bmi_category(bmi),
    )
