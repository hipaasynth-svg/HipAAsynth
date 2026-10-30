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

from hipaasynth.core.anchor import Anchor
from hipaasynth.core.anchor_stamp import stamp_population, build_metadata
from hipaasynth.core.config import (
    GenerationConfig,
    ENGINE_VERSION,
    SCHEMA_VERSION,
    DEFAULT_SYNTHETIC_DISCLAIMER,
)
from hipaasynth.core.schema import Patient, Demographics, Condition, Visit
from hipaasynth.core.profile_loader import load_population_profile
from hipaasynth.core.model_interface import ModelInterface, MockClinicalModel, ScoredMockModel

__all__ = [
    "Anchor",
    "Condition",
    "DEFAULT_SYNTHETIC_DISCLAIMER",
    "Demographics",
    "ENGINE_VERSION",
    "GenerationConfig",
    "MockClinicalModel",
    "ModelInterface",
    "Patient",
    "SCHEMA_VERSION",
    "ScoredMockModel",
    "Visit",
    "build_metadata",
    "load_population_profile",
    "stamp_population",
]
