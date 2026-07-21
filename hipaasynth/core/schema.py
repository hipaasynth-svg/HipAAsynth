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

from dataclasses import dataclass, asdict, field
from typing import List, Any

@dataclass(frozen=True)
class Demographics:
    patient_id: str
    seed: int
    age: int
    sex: str
    ethnicity: str

@dataclass(frozen=True)
class Anthropometrics:
    height_cm: float
    weight_kg: float
    bmi: float
    bmi_category: str

@dataclass(frozen=True)
class Condition:
    name: str
    onset_age: int
    active: bool

@dataclass(frozen=True)
class LabResult:
    lab_name: str
    value: float
    unit: str
    reference_range: str
    date_recorded: str

@dataclass(frozen=True)
class Medication:
    name: str
    active: bool = True

@dataclass(frozen=True)
class Visit:
    visit_id: str
    visit_type: str
    visit_date: str
    primary_diagnosis: str
    labs: List[LabResult]

@dataclass(frozen=True)
class Patient:
    demographics: Demographics
    anthropometrics: Anthropometrics
    conditions: List[Condition]
    visits: List[Visit]
    engine_version: str
    schema_version: str
    synthetic: bool = True
    disclaimer: str = ""
    observations: dict[str, Any] = field(default_factory=dict)
    medications: List[Medication] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Return this record as a plain dict via dataclasses.asdict, for exporters
        and serializers. No side effects.
        """
        return asdict(self)
