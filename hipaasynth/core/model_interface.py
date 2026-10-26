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
Shared model interfaces for HipAAsynth.

This module provides the abstract base class ``ModelInterface`` and reference
mock-model implementations used by validation modules.

All implementations are deterministic and use only the Python standard library.
No PHI is used or referenced at any point.
"""

import math
import random
from abc import ABC, abstractmethod
from typing import Any, Dict


class ModelInterface(ABC):
    """Abstract base class for clinical model interfaces used by HipAAsynth."""

    @abstractmethod
    def evaluate(self, patient: Dict[str, Any]) -> float:
        """
        Evaluate a synthetic patient record and return a scalar score.

        Args:
            patient: A synthetic patient dictionary produced by a HipAAsynth pipeline.

        Returns:
            A float score, typically bounded to [0, 1].
        """
        raise NotImplementedError


def validate_model_score(value: Any, where: str) -> float:
    """Return ``value`` as a float if it is a usable model score, else raise.

    PSF (SDI) and CC (CDI) are ratios of mean scores, so a score must be a
    finite, non-negative real number. ``bool`` is rejected (it is an ``int``
    subclass but not a score), as are ``None``, strings and NaN/inf, which used
    to be summed silently or turned into SDI/CDI 0.0 (FAIL) without explanation.
    Scores above 1 are allowed: the interface says scores are only *typically*
    in [0, 1], and a ratio of means is scale-free.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        if type(value).__name__ not in ("float64", "float32", "int64", "int32"):
            raise TypeError(
                f"model.evaluate() returned {value!r} ({type(value).__name__}) for {where}; "
                "expected a finite, non-negative number"
            )
    score = float(value)
    if not math.isfinite(score) or score < 0:
        raise ValueError(
            f"model.evaluate() returned {value!r} for {where}; "
            "expected a finite, non-negative number"
        )
    return score


class MockClinicalModel(ModelInterface):
    """
    Concrete mock model that scores records based on clinical field completeness.

    The mock score is intentionally sensitive to sparsity and continuity so that
    the HipAAsynth framework can demonstrate detection of fairness degradation.
    A real model replaces this class by implementing :class:`ModelInterface`.
    """

    # Sparsity completeness weights shared with PSF.
    _PSF_COMPLETENESS: Dict[str, float] = {
        "S7": 1.00,
        "S6": 0.85,
        "S5": 0.70,
        "S4": 0.55,
        "S3": 0.40,
        "S2": 0.25,
        "S1": 0.10,
    }

    # Care-continuity completeness weights shared with CC.
    _CC_COMPLETENESS: Dict[str, float] = {
        "PROFILE_A": 1.00,
        "PROFILE_B": 0.70,
        "PROFILE_C": 0.40,
        "PROFILE_D": 0.10,
    }

    def __init__(self, seed: int = 42) -> None:
        """
        Initialize the mock model.

        Args:
            seed: Random seed for reproducible patient-level score noise.
        """
        self.rng = random.Random(seed)

    def evaluate(self, patient: Dict[str, Any]) -> float:
        """
        Compute a synthetic model score for ``patient``.

        The score is driven by the sparsity level or continuity profile
        (clinical completeness) plus a small amount of patient-level noise.

        Args:
            patient: Synthetic patient record.

        Returns:
            A score in [0, 1].
        """
        if "sparsity_level" in patient:
            # PSF-style patient.
            completeness = self._PSF_COMPLETENESS.get(patient["sparsity_level"], 0.0)
        elif "continuity_profile" in patient:
            # CC-style patient.
            completeness = self._CC_COMPLETENESS.get(patient["continuity_profile"], 0.0)
            clinical = patient.get("clinical", {})
            populated = sum(
                1
                for v in clinical.values()
                if v is not None and v != [] and v != {} and v != ""
            )
            completeness += min(populated / 12.0, 0.20)
        else:
            completeness = 0.50

        reliability = 0.90

        # Gaussian-ish noise using the Box-Muller transform.
        u1 = self.rng.random()
        u2 = self.rng.random()
        z0 = math.sqrt(max(-2.0 * math.log(u1), 0.0)) * math.cos(
            2.0 * math.pi * u2
        )
        noise = z0 * 0.03

        score = completeness * reliability + noise
        return max(0.0, min(1.0, score))


class ScoredMockModel(ModelInterface):
    """
    Mock model that returns scores weighted by both field density AND
    demographic factors.

    Used to simulate a biased model for fairness testing demonstration.
    Higher scores for: male, white, suburban, high SES, commercial insurance.
    Lower scores for: AIAN, frontier, uninsured, low SES, absent records.
    Useful for confirming fairness modules detect bias that MockClinicalModel
    cannot demonstrate.
    """

    # Sparsity completeness weights for PSF patients.
    _PSF_COMPLETENESS: Dict[str, float] = {
        "S7": 1.00,
        "S6": 0.85,
        "S5": 0.70,
        "S4": 0.55,
        "S3": 0.40,
        "S2": 0.25,
        "S1": 0.10,
    }

    # Care-continuity completeness weights for CC patients.
    _CC_COMPLETENESS: Dict[str, float] = {
        "PROFILE_A": 1.00,
        "PROFILE_B": 0.70,
        "PROFILE_C": 0.40,
        "PROFILE_D": 0.10,
    }

    def __init__(self, seed: int = 42) -> None:
        """
        Initialize the scored mock model.

        Args:
            seed: Random seed for reproducible patient-level score noise.
        """
        self.rng = random.Random(seed)

    def _demographic_adjustment(self, patient: Dict[str, Any]) -> float:
        """
        Compute a demographic adjustment factor.

        Positive values favor historically over-represented groups;
        negative values penalize under-represented groups.
        """
        adjustment = 0.0

        sex = patient.get("sex", "")
        if sex == "Male":
            adjustment += 0.02
        elif sex == "Female":
            adjustment -= 0.01

        race = patient.get("race_ethnicity", "")
        if "White" in race:
            adjustment += 0.03
        elif "American Indian or Alaska Native" in race:
            adjustment -= 0.06
        elif "Hispanic or Latino" in race:
            adjustment -= 0.03
        elif "Black" in race:
            adjustment -= 0.02

        geography = patient.get(
            "geography_type", patient.get("geography", "")
        )
        if "Suburban" in geography:
            adjustment += 0.02
        elif (
            "Frontier" in geography
            or "Rural" in geography
            or "Tribal" in geography
        ):
            adjustment -= 0.03
        elif "Urban core" in geography:
            adjustment -= 0.01

        ses = patient.get("ses_proxy", "")
        if ses == "High":
            adjustment += 0.02
        elif ses == "Low":
            adjustment -= 0.03

        insurance = patient.get(
            "insurance_type", patient.get("insurance_status", "")
        )
        if "Commercial" in insurance:
            adjustment += 0.02
        elif "Uninsured" in insurance or "Self-pay" in insurance:
            adjustment -= 0.03

        return adjustment

    def evaluate(self, patient: Dict[str, Any]) -> float:
        """
        Compute a synthetic biased model score for ``patient``.

        Args:
            patient: Synthetic patient record.

        Returns:
            A score in [0, 1].
        """
        if "sparsity_level" in patient:
            completeness = self._PSF_COMPLETENESS.get(
                patient["sparsity_level"], 0.0
            )
        elif "continuity_profile" in patient:
            completeness = self._CC_COMPLETENESS.get(
                patient["continuity_profile"], 0.0
            )
            clinical = patient.get("clinical", {})
            populated = sum(
                1
                for v in clinical.values()
                if v is not None and v != [] and v != {} and v != ""
            )
            completeness += min(populated / 12.0, 0.15)
        else:
            completeness = 0.50

        demographic_adj = self._demographic_adjustment(patient)

        # Gaussian-ish noise using the Box-Muller transform.
        u1 = self.rng.random()
        u2 = self.rng.random()
        z0 = math.sqrt(max(-2.0 * math.log(u1), 0.0)) * math.cos(
            2.0 * math.pi * u2
        )
        noise = z0 * 0.025

        score = completeness + demographic_adj + noise
        return max(0.0, min(1.0, score))
