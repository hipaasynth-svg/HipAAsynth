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

"""DEMO models, so 7AAST can be tried without a model of your own.

These are not clinical tools and their results are labelled DEMO everywhere.

``demo_guideline``  Textbook rules on whatever the case shows. Reads the
                    numbers when they are there and the described symptoms
                    when they are not.
``demo_biased``     The same rules, but it only reads numbers (so it misses
                    patients who describe their symptoms in their own words)
                    and, for structured records, misses half of the true cases
                    in Black and Native patients. It exists to show what a
                    failing report looks like.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any

from hipaasynth.aast.adapter import ModelAdapter
from hipaasynth.aast.cases import case_id

DEMO_MODELS = ("demo_guideline", "demo_biased")

_NO_INFECTION = ("none_suspected", None)


def _f(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(str(value).split()[0].rstrip("%°C"))
    except ValueError:
        return None


def _yes(value: Any) -> bool:
    return value is True or str(value).strip().lower() == "yes"


def _rule(condition: str, m: dict[str, Any]) -> bool | None:
    """Textbook rule on a measurement dict keyed like the blinded labels.

    Returns None when the needed measurements are absent.
    """
    if condition == "sepsis":
        rr, sbp, lactate = _f(m.get("RR")), _f(m.get("SBP")), _f(m.get("Lactate"))
        if rr is None and sbp is None and lactate is None:
            return None
        infection = m.get("Suspected infection source") not in _NO_INFECTION
        qsofa = int((rr or 0) >= 22) + int((sbp or 999) <= 100)
        qsofa += int(str(m.get("Mental status", "alert")).lower() not in ("alert", "none"))
        return bool(infection and (qsofa >= 2 or (lactate or 0) >= 2.0))
    if condition == "stroke":
        nihss = _f(m.get("NIHSS"))
        if nihss is None:
            return None
        glucose = _f(m.get("Glucose"))
        return bool(
            nihss >= 1
            and (glucose is None or glucose >= 60)
            and not _yes(m.get("Seizure at onset"))
            and not _yes(m.get("Forehead weakness on the affected side"))
            and not (_yes(m.get("History of migraine")) and nihss <= 3)
        )
    if condition == "dka":
        ph, hco3 = _f(m.get("pH")), _f(m.get("HCO3"))
        bohb, glucose = _f(m.get("Beta-hydroxybutyrate")), _f(m.get("Glucose"))
        diabetic = str(m.get("Diabetes type", "")).lower() in ("type1", "type2")
        if hco3 is None and ph is None and glucose is None:
            return None
        if ph is not None or bohb is not None:
            return bool(diabetic and (ph or 7.4) < 7.30 and (hco3 or 24) < 18 and (bohb or 0) >= 3)
        return bool(diabetic and (hco3 or 24) < 18 and (glucose or 0) >= 250)
    if condition == "fabry":
        findings = m.get("Findings")
        if findings is None:
            return None
        n = 0 if findings == "none specific" else len(str(findings).split(","))
        return n >= 2
    raise ValueError(f"unknown condition {condition!r}")


_SYMPTOM_RULES: dict[str, Callable[[str], bool]] = {
    "sepsis": lambda t: ("hot" in t or "cold" in t)
    and ("fast" in t or "racing" in t)
    and ("confused" in t or "faint" in t or "dizzy" in t or "weak" in t),
    "stroke": lambda t: "face" in t
    and ("speech" in t or "words" in t or "weak" in t)
    and "shaking all over" not in t
    and "forehead" not in t
    and "shaky" not in t,
    "dka": lambda t: "thirsty" in t and ("breath" in t or "breathing fast" in t),
    "fabry": lambda t: "burn" in t and ("sweat" in t or "family" in t),
}


def _text_measurements(text: str) -> dict[str, str]:
    """Measurements from a blinded form's ``Label value | Label value`` text.

    Works on every form that carries the decision-time line (clinician note,
    mid-level note, high-literacy patient message); returns ``{}`` on forms
    that only describe symptoms.
    """
    out: dict[str, str] = {}
    if text.lstrip().startswith("{"):
        try:
            bundle = json.loads(text)
        except ValueError:
            return out
        for entry in bundle.get("entry", []):
            resource = entry.get("resource", {})
            label = resource.get("code", {}).get("text")
            if resource.get("resourceType") == "Observation" and label in _LABELS:
                out.setdefault(label, str(resource.get("valueString")))
        return out
    for label in _LABELS:
        match = re.search(
            rf"(?:^|\| |: |\n\s*){re.escape(label)} (.+?)(?= \||\.\s|\.$|$)",
            text,
            re.MULTILINE,
        )
        if match:
            out[label] = match.group(1).strip()
    return out


_LABELS = (
    "Temp", "HR", "RR", "SBP", "DBP", "SpO2", "O2 device", "FiO2", "Mental status", "Lactate",
    "WBC", "Creatinine", "Glucose", "Urine output", "Suspected infection source", "NIHSS",
    "Onset-to-door", "Atrial fibrillation", "Prior stroke", "Anticoagulant use",
    "Prior intracranial hemorrhage", "Recent major surgery", "Seizure at onset",
    "History of migraine", "Forehead weakness on the affected side", "pH", "HCO3", "Anion gap",
    "Beta-hydroxybutyrate", "Urine ketones", "Potassium", "Diabetes type", "Findings",
)  # fmt: skip

# Observation key -> blinded label, for records.
_RECORD_LABELS = {
    "temperature_c_initial": "Temp", "heart_rate_initial": "HR", "resp_rate_initial": "RR",
    "sbp_initial": "SBP", "lactate_initial": "Lactate", "mental_status": "Mental status",
    "suspected_infection_source": "Suspected infection source", "nihss_score": "NIHSS",
    "glucose_admission": "Glucose", "seizure_at_onset": "Seizure at onset",
    "migraine_history": "History of migraine",
    "forehead_weakness": "Forehead weakness on the affected side", "arterial_ph": "pH",
    "bicarbonate_meq_l": "HCO3", "beta_hydroxybutyrate_mmol_l": "Beta-hydroxybutyrate",
    "glucose_mg_dl": "Glucose", "diabetes_type": "Diabetes type",
}  # fmt: skip

_FABRY_KEYS = (
    "neuropathic_pain", "hypohidrosis", "angiokeratoma", "cornea_verticillata", "proteinuria",
    "left_ventricular_hypertrophy", "cryptogenic_stroke_young", "family_history_fabry",
)  # fmt: skip


def _record_measurements(record: dict[str, Any]) -> dict[str, Any]:
    obs = record.get("observations") or {}
    out = {label: obs[key] for key, label in _RECORD_LABELS.items() if obs.get(key) is not None}
    if any(k in obs for k in _FABRY_KEYS):
        found = [k for k in _FABRY_KEYS if obs.get(k)]
        out["Findings"] = ", ".join(found) if found else "none specific"
    return out


def _coin(case: Any) -> bool:
    # Content hash, so the same case gets the same answer however it was stored.
    return int(case_id(case)[:2], 16) % 2 == 0


def demo_adapter(name: str, condition: str, input_type: str) -> ModelAdapter:
    """A DEMO :class:`ModelAdapter` for ``condition`` reading ``input_type`` cases."""
    if name not in DEMO_MODELS:
        raise ValueError(f"demo model must be one of {DEMO_MODELS}, got {name!r}")
    biased = name == "demo_biased"

    def model(case: Any) -> bool:
        if input_type == "text":
            decision = _rule(condition, _text_measurements(case))
            if decision is None:
                decision = False if biased else _SYMPTOM_RULES[condition](case.lower())
            return decision
        decision = bool(_rule(condition, _record_measurements(case)))
        ethnicity = (case.get("demographics") or {}).get("ethnicity")
        if biased and decision and ethnicity in ("black", "native") and _coin(case):
            return False
        return decision

    return ModelAdapter(model, "binary", input=input_type, name=f"{name} (DEMO)")
