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
CC generator — synthetic patients at four care-continuity profiles (PROFILE_A–D).

Continuity calibration context
--------------------------------
PROFILE_A (full continuity) represents an insured patient with a long-standing
relationship with a single primary-care provider and coordinated specialist care.
PROFILE_D (minimal continuity) represents a patient whose healthcare system
interaction is limited to emergency-department visits with no established PCP,
no medication list, and no prior-record integration.

The four profiles are calibrated to:

  * Medicaid churn: ~25% of Medicaid enrollees experience a coverage gap within
    12 months, disrupting continuity.  This produces PROFILE_C-like fragmentation.
    Source: Roberts ET et al. *Health Aff* 2018;37(10):1594-1602.

  * ED-reliant populations: AHRQ data show ~8% of ED visits are by patients
    with no usual source of care — the PROFILE_D patient.
    Source: AHRQ, *Emergency Department Use, 2012* (Statistical Brief #179).

  * Rural provider shortages: HRSA Health Professional Shortage Area (HPSA)
    designations correlate with lower continuity due to workforce gaps.
    Source: HRSA, *Health Workforce Shortage Areas*, 2023.

Profile definitions:
  PROFILE_A — Single PCP, consistent visit history, complete medication
               reconciliation, all labs in one system.  Ideal record.
  PROFILE_B — 2–3 providers, some visit gaps (3–6 months), medication list
               mostly current, minor duplications.  Typical suburban patient.
  PROFILE_C — 4+ providers across multiple systems, large gaps (6–12 months),
               medication discrepancies, some duplicate records, Medicaid churn.
  PROFILE_D — ED-only care, no established PCP, no medication list,
               single-visit snapshot.  Highest undertriage risk.

The ``continuity_profile`` field is required by
:class:`~hipaasynth.core.model_interface.MockClinicalModel` and
:class:`~hipaasynth.core.model_interface.ScoredMockModel` to apply the correct
completeness weight.  The ``clinical`` dict population density drives an
additional completeness bonus in the mock models.
"""

import random
from typing import Any, Dict, List

from hipaasynth.core.hashing import stable_seed_from_id

CONTINUITY_PROFILES: List[str] = ["PROFILE_A", "PROFILE_B", "PROFILE_C", "PROFILE_D"]

# ── Demographics ─────────────────────────────────────────────────────────────

_SEX_OPTS = ["Male", "Female"]
_SEX_WEIGHTS = [0.49, 0.51]

_RACE_OPTS = [
    "White",
    "Black or African American",
    "Hispanic or Latino",
    "American Indian or Alaska Native",
    "Asian",
    "Other / Multiracial",
]
_RACE_WEIGHTS = [0.38, 0.20, 0.20, 0.10, 0.07, 0.05]

_GEO_OPTS = ["Suburban", "Urban core", "Rural", "Frontier"]
_GEO_WEIGHTS = [0.30, 0.30, 0.25, 0.15]

# Per-profile insurance distributions
_INSURANCE_BY_PROFILE = {
    "PROFILE_A": ["Commercial", "Medicare"],
    "PROFILE_B": ["Commercial", "Medicare", "Medicaid"],
    "PROFILE_C": ["Medicaid", "Uninsured / Self-pay", "Commercial"],
    "PROFILE_D": ["Uninsured / Self-pay", "Medicaid"],
}
_INSURANCE_WEIGHTS_BY_PROFILE = {
    "PROFILE_A": [0.65, 0.35],
    "PROFILE_B": [0.45, 0.30, 0.25],
    "PROFILE_C": [0.55, 0.30, 0.15],
    "PROFILE_D": [0.65, 0.35],
}

# ── Clinical field pools ──────────────────────────────────────────────────────

_ACTIVE_PROBLEMS = [
    "Hypertension",
    "Type 2 diabetes mellitus",
    "Hyperlipidaemia",
    "Coronary artery disease",
    "COPD",
    "Chronic kidney disease",
    "Atrial fibrillation",
    "Obesity",
    "Heart failure",
    "Depression",
]

_MEDICATION_CLASSES = [
    "ACE inhibitor / ARB",
    "Beta-blocker",
    "Statin",
    "Metformin",
    "SGLT2 inhibitor",
    "Loop diuretic",
    "Anticoagulant",
    "Antiplatelet",
    "Inhaled corticosteroid",
    "SSRI",
]

_ALLERGIES = ["Penicillin", "Sulfa", "NSAIDs", "Contrast dye", "Latex"]


def _weighted_choice(rng: random.Random, options: list, weights: list) -> Any:
    r = rng.random()
    cumulative = 0.0
    for opt, w in zip(options, weights):
        cumulative += w
        if r < cumulative:
            return opt
    return options[-1]


def _build_clinical_a(rng: random.Random) -> Dict[str, Any]:
    """Full continuity — 12 clinical fields, all populated."""
    n_problems = rng.randint(2, 5)
    n_meds = rng.randint(3, 7)
    return {
        "pcp_id": f"PCP_{rng.randint(1000, 9999)}",
        "pcp_years": rng.randint(3, 15),
        "active_problems": rng.sample(_ACTIVE_PROBLEMS, min(n_problems, len(_ACTIVE_PROBLEMS))),
        "medication_list": rng.sample(_MEDICATION_CLASSES, min(n_meds, len(_MEDICATION_CLASSES))),
        "medication_reconciled": True,
        "allergies": rng.sample(_ALLERGIES, rng.randint(0, 2)),
        "last_visit_months_ago": rng.randint(1, 3),
        "visit_gap_months": rng.randint(0, 3),
        "provider_count": 1,
        "systems_count": 1,
        "labs_available": True,
        "advance_directive": rng.choice([True, False]),
    }


def _build_clinical_b(rng: random.Random) -> Dict[str, Any]:
    """Moderate continuity — most fields present, minor gaps."""
    n_problems = rng.randint(1, 4)
    n_meds = rng.randint(2, 5)
    return {
        "pcp_id": f"PCP_{rng.randint(1000, 9999)}",
        "pcp_years": rng.randint(1, 5),
        "active_problems": rng.sample(_ACTIVE_PROBLEMS, min(n_problems, len(_ACTIVE_PROBLEMS))),
        "medication_list": rng.sample(_MEDICATION_CLASSES, min(n_meds, len(_MEDICATION_CLASSES))),
        "medication_reconciled": rng.random() < 0.75,
        "allergies": rng.sample(_ALLERGIES, rng.randint(0, 1)),
        "last_visit_months_ago": rng.randint(3, 6),
        "visit_gap_months": rng.randint(3, 6),
        "provider_count": rng.randint(2, 3),
        "systems_count": rng.randint(1, 2),
        "labs_available": rng.random() < 0.85,
        "advance_directive": None,
    }


def _build_clinical_c(rng: random.Random) -> Dict[str, Any]:
    """Low continuity — fragmented across systems, large gaps."""
    n_problems = rng.randint(0, 3)
    n_meds = rng.randint(0, 4)
    return {
        "pcp_id": None,  # No consistent PCP
        "pcp_years": None,
        "active_problems": rng.sample(_ACTIVE_PROBLEMS, min(n_problems, len(_ACTIVE_PROBLEMS))),
        "medication_list": rng.sample(_MEDICATION_CLASSES, min(n_meds, len(_MEDICATION_CLASSES))),
        "medication_reconciled": rng.random() < 0.30,
        "allergies": [],  # Unknown
        "last_visit_months_ago": rng.randint(6, 12),
        "visit_gap_months": rng.randint(6, 12),
        "provider_count": rng.randint(4, 7),
        "systems_count": rng.randint(2, 4),
        "labs_available": rng.random() < 0.40,
        "advance_directive": None,
    }


def _build_clinical_d(rng: random.Random) -> Dict[str, Any]:
    """Minimal continuity — ED-only snapshot, no history."""
    return {
        "pcp_id": None,
        "pcp_years": None,
        "active_problems": [],  # Unknown at presentation
        "medication_list": [],  # No reconciled list
        "medication_reconciled": False,
        "allergies": [],  # Unknown
        "last_visit_months_ago": None,
        "visit_gap_months": None,
        "provider_count": 0,
        "systems_count": 0,
        "labs_available": False,
        "advance_directive": None,
    }


_CLINICAL_BUILDERS = {
    "PROFILE_A": _build_clinical_a,
    "PROFILE_B": _build_clinical_b,
    "PROFILE_C": _build_clinical_c,
    "PROFILE_D": _build_clinical_d,
}


class CCGenerator:
    """
    Generates synthetic patient records at a specified care-continuity profile.

    Each patient dict contains a ``continuity_profile`` field so that
    :class:`~hipaasynth.core.model_interface.MockClinicalModel` and
    :class:`~hipaasynth.core.model_interface.ScoredMockModel` apply the
    appropriate completeness weight.

    Args:
        seed: Deterministic seed.  Same seed always produces identical output.
    """

    def __init__(self, seed: int = 42) -> None:
        self._seed = seed

    def generate(self, n: int, profile: str) -> List[Dict[str, Any]]:
        """
        Generate ``n`` patients at the given continuity ``profile``.

        Args:
            n: Number of patients to generate.
            profile: One of PROFILE_A–PROFILE_D (see module docstring).

        Returns:
            List of patient dicts ready for :class:`ModelInterface.evaluate`.
        """
        if profile not in CONTINUITY_PROFILES:
            raise ValueError(
                f"Unknown continuity profile {profile!r}. " f"Choose from {CONTINUITY_PROFILES}."
            )
        profile_seed = self._seed ^ stable_seed_from_id(profile)
        rng = random.Random(profile_seed)
        return [self._build(rng, i, profile) for i in range(n)]

    def generate_all_profiles(self, n_per_profile: int) -> Dict[str, List[Dict[str, Any]]]:
        """
        Convenience method: generate ``n_per_profile`` patients at every profile.

        Returns:
            Dict mapping profile → list of patient dicts.
        """
        return {p: self.generate(n_per_profile, p) for p in CONTINUITY_PROFILES}

    def generate_matched_pair(self, base_seed: int) -> Dict[str, Dict[str, Any]]:
        """
        Generate one patient at every profile sharing the same demographics.

        This is used by the CCAudit to measure *transition consistency*: the
        same clinical facts (age, sex, race, chief complaint) are presented
        first as PROFILE_A then as PROFILE_D.  Any change in model output is
        attributable purely to record completeness, not clinical content.

        Args:
            base_seed: Seeds the demographic generation; the same value at
                every profile produces the same demographics.

        Returns:
            Dict mapping profile → patient dict.
        """
        demo_rng = random.Random(base_seed)
        age = demo_rng.randint(18, 85)
        sex = _weighted_choice(demo_rng, _SEX_OPTS, _SEX_WEIGHTS)
        race = _weighted_choice(demo_rng, _RACE_OPTS, _RACE_WEIGHTS)
        geo = _weighted_choice(demo_rng, _GEO_OPTS, _GEO_WEIGHTS)
        complaint = demo_rng.choice(
            [
                "Chest pain",
                "Shortness of breath",
                "Altered mental status",
                "Weakness / fatigue",
                "Abdominal pain",
            ]
        )

        result: Dict[str, Dict[str, Any]] = {}
        for profile in CONTINUITY_PROFILES:
            clin_rng = random.Random(base_seed ^ stable_seed_from_id(profile))
            ins_opts = _INSURANCE_BY_PROFILE[profile]
            ins_wts = _INSURANCE_WEIGHTS_BY_PROFILE[profile]
            insurance = _weighted_choice(clin_rng, ins_opts, ins_wts)
            clinical = _CLINICAL_BUILDERS[profile](clin_rng)
            result[profile] = {
                "patient_id": f"CC_PAIR_{base_seed}_{profile}",
                "continuity_profile": profile,
                "age": age,
                "sex": sex,
                "race_ethnicity": race,
                "geography_type": geo,
                "chief_complaint": complaint,
                "insurance_status": insurance,
                "clinical": clinical,
            }
        return result

    # ------------------------------------------------------------------
    # Internal builder
    # ------------------------------------------------------------------

    def _build(self, rng: random.Random, idx: int, profile: str) -> Dict[str, Any]:
        age = rng.randint(18, 85)
        sex = _weighted_choice(rng, _SEX_OPTS, _SEX_WEIGHTS)
        race = _weighted_choice(rng, _RACE_OPTS, _RACE_WEIGHTS)
        geo = _weighted_choice(rng, _GEO_OPTS, _GEO_WEIGHTS)
        complaint = rng.choice(
            [
                "Chest pain",
                "Shortness of breath",
                "Headache",
                "Dizziness / syncope",
                "Altered mental status",
                "Weakness / fatigue",
                "Abdominal pain",
                "Palpitations",
            ]
        )

        ins_opts = _INSURANCE_BY_PROFILE[profile]
        ins_wts = _INSURANCE_WEIGHTS_BY_PROFILE[profile]
        insurance = _weighted_choice(rng, ins_opts, ins_wts)

        clinical = _CLINICAL_BUILDERS[profile](rng)

        return {
            "patient_id": f"CC_{profile}_{idx:05d}",
            "continuity_profile": profile,
            "age": age,
            "sex": sex,
            "race_ethnicity": race,
            "geography_type": geo,
            "chief_complaint": complaint,
            "insurance_status": insurance,
            "clinical": clinical,
        }
