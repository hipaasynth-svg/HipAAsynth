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

"""DIF mock models for demonstrating polymorphic fairness signals.

These models are intentionally simple.  They operate on the synthetic patient's
acute-condition ground truth (sepsis_flag, stroke_flag, dka_flag, or
fabry_referral_flag in ``observations``) and produce deterministic binary
decisions for every polymorphic form.
"""

from dataclasses import dataclass
from typing import Any, Optional, Protocol, Union, runtime_checkable

from hipaasynth.core.schema import Patient
from hipaasynth.polymorphic.forms import Form


@dataclass
class DecisionResult:
    """Structured result returned by real-model adapters.

    Real models (LLMs, hosted clinical classifiers) do not always emit a clean
    binary decision.  ``DecisionResult`` lets an adapter preserve the model's
    raw output alongside the parsed decision so that ambiguous or refused
    responses are never silently coerced into a ``True``/``False`` triage call.

    Attributes:
        raw_response: The verbatim text/output returned by the underlying model.
        decision: The parsed binary triage decision, or ``None`` when the
            response could not be parsed into an unambiguous decision.
        refused: ``True`` if the model explicitly declined or refused to answer.
        parse_confidence: Adapter confidence in the parse, in ``[0.0, 1.0]``.

    The mock models (:class:`MockFairModel`, :class:`MockBiasedModel`) return
    plain ``bool`` values and do **not** use this dataclass.  The DIF audit
    layer accepts either a plain ``bool`` or a ``DecisionResult``.
    """

    raw_response: str
    decision: Optional[bool]
    refused: bool
    parse_confidence: float


@runtime_checkable
class ClinicalModel(Protocol):
    """Contract for any model audited by the DIF fairness framework.

    A conforming model exposes a single ``predict`` method:

        predict(patient, form) -> bool | DecisionResult

    Contract:
        - ``predict`` must return a binary acute-triage decision for the given
          synthetic ``patient`` rendered in the given polymorphic ``form``.
          ``True`` means *treat/escalate*; ``False`` means *do not*.
        - The decision may be returned directly as a ``bool`` (as the reference
          mock models do) or wrapped in a :class:`DecisionResult` so that the
          raw model output is preserved.
        - Real-model adapters must **never** silently coerce an ambiguous or
          refused response into a decision.  When the underlying model is
          unclear or declines to answer, the adapter must return a
          :class:`DecisionResult` with ``decision=None`` (unparseable) or
          ``refused=True`` rather than defaulting to ``False``.

    :class:`MockFairModel` and :class:`MockBiasedModel` already satisfy this
    contract by returning plain ``bool`` decisions.
    """

    def predict(self, patient: Patient, form: dict[str, Any]) -> Union[bool, DecisionResult]:
        """Return an acute-triage decision for ``patient`` rendered as ``form``."""
        ...


def _ground_truth(patient: Patient) -> bool:
    """Return the acute-condition ground truth for a synthetic patient.

    A positive determination is any active acute/actionable finding across the
    supported modules: sepsis, acute stroke, diabetic ketoacidosis, or a
    Fabry-disease referral. The DIF audit scores a model's decision
    *consistency* across the seven polymorphic forms against this value.
    """
    obs = patient.observations or {}
    return bool(
        obs.get("sepsis_flag")
        or obs.get("stroke_flag")
        or obs.get("dka_flag")
        or obs.get("fabry_referral_flag")
    )


class MockFairModel:
    """Reference fair model: consistent, correct decisions across all 7 forms."""

    def predict(self, patient: Patient, form: dict[str, Any]) -> bool:
        """Return the ground-truth decision regardless of form."""
        return _ground_truth(patient)


class MockBiasedModel:
    """
    Reference biased model: accurate on clinician-facing forms (1-3) but
    systematically under-triages patient-facing and LEP forms (4-6).

    Under-triage here means positive acute cases are classified as negative
    for the disadvantaged forms, while negative cases remain correctly
    classified.
    """

    UNDER_TRIAGED_FORMS = {
        Form.PATIENT_HIGH_LITERACY.value,
        Form.PATIENT_LOW_LITERACY.value,
        Form.LEP_TRANSLATED.value,
    }

    def predict(self, patient: Patient, form: dict[str, Any]) -> bool:
        """Return ground truth for clinician/CHW forms; under-triage patient/LEP."""
        gt = _ground_truth(patient)
        form_name = form.get("form", "")
        if form_name in self.UNDER_TRIAGED_FORMS and gt:
            return False
        return gt


class MockSDoHBiasedModel:
    """
    Reference SDoH-biased model: accurate everywhere except the SDoH-rich CHW
    intake form for patients carrying a high social-determinant burden, whom it
    under-triages. Demonstrates the SDoH Amplification Factor (SAF) — the CHW
    form is where a model that penalizes social complexity reveals itself.
    """

    HIGH_SDOH_BURDEN = 2  # of 4 adverse factors

    def predict(self, patient: Patient, form: dict[str, Any]) -> bool:
        """Under-triage acute-positive high-SDoH-burden patients on the CHW form."""
        gt = _ground_truth(patient)
        if form.get("form", "") == Form.CHW_SDOH_RICH.value and gt:
            # Import locally to keep the module import graph light.
            from hipaasynth.polymorphic.sdoh import derive_sdoh

            if derive_sdoh(patient).get("sdoh_burden_score", 0) >= self.HIGH_SDOH_BURDEN:
                return False
        return gt
