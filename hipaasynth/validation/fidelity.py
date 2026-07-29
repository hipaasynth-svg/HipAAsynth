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

"""Statistical-fidelity checks for a generated cohort (Tier 4, step 1).

Where :func:`hipaasynth.exporters.profile_fit_stats` answers *"does the cohort's
demographic mix match a configured population profile?"* (and only runs when a
profile is set, and only for sex / ethnicity / age bands), this module answers a
complementary, profile-free question: **is the generated data internally
faithful to the engine's own generative model?**

It checks three things, using pure standard library (no numpy/scipy/pandas):

1. **Marginal distributions** — summary statistics for every generated lab
   analyte (Glucose, Creatinine, LDL, WBC, …) and prevalence for every generated
   condition. These are the marginals ``profile_fit_stats`` never looks at.

2. **Pairwise correlations between clinically-linked variables.** The engine's
   generation logic (:mod:`hipaasynth.pipelines.generator_numerics`,
   ``CONDITION_LAB_MODIFIERS``) deliberately couples certain diagnoses to certain
   labs — a diabetic's Glucose, a CKD patient's Creatinine, a hyperlipidemia
   patient's LDL, a sepsis patient's WBC are each drawn as ``max(baseline,
   elevated_draw)``. A faithful cohort must therefore show a *positive*
   association between carrying the diagnosis and the coupled lab value. This
   module measures that association (mean shift + point-biserial correlation) so
   a regression that silently breaks the coupling is caught.

3. **Temporal consistency.** Every condition's ``onset_age`` must be ≤ the
   patient's age; every measurement date must fall inside the patient's
   observation-period span (earliest…latest visit); the span itself must be
   well-ordered. (The engine does **not** chronologically order visits within a
   patient — see ``visit_order_report`` — so visit ordering is *reported* as an
   informational statistic, not asserted as a violation.)

Data access reuses :func:`hipaasynth.exporters.omop.build_cdm_tables` and
:func:`hipaasynth.exporters.exporters._flat_patient_rows`, so this module sees
exactly the rows an OMOP / flat-table consumer would, with no separate traversal
of the patient graph to drift out of sync.

Nothing here raises on a "bad" cohort: it *reports*. Callers (tests, CLI, audit)
decide what to do with the findings. The one exception is genuinely malformed
input (e.g. a non-``Patient``), which fails loud.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from hipaasynth.exporters.exporters import _flat_patient_rows
from hipaasynth.exporters.omop import build_cdm_tables


# ─────────────────────────────────────────────────────────────────────────────
# Clinically-linked (condition, lab) couplings the engine encodes.
#
# Mirrors ``CONDITION_LAB_MODIFIERS`` in generator_numerics: each listed
# condition draws the coupled lab as ``max(baseline, elevated_draw)``, so the
# association is expected POSITIVE (carrying the condition raises the lab). The
# ``floor`` is the value below which the engine can never place the lab *for a
# patient carrying that condition* — a hard invariant used by the validator's
# lab-vs-diagnosis rule; recorded here so both live next to the coupling they
# describe. Source citations are in generator_numerics ([N4]–[N7]).
# ─────────────────────────────────────────────────────────────────────────────
LINKED_LAB_PAIRS: List[Dict[str, Any]] = [
    {"condition": "type2_diabetes", "lab": "Glucose", "direction": "higher", "floor": None},
    {"condition": "chronic_kidney_disease", "lab": "Creatinine", "direction": "higher", "floor": 1.05},
    {"condition": "hyperlipidemia", "lab": "LDL", "direction": "higher", "floor": 160.0},
    {"condition": "sepsis", "lab": "WBC", "direction": "higher", "floor": 11.0},
]


# ─────────────────────────────────────────────────────────────────────────────
# Small, self-contained statistics (hand-rolled — stdlib only).
# ─────────────────────────────────────────────────────────────────────────────
def _mean(xs: Sequence[float]) -> float:
    return sum(xs) / len(xs)


def _variance(xs: Sequence[float]) -> float:
    """Population variance (÷n). Zero for a constant or single-element sequence."""
    if len(xs) < 2:
        return 0.0
    mu = _mean(xs)
    return sum((x - mu) ** 2 for x in xs) / len(xs)


def _quantile(sorted_xs: Sequence[float], q: float) -> float:
    """Linear-interpolation quantile of an already-sorted sequence."""
    if not sorted_xs:
        raise ValueError("quantile of empty sequence")
    if len(sorted_xs) == 1:
        return float(sorted_xs[0])
    pos = q * (len(sorted_xs) - 1)
    lo = math.floor(pos)
    hi = math.ceil(pos)
    if lo == hi:
        return float(sorted_xs[lo])
    frac = pos - lo
    return sorted_xs[lo] * (1 - frac) + sorted_xs[hi] * frac


def pearson_correlation(xs: Sequence[float], ys: Sequence[float]) -> Optional[float]:
    """Pearson product-moment correlation of two equal-length numeric sequences.

    Returns a value in [-1, 1], or ``None`` when it is undefined — either fewer
    than two paired points, or one of the variables has zero variance (a
    constant), for which correlation is not defined. Clamps tiny floating-point
    overshoots to the [-1, 1] range.
    """
    if len(xs) != len(ys):
        raise ValueError("pearson_correlation requires equal-length sequences")
    n = len(xs)
    if n < 2:
        return None
    mx, my = _mean(xs), _mean(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx == 0.0 or syy == 0.0:
        return None
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    r = sxy / math.sqrt(sxx * syy)
    return max(-1.0, min(1.0, r))


def _summary(values: Sequence[float]) -> Dict[str, float]:
    """Distribution summary for a numeric marginal."""
    xs = sorted(float(v) for v in values)
    return {
        "n": len(xs),
        "mean": round(_mean(xs), 4),
        "std": round(math.sqrt(_variance(xs)), 4),
        "min": round(xs[0], 4),
        "p25": round(_quantile(xs, 0.25), 4),
        "median": round(_quantile(xs, 0.50), 4),
        "p75": round(_quantile(xs, 0.75), 4),
        "max": round(xs[-1], 4),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Marginal distributions.
# ─────────────────────────────────────────────────────────────────────────────
def lab_value_marginals(patients: Sequence[Any]) -> Dict[str, Dict[str, float]]:
    """Per-analyte summary statistics over every generated measurement.

    Reads the OMOP ``measurement`` rows (``build_cdm_tables``) so the analyte set
    and values are exactly what an OMOP consumer would load. Analytes with no
    numeric value are skipped.
    """
    tables = build_cdm_tables(list(patients))
    by_analyte: Dict[str, List[float]] = {}
    for row in tables["measurement"]:
        name = row["measurement_source_value"]
        value = row["value_as_number"]
        if value is None or value == "":
            continue
        by_analyte.setdefault(name, []).append(float(value))
    return {name: _summary(vals) for name, vals in sorted(by_analyte.items()) if vals}


def condition_prevalence(patients: Sequence[Any]) -> Dict[str, Dict[str, float]]:
    """Prevalence (count and fraction of patients) for every generated condition."""
    patients = list(patients)
    total = len(patients)
    counts: Dict[str, int] = {}
    for p in patients:
        # A patient can carry a condition at most once (validator dedups), so a
        # set guards against any accidental double-count.
        for name in {c.name for c in p.conditions}:
            counts[name] = counts.get(name, 0) + 1
    return {
        name: {"count": counts[name], "prevalence": round(counts[name] / total, 4) if total else 0.0}
        for name in sorted(counts)
    }


# ─────────────────────────────────────────────────────────────────────────────
# Pairwise correlation between clinically-linked variables.
# ─────────────────────────────────────────────────────────────────────────────
def _patient_mean_lab(patient: Any, lab_name: str) -> Optional[float]:
    """Mean of one analyte's values across all of a patient's visits, or None."""
    vals = [lab.value for v in patient.visits for lab in v.labs if lab.lab_name == lab_name]
    return _mean(vals) if vals else None


@dataclass(frozen=True)
class LinkedCorrelation:
    """Association between carrying a diagnosis and its clinically-coupled lab."""

    condition: str
    lab: str
    expected_direction: str          # "higher" — the engine raises the lab
    n_with: int                      # patients carrying the condition (with the lab)
    n_without: int
    mean_with: Optional[float]
    mean_without: Optional[float]
    mean_shift: Optional[float]      # mean_with - mean_without
    point_biserial: Optional[float]  # corr(has_condition, patient-mean lab)
    direction_ok: Optional[bool]     # None when not evaluable (a group is empty)


def linked_lab_correlations(patients: Sequence[Any]) -> List[LinkedCorrelation]:
    """Measure the diagnosis→lab association for every coupling in LINKED_LAB_PAIRS.

    For each ``(condition, lab)`` pair, every patient who has *at least one*
    measurement of that lab contributes a point: ``x = 1`` if they carry the
    condition else ``0``; ``y`` = their mean value for that lab. We report the
    mean lab value with vs. without the diagnosis, the shift, and the
    point-biserial correlation (Pearson between the 0/1 group indicator and the
    lab). ``direction_ok`` is True when the observed shift matches the engine's
    expected direction. It is ``None`` (not False) when a group is empty and the
    association can't be evaluated — e.g. no sepsis patients in a default cohort.
    """
    patients = list(patients)
    out: List[LinkedCorrelation] = []
    for pair in LINKED_LAB_PAIRS:
        cond, lab, direction = pair["condition"], pair["lab"], pair["direction"]
        xs: List[float] = []
        ys: List[float] = []
        with_vals: List[float] = []
        without_vals: List[float] = []
        for p in patients:
            mean_lab = _patient_mean_lab(p, lab)
            if mean_lab is None:
                continue
            has = any(c.name == cond for c in p.conditions)
            xs.append(1.0 if has else 0.0)
            ys.append(mean_lab)
            (with_vals if has else without_vals).append(mean_lab)

        mean_with = round(_mean(with_vals), 4) if with_vals else None
        mean_without = round(_mean(without_vals), 4) if without_vals else None
        shift = (
            round(mean_with - mean_without, 4)
            if mean_with is not None and mean_without is not None
            else None
        )
        if shift is None:
            direction_ok: Optional[bool] = None
        elif direction == "higher":
            direction_ok = shift >= 0.0
        else:
            direction_ok = shift <= 0.0
        out.append(
            LinkedCorrelation(
                condition=cond,
                lab=lab,
                expected_direction=direction,
                n_with=len(with_vals),
                n_without=len(without_vals),
                mean_with=mean_with,
                mean_without=mean_without,
                mean_shift=shift,
                point_biserial=pearson_correlation(xs, ys),
                direction_ok=direction_ok,
            )
        )
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Temporal consistency.
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class TemporalConsistencyReport:
    """Findings from the temporal-consistency checks. ``ok`` iff no violations."""

    onset_after_age: List[Dict[str, Any]] = field(default_factory=list)
    measurement_outside_span: List[Dict[str, Any]] = field(default_factory=list)
    inverted_observation_period: List[Dict[str, Any]] = field(default_factory=list)
    n_patients: int = 0
    n_conditions_checked: int = 0
    n_measurements_checked: int = 0

    @property
    def violations(self) -> int:
        return (
            len(self.onset_after_age)
            + len(self.measurement_outside_span)
            + len(self.inverted_observation_period)
        )

    @property
    def ok(self) -> bool:
        return self.violations == 0


def temporal_consistency(patients: Sequence[Any]) -> TemporalConsistencyReport:
    """Check the temporal invariants the engine guarantees.

    Hard invariants (a violation is a real defect):
      * every ``condition.onset_age <= patient.age``;
      * every measurement date lies within the person's observation-period span
        (earliest…latest visit date), read from ``build_cdm_tables``;
      * ``observation_period_start_date <= observation_period_end_date``.

    Visit *ordering* is intentionally not asserted — see
    :func:`visit_order_report` — because the generator draws each visit date
    independently and does not sort them, so unordered visits are a modeling
    choice, not a data defect.
    """
    patients = list(patients)
    report = TemporalConsistencyReport(n_patients=len(patients))

    # onset_age <= age straight from the patient objects.
    for p in patients:
        age = p.demographics.age
        for c in p.conditions:
            report.n_conditions_checked += 1
            if c.onset_age > age:
                report.onset_after_age.append(
                    {"patient_id": p.demographics.patient_id, "condition": c.name,
                     "onset_age": c.onset_age, "age": age}
                )

    # Observation-period span + measurement containment via the CDM rows.
    tables = build_cdm_tables(patients)
    span_by_person: Dict[Any, tuple] = {}
    for op in tables["observation_period"]:
        start = op["observation_period_start_date"]
        end = op["observation_period_end_date"]
        span_by_person[op["person_id"]] = (start, end)
        if start and end and start > end:
            report.inverted_observation_period.append(
                {"person_id": op["person_id"], "start": start, "end": end}
            )

    for m in tables["measurement"]:
        date = m["measurement_date"]
        if not date:
            continue
        span = span_by_person.get(m["person_id"])
        if span is None:
            continue
        start, end = span
        report.n_measurements_checked += 1
        if start and end and not (start <= date <= end):
            report.measurement_outside_span.append(
                {"person_id": m["person_id"], "measurement_id": m["measurement_id"],
                 "measurement_date": date, "span_start": start, "span_end": end}
            )

    return report


def visit_order_report(patients: Sequence[Any]) -> Dict[str, Any]:
    """Informational: fraction of multi-visit patients whose visits are in order.

    The engine does not sort visit dates, so this is a *descriptive* statistic
    (not a pass/fail check). It is useful for a report that wants to state, for
    the record, how often visit dates happen to be non-decreasing.
    """
    patients = list(patients)
    multi = 0
    ordered = 0
    for p in patients:
        dates = [v.visit_date for v in p.visits]
        if len(dates) < 2:
            continue
        multi += 1
        if dates == sorted(dates):
            ordered += 1
    return {
        "multi_visit_patients": multi,
        "chronologically_ordered": ordered,
        "ordered_fraction": round(ordered / multi, 4) if multi else None,
        "note": "The engine draws visit dates independently and does not sort "
                "them; unordered visits are expected and not a defect.",
    }


# ─────────────────────────────────────────────────────────────────────────────
# Top-level report.
# ─────────────────────────────────────────────────────────────────────────────
def fidelity_report(patients: Sequence[Any]) -> Dict[str, Any]:
    """Assemble the full statistical-fidelity report for a cohort.

    Profile-free: unlike ``profile_fit_stats`` this needs no population profile.
    Returns a plain dict (JSON-friendly) so it can be serialized alongside the
    OMOP / FHIR export or the fairness passport.
    """
    patients = list(patients)
    if not patients:
        raise ValueError("fidelity_report requires a non-empty cohort")
    # Fail loud on obviously malformed input rather than producing junk stats.
    _ = _flat_patient_rows(patients)  # validates the flat-row contract holds

    temporal = temporal_consistency(patients)
    correlations = linked_lab_correlations(patients)
    return {
        "n_patients": len(patients),
        "lab_marginals": lab_value_marginals(patients),
        "condition_prevalence": condition_prevalence(patients),
        "linked_lab_correlations": [vars(c) for c in correlations],
        "temporal_consistency": {
            "ok": temporal.ok,
            "violations": temporal.violations,
            "onset_after_age": temporal.onset_after_age,
            "measurement_outside_span": temporal.measurement_outside_span,
            "inverted_observation_period": temporal.inverted_observation_period,
            "n_conditions_checked": temporal.n_conditions_checked,
            "n_measurements_checked": temporal.n_measurements_checked,
        },
        "visit_order": visit_order_report(patients),
    }
