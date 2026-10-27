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
Shared statistics for the 7AAST axes: intervals, verdicts and the noise floor.

Three rules every axis follows
------------------------------
1. **Every estimate carries an interval.** Rates (miss rates, flip rates) use
   the exact Clopper-Pearson interval, which stays valid for the small subgroups
   these audits are about, where bootstrap intervals break down. Other metrics
   use a seeded percentile bootstrap, so a rerun gives identical bounds.
2. **Three verdicts, never false confidence.** PASS when the whole interval is
   on the safe side of the threshold, FAIL when the whole interval is on the
   wrong side, INCONCLUSIVE when it straddles the line or a group has too few
   positive cases (``min_events``) to say anything.
3. **Effects must beat the noise floor.** Non-deterministic models (LLMs) can
   change their answer on an identical input. 2026 counterfactual-audit work
   found re-run instability comparable to demographic effects, so an effect only
   counts when its interval lies entirely above the model's own measured re-run
   flip rate (:func:`measure_noise_floor`, :func:`beyond_noise`).

All functions are deterministic and use only the Python standard library.
"""

from __future__ import annotations

import math
import random
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from hipaasynth.aast.adapter import ModelAdapter, ModelResponse

PASS = "PASS"
FAIL = "FAIL"
INCONCLUSIVE = "INCONCLUSIVE"

#: Fewest positive cases in a group before a verdict on that group is issued.
#: A conservative default; axes may raise it. Below it the verdict is INCONCLUSIVE.
DEFAULT_MIN_EVENTS = 10

#: Rules for comparing an interval with a threshold.
RULES = ("at_least", "at_most", "abs_at_most")


@dataclass(frozen=True)
class Interval:
    """A point estimate with a two-sided confidence interval."""

    estimate: float
    low: float
    high: float
    level: float = 0.95
    method: str = ""

    def __post_init__(self) -> None:
        if not self.low <= self.estimate <= self.high:
            raise ValueError(f"interval must satisfy low <= estimate <= high, got {self!r}")


@dataclass(frozen=True)
class Verdict:
    """The outcome of one check, with the evidence that produced it."""

    status: str
    interval: Interval | None
    threshold: float
    rule: str
    reason: str


# ------------------------------------------------------------------ intervals


def _log_binom_pmf(i: int, n: int, p: float) -> float:
    return (
        math.lgamma(n + 1)
        - math.lgamma(i + 1)
        - math.lgamma(n - i + 1)
        + i * math.log(p)
        + (n - i) * math.log1p(-p)
    )


def _binom_cdf(k: int, n: int, p: float) -> float:
    """P(X <= k) for X ~ Binomial(n, p)."""
    if k < 0:
        return 0.0
    if k >= n:
        return 1.0
    if p <= 0.0:
        return 1.0
    if p >= 1.0:
        return 0.0
    return min(1.0, sum(math.exp(_log_binom_pmf(i, n, p)) for i in range(k + 1)))


def _bisect(f: Callable[[float], float], lo: float, hi: float) -> float:
    """Root of a function monotone on [lo, hi], to 1e-12."""
    for _ in range(200):
        mid = (lo + hi) / 2
        if (f(lo) > 0) == (f(mid) > 0):
            lo = mid
        else:
            hi = mid
        if hi - lo < 1e-12:
            break
    return (lo + hi) / 2


def clopper_pearson(successes: int, n: int, level: float = 0.95) -> Interval:
    """Exact binomial interval for ``successes`` out of ``n``.

    Guaranteed coverage at any ``n``, including the small subgroup sizes where
    normal-approximation and bootstrap intervals are unreliable.

    Raises:
        ValueError: on ``n < 1``, ``successes`` outside ``[0, n]`` or a bad level.
    """
    if isinstance(n, bool) or not isinstance(n, int) or n < 1:
        raise ValueError(f"n must be an int >= 1, got {n!r}")
    if isinstance(successes, bool) or not isinstance(successes, int) or not 0 <= successes <= n:
        raise ValueError(f"successes must be an int in [0, {n}], got {successes!r}")
    if not 0 < level < 1:
        raise ValueError(f"level must be in (0, 1), got {level!r}")
    alpha = 1 - level
    k = successes
    # Lower: P(X >= k | p) = alpha/2  <=>  1 - cdf(k-1) = alpha/2.
    low = 0.0 if k == 0 else _bisect(lambda p: (1 - _binom_cdf(k - 1, n, p)) - alpha / 2, 0, 1)
    # Upper: P(X <= k | p) = alpha/2.
    high = 1.0 if k == n else _bisect(lambda p: _binom_cdf(k, n, p) - alpha / 2, 0, 1)
    estimate = k / n
    return Interval(
        estimate=estimate,
        low=min(low, estimate),
        high=max(high, estimate),
        level=level,
        method="clopper-pearson",
    )


def bootstrap_interval(
    values: Sequence[Any],
    statistic: Callable[[list[Any]], float],
    *,
    seed: int,
    resamples: int = 2000,
    level: float = 0.95,
) -> Interval:
    """Seeded percentile-bootstrap interval of ``statistic`` over ``values``.

    ``values`` are the resampling units (usually patients), so paired designs
    keep each patient's measurements together. The same seed always gives the
    same bounds.

    Raises:
        ValueError: on empty ``values``, ``resamples < 100`` or a bad level.
    """
    data = list(values)
    if not data:
        raise ValueError("bootstrap needs at least one value")
    if resamples < 100:
        raise ValueError(f"resamples must be >= 100, got {resamples!r}")
    if not 0 < level < 1:
        raise ValueError(f"level must be in (0, 1), got {level!r}")
    rng = random.Random(seed)
    n = len(data)
    stats = sorted(statistic([data[rng.randrange(n)] for _ in range(n)]) for _ in range(resamples))
    estimate = statistic(data)
    tail = (1 - level) / 2
    low = stats[math.floor(tail * (resamples - 1))]
    high = stats[math.ceil((1 - tail) * (resamples - 1))]
    return Interval(
        estimate=estimate,
        low=min(low, estimate),
        high=max(high, estimate),
        level=level,
        method=f"bootstrap(resamples={resamples}, seed={seed})",
    )


# -------------------------------------------------------------------- verdicts


def verdict(
    interval: Interval | None,
    threshold: float,
    rule: str,
    *,
    events: int | None = None,
    min_events: int = DEFAULT_MIN_EVENTS,
) -> Verdict:
    """PASS / FAIL / INCONCLUSIVE for ``interval`` against ``threshold``.

    Rules:
        ``at_least``     the metric must be >= threshold (e.g. DCS >= 0.85).
        ``at_most``      the metric must be <= threshold (e.g. LFDI <= 0.20).
        ``abs_at_most``  |metric| must be <= threshold (e.g. |ISG| <= 0.15).

    Args:
        events:     Positive cases behind the estimate, when it depends on them
                    (miss rates, sensitivity). Below ``min_events`` the verdict
                    is INCONCLUSIVE whatever the interval says.
        min_events: See :data:`DEFAULT_MIN_EVENTS`.
    """
    if rule not in RULES:
        raise ValueError(f"rule must be one of {RULES}, got {rule!r}")
    if interval is None:
        return Verdict(INCONCLUSIVE, None, threshold, rule, "no data to evaluate")
    if events is not None and events < min_events:
        return Verdict(
            INCONCLUSIVE,
            interval,
            threshold,
            rule,
            f"only {events} positive case(s); at least {min_events} needed",
        )
    lo, hi, t = interval.low, interval.high, threshold
    if rule == "at_least":
        passed, failed = lo >= t, hi < t
    elif rule == "at_most":
        passed, failed = hi <= t, lo > t
    else:
        passed, failed = -t <= lo and hi <= t, lo > t or hi < -t
    span = f"[{lo:.3f}, {hi:.3f}]"
    if passed:
        return Verdict(PASS, interval, t, rule, f"interval {span} is within the threshold {t}")
    if failed:
        return Verdict(FAIL, interval, t, rule, f"interval {span} is entirely outside {t}")
    return Verdict(INCONCLUSIVE, interval, t, rule, f"interval {span} straddles the threshold {t}")


# ----------------------------------------------------------------- noise floor


@dataclass(frozen=True)
class NoiseFloor:
    """How often the model changes its answer when nothing about the case changes.

    Attributes:
        deterministic: Two identical calls gave identical answers on every case.
        repeats:       Calls made per case.
        flips:         Cases whose decisions were not all the same across repeats.
        cases:         Cases probed.
        rate:          ``flips / cases`` with an exact interval.
    """

    deterministic: bool
    repeats: int
    flips: int
    cases: int
    rate: Interval


def majority_decision(responses: Sequence[ModelResponse]) -> bool | None:
    """Majority vote over answered responses; ``None`` on a tie or no answers."""
    yes = sum(1 for r in responses if r.decision is True)
    no = sum(1 for r in responses if r.decision is False)
    if yes == no:
        return None
    return yes > no


def _outcome(r: ModelResponse) -> tuple[Any, ...]:
    return (r.decision, r.abstained, r.parse_failed)


def measure_noise_floor(
    adapter: ModelAdapter,
    cases: Sequence[Any],
    *,
    repeats: int = 5,
    targets: Sequence[str] | None = None,
    level: float = 0.95,
) -> tuple[NoiseFloor, list[list[ModelResponse]]]:
    """Measure the model's re-run instability on ``cases``.

    Each case is sent twice first. If every pair matches, the model is treated
    as deterministic and no further calls are made. Otherwise each case is sent
    ``repeats`` times in total. Cost: ``2 x len(cases)`` calls for a
    deterministic model, ``repeats x len(cases)`` otherwise.

    Returns:
        The :class:`NoiseFloor` and every case's responses, so the axis can reuse
        them (for example via :func:`majority_decision`) instead of calling again.

    Raises:
        ValueError: on no cases, ``repeats < 2`` or mismatched ``targets``.
    """
    if not cases:
        raise ValueError("noise floor needs at least one case")
    if isinstance(repeats, bool) or not isinstance(repeats, int) or repeats < 2:
        raise ValueError(f"repeats must be an int >= 2, got {repeats!r}")
    if targets is not None and len(targets) != len(cases):
        raise ValueError("targets must have one entry per case")

    def ask(i: int) -> ModelResponse:
        target = targets[i] if targets is not None else None
        return adapter.respond(cases[i], target=target)

    runs = [[ask(i), ask(i)] for i in range(len(cases))]
    deterministic = all(_outcome(a) == _outcome(b) for a, b in runs)
    if not deterministic:
        for i, responses in enumerate(runs):
            responses.extend(ask(i) for _ in range(repeats - 2))
    flips = sum(1 for responses in runs if len({_outcome(r) for r in responses}) > 1)
    floor = NoiseFloor(
        deterministic=deterministic,
        repeats=2 if deterministic else repeats,
        flips=flips,
        cases=len(cases),
        rate=clopper_pearson(flips, len(cases), level),
    )
    return floor, runs


def beyond_noise(effect: Interval, floor: NoiseFloor) -> bool:
    """True when ``effect`` is distinguishable from re-run noise.

    The effect's whole interval must lie above the floor's upper bound. For a
    deterministic model the floor is zero, so any effect whose interval excludes
    zero counts.
    """
    if floor.deterministic:
        return effect.low > 0
    return effect.low > floor.rate.high
