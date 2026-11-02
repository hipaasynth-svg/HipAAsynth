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

"""The 7AAST report page: seal and verdict on page one, then charts and every number.

One self-contained HTML file: inline CSS and SVG, no scripts, no external
files, prints to letter or A4 (and so to PDF). The report document travels
inside it, so ``hipaasynth 7aast verify report.html`` checks the page itself.
Everything shown is read from the document; nothing here changes a hash.
"""

from __future__ import annotations

import html
import json
import math
from typing import Any

from hipaasynth.aast import ots
from hipaasynth.aast.report import (
    _EMBED_CLOSE,
    _EMBED_OPEN,
    AXIS_QUESTIONS,
    OVERALL_MEANING,
    PROVENANCE_FIELDS,
    STAGES,
    STATUS_MEANING,
)
from hipaasynth.aast.stats import FAIL, INCONCLUSIVE, PASS

CONDITION_NAMES = {
    "sepsis": "sepsis",
    "stroke": "stroke",
    "dka": "diabetic ketoacidosis (DKA)",
    "fabry": "Fabry disease",
}

#: Short, plain names for the checks (the report also gives the full name).
PLAIN_NAMES = {
    "accuracy": "Overall accuracy",
    "1": "Same patient, seven different write-ups",
    "2": "Patient-written versus clinician notes",
    "2b": "Fairness across groups",
    "3": "Low-literacy and translated notes",
    "4": "Notes full of social needs",
    "5": "Only race or sex changed",
    "6": "Sites missing some tests",
    "7": "History held by another health system",
}

_ETHNICITY = {
    "asian": "Asian",
    "black": "Black",
    "hispanic": "Hispanic",
    "native": "Am. Indian / Alaska Native",
    "white": "White",
    "pacific": "Pacific Islander",
    "other": "Other race",
}
_DIMENSIONS = {
    "ethnicity": "Race / ethnicity",
    "sex": "Sex",
    "age": "Age",
    "skin_tone": "Skin tone (Monk)",
    "rural": "Rural",
    "insurance": "Insurance",
    "social_needs": "Social needs",
    "language": "Language",
}


def _e(value: Any) -> str:
    return html.escape("" if value is None else str(value))


def _pc(x: float | None, digits: int = 0) -> str:
    return "n/a" if x is None else f"{100 * x:.{digits}f}%"


def plain_name(axis: dict[str, Any]) -> str:
    key = str(axis.get("axis"))
    if key == "2" and "fairness" in str(axis.get("name", "")).lower():
        return PLAIN_NAMES["2b"]
    return PLAIN_NAMES.get(key, str(axis.get("name")))


def group_label(key: str, *, short: bool = False) -> str:
    dim, _, value = key.partition("=")
    if dim == "ethnicity":
        if short and value == "native":
            return "AI/AN"
        return _ETHNICITY.get(value, value.title())
    if dim == "sex":
        return {"female": "Women", "male": "Men"}.get(value, value.title())
    if dim == "age":
        return f"Age {value}"
    if dim == "skin_tone":
        v = value.replace("monk_", "")
        return f"Tone {v}" if short else f"Monk skin tone {v}"
    if dim == "rural":
        return {"yes": "Rural", "no": "Not rural"}.get(value, value)
    if dim == "social_needs":
        return f"{value.title()} needs" if short else f"{value.title()} social needs"
    if dim == "insurance":
        return value.title()
    return f"{value.replace('_', ' ').title()}" if short else f"{dim}: {value}"


def _axes(doc: dict[str, Any]) -> list[dict[str, Any]]:
    return list(doc["results"].get("axes", []))


def _axis(doc: dict[str, Any], key: str) -> dict[str, Any] | None:
    return next((a for a in _axes(doc) if a.get("axis") == key), None)


def _group_axis(doc: dict[str, Any]) -> dict[str, Any] | None:
    return next((a for a in _axes(doc) if "groups" in (a.get("metrics") or {})), None)


# ------------------------------------------------------------- plain English


def plain_english(doc: dict[str, Any]) -> list[str | list[str]]:
    """How the model did, in sentences a non-statistician can act on.

    Each item is a paragraph, or a list of bullet points.
    """
    pop, results = doc["population"], doc["results"]
    model = doc["method"]["model"].get("name") or "The model"
    cond = CONDITION_NAMES.get(str(pop.get("condition")), str(pop.get("condition")))
    n, t = int(pop.get("n") or 0), int(pop.get("true_cases") or 0)
    out: list[str | list[str]] = [
        f"{model} was tested on {n} synthetic patients: {t} who have {cond} and {n - t} "
        f"look-alike patients who have something else with similar signs. Each case was shown "
        f"the way it looks at the moment of decision, with the answer hidden."
    ]
    acc = _axis(doc, "accuracy")
    if acc:
        m = acc.get("metrics") or {}
        missed = int(m.get("missed_true_cases") or 0)
        alarms = int(m.get("false_alarms") or 0)
        sens = (m.get("sensitivity") or {}).get("estimate")
        text = f"It caught {t - missed} of {t} true cases ({_pc(sens)})"
        if missed:
            text += f", so it missed {missed}"
        text += f", and raised a false alarm on {alarms} of {n - t} look-alike patients."
        out.append(text)
    failed = [a for a in _axes(doc) if a.get("status") == FAIL]
    if failed:
        out.append(f"It failed {len(failed)} check{'s' if len(failed) > 1 else ''}:")
        out.append([f"{plain_name(a)}: {a.get('summary')}" for a in failed])
    worst = _worst_group(doc)
    if worst:
        key, g = worst
        gap = (g.get("gap_vs_rest") or {}).get("estimate") or 0.0
        if gap > 0.0:
            out.append(
                f"Missed cases were most common in one group ({group_label(key)}): "
                f"{_pc(g.get('miss_rate'))} of its {g.get('true_cases')} true cases were "
                f"missed, {100 * gap:.0f} points more than everyone else."
            )
    undecided = [a for a in _axes(doc) if a.get("status") == INCONCLUSIVE]
    if undecided:
        names = ", ".join(plain_name(a).lower() for a in undecided)
        out.append(
            f"These could not be decided with {n} patients: {names}. A larger run narrows the "
            "ranges and may settle them."
        )
    overall = results.get("overall")
    if overall == FAIL:
        out.append(
            "Bottom line: on these patients the model did measurably worse than the pass mark. "
            "Do not rely on it for the patients these checks describe until the failures are "
            "fixed and the model is re-tested and validated on local data."
        )
    elif overall == PASS:
        out.append(
            "Bottom line: it passed every check with a pass mark. This is a stress test on "
            "synthetic patients, so still validate the model on local data before use."
        )
    else:
        out.append(
            "Bottom line: nothing failed, but the result is not settled. Run it again with more "
            "patients before drawing a conclusion."
        )
    return out


def _worst_group(doc: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    axis = _group_axis(doc)
    if not axis:
        return None
    groups = (axis.get("metrics") or {}).get("groups") or {}
    judged = [(k, g) for k, g in groups.items() if (g.get("true_cases") or 0) >= 3]
    if not judged:
        return None
    return max(judged, key=lambda kg: (kg[1].get("gap_vs_rest") or {}).get("estimate") or 0.0)


# ------------------------------------------------------------------ charts

_W = 760
_LABEL = 250
_PLOT0, _PLOT1 = _LABEL + 10, _W - 70
_ROW = 28


def _x(v: float, lo: float, hi: float) -> float:
    v = min(max(v, lo), hi)
    return _PLOT0 + (v - lo) / (hi - lo) * (_PLOT1 - _PLOT0)


def interval_chart(
    title: str,
    rows: list[dict[str, Any]],
    *,
    lo: float = 0.0,
    hi: float = 1.0,
    note: str = "",
) -> str:
    """Dots with 95% interval bars; each row may carry its own pass mark.

    ``rows``: ``{"label", "estimate", "low", "high", "status", "threshold"?}``.
    """
    rows = [r for r in rows if r.get("estimate") is not None]
    if not rows:
        return ""
    height = 34 + _ROW * len(rows) + 22
    ticks = [lo + (hi - lo) * i / 4 for i in range(5)]
    parts = [
        f"<figure class='chart'><figcaption>{_e(title)}</figcaption>"
        f"<svg viewBox='0 0 {_W} {height}' role='img' aria-label='{_e(title)}'>"
    ]
    for tv in ticks:
        x = _x(tv, lo, hi)
        parts.append(
            f"<line class='grid' x1='{x:.1f}' x2='{x:.1f}' y1='24' y2='{height - 22}'/>"
            f"<text class='tick' x='{x:.1f}' y='{height - 6}' text-anchor='middle'>"
            f"{100 * tv:.0f}%</text>"
        )
    if lo < 0 < hi:
        x = _x(0.0, lo, hi)
        parts.append(f"<line class='zero' x1='{x:.1f}' x2='{x:.1f}' y1='24' y2='{height - 22}'/>")
    for i, r in enumerate(rows):
        y = 34 + _ROW * i + _ROW / 2
        status = _e(r.get("status") or "")
        est, low, high = r["estimate"], r.get("low", r["estimate"]), r.get("high", r["estimate"])
        parts.append(
            f"<text class='label' x='{_LABEL}' y='{y + 4:.1f}' text-anchor='end'>"
            f"{_e(r['label'])}</text>"
        )
        for th in r.get("thresholds") or (
            [r["threshold"]] if r.get("threshold") is not None else []
        ):
            x = _x(th, lo, hi)
            parts.append(
                f"<line class='mark' x1='{x:.1f}' x2='{x:.1f}' y1='{y - 11:.1f}' y2='{y + 11:.1f}'/>"
            )
        parts.append(
            f"<line class='ci s-{status}' x1='{_x(low, lo, hi):.1f}' x2='{_x(high, lo, hi):.1f}' "
            f"y1='{y:.1f}' y2='{y:.1f}'/>"
            f"<circle class='dot s-{status}' cx='{_x(est, lo, hi):.1f}' cy='{y:.1f}' r='5.5'/>"
            f"<text class='val' x='{_PLOT1 + 8}' y='{y + 4:.1f}'>{round(100 * est) or 0}%</text>"
        )
    parts.append(
        f"<text class='tick' x='{_PLOT0}' y='14'>dot = result, bar = 95% range, "
        f"tall line = pass mark</text></svg>"
    )
    if note:
        parts.append(f"<p class='note'>{_e(note)}</p>")
    parts.append("</figure>")
    return "".join(parts)


def _heat(rate: float) -> tuple[str, str]:
    """Fill and text colour for a share of the scale (0 = pale, 1 = deep red)."""
    stops = [(0.0, (240, 246, 252)), (0.25, (253, 208, 162)), (0.5, (241, 105, 19)),
             (1.0, (127, 39, 4))]  # fmt: skip
    rate = min(max(rate, 0.0), 1.0)
    for (a, ca), (b, cb) in zip(stops, stops[1:], strict=False):
        if rate <= b:
            f = (rate - a) / (b - a) if b > a else 0.0
            rgb = tuple(round(ca[i] + (cb[i] - ca[i]) * f) for i in range(3))
            return f"rgb{rgb}", "#fff" if rate > 0.42 else "#1b1f24"
    return "rgb(127,39,4)", "#fff"


def heatmap(doc: dict[str, Any]) -> str:
    """Share of true cases missed, by group: one row per dimension."""
    axis = _group_axis(doc)
    if not axis:
        return ""
    groups = (axis.get("metrics") or {}).get("groups") or {}
    by_dim: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    for key, g in sorted(groups.items()):
        by_dim.setdefault(key.partition("=")[0], []).append((key, g))
    order = [d for d in _DIMENSIONS if d in by_dim] + [d for d in by_dim if d not in _DIMENSIONS]
    cols = max(len(v) for v in by_dim.values())
    # Scale the colours to the data (at least 0-20%), so small gaps still show.
    top = min(1.0, max(0.2, math.ceil(max(float(g.get("miss_rate") or 0) for g in groups.values())
                                      * 10) / 10))  # fmt: skip
    label_w, cell_w, cell_h = 150, min(120, (_W - 150) // cols), 46
    width = label_w + cell_w * cols
    height = 18 + cell_h * len(order) + 30
    parts = [
        "<figure class='chart'><figcaption>Missed true cases by group (heatmap)</figcaption>"
        f"<svg viewBox='0 0 {width} {height}' role='img' "
        "aria-label='Share of true cases missed in each group'>"
    ]
    for r, dim in enumerate(order):
        y = 18 + cell_h * r
        parts.append(
            f"<text class='label' x='{label_w - 8}' y='{y + cell_h / 2 + 4:.0f}' "
            f"text-anchor='end'>{_e(_DIMENSIONS.get(dim, dim))}</text>"
        )
        for c, (key, g) in enumerate(by_dim[dim]):
            x = label_w + cell_w * c
            rate = float(g.get("miss_rate") or 0.0)
            fill, ink = _heat(rate / top)
            few = (g.get("true_cases") or 0) < 5
            parts.append(
                f"<rect x='{x + 2}' y='{y + 2}' width='{cell_w - 4}' height='{cell_h - 4}' rx='4' "
                f"fill='{fill}' class='{'few' if few else ''}'/>"
                f"<text x='{x + cell_w / 2:.0f}' y='{y + 19}' text-anchor='middle' "
                f"style='fill:{ink}' class='cell'>{_e(group_label(key, short=True))}</text>"
                f"<text x='{x + cell_w / 2:.0f}' y='{y + 35}' text-anchor='middle' style='fill:{ink}' "
                f"class='cellv'>{100 * rate:.0f}% of {_e(g.get('true_cases'))}</text>"
            )
    ly = height - 14
    for i in range(6):
        fill, _ = _heat(i / 5)
        parts.append(f"<rect x='{label_w + i * 34}' y='{ly - 10}' width='34' height='12' "
                     f"fill='{fill}'/>")  # fmt: skip
    parts.append(
        f"<text class='tick' x='{label_w - 8}' y='{ly}' text-anchor='end'>0% missed</text>"
        f"<text class='tick' x='{label_w + 6 * 34 + 6}' y='{ly}'>{100 * top:.0f}% missed or more "
        "&#183; dashed "
        "border: fewer than 5 true cases</text></svg>"
        "<p class='note'>Each cell: the share of that group's true cases the model missed, and "
        "how many true cases the group had. Deeper red is worse; the colour scale runs from "
        f"0% to {100 * top:.0f}% missed.</p></figure>"
    )
    return "".join(parts)


def _ci(m: dict[str, Any] | None) -> dict[str, Any]:
    m = m or {}
    return {"estimate": m.get("estimate"), "low": m.get("low"), "high": m.get("high")}


def charts(doc: dict[str, Any]) -> list[str]:
    out = []
    acc = _axis(doc, "accuracy")
    if acc:
        m = acc.get("metrics") or {}
        rows = [
            {"label": "True cases caught (sensitivity)", **_ci(m.get("sensitivity")),
             "status": acc.get("status")},
            {"label": "Look-alikes cleared (specificity)", **_ci(m.get("specificity")),
             "status": acc.get("status")},
            {"label": "Balanced accuracy", **_ci(m.get("interval")),
             "status": acc.get("status"), "threshold": m.get("threshold")},
        ]  # fmt: skip
        for name, ci in (m.get("sensitivity_by_presentation") or {}).items():
            rows.append({"label": f"Caught: {name.replace('_', ' ')}", **_ci(ci),
                         "status": "DESCRIPTIVE"})  # fmt: skip
        out.append(interval_chart("Accuracy", rows))
    gaxis = _group_axis(doc)
    if gaxis:
        out.append(heatmap(doc))
        groups = (gaxis.get("metrics") or {}).get("groups") or {}
        th = (gaxis.get("metrics") or {}).get("threshold") or 0.15
        rows = [
            {"label": group_label(k), **_ci(g.get("gap_vs_rest")), "status": g.get("status"),
             "thresholds": [-th, th]}
            for k, g in sorted(groups.items())
        ]  # fmt: skip
        out.append(interval_chart(
            "Each group's miss rate minus everyone else's", rows, lo=-1.0, hi=1.0,
            note=f"Right of zero: the model misses more true cases in that group. The pass "
                 f"band is plus or minus {100 * th:.0f} points."))  # fmt: skip
    forms = [a for a in _axes(doc) if a.get("axis") in ("1", "2", "3", "4")
             and "interval" in (a.get("metrics") or {})]  # fmt: skip
    if forms:
        rows = [{"label": plain_name(a), **_ci(a["metrics"]["interval"]), "status": a.get("status"),
                 "threshold": a["metrics"].get("threshold")} for a in forms]  # fmt: skip
        out.append(interval_chart(
            "Written forms (Axes 1-4)", rows,
            note="Consistency (top) should be above its mark; the gaps should be below theirs."))  # fmt: skip
    twins = _axis(doc, "5")
    if twins and twins.get("metrics"):
        m = twins["metrics"]
        tol = m.get("tolerance")
        rows = []
        for key, label in (("ethnicity", "Race changed"), ("sex", "Sex changed")):
            if m.get(key):
                rows.append({"label": label, **_ci(m[key].get("flip_rate")),
                             "status": twins.get("status"), "threshold": tol})  # fmt: skip
        if m.get("noise_floor"):
            rows.append({"label": "Same case re-run", **_ci(m["noise_floor"].get("rate")),
                         "status": "DESCRIPTIVE"})  # fmt: skip
        if m.get("control"):
            rows.append({"label": "Irrelevant detail changed", **_ci(m["control"].get("flip_rate")),
                         "status": "DESCRIPTIVE"})  # fmt: skip
        out.append(interval_chart(
            "Answers that flipped (Axis 5)", rows,
            hi=max(0.2, math.ceil(max((r.get("high") or 0) for r in rows) * 5) / 5) if rows else 0.2,
            note="Race or sex alone should not flip more answers than re-running or an irrelevant "
                 "edit does."))  # fmt: skip
    rows = []
    s6 = _axis(doc, "6")
    if s6 and s6.get("metrics"):
        for key, label in (("critical_access", "Critical access hospital"), ("clinic", "Clinic")):
            sm = s6["metrics"].get(key)
            if sm:
                rows.append({"label": label, **_ci(sm.get("interval")), "status": sm.get("status"),
                             "threshold": sm.get("threshold")})  # fmt: skip
    s7 = _axis(doc, "7")
    if s7 and (s7.get("metrics") or {}).get("interval"):
        rows.append({"label": "History held elsewhere", **_ci(s7["metrics"]["interval"]),
                     "status": s7.get("status"), "threshold": s7["metrics"].get("threshold")})  # fmt: skip
    if rows:
        out.append(interval_chart(
            "Share of catches kept when information is missing (Axes 6-7)", rows, hi=1.0,
            note="100% means it catches as many true cases as with full hospital information."))  # fmt: skip
    return [c for c in out if c]


# --------------------------------------------------------------- tables


def _flatten(prefix: str, value: Any, out: list[tuple[str, str]]) -> None:
    if isinstance(value, dict):
        if set(value) >= {"estimate", "low", "high"}:
            out.append((prefix, f"{value['estimate']} [{value['low']}, {value['high']}]"))
            return
        for k, v in value.items():
            _flatten(f"{prefix}.{k}" if prefix else str(k), v, out)
    else:
        out.append((prefix, json.dumps(value) if not isinstance(value, str) else value))


def metrics_table(axis: dict[str, Any]) -> str:
    rows: list[tuple[str, str]] = []
    _flatten("", axis.get("metrics") or {}, rows)
    if not rows:
        return ""
    body = "".join(f"<tr><th>{_e(k)}</th><td><code>{_e(v)}</code></td></tr>" for k, v in rows)
    return f"<table class='metrics'>{body}</table>"


# --------------------------------------------------------------- the seal


def _hash_lines(h: str) -> str:
    return "<br>".join(_e(h[i : i + 32]) for i in range(0, len(h), 32))


def seal_box(doc: dict[str, Any], outer: dict[str, Any] | None = None) -> str:
    """The seal panel; for a comparison, ``outer`` gives the pair's hash and seal."""
    method, pop, ch = doc["method"], doc["population"], doc["chain"]
    prov = method.get("provenance") or {}
    model = method["model"]
    seal = doc.get("seal") or {}
    if outer is not None:
        ch, seal = outer["chain"], outer.get("seal") or {}
    rows: list[tuple[str, str]] = [
        ("Model", _e(model.get("name"))),
        ("Model version", _e(prov.get("model_version") or "not given")),
        ("Condition", _e(CONDITION_NAMES.get(pop.get("condition"), pop.get("condition")))),
        ("Reads / answers", f"{_e(model.get('input'))} / {_e(model.get('output'))}"),
    ]
    for key in ("run_by", "organization", "intended_use", "scenario"):
        if prov.get(key):
            rows.append((PROVENANCE_FIELDS[key], _e(prov[key])))
    if prov.get("transcript_sha256"):
        rows.append(("Transcript", f"<span class='hash'>{_hash_lines(prov['transcript_sha256'])}"
                                   "</span> (SHA-256 of every question and answer)"))  # fmt: skip
    if prov.get("started_utc"):
        rows.append(("Test run", f"{_e(prov['started_utc'])} to {_e(prov.get('finished_utc'))} "
                                 "(UTC, recorded by the tool)"))  # fmt: skip
    rows.append(("Engine", _e(prov.get("tool") or f"HipAAsynth {method.get('engine_version')}")))
    rows.append(("Report hash", f"<span class='hash'>{_hash_lines(str(ch.get('report')))}</span>"))
    sig = seal.get("signature")
    if sig:
        who = ", ".join(x for x in (sig.get("signer"), sig.get("organization")) if x)
        rows.append(("Signed", f"Ed25519 key <span class='hash'>{_e(sig.get('fingerprint'))}</span>"
                               + (f" ({_e(who)})" if who else "")))  # fmt: skip
    else:
        rows.append(("Signed", "not signed"))
    stamp = seal.get("opentimestamps")
    if stamp:
        try:
            pi = ots.info(ots.decode(stamp["proof"]))
            if pi.bitcoin:
                text = f"anchored in Bitcoin block {pi.bitcoin[0][0]}"
            else:
                text = (f"submitted {_e(stamp.get('submitted_utc'))} to {len(pi.pending)} "
                        "OpenTimestamps calendar(s); Bitcoin proof follows within hours")  # fmt: skip
        except (ots.OTSError, KeyError, TypeError):
            text = "unreadable timestamp proof"
        rows.append(("Timestamp", text))
    else:
        rows.append(("Timestamp", "not timestamped"))
    body = "".join(f"<tr><th>{k}</th><td>{v}</td></tr>" for k, v in rows)
    return (
        "<section class='seal'><div class='seal-head'><span class='seal-mark'>&#9741;</span>"
        "<div><strong>Sealed test record</strong><br><span class='muted'>Everything below is "
        "covered by the report hash; the signature and timestamp cover the hash.</span></div>"
        f"</div><table>{body}</table><p class='note'>This page states what the report says. To "
        "check it, run <code>hipaasynth 7aast verify THIS_FILE --bitcoin</code>, or upload the "
        "two timestamp files from the 7AAST page at opentimestamps.org.</p></section>"
    )


# ----------------------------------------------------------------- CSS

_CSS = """
:root{--bg:#fff;--fg:#1b1f24;--muted:#57606a;--line:#d0d7de;--card:#f6f8fa;
--pass:#1a7f37;--fail:#cf222e;--inc:#9a6700;--info:#0969da;--na:#6e7781;--seal:#0b3d91}
@media (prefers-color-scheme:dark){:root{--bg:#0d1117;--fg:#e6edf3;--muted:#9198a1;
--line:#30363d;--card:#161b22;--pass:#3fb950;--fail:#f85149;--inc:#d29922;--info:#58a6ff;
--na:#8b949e;--seal:#79c0ff}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,-apple-system,
"Segoe UI",Roboto,sans-serif}
main{max-width:960px;margin:0 auto;padding:24px 16px 48px}
h1{font-size:1.5rem;margin:.2em 0}h2{font-size:1.15rem;margin:1.6em 0 .5em}
.muted{color:var(--muted)}.note{color:var(--muted);font-size:.85rem;margin:4px 0}
.demo{background:var(--fail);color:#fff;font-weight:700;padding:10px 16px;text-align:center;
letter-spacing:.04em}
.seal{border:2px solid var(--seal);border-radius:10px;padding:12px 16px;margin:14px 0}
.seal-head{display:flex;gap:12px;align-items:center;margin-bottom:6px}
.seal-mark{font-size:1.8rem;color:var(--seal);line-height:1}
.seal th{width:150px;color:var(--muted);font-weight:600}
.overall{display:flex;flex-wrap:wrap;gap:12px 16px;align-items:center;background:var(--card);
border:1px solid var(--line);border-radius:8px;padding:14px 16px;margin:14px 0}
.overall>div{flex:1 1 240px}
.plain p{margin:6px 0}
.badge{display:inline-block;font-weight:700;font-size:.78rem;padding:2px 8px;border-radius:12px;
color:#fff;white-space:nowrap}
.big{font-size:1.2rem;padding:6px 14px}
.PASS{background:var(--pass)}.FAIL{background:var(--fail)}.INCONCLUSIVE{background:var(--inc)}
.DESCRIPTIVE{background:var(--info)}.NOT_APPLICABLE{background:var(--na)}
.axis{border:1px solid var(--line);border-radius:8px;padding:10px 14px;margin:10px 0;
break-inside:avoid}
.axis h3{margin:0 0 4px;font-size:1rem;display:flex;gap:10px;align-items:center;flex-wrap:wrap}
.axis p{margin:4px 0}
code,.hash{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.82rem;
overflow-wrap:anywhere}
table{border-collapse:collapse;width:100%}td,th{text-align:left;padding:4px 8px;
border-bottom:1px solid var(--line);vertical-align:top}
.metrics{font-size:.85rem;margin-top:6px}.metrics th{font-weight:400;color:var(--muted)}
ul{padding-left:1.2em}li{margin:4px 0}
.score td:first-child{white-space:nowrap}
figure.chart{margin:14px 0;break-inside:avoid}
figcaption{font-weight:600;margin-bottom:4px}
svg{width:100%;height:auto;display:block}
svg text{font:13px system-ui,sans-serif;fill:var(--fg)}
svg .tick{font-size:11px;fill:var(--muted)}svg .val{font-size:12px;font-weight:600}
svg .cell{font-size:12px;font-weight:600}svg .cellv{font-size:11px}
svg .grid{stroke:var(--line);stroke-width:1}svg .zero{stroke:var(--muted);stroke-width:1.5}
svg .mark{stroke:var(--fg);stroke-width:2;stroke-dasharray:3 2}
svg .ci{stroke-width:3;stroke-linecap:round}
svg rect.few{stroke:var(--fg);stroke-dasharray:4 3;stroke-width:1.5}
.s-PASS{stroke:var(--pass);fill:var(--pass)}.s-FAIL{stroke:var(--fail);fill:var(--fail)}
.s-INCONCLUSIVE{stroke:var(--inc);fill:var(--inc)}.s-DESCRIPTIVE,.s-{stroke:var(--info);
fill:var(--info)}.s-NOT_APPLICABLE{stroke:var(--na);fill:var(--na)}
line.ci{fill:none}
.page{break-before:page}
@page{size:auto;margin:14mm}
@media print{
:root{--bg:#fff;--fg:#1b1f24;--muted:#57606a;--line:#d0d7de;--card:#f6f8fa;--pass:#1a7f37;
--fail:#cf222e;--inc:#9a6700;--info:#0969da;--na:#6e7781;--seal:#0b3d91}
*{-webkit-print-color-adjust:exact;print-color-adjust:exact}
body{font-size:12px}main{max-width:none;padding:0}h2{margin-top:1em}
.seal,.overall,figure.chart,.axis,table{break-inside:avoid}
}
"""


# ------------------------------------------------------------------ page


def render_page(doc: dict[str, Any]) -> str:
    pop, method, results, ch = doc["population"], doc["method"], doc["results"], doc["chain"]
    model, settings = method["model"], method["settings"]
    prov = method.get("provenance") or {}
    overall = results["overall"]
    n, true_cases = pop.get("n") or 0, pop.get("true_cases") or 0
    cond = CONDITION_NAMES.get(pop.get("condition"), pop.get("condition"))
    p = ["<!doctype html><html lang='en'><head><meta charset='utf-8'>",
         "<meta name='viewport' content='width=device-width,initial-scale=1'>",
         f"<title>7AAST report: {_e(model.get('name'))}</title>",
         f"<style>{_CSS}</style></head><body>"]  # fmt: skip
    if method.get("demo"):
        p.append("<div class='demo'>DEMO MODEL: NOT A CLINICAL TOOL</div>")
    p.append("<main>")
    # ---- page one: who, what, the seal, the verdict, plain English, scorecard
    p.append(
        f"<p class='muted'>7-Axis Adversarial Stress Test &middot; HipAAsynth "
        f"{_e(method.get('engine_version'))}"
        + (f" &middot; {_e(prov['started_utc'][:10])}" if prov.get("started_utc") else "")
        + f"</p><h1>{_e(model.get('name'))}"
        + (f" {_e(prov['model_version'])}" if prov.get("model_version") else "")
        + f": {_e(cond)}</h1>"
    )
    p.append(seal_box(doc))
    p.append(
        f"<div class='overall'><span class='badge big {_e(overall)}'>{_e(overall)}</span>"
        f"<div>{_e(OVERALL_MEANING.get(overall, ''))}</div></div>"
    )
    p.append("<section class='plain'><h2>How the model did, in plain English</h2>")
    for item in plain_english(doc):
        if isinstance(item, list):
            p.append("<ul>" + "".join(f"<li>{_e(x)}</li>" for x in item) + "</ul>")
        else:
            p.append(f"<p>{_e(item)}</p>")
    p.append("</section>")
    p.append("<h2>Scorecard</h2><table class='score'><tr><th>Result</th><th>Check</th>"
             "<th>What was found</th></tr>")  # fmt: skip
    for a in results["axes"]:
        p.append(
            f"<tr><td><span class='badge {_e(a.get('status'))}'>{_e(a.get('status'))}</span></td>"
            f"<td>{_e(plain_name(a))}</td><td>{_e(a.get('summary'))}</td></tr>"
        )
    p.append("</table>")
    # ---- charts
    figs = charts(doc)
    if figs:
        p.append("<section class='page'><h2>Charts</h2>")
        p.extend(figs)
        p.append("</section>")
    # ---- each check in full, with every number
    p.append("<section class='page'><h2>Each check in full</h2><ul class='muted'>")
    p.extend(f"<li><span class='badge {_e(k)}'>{_e(k)}</span> {_e(v)}</li>"
             for k, v in STATUS_MEANING.items())  # fmt: skip
    p.append("</ul>")
    for a in results["axes"]:
        status = a.get("status", "")
        label = "" if a.get("axis") == "accuracy" else f"Axis {_e(a.get('axis'))} &middot; "
        p.append(
            f"<section class='axis'><h3><span class='badge {_e(status)}'>{_e(status)}</span>"
            f"{label}{_e(a.get('name'))}</h3>"
            f"<p class='muted'>{_e(AXIS_QUESTIONS.get(a.get('axis', ''), ''))}</p>"
            f"<p><strong>Result:</strong> {_e(a.get('summary'))}</p>"
        )
        if a.get("reason"):
            p.append(f"<p class='muted'>Why: {_e(a.get('reason'))}</p>")
        p.append(metrics_table(a))
        p.append("</section>")
    p.append("</section>")
    rates = results.get("answer_rates", {})
    cases = rates.get("cases", 0)
    answered = rates.get("answered", 0)
    p.append(
        "<h2>Answers</h2><p>"
        f"The model answered {answered} of {cases} main cases"
        + (f" ({100 * answered / cases:.0f}%)" if cases else "")
        + f"; it declined {rates.get('abstained', 0)} and {rates.get('unreadable', 0)} answers "
        "could not be read. A declined or unreadable answer on a true case counts as a miss. "
        f"Total model calls: {results.get('model_calls')}. Cohort: {n} patients, {true_cases} "
        f"true cases, seed {_e(pop.get('seed'))}.</p>"
    )
    p.append("<h2>Limits of this report</h2><ul>")
    p.extend(f"<li>{_e(note)}</li>" for note in results.get("limitations", []))
    p.append(
        "<li>This is a stress-test record on synthetic patients. It is not a certification, "
        "a regulatory clearance or a measure of real-world performance.</li></ul>"
    )
    p.append("<h2>Settings</h2><table>")
    p.extend(
        f"<tr><th>{_e(k)}</th><td><code>{_e(v)}</code></td></tr>"
        for k, v in [*settings.items(), *((f"model.{k}", v) for k, v in model.items()),
                     *((f"provenance.{k}", v) for k, v in prov.items())]
        if v is not None
    )  # fmt: skip
    p.append("</table>")
    p.append(
        "<h2>Checking this report</h2>"
        "<p>Each hash covers the ones above it, so any edit changes the report hash. The "
        "signature (if any) is over the report hash with the key shown on page one; the "
        "timestamp (if any) proves the report hash existed by the Bitcoin block's time. Run "
        "<code>hipaasynth 7aast verify THIS_FILE --regenerate --bitcoin</code> to recompute the "
        "chain, rebuild every case from the seed, and check the signature and the timestamp."
        "</p><table>"
    )
    p.extend(
        f"<tr><th>{_e(stage)}</th><td class='hash'>{_e(ch.get(stage))}</td></tr>"
        for stage in STAGES
    )
    p.append("</table></main>")
    data = json.dumps(doc, ensure_ascii=True).replace("<", "\\u003c")
    p.append(f"{_EMBED_OPEN}{data}{_EMBED_CLOSE}</body></html>")
    return "".join(p)


# -------------------------------------------------------------- comparison

FINDING = {
    "WORSE": ("FAIL", "Worse for these patients"),
    "NO_CLEAR_GAP": ("INCONCLUSIVE", "No clear gap at this size"),
    "BETTER": ("PASS", "Better for these patients"),
}


def render_comparison(doc: dict[str, Any]) -> str:
    """The page for a paired run: scenario patients against the US baseline."""
    from hipaasynth.aast.compare import plain_english as compare_english

    target, baseline, comp = doc["target"], doc["baseline"], doc["comparison"]
    model = target["method"]["model"]
    cond = CONDITION_NAMES.get(target["population"]["condition"],
                               target["population"]["condition"])  # fmt: skip
    who = comp.get("target_label") or comp.get("target_profile")
    badge, meaning = FINDING.get(comp["sensitivity_finding"], ("INCONCLUSIVE", ""))
    p = ["<!doctype html><html lang='en'><head><meta charset='utf-8'>",
         "<meta name='viewport' content='width=device-width,initial-scale=1'>",
         f"<title>7AAST comparison: {_e(model.get('name'))}</title>",
         f"<style>{_CSS}</style></head><body>"]  # fmt: skip
    if target["method"].get("demo"):
        p.append("<div class='demo'>DEMO MODEL: NOT A CLINICAL TOOL</div>")
    p.append(
        "<main><p class='muted'>7AAST paired comparison &middot; HipAAsynth "
        f"{_e(target['method'].get('engine_version'))}</p>"
        f"<h1>{_e(model.get('name'))}: {_e(cond)}, {_e(who)} patients vs the US baseline</h1>"
    )
    p.append(seal_box(target, outer=doc))
    p.append(
        f"<div class='overall'><span class='badge big {badge}'>{_e(meaning)}</span>"
        f"<div>{_e(compare_english(comp, cond))}</div></div>"
    )
    rows = [
        {"label": r["metric"], **r["difference"],
         "status": badge if r["key"] == "sensitivity" else "DESCRIPTIVE"}
        for r in comp["rows"]
    ]  # fmt: skip
    p.append(interval_chart(
        f"{who} minus US baseline", rows, lo=-0.5, hi=0.5,
        note="Left of zero: worse for these patients. Bars are 95% ranges."))  # fmt: skip
    p.append("<h2>Side by side</h2><table class='score'><tr><th>Measure</th>"
             f"<th>{_e(who)}</th><th>US baseline</th><th>Difference</th></tr>")  # fmt: skip
    for r in comp["rows"]:
        d = r["difference"]
        p.append(
            f"<tr><td>{_e(r['metric'])}</td>"
            f"<td>{_pc(r['target'])} ({r['target_counts'][0]} of {r['target_counts'][1]})</td>"
            f"<td>{_pc(r['baseline'])} ({r['baseline_counts'][0]} of {r['baseline_counts'][1]})"
            f"</td><td>{100 * d['estimate']:+.0f} points [{100 * d['low']:+.0f}, "
            f"{100 * d['high']:+.0f}]</td></tr>"
        )
    for c in comp["checks"]:
        if c["axis"] == "accuracy":
            continue
        diff = c["difference"]
        p.append(
            f"<tr><td>{_e(plain_name(c))}</td>"
            f"<td><span class='badge {_e(c['target_status'])}'>{_e(c['target_status'])}</span>"
            f" {_pc(c['target_estimate'])}</td>"
            f"<td><span class='badge {_e(c['baseline_status'])}'>{_e(c['baseline_status'])}"
            f"</span> {_pc(c['baseline_estimate'])}</td>"
            f"<td>{'' if diff is None else f'{100 * diff:+.0f} points'}</td></tr>"
        )
    p.append("</table>")
    p.append(f"<p class='note'>{_e(comp['method'])} Both runs used the same model, settings, "
             "seed and size; only the population profile differs.</p>")  # fmt: skip
    for title, inner in ((f"{who} patients", target), ("US baseline", baseline)):
        overall = inner["results"]["overall"]
        p.append(f"<section class='page'><h2>The {_e(title)} run</h2>"
                 f"<div class='overall'><span class='badge big {_e(overall)}'>{_e(overall)}"
                 f"</span><div>{_e(OVERALL_MEANING.get(overall, ''))}</div></div>")  # fmt: skip
        for item in plain_english(inner):
            if isinstance(item, list):
                p.append("<ul>" + "".join(f"<li>{_e(x)}</li>" for x in item) + "</ul>")
            else:
                p.append(f"<p>{_e(item)}</p>")
        p.extend(charts(inner))
        p.append(f"<p class='note'>Report hash {_e(inner['chain']['report'])}. The full report "
                 "is inside this file; save it on its own from the 7AAST page.</p></section>")  # fmt: skip
    p.append(
        "<h2>Checking this comparison</h2><p>Run <code>hipaasynth 7aast verify THIS_FILE "
        "--regenerate --bitcoin</code>: it checks both reports, recomputes the comparison and "
        "checks the seal.</p><table>"
    )
    p.extend(f"<tr><th>{k}</th><td class='hash'>{_e(doc['chain'].get(k))}</td></tr>"
             for k in ("target", "baseline", "comparison", "report"))  # fmt: skip
    p.append("<tr><th colspan='2'>Limits</th></tr>")
    p.extend(f"<tr><td colspan='2'>{_e(n)}</td></tr>" for n in target["results"]["limitations"])
    p.append("</table></main>")
    data = json.dumps(doc, ensure_ascii=True).replace("<", "\\u003c")
    p.append(f"{_EMBED_OPEN}{data}{_EMBED_CLOSE}</body></html>")
    return "".join(p)
