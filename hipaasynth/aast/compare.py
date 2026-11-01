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

"""Paired runs: the same model on a scenario's patients and on the US baseline.

A single 7AAST run says how a model does on one population. The question a
buyer asks is sharper: *does it do worse for these patients than for everyone
else?* :func:`compare` takes two report documents made with the same model,
condition, input, size, seed and prevalence, one on the scenario's population
profile and one on the US reference profile, and states the difference:

* true cases caught and look-alikes cleared, each with the difference and its
  95% interval (Newcombe's method from Wilson score intervals, for two
  independent proportions), and
* every other check's estimate side by side.

A **comparison document** holds both reports unchanged, the comparison, and a
hash chain: ``target`` and ``baseline`` are the two report hashes,
``comparison`` hashes the comparison, and ``report`` hashes all three, so the
same seal (signature, timestamp) covers the pair.
"""

from __future__ import annotations

import math
from typing import Any

from hipaasynth.aast.report import (
    Check,
    Verification,
    _seal_checks,
    _sha,
    canonical,
    verify,
)

FORMAT = "hipaasynth-7aast-comparison/1"
#: The baseline population: the US national reference profile.
BASELINE_PROFILE = "us_default"
_SAME = ("engine_version", "input", "condition", "n", "seed", "prevalence")


class ComparisonError(ValueError):
    """Two reports that cannot be compared, or a comparison that does not check out."""


def _wilson(k: int, n: int, z: float = 1.959963984540054) -> tuple[float, float]:
    if n == 0:
        return 0.0, 1.0
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def newcombe(k1: int, n1: int, k2: int, n2: int) -> dict[str, float]:
    """Difference p1 - p2 of two independent proportions with its 95% interval.

    Newcombe RG. Interval estimation for the difference between independent
    proportions. Stat Med 1998;17(8):873-890 (method 10).
    """
    p1, p2 = (k1 / n1 if n1 else 0.0), (k2 / n2 if n2 else 0.0)
    l1, u1 = _wilson(k1, n1)
    l2, u2 = _wilson(k2, n2)
    d = p1 - p2
    low = d - math.sqrt((p1 - l1) ** 2 + (u2 - p2) ** 2)
    high = d + math.sqrt((u1 - p1) ** 2 + (p2 - l2) ** 2)
    return {"estimate": round(d, 4), "low": round(low, 4), "high": round(high, 4)}


def _counts(doc: dict[str, Any]) -> dict[str, int]:
    pop = doc["population"]
    acc = next(a for a in doc["results"]["axes"] if a.get("axis") == "accuracy")
    m = acc.get("metrics") or {}
    t, n = int(pop["true_cases"]), int(pop["n"])
    return {"true_cases": t, "caught": t - int(m.get("missed_true_cases") or 0),
            "look_alikes": n - t, "cleared": (n - t) - int(m.get("false_alarms") or 0)}  # fmt: skip


def _estimate(axis: dict[str, Any]) -> float | None:
    m = axis.get("metrics") or {}
    for key in ("interval",):
        if isinstance(m.get(key), dict):
            est = m[key].get("estimate")
            return None if est is None else float(est)
    return None


def compare(target: dict[str, Any], baseline: dict[str, Any]) -> dict[str, Any]:
    """The comparison of two report documents (target population vs baseline)."""
    tp, bp = target["population"], baseline["population"]
    differ = [k for k in _SAME if tp.get(k) != bp.get(k)]
    if target["method"]["model"] != baseline["method"]["model"]:
        differ.append("model")
    if target["method"]["settings"].get("tests") != baseline["method"]["settings"].get("tests"):
        differ.append("tests")
    if differ:
        raise ComparisonError(f"the two reports differ in {', '.join(differ)}; run both with the "
                              "same model and settings")  # fmt: skip
    tc, bc = _counts(target), _counts(baseline)
    rows: list[dict[str, Any]] = [
        {"metric": "True cases caught (sensitivity)", "key": "sensitivity",
         "target": round(tc["caught"] / tc["true_cases"], 4) if tc["true_cases"] else None,
         "baseline": round(bc["caught"] / bc["true_cases"], 4) if bc["true_cases"] else None,
         "target_counts": [tc["caught"], tc["true_cases"]],
         "baseline_counts": [bc["caught"], bc["true_cases"]],
         "difference": newcombe(tc["caught"], tc["true_cases"], bc["caught"], bc["true_cases"])},
        {"metric": "Look-alikes cleared (specificity)", "key": "specificity",
         "target": round(tc["cleared"] / tc["look_alikes"], 4) if tc["look_alikes"] else None,
         "baseline": round(bc["cleared"] / bc["look_alikes"], 4) if bc["look_alikes"] else None,
         "target_counts": [tc["cleared"], tc["look_alikes"]],
         "baseline_counts": [bc["cleared"], bc["look_alikes"]],
         "difference": newcombe(tc["cleared"], tc["look_alikes"], bc["cleared"],
                                bc["look_alikes"])},
    ]  # fmt: skip
    checks = []
    base_axes = {a.get("axis"): a for a in baseline["results"]["axes"]}
    for a in target["results"]["axes"]:
        b = base_axes.get(a.get("axis"))
        if b is None:
            continue
        te, be = _estimate(a), _estimate(b)
        checks.append({"axis": a.get("axis"), "name": a.get("name"),
                       "target_status": a.get("status"), "baseline_status": b.get("status"),
                       "target_estimate": te, "baseline_estimate": be,
                       "difference": None if te is None or be is None else round(te - be, 4)})  # fmt: skip
    sens = rows[0]["difference"]
    if sens["high"] < 0:
        finding = "WORSE"
    elif sens["low"] > 0:
        finding = "BETTER"
    else:
        finding = "NO_CLEAR_GAP"
    return {
        "target_label": _label(tp.get("profile")),
        "target_profile": tp.get("profile"),
        "baseline_profile": bp.get("profile"),
        "scenario": (target["method"].get("provenance") or {}).get("scenario"),
        "sensitivity_finding": finding,
        "rows": rows,
        "checks": checks,
        "method": "Difference of two independent proportions, 95% interval by Newcombe's "
        "method 10 (Wilson score), Stat Med 1998;17:873-890.",
    }


def _label(profile: str | None) -> str:
    """A readable name for a bundled profile (its display name), else the name itself."""
    import json

    from hipaasynth.sdk import _resolve_profile

    if not profile:
        return "the default population"
    try:
        path = _resolve_profile(profile)
        with open(path or "", encoding="utf-8") as fh:
            return str(json.load(fh).get("display_name") or profile)
    except (OSError, ValueError):
        return str(profile)


def plain_english(comparison: dict[str, Any], condition: str) -> str:
    sens = comparison["rows"][0]
    d = sens["difference"]
    who = comparison.get("target_label") or comparison.get("target_profile")
    head = (
        f"On {who} patients the model caught {100 * (sens['target'] or 0):.0f}% of true "
        f"{condition} cases ({sens['target_counts'][0]} of {sens['target_counts'][1]}), against "
        f"{100 * (sens['baseline'] or 0):.0f}% on the US baseline "
        f"({sens['baseline_counts'][0]} of {sens['baseline_counts'][1]})."
    )
    points = abs(100 * d["estimate"])
    if comparison["sensitivity_finding"] == "WORSE":
        tail = (f" That is {points:.0f} points worse for these patients (95% range "
                f"{100 * -d['high']:.0f} to {100 * -d['low']:.0f} points worse): a real gap.")  # fmt: skip
    elif comparison["sensitivity_finding"] == "BETTER":
        tail = f" That is {points:.0f} points better for these patients, a real difference."
    else:
        tail = (f" The difference ({100 * d['estimate']:+.0f} points, 95% range "
                f"{100 * d['low']:+.0f} to {100 * d['high']:+.0f}) is not clear at this size; "
                "more patients would settle it.")  # fmt: skip
    return head + tail


def build_comparison(target: dict[str, Any], baseline: dict[str, Any]) -> dict[str, Any]:
    """A comparison document: both reports, the comparison and its hash chain."""
    comparison = compare(target, baseline)
    t, b = target["chain"]["report"], baseline["chain"]["report"]
    c = _sha(canonical(comparison))
    return {
        "format": FORMAT,
        "target": target,
        "baseline": baseline,
        "comparison": comparison,
        "chain": {"algorithm": "sha256", "target": t, "baseline": b, "comparison": c,
                  "report": _sha(c + t + b)},  # fmt: skip
    }


def chain_text(doc: dict[str, Any]) -> str:
    """The text whose SHA-256 is the comparison's report hash (for opentimestamps.org)."""
    ch = doc["chain"]
    return str(ch["comparison"] + ch["target"] + ch["baseline"])


def verify_comparison(doc: dict[str, Any], *, regenerate: bool = False,
                      bitcoin: bool = False) -> Verification:  # fmt: skip
    """Check both reports, the comparison, the chain and the seal."""
    out = Verification()
    for side in ("target", "baseline"):
        inner = verify(doc[side], regenerate=regenerate, bitcoin=bitcoin)
        out.checks.append(Check(f"{side} report", inner.ok,
                                "checks out" if inner.ok else "; ".join(
                                    f"{c.name}: {c.detail}" for c in inner.checks if not c.ok)))  # fmt: skip
        same = doc["chain"].get(side) == doc[side]["chain"].get("report")
        out.checks.append(Check(f"{side} hash in chain", same,
                                "matches" if same else "does not match the report inside"))  # fmt: skip
    try:
        recomputed = compare(doc["target"], doc["baseline"])
    except (ComparisonError, KeyError, TypeError, StopIteration) as err:
        out.checks.append(Check("comparison", False, f"cannot recompute ({err})"))
        return out
    out.checks.append(Check("comparison", recomputed == doc["comparison"],
                            "recomputed from the two reports" if recomputed == doc["comparison"]
                            else "differs from what the two reports give"))  # fmt: skip
    ch = doc["chain"]
    c = _sha(canonical(doc["comparison"]))
    ok = ch.get("comparison") == c and ch.get("report") == _sha(c + ch["target"] + ch["baseline"])
    out.checks.append(
        Check("comparison hash", ok, ch.get("report", "") if ok else "does not match")
    )
    out.checks.extend(_seal_checks(doc, bitcoin=bitcoin))
    return out
