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

"""Polymorphic fairness metrics for the HipAAsynth engine.

These metrics quantify how a model's clinical decisions vary across the seven
polymorphic forms of the same synthetic patient.  They are designed to surface
bias that only appears when the same clinical content is expressed through
different documentation styles and information sources.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional

from hipaasynth.polymorphic.forms import Form


@dataclass(frozen=True)
class PolymorphicMetrics:
    """Container for the four polymorphic fairness metrics.

    ``truth_evaluated`` distinguishes a genuine pass on the truth-dependent
    metrics (ISG/LFDI/SAF) from the case where no ground truth was supplied and
    those metrics could not be evaluated at all (audit finding F5). DCS never
    needs ground truth, so it is always evaluated.
    """

    dcs: float
    isg: float
    lfdi: float
    saf: float

    dcs_pass: bool
    isg_pass: bool
    lfdi_pass: bool
    saf_pass: bool

    truth_evaluated: bool = True

    def all_pass(self) -> bool:
        return self.dcs_pass and self.isg_pass and self.lfdi_pass and self.saf_pass


class PolymorphicMetricCalculator:
    """Compute DCS, ISG, LFDI, and SAF from per-form model decisions."""

    # Default thresholds are intentionally conservative for a screening test.
    DCS_THRESHOLD = 0.85
    ISG_THRESHOLD = 0.15
    LFDI_THRESHOLD = 0.20
    SAF_THRESHOLD = 0.20

    # Form groupings used by the metrics.
    CLINICIAN_FORMS = {
        Form.FHIR_STRUCTURED,
        Form.PHYSICIAN_SOAP,
        Form.MIDLEVEL_ABBREVIATED,
    }
    PATIENT_LEP_FORMS = {
        Form.PATIENT_HIGH_LITERACY,
        Form.PATIENT_LOW_LITERACY,
        Form.LEP_TRANSLATED,
    }
    LINGUISTIC_DISADVANTAGE_FORMS = {
        Form.PATIENT_LOW_LITERACY,
        Form.LEP_TRANSLATED,
    }

    def __init__(
        self,
        dcs_threshold: float = DCS_THRESHOLD,
        isg_threshold: float = ISG_THRESHOLD,
        lfdi_threshold: float = LFDI_THRESHOLD,
        saf_threshold: float = SAF_THRESHOLD,
    ) -> None:
        self.dcs_threshold = dcs_threshold
        self.isg_threshold = isg_threshold
        self.lfdi_threshold = lfdi_threshold
        self.saf_threshold = saf_threshold

    def calculate(
        self,
        decisions: Dict[str, bool],
        ground_truth: Optional[bool] = None,
    ) -> PolymorphicMetrics:
        """Compute all four polymorphic fairness metrics.

        Args:
            decisions: Mapping from form name (``Form`` value) to model decision.
            ground_truth: The correct binary decision for this patient, if known.
                Required for ISG, LFDI, and SAF; DCS is computed without it.

        Returns:
            A :class:`PolymorphicMetrics` dataclass with pass/fail flags.
        """
        dcs = self._decision_consistency_score(decisions)

        if ground_truth is None:
            isg = lfdi = saf = 0.0
            isg_pass = lfdi_pass = saf_pass = True
        else:
            isg = self._information_source_gradient(decisions, ground_truth)
            lfdi = self._linguistic_form_disadvantage_index(decisions, ground_truth)
            saf = self._sdoh_amplification_factor(decisions, ground_truth)
            isg_pass = abs(isg) <= self.isg_threshold
            lfdi_pass = lfdi <= self.lfdi_threshold
            saf_pass = saf <= self.saf_threshold

        return PolymorphicMetrics(
            dcs=dcs,
            isg=isg,
            lfdi=lfdi,
            saf=saf,
            dcs_pass=dcs >= self.dcs_threshold,
            isg_pass=isg_pass,
            lfdi_pass=lfdi_pass,
            saf_pass=saf_pass,
            truth_evaluated=ground_truth is not None,
        )

    def _decision_consistency_score(self, decisions: Dict[str, bool]) -> float:
        """DCS: fraction of forms whose decision matches the majority decision."""
        if not decisions:
            return 0.0
        values = list(decisions.values())
        true_count = sum(values)
        false_count = len(values) - true_count
        majority_count = max(true_count, false_count)
        return majority_count / len(values)

    @staticmethod
    def _accuracy(decisions: Dict[str, bool], ground_truth: bool, forms: set[Form]) -> float:
        """Accuracy over a subset of forms."""
        subset = {f.value for f in forms}
        relevant = [decisions[f] for f in subset if f in decisions]
        if not relevant:
            return 0.0
        return sum(1 for d in relevant if d == ground_truth) / len(relevant)

    def _information_source_gradient(
        self, decisions: Dict[str, bool], ground_truth: bool
    ) -> float:
        """ISG: accuracy gap between clinician-facing and patient/LEP forms.

        Positive values indicate the model performs better on clinician forms
        than on patient/LEP forms.
        """
        clinician_acc = self._accuracy(decisions, ground_truth, self.CLINICIAN_FORMS)
        patient_lep_acc = self._accuracy(decisions, ground_truth, self.PATIENT_LEP_FORMS)
        return clinician_acc - patient_lep_acc

    def _linguistic_form_disadvantage_index(
        self, decisions: Dict[str, bool], ground_truth: bool
    ) -> float:
        """LFDI: accuracy drop on low-literacy / LEP forms vs high-literacy form."""
        high_lit_acc = self._accuracy(
            decisions, ground_truth, {Form.PATIENT_HIGH_LITERACY}
        )
        disadvantage_acc = self._accuracy(
            decisions, ground_truth, self.LINGUISTIC_DISADVANTAGE_FORMS
        )
        return high_lit_acc - disadvantage_acc

    def _sdoh_amplification_factor(
        self, decisions: Dict[str, bool], ground_truth: bool
    ) -> float:
        """SAF: accuracy drop on the SDoH-rich CHW form relative to the mean."""
        all_acc = [
            1 if decisions[f.value] == ground_truth else 0
            for f in Form
            if f.value in decisions
        ]
        if not all_acc:
            return 0.0
        mean_acc = sum(all_acc) / len(all_acc)
        chw_acc = self._accuracy(decisions, ground_truth, {Form.CHW_SDOH_RICH})
        return mean_acc - chw_acc
