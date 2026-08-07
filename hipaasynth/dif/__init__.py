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

from hipaasynth.dif.framework import DIFConfig, run_audit
from hipaasynth.dif.report import (
    CohortFairnessSummary,
    FairnessPassport,
    per_form_error_rates,
    summarize_cohort,
    write_passport_bundle,
)
from hipaasynth.dif.stability import (
    BootstrapUncertainty,
    ConceptDriftResult,
    StabilityReport,
    ThresholdSensitivity,
    bootstrap_uncertainty,
    concept_drift,
    stability_report,
    threshold_sensitivity,
)

__all__ = [
    "DIFConfig",
    "FairnessPassport",
    "CohortFairnessSummary",
    "run_audit",
    "summarize_cohort",
    "per_form_error_rates",
    "write_passport_bundle",
    "ConceptDriftResult",
    "BootstrapUncertainty",
    "ThresholdSensitivity",
    "StabilityReport",
    "concept_drift",
    "bootstrap_uncertainty",
    "threshold_sensitivity",
    "stability_report",
]
