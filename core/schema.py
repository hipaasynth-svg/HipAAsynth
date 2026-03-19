# Copyright (c) 2026 Cody Carlson
# Licensed under the Apache License, Version 2.0

"""
Schema module for Synthetic Clinical Cohort Engine.

This module defines the dataclasses that represent the canonical schema
for synthetic patient records. All classes use standard library dataclasses.
"""

from dataclasses import dataclass, field, asdict
from typing import List, Any


@dataclass(frozen=True)
class Demographics:
    """
    Demographic information for a synthetic patient.
    
    Attributes:
        patient_id: Synthetic deterministic identifier (e.g., SYN-xxxxxxxx)
        seed: Per-patient deterministic seed used for generation
        age: Patient age in years
        sex: Biological sex ("female" or "male")
        ethnicity: Ethnicity category
    """
    patient_id: str
    seed: int
    age: int
    sex: str
    ethnicity: str


@dataclass(frozen=True)
class Anthropometrics:
    """
    Anthropometric information for a synthetic patient.

    Attributes:
        height_cm: Height in centimeters
        weight_kg: Weight in kilograms, derived from height and BMI
        bmi: Body mass index
        bmi_category: Standard adult BMI category
    """
    height_cm: float
    weight_kg: float
    bmi: float
    bmi_category: str


@dataclass(frozen=True)
class Condition:
    """
    Medical condition/diagnosis for a synthetic patient.
    
    Attributes:
        name: Condition identifier string
        onset_age: Age at which condition started (0 to current age)
        active: Whether the condition is currently active
    """
    name: str
    onset_age: int
    active: bool


@dataclass(frozen=True)
class LabResult:
    """
    Laboratory test result for a synthetic patient visit.
    
    Attributes:
        lab_name: Name of the lab test
        value: Numeric result value
        unit: Unit of measurement
        reference_range: Normal reference range string
        date_recorded: ISO date string (yyyy-mm-dd)
    """
    lab_name: str
    value: float
    unit: str
    reference_range: str
    date_recorded: str


@dataclass(frozen=True)
class Visit:
    """
    Healthcare visit/encounter for a synthetic patient.
    
    Attributes:
        visit_id: Synthetic deterministic visit identifier
        visit_type: Type of visit (outpatient, urgent_care, telehealth)
        visit_date: ISO date string (yyyy-mm-dd)
        primary_diagnosis: Primary diagnosis for the visit
        labs: List of lab results associated with this visit
    """
    visit_id: str
    visit_type: str
    visit_date: str
    primary_diagnosis: str
    labs: List[LabResult]


@dataclass(frozen=True)
class Patient:
    """
    Complete synthetic patient record.

    This is the top-level container for all patient information including
    demographics, anthropometrics, conditions, and visit history.
    """
    demographics: Demographics
    anthropometrics: Anthropometrics
    conditions: List[Condition]
    visits: List[Visit]
    engine_version: str
    schema_version: str
    synthetic: bool = True
    disclaimer: str = ""
    
    def to_dict(self) -> dict[str, Any]:
        """
        Convert Patient object to a dictionary.
        
        Uses dataclasses.asdict for recursive conversion of all nested dataclasses.
        
        Returns:
            Dictionary representation of the patient record
        """
        return asdict(self)
