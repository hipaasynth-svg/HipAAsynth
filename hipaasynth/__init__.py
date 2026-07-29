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

"""hipaasynth: synthetic clinical record generation engine."""

from hipaasynth.psf import PSFGenerator, PSFAudit, PSFConfig, PSFResult, PSFReport, SPARSITY_LEVELS
from hipaasynth.cc import CCGenerator, CCAudit, CCConfig, CCResult, CCReport, CONTINUITY_PROFILES
from hipaasynth.core import (
    Anchor,
    build_metadata,
    stamp_population,
    GenerationConfig,
    ENGINE_VERSION,
    SCHEMA_VERSION,
    DEFAULT_SYNTHETIC_DISCLAIMER,
    Patient,
    Demographics,
    Condition,
    Visit,
    load_population_profile,
    ModelInterface,
    MockClinicalModel,
    ScoredMockModel,
)
from hipaasynth.sdk import generate, Cohort, MODULES, available_profiles

__all__ = [
    "PSFGenerator",
    "PSFAudit",
    "PSFConfig",
    "PSFResult",
    "PSFReport",
    "SPARSITY_LEVELS",
    "CCGenerator",
    "CCAudit",
    "CCConfig",
    "CCResult",
    "CCReport",
    "CONTINUITY_PROFILES",
    "Anchor",
    "build_metadata",
    "stamp_population",
    "GenerationConfig",
    "ENGINE_VERSION",
    "SCHEMA_VERSION",
    "DEFAULT_SYNTHETIC_DISCLAIMER",
    "Patient",
    "Demographics",
    "Condition",
    "Visit",
    "load_population_profile",
    "ModelInterface",
    "MockClinicalModel",
    "ScoredMockModel",
    "generate",
    "Cohort",
    "MODULES",
    "available_profiles",
]
