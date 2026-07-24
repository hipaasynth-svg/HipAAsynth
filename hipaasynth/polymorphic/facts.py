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

"""Canonical clinical fact set for the polymorphic form engine.

WHY THIS EXISTS (audit finding F1)
----------------------------------
A fairness stress-test's central claim is that decision divergence across the
seven forms is attributable to **documentation form**, not to differences in the
underlying clinical facts. That claim only holds if every form encodes the *same
facts*. This module defines the canonical fact set for a patient and a way to
measure which facts a rendered form actually carries, so that:

  * ``same_facts`` mode can be *verified* (every form encodes every fact), and
  * ``realistic_missingness`` mode can *measure* what each form omits, turning
    missingness into an explicit, controlled axis rather than a silent one.

The fact set separates two categories:

  * ALWAYS-PRESENT facts — patient identity, active conditions, acute status.
    These must appear in every form in every mode; dropping them would make the
    forms clinically different patients, not different documentation styles.
  * OMISSIBLE facts — the numeric labs. In ``same_facts`` mode they appear in
    every form; in ``realistic_missingness`` mode a form may omit them, and the
    omission is recorded and measured.

Pure standard library. Zero PHI.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple


def humanize(name: str) -> str:
    """Turn a snake_case condition name into human words (``copd`` stays as-is)."""
    return name.replace("_", " ")


def format_lab_value(value: float) -> str:
    """Canonical string rendering of a lab value.

    Centralized so form builders and the coverage checker agree byte-for-byte on
    how a numeric lab appears in text (the substring the coverage check looks
    for).
    """
    return f"{value}"


@dataclass(frozen=True)
class ClinicalFactSet:
    """The canonical clinical facts a form must (potentially) convey.

    Extracted once from the ``Patient`` and shared by every form, so any two
    forms encode the same underlying facts by construction. Instances are
    hashable/frozen and order-stable (conditions and labs are sorted) so a fact
    set participates cleanly in deterministic hashing.
    """

    patient_id: str
    age: int
    sex: str
    active_conditions: Tuple[str, ...]
    acute_flag: bool
    acute_type: Optional[str]  # 'sepsis' | 'stroke' | None
    labs: Tuple[Tuple[str, float], ...]  # (lab_name, value), sorted by name

    def condition_tokens(self) -> List[str]:
        """Lowercased humanized condition substrings (for display/reporting)."""
        return [humanize(c).lower() for c in self.active_conditions]

    def lab_value_tokens(self) -> List[str]:
        """Canonical lab-value substrings expected when labs are included."""
        return [format_lab_value(v) for _, v in self.labs]


def _condition_present(low_text: str, condition: str) -> bool:
    """True if ``condition`` appears in ``low_text`` in either raw snake_case or
    humanized form. Different forms spell conditions differently — clinician/FHIR
    forms keep the raw ``chronic_kidney_disease`` token, patient forms humanize to
    ``chronic kidney disease`` — so a fact is "present" if *either* spelling
    appears.
    """
    raw = condition.lower()
    human = humanize(condition).lower()
    return raw in low_text or human in low_text


def extract_fact_set(patient: Any) -> ClinicalFactSet:
    """Build the canonical :class:`ClinicalFactSet` for ``patient``.

    Acute status is read from the observation bundle (``sepsis_flag`` /
    ``stroke_flag`` / ``dka_flag`` / ``fabry_referral_flag``) so it is consistent
    with the acuity a form renders. Labs are taken from the most recent visit —
    the same visit the form builders render.
    """
    obs = patient.observations or {}
    acute_type: Optional[str] = None
    if obs.get("sepsis_flag"):
        acute_type = "sepsis"
    elif obs.get("stroke_flag"):
        acute_type = "stroke"
    elif obs.get("dka_flag"):
        acute_type = "dka"
    elif obs.get("fabry_referral_flag"):
        acute_type = "fabry_referral"

    labs: List[Tuple[str, float]] = []
    if patient.visits:
        for lab in patient.visits[-1].labs:
            labs.append((lab.lab_name, lab.value))
    labs.sort(key=lambda kv: kv[0])

    active_conditions = tuple(sorted(c.name for c in patient.conditions if c.active))

    return ClinicalFactSet(
        patient_id=patient.demographics.patient_id,
        age=patient.demographics.age,
        sex=patient.demographics.sex,
        active_conditions=active_conditions,
        acute_flag=bool(acute_type),
        acute_type=acute_type,
        labs=tuple(labs),
    )


def fact_coverage(text: str, facts: ClinicalFactSet) -> Dict[str, Any]:
    """Measure which facts a rendered form ``text`` carries.

    Returns a dict with, per category, the present/missing tokens and a
    ``covered`` flag. Substring matching on lowercased text — deliberately
    simple, deterministic, and dependency-free (the form builders use the exact
    canonical token strings, so exact-substring coverage is reliable).
    """
    low = text.lower()

    cond_present = [
        humanize(c).lower() for c in facts.active_conditions if _condition_present(low, c)
    ]
    cond_missing = [
        humanize(c).lower() for c in facts.active_conditions if not _condition_present(low, c)
    ]

    lab_tokens = facts.lab_value_tokens()
    lab_present = [t for t in lab_tokens if t in low]
    lab_missing = [t for t in lab_tokens if t not in low]

    return {
        "conditions": {
            "present": cond_present,
            "missing": cond_missing,
            "covered": not cond_missing,
        },
        "labs": {
            "present": lab_present,
            "missing": lab_missing,
            "covered": not lab_missing,
        },
    }


def structured_fact_coverage(fhir_text: str, facts: ClinicalFactSet) -> Dict[str, Any]:
    """Measure fact coverage for a *structured* (FHIR) form.

    A FHIR bundle encodes conditions and labs as coded resources (Condition /
    Observation), not as English text, so lexical coverage does not apply. A
    condition/lab fact is "present" when the bundle carries at least as many
    Condition/Observation resources as there are active conditions / labs — the
    coded equivalent of surfacing the fact.
    """
    try:
        bundle = json.loads(fhir_text)
        resources = [entry.get("resource", {}) for entry in bundle.get("entry", [])]
    except (ValueError, AttributeError):
        resources = []

    n_condition = sum(1 for r in resources if r.get("resourceType") == "Condition")
    n_observation = sum(1 for r in resources if r.get("resourceType") == "Observation")

    return {
        "conditions": {
            "present": n_condition,
            "expected": len(facts.active_conditions),
            "missing": [],
            "covered": n_condition >= len(facts.active_conditions),
        },
        "labs": {
            "present": n_observation,
            "expected": len(facts.labs),
            "missing": [],
            "covered": n_observation >= len(facts.labs),
        },
    }


# Categories that MUST be present in every form, in every information mode.
ALWAYS_PRESENT_CATEGORIES: Tuple[str, ...] = ("conditions",)
# Categories that may be omitted only under realistic_missingness mode.
OMISSIBLE_CATEGORIES: Tuple[str, ...] = ("labs",)
