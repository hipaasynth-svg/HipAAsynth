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

"""What a model under test may see: the blinded, decision-time view of a patient.

WHY THIS EXISTS
---------------
A test that asks a model "is this sepsis?" is meaningless if the case it is
shown already says "sepsis". Generated patients carry their answer (the
``*_flag`` ground truth, the diagnosis in ``conditions`` and every visit's
``primary_diagnosis``) and facts that only exist *after* the decision
(``hours_to_hypotension``, ``tpa_administered``, 90-day outcomes). Label and
temporal leakage of exactly this kind is what inflated real sepsis models: the
Epic Sepsis Model's AUROC fell to 0.47 once predictions made after clinical
recognition were excluded (Kamran et al.).

This module is the single list of what is hidden. Blinded forms
(``INFO_MODE_BLINDED``), :func:`blind_record` for structured-input models, and
the Axis 5 decision-time prompts all use it, so the three can never disagree.

A blinded case keeps what a clinician has at the moment of decision:
demographics, chronic comorbidities, vitals, point-of-care labs, the exam,
symptoms and social context. It drops:

* **Answer** — decision-target conditions and diagnoses, ground-truth flags,
  severity labels the answer implies.
* **Future** — anything measured or decided after the triage moment.
* **Generator internals** — flags that record how the synthetic case was built
  rather than anything a clinician could observe.

Pure standard library. Zero PHI.
"""

from __future__ import annotations

import copy
from typing import Any

#: Conditions a DIF audit asks the model to decide.
DECISION_TARGET_CONDITIONS: tuple[str, ...] = ("sepsis", "stroke", "dka", "fabry")

#: Ground truth and labels that restate it.
ANSWER_FIELDS: frozenset[str] = frozenset(
    {
        "sepsis_flag",
        "stroke_flag",
        "dka_flag",
        "fabry_referral_flag",
        "dka_severity",
        "euglycemic_dka",
        "stroke_type",
        "fabry_phenotype",
        "referral_reason",
    }
)

#: Facts that only exist after the decision is made.
FUTURE_FIELDS: frozenset[str] = frozenset(
    {
        "hours_to_hypotension",
        "deterioration_pattern",
        "delayed_hypotension_flag",
        "fluid_input_6h_ml",
        "fluid_balance_6h_ml",
        "ventilation_mode",
        "tpa_eligible",
        "tpa_administered",
        "door_to_needle_minutes",
        "mrs_discharge",
        "mrs_90day",
        "alpha_gal_a_activity",
        "precipitant",
    }
)

#: Flags describing how the synthetic case was constructed, not observations.
GENERATOR_FIELDS: frozenset[str] = frozenset(
    {
        "cryptic_shock_flag",
        "normal_wbc_elevated_lactate_flag",
        "afebrile_tachycardic_flag",
        "afebrile_flag",
        "dm_htn_ckd_stack_flag",
        "altered_mental_status_only_flag",
        "sex_x_linked_note",
    }
)

#: Every observation key a blinded case never shows.
HIDDEN_OBSERVATION_FIELDS: frozenset[str] = ANSWER_FIELDS | FUTURE_FIELDS | GENERATOR_FIELDS

#: Neutral wording for a visit whose diagnosis is the answer.
MASKED_DIAGNOSIS = "a new health concern"


def is_hidden_observation(key: str) -> bool:
    """True when observation ``key`` must not reach a blinded case."""
    return key in HIDDEN_OBSERVATION_FIELDS or key.endswith("_observation_version")


def is_decision_target(condition_name: Any) -> bool:
    """True when ``condition_name`` names a condition the audit asks about."""
    return str(condition_name).lower() in DECISION_TARGET_CONDITIONS


def mask_diagnosis(diagnosis: Any) -> Any:
    """Replace a decision-target diagnosis with neutral wording; keep others."""
    return MASKED_DIAGNOSIS if is_decision_target(diagnosis) else diagnosis


def visible_observations(observations: dict[str, Any] | None) -> dict[str, Any]:
    """The observation bundle a clinician has at the decision moment.

    ``altered_mental_status_only_flag`` is a generator flag, but mental status
    itself is observable, so it is restated as ``mental_status`` when the bundle
    does not already carry one.
    """
    obs = observations or {}
    visible = {k: copy.deepcopy(v) for k, v in obs.items() if not is_hidden_observation(k)}
    if "altered_mental_status_only_flag" in obs and "mental_status" not in visible:
        visible["mental_status"] = "altered" if obs["altered_mental_status_only_flag"] else "alert"
    return visible


def blind_record(record: dict[str, Any]) -> dict[str, Any]:
    """Return a blinded, decision-time copy of a ``Patient.to_dict()`` record.

    The input is not modified. Decision-target conditions are removed, every
    visit's target diagnosis is masked, and hidden observation fields are
    dropped (see :data:`HIDDEN_OBSERVATION_FIELDS`). The seed is dropped too: it
    identifies the generator draw, not the patient.
    """
    out = copy.deepcopy(record)
    demographics = out.get("demographics")
    if isinstance(demographics, dict):
        demographics.pop("seed", None)
    out["conditions"] = [
        c for c in out.get("conditions", []) or [] if not is_decision_target(c.get("name"))
    ]
    for visit in out.get("visits", []) or []:
        if "primary_diagnosis" in visit:
            visit["primary_diagnosis"] = mask_diagnosis(visit["primary_diagnosis"])
    out["observations"] = visible_observations(record.get("observations"))
    return out
