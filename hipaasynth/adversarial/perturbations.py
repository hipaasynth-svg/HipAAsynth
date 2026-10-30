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
adversarial/perturbations.py
─────────────────────────────
Profile-aware stochastic drift perturbations.

Profile is resolved via a filename lookup table, not substring matching.
Any profile filename not in the table falls to "default" explicitly.

GAP 1 FIX (6AAST Axis 2):
  apply_noise() derives noise_sigma from within-cohort observed variance
  read from the profile JSON, satisfying the pre-registration requirement
  that sigma is variance-derived, not a fixed multiplier.
"""

import copy
import json
import random
import os

from hipaasynth.core.hashing import stable_seed_from_id

_PROFILE_PARAMS = {
    "rural": {"dropout_year": 4, "comorbidity_rate": 0.4, "age_correction": -0.5},
    "tribal": {"dropout_year": 2, "comorbidity_rate": 0.6, "age_correction": -0.3},
    "urban": {"dropout_year": 6, "comorbidity_rate": 0.25, "age_correction": -0.2},
    "default": {"dropout_year": 3, "comorbidity_rate": 0.35, "age_correction": -0.3},
}

# Explicit filename → profile type mapping.
# Add new profiles here when they are created.
_FILENAME_TO_TYPE = {
    "minot_nd.json": "rural",
    "nd_tribal_region_a.json": "tribal",
    "nd_tribal_region_a_v2.json": "tribal",
    "nd_tribal_region_b.json": "tribal",
    "nd_tribal_region_b_v2.json": "tribal",
    "fargo_nd.json": "urban",
    "us_default.json": "default",
    "karachi_pakistan.json": "default",
    "lagos_nigeria.json": "default",
}

# Continuous variable → observation key mapping.
# Maps the profile continuous_vars key to the field name used in patient observations.
_VAR_TO_OBS_KEYS = {
    "hba1c": ["hba1c", "hba1c_initial"],
    "bmi": ["bmi"],
    "systolic_bp": ["sbp_initial", "sbp_admission", "sbp"],
    "creatinine": ["creatinine_initial", "creatinine"],
    "egfr": ["egfr", "egfr_initial"],
}

# Fallback reference values (NHANES 2017-2020 US national) used when a profile
# does not define continuous_vars.  These are never used when continuous_vars
# is present in the profile.
_REFERENCE_STD = {
    "hba1c": 1.5,
    "bmi": 7.5,
    "systolic_bp": 18.5,
    "creatinine": 0.42,
    "egfr": 24.0,
}


def _resolve_profile_type(profile_path: str | None) -> str:
    """
    Resolve a profile file path to a perturbation parameter set.
    Uses explicit filename lookup — no substring matching.
    """
    if not profile_path:
        return "default"
    filename = os.path.basename(profile_path)
    return _FILENAME_TO_TYPE.get(filename, "default")


def _load_continuous_var_stds(profile_path: str) -> dict:
    """
    Load within-cohort observed standard deviations from the profile JSON.

    Returns a dict mapping variable name → observed_std.
    Falls back to _REFERENCE_STD for any variable not found in the profile,
    so the method always returns a complete set of five variables.
    """
    stds = dict(_REFERENCE_STD)

    if not profile_path or not os.path.isfile(profile_path):
        return stds

    try:
        with open(profile_path) as f:
            profile = json.load(f)
    except (json.JSONDecodeError, OSError):
        return stds

    cv = profile.get("continuous_vars", {})
    for var in _REFERENCE_STD:
        entry = cv.get(var)
        if isinstance(entry, dict) and "observed_std" in entry:
            std_val = entry["observed_std"]
            if isinstance(std_val, (int, float)) and std_val > 0:
                stds[var] = float(std_val)

    return stds


class PerturbationEngine:
    """
    Applies stochastic, profile-aware drift perturbations to synthetic timelines.

    Perturbations are driven by:
      - Profile type resolved from the profile_path in timeline metadata
      - Per-patient seeded RNG (patient drifts identically across runs)
      - Rates calibrated to approximate real population drift patterns

    Profile types and their clinical basis:
      rural   — higher comorbidity accumulation (BRFSS rural data),
                delayed treatment dropout vs urban
      tribal  — earliest treatment dropout (IHS data on care access gaps),
                steepest comorbidity curve (diabetes/HTN/CKD burden)
      urban   — moderate drift, standard aging curve (BRFSS urban)
      default — US national baseline fallback
    """

    def apply(self, timelines, profile_path: str | None = None):
        # Resolve profile type: prefer explicit argument, fall back to metadata
        if profile_path is None and timelines:
            first_meta = (
                timelines[0]["timeline"][0].get("_meta", {}) if timelines[0]["timeline"] else {}
            )
            profile_path = first_meta.get("profile_path")

        profile_key = _resolve_profile_type(profile_path)
        params = _PROFILE_PARAMS[profile_key]

        dropout_year = params["dropout_year"]
        comorbidity_rate = params["comorbidity_rate"]
        age_correction = params["age_correction"]

        for p in timelines:
            # Stable cross-process seed (determinism contract)
            rng = random.Random(stable_seed_from_id(p["patient_id"], salt=0xA1))

            for t in p["timeline"]:
                y = t["_meta"]["year"]

                if y >= dropout_year and rng.random() < 0.3:
                    t["treatment"] = 0

                if y >= 4 and rng.random() < comorbidity_rate:
                    t["comorbidities"] += 1

                if y >= 5:
                    t["age"] = max(18, t["age"] + round(age_correction))

        return timelines

    def apply_noise(self, timelines, profile_path: str, noise_sigma_multiplier: float = 0.05):
        """
        Apply Gaussian noise to continuous clinical variables.

        Noise sigma is derived from within-cohort observed variance read from
        the profile JSON (6AAST Axis 2).  This satisfies
        the pre-registration requirement that sigma is variance-derived, not
        a fixed multiplier.

        Args:
            timelines:              Patient timeline list.
            profile_path:           Path to the cohort profile JSON (required).
                                    Used to read per-variable observed_std.
            noise_sigma_multiplier: Multiplier applied to observed_std to derive
                                    the per-variable noise sigma.
                                    Default 0.05 (5% of cohort std).

        Returns:
            timelines with Gaussian noise applied in-place to matching
            observation keys.  Each timeline entry gains a
            '_noise_metadata' dict with the derived sigmas logged.
        """
        observed_stds = _load_continuous_var_stds(profile_path)

        noise_sigmas = {var: observed_stds[var] * noise_sigma_multiplier for var in observed_stds}

        for p in timelines:
            # Stable cross-process seed namespaced for noise (salt 0xB2)
            rng = random.Random(stable_seed_from_id(p["patient_id"], salt=0xB2))

            for t in p["timeline"]:
                patient_dict = t.get("_patient_dict")
                if patient_dict is None:
                    continue

                obs = patient_dict.get("observations", {})

                for var, sigma in noise_sigmas.items():
                    obs_keys = _VAR_TO_OBS_KEYS.get(var, [])
                    for key in obs_keys:
                        if key in obs and isinstance(obs[key], (int, float)):
                            noise = rng.gauss(0.0, sigma)
                            obs[key] = round(obs[key] + noise, 4)
                            break

                t["_noise_metadata"] = {
                    "noise_sigmas_derived": noise_sigmas,
                    "noise_sigma_multiplier": noise_sigma_multiplier,
                    "profile_path": profile_path,
                    "observed_stds_source": "profile_continuous_vars",
                }

        return timelines

    def apply_missingness(self, timelines: list, missingness_rate: float) -> list:
        """
        Randomly null observation fields to simulate missing clinical data.

        For each timeline state, _patient_dict is deep-copied before any
        modification so that missingness does not compound with apply_noise()
        mutations on shared references.

        Fields are selected for nulling at the given rate using a per-patient
        seeded RNG (salt 0xC3) so the same patient receives the same missing
        fields across independent runs (determinism contract).

        Ground-truth flags (sepsis_flag, stroke_flag) are never nulled.

        Args:
            timelines:        Patient timeline list.
            missingness_rate: Fraction of non-None observation fields to null.
                              Expected values: 0.05, 0.10, 0.15, or 0.20.

        Returns:
            timelines with observation fields nulled in-place on fresh
            _patient_dict copies.  Each timeline entry gains a
            '_missingness_metadata' dict.
        """
        _PROTECTED = {"sepsis_flag", "stroke_flag"}

        for p in timelines:
            # Stable cross-process seed namespaced for missingness (salt 0xC3)
            rng = random.Random(stable_seed_from_id(p["patient_id"], salt=0xC3))

            for t in p["timeline"]:
                patient_dict = t.get("_patient_dict")
                if patient_dict is None:
                    continue

                # Deep copy before modifying — required so missingness does not
                # compound with apply_noise() mutations on shared references.
                patient_dict = copy.deepcopy(patient_dict)
                t["_patient_dict"] = patient_dict

                obs = patient_dict.get("observations", {})

                # Candidate fields: non-None and not ground-truth protected.
                candidates = [k for k, v in obs.items() if v is not None and k not in _PROTECTED]

                fields_available = len(candidates)

                # Sample without replacement at the given rate.
                k = max(0, round(fields_available * missingness_rate))
                fields_nulled = rng.sample(candidates, k) if k and candidates else []

                for field in fields_nulled:
                    obs[field] = None

                t["_missingness_metadata"] = {
                    "missingness_rate": missingness_rate,
                    "fields_nulled": fields_nulled,
                    "fields_available": fields_available,
                }

        return timelines
