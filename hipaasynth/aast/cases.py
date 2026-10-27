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

"""What the model under test is shown: blinded cases and their controlled variants.

Every 7AAST case is blinded and decision-time (see polymorphic/blinding.py). A
``text`` model gets a rendered form, a ``record`` model gets a blinded record.
The variants below change one controlled thing about the *same* patient, so
any change in the model's answer is attributable to that one thing.

Care settings (Axis 6) remove the tests a setting cannot run, following the
evidence that specific tests (lactate, arterial blood gas, ketones) are missing
or late in critical access and remote settings, not random fields:

``hospital``         everything.
``critical_access``  no lactate, no arterial pH, no beta-hydroxybutyrate.
``clinic``           vitals, exam and point-of-care glucose and urine only.

Fragmented care (Axis 7) removes the patient's history: chronic conditions,
prior visits and labs, medications and history-based findings, as when the
patient's records sit in another health system.

Pure standard library. Zero PHI.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from typing import Any

from hipaasynth.core.schema import Patient
from hipaasynth.polymorphic.blinding import blind_record
from hipaasynth.polymorphic.forms import INFO_MODE_BLINDED, Form, PolymorphicFormEngine

#: The canonical text presentation for cohort-level measures (accuracy, groups,
#: care settings, twins). Axes 1-4 use all seven forms.
CANONICAL_FORM = Form.PHYSICIAN_SOAP

CARE_SETTINGS = ("hospital", "critical_access", "clinic")

#: Observation keys each setting cannot provide.
_SETTING_REMOVES: dict[str, frozenset[str]] = {
    "hospital": frozenset(),
    "critical_access": frozenset({"lactate_initial", "arterial_ph", "beta_hydroxybutyrate_mmol_l"}),
    "clinic": frozenset(
        {
            "lactate_initial",
            "arterial_ph",
            "beta_hydroxybutyrate_mmol_l",
            "wbc_initial",
            "creatinine_initial",
            "glucose_initial",
            "bicarbonate_meq_l",
            "anion_gap",
            "potassium_meq_l",
        }
    ),
}

#: History-based observation keys a fragmented record loses.
_HISTORY_KEYS = frozenset(
    {
        "diabetes_flag",
        "hypertension_flag",
        "ckd_flag",
        "chronic_kidney_disease",
        "atrial_fibrillation",
        "prior_stroke",
        "prior_ich",
        "anticoagulant_use",
        "migraine_history",
        "family_history_fabry",
        "diabetes_type",
    }
)

_ENGINE = PolymorphicFormEngine(information_mode=INFO_MODE_BLINDED)


def present(patient: Patient, input_type: str, form: Form | str = CANONICAL_FORM) -> Any:
    """The blinded case a model with ``input_type`` is shown for ``patient``."""
    if input_type == "record":
        return blind_record(patient.to_dict())
    if input_type == "text":
        return _ENGINE.express(patient, form)["full_text"]
    raise ValueError(f"input_type must be 'text' or 'record', got {input_type!r}")


def case_id(case: Any) -> str:
    """Content hash of a case: the same case always has the same id."""
    if isinstance(case, str):
        payload = case.encode("utf-8")
    else:
        payload = json.dumps(case, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(payload).hexdigest()


def _with_observations(patient: Patient, drop: frozenset[str]) -> Patient:
    obs = {k: (None if k in drop else v) for k, v in (patient.observations or {}).items()}
    return dataclasses.replace(patient, observations=obs)


def in_setting(patient: Patient, setting: str) -> Patient:
    """``patient`` as seen in care ``setting`` (tests the setting lacks are absent)."""
    if setting not in _SETTING_REMOVES:
        raise ValueError(f"setting must be one of {CARE_SETTINGS}, got {setting!r}")
    return _with_observations(patient, _SETTING_REMOVES[setting])


def fragmented(patient: Patient) -> Patient:
    """``patient`` arriving with no history on file (records held elsewhere)."""
    p = _with_observations(patient, _HISTORY_KEYS)
    current = p.visits[-1:] if p.visits else []
    current = [dataclasses.replace(v, labs=[]) for v in current]
    return dataclasses.replace(p, conditions=[], visits=current, medications=[])


def twin(patient: Patient, attribute: str, value: str) -> Patient:
    """``patient`` with one demographic ``attribute`` (``ethnicity``/``sex``) changed."""
    if attribute not in ("ethnicity", "sex"):
        raise ValueError(f"attribute must be 'ethnicity' or 'sex', got {attribute!r}")
    if attribute == "ethnicity":
        demographics = dataclasses.replace(patient.demographics, ethnicity=value)
    else:
        demographics = dataclasses.replace(patient.demographics, sex=value)
    return dataclasses.replace(patient, demographics=demographics)


def control(patient: Patient) -> Patient:
    """``patient`` with a clinically irrelevant change: the visit date moves a day.

    The control perturbation of a baseline-aware counterfactual audit: a model
    whose answer changes this often under an irrelevant edit cannot be said to
    react to demographics when it changes that often under a demographic edit.
    """
    if not patient.visits:
        return dataclasses.replace(
            patient,
            anthropometrics=dataclasses.replace(
                patient.anthropometrics, bmi=round(patient.anthropometrics.bmi + 0.1, 1)
            ),
        )
    last = patient.visits[-1]
    year, month, day = (int(x) for x in last.visit_date.split("-"))
    day = day + 1 if day < 28 else day - 1
    moved = dataclasses.replace(last, visit_date=f"{year:04d}-{month:02d}-{day:02d}")
    return dataclasses.replace(patient, visits=[*patient.visits[:-1], moved])
