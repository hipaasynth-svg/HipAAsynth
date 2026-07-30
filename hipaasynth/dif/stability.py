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

"""Stability metrics for the fairness-audit layer (Tier 4, step 4).

Three metrics that describe *how trustworthy the audit's own numbers are*,
computed at the **cohort level** over a list of :class:`FairnessPassport`. They
deliberately do not touch the per-patient passport or its sealed
``content_sha256`` — a passport stays byte-identical; these add a second, cohort
layer on top.

  * **Concept drift** — how much a cohort fairness metric moves when the cohort
    is regenerated with a *different seed* (same config). Two passport lists in,
    per-metric drift out, with a "drifted" flag when the shift exceeds a
    threshold. Answers: "is my audit conclusion an artifact of one lucky seed?"

  * **Uncertainty** — the sampling uncertainty of a cohort metric, via
    **bootstrap resampling** of the passports (with replacement). The engine is
    deterministic per seed, so there is no run-to-run noise to average; the
    honest uncertainty that remains is *estimator* uncertainty — how much the
    metric would wobble on another cohort of the same size drawn the same way.
    Bootstrap standard error + a 95% percentile CI make that explicit. This is
    the honest definition the task asked for before implementing.

  * **Sensitivity** — the *local* sensitivity of a pass-rate to the pass/fail
    **threshold**, by finite difference. A tiny threshold nudge that swings the
    pass rate a lot means the audit verdict is fragile at that operating point.

All three are pure standard library and fully deterministic given their seeds.
"""
from __future__ import annotations

import random
import statistics
from dataclasses import dataclass
from typing import Callable, Dict, List, Sequence

from hipaasynth.dif.report import FairnessPassport


# ─────────────────────────────────────────────────────────────────────────────
# Cohort scalar extractors — the metrics drift / bootstrap operate on.
# ─────────────────────────────────────────────────────────────────────────────
def _dcs_mean(ps: Sequence[FairnessPassport]) -> float:
    return statistics.fmean([p.metrics.dcs for p in ps]) if ps else 0.0


def _truth(ps: Sequence[FairnessPassport]) -> List[FairnessPassport]:
    return [p for p in ps if p.metrics.truth_evaluated]


def _isg_mean(ps: Sequence[FairnessPassport]) -> float:
    t = _truth(ps)
    return statistics.fmean([p.metrics.isg for p in t]) if t else 0.0


def _lfdi_mean(ps: Sequence[FairnessPassport]) -> float:
    t = _truth(ps)
    return statistics.fmean([p.metrics.lfdi for p in t]) if t else 0.0


def _saf_mean(ps: Sequence[FairnessPassport]) -> float:
    t = _truth(ps)
    return statistics.fmean([p.metrics.saf for p in t]) if t else 0.0


def _overall_pass_rate(ps: Sequence[FairnessPassport]) -> float:
    return sum(1 for p in ps if p.passed()) / len(ps) if ps else 0.0


def _dcs_pass_rate(ps: Sequence[FairnessPassport]) -> float:
    return sum(1 for p in ps if p.metrics.dcs_pass) / len(ps) if ps else 0.0


COHORT_METRICS: Dict[str, Callable[[Sequence[FairnessPassport]], float]] = {
    "dcs_mean": _dcs_mean,
    "isg_mean": _isg_mean,
    "lfdi_mean": _lfdi_mean,
    "saf_mean": _saf_mean,
    "overall_pass_rate": _overall_pass_rate,
    "dcs_pass_rate": _dcs_pass_rate,
}

# Metrics that drift is reported on by default.
DEFAULT_DRIFT_METRICS = ["dcs_mean", "isg_mean", "lfdi_mean", "saf_mean", "overall_pass_rate"]
DEFAULT_DRIFT_THRESHOLD = 0.10


# ─────────────────────────────────────────────────────────────────────────────
# 1. Concept drift.
# ─────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class ConceptDriftResult:
    metric: str
    baseline: float
    comparison: float
    drift: float       # comparison - baseline
    abs_drift: float
    threshold: float
    drifted: bool


def concept_drift(
    baseline: Sequence[FairnessPassport],
    comparison: Sequence[FairnessPassport],
    *,
    metrics: Sequence[str] = tuple(DEFAULT_DRIFT_METRICS),
    threshold: float = DEFAULT_DRIFT_THRESHOLD,
) -> List[ConceptDriftResult]:
    """Per-metric drift between two cohort generations (e.g. two seeds).

    ``drift = metric(comparison) - metric(baseline)``. A metric is flagged
    ``drifted`` when ``abs(drift) > threshold`` — a meaningful shift, not noise.
    Both cohorts must be non-empty.
    """
    if not baseline or not comparison:
        raise ValueError("concept_drift requires two non-empty passport cohorts")
    out: List[ConceptDriftResult] = []
    for name in metrics:
        fn = COHORT_METRICS[name]
        b = fn(baseline)
        c = fn(comparison)
        d = c - b
        out.append(ConceptDriftResult(
            metric=name, baseline=b, comparison=c, drift=d, abs_drift=abs(d),
            threshold=threshold, drifted=abs(d) > threshold,
        ))
    return out


# ─────────────────────────────────────────────────────────────────────────────
# 2. Uncertainty (bootstrap).
# ─────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class BootstrapUncertainty:
    metric: str
    point_estimate: float
    std_error: float
    ci95_low: float
    ci95_high: float
    n_resamples: int
    n_cohort: int


def bootstrap_uncertainty(
    passports: Sequence[FairnessPassport],
    *,
    metric: str = "overall_pass_rate",
    n_resamples: int = 500,
    seed: int = 0,
) -> BootstrapUncertainty:
    """Bootstrap standard error + 95% percentile CI for a cohort metric.

    Resamples the passports with replacement ``n_resamples`` times, recomputes
    ``metric`` on each resample, and reports the point estimate (on the original
    cohort), the bootstrap standard error (stdev of the resample estimates), and
    the 2.5/97.5 percentile interval. Deterministic given ``seed``.
    """
    if metric not in COHORT_METRICS:
        raise ValueError(f"unknown metric {metric!r}; choose from {sorted(COHORT_METRICS)}")
    passports = list(passports)
    if not passports:
        raise ValueError("bootstrap_uncertainty requires a non-empty cohort")
    fn = COHORT_METRICS[metric]
    point = fn(passports)

    rng = random.Random(seed)
    n = len(passports)
    estimates: List[float] = []
    for _ in range(n_resamples):
        resample = [passports[rng.randrange(n)] for _ in range(n)]
        estimates.append(fn(resample))

    se = statistics.stdev(estimates) if len(estimates) > 1 else 0.0
    ordered = sorted(estimates)
    lo = _percentile(ordered, 2.5)
    hi = _percentile(ordered, 97.5)
    return BootstrapUncertainty(
        metric=metric, point_estimate=point, std_error=se,
        ci95_low=lo, ci95_high=hi, n_resamples=n_resamples, n_cohort=n,
    )


def _percentile(ordered: Sequence[float], pct: float) -> float:
    if not ordered:
        return 0.0
    if len(ordered) == 1:
        return float(ordered[0])
    pos = (pct / 100.0) * (len(ordered) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(ordered) - 1)
    frac = pos - lo
    return ordered[lo] * (1 - frac) + ordered[hi] * frac


# ─────────────────────────────────────────────────────────────────────────────
# 3. Sensitivity (threshold finite difference).
# ─────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class ThresholdSensitivity:
    pass_metric: str        # e.g. "dcs_pass_rate"
    value_attr: str         # per-patient metric compared to threshold, e.g. "dcs"
    base_threshold: float
    delta: float
    rate_minus: float       # pass rate at (threshold - delta)
    rate_base: float
    rate_plus: float        # pass rate at (threshold + delta)
    sensitivity: float      # central-difference d(pass_rate)/d(threshold)


# How each pass-rate relates a per-patient metric value to a threshold. ``ge``
# means "passes when value >= threshold" (DCS); ``le`` means "passes when
# value <= threshold" (LFDI/SAF are upper-bounded); ISG is two-sided (|value|).
_PASS_RULES = {
    "dcs": ("dcs", "ge"),
    "lfdi": ("lfdi", "le"),
    "saf": ("saf", "le"),
    "isg": ("isg", "abs_le"),
}


def _pass_rate_at(passports: Sequence[FairnessPassport], attr: str, mode: str, thr: float) -> float:
    total = 0
    passed = 0
    for p in passports:
        # ISG/LFDI/SAF are only meaningful when ground truth was evaluated.
        if attr != "dcs" and not p.metrics.truth_evaluated:
            continue
        total += 1
        v = getattr(p.metrics, attr)
        if mode == "ge":
            ok = v >= thr
        elif mode == "le":
            ok = v <= thr
        else:  # abs_le
            ok = abs(v) <= thr
        if ok:
            passed += 1
    return passed / total if total else 0.0


def threshold_sensitivity(
    passports: Sequence[FairnessPassport],
    *,
    threshold_name: str = "dcs",
    base_threshold: float = 0.85,
    delta: float = 0.05,
) -> ThresholdSensitivity:
    """Local sensitivity of a pass-rate to its pass/fail threshold.

    Recomputes the pass rate at ``base_threshold ± delta`` (using the stored
    per-patient metric values — no re-audit needed) and returns the central-
    difference slope ``(rate_plus - rate_minus) / (2·delta)``. For a
    lower-bounded metric (DCS, ``ge``) a *higher* threshold can only lower the
    pass rate, so the slope is ≤ 0; the magnitude is what matters — a large
    magnitude means the verdict is fragile at that operating point.
    """
    if threshold_name not in _PASS_RULES:
        raise ValueError(f"unknown threshold {threshold_name!r}; choose from {sorted(_PASS_RULES)}")
    if delta <= 0:
        raise ValueError("delta must be positive")
    passports = list(passports)
    if not passports:
        raise ValueError("threshold_sensitivity requires a non-empty cohort")
    attr, mode = _PASS_RULES[threshold_name]
    rate_minus = _pass_rate_at(passports, attr, mode, base_threshold - delta)
    rate_base = _pass_rate_at(passports, attr, mode, base_threshold)
    rate_plus = _pass_rate_at(passports, attr, mode, base_threshold + delta)
    sensitivity = (rate_plus - rate_minus) / (2.0 * delta)
    return ThresholdSensitivity(
        pass_metric=f"{threshold_name}_pass_rate",
        value_attr=attr,
        base_threshold=base_threshold,
        delta=delta,
        rate_minus=rate_minus,
        rate_base=rate_base,
        rate_plus=rate_plus,
        sensitivity=sensitivity,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Bundle.
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class StabilityReport:
    """All three stability metrics for one audit, plus a markdown renderer."""

    concept_drift: List[ConceptDriftResult]
    uncertainty: BootstrapUncertainty
    sensitivity: ThresholdSensitivity

    def any_drift(self) -> bool:
        return any(d.drifted for d in self.concept_drift)

    def to_markdown(self) -> str:
        lines = [
            "# HipAAsynth Audit Stability Report",
            "",
            "## Concept Drift (seed-to-seed)",
            "| Metric | Baseline | Comparison | Drift | Flagged |",
            "|---|---|---|---|---|",
        ]
        for d in self.concept_drift:
            lines.append(
                f"| {d.metric} | {d.baseline:.3f} | {d.comparison:.3f} | "
                f"{d.drift:+.3f} | {'⚠️ yes' if d.drifted else 'no'} |"
            )
        u = self.uncertainty
        s = self.sensitivity
        lines += [
            "",
            "## Uncertainty (bootstrap)",
            f"- **Metric:** {u.metric}",
            f"- **Point estimate:** {u.point_estimate:.3f}",
            f"- **Bootstrap SE:** {u.std_error:.3f}",
            f"- **95% CI:** [{u.ci95_low:.3f}, {u.ci95_high:.3f}] "
            f"({u.n_resamples} resamples, n={u.n_cohort})",
            "",
            "## Sensitivity (threshold finite difference)",
            f"- **Pass metric:** {s.pass_metric}",
            f"- **Base threshold:** {s.base_threshold:.3f} (±{s.delta:.3f})",
            f"- **Pass rate −δ / base / +δ:** {s.rate_minus:.3f} / "
            f"{s.rate_base:.3f} / {s.rate_plus:.3f}",
            f"- **d(pass rate)/d(threshold):** {s.sensitivity:+.3f}",
            "",
            "---",
            "",
            "*All data are synthetic. No PHI is used or referenced.*",
        ]
        return "\n".join(lines)


def stability_report(
    baseline: Sequence[FairnessPassport],
    comparison: Sequence[FairnessPassport],
    *,
    uncertainty_metric: str = "overall_pass_rate",
    n_resamples: int = 500,
    bootstrap_seed: int = 0,
    threshold_name: str = "dcs",
    base_threshold: float = 0.85,
    delta: float = 0.05,
    drift_threshold: float = DEFAULT_DRIFT_THRESHOLD,
) -> StabilityReport:
    """Compute all three stability metrics for a baseline/comparison audit pair.

    ``baseline`` and ``comparison`` are two passport cohorts from the same audit
    config under different generation seeds (for the drift comparison). The
    uncertainty and sensitivity metrics are computed on ``baseline``.
    """
    return StabilityReport(
        concept_drift=concept_drift(baseline, comparison, threshold=drift_threshold),
        uncertainty=bootstrap_uncertainty(
            baseline, metric=uncertainty_metric, n_resamples=n_resamples, seed=bootstrap_seed
        ),
        sensitivity=threshold_sensitivity(
            baseline, threshold_name=threshold_name,
            base_threshold=base_threshold, delta=delta,
        ),
    )
