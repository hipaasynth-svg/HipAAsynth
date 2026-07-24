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

"""Deterministic social-determinants-of-health (SDoH) derivation for CHW forms.

WHY THIS EXISTS (audit finding F3)
----------------------------------
The CHW ("community health worker") form previously hardcoded identical SDoH
lines for every patient ("The person has a home. They have a ride. They have
enough food."). With no patient-specific SDoH variation, the SDoH Amplification
Factor (SAF) metric had nothing to amplify and the "SDoH-rich" archetype carried
no signal.

This module derives a **per-patient, deterministic** SDoH profile so CHW notes
vary and SAF becomes meaningful. Derivation is anchor-consistent: it is a pure
SHA-256 function of the patient id (itself anchor-rooted), so it introduces no
new RNG and does not touch the generation pipeline's RNG stream. A population
profile may raise the adverse-SDoH base rates for a locale (rural / tribal /
uninsured), matching the engine's "marginal knob" philosophy.

Pure standard library. Zero PHI.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional

SDOH_ENGINE_VERSION = "sdoh_v1"

# National-ish base *adverse* rates (probability the SDoH factor is a barrier).
# These are deliberately coarse placeholders — real CHW intakes use validated
# tools (PRAPARE, AHC-HRSN). They exist to give SAF a varying signal, not to be
# an epidemiologic claim. A profile can override any of them per locale.
_BASE_ADVERSE_RATES: Dict[str, float] = {
    "housing_insecure": 0.18,
    "transport_barrier": 0.22,
    "food_insecure": 0.20,
    "uninsured": 0.12,
}

# Insurance category weights (used only for the reported label, not the burden
# score). Conditional on the uninsured draw above.
_INSURED_CATEGORIES = ("medicaid", "medicare", "commercial", "ihs_tribal")


def _unit_float(digest_hex: str, start: int) -> float:
    """Deterministic float in [0, 1) from two hex bytes of a digest."""
    byte_pair = digest_hex[start : start + 4]
    return int(byte_pair, 16) / 0x10000


def derive_sdoh(
    patient: Any,
    profile: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Return a deterministic per-patient SDoH profile.

    Deterministic in the patient id (anchor-rooted), so identical seed/profile/n
    yields identical SDoH. ``profile`` may carry an ``sdoh_adverse_rates`` mapping
    to raise/lower any base rate for a locale; the same deterministic draw is then
    compared against the locale rate, so a higher-burden locale produces more
    barriers without breaking determinism.

    Returns housing/transport/food/insurance status, a ``sdoh_burden_score``
    (count of adverse factors, 0-4), and provenance metadata.
    """
    overrides: Mapping[str, Any] = {}
    if profile and isinstance(profile.get("sdoh_adverse_rates"), Mapping):
        overrides = profile["sdoh_adverse_rates"]

    pid = str(patient.demographics.patient_id)
    digest = hashlib.sha256(f"{pid}:{SDOH_ENGINE_VERSION}:sdoh".encode()).hexdigest()

    def adverse(factor: str, offset: int) -> bool:
        rate = float(overrides.get(factor, _BASE_ADVERSE_RATES[factor]))
        return _unit_float(digest, offset) < rate

    housing_insecure = adverse("housing_insecure", 0)
    transport_barrier = adverse("transport_barrier", 4)
    food_insecure = adverse("food_insecure", 8)
    uninsured = adverse("uninsured", 12)

    if uninsured:
        insurance = "uninsured"
    else:
        idx = int(_unit_float(digest, 16) * len(_INSURED_CATEGORIES))
        insurance = _INSURED_CATEGORIES[min(idx, len(_INSURED_CATEGORIES) - 1)]

    burden = sum([housing_insecure, transport_barrier, food_insecure, uninsured])

    return {
        "housing_insecure": housing_insecure,
        "transport_barrier": transport_barrier,
        "food_insecure": food_insecure,
        "uninsured": uninsured,
        "insurance_status": insurance,
        "sdoh_burden_score": burden,
        "sdoh_engine_version": SDOH_ENGINE_VERSION,
    }


@dataclass(frozen=True)
class _SDoHLines:
    housing: str
    transport: str
    food: str
    insurance: str


def sdoh_narrative_lines(sdoh: Mapping[str, Any]) -> _SDoHLines:
    """Render plain-language CHW intake lines from an SDoH profile."""
    return _SDoHLines(
        housing=(
            "  The person does not have stable housing."
            if sdoh["housing_insecure"]
            else "  The person has stable housing."
        ),
        transport=(
            "  They do not have a reliable ride to care."
            if sdoh["transport_barrier"]
            else "  They have a reliable ride to care."
        ),
        food=(
            "  They do not always have enough food."
            if sdoh["food_insecure"]
            else "  They have enough food."
        ),
        insurance=f"  Insurance: {sdoh['insurance_status']}.",
    )
