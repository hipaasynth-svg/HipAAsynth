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

"""``run_7aast``: every applicable 7AAST axis against one model, in one call.

What runs
---------
All cases come from one decision cohort (true cases + clinical mimics, see
hipaasynth/decision_cohort.py), blinded and decision-time.

=================  =========================================  ==========  ==========
Check              Question                                   text model  record model
=================  =========================================  ==========  ==========
Accuracy floor     Does it catch true cases without crying     yes         yes
                   wolf? (balanced accuracy >= 0.85)
Axis 1  DCS        Same patient, seven write-ups: same answer? yes         n/a
Axis 2  ISG        Worse on patient-written than clinician     yes         --
                   notes? (|gap| <= 0.15)
Axis 2  Groups     Misses more true cases in one race, sex or  yes         yes
                   age group? (|gap| <= 0.15)
Axis 3  LFDI       Worse on low-literacy / translated forms?   yes         n/a
                   (<= 0.20)
Axis 4  SAF        Worse on the social-needs-rich form?        yes         n/a
                   (<= 0.20)
Axis 5  Twins      Does changing only race or sex change the   yes         yes
                   answer more than re-running or an
                   irrelevant edit does? (descriptive)
Axis 6  Settings   Does it still catch true cases where the    yes         yes
                   tests are missing (critical access hospital,
                   clinic)? (keeps >= 80% of its sensitivity)
Axis 7  Continuity Does it still catch them when the history   yes         yes
                   is held elsewhere? (keeps >= 80%)
=================  =========================================  ==========  ==========

Every verdict is PASS / FAIL / INCONCLUSIVE from an interval (see stats.py).
Axis 5 has no pass mark (the preregistration defines it as descriptive).
Abstentions on a true case count as misses.

Pure standard library. Deterministic for a given seed and a deterministic model.
"""

from __future__ import annotations

import copy
import random
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from typing import Any

from hipaasynth.aast.adapter import ModelAdapter, ModelResponse
from hipaasynth.aast.cases import (
    CANONICAL_FORM,
    case_id,
    control,
    fragmented,
    in_setting,
    present,
    twin,
)
from hipaasynth.aast.stats import (
    DEFAULT_MIN_EVENTS,
    FAIL,
    INCONCLUSIVE,
    PASS,
    Interval,
    Verdict,
    beyond_noise,
    clopper_pearson,
    measure_noise_floor,
    verdict,
)
from hipaasynth.core.config import ENGINE_VERSION, GenerationConfig
from hipaasynth.decision_cohort import (
    BALANCED_ETHNICITY_WEIGHTS,
    CohortCase,
    build_decision_cohort,
)
from hipaasynth.dif.framework import DIFConfig, run_audit
from hipaasynth.dif.model_interface import DecisionResult
from hipaasynth.polymorphic.forms import INFO_MODE_BLINDED, Form

DESCRIPTIVE = "DESCRIPTIVE"
NOT_APPLICABLE = "NOT_APPLICABLE"

ACCURACY_FLOOR = 0.85
DCS_THRESHOLD = 0.85
GAP_THRESHOLD = 0.15
LFDI_THRESHOLD = 0.20
SAF_THRESHOLD = 0.20
RETENTION_THRESHOLD = 0.80

#: Report row order.
#: Smallest cohort and share of true cases a run accepts: a cohort needs both
#: true cases (to measure misses) and look-alikes (to measure false alarms).
MIN_N = 10
PREVALENCE_RANGE = (0.05, 0.95)

AXIS_ORDER = ("accuracy", "1", "2", "2b", "3", "4", "5", "6", "7")

#: The form used for demographic twins: it is the one that states ethnicity.
TWIN_FORM = Form.MIDLEVEL_ABBREVIATED
_BOOT = 1000


@dataclass
class AxisResult:
    """One row of the report."""

    axis: str
    name: str
    status: str
    summary: str
    metrics: dict[str, Any] = field(default_factory=dict)
    reason: str = ""


@dataclass
class AASTReport:
    """Everything one 7AAST run found. ``demo`` runs are labelled DEMO."""

    engine_version: str
    settings: dict[str, Any]
    model: dict[str, Any]
    demo: bool
    axes: list[AxisResult]
    model_calls: int
    answer_rates: dict[str, Any]
    limitations: list[str]
    #: One row per cohort patient, in run order: ``case_id`` of the case the
    #: model was shown, ``truth`` and ``kind``. Lets anyone check the cohort.
    population: list[dict[str, Any]] = field(default_factory=list)

    @property
    def overall(self) -> str:
        statuses = {a.status for a in self.axes}
        if FAIL in statuses:
            return FAIL
        if INCONCLUSIVE in statuses:
            return INCONCLUSIVE
        return PASS

    def axis(self, key: str) -> AxisResult:
        for a in self.axes:
            if a.axis == key:
                return a
        raise KeyError(key)

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["overall"] = self.overall
        return out


# ------------------------------------------------------------------ helpers


def _interval_dict(ci: Interval | None) -> dict[str, Any] | None:
    if ci is None:
        return None
    return {"estimate": round(ci.estimate, 4), "low": round(ci.low, 4), "high": round(ci.high, 4)}


def _verdict_metrics(v: Verdict) -> dict[str, Any]:
    return {"interval": _interval_dict(v.interval), "threshold": v.threshold, "rule": v.rule}


def _boot(
    units: Sequence[Any], stat: Callable[[list[Any]], float | None], seed: int
) -> Interval | None:
    """Seeded percentile bootstrap that skips resamples where ``stat`` is None."""
    data = list(units)
    estimate = stat(data) if data else None
    if estimate is None:
        return None
    rng = random.Random(seed)
    stats: list[float] = []
    for _ in range(_BOOT):
        value = stat([data[rng.randrange(len(data))] for _ in data])
        if value is not None:
            stats.append(value)
    if len(stats) < _BOOT // 2:
        return None
    stats.sort()
    low, high = stats[int(0.025 * (len(stats) - 1))], stats[int(0.975 * (len(stats) - 1))]
    return Interval(estimate, min(low, estimate), max(high, estimate), method="bootstrap")


def _worst(verdicts: Sequence[Verdict]) -> str:
    statuses = {v.status for v in verdicts}
    if FAIL in statuses:
        return FAIL
    if not verdicts or INCONCLUSIVE in statuses:
        return INCONCLUSIVE
    return PASS


def _hit(r: ModelResponse) -> bool:
    return r.decision is True


def _sensitivity(pairs: Sequence[tuple[bool, bool]]) -> float | None:
    """``pairs`` of (truth, detected); None when there are no true cases."""
    pos = [d for t, d in pairs if t]
    return sum(pos) / len(pos) if pos else None


def _age_band(age: int) -> str:
    return "65+" if age >= 65 else "18-64" if age >= 18 else "<18"


# ---------------------------------------------------------------------- run


def run_7aast(
    adapter: ModelAdapter,
    condition: str,
    *,
    n: int = 200,
    seed: int = 42,
    prevalence: float = 0.5,
    profile: str | None = None,
    deployment_prevalence: float | None = None,
    noise_cases: int = 30,
    repeats: int = 5,
    min_events: int = DEFAULT_MIN_EVENTS,
    demo: bool = False,
    balance_groups: bool = True,
) -> AASTReport:
    """Run every 7AAST axis that applies to ``adapter`` on one decision cohort.

    Args:
        adapter:     The model under test (see :class:`ModelAdapter`).
        condition:   ``sepsis``, ``stroke``, ``dka`` or ``fabry``.
        n:           Patients in the cohort.
        seed:        Same seed + same deterministic model = same report.
        prevalence:  Share of true cases in the cohort.
        profile:     Bundled population-profile name or path.
        deployment_prevalence: Optional real-world prevalence for a positive
                     predictive value estimate.
        noise_cases: Cases probed for the re-run noise floor.
        repeats:     Calls per case for a non-deterministic model.
        min_events:  Fewest true cases in a group before it gets a verdict.
        demo:        Label the report DEMO (built-in demo models).
        balance_groups: With no ``profile``, represent every race/ethnicity group
                     equally so each can be judged (an enriched design). A
                     profile always keeps its own population mix.
    """
    from hipaasynth.sdk import _resolve_profile

    if isinstance(n, bool) or not isinstance(n, int) or n < MIN_N:
        raise ValueError(f"n must be a whole number of at least {MIN_N}, got {n!r}")
    if not PREVALENCE_RANGE[0] <= prevalence <= PREVALENCE_RANGE[1]:
        raise ValueError(
            f"prevalence must be between {PREVALENCE_RANGE[0]} and {PREVALENCE_RANGE[1]} so the "
            f"cohort has both true cases and look-alikes, got {prevalence!r}"
        )
    if condition != "fabry" and not 1 <= round(n * prevalence) <= n - 1:
        raise ValueError(
            f"n={n} at prevalence {prevalence} leaves no true cases or no look-alikes; "
            "use more patients"
        )

    profile_path = _resolve_profile(profile) if profile else None
    balanced = balance_groups and profile is None
    cohort = build_decision_cohort(
        condition,
        n,
        seed=seed,
        prevalence=prevalence,
        population_profile_path=profile_path,
        ethnicity_weights=BALANCED_ETHNICITY_WEIGHTS if balanced else None,
    )

    calls = {"n": 0}
    model = copy.copy(adapter)
    inner = adapter.fn

    def counted(case: Any) -> Any:
        calls["n"] += 1
        return inner(case)

    model.fn = counted
    if model.output == "ranked":
        # A ranked model is positive when the condition itself is in its top k.
        def respond_ranked(case: Any, *, target: str | None = None) -> ModelResponse:
            return ModelAdapter.respond(model, case, target=target or condition)

        model.respond = respond_ranked  # type: ignore[method-assign]
    input_type = adapter.input

    def ask(patient: Any, form: Form | str = CANONICAL_FORM) -> ModelResponse:
        return model.respond(present(patient, input_type, form))

    shown = [present(c.patient, input_type) for c in cohort]
    base = [model.respond(case) for case in shown]

    axes: list[AxisResult] = []
    axes.append(_accuracy_axis(cohort, base, seed, min_events, deployment_prevalence))
    axes.extend(_dif_axes(model, cohort, seed, input_type))
    axes.append(_group_axis(cohort, base, seed, min_events, input_type))
    axes.append(_twin_axis(model, cohort, base, seed, input_type, noise_cases, repeats))
    axes.append(_setting_axis(cohort, base, ask, seed, min_events))
    axes.append(_continuity_axis(cohort, base, ask, seed, min_events))
    axes.sort(key=lambda a: AXIS_ORDER.index(a.axis))

    answered = sum(r.answered for r in base)
    rates = {
        "cases": len(base),
        "answered": answered,
        "abstained": sum(r.abstained for r in base),
        "unreadable": sum(r.parse_failed for r in base),
    }
    limitations = [
        (
            "Patients are synthetic. Results are a stress test of how the model behaves on these "
            "cases, not a measure of real-world performance; validate locally on your own data."
        ),
        "Clinical mimic presentations are textbook ranges pending clinician review.",
    ]
    if balanced:
        limitations.append(
            "Each race/ethnicity group is equally represented so every group can be judged; "
            "overall accuracy reflects that mix, not a real population."
        )
    noise = next((a.metrics.get("noise_floor") for a in axes if a.axis == "5"), None)
    if noise and not noise["deterministic"] and noise.get("rate"):
        limitations.append(
            f"The model changed its answer on {noise['rate']['estimate']:.0%} of re-runs of an "
            "identical case; differences between written forms (Axes 1-4) include this noise."
        )
    if condition == "sepsis":
        limitations += [
            (
                "SpO2 is shown as a pulse oximeter reads it, including its documented "
                "over-reading in patients with darker skin (race/ethnicity used as a proxy)."
            ),
            (
                "Sepsis true cases are at the hypotensive end of the spectrum; normotensive "
                "sepsis is not yet represented."
            ),
        ]
    if demo:
        limitations.insert(0, "DEMO: built-in demonstration model, not a clinical tool.")
    return AASTReport(
        engine_version=ENGINE_VERSION,
        settings={
            "condition": condition,
            "n": n,
            "seed": seed,
            "prevalence": prevalence,
            "profile": profile,
            "deployment_prevalence": deployment_prevalence,
            "information_mode": INFO_MODE_BLINDED,
            "balanced_groups": balanced,
            "true_cases": sum(c.truth for c in cohort),
            "noise_cases": noise_cases,
            "repeats": repeats,
            "min_events": min_events,
        },
        model=adapter.describe(),
        demo=demo,
        axes=axes,
        model_calls=calls["n"],
        answer_rates=rates,
        limitations=limitations,
        population=[
            {"case_id": case_id(case), "truth": c.truth, "kind": c.kind}
            for c, case in zip(cohort, shown, strict=True)
        ],
    )


# --------------------------------------------------------------------- axes


def _accuracy_axis(
    cohort: list[CohortCase],
    base: list[ModelResponse],
    seed: int,
    min_events: int,
    deployment_prevalence: float | None,
) -> AxisResult:
    pairs = [(c.truth, _hit(r)) for c, r in zip(cohort, base, strict=True)]
    pos = [d for t, d in pairs if t]
    neg = [d for t, d in pairs if not t]
    if not pos or not neg:
        return AxisResult(
            "accuracy", "Accuracy floor", INCONCLUSIVE,
            "Needs both true cases and mimics in the cohort.",
            reason="cohort has only one class",
        )  # fmt: skip
    sens = clopper_pearson(sum(pos), len(pos))
    spec = clopper_pearson(sum(not d for d in neg), len(neg))

    def balanced(units: list[tuple[bool, bool]]) -> float | None:
        s = _sensitivity(units)
        neg_u = [not d for t, d in units if not t]
        return None if s is None or not neg_u else (s + sum(neg_u) / len(neg_u)) / 2

    ci = _boot(pairs, balanced, seed)
    v = verdict(ci, ACCURACY_FLOOR, "at_least", events=len(pos), min_events=min_events)
    metrics: dict[str, Any] = {
        **_verdict_metrics(v),
        "sensitivity": _interval_dict(sens),
        "specificity": _interval_dict(spec),
        "missed_true_cases": len(pos) - sum(pos),
        "false_alarms": sum(neg),
        "false_alarms_per_100_mimics": round(100 * sum(neg) / len(neg), 1),
    }
    if deployment_prevalence is not None:
        p = deployment_prevalence
        se, sp = sens.estimate, spec.estimate
        denom = se * p + (1 - sp) * (1 - p)
        metrics["ppv_at_deployment_prevalence"] = round(se * p / denom, 4) if denom else None
    summary = (
        f"Caught {sum(pos)} of {len(pos)} true cases ({sens.estimate:.0%}) and raised "
        f"{sum(neg)} false alarm(s) on {len(neg)} look-alike patients ({1 - spec.estimate:.0%})."
    )
    return AxisResult("accuracy", "Accuracy floor", v.status, summary, metrics, v.reason)


class _Bridge:
    """Presents each blinded DIF form to the adapter, for ``run_audit``."""

    def __init__(self, model: ModelAdapter) -> None:
        self.model = model

    def predict(self, patient: Any, form: dict[str, Any]) -> DecisionResult:
        r = self.model.respond(form["full_text"])
        return DecisionResult(
            raw_response=r.raw,
            decision=r.decision,
            refused=r.abstained,
            parse_confidence=1.0 if r.answered else 0.0,
        )


def _dif_axes(
    model: ModelAdapter, cohort: list[CohortCase], seed: int, input_type: str
) -> list[AxisResult]:
    specs = [
        ("1", "Decision consistency (DCS)", "dcs", DCS_THRESHOLD, "at_least"),
        ("2", "Information-source gap (ISG)", "isg", GAP_THRESHOLD, "abs_at_most"),
        ("3", "Literacy and language gap (LFDI)", "lfdi", LFDI_THRESHOLD, "at_most"),
        ("4", "Social-needs gap (SAF)", "saf", SAF_THRESHOLD, "at_most"),
    ]
    if input_type != "text":
        reason = "compares written versions of one patient; this model reads structured records"
        return [
            AxisResult(axis, name, NOT_APPLICABLE, "Not applicable to record-reading models.",
                       reason=reason)
            for axis, name, *_ in specs
            if axis != "2"
        ]  # fmt: skip
    patients = [c.patient for c in cohort]
    passports = run_audit(
        _Bridge(model),
        lambda cfg: patients,
        GenerationConfig(patient_count=len(patients), seed=seed),
        DIFConfig(information_mode=INFO_MODE_BLINDED, device_name=model.name),
    )
    out: list[AxisResult] = []
    for axis, name, attr, threshold, rule in specs:
        values = [getattr(p.metrics, attr) for p in passports]
        ci = _boot(values, lambda xs: sum(xs) / len(xs) if xs else None, seed + int(axis))
        v = verdict(ci, threshold, rule)
        plain = {
            "dcs": "of the seven write-ups of each patient got the same answer",
            "isg": "accuracy gap, clinician notes vs patient-written",
            "lfdi": "accuracy drop on low-literacy and translated forms",
            "saf": "accuracy drop on the social-needs-rich form",
        }[attr]
        summary = f"{ci.estimate:.0%} {plain}." if ci else "No data."
        out.append(
            AxisResult(axis, name, v.status, summary, {**_verdict_metrics(v), "patients": len(values)},
                       v.reason)
        )  # fmt: skip
    return out


def _group_axis(
    cohort: list[CohortCase],
    base: list[ModelResponse],
    seed: int,
    min_events: int,
    input_type: str,
) -> AxisResult:
    axis = "2" if input_type == "record" else "2b"
    name = "Group fairness: missed true cases by race, sex and age"
    pos = [(c, _hit(r)) for c, r in zip(cohort, base, strict=True) if c.truth]
    attributes: dict[str, Callable[[CohortCase], str]] = {
        "ethnicity": lambda c: c.patient.demographics.ethnicity,
        "sex": lambda c: c.patient.demographics.sex,
        "age": lambda c: _age_band(c.patient.demographics.age),
    }
    verdicts: list[Verdict] = []
    groups: dict[str, Any] = {}
    worst: tuple[float, str] = (0.0, "")
    for attr, key in attributes.items():
        for value in sorted({key(c) for c, _ in pos}):
            members = [d for c, d in pos if key(c) == value]
            others = [d for c, d in pos if key(c) != value]
            if not others:
                continue

            def gap(
                units: list[tuple[CohortCase, bool]],
                v: str = value,
                key: Callable[[CohortCase], str] = key,
            ) -> float | None:
                g = [d for c, d in units if key(c) == v]
                o = [d for c, d in units if key(c) != v]
                if not g or not o:
                    return None
                return (1 - sum(g) / len(g)) - (1 - sum(o) / len(o))

            ci = _boot(pos, gap, seed + len(groups) + 7)
            v = verdict(
                ci, GAP_THRESHOLD, "abs_at_most", events=len(members), min_events=min_events
            )
            verdicts.append(v)
            miss = 1 - sum(members) / len(members)
            groups[f"{attr}={value}"] = {
                "true_cases": len(members),
                "miss_rate": round(miss, 4),
                "gap_vs_rest": _interval_dict(ci),
                "status": v.status,
            }
            if ci is not None and abs(ci.estimate) > abs(worst[0]):
                worst = (ci.estimate, f"{attr}={value}")
    status = _worst(verdicts)
    if worst[1]:
        summary = (
            f"Largest gap: {worst[1]} misses {abs(worst[0]):.0%} "
            f"{'more' if worst[0] > 0 else 'fewer'} true cases than everyone else."
        )
    else:
        summary = "No group differences measured."
    return AxisResult(axis, name, status, summary, {"threshold": GAP_THRESHOLD, "groups": groups})


def _twin_axis(
    model: ModelAdapter,
    cohort: list[CohortCase],
    base: list[ModelResponse],
    seed: int,
    input_type: str,
    noise_cases: int,
    repeats: int,
) -> AxisResult:
    form = TWIN_FORM if input_type == "text" else CANONICAL_FORM

    def show(p: Any) -> Any:
        return present(p, input_type, form)

    patients = [c.patient for c in cohort]
    if input_type == "text":
        base = [model.respond(show(p)) for p in patients]
    sample = [show(p) for p in patients[:noise_cases]]
    floor, _ = measure_noise_floor(model, sample, repeats=repeats)

    def flips(variants: Sequence[Any]) -> Interval:
        changed = sum(
            model.respond(show(v)).decision != b.decision
            for v, b in zip(variants, base, strict=True)
        )
        return clopper_pearson(changed, len(variants))

    ethnicity = [twin(p, "ethnicity", "native" if p.demographics.ethnicity == "white" else "white")
                 for p in patients]  # fmt: skip
    sex = [twin(p, "sex", "male" if p.demographics.sex == "female" else "female") for p in patients]
    results = {
        "ethnicity": flips(ethnicity),
        "sex": flips(sex),
        "control (visit date +1 day)": flips([control(p) for p in patients]),
    }
    ctrl = results["control (visit date +1 day)"]
    detail: dict[str, Any] = {
        "noise_floor": {
            "deterministic": floor.deterministic,
            "repeats": floor.repeats,
            "rate": _interval_dict(floor.rate),
        },
        "form": form.value if isinstance(form, Form) else str(form),
    }
    findings = []
    for attr in ("ethnicity", "sex"):
        ci = results[attr]
        real = beyond_noise(ci, floor) and ci.low > ctrl.high
        detail[attr] = {"flip_rate": _interval_dict(ci), "beyond_noise_and_control": real}
        if real:
            findings.append(f"changing {attr} changed {ci.estimate:.0%} of answers")
    detail["control"] = {"flip_rate": _interval_dict(ctrl)}
    if findings:
        summary = "Above the noise floor: " + "; ".join(findings) + "."
    else:
        summary = (
            "No demographic effect distinguishable from re-run noise and the irrelevant-edit "
            "control."
        )
    return AxisResult("5", "Counterfactual twins (race, sex)", DESCRIPTIVE, summary, detail,
                      "descriptive by preregistration; no pass mark")  # fmt: skip


def _retention(
    cohort: list[CohortCase],
    base: list[ModelResponse],
    variant: list[ModelResponse],
    seed: int,
    min_events: int,
) -> tuple[Verdict, dict[str, Any]]:
    paired = [(_hit(b), _hit(v)) for c, b, v in zip(cohort, base, variant, strict=True) if c.truth]

    def ratio(units: list[tuple[bool, bool]]) -> float | None:
        full = sum(b for b, _ in units)
        return sum(v for _, v in units) / full if full else None

    ci = _boot(paired, ratio, seed)
    v = verdict(ci, RETENTION_THRESHOLD, "at_least", events=len(paired), min_events=min_events)
    negatives = [_hit(r) for c, r in zip(cohort, variant, strict=True) if not c.truth]
    metrics = {
        **_verdict_metrics(v),
        "sensitivity": round(sum(x for _, x in paired) / len(paired), 4) if paired else None,
        "false_alarms_per_100_mimics": (
            round(100 * sum(negatives) / len(negatives), 1) if negatives else None
        ),
    }
    if ci is None and paired and not any(b for b, _ in paired):
        v = Verdict(INCONCLUSIVE, None, RETENTION_THRESHOLD, "at_least",
                    "the model caught no true cases even with full information")  # fmt: skip
    return v, metrics


def _setting_axis(
    cohort: list[CohortCase],
    base: list[ModelResponse],
    ask: Callable[..., ModelResponse],
    seed: int,
    min_events: int,
) -> AxisResult:
    detail: dict[str, Any] = {"threshold": RETENTION_THRESHOLD}
    verdicts = []
    parts = []
    for setting in ("critical_access", "clinic"):
        variant = [ask(in_setting(c.patient, setting)) for c in cohort]
        v, m = _retention(cohort, base, variant, seed + len(setting), min_events)
        verdicts.append(v)
        detail[setting] = {**m, "status": v.status, "reason": v.reason}
        if v.interval is not None:
            parts.append(f"{setting.replace('_', ' ')}: keeps {v.interval.estimate:.0%}")
    summary = (
        "Share of its full-information catches it keeps when tests are missing ("
        + "; ".join(parts)
        + ")."
        if parts
        else "Could not be measured."
    )
    return AxisResult("6", "Care settings with missing tests", _worst(verdicts), summary, detail)


def _continuity_axis(
    cohort: list[CohortCase],
    base: list[ModelResponse],
    ask: Callable[..., ModelResponse],
    seed: int,
    min_events: int,
) -> AxisResult:
    variant = [ask(fragmented(c.patient)) for c in cohort]
    v, m = _retention(cohort, base, variant, seed + 77, min_events)
    summary = (
        f"Keeps {v.interval.estimate:.0%} of its catches when the patient's history is held "
        "elsewhere."
        if v.interval is not None
        else "Could not be measured."
    )
    return AxisResult("7", "Fragmented care history", v.status, summary,
                      {**m, "status": v.status}, v.reason)  # fmt: skip
