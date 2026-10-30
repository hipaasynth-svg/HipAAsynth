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

"""CC report — renders a CCResult as a human-readable markdown document."""

from datetime import datetime, timezone
from typing import List

from hipaasynth.cc.framework import CCResult
from hipaasynth.cc.generator import CONTINUITY_PROFILES


# Human-readable labels for each profile
_PROFILE_LABELS = {
    "PROFILE_A": "Full continuity — single PCP, complete records",
    "PROFILE_B": "Moderate continuity — 2–3 providers, minor gaps",
    "PROFILE_C": "Low continuity — fragmented, Medicaid churn",
    "PROFILE_D": "Minimal continuity — ED-only, no PCP, no history",
}

# Real-world analogues for each profile
_PROFILE_CONTEXT = {
    "PROFILE_A": "Commercially insured, suburban, long-standing PCP relationship",
    "PROFILE_B": "Moderate insurance, suburban/urban, some specialist involvement",
    "PROFILE_C": "Medicaid churn, frequent mover, 4+ providers across systems",
    "PROFILE_D": "Uninsured / ED-reliant, no established care — AHRQ ~8% of ED visits",
}


class CCReport:
    """
    Renders a :class:`~hipaasynth.cc.framework.CCResult` as markdown.

    Usage::

        report = CCReport(result)
        print(report.to_markdown())
    """

    def __init__(self, result: CCResult) -> None:
        self._r = result

    def to_markdown(self) -> str:
        r = self._r
        cfg = r.config
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        lines: List[str] = [
            "# HipAAsynth — Care Continuity (CC) Report",
            "",
            "## Audit Configuration",
            f"- **Model:** {cfg.model_name} v{cfg.model_version}",
            f"- **Patients per profile:** {cfg.n_per_profile}",
            f"- **Matched pairs (transition test):** {cfg.n_matched_pairs}",
            f"- **Seed:** {cfg.seed}",
            f"- **CDI threshold:** {cfg.cdi_threshold:.2f}",
            f"- **Report generated (UTC):** {now}",
            "",
            "## Continuity Profile Definitions",
            "",
            "| Profile | Description | Real-world analogue |",
            "|---|---|---|",
        ]
        for p in CONTINUITY_PROFILES:
            lines.append(f"| {p} | {_PROFILE_LABELS[p]} | {_PROFILE_CONTEXT[p]} |")

        lines += [
            "",
            "> **Calibration sources:**",
            "> Roberts ET et al. *Health Aff* 2018;37(10):1594-1602 (Medicaid churn ~25%/12 months);",
            "> AHRQ Statistical Brief #179, 2012 (~8% of ED visits: no usual source of care);",
            "> HRSA Health Workforce Shortage Areas 2023 (rural continuity gap).",
            "",
            "## Continuity Degradation Index (CDI)",
            "",
            f"**CDI = mean_score(PROFILE_D) / mean_score(PROFILE_A) = "
            f"{r.per_profile_scores.get('PROFILE_D', 0):.4f} / "
            f"{r.per_profile_scores.get('PROFILE_A', 1):.4f} = "
            f"{r.cdi:.4f}**",
            "",
            f"> Threshold: CDI ≥ {cfg.cdi_threshold:.2f}  →  "
            f"**{'PASS ✓' if r.cdi_pass else 'FAIL ✗'}**",
            "",
            "_CDI < 0.80 means the model is assigning systematically lower scores to_",
            "_patients with fragmented care histories — the patients most at risk of_",
            "_undertriage and least able to advocate for themselves._",
            "",
            "## Per-Profile Score Summary",
            "",
            "| Profile | Mean score | vs PROFILE_A | Status |",
            "|---|---|---|---|",
        ]

        a_score = r.per_profile_scores.get("PROFILE_A", 1.0)
        for profile in CONTINUITY_PROFILES:
            score = r.per_profile_scores.get(profile, 0.0)
            ratio = score / a_score if a_score > 0 else 0.0
            if profile == "PROFILE_A":
                status = "baseline"
            else:
                status = "PASS" if ratio >= cfg.cdi_threshold else "FAIL"
            lines.append(f"| {profile} | {score:.4f} | {ratio:.3f} | {status} |")

        # Transition consistency
        n_pairs = len(r.transition_deltas)
        positive = sum(1 for d in r.transition_deltas if d > 0)
        lines += [
            "",
            "## Transition Consistency (Continuity Bias)",
            "",
            "_Same demographics, different record completeness._",
            "_Delta = score(PROFILE_A) − score(PROFILE_D) per matched patient._",
            "_Positive delta = model scores higher when the record is complete._",
            "",
            f"- **Matched pairs evaluated:** {n_pairs}",
            (
                f"- **Pairs with positive delta (A > D):** {positive} / {n_pairs} "
                f"({100 * positive / n_pairs:.0f}%)"
                if n_pairs
                else "- N/A"
            ),
            f"- **Mean delta (continuity bias):** {r.mean_transition_delta:.4f}",
            "",
        ]

        if r.transition_deltas:
            min_d = min(r.transition_deltas)
            max_d = max(r.transition_deltas)
            lines += [
                f"- **Min delta:** {min_d:.4f}",
                f"- **Max delta:** {max_d:.4f}",
                "",
            ]

        lines += [
            "## Overall Result",
            "",
            f"**{'PASS ✓' if r.all_pass() else 'FAIL ✗'}** — "
            f"CDI = {r.cdi:.4f} (threshold {cfg.cdi_threshold:.2f})",
            "",
            "---",
            "",
            "*All data are synthetic. No PHI is used or referenced.*",
            "*HipAAsynth CC Axis — 7-Axis Adversarial Stress Test (7AAST)*",
        ]
        return "\n".join(lines)
