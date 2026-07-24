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

"""FairnessPassport report for the DIF audit layer.

The passport is a **hash-sealed, third-party-verifiable** artifact (audit
finding F2). Beyond the model's per-form decisions and the fairness metrics, it
records everything needed to reproduce the exact presentations the model saw:
the seed, run date, generation anchor hash, form-engine version, and the
SHA-256 of every rendered form. ``content_sha256`` seals the whole passport, and
``verify()`` re-renders the forms to confirm byte-identical presentations.
"""

from __future__ import annotations

import hashlib
import json
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from hipaasynth.polymorphic.metrics import PolymorphicMetrics


@dataclass
class FairnessPassport:
    """
    Per-patient fairness passport produced by a DIF audit.

    Captures the model's decisions across all seven polymorphic forms for one
    synthetic patient, the computed polymorphic fairness metrics, regulatory
    mappings with remediation guidance, and a verification seal (seed, anchor
    hash, form-engine version, per-form content hashes) that lets a third party
    re-render the exact presentations and confirm them.
    """

    device_name: str
    device_version: str
    test_date: str
    patient_id: str
    ground_truth: bool
    decisions: Dict[str, bool]
    metrics: PolymorphicMetrics
    fda_tplc_mapping: Dict[str, str] = field(default_factory=dict)
    eu_ai_act_mapping: Dict[str, str] = field(default_factory=dict)
    recommendations: List[str] = field(default_factory=list)
    refused_forms: List[str] = field(default_factory=list)
    unparseable_forms: List[str] = field(default_factory=list)
    # Verification seal (audit finding F2).
    seed: Optional[int] = None
    run_date: Optional[str] = None
    anchor_hash: Optional[str] = None
    engine_version: Optional[str] = None
    form_engine_version: Optional[str] = None
    information_mode: Optional[str] = None
    form_hashes: Dict[str, str] = field(default_factory=dict)

    @classmethod
    def build(
        cls,
        device_name: str,
        device_version: str,
        patient_id: str,
        ground_truth: bool,
        decisions: Dict[str, bool],
        metrics: PolymorphicMetrics,
        refused_forms: Optional[List[str]] = None,
        unparseable_forms: Optional[List[str]] = None,
        *,
        test_date: Optional[str] = None,
        seed: Optional[int] = None,
        run_date: Optional[str] = None,
        anchor_hash: Optional[str] = None,
        engine_version: Optional[str] = None,
        form_engine_version: Optional[str] = None,
        information_mode: Optional[str] = None,
        form_hashes: Optional[Dict[str, str]] = None,
    ) -> "FairnessPassport":
        """Construct a fully populated passport with regulatory mappings and seal.

        ``test_date`` defaults to the deterministic ``run_date`` when supplied
        (so the passport is byte-identical across runs of the same seed/config);
        only when neither is given does it fall back to the wall-clock UTC time.
        ``refused_forms`` / ``unparseable_forms`` are recorded verbatim rather
        than coerced into a ``False`` decision.
        """
        fda = _fda_tplc_mapping(metrics)
        eu = _eu_ai_act_mapping(metrics)
        recs = _recommendations(metrics)
        if test_date is None:
            test_date = run_date or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        return cls(
            device_name=device_name,
            device_version=device_version,
            test_date=test_date,
            patient_id=patient_id,
            ground_truth=ground_truth,
            decisions=decisions,
            metrics=metrics,
            fda_tplc_mapping=fda,
            eu_ai_act_mapping=eu,
            recommendations=recs,
            refused_forms=list(refused_forms or []),
            unparseable_forms=list(unparseable_forms or []),
            seed=seed,
            run_date=run_date,
            anchor_hash=anchor_hash,
            engine_version=engine_version,
            form_engine_version=form_engine_version,
            information_mode=information_mode,
            form_hashes=dict(form_hashes or {}),
        )

    def passed(self) -> bool:
        """Return True if all polymorphic metrics pass."""
        return self.metrics.all_pass()

    def _seal_payload(self) -> Dict[str, Any]:
        """Deterministic content sealed by ``content_sha256`` (no wall-clock)."""
        m = self.metrics
        return {
            "device_name": self.device_name,
            "device_version": self.device_version,
            "patient_id": self.patient_id,
            "ground_truth": self.ground_truth,
            "decisions": self.decisions,
            "metrics": {
                "dcs": m.dcs,
                "isg": m.isg,
                "lfdi": m.lfdi,
                "saf": m.saf,
                "truth_evaluated": m.truth_evaluated,
            },
            "seed": self.seed,
            "run_date": self.run_date,
            "anchor_hash": self.anchor_hash,
            "engine_version": self.engine_version,
            "form_engine_version": self.form_engine_version,
            "information_mode": self.information_mode,
            "form_hashes": self.form_hashes,
            "refused_forms": sorted(self.refused_forms),
            "unparseable_forms": sorted(self.unparseable_forms),
        }

    def content_sha256(self) -> str:
        """SHA-256 seal over the passport's deterministic content."""
        serialized = json.dumps(self._seal_payload(), sort_keys=True, default=str)
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    def verify(self, patient: Any, engine: Any = None) -> bool:
        """Re-render ``patient``'s forms and confirm they match the sealed hashes.

        Returns True only if the form-engine version matches and every recorded
        per-form ``content_sha256`` reproduces exactly. Requires the original
        patient record; a third party regenerates it from the sealed seed/config.
        """
        from hipaasynth.polymorphic.forms import FORM_ENGINE_VERSION, PolymorphicFormEngine

        if not self.form_hashes:
            return False
        if self.form_engine_version and self.form_engine_version != FORM_ENGINE_VERSION:
            return False
        if engine is None:
            engine = PolymorphicFormEngine(
                information_mode=self.information_mode or "same_facts"
            )
        for rendered in engine.express_all(patient):
            expected = self.form_hashes.get(rendered["form"])
            if expected is None or expected != rendered["content_sha256"]:
                return False
        return True

    def to_markdown(self) -> str:
        """Render the passport as a markdown report."""
        m = self.metrics

        def truth_cell(passed: bool) -> str:
            if not m.truth_evaluated:
                return "NOT EVALUATED"
            return "PASS" if passed else "FAIL"

        lines = [
            "# HipAAsynth Fairness Passport",
            "",
            "## Device Under Test",
            f"- **Device name:** {self.device_name}",
            f"- **Device version:** {self.device_version}",
            f"- **Test date:** {self.test_date}",
            f"- **Synthetic patient ID:** {self.patient_id}",
            f"- **Ground truth acute condition:** "
            f"{'Yes' if self.ground_truth else 'No' if self.metrics.truth_evaluated else 'Unknown (not supplied)'}",
            "",
            "## Polymorphic Decisions",
            "| Form | Decision | Matches ground truth |",
            "|---|---|---|",
        ]
        for form_name, decision in sorted(self.decisions.items()):
            if not m.truth_evaluated:
                match = "—"
            else:
                match = "✓" if decision == self.ground_truth else "✗"
            lines.append(
                f"| {form_name} | {'Yes' if decision else 'No'} | {match} |"
            )
        for form_name in sorted(self.refused_forms):
            lines.append(f"| {form_name} | refused | — |")
        for form_name in sorted(self.unparseable_forms):
            lines.append(f"| {form_name} | unparseable | — |")

        lines += [
            "",
            "## Polymorphic Fairness Metrics",
            "| Metric | Value | Pass |",
            "|---|---|---|",
            f"| DCS | {m.dcs:.3f} | {'PASS' if m.dcs_pass else 'FAIL'} |",
            f"| ISG | {m.isg:.3f} | {truth_cell(m.isg_pass)} |",
            f"| LFDI | {m.lfdi:.3f} | {truth_cell(m.lfdi_pass)} |",
            f"| SAF | {m.saf:.3f} | {truth_cell(m.saf_pass)} |",
            "",
            f"**Overall result:** {'PASS' if self.passed() else 'FAIL'}"
            + ("" if m.truth_evaluated else " (equity metrics not evaluated — no ground truth)"),
            "",
            "## Verification Seal",
            f"- **Engine version:** {self.engine_version or 'n/a'}",
            f"- **Form engine version:** {self.form_engine_version or 'n/a'}",
            f"- **Information mode:** {self.information_mode or 'n/a'}",
            f"- **Seed:** {self.seed if self.seed is not None else 'n/a'}",
            f"- **Run date:** {self.run_date or 'n/a'}",
            f"- **Generation anchor hash:** {self.anchor_hash or 'n/a'}",
            f"- **Passport content hash (SHA-256):** {self.content_sha256()}",
        ]
        if self.form_hashes:
            lines += ["", "| Form | Content SHA-256 |", "|---|---|"]
            for form_name in sorted(self.form_hashes):
                lines.append(f"| {form_name} | `{self.form_hashes[form_name]}` |")

        lines += ["", "## FDA TPLC Compliance Mapping"]
        for stage, note in self.fda_tplc_mapping.items():
            lines.append(f"- **{stage}:** {note}")

        lines += ["", "## EU AI Act Compliance Mapping"]
        for article, note in self.eu_ai_act_mapping.items():
            lines.append(f"- **{article}:** {note}")

        if self.recommendations:
            lines += ["", "## Remediation Recommendations"]
            for i, rec in enumerate(self.recommendations, 1):
                lines.append(f"{i}. {rec}")

        lines += [
            "",
            "---",
            "",
            "*All data are synthetic. No PHI is used or referenced.*",
        ]
        return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Cohort-level aggregation (audit finding F4)
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class CohortFairnessSummary:
    """Aggregate fairness signal across a cohort of passports.

    Per-patient ISG/LFDI/SAF are noisy (they are accuracy gaps over 1-3 forms);
    the decision-relevant signal emerges at the cohort level. This roll-up
    reports means (with 95% normal-approx confidence half-widths), pass rates,
    and the worst-performing form.
    """

    n: int
    device_name: str
    device_version: str
    dcs_mean: float
    dcs_pass_rate: float
    isg_mean: float
    lfdi_mean: float
    saf_mean: float
    isg_ci95: float
    lfdi_ci95: float
    saf_ci95: float
    overall_pass_rate: float
    truth_evaluated_n: int
    worst_form: Optional[str]
    worst_form_error_rate: float

    def to_markdown(self) -> str:
        lines = [
            "# HipAAsynth Cohort Fairness Summary",
            "",
            f"- **Device:** {self.device_name} v{self.device_version}",
            f"- **Patients audited:** {self.n}",
            f"- **Ground-truth-evaluated patients:** {self.truth_evaluated_n}",
            "",
            "| Metric | Cohort mean | 95% CI (±) |",
            "|---|---|---|",
            f"| DCS | {self.dcs_mean:.3f} | — |",
            f"| ISG | {self.isg_mean:.3f} | {self.isg_ci95:.3f} |",
            f"| LFDI | {self.lfdi_mean:.3f} | {self.lfdi_ci95:.3f} |",
            f"| SAF | {self.saf_mean:.3f} | {self.saf_ci95:.3f} |",
            "",
            f"- **DCS pass rate:** {self.dcs_pass_rate:.1%}",
            f"- **Overall pass rate:** {self.overall_pass_rate:.1%}",
            f"- **Worst-performing form:** {self.worst_form or 'n/a'} "
            f"(error rate {self.worst_form_error_rate:.1%})",
            "",
            "---",
            "",
            "*All data are synthetic. No PHI is used or referenced.*",
        ]
        return "\n".join(lines)


def _ci95_halfwidth(values: List[float]) -> float:
    """95% normal-approximation confidence half-width for a mean."""
    if len(values) < 2:
        return 0.0
    sd = statistics.stdev(values)
    return 1.96 * sd / (len(values) ** 0.5)


def summarize_cohort(passports: List[FairnessPassport]) -> CohortFairnessSummary:
    """Aggregate a list of passports into a :class:`CohortFairnessSummary`."""
    if not passports:
        raise ValueError("cannot summarize an empty cohort")

    first = passports[0]
    dcs = [p.metrics.dcs for p in passports]
    truth = [p for p in passports if p.metrics.truth_evaluated]
    isg = [p.metrics.isg for p in truth]
    lfdi = [p.metrics.lfdi for p in truth]
    saf = [p.metrics.saf for p in truth]

    def mean(xs: List[float]) -> float:
        return statistics.fmean(xs) if xs else 0.0

    # Worst form: highest disagreement-with-ground-truth rate across the cohort.
    error_counts: Dict[str, int] = {}
    error_totals: Dict[str, int] = {}
    for p in truth:
        for form_name, decision in p.decisions.items():
            error_totals[form_name] = error_totals.get(form_name, 0) + 1
            if decision != p.ground_truth:
                error_counts[form_name] = error_counts.get(form_name, 0) + 1
    worst_form: Optional[str] = None
    worst_rate = 0.0
    for form_name, total in sorted(error_totals.items()):
        rate = error_counts.get(form_name, 0) / total if total else 0.0
        if rate > worst_rate:
            worst_rate = rate
            worst_form = form_name

    return CohortFairnessSummary(
        n=len(passports),
        device_name=first.device_name,
        device_version=first.device_version,
        dcs_mean=mean(dcs),
        dcs_pass_rate=sum(1 for p in passports if p.metrics.dcs_pass) / len(passports),
        isg_mean=mean(isg),
        lfdi_mean=mean(lfdi),
        saf_mean=mean(saf),
        isg_ci95=_ci95_halfwidth(isg),
        lfdi_ci95=_ci95_halfwidth(lfdi),
        saf_ci95=_ci95_halfwidth(saf),
        overall_pass_rate=sum(1 for p in passports if p.passed()) / len(passports),
        truth_evaluated_n=len(truth),
        worst_form=worst_form,
        worst_form_error_rate=worst_rate,
    )


def _fda_tplc_mapping(metrics: PolymorphicMetrics) -> Dict[str, str]:
    """Map polymorphic metrics to FDA Total Product Life Cycle stages."""
    return {
        "Design & Development (21 CFR 820.30)": (
            "DCS confirms decision consistency across intended-use documentation styles. "
            f"{'PASS' if metrics.dcs_pass else 'FAIL'} — "
            f"{'consistent' if metrics.dcs_pass else 'inconsistent'} across forms."
        ),
        "Performance Evaluation / Clinical Validation": (
            "ISG measures accuracy equity between clinician-facing and patient/LEP forms. "
            f"{'PASS' if metrics.isg_pass else 'FAIL'} — "
            f"gradient = {metrics.isg:.3f}."
        ),
        "Labeling & Intended Use": (
            "LFDI captures linguistic-form disadvantage for low-literacy/LEP patients. "
            f"{'PASS' if metrics.lfdi_pass else 'FAIL'} — "
            f"index = {metrics.lfdi:.3f}."
        ),
        "Post-Market Surveillance": (
            "SAF monitors SDoH-rich CHW intake performance. "
            f"{'PASS' if metrics.saf_pass else 'FAIL'} — "
            f"factor = {metrics.saf:.3f}."
        ),
    }


def _eu_ai_act_mapping(metrics: PolymorphicMetrics) -> Dict[str, str]:
    """Map polymorphic metrics to EU AI Act obligations for high-risk AI."""
    return {
        "Art. 9 — Risk Management System": (
            "ISG and LFDI identify population-specific performance risks. "
            f"ISG {'PASS' if metrics.isg_pass else 'FAIL'}; "
            f"LFDI {'PASS' if metrics.lfdi_pass else 'FAIL'}."
        ),
        "Art. 10 — Data & Training Governance": (
            "DCS evaluates whether training-data documentation bias leaks into decisions. "
            f"DCS {'PASS' if metrics.dcs_pass else 'FAIL'}."
        ),
        "Art. 13 — Transparency & Instructions for Use": (
            "Passport documents intended-use populations and known form-dependent failure modes."
        ),
        "Art. 61 — Post-Market Monitoring": (
            "SAF tracks SDoH-amplified degradation over time. "
            f"SAF {'PASS' if metrics.saf_pass else 'FAIL'}."
        ),
    }


def _recommendations(metrics: PolymorphicMetrics) -> List[str]:
    """Generate remediation recommendations from failing metrics."""
    recs = []
    if not metrics.dcs_pass:
        recs.append(
            "Improve decision consistency: calibrate model confidence thresholds across "
            "structured and narrative inputs so the same clinical content yields the same decision."
        )
    if not metrics.isg_pass:
        recs.append(
            "Reduce information-source gradient: augment training data with patient-generated, "
            "LEP, and abbreviated clinical narratives; evaluate performance parity before deployment."
        )
    if not metrics.lfdi_pass:
        recs.append(
            "Reduce linguistic-form disadvantage: test against low-health-literacy and "
            "non-English inputs; add plain-language and interpreter-mediated intake support."
        )
    if not metrics.saf_pass:
        recs.append(
            "Address SDoH amplification: review model performance on CHW intake notes with "
            "full social-determinant context; ensure SDoH variables do not proxy for undesired exclusion."
        )
    if metrics.all_pass():
        recs.append(
            "No polymorphic fairness signals detected. Continue routine monitoring "
            "as documentation practices and patient populations evolve."
        )
    return recs
