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

"""PSF report — renders a PSFResult as a human-readable markdown document."""

from datetime import datetime, timezone
from typing import List

from hipaasynth.psf.framework import PSFResult
from hipaasynth.psf.generator import SPARSITY_LEVELS


class PSFReport:
    """
    Renders a :class:`~hipaasynth.psf.framework.PSFResult` as markdown.

    Usage::

        report = PSFReport(result)
        print(report.to_markdown())
    """

    def __init__(self, result: PSFResult) -> None:
        self._r = result

    def to_markdown(self) -> str:
        r = self._r
        cfg = r.config
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        lines: List[str] = [
            "# HipAAsynth — Population Sparsity Fairness (PSF) Report",
            "",
            "## Audit Configuration",
            f"- **Model:** {cfg.model_name} v{cfg.model_version}",
            f"- **Patients per level:** {cfg.n_per_level}",
            f"- **Seed:** {cfg.seed}",
            f"- **SDI threshold:** {cfg.sdi_threshold:.2f}",
            f"- **Report generated (UTC):** {now}",
            "",
            "## Sparsity Level Definitions",
            "",
            "| Level | Fields present | Real-world analogue |",
            "|---|---|---|",
            "| S7 | Full record (demographics, labs, lab history, comorbidities, visit history, insurance, SES) | Academic medical centre |",
            "| S6 | S7 minus insurance and SES proxy | Community hospital |",
            "| S5 | S6 minus lab history | Rural hospital with partial EHR |",
            "| S4 | S5 minus visit history | Critical-access hospital |",
            "| S3 | S4 minus comorbidities | IHS clinic with limited coding |",
            "| S2 | S3 minus current labs and primary Dx | IHS / tribal minimal record |",
            "| S1 | Age, sex, race/ethnicity, geography, chief complaint only | ED triage note, no EHR integration |",
            "",
            "> **Calibration sources:** IHS Data Governance Framework (IHS, 2022);",
            "> Sequist TD. *N Engl J Med* 2021;385:2373-2379 (IHS EHR gaps);",
            "> Adler-Milstein J et al. *Health Aff* 2017;36(5):848-854 (CAH EHR adoption);",
            "> Decker SL. *JAMA Intern Med* 2013;173(18):1783-1784 (safety-net EHR fragmentation).",
            "",
            "## Sparsity Degradation Index (SDI)",
            "",
            f"**SDI = mean_score(S1) / mean_score(S7) = "
            f"{r.per_level_scores.get('S1', 0):.4f} / "
            f"{r.per_level_scores.get('S7', 1):.4f} = "
            f"{r.sdi:.4f}**",
            "",
            f"> Threshold: SDI ≥ {cfg.sdi_threshold:.2f}  →  "
            f"**{'PASS ✓' if r.sdi_pass else 'FAIL ✗'}**",
            "",
            "_SDI < 0.80 means the model is more sensitive to record completeness than_",
            "_to clinical content, penalising patients from under-resourced settings._",
            "",
            "## Per-Level Score Summary",
            "",
            "| Level | Mean score | vs S7 | Status |",
            "|---|---|---|---|",
        ]

        s7 = r.per_level_scores.get("S7", 1.0)
        for level in reversed(SPARSITY_LEVELS):
            score = r.per_level_scores.get(level, 0.0)
            ratio = score / s7 if s7 > 0 else 0.0
            status = (
                "baseline" if level == "S7" else ("PASS" if ratio >= cfg.sdi_threshold else "FAIL")
            )
            lines.append(f"| {level} | {score:.4f} | {ratio:.3f} | {status} |")

        lines += [
            "",
            "## Demographic-Sparsity Interaction",
            "",
            "_Shows mean model score by race/ethnicity at S1 (most sparse) and S7 (full)._",
            "_A fair model shows equal degradation across groups; a biased model amplifies_",
            "_the sparsity penalty for historically under-served populations._",
            "",
        ]

        # Build a sorted union of all race/ethnicity groups across levels
        all_groups: List[str] = []
        for level in ["S1", "S7"]:
            for g in r.demographic_scores.get(level, {}):
                if g not in all_groups:
                    all_groups.append(g)
        all_groups.sort()

        lines.append("| Race/Ethnicity | S1 score | S7 score | Degradation ratio |")
        lines.append("|---|---|---|---|")
        for group in all_groups:
            s1g = r.demographic_scores.get("S1", {}).get(group)
            s7g = r.demographic_scores.get("S7", {}).get(group)
            if s1g is None or s7g is None:
                continue
            deg = s1g / s7g if s7g > 0 else 0.0
            lines.append(f"| {group} | {s1g:.4f} | {s7g:.4f} | {deg:.3f} |")

        lines += [
            "",
            "## Overall Result",
            "",
            f"**{'PASS ✓' if r.all_pass() else 'FAIL ✗'}** — "
            f"SDI = {r.sdi:.4f} (threshold {cfg.sdi_threshold:.2f})",
            "",
            "---",
            "",
            "*All data are synthetic. No PHI is used or referenced.*",
            "*HipAAsynth PSF Axis — 7-Axis Adversarial Stress Test (7AAST)*",
        ]
        return "\n".join(lines)
