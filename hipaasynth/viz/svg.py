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

"""Hand-rolled SVG visualizations — population distribution + fairness heatmap.

**Stdlib-only, no charting library (flagged like Tier 1's pyarrow choice).** The
engine core stays pure standard library, so these charts are assembled as plain
SVG strings rather than pulling in matplotlib/plotly/d3. The shapes here (grouped
horizontal bars, a coloured grid) are simple enough that hand-rolled SVG is honest
and readable; a charting dependency would buy nothing for this and would break the
"stdlib-only core" value. The output is a self-contained ``<svg>…</svg>`` string
that embeds directly in the web UI or writes to a ``.svg`` file.

Two visualizations:
  * :func:`demographics_distribution_svg` — age / sex / ethnicity distribution of a
    generated cohort (from ``Patient.demographics`` alone; no new data plumbing).
  * :func:`fairness_heatmap_svg` — a per-form error-rate heatmap across the seven
    polymorphic forms plus the four cohort ``PolymorphicMetrics`` (DCS/ISG/LFDI/SAF),
    built from a list of :class:`~hipaasynth.dif.report.FairnessPassport`.

All inputs describe synthetic data — no PHI.
"""
from __future__ import annotations

from collections import Counter
from html import escape
from typing import Dict, List, Optional, Sequence, Tuple

# Canonical polymorphic form order (clinician forms first, then patient/LEP/CHW),
# so the heatmap rows read in a consistent, meaningful order.
_FORM_ORDER: Tuple[str, ...] = (
    "FHIR_STRUCTURED",
    "PHYSICIAN_SOAP",
    "MIDLEVEL_ABBREVIATED",
    "PATIENT_HIGH_LITERACY",
    "PATIENT_LOW_LITERACY",
    "LEP_TRANSLATED",
    "CHW_SDOH_RICH",
)
_FORM_LABELS: Dict[str, str] = {
    "FHIR_STRUCTURED": "FHIR (structured)",
    "PHYSICIAN_SOAP": "Physician SOAP",
    "MIDLEVEL_ABBREVIATED": "Mid-level (abbrev.)",
    "PATIENT_HIGH_LITERACY": "Patient (high-lit.)",
    "PATIENT_LOW_LITERACY": "Patient (low-lit.)",
    "LEP_TRANSLATED": "LEP (translated)",
    "CHW_SDOH_RICH": "CHW (SDoH-rich)",
}

# Age bands mirror the profile configs (hipaasynth/profiles/*.json).
_AGE_BANDS: Tuple[Tuple[str, int, int], ...] = (
    ("18-24", 18, 24),
    ("25-44", 25, 44),
    ("45-64", 45, 64),
    ("65-90", 65, 90),
)

# Palette (works on the UI's dark panel and as a standalone file on white).
_INK = "#1f2a37"
_MUTED = "#6b7280"
_BAR = "#4c8bf5"
_BAR_ALT = "#8b5cf6"
_BAR_ETH = "#0ea5a4"
_GRID = "#d1d9e6"


def _esc(text: object) -> str:
    return escape(str(text), quote=True)


def _bar_group(
    x: int,
    y: int,
    width: int,
    rows: Sequence[Tuple[str, int]],
    total: int,
    colour: str,
) -> Tuple[str, int]:
    """Render one titled group of horizontal bars; return (svg, next_y)."""
    label_w = 130
    bar_x = x + label_w
    bar_w = width - label_w - 60
    row_h = 22
    gap = 6
    max_count = max((c for _, c in rows), default=1) or 1
    parts: List[str] = []
    cy = y
    for label, count in rows:
        frac = count / max_count
        w = max(1, round(bar_w * frac))
        pct = (count / total * 100) if total else 0.0
        parts.append(
            f'<text x="{bar_x - 8}" y="{cy + row_h / 2 + 4}" text-anchor="end" '
            f'font-size="12" fill="{_INK}">{_esc(label)}</text>'
        )
        parts.append(
            f'<rect x="{bar_x}" y="{cy}" width="{bar_w}" height="{row_h}" '
            f'rx="3" fill="{_GRID}" opacity="0.35"/>'
        )
        parts.append(
            f'<rect x="{bar_x}" y="{cy}" width="{w}" height="{row_h}" rx="3" '
            f'fill="{colour}"><title>{_esc(label)}: {count} ({pct:.1f}%)</title></rect>'
        )
        parts.append(
            f'<text x="{bar_x + w + 6}" y="{cy + row_h / 2 + 4}" font-size="11" '
            f'fill="{_MUTED}">{count} · {pct:.0f}%</text>'
        )
        cy += row_h + gap
    return "\n".join(parts), cy


def cohort_demographics(patients: Sequence) -> Dict[str, List[Tuple[str, int]]]:
    """Aggregate a cohort's age-band / sex / ethnicity counts (ordered).

    Pure data reduction over ``Patient.demographics`` — the same numbers the SVG
    renders, exposed separately so callers can test the aggregation directly.
    """
    ages = Counter()
    for p in patients:
        age = p.demographics.age
        band = next((name for name, lo, hi in _AGE_BANDS if lo <= age <= hi), "other")
        ages[band] += 1
    age_rows = [(name, ages.get(name, 0)) for name, _, _ in _AGE_BANDS]
    if ages.get("other"):
        age_rows.append(("other", ages["other"]))

    sex = Counter(p.demographics.sex for p in patients)
    sex_rows = sorted(sex.items(), key=lambda kv: (-kv[1], kv[0]))

    eth = Counter(p.demographics.ethnicity for p in patients)
    eth_rows = sorted(eth.items(), key=lambda kv: (-kv[1], kv[0]))
    return {"age": age_rows, "sex": sex_rows, "ethnicity": eth_rows}


def demographics_distribution_svg(
    patients: Sequence,
    *,
    width: int = 460,
    title: Optional[str] = None,
) -> str:
    """Render a cohort's age / sex / ethnicity distribution as grouped bar charts."""
    n = len(patients)
    dist = cohort_demographics(patients)
    heading = title or f"Population distribution (n={n})"

    body: List[str] = []
    y = 54
    for section, colour in (("age", _BAR), ("sex", _BAR_ALT), ("ethnicity", _BAR_ETH)):
        rows = dist[section]
        body.append(
            f'<text x="16" y="{y}" font-size="13" font-weight="600" '
            f'fill="{_INK}">{section.capitalize()}</text>'
        )
        y += 12
        group_svg, y = _bar_group(16, y, width, rows, n, colour)
        body.append(group_svg)
        y += 18

    height = y + 10
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" '
        f'aria-label="{_esc(heading)}" font-family="system-ui, sans-serif">'
        f'<rect x="0" y="0" width="{width}" height="{height}" fill="#ffffff" rx="8"/>'
        f'<text x="16" y="28" font-size="15" font-weight="700" '
        f'fill="{_INK}">{_esc(heading)}</text>'
        f'<text x="{width - 16}" y="28" text-anchor="end" font-size="10" '
        f'fill="{_MUTED}">synthetic — no PHI</text>'
        + "\n".join(body)
        + "</svg>"
    )


def _heat_colour(rate: float) -> str:
    """Green (low error) → amber → red (high error) for a 0..1 error rate."""
    rate = max(0.0, min(1.0, rate))
    if rate <= 0.5:
        # green → amber
        t = rate / 0.5
        r = int(0x2f + (0xf5 - 0x2f) * t)
        g = int(0xb9 + (0xb0 - 0xb9) * t)
        b = int(0x50 + (0x22 - 0x50) * t)
    else:
        # amber → red
        t = (rate - 0.5) / 0.5
        r = int(0xf5 + (0xf8 - 0xf5) * t)
        g = int(0xb0 + (0x51 - 0xb0) * t)
        b = int(0x22 + (0x49 - 0x22) * t)
    return f"#{r:02x}{g:02x}{b:02x}"


def fairness_heatmap_svg(passports: Sequence, *, width: int = 460) -> str:
    """Render a fairness visualization from a cohort of ``FairnessPassport`` objects.

    Two panels: (1) a per-form error-rate heatmap across the seven polymorphic
    forms, and (2) the four cohort ``PolymorphicMetrics`` (DCS/ISG/LFDI/SAF) with
    their cohort means and pass/fail status.
    """
    # Local imports keep this module import-light and avoid a hard dif dependency
    # for callers that only want the demographics chart.
    from hipaasynth.dif.report import per_form_error_rates, summarize_cohort

    if not passports:
        raise ValueError("fairness_heatmap_svg requires at least one passport")

    summary = summarize_cohort(list(passports))
    errors = per_form_error_rates(list(passports))

    x0 = 200          # left column for form labels
    cell_w = width - x0 - 60
    cell_h = 26
    gap = 4
    parts: List[str] = []

    y = 66
    parts.append(
        f'<text x="16" y="{y}" font-size="13" font-weight="600" fill="{_INK}">'
        f'Per-form error rate (vs. ground truth)</text>'
    )
    y += 12
    truth_note = (
        f"{summary.truth_evaluated_n} of {summary.n} patients ground-truth-evaluated"
    )
    parts.append(
        f'<text x="16" y="{y}" font-size="10" fill="{_MUTED}">{_esc(truth_note)}</text>'
    )
    y += 12
    for form in _FORM_ORDER:
        rate = errors.get(form, 0.0)
        colour = _heat_colour(rate)
        label = _FORM_LABELS.get(form, form)
        parts.append(
            f'<text x="{x0 - 8}" y="{y + cell_h / 2 + 4}" text-anchor="end" '
            f'font-size="11" fill="{_INK}">{_esc(label)}</text>'
        )
        parts.append(
            f'<rect x="{x0}" y="{y}" width="{cell_w}" height="{cell_h}" rx="3" '
            f'fill="{colour}"><title>{_esc(label)}: {rate * 100:.1f}% error</title></rect>'
        )
        text_fill = "#ffffff" if rate > 0.25 else _INK
        parts.append(
            f'<text x="{x0 + cell_w / 2}" y="{y + cell_h / 2 + 4}" text-anchor="middle" '
            f'font-size="11" fill="{text_fill}">{rate * 100:.0f}%</text>'
        )
        y += cell_h + gap

    # Metric summary tiles.
    y += 14
    parts.append(
        f'<text x="16" y="{y}" font-size="13" font-weight="600" fill="{_INK}">'
        f'Cohort polymorphic metrics</text>'
    )
    y += 12
    metrics = [
        ("DCS", summary.dcs_mean, summary.dcs_pass_rate >= 0.5, "consistency"),
        ("ISG", summary.isg_mean, _metric_ok(summary, "isg"), "info-source gap"),
        ("LFDI", summary.lfdi_mean, _metric_ok(summary, "lfdi"), "linguistic disadv."),
        ("SAF", summary.saf_mean, _metric_ok(summary, "saf"), "SDoH amplification"),
    ]
    tile_w = (width - 32 - 3 * 8) / 4
    for i, (name, value, ok, sub) in enumerate(metrics):
        tx = 16 + i * (tile_w + 8)
        fill = "#e8f6ec" if ok else "#fdecea"
        edge = "#2fb950" if ok else "#f85149"
        parts.append(
            f'<rect x="{tx}" y="{y}" width="{tile_w}" height="58" rx="6" '
            f'fill="{fill}" stroke="{edge}" stroke-width="1.5"/>'
        )
        parts.append(
            f'<text x="{tx + tile_w / 2}" y="{y + 18}" text-anchor="middle" '
            f'font-size="12" font-weight="700" fill="{_INK}">{name}</text>'
        )
        parts.append(
            f'<text x="{tx + tile_w / 2}" y="{y + 36}" text-anchor="middle" '
            f'font-size="14" fill="{_INK}">{value:.2f}</text>'
        )
        parts.append(
            f'<text x="{tx + tile_w / 2}" y="{y + 50}" text-anchor="middle" '
            f'font-size="8" fill="{_MUTED}">{_esc(sub)}</text>'
        )
    y += 58 + 14

    height = y + 6
    heading = f"Fairness audit · {_esc(summary.device_name)} v{_esc(summary.device_version)}"
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-label="fairness heatmap" '
        f'font-family="system-ui, sans-serif">'
        f'<rect x="0" y="0" width="{width}" height="{height}" fill="#ffffff" rx="8"/>'
        f'<text x="16" y="28" font-size="15" font-weight="700" fill="{_INK}">{heading}</text>'
        f'<text x="16" y="44" font-size="10" fill="{_MUTED}">'
        f'overall pass rate {summary.overall_pass_rate * 100:.0f}% · synthetic — no PHI</text>'
        + "\n".join(parts)
        + "</svg>"
    )


def _metric_ok(summary, which: str) -> bool:
    """A truth-dependent metric is only 'ok' when it was actually evaluated."""
    if summary.truth_evaluated_n == 0:
        return False
    thresholds = {"isg": 0.15, "lfdi": 0.20, "saf": 0.20}
    value = getattr(summary, f"{which}_mean")
    return value <= thresholds[which]
