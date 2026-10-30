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
adversarial/temporal.py
────────────────────────
Longitudinal patient timeline generation + post-training temporal drift.

GAP 2 FIX (6AAST Axis 3):
  TemporalEngine now accepts drift_months ∈ {None, 6, 12, 18} representing
  discrete post-training intervals.  apply_drift() shifts disease prevalence,
  prescription patterns, and demographic composition incrementally per
  calibrated federal trend data, replacing the previous binary on/off flag.
"""

import json
import os
import random

from hipaasynth.adversarial.run_context_shim import RunContext
from hipaasynth.core.hashing import stable_seed_from_id
from hipaasynth.pipelines.run_pipeline import run_pipeline


_VALID_DRIFT_MONTHS = (None, 6, 12, 18)
_MAX_DRIFT_MONTHS = 18

# Default trend magnitudes used when a profile does not define temporal_trends.
# Calibrated to CDC BRFSS / CMS Part D / US Census 2024 national trend rates,
# scaled to the 18-month maximum.
_DEFAULT_TRENDS: dict = {
    "disease_prevalence_shift": {
        "diabetes": 0.010,
        "hypertension": 0.013,
        "ckd": 0.007,
    },
    "prescription_shift": {
        "antibiotics": -0.067,
        "statins": 0.050,
        "ace_inhibitors": 0.033,
    },
    "demographic_shift": {
        "age_65_plus_fraction_delta": 0.013,
        "comorbidity_index_delta": 0.017,
    },
    "source": "default (CDC BRFSS / CMS Part D / US Census 2024 national)",
}


def _load_trend_data(profile_path: str | None, drift_months: int) -> dict:
    """
    Load federal trend data for the given drift interval from the profile JSON.

    Falls back to _DEFAULT_TRENDS scaled by shift_fraction when the profile
    does not define temporal_trends.
    """
    shift_fraction = drift_months / _MAX_DRIFT_MONTHS

    if profile_path and os.path.isfile(profile_path):
        try:
            with open(profile_path) as f:
                profile = json.load(f)
            trends = profile.get("temporal_trends", {})
            entry = trends.get(str(drift_months))
            if isinstance(entry, dict):
                return entry
        except (json.JSONDecodeError, OSError):
            pass

    # Fallback: scale defaults to the requested interval
    return {
        "disease_prevalence_shift": {
            k: round(v * shift_fraction, 6)
            for k, v in _DEFAULT_TRENDS["disease_prevalence_shift"].items()
        },
        "prescription_shift": {
            k: round(v * shift_fraction, 6)
            for k, v in _DEFAULT_TRENDS["prescription_shift"].items()
        },
        "demographic_shift": {
            k: round(v * shift_fraction, 6) for k, v in _DEFAULT_TRENDS["demographic_shift"].items()
        },
        "source": _DEFAULT_TRENDS["source"],
    }


class TemporalEngine:
    """
    Longitudinal patient timeline generator + post-training drift applier.

    Generation
    ──────────
    Each year-slice uses seed + year_index so slices are distinct but
    reproducible. Condition and profile are forwarded to the adapter
    so the engine generates the right patient type.

    Post-training drift (apply_drift)
    ─────────────────────────────────
    drift_months ∈ {None, 6, 12, 18} — discrete post-training intervals.
      • None  → no drift (baseline)
      • 6     → 1/3 of 18-month total shift
      • 12    → 2/3 of 18-month total shift
      • 18    → full shift

    Shifts applied incrementally per calibrated federal trend data:
      • Disease prevalence (CDC BRFSS / IDF Atlas / WHO regional)
      • Prescription patterns (CMS Part D utilization trends)
      • Demographic composition (US Census / UN Population Prospects)

    All shifts are deterministic — identical across runs with the same seed.
    """

    def __init__(self, seed=None, years=None, condition=None, profile=None, drift_months=None):
        if drift_months not in _VALID_DRIFT_MONTHS:
            raise ValueError(
                f"drift_months must be one of {_VALID_DRIFT_MONTHS}; " f"got {drift_months!r}"
            )
        self.seed = seed
        self.years = years
        self.condition = condition
        self.profile = profile
        self.drift_months = drift_months

    def generate(self, config=None):
        if self.years is None:
            raise ValueError("TemporalEngine.generate() requires 'years' set " "in __init__")

        timelines = {}

        for year in range(self.years):
            ctx = RunContext(
                seed=self.seed + year,
                metadata={
                    "year": year,
                    "required_condition": self.condition,
                    "profile_path": self.profile,
                },
            )
            data = run_pipeline(config=config, context=ctx)

            for row in data:
                pid = row["patient_id"]
                if pid not in timelines:
                    timelines[pid] = {"patient_id": pid, "timeline": []}
                row["_meta"] = {"year": year}
                timelines[pid]["timeline"].append(row)

        return list(timelines.values())

    def apply_drift(self, timelines, profile_path: str | None = None):
        """
        Apply incremental post-training temporal drift to existing timelines.

        Returns timelines (modified in place) with each timeline entry annotated
        with a '_drift_metadata' dict capturing drift_months, shift_fraction,
        trend source, and applied magnitudes.

        When self.drift_months is None this is a no-op and an explicit
        'no drift' metadata block is logged for audit completeness.
        """
        # Resolve profile path: prefer explicit argument, fall back to instance,
        # then to first timeline's metadata (mirrors PerturbationEngine).
        if profile_path is None:
            profile_path = self.profile
        if profile_path is None and timelines:
            first_meta = (
                timelines[0]["timeline"][0].get("_meta", {}) if timelines[0]["timeline"] else {}
            )
            profile_path = first_meta.get("profile_path")

        if self.drift_months is None:
            for p in timelines:
                for t in p["timeline"]:
                    t["_drift_metadata"] = {
                        "drift_months": None,
                        "shift_fraction": 0.0,
                        "trend_source": None,
                        "profile_path": profile_path,
                    }
            return timelines

        shift_fraction = self.drift_months / _MAX_DRIFT_MONTHS
        trend_data = _load_trend_data(profile_path, self.drift_months)

        prev_shift = trend_data.get("disease_prevalence_shift", {})
        rx_shift = trend_data.get("prescription_shift", {})
        demo_shift = trend_data.get("demographic_shift", {})
        trend_src = trend_data.get("source", "unknown")

        dm_p = float(prev_shift.get("diabetes", 0.0))
        htn_p = float(prev_shift.get("hypertension", 0.0))
        ckd_p = float(prev_shift.get("ckd", 0.0))
        abx_r = float(rx_shift.get("antibiotics", 0.0))
        statin_r = float(rx_shift.get("statins", 0.0))
        ace_r = float(rx_shift.get("ace_inhibitors", 0.0))
        age_d = float(demo_shift.get("age_65_plus_fraction_delta", 0.0))
        com_d = float(demo_shift.get("comorbidity_index_delta", 0.0))

        for p in timelines:
            # Stable cross-process seed namespaced per drift interval.
            # Salt = 0xD7117 * drift_months guarantees that 6/12/18-month
            # drifts apply different but reproducible perturbations to the
            # same patient across separate interpreter runs.
            rng = random.Random(
                stable_seed_from_id(p["patient_id"], salt=0xD7117 * self.drift_months)
            )

            for t in p["timeline"]:
                # Disease prevalence shift — flip a small fraction of patients
                # toward higher comorbidity load.
                if rng.random() < (dm_p + htn_p + ckd_p):
                    if "comorbidities" in t and isinstance(t["comorbidities"], (int, float)):
                        t["comorbidities"] += 1

                # Prescription pattern shift — adjust treatment field to reflect
                # net prescribing direction.
                if "treatment" in t and isinstance(t["treatment"], (int, float)):
                    rx_net = statin_r + ace_r + abx_r
                    if rng.random() < abs(rx_net):
                        t["treatment"] = 1 if rx_net > 0 else 0

                # Demographic composition shift — small age increment for the
                # subset of patients drifting into the 65+ band.
                if "age" in t and isinstance(t["age"], (int, float)):
                    if rng.random() < age_d:
                        t["age"] = min(90, t["age"] + 1)

                # Patient-dict observation-level shifts (when present)
                patient_dict = t.get("_patient_dict")
                if patient_dict is not None:
                    obs = patient_dict.get("observations", {})
                    if rng.random() < com_d and "comorbidity_count" in obs:
                        if isinstance(obs["comorbidity_count"], (int, float)):
                            obs["comorbidity_count"] += 1

                t["_drift_metadata"] = {
                    "drift_months": self.drift_months,
                    "shift_fraction": round(shift_fraction, 4),
                    "trend_source": trend_src,
                    "profile_path": profile_path,
                    "applied_shifts": {
                        "disease_prevalence_shift": prev_shift,
                        "prescription_shift": rx_shift,
                        "demographic_shift": demo_shift,
                    },
                }

        return timelines
