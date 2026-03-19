# Copyright (c) 2026 Cody Carlson
# Licensed under the Apache License, Version 2.0

"""
Numeric/lab value generator module for Synthetic Clinical Cohort Engine.

This module handles generation of laboratory test results with values that
are influenced by patient conditions (e.g., elevated glucose for diabetes).
"""

import random
import math
from datetime import datetime, timedelta
from typing import Optional

from core.schema import LabResult, Visit, Condition


# Lab test definitions with reference ranges and units
LAB_DEFINITIONS = {
    "Glucose": {
        "unit": "mg/dL",
        "reference_range": "70-99",
        "baseline_mean": 95.0,
        "baseline_std": 18.0,
    },
    "Creatinine": {
        "unit": "mg/dL",
        "reference_range": "0.6-1.3",
        "baseline_mean": 1.0,
        "baseline_std": 0.25,
    },
    "LDL": {
        "unit": "mg/dL",
        "reference_range": "<100",
        "baseline_mean": 111.0,
        "baseline_std": 32.0,
    },
    "WBC": {
        "unit": "10^9/L",
        "reference_range": "4.0-11.0",
        "baseline_mean": 7.0,
        "baseline_std": 2.0,
    },
}

# Condition-linked lab value modifiers
# Format: (condition_name, lab_name, min_override, max_override)
CONDITION_LAB_MODIFIERS = {
    ("type2_diabetes", "Glucose"): "diabetic_glucose",
    ("chronic_kidney_disease", "Creatinine"): (1.05, 1.25),
    ("hyperlipidemia", "LDL"): (160.0, 260.0),
}


def _normal_distribution(rng: random.Random, mean: float, std: float) -> float:
    """
    Generate a value from a normal distribution using Box-Muller transform.
    
    Args:
        rng: Random number generator instance
        mean: Mean of the distribution
        std: Standard deviation of the distribution
        
    Returns:
        Random value from N(mean, std^2)
    """
    # Box-Muller transform
    u1 = rng.random()
    u2 = rng.random()
    z0 = math.sqrt(-2.0 * math.log(u1)) * math.cos(2.0 * math.pi * u2)
    return mean + z0 * std


def _generate_lab_value(
    rng: random.Random,
    lab_name: str,
    condition_names: set[str],
) -> float:
    """
    Generate a lab value with condition-based modifications.
    
    Baseline values are drawn from normal distributions. If the patient has
    a relevant condition, the value is adjusted to be in the pathological range.
    
    Args:
        rng: Random number generator instance
        lab_name: Name of the lab test
        condition_names: Set of patient's condition names
        
    Returns:
        Generated lab value (float)
    """
    lab_def = LAB_DEFINITIONS[lab_name]
    baseline = _normal_distribution(rng, lab_def["baseline_mean"], lab_def["baseline_std"])
    
    for condition in condition_names:
        key = (condition, lab_name)
        if key in CONDITION_LAB_MODIFIERS:
            modifier = CONDITION_LAB_MODIFIERS[key]
            if modifier == "diabetic_glucose":
                baseline = max(baseline, _normal_distribution(rng, 164.0, 40.0))
            else:
                min_val, max_val = modifier
                pathological = rng.uniform(min_val, max_val)
                baseline = max(baseline, pathological)
    
    return round(max(0.0, baseline), 2)


_REFERENCE_DATE = datetime(2024, 6, 15)


def _generate_visit_date(rng: random.Random, reference_date: Optional[datetime] = None) -> str:
    """
    Generate a visit date within the last 365 days from a fixed reference.

    Uses a fixed reference date (2024-06-15) by default so that outputs
    are fully deterministic. Callers may override for testing.

    Args:
        rng: Random number generator instance
        reference_date: Reference date (defaults to _REFERENCE_DATE)

    Returns:
        ISO date string (yyyy-mm-dd)
    """
    if reference_date is None:
        reference_date = _REFERENCE_DATE

    offset_days = rng.randint(0, 365)
    visit_date = reference_date - timedelta(days=offset_days)
    return visit_date.strftime("%Y-%m-%d")


def generate_labs_for_visit(
    rng: random.Random,
    conditions: list[Condition],
    visit_date: str,
) -> list[LabResult]:
    """
    Generate lab results for a single visit.
    
    Generates all four lab types (Glucose, Creatinine, LDL, WBC) with values
    influenced by patient conditions.
    
    Args:
        rng: Random number generator instance
        conditions: Patient's conditions
        visit_date: Date of the visit (ISO format)
        
    Returns:
        List of LabResult objects
    """
    condition_names = {c.name for c in conditions}
    labs = []
    
    for lab_name, lab_def in LAB_DEFINITIONS.items():
        value = _generate_lab_value(rng, lab_name, condition_names)
        labs.append(LabResult(
            lab_name=lab_name,
            value=value,
            unit=lab_def["unit"],
            reference_range=lab_def["reference_range"],
            date_recorded=visit_date,
        ))
    
    return labs

def generate_visits(
    rng: random.Random,
    patient_seed: int,
    conditions: list[Condition],
    visits_min: int,
    visits_max: int,
    include_labs: bool,
) -> list[Visit]:
    """
    Generate visit records for a patient.
    
    Args:
        rng: Random number generator instance
        patient_seed: Patient's seed (used for visit_id generation)
        conditions: Patient's conditions
        visits_min: Minimum number of visits
        visits_max: Maximum number of visits
        include_labs: Whether to include lab results
        
    Returns:
        List of Visit objects
    """
    visits = []
    num_visits = rng.randint(visits_min, visits_max)
    
    # Determine primary diagnosis (first condition or routine check)
    primary_diagnosis = conditions[0].name if conditions else "routine_check"
    
    # Visit type options
    visit_types = ["outpatient", "urgent_care", "telehealth"]
    
    for j in range(num_visits):
        # Generate deterministic visit_id
        visit_id = f"V-{patient_seed:08x}-{j+1}"
        
        # Generate visit date
        visit_date = _generate_visit_date(rng)
        
        # Select visit type
        visit_type = rng.choice(visit_types)
        
        # Generate labs if requested
        labs = []
        if include_labs:
            labs = generate_labs_for_visit(rng, conditions, visit_date)
        
        visits.append(Visit(
            visit_id=visit_id,
            visit_type=visit_type,
            visit_date=visit_date,
            primary_diagnosis=primary_diagnosis,
            labs=labs,
        ))
    
    return visits
