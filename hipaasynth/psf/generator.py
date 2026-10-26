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
PSF generator — synthetic patients at seven EHR sparsity levels (S1–S7).

Sparsity calibration context
-----------------------------
S7 (full) represents a well-resourced academic medical centre with complete
structured data.  S1–S3 represent the data reality of:

  * IHS (Indian Health Service) / tribal health facilities: documented gaps
    in lab availability, insurance coding, and visit-history continuity.
    Source: IHS Data Governance Framework (IHS, 2022); Sequist TD.
    N Engl J Med 2021;385(25):2373-2379.

  * Rural critical-access hospitals (CAHs): CMS data show smaller facilities
    have lower EHR-adoption rates and less complete structured data than
    urban academic centres.
    Source: Adler-Milstein J et al. Health Aff 2017;36(5):848-854.

  * Safety-net hospitals serving Medicaid / uninsured patients: fragmented
    records scattered across multiple facilities.
    Source: Decker SL. JAMA Intern Med 2013;173(18):1783-1784.

Level definitions (each level includes all fields of the levels above it):
  S7 — everything: demographics, labs, lab history, comorbidities,
        visit history, insurance, SES proxy, primary Dx.
  S6 — drop insurance_type and ses_proxy (SES data often absent in
        tribal / frontier records).
  S5 — also drop lab_history (only current labs retained).
  S4 — also drop visit_history.
  S3 — also drop comorbidities.
  S2 — also drop current_labs and primary_dx.
  S1 — only age, sex, race_ethnicity, geography_type, chief_complaint.
        Simulates an ED triage note from a facility with no EHR integration.

Note: race_ethnicity and geography_type are retained at all levels including
S1 because they are captured on the intake demographic sheet even in the most
resource-constrained settings, and because their presence is needed to expose
demographic-sparsity interaction bias in ScoredMockModel.
"""

import random
from typing import Any, Dict, List

from hipaasynth.core.hashing import stable_seed_from_id

# Ordered from least complete (S1) to most complete (S7).
SPARSITY_LEVELS: List[str] = ["S1", "S2", "S3", "S4", "S5", "S6", "S7"]

# Population distributions — representative of the IHS / tribal / rural population
# that lives in the S1-S3 data-sparsity zone.
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
_RACE_WEIGHTS = [0.35, 0.18, 0.20, 0.15, 0.07, 0.05]

_GEO_OPTS = ["Suburban", "Urban core", "Rural", "Frontier", "Tribal"]
_GEO_WEIGHTS = [0.20, 0.20, 0.25, 0.15, 0.20]

_SES_OPTS = ["High", "Middle", "Low"]
_SES_WEIGHTS = [0.15, 0.35, 0.50]

_INSURANCE_OPTS = [
    "Commercial",
    "Medicaid",
    "Medicare",
    "IHS / VA",
    "Uninsured / Self-pay",
]
_INSURANCE_WEIGHTS = [0.15, 0.30, 0.20, 0.15, 0.20]

_CHIEF_COMPLAINTS = [
    "Chest pain",
    "Shortness of breath",
    "Abdominal pain",
    "Headache",
    "Dizziness / syncope",
    "Weakness / fatigue",
    "Altered mental status",
    "Palpitations",
    "Back pain",
    "Cough",
]

_PRIMARY_DX = [
    "Acute coronary syndrome",
    "Congestive heart failure exacerbation",
    "COPD exacerbation",
    "Sepsis",
    "Ischemic stroke",
    "Diabetic ketoacidosis",
    "Pneumonia",
    "Pulmonary embolism",
    "Hypertensive urgency",
    "Acute kidney injury",
]

_COMORBIDITIES_POOL = [
    "Type 2 diabetes mellitus",
    "Hypertension",
    "Chronic kidney disease",
    "COPD",
    "Coronary artery disease",
    "Heart failure",
    "Atrial fibrillation",
    "Obesity",
    "Hyperlipidaemia",
    "Depression",
]


def _weighted_choice(rng: random.Random, options: list, weights: list) -> Any:
    r = rng.random()
    cumulative = 0.0
    for opt, w in zip(options, weights):
        cumulative += w
        if r < cumulative:
            return opt
    return options[-1]


def _generate_labs(rng: random.Random) -> Dict[str, Any]:
    return {
        "sodium_meql": round(rng.gauss(139, 4), 1),
        "potassium_meql": round(rng.gauss(4.0, 0.5), 1),
        "creatinine_mgdl": round(rng.gauss(1.0, 0.3), 2),
        "glucose_mgdl": round(rng.gauss(110, 30), 0),
        "hemoglobin_gdl": round(rng.gauss(12.5, 2.0), 1),
        "wbc_per_nl": round(rng.gauss(8.0, 2.5), 1),
        "troponin_ngl": round(rng.gauss(0.02, 0.015), 3),
        "bnp_pgml": round(rng.gauss(150, 100), 0),
    }


def _generate_lab_history(rng: random.Random) -> List[Dict[str, Any]]:
    entries = []
    for months_ago in [3, 6, 12]:
        entries.append({
            "months_ago": months_ago,
            "hba1c_pct": round(rng.gauss(7.2, 1.0), 1),
            "egfr_ml_min": round(rng.gauss(65, 20), 0),
            "ldl_mgdl": round(rng.gauss(110, 30), 0),
        })
    return entries


def _generate_visit_history(rng: random.Random) -> List[Dict[str, Any]]:
    entries = []
    for i, months_ago in enumerate([1, 4, 8, 14]):
        entries.append({
            "months_ago": months_ago,
            "visit_type": rng.choice(["PCP", "Specialist", "ED", "Urgent care"]),
            "facility": f"Clinic {i + 1}",
        })
    return entries


class PSFGenerator:
    """
    Generates synthetic patient records at a specified EHR sparsity level.

    Each patient dict contains a ``sparsity_level`` field so that
    :class:`~hipaasynth.core.model_interface.MockClinicalModel` and
    :class:`~hipaasynth.core.model_interface.ScoredMockModel` can apply the
    appropriate completeness weight without any additional configuration.

    Args:
        seed: Deterministic seed.  Same seed always produces identical output.
    """

    def __init__(self, seed: int = 42) -> None:
        self._seed = seed

    def generate(self, n: int, sparsity_level: str) -> List[Dict[str, Any]]:
        """
        Generate ``n`` patients at ``sparsity_level``.

        Args:
            n: Number of patients to generate.
            sparsity_level: One of S1–S7 (see module docstring).

        Returns:
            List of patient dicts ready for :class:`ModelInterface.evaluate`.
        """
        if sparsity_level not in SPARSITY_LEVELS:
            raise ValueError(
                f"Unknown sparsity level {sparsity_level!r}. "
                f"Choose from {SPARSITY_LEVELS}."
            )

        # Derive a level-specific seed so that generating S1 vs S7 populations
        # with the same seed still produces the same base demographics.
        level_seed = self._seed ^ stable_seed_from_id(sparsity_level)
        rng = random.Random(level_seed)

        patients = []
        for i in range(n):
            patient = self._build(rng, i, sparsity_level)
            patients.append(patient)
        return patients

    def generate_all_levels(self, n_per_level: int) -> Dict[str, List[Dict[str, Any]]]:
        """
        Convenience method: generate ``n_per_level`` patients at every level.

        Returns:
            Dict mapping sparsity level → list of patient dicts.
        """
        return {level: self.generate(n_per_level, level) for level in SPARSITY_LEVELS}

    # ------------------------------------------------------------------
    # Internal builders
    # ------------------------------------------------------------------

    def _build(
        self, rng: random.Random, idx: int, level: str
    ) -> Dict[str, Any]:
        """Assemble a patient dict for the given sparsity level."""

        # Core fields — always present at every level.
        age = rng.randint(18, 85)
        sex = _weighted_choice(rng, _SEX_OPTS, _SEX_WEIGHTS)
        race = _weighted_choice(rng, _RACE_OPTS, _RACE_WEIGHTS)
        geo = _weighted_choice(rng, _GEO_OPTS, _GEO_WEIGHTS)
        complaint = rng.choice(_CHIEF_COMPLAINTS)

        patient: Dict[str, Any] = {
            "patient_id": f"PSF_{level}_{idx:05d}",
            "sparsity_level": level,
            "age": age,
            "sex": sex,
            "race_ethnicity": race,
            "geography_type": geo,
            "chief_complaint": complaint,
        }

        # S2+ adds current labs and primary Dx.
        if level in ("S2", "S3", "S4", "S5", "S6", "S7"):
            patient["current_labs"] = _generate_labs(rng)
            patient["primary_dx"] = rng.choice(_PRIMARY_DX)

        # S3+ adds comorbidities.
        if level in ("S3", "S4", "S5", "S6", "S7"):
            n_comorbid = rng.randint(0, 4)
            patient["comorbidities"] = rng.sample(
                _COMORBIDITIES_POOL, min(n_comorbid, len(_COMORBIDITIES_POOL))
            )

        # S4+ adds visit history.
        if level in ("S4", "S5", "S6", "S7"):
            patient["visit_history"] = _generate_visit_history(rng)

        # S5+ adds lab history.
        if level in ("S5", "S6", "S7"):
            patient["lab_history"] = _generate_lab_history(rng)

        # S6+ adds SES and insurance.
        if level in ("S6", "S7"):
            patient["ses_proxy"] = _weighted_choice(rng, _SES_OPTS, _SES_WEIGHTS)
            patient["insurance_type"] = _weighted_choice(
                rng, _INSURANCE_OPTS, _INSURANCE_WEIGHTS
            )

        return patient
