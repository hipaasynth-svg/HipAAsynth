# Copyright (c) 2026 Cody Carlson
# Licensed under the Apache License, Version 2.0

"""
Anthropometrics generator module for Synthetic Clinical Cohort Engine.

This module generates deterministic adult anthropometric information including
height, BMI, derived weight, and BMI category using a patient-specific seed.
"""

import random

from core.schema import Anthropometrics


def _derive_anthropometric_seed(patient_seed: int) -> int:
    """
    Derive a deterministic anthropometrics sub-seed from the patient seed.

    Args:
        patient_seed: Per-patient deterministic seed from demographics

    Returns:
        Deterministic 32-bit integer sub-seed for anthropometric generation
    """
    return (patient_seed * 2654435761 + 1013904223) & 0xFFFFFFFF


def _clip(value: float, lower: float, upper: float) -> float:
    return min(max(value, lower), upper)


def _bmi_category(bmi: float) -> str:
    """
    Return the standard adult BMI category.
    """
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
    """
    Generate adult height in centimeters using sex-specific normal distributions.
    """
    if sex == "male":
        value = rng.gauss(176.0, 7.0)
    elif sex == "female":
        value = rng.gauss(162.0, 7.0)
    else:
        raise ValueError(f"Unsupported sex for anthropometric generation: {sex!r}")

    return round(_clip(value, 140.0, 205.0), 1)


def _generate_bmi(rng: random.Random, age: int, sex: str) -> float:
    """
    Generate adult BMI using a simple age/sex-adjusted modeled distribution.
    """
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
    """
    Derive weight in kilograms from height in centimeters and BMI.
    """
    height_m = height_cm / 100.0
    return round(bmi * (height_m ** 2), 1)


def generate_anthropometrics(patient_seed: int, age: int, sex: str) -> Anthropometrics:
    """
    Generate deterministic anthropometric information for a single adult patient.

    Args:
        patient_seed: Deterministic patient seed from demographics
        age: Patient age in years
        sex: Biological sex ("female" or "male")

    Returns:
        Anthropometrics object
    """
    anthro_seed = _derive_anthropometric_seed(patient_seed)
    rng = random.Random(anthro_seed)

    height_cm = _generate_height_cm(rng, sex)
    bmi = _generate_bmi(rng, age, sex)
    weight_kg = _weight_from_height_bmi(height_cm, bmi)

    return Anthropometrics(
        height_cm=height_cm,
        weight_kg=weight_kg,
        bmi=bmi,
        bmi_category=_bmi_category(bmi),
    )
