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

"""Published clinical scores, reimplemented, as reference models for 7AAST.

These are the rules hospitals actually run, so testing them shows how a
deployed rule behaves on the patients 7AAST builds, and whether 7AAST
reproduces what the literature already knows about them (qSOFA misses many
cases, SIRS raises many false alarms).

=================  =========  ==========================================================
Name               Condition  Rule (positive when)
=================  =========  ==========================================================
``qsofa``          sepsis     Suspected infection and qSOFA >= 2: RR >= 22, SBP <= 100,
                              altered mentation (Seymour et al., JAMA 2016).
``sirs``           sepsis     Suspected infection and >= 2 SIRS criteria: temp > 38 or
                              < 36 C, HR > 90, RR > 20, WBC > 12 or < 4 (Bone et al.,
                              Chest 1992).
``news2``          sepsis     National Early Warning Score 2 >= 5 (RCP 2017), as a
                              ``score`` model with threshold 5. Oxygen support is
                              hidden at decision time, so air is assumed.
``rosier``         stroke     ROSIER > 0 (Nor et al., Lancet Neurol 2005), with the
                              deficit items approximated from the NIHSS (records carry
                              the score, not each item); hypoglycaemia (< 63 mg/dL) is
                              excluded first, as ROSIER requires.
``ada_dka``        dka        ADA 2024 consensus: glucose >= 200 or known diabetes,
                              ketones, acidosis; bedside-only: glucose >= 250 and urine
                              ketones (Umpierrez et al., Diabetes Care 2024).
=================  =========  ==========================================================

They read both written cases and records, like the demo models. Reports name
them ``reference: <score>`` and say they are reimplementations, not a vendor's
product. Pure standard library.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from hipaasynth.aast.adapter import ModelAdapter
from hipaasynth.aast.demo import _f, _record_measurements, _rule, _text_measurements, _yes

_NO_INFECTION = ("none_suspected", None, "None")


def _infection(m: dict[str, Any]) -> bool:
    return m.get("Suspected infection source") not in _NO_INFECTION


def _altered(m: dict[str, Any]) -> bool:
    return str(m.get("Mental status", "alert")).lower() not in ("alert", "none")


def qsofa(m: dict[str, Any]) -> bool | None:
    rr, sbp = _f(m.get("RR")), _f(m.get("SBP"))
    if rr is None and sbp is None:
        return None
    points = int((rr or 0) >= 22) + int((sbp or 999) <= 100) + int(_altered(m))
    return _infection(m) and points >= 2


def sirs(m: dict[str, Any]) -> bool | None:
    temp, hr, rr, wbc = (_f(m.get(k)) for k in ("Temp", "HR", "RR", "WBC"))
    if temp is None and hr is None and rr is None:
        return None
    points = int(temp is not None and (temp > 38.0 or temp < 36.0))
    points += int((hr or 0) > 90) + int((rr or 0) > 20)
    points += int(wbc is not None and (wbc > 12.0 or wbc < 4.0))
    return _infection(m) and points >= 2


def _band(value: float | None, bands: list[tuple[float, int]], top: int) -> int:
    if value is None:
        return 0
    for upper, points in bands:
        if value <= upper:
            return points
    return top


def news2(m: dict[str, Any]) -> float | None:
    rr, spo2, sbp, hr, temp = (_f(m.get(k)) for k in ("RR", "SpO2", "SBP", "HR", "Temp"))
    if rr is None and sbp is None and hr is None:
        return None
    score = _band(rr, [(8, 3), (11, 1), (20, 0), (24, 2)], 3)
    score += _band(spo2, [(91, 3), (93, 2), (95, 1)], 0)
    score += _band(sbp, [(90, 3), (100, 2), (110, 1), (219, 0)], 3)
    score += _band(hr, [(40, 3), (50, 1), (90, 0), (110, 1), (130, 2)], 3)
    score += _band(temp, [(35.0, 3), (36.0, 1), (38.0, 0), (39.0, 1)], 2)
    score += 3 if _altered(m) else 0
    return float(score)


def rosier(m: dict[str, Any]) -> bool | None:
    nihss, glucose = _f(m.get("NIHSS")), _f(m.get("Glucose"))
    if nihss is None:
        return None
    if glucose is not None and glucose < 63:
        return False
    deficits = int(nihss >= 1) + int(nihss >= 4) + int(nihss >= 10)
    return deficits - int(_yes(m.get("Seizure at onset"))) > 0


def ada_dka(m: dict[str, Any]) -> bool | None:
    return _rule("dka", m)


REFERENCE_MODELS: dict[str, tuple[str, str, Callable[[dict[str, Any]], Any]]] = {
    "qsofa": ("sepsis", "binary", qsofa),
    "sirs": ("sepsis", "binary", sirs),
    "news2": ("sepsis", "score", news2),
    "rosier": ("stroke", "binary", rosier),
    "ada_dka": ("dka", "binary", ada_dka),
}


def reference_adapter(name: str, input_type: str) -> ModelAdapter:
    """A :class:`ModelAdapter` for reference score ``name`` reading ``input_type`` cases."""
    if name not in REFERENCE_MODELS:
        raise ValueError(f"reference model must be one of {', '.join(REFERENCE_MODELS)}")
    _condition, output, rule = REFERENCE_MODELS[name]

    def model(case: Any) -> Any:
        m = _text_measurements(case) if input_type == "text" else _record_measurements(case)
        value = rule(m)
        if value is None:
            return 0.0 if output == "score" else False
        return value

    settings: dict[str, Any] = {"threshold": 5.0} if output == "score" else {}
    return ModelAdapter(model, output, input=input_type, name=f"reference: {name}", **settings)


def reference_condition(name: str) -> str:
    """The condition reference score ``name`` decides."""
    return REFERENCE_MODELS[name][0]
