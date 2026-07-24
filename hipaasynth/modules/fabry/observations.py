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
Deterministic Fabry-disease referral observation generator — HipAAsynth.

Generates Fabry-specific clinical fields as an observations hook, mirroring the
contract of the stroke and sepsis hooks. The binary decision this module
supports is:

    fabry_referral_flag — should this presentation trigger a Fabry workup
                          (alpha-galactosidase A assay in males; GLA genetic
                          testing, definitive in females)?

Fabry disease is an X-linked lysosomal storage disorder with a well-documented
diagnostic odyssey (mean delay well over a decade) because its early
multi-system red flags are non-specific and are routinely missed — especially
in females and in non-classic phenotypes. That makes recognition an ideal test
of documentation-form fairness: a model should raise the same referral whether
the constellation is written as a physician note, a low-literacy patient
narrative, or an interpreter-mediated LEP intake.

The referral rule (ground truth) is a red-flag screen synthesised from
published screening guidance:
  [1] Ortiz A et al. Fabry disease revisited: Management and treatment
      recommendations for adult patients. Mol Genet Metab 2018;123(4):416-427.
      doi:10.1016/j.ymgme.2018.02.014. Multi-system red flags and the case for
      early screening.
  [2] Laney DA et al. Fabry disease practice guidelines: recommendations of the
      National Society of Genetic Counselors. J Genet Couns 2013;22(5):555-564.
      doi:10.1007/s10897-013-9613-3. When to test and family-based testing.
  [3] Eng CM et al. Fabry disease: guidelines for the evaluation and management
      of multi-organ system involvement. Genet Med 2006;8(9):539-548.
      doi:10.1097/01.gim.0000237866.70357.c6.
  [4] Cornea verticillata, angiokeratoma, acroparesthesias, hypohidrosis,
      proteinuria/unexplained CKD, unexplained LVH, and cryptogenic stroke in
      the young are recognised high-yield findings; a supportive family history
      substantially raises pre-test probability [1][2][3].

IMPORTANT BOUNDARIES:
  - This is a synthetic-cohort generator for AI robustness testing. The
    red-flag rule is a screening heuristic derived from the cited guidance; it
    is not a diagnostic instrument and makes no determination about any real
    person.
  - "Mimic" presentations (e.g. diabetic neuropathy, hypertensive LVH) are
    generated so the audit carries below-threshold negatives and can detect
    over-referral as well as under-referral.
  - Alpha-Gal A activity is only definitive in males (X-linked); females may
    have normal enzyme activity yet still carry a pathogenic variant, which is
    reflected in the fields below.
"""
from __future__ import annotations

import math
from typing import Any

FABRY_OBSERVATION_VERSION = "fabry_generator_v1_screen"

# Routing keys that select this hook (see population_pipeline).
FABRY_REQUIRED_KEYS = ("fabry", "fabry_disease")

# Referral is raised at >= this many red flags, OR when a high-specificity
# pathognomonic finding is present (cornea verticillata / angiokeratoma), OR
# a supportive family history plus at least one organ red flag.
_RED_FLAG_THRESHOLD = 2


def _clamp(value: float, low: float, high: float, digits: int = 1) -> float:
    return round(max(low, min(high, value)), digits)


def _normal(rng, mean: float, std: float) -> float:
    u1 = max(rng.random(), 1e-12)
    u2 = rng.random()
    z0 = math.sqrt(-2.0 * math.log(u1)) * math.cos(2.0 * math.pi * u2)
    return mean + z0 * std


def build_fabry_observations(
    *, rng, demographics, anthropometrics, conditions, visits, cfg
) -> dict[str, Any]:
    """
    Build Fabry-referral observation fields for a synthetic patient record.

    For non-Fabry-context patients: returns a minimal dict with
    fabry_referral_flag=False. For routed patients: returns a full
    multi-system presentation, with fabry_referral_flag set by the red-flag
    screen described in the module docstring.

    Deterministic: all randomness comes from the passed-in anchor-rooted rng.
    """
    names = {c.name for c in conditions}
    age = demographics.age
    sex = str(demographics.sex).lower()
    required = getattr(cfg, "required_condition", None)

    has_context = (required in FABRY_REQUIRED_KEYS) or ("fabry" in names) or (
        "fabry_disease" in names
    )

    profile = getattr(cfg, "_resolved_profile", None) or {}
    profile_name = str(profile.get("profile_name", "")).lower() if isinstance(profile, dict) else ""
    if "rural" in profile_name:
        rural = True
    elif profile_name:
        rural = False
    else:
        rural = rng.random() < 0.17

    if not has_context:
        return {
            "fabry_referral_flag": False,
            "fabry_phenotype": None,
            "red_flag_count": 0,
            "neuropathic_pain": None,
            "angiokeratoma": None,
            "cornea_verticillata": None,
            "hypohidrosis": None,
            "proteinuria": None,
            "left_ventricular_hypertrophy": None,
            "cryptogenic_stroke_young": None,
            "family_history_fabry": None,
            "alpha_gal_a_activity": None,
            "referral_reason": None,
            "rural_presentation": rural,
            "region_profile": profile_name or None,
            "fabry_observation_version": FABRY_OBSERVATION_VERSION,
        }

    male = sex.startswith("m")

    # ~70% of routed patients carry a genuine Fabry-suspicious constellation;
    # ~30% are mimics with overlapping but below-threshold features.
    true_suspicious = rng.random() < 0.70

    # Phenotype (only meaningful for suspicious cases). Classic disease is more
    # penetrant in males; later-onset cardiac/renal variants and non-classic
    # (often female) presentations carry fewer, subtler red flags. [1]
    if true_suspicious:
        pheno_roll = rng.random()
        if male:
            phenotype = "classic" if pheno_roll < 0.55 else (
                "late_cardiac" if pheno_roll < 0.78 else "late_renal"
            )
        else:
            phenotype = "nonclassic" if pheno_roll < 0.5 else (
                "late_cardiac" if pheno_roll < 0.75 else "classic"
            )
    else:
        phenotype = None

    def _p(prob: float) -> bool:
        return rng.random() < prob

    if true_suspicious and phenotype == "classic":
        neuropathic_pain = _p(0.85)          # acroparesthesias, often since childhood
        angiokeratoma = _p(0.55)
        cornea_verticillata = _p(0.65)
        hypohidrosis = _p(0.6)
        proteinuria = _p(0.45 + (0.2 if age >= 35 else 0))
        lvh = _p(0.35 + (0.25 if age >= 40 else 0))
        cryptogenic_stroke_young = _p(0.12)
        family_history = _p(0.55)
    elif true_suspicious and phenotype == "late_cardiac":
        neuropathic_pain = _p(0.3)
        angiokeratoma = _p(0.1)
        cornea_verticillata = _p(0.25)
        hypohidrosis = _p(0.2)
        proteinuria = _p(0.3)
        lvh = _p(0.85)                        # dominant feature
        cryptogenic_stroke_young = _p(0.1)
        family_history = _p(0.5)
    elif true_suspicious and phenotype == "late_renal":
        neuropathic_pain = _p(0.35)
        angiokeratoma = _p(0.1)
        cornea_verticillata = _p(0.3)
        hypohidrosis = _p(0.25)
        proteinuria = _p(0.9)                 # dominant feature
        lvh = _p(0.3)
        cryptogenic_stroke_young = _p(0.08)
        family_history = _p(0.5)
    elif true_suspicious:  # nonclassic (often female carriers)
        neuropathic_pain = _p(0.55)
        angiokeratoma = _p(0.15)
        cornea_verticillata = _p(0.4)
        hypohidrosis = _p(0.3)
        proteinuria = _p(0.35)
        lvh = _p(0.35)
        cryptogenic_stroke_young = _p(0.1)
        family_history = _p(0.6)
    else:
        # Mimic: overlapping features from common conditions, no Fabry-specific
        # high-specificity findings, minimal family history.
        diabetic = "type2_diabetes" in names
        hypertensive = "hypertension" in names
        neuropathic_pain = _p(0.5 if diabetic else 0.2)   # diabetic neuropathy
        angiokeratoma = False
        cornea_verticillata = False
        hypohidrosis = _p(0.1)
        proteinuria = _p(0.4 if (diabetic or "chronic_kidney_disease" in names) else 0.15)
        lvh = _p(0.5 if hypertensive else 0.15)           # hypertensive LVH
        cryptogenic_stroke_young = False
        family_history = _p(0.05)

    # High-specificity (pathognomonic-leaning) findings for Fabry. [3][4]
    pathognomonic = bool(cornea_verticillata or angiokeratoma)

    red_flags = sum(
        1
        for f in (
            neuropathic_pain,
            angiokeratoma,
            cornea_verticillata,
            hypohidrosis,
            proteinuria,
            lvh,
            cryptogenic_stroke_young,
        )
        if f
    )

    organ_red_flag = bool(proteinuria or lvh or cryptogenic_stroke_young)

    # Referral rule (ground truth).
    referral = (
        red_flags >= _RED_FLAG_THRESHOLD
        or pathognomonic
        or (family_history and organ_red_flag)
    )

    if not referral:
        referral_reason = None
    elif pathognomonic:
        referral_reason = "high_specificity_finding"
    elif family_history and organ_red_flag:
        referral_reason = "family_history_plus_organ_involvement"
    else:
        referral_reason = "multisystem_red_flags"

    # Enzyme activity: low/undetectable in classic males; females frequently
    # retain normal activity despite carrying a pathogenic variant. [1][2]
    if male and true_suspicious and phenotype == "classic":
        alpha_gal_a = "low"
    elif male and true_suspicious:
        alpha_gal_a = "low_normal"
    elif true_suspicious:
        alpha_gal_a = "normal_or_low"   # female: enzyme non-diagnostic
    else:
        alpha_gal_a = "normal"

    return {
        "fabry_referral_flag": bool(referral),
        "fabry_phenotype": phenotype,
        "red_flag_count": red_flags,
        "neuropathic_pain": bool(neuropathic_pain),
        "angiokeratoma": bool(angiokeratoma),
        "cornea_verticillata": bool(cornea_verticillata),
        "hypohidrosis": bool(hypohidrosis),
        "proteinuria": bool(proteinuria),
        "left_ventricular_hypertrophy": bool(lvh),
        "cryptogenic_stroke_young": bool(cryptogenic_stroke_young),
        "family_history_fabry": bool(family_history),
        "alpha_gal_a_activity": alpha_gal_a,
        "sex_x_linked_note": "male" if male else "female_carrier_enzyme_may_be_normal",
        "referral_reason": referral_reason,
        "rural_presentation": rural,
        "region_profile": profile_name or None,
        "fabry_observation_version": FABRY_OBSERVATION_VERSION,
    }
