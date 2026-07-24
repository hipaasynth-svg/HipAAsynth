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
HipAAsynth — Conditional Dependence Module
==========================================

Central home for **conditional dependence** between a primary condition's
severity/stage and its comorbidity cluster. This is the module referenced by
the architecture constraint "keep correlation logic in clearly named functions
or a dedicated dependence module."

WHY THIS EXISTS
---------------
The engine historically drew comorbidities with *independent* Bernoulli trials
(``rng.random() < marginal_rate``), optionally scaled by a single blanket
multiplier. That destroys joint fidelity: a GOLD 1 (mild) COPD patient and a
GOLD 4 (very severe) COPD patient carried the same pulmonary-hypertension
probability, which is clinically false. This module replaces those independent
draws with **severity-conditional rates** while keeping the published marginal
prevalence intact.

THE MODEL (marginal-preserving severity gradient)
-------------------------------------------------
For each comorbidity we keep the published national **marginal** ``m`` (BRFSS /
AHA / NHANES calibrated) and tilt it across the primary condition's severity
strata using a monotonic **gradient** of multipliers ``g = (g_1, ..., g_k)``.
The gradient is *normalized against the severity-stratum distribution* ``w`` so
that::

    sum_s w[s] * g_norm[s] == 1.0

Because the stratum-weighted mean of the multiplier is exactly 1.0, the
stratum-weighted mean of the resulting rate is exactly the marginal::

    sum_s w[s] * (m * g_norm[s]) == m * 1.0 == m

So marginal calibration is preserved **by construction** (see
``docs/CONDITIONAL_DEPENDENCE.md`` and ``tests/test_conditional_dependence.py``),
while the per-stratum rate ``m * g_norm[s]`` produces a real, directional
severity gradient. Trade-off policy: **preserve the marginal** — if a steep
gradient would push a stratum rate past ``_RATE_CAP`` the rate is clamped and
the (tiny) marginal drift is accepted; the current tables are tuned so no
clamping occurs (verified in tests).

GEOGRAPHIC / LOCALE TUNING (the "marginal knob")
------------------------------------------------
Marginals are the single authoritative knob a population profile sets per
locale (e.g. a rural IHS or tribal profile with elevated diabetes/COPD burden).
Every rate-building function accepts an optional ``marginal_overrides`` mapping;
when a locale profile supplies a different base marginal the **same normalized
gradient re-centers on it automatically**. The number a profile dials in is the
marginal the cohort reproduces — the dependence structure rides on top as a
separate, reusable layer. This is why the trade-off policy is "preserve the
marginal": it keeps the locale knob honest.

DETERMINISM CONTRACT
--------------------
This module never creates its own RNG. Callers pass the existing anchor-rooted,
namespaced ``random.Random`` instance. The ``draw_*`` helpers consume **exactly
one** ``rng.random()`` call per comorbidity, in a **fixed key order**, so the
RNG stream structure is identical to the independent-draw version it replaces —
only the comparison threshold changes. Swapping in this module does not shift
any downstream (labs / meds / functional) draw that uses a different namespaced
RNG.

Pure Python standard library. Zero PHI. Zero external dependencies.
"""

from __future__ import annotations

import random
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

# Probability cap — rates are clamped here to stay valid probabilities. Tuned so
# the current tables never actually hit it (verified in the joint tests), which
# is what keeps marginals *exactly* preserved.
_RATE_CAP = 0.97


# ─────────────────────────────────────────────────────────────────────────────
# Core gradient math
# ─────────────────────────────────────────────────────────────────────────────
def normalize_gradient(
    gradient: Sequence[float], stratum_weights: Sequence[float]
) -> Tuple[float, ...]:
    """Scale a monotonic multiplier ``gradient`` so its weighted mean under
    ``stratum_weights`` is exactly 1.0.

    This is the operation that makes the severity tilt marginal-preserving:
    after normalization, ``sum(w_s * g_s) == 1`` so ``sum(w_s * m * g_s) == m``.

    Both sequences must be the same length; weights need not pre-sum to 1
    (they are used only to compute the weighted mean of the gradient).
    """
    if len(gradient) != len(stratum_weights):
        raise ValueError("gradient and stratum_weights must have equal length")
    total_w = sum(stratum_weights)
    if total_w <= 0:
        raise ValueError("stratum_weights must sum to a positive value")
    weighted_mean = sum(g * w for g, w in zip(gradient, stratum_weights)) / total_w
    if weighted_mean <= 0:
        raise ValueError("gradient weighted mean must be positive")
    return tuple(g / weighted_mean for g in gradient)


def resolve_rates(
    marginal: float,
    gradient: Sequence[float],
    strata: Sequence[str],
    stratum_weights: Sequence[float],
    cap: float = _RATE_CAP,
) -> Dict[str, float]:
    """Return ``{stratum: rate}`` for one comorbidity.

    ``rate[s] = clamp(marginal * normalized_gradient[s], 0, cap)``. The
    normalized gradient guarantees the weight-averaged rate equals ``marginal``
    (pre-clamp). See module docstring.
    """
    norm = normalize_gradient(gradient, stratum_weights)
    return {
        stratum: round(min(cap, max(0.0, marginal * factor)), 6)
        for stratum, factor in zip(strata, norm)
    }


# ─────────────────────────────────────────────────────────────────────────────
# Named gradient shapes
# ─────────────────────────────────────────────────────────────────────────────
# Monotonic multiplier shapes, mildest→most-severe stratum. Interpreted per
# primary condition (COPD uses the 4-GOLD form; CHF uses the 4-NYHA form). The
# names describe how strongly a comorbidity tracks the primary condition's
# severity, grounded in the cited literature per assignment below. Raw shapes
# are normalized to the relevant stratum distribution at table-build time.
_GRADIENT_SHAPES_4: Dict[str, Tuple[float, float, float, float]] = {
    # weak severity dependence (roughly flat; common baseline conditions)
    "shallow": (0.85, 0.95, 1.08, 1.20),
    # moderate dependence (symptom-burden linked)
    "moderate": (0.70, 0.92, 1.14, 1.42),
    # strong dependence (organ-damage / disease-progression linked)
    "steep": (0.55, 0.85, 1.25, 1.70),
    # very strong dependence (pathophysiologically downstream of severity)
    "very_steep": (0.45, 0.80, 1.30, 1.90),
}

# CHF gradient shapes are given directly over NYHA I→IV. NYHA III is anchored at
# ~1.0 (it is the modal hospitalized class) so the shapes read intuitively.
_GRADIENT_SHAPES_NYHA: Dict[str, Tuple[float, float, float, float]] = {
    "shallow": (0.85, 0.92, 1.00, 1.10),
    "moderate": (0.70, 0.82, 1.00, 1.20),
    "steep": (0.55, 0.72, 1.00, 1.30),
    "very_steep": (0.40, 0.62, 1.00, 1.42),
}


# ─────────────────────────────────────────────────────────────────────────────
# COPD comorbidity dependence  (conditional on GOLD stage)
# ─────────────────────────────────────────────────────────────────────────────
# Severity strata and their prevalence in the diagnosed COPD population.
# Source: Buist AS et al. (BOLD Study) Lancet 2007;370(9589):741-750;
#         GOLD 2024 staging framework.
COPD_GOLD_STRATA: Tuple[str, ...] = ("GOLD_1", "GOLD_2", "GOLD_3", "GOLD_4")
COPD_GOLD_WEIGHTS: Tuple[float, ...] = (0.20, 0.38, 0.28, 0.14)

# (national marginal, gradient shape) per comorbidity. Marginals are the
# published COPD-population prevalences (unchanged from copd_generator's
# COMORBIDITY_RATES). Gradient assignment rationale + sources:
#   hypertension            0.55 shallow    — highly prevalent, weak GOLD gradient.
#   cardiovascular_disease  0.25 steep      — CV risk rises with airflow limitation.
#                                             Chen W et al. Lancet Respir Med 2015;3(8):631-639.
#   type2_diabetes          0.22 shallow    — metabolic comorbidity, weak GOLD link.
#                                             Mirrakhimov AE. Cardiovasc Diabetol 2012;11:132.
#   depression              0.27 moderate   — tracks dyspnea/symptom burden.
#                                             Yohannes AM et al. Respir Care 2014;59(7):1112-1120.
#   anxiety                 0.19 moderate   — tracks dyspnea/symptom burden. Yohannes 2014.
#   osa                     0.15 moderate   — overlap syndrome more common in advanced disease.
#                                             Shawon MS et al. Respir Med 2017;131:79-90.
#   pulmonary_hypertension  0.18 very_steep — strongly downstream of severe airflow
#                                             obstruction/hypoxemia; prevalence climbs sharply
#                                             GOLD 3-4. Chaouat A et al. Eur Respir J 2008;32(5):1371-1385.
#   osteoporosis            0.24 steep      — rises with steroid exposure, inactivity, low BMI
#                                             in severe COPD. Graat-Verboom L et al. Eur Respir J 2009;34:209-218.
#   lung_cancer_history     0.04 very_steep — shared smoking dose + emphysema severity.
#                                             de-Torres JP et al. Am J Respir Crit Care Med 2015;191(3):285-291.
COPD_COMORBIDITY_MODEL: Dict[str, Tuple[float, str]] = {
    "hypertension": (0.55, "shallow"),
    "cardiovascular_disease": (0.25, "steep"),
    "type2_diabetes": (0.22, "shallow"),
    "depression": (0.27, "moderate"),
    "anxiety": (0.19, "moderate"),
    "osa": (0.15, "moderate"),
    "pulmonary_hypertension": (0.18, "very_steep"),
    "osteoporosis": (0.24, "steep"),
    "lung_cancer_history": (0.04, "very_steep"),
}


# ─────────────────────────────────────────────────────────────────────────────
# CHF comorbidity dependence  (conditional on NYHA class)
# ─────────────────────────────────────────────────────────────────────────────
# Severity strata and their prevalence in the *hospitalized* HF population.
# Source: Fonarow GC et al. (OPTIMIZE-HF) JAMA 2007;297(1):61-70.
CHF_NYHA_STRATA: Tuple[str, ...] = ("I", "II", "III", "IV")
CHF_NYHA_WEIGHTS: Tuple[float, ...] = (0.03, 0.14, 0.54, 0.29)

# (national marginal, gradient shape) per comorbidity. Marginals are the
# published hospitalized-HF prevalences (unchanged from chf_generator's
# COMORBIDITY_RATES). Gradient assignment rationale + sources:
#   hypertension                 0.73 shallow  — near-universal, weak NYHA gradient.
#   type2_diabetes               0.45 shallow  — metabolic comorbidity, weak NYHA link.
#   ckd                          0.48 steep    — cardiorenal syndrome worsens with NYHA.
#                                                Ronco C et al. J Am Coll Cardiol 2008;52(19):1527-1539.
#   afib                         0.45 moderate — arrhythmia burden rises with class.
#                                                Dharmarajan K et al. JAMA 2013;309(4):355-363.
#   copd                         0.28 shallow  — coincident airway disease, weak NYHA link.
#   cad                          0.55 moderate — ischemic substrate more common in worse HF.
#   prior_mi                     0.32 moderate — prior infarction tracks ischemic severity.
#   prior_cabg_or_pci            0.28 shallow  — revascularization history, weak NYHA gradient.
#   anemia                       0.37 steep    — anemia of HF/CKD deepens with severity.
#                                                Groenveld HF et al. J Am Coll Cardiol 2008;52:818-827.
#   sleep_apnea                  0.24 moderate — SDB prevalence rises with HF severity.
#   depression                   0.22 moderate — tracks symptom burden/functional limitation.
#                                                Rutledge T et al. J Am Coll Cardiol 2006;48:1527-1537.
#   peripheral_vascular_disease  0.18 moderate — systemic atherosclerosis burden.
#   stroke_tia_history           0.14 moderate — thromboembolic risk rises with class/AF.
#   liver_disease                0.08 steep    — congestive hepatopathy in advanced HF.
#                                                Samsky MD et al. J Am Coll Cardiol 2013;61:2397-2405.
CHF_COMORBIDITY_MODEL: Dict[str, Tuple[float, str]] = {
    "hypertension": (0.73, "shallow"),
    "type2_diabetes": (0.45, "shallow"),
    "ckd": (0.48, "steep"),
    "afib": (0.45, "moderate"),
    "copd": (0.28, "shallow"),
    "cad": (0.55, "moderate"),
    "prior_mi": (0.32, "moderate"),
    "prior_cabg_or_pci": (0.28, "shallow"),
    "anemia": (0.37, "steep"),
    "sleep_apnea": (0.24, "moderate"),
    "depression": (0.22, "moderate"),
    "peripheral_vascular_disease": (0.18, "moderate"),
    "stroke_tia_history": (0.14, "moderate"),
    "liver_disease": (0.08, "steep"),
}


def _build_rate_table(
    model: Mapping[str, Tuple[float, str]],
    shapes: Mapping[str, Sequence[float]],
    strata: Sequence[str],
    weights: Sequence[float],
    marginal_overrides: Optional[Mapping[str, float]] = None,
) -> Dict[str, Dict[str, float]]:
    """Resolve a ``{comorbidity: {stratum: rate}}`` table from a model.

    ``marginal_overrides`` lets a locale/population profile replace the base
    marginal for any comorbidity; the normalized gradient re-centers on the new
    value automatically (the "marginal knob" described in the module docstring).
    Comorbidity insertion order is preserved so callers draw in a fixed order.
    """
    overrides = marginal_overrides or {}
    table: Dict[str, Dict[str, float]] = {}
    for comorbidity, (marginal, shape_name) in model.items():
        m = float(overrides.get(comorbidity, marginal))
        table[comorbidity] = resolve_rates(m, shapes[shape_name], strata, weights)
    return table


def copd_comorbidity_rate_table(
    marginal_overrides: Optional[Mapping[str, float]] = None,
) -> Dict[str, Dict[str, float]]:
    """``{comorbidity: {GOLD_stage: rate}}`` for COPD (see COPD_COMORBIDITY_MODEL)."""
    return _build_rate_table(
        COPD_COMORBIDITY_MODEL,
        _GRADIENT_SHAPES_4,
        COPD_GOLD_STRATA,
        COPD_GOLD_WEIGHTS,
        marginal_overrides,
    )


def chf_comorbidity_rate_table(
    marginal_overrides: Optional[Mapping[str, float]] = None,
) -> Dict[str, Dict[str, float]]:
    """``{comorbidity: {NYHA_class: rate}}`` for CHF (see CHF_COMORBIDITY_MODEL)."""
    return _build_rate_table(
        CHF_COMORBIDITY_MODEL,
        _GRADIENT_SHAPES_NYHA,
        CHF_NYHA_STRATA,
        CHF_NYHA_WEIGHTS,
        marginal_overrides,
    )


# Pre-resolved national tables (no profile overrides). Built once at import.
COPD_RATES_BY_GOLD: Dict[str, Dict[str, float]] = copd_comorbidity_rate_table()
CHF_RATES_BY_NYHA: Dict[str, Dict[str, float]] = chf_comorbidity_rate_table()


# ─────────────────────────────────────────────────────────────────────────────
# Draw helpers — one rng.random() per comorbidity, fixed order (determinism)
# ─────────────────────────────────────────────────────────────────────────────
def draw_copd_comorbidities(
    rng: random.Random,
    gold_stage: str,
    marginal_overrides: Optional[Mapping[str, float]] = None,
) -> Dict[str, bool]:
    """Draw the COPD comorbidity cluster conditional on ``gold_stage``.

    Consumes exactly one ``rng.random()`` per comorbidity, in the fixed order of
    ``COPD_COMORBIDITY_MODEL`` — identical RNG-stream structure to the
    independent-draw version it replaces, so determinism is unaffected. Only the
    comparison threshold (now GOLD-conditional) differs.
    """
    if gold_stage not in COPD_GOLD_STRATA:
        raise ValueError(f"unknown GOLD stage: {gold_stage!r}")
    table = (
        copd_comorbidity_rate_table(marginal_overrides)
        if marginal_overrides
        else COPD_RATES_BY_GOLD
    )
    return {
        comorbidity: rng.random() < stratum_rates[gold_stage]
        for comorbidity, stratum_rates in table.items()
    }


def draw_chf_comorbidities(
    rng: random.Random,
    nyha_class: str,
    hf_stage: Optional[str] = None,
    hf_phenotype: Optional[str] = None,
    marginal_overrides: Optional[Mapping[str, float]] = None,
) -> Dict[str, bool]:
    """Draw the CHF comorbidity cluster conditional on ``nyha_class``.

    ``hf_stage`` and ``hf_phenotype`` are accepted for forward compatibility and
    documentation of the intended conditioning axes; the current model conditions
    on NYHA class (the strongest, best-published severity axis for the
    hospitalized-HF comorbidity cluster). Consumes exactly one ``rng.random()``
    per comorbidity in the fixed order of ``CHF_COMORBIDITY_MODEL``.
    """
    if nyha_class not in CHF_NYHA_STRATA:
        raise ValueError(f"unknown NYHA class: {nyha_class!r}")
    table = (
        chf_comorbidity_rate_table(marginal_overrides) if marginal_overrides else CHF_RATES_BY_NYHA
    )
    return {
        comorbidity: rng.random() < stratum_rates[nyha_class]
        for comorbidity, stratum_rates in table.items()
    }


# ─────────────────────────────────────────────────────────────────────────────
# Stage 7 scaffold — LIFE OUTCOMES (relationship / employment / income)
# ─────────────────────────────────────────────────────────────────────────────
# Per the sequential generation order, life-outcome variables are the FINAL
# stage, drawn conditionally on functional status + conditions + age +
# demographics. This scaffold establishes the structure and the conditioning
# signature so the stage can be calibrated and wired into the record later.
#
# STATUS: PROVISIONAL — the directional logic below is clinically plausible but
# is NOT yet calibrated to a published target (unlike the comorbidity marginals
# above). It is intentionally NOT part of the default Patient record, so it does
# not affect existing outputs, determinism of shipped cohorts, or the
# FairnessPassport. It is deterministic given its rng + inputs and is exercised
# by the dependence tests to lock the structure in place.
LIFE_OUTCOME_FIELDS: Tuple[str, ...] = (
    "relationship_stability",
    "employment_status",
    "income_band",
)


def draw_life_outcomes(
    rng: random.Random,
    *,
    functional_status: float,
    condition_count: int,
    age: int,
    sex: str,
    marginal_overrides: Optional[Mapping[str, float]] = None,
) -> Dict[str, Any]:
    """PROVISIONAL stage-7 hook: draw life-outcome variables conditional on
    functional status, condition burden, age, and demographics.

    ``functional_status`` is a 0.0 (fully impaired) → 1.0 (fully functional)
    score the caller derives from the disability/functional stage. Higher
    impairment and higher condition burden shift outcomes toward instability,
    unemployment/disability, and lower income bands — the documented direction
    this scaffold guarantees. Consumes exactly three ``rng.random()`` draws in a
    fixed order. Not calibrated to a published marginal yet (see module notes).
    """
    fs = max(0.0, min(1.0, float(functional_status)))
    burden = max(0.0, min(1.0, condition_count / 8.0))
    # Working-age vs retirement shifts the employment axis.
    working_age = 18 <= age < 65

    # 1) Relationship stability: impairment + burden erode stability.
    stable_p = max(0.05, min(0.95, 0.72 * fs - 0.15 * burden + 0.10))
    relationship_stability = "stable" if rng.random() < stable_p else "unstable"

    # 2) Employment status: gated by working age, then by function/burden.
    emp_roll = rng.random()
    if not working_age:
        employment_status = "retired" if age >= 65 else "not_in_labor_force"
    else:
        disabled_p = max(0.02, min(0.85, 0.55 * (1.0 - fs) + 0.20 * burden))
        employed_p = max(0.05, min(0.95, 0.85 * fs - 0.10 * burden))
        if emp_roll < disabled_p:
            employment_status = "disabled"
        elif emp_roll < disabled_p + employed_p:
            employment_status = "employed"
        else:
            employment_status = "unemployed"

    # 3) Income band: driven by employment + function; monotone ladder.
    income_roll = rng.random()
    ladder = ("low", "low_middle", "middle", "upper_middle", "high")
    lift = 0.55 * fs + (0.25 if employment_status == "employed" else 0.0) - 0.15 * burden
    idx = int(
        round(max(0.0, min(1.0, 0.15 + lift + 0.20 * (income_roll - 0.5))) * (len(ladder) - 1))
    )
    income_band = ladder[max(0, min(len(ladder) - 1, idx))]

    return {
        "relationship_stability": relationship_stability,
        "employment_status": employment_status,
        "income_band": income_band,
        "life_outcome_stage_status": "provisional_uncalibrated",
    }
