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

"""The 7AAST report as a file: JSON for systems, HTML for people, and a hash chain.

A report document has three sections and a chain of four SHA-256 hashes:

==========  =========================================================  ==========================
Stage       What it covers                                             Hash
==========  =========================================================  ==========================
population  The cohort: settings that generate it and, for every       ``sha256(canon(pop))``
            patient, the content hash of the case shown, its truth
            and its kind.
method      How the model was tested: engine version, run settings,    ``sha256(canon(method)
            how answers were read, pass marks, axis order.             + population)``
results     Every axis result, answer rates, model calls, overall.     ``sha256(canon(results)
                                                                       + method + population)``
report      The whole document.                                        ``sha256(results + method
                                                                       + population)``
==========  =========================================================  ==========================

``canon`` is JSON with sorted keys and no spaces. Each hash covers the ones
before it, so a change anywhere (one case, one pass mark, one number) changes
the final ``report`` hash. :func:`verify` recomputes the chain, and with
``regenerate=True`` rebuilds the cohort from its settings and checks every case.

What the chain does and does not show: it shows the document is internally
consistent and unchanged since the hashes were written. It cannot show who
wrote it. To make an edit detectable, record the ``report`` hash somewhere the
editor cannot change (an email, a ticket, a contract annex) when the run is
made. A report is a stress-test record on synthetic patients, not a
certification.

Pure standard library. Same inputs, same model, same hashes.
"""

from __future__ import annotations

import hashlib
import html
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hipaasynth.aast import run as _run
from hipaasynth.aast.run import AXIS_ORDER, AASTReport
from hipaasynth.aast.stats import FAIL, INCONCLUSIVE, PASS

FORMAT = "hipaasynth-7aast-report/1"
STAGES = ("population", "method", "results", "report")

#: Settings that decide which patients are generated (the rest go in ``method``).
_POPULATION_SETTINGS = (
    "condition",
    "n",
    "seed",
    "prevalence",
    "profile",
    "information_mode",
    "balanced_groups",
)

#: Plain-English description of each check, for the HTML report.
AXIS_QUESTIONS: dict[str, str] = {
    "accuracy": (
        "Does the model catch true cases without raising alarms on look-alike patients? "
        "Balanced accuracy (the average of the share of true cases caught and the share of "
        "look-alikes correctly cleared) must be at least 85%."
    ),
    "1": (
        "Is the answer the same when the same patient is written up seven different ways "
        "(physician note, nurse note, patient message, translated note and others)? "
        "At least 85% of patients must get one answer across all seven."
    ),
    "2": (
        "Text models: is the model worse on notes written by the patient than on notes "
        "written by a clinician? Record models: does it miss more true cases in one race, "
        "sex or age group than another (skin tone, rurality, insurance and social needs "
        "are checked too)? The gap must be within 15 points."
    ),
    "2b": (
        "Does the model miss more true cases in one race, sex or age group than another? "
        "The gap in miss rates must be within 15 points. Skin tone, rurality, insurance and "
        "social needs are also checked: a clear gap there fails the check."
    ),
    "3": (
        "Is the model worse on low-literacy or translated write-ups of the same patient? "
        "The gap must be within 20 points."
    ),
    "4": (
        "Is the model worse when the write-up is full of social needs (housing, transport, "
        "cost) for the same patient? The gap must be within 20 points."
    ),
    "5": (
        "If only the patient's race or sex is changed, does the answer change more often "
        "than when the model is simply re-run or an irrelevant detail is changed? It fails "
        "when race or sex alone changes answers beyond both, and passes when it changes at "
        "most 5% of them."
    ),
    "6": (
        "Does the model still catch true cases where some tests cannot be run (a critical "
        "access hospital with no lactate, blood gas or ketone test; a clinic with vitals and "
        "bedside tests only)? It must keep at least 80% of its hospital sensitivity."
    ),
    "7": (
        "Does the model still catch true cases when the patient's history is held by another "
        "health system? It must keep at least 80% of its sensitivity."
    ),
}

STATUS_MEANING = {
    PASS: "Passed: the whole confidence interval is on the right side of the pass mark.",
    FAIL: "Failed: the whole confidence interval is on the wrong side of the pass mark.",
    INCONCLUSIVE: (
        "Inconclusive: the interval straddles the pass mark, or there were too few cases to "
        "judge. More patients (--n) narrow the interval."
    ),
    _run.DESCRIPTIVE: "Reported for review; no pass mark.",
    _run.NOT_APPLICABLE: "Not applicable to this kind of model.",
}


OVERALL_MEANING = {
    FAIL: "At least one check failed: the model did measurably worse than its pass mark.",
    INCONCLUSIVE: (
        "No check failed, but at least one could not be decided at this cohort size. "
        "A larger run (--n) may settle it."
    ),
    PASS: "Every check with a pass mark passed.",
}


class ReportFileError(ValueError):
    """The file is not a 7AAST report document."""


# ------------------------------------------------------------------ hashing


def canonical(obj: Any) -> str:
    """Compact JSON with sorted keys: one text per value, so one hash per value."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False)  # fmt: skip


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def chain(population: Any, method: Any, results: Any) -> dict[str, str]:
    """The four stage hashes for these sections."""
    pop = _sha(canonical(population))
    meth = _sha(canonical(method) + pop)
    res = _sha(canonical(results) + meth + pop)
    return {"population": pop, "method": meth, "results": res, "report": _sha(res + meth + pop)}


# ----------------------------------------------------------------- document


def build_document(report: AASTReport) -> dict[str, Any]:
    """The report as a JSON-ready document with its hash chain."""
    d = json.loads(canonical(report.to_dict()))  # tuples -> lists, as a reader will see it
    settings = d["settings"]
    population = {
        "engine_version": d["engine_version"],
        "input": d["model"]["input"],
        **{k: settings.get(k) for k in _POPULATION_SETTINGS},
        "true_cases": settings.get("true_cases"),
        "cases": d["population"],
    }
    method = {
        "engine_version": d["engine_version"],
        "settings": settings,
        "model": d["model"],
        "demo": d["demo"],
        "axis_order": list(AXIS_ORDER),
        "pass_marks": {
            "accuracy_floor": _run.ACCURACY_FLOOR,
            "decision_consistency": _run.DCS_THRESHOLD,
            "gap": _run.GAP_THRESHOLD,
            "literacy_language_gap": _run.LFDI_THRESHOLD,
            "social_needs_gap": _run.SAF_THRESHOLD,
            "retention": _run.RETENTION_THRESHOLD,
        },
    }
    results = {
        "overall": d["overall"],
        "axes": d["axes"],
        "model_calls": d["model_calls"],
        "answer_rates": d["answer_rates"],
        "limitations": d["limitations"],
    }
    return {
        "format": FORMAT,
        "population": population,
        "method": method,
        "results": results,
        "chain": {"algorithm": "sha256", **chain(population, method, results)},
    }


def write_report(report: AASTReport, path: str | Path) -> dict[str, Any]:
    """Write the report to ``path``: ``.html`` for people, anything else as JSON.

    Returns the document (with its chain) that was written.
    """
    doc = build_document(report)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() in (".html", ".htm"):
        path.write_text(render_html(doc), encoding="utf-8")
    else:
        path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return doc


def load_document(path: str | Path) -> dict[str, Any]:
    """Read a JSON report document (an HTML report carries the same JSON inside)."""
    path = Path(path)
    if not path.is_file():
        raise ReportFileError(f"report not found: {path}")
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() in (".html", ".htm"):
        start = text.find(_EMBED_OPEN)
        end = text.find(_EMBED_CLOSE, start + 1)
        if start < 0 or end < 0:
            raise ReportFileError(f"{path}: no embedded report data")
        text = text[start + len(_EMBED_OPEN) : end]
    try:
        doc = json.loads(text)
    except ValueError as err:
        raise ReportFileError(f"{path}: not valid JSON ({err})") from err
    if not isinstance(doc, dict) or doc.get("format") != FORMAT:
        raise ReportFileError(f"{path}: not a 7AAST report (expected format {FORMAT!r})")
    return doc


# ------------------------------------------------------------------- verify


@dataclass
class Check:
    name: str
    ok: bool
    detail: str


@dataclass
class Verification:
    checks: list[Check] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(c.ok for c in self.checks)

    def text(self) -> str:
        lines = [f"  [{'ok' if c.ok else 'FAILED':>6}]  {c.name}: {c.detail}" for c in self.checks]
        lines.append("")
        lines.append(
            "VERIFIED: the report is internally consistent."
            if self.ok
            else "NOT VERIFIED: the report has been changed or does not match its cohort."
        )
        return "\n".join(lines)


def _overall(axes: list[dict[str, Any]]) -> str:
    statuses = {a.get("status") for a in axes}
    if FAIL in statuses:
        return FAIL
    if INCONCLUSIVE in statuses:
        return INCONCLUSIVE
    return PASS


def verify(doc: dict[str, Any], *, regenerate: bool = False) -> Verification:
    """Recompute the chain of ``doc``; with ``regenerate`` also rebuild the cohort."""
    out = Verification()
    try:
        expected = chain(doc["population"], doc["method"], doc["results"])
        stored = doc["chain"]
    except (KeyError, TypeError, ValueError) as err:
        out.checks.append(Check("structure", False, f"missing or unreadable section ({err})"))
        return out
    broken = False
    for stage in STAGES:
        same = not broken and stored.get(stage) == expected[stage]
        if same:
            detail = expected[stage]
        elif broken:
            detail = "not checked: an earlier stage differs"
        else:
            detail = f"recomputed {expected[stage][:16]}..., report says {str(stored.get(stage))[:16]}..."
        out.checks.append(Check(f"{stage} hash", same, detail))
        broken = broken or not same

    results = doc["results"]
    overall = _overall(results.get("axes", []))
    out.checks.append(
        Check(
            "overall verdict",
            overall == results.get("overall"),
            f"axes give {overall}, report says {results.get('overall')}",
        )
    )
    if regenerate:
        out.checks.append(_regenerate_check(doc["population"]))
    return out


def _regenerate_check(population: dict[str, Any]) -> Check:
    from hipaasynth.aast.cases import case_id, present
    from hipaasynth.core.config import ENGINE_VERSION
    from hipaasynth.decision_cohort import BALANCED_ETHNICITY_WEIGHTS, build_decision_cohort
    from hipaasynth.sdk import _resolve_profile

    name = "cohort rebuilt from settings"
    if population.get("engine_version") != ENGINE_VERSION:
        return Check(
            name,
            False,
            f"report made with engine {population.get('engine_version')}, this is "
            f"{ENGINE_VERSION}; to rebuild the cohort, install that version "
            f"(pip install 'hipaasynth=={population.get('engine_version')}' or "
            f"git checkout v{population.get('engine_version')}) and verify again. The hash "
            "checks above do not depend on the version",
        )
    try:
        profile = population.get("profile")
        cohort = build_decision_cohort(
            population["condition"],
            population["n"],
            seed=population["seed"],
            prevalence=population["prevalence"],
            population_profile_path=_resolve_profile(profile) if profile else None,
            ethnicity_weights=(
                BALANCED_ETHNICITY_WEIGHTS if population.get("balanced_groups") else None
            ),
        )
        rebuilt = [
            {
                "case_id": case_id(present(c.patient, population["input"])),
                "truth": c.truth,
                "kind": c.kind,
            }
            for c in cohort
        ]
    except (KeyError, TypeError, ValueError, OSError) as err:
        return Check(name, False, f"could not rebuild ({err})")
    cases = population.get("cases", [])
    if rebuilt == cases:
        return Check(name, True, f"all {len(cases)} cases match")
    differ = sum(a != b for a, b in zip(rebuilt, cases, strict=False)) + abs(
        len(rebuilt) - len(cases)
    )
    return Check(name, False, f"{differ} of {len(cases)} cases differ from the rebuilt cohort")


# --------------------------------------------------------------------- HTML

_EMBED_OPEN = '<script type="application/json" id="report-data">'
_EMBED_CLOSE = "</script>"

_CSS = """
:root{--bg:#fff;--fg:#1b1f24;--muted:#57606a;--line:#d0d7de;--card:#f6f8fa;
--pass:#1a7f37;--fail:#cf222e;--inc:#9a6700;--info:#0969da;--na:#6e7781}
@media (prefers-color-scheme:dark){:root{--bg:#0d1117;--fg:#e6edf3;--muted:#9198a1;
--line:#30363d;--card:#161b22;--pass:#3fb950;--fail:#f85149;--inc:#d29922;--info:#58a6ff;
--na:#8b949e}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.5 system-ui,-apple-system,
"Segoe UI",Roboto,sans-serif}
main{max-width:960px;margin:0 auto;padding:24px 16px 48px}
h1{font-size:1.6rem;margin:.2em 0}h2{font-size:1.15rem;margin:1.8em 0 .5em}
.muted{color:var(--muted)}.demo{background:var(--fail);color:#fff;font-weight:700;
padding:10px 16px;text-align:center;letter-spacing:.04em}
.overall>div{flex:1 1 240px}
.overall{display:flex;flex-wrap:wrap;gap:12px 16px;align-items:center;background:var(--card);
border:1px solid var(--line);border-radius:8px;padding:16px;margin:16px 0}
.badge{display:inline-block;font-weight:700;font-size:.8rem;padding:2px 8px;border-radius:12px;
color:#fff;white-space:nowrap}
.big{font-size:1.2rem;padding:6px 14px}
.PASS{background:var(--pass)}.FAIL{background:var(--fail)}.INCONCLUSIVE{background:var(--inc)}
.DESCRIPTIVE{background:var(--info)}.NOT_APPLICABLE{background:var(--na)}
.axis{border:1px solid var(--line);border-radius:8px;padding:12px 16px;margin:10px 0}
.axis h3{margin:0 0 4px;font-size:1rem;display:flex;gap:10px;align-items:center;flex-wrap:wrap}
.axis p{margin:4px 0}
code,.hash{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.85rem;
overflow-wrap:anywhere}
table{border-collapse:collapse;width:100%}td,th{text-align:left;padding:4px 8px;
border-bottom:1px solid var(--line);vertical-align:top}
ul{padding-left:1.2em}li{margin:4px 0}
"""


def _e(value: Any) -> str:
    return html.escape("" if value is None else str(value))


def _pct(part: int, whole: int) -> str:
    return f"{part} of {whole} ({100 * part / whole:.0f}%)" if whole else str(part)


def render_html(doc: dict[str, Any]) -> str:
    """A self-contained HTML page for ``doc`` (no scripts, no external files)."""
    pop, method, results, ch = doc["population"], doc["method"], doc["results"], doc["chain"]
    model, settings = method["model"], method["settings"]
    overall = results["overall"]
    n, true_cases = pop.get("n") or 0, pop.get("true_cases") or 0
    parts = ["<!doctype html><html lang='en'><head><meta charset='utf-8'>",
             "<meta name='viewport' content='width=device-width,initial-scale=1'>",
             f"<title>7AAST report: {_e(model.get('name'))}</title>",
             f"<style>{_CSS}</style></head><body>"]  # fmt: skip
    if method.get("demo"):
        parts.append("<div class='demo'>DEMO MODEL: NOT A CLINICAL TOOL</div>")
    parts.append("<main>")
    parts.append(
        f"<p class='muted'>7-Axis Adversarial Stress Test &middot; HipAAsynth "
        f"{_e(method.get('engine_version'))}</p>"
        f"<h1>{_e(model.get('name'))}: {_e(pop.get('condition'))}</h1>"
        f"<p class='muted'>Model reads {_e(model.get('input'))}, answers "
        f"{_e(model.get('output'))}. {n} synthetic patients: {true_cases} true cases and "
        f"{n - true_cases} look-alike patients who have a different condition with similar "
        f"signs. Seed {_e(pop.get('seed'))}. Every case was shown as it would look at the "
        f"moment of decision, with the answer hidden.</p>"
    )
    parts.append(
        f"<div class='overall'><span class='badge big {_e(overall)}'>{_e(overall)}</span>"
        f"<div>{_e(OVERALL_MEANING.get(overall, ''))}</div></div>"
    )
    parts.append("<h2>The checks</h2><ul class='muted'>")
    parts.extend(
        f"<li><span class='badge {_e(k)}'>{_e(k)}</span> {_e(v)}</li>"
        for k, v in STATUS_MEANING.items()
    )
    parts.append("</ul>")
    for a in results["axes"]:
        status = a.get("status", "")
        label = "" if a.get("axis") == "accuracy" else f"Axis {_e(a.get('axis'))} &middot; "
        parts.append(
            f"<section class='axis'><h3><span class='badge {_e(status)}'>{_e(status)}</span>"
            f"{label}{_e(a.get('name'))}</h3>"
            f"<p class='muted'>{_e(AXIS_QUESTIONS.get(a.get('axis', ''), ''))}</p>"
            f"<p><strong>Result:</strong> {_e(a.get('summary'))}</p>"
        )
        if a.get("reason"):
            parts.append(f"<p class='muted'>Why: {_e(a.get('reason'))}</p>")
        parts.append("</section>")
    rates = results.get("answer_rates", {})
    cases = rates.get("cases", 0)
    parts.append(
        "<h2>Answers</h2><p>"
        f"The model answered {_pct(rates.get('answered', 0), cases)} of the main cases; "
        f"it declined {rates.get('abstained', 0)} and {rates.get('unreadable', 0)} answers "
        f"could not be read. A declined or unreadable answer on a true case counts as a miss. "
        f"Total model calls: {results.get('model_calls')}.</p>"
    )
    parts.append("<h2>Limits of this report</h2><ul>")
    parts.extend(f"<li>{_e(note)}</li>" for note in results.get("limitations", []))
    parts.append(
        "<li>This is a stress-test record on synthetic patients. It is not a certification, "
        "a regulatory clearance or a measure of real-world performance.</li></ul>"
    )
    parts.append("<h2>Settings</h2><table>")
    parts.extend(
        f"<tr><th>{_e(k)}</th><td><code>{_e(v)}</code></td></tr>"
        for k, v in [*settings.items(), *((f"model.{k}", v) for k, v in model.items())]
        if v is not None
    )
    parts.append("</table>")
    parts.append(
        "<h2>Checking this report has not been changed</h2>"
        "<p>Each hash covers the ones above it, so any edit changes the report hash. Keep the "
        "report hash somewhere the report's holder cannot change it, then run "
        "<code>hipaasynth 7aast verify THIS_FILE --regenerate</code> to recompute the chain "
        "and rebuild every case from the seed.</p><table>"
    )
    parts.extend(
        f"<tr><th>{_e(stage)}</th><td class='hash'>{_e(ch.get(stage))}</td></tr>"
        for stage in STAGES
    )
    parts.append("</table></main>")
    data = json.dumps(doc, ensure_ascii=True).replace("<", "\\u003c")
    parts.append(f"{_EMBED_OPEN}{data}{_EMBED_CLOSE}</body></html>")
    return "".join(parts)
