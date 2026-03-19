# Copyright (c) 2026 Cody Carlson
# Licensed under the Apache License, Version 2.0

"""
Profile loader module for Synthetic Clinical Cohort Engine.

This module loads population demographic profiles from JSON files,
allowing the engine to generate cohorts calibrated to specific
cities, regions, or national baselines.
"""

import json
from pathlib import Path


def load_population_profile(path: str) -> dict:
    """
    Load a population profile from a JSON file.

    Converts age_bands (list of dicts) into age_band_weights
    (list of tuples) for direct use by the engine.

    Args:
        path: Path to the profile JSON file

    Returns:
        Dictionary containing the population profile data,
        with age_band_weights as list[tuple[int, int, float]]

    Raises:
        FileNotFoundError: If the profile file does not exist
        json.JSONDecodeError: If the file is not valid JSON
    """
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if "age_bands" in data and "age_band_weights" not in data:
        data["age_band_weights"] = [
            (b["min"], b["max"], b["weight"])
            for b in data["age_bands"]
        ]

    return data
