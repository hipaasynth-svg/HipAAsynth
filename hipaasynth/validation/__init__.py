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

"""Trustworthiness checks for a generated cohort (Tier 4).

Three independent questions, one per module:

* :mod:`~hipaasynth.validation.fidelity` — *are the statistics plausible?*
  Lab marginals, condition prevalence, physiologically linked correlations,
  and temporal ordering. :func:`fidelity_report` is the aggregate.
* :mod:`~hipaasynth.validation.utility_probe` — *is the signal learnable?*
  :func:`downstream_utility_probe` trains a pure-Python logistic model on the
  synthetic cohort and reports held-out AUC and lift over the majority class.
* :mod:`~hipaasynth.validation.validator` — *is each record internally coherent?*
  Per-patient repair and clinical-plausibility checks.

Everything here is pure standard library and takes a plain sequence of
``Patient`` objects, so it composes with any cohort the engine produces.

The two aggregates are also reachable from the SDK as
:meth:`hipaasynth.sdk.Cohort.fidelity` and :meth:`hipaasynth.sdk.Cohort.utility`.

Note on scope: cohort *stability* (drift/uncertainty/sensitivity across two audit
runs) lives in :mod:`hipaasynth.dif.stability` rather than here, because it
consumes ``FairnessPassport`` pairs from the DIF audit, not patients.
"""

from hipaasynth.validation.fidelity import (
    LinkedCorrelation,
    TemporalConsistencyReport,
    condition_prevalence,
    fidelity_report,
    lab_value_marginals,
    linked_lab_correlations,
    pearson_correlation,
    temporal_consistency,
    visit_order_report,
)
from hipaasynth.validation.utility_probe import (
    DEFAULT_TARGET,
    LogisticModel,
    UtilityProbeResult,
    accuracy,
    downstream_utility_probe,
    extract_features,
    roc_auc,
    train_logistic,
)
from hipaasynth.validation.validator import (
    check_clinical_plausibility,
    check_lab_diagnosis_consistency,
    check_medication_timeline,
    find_clinical_plausibility_issues,
    validate_cohort,
    validate_patient,
    validate_patients,
)

__all__ = [
    "DEFAULT_TARGET",
    "LinkedCorrelation",
    "LogisticModel",
    "TemporalConsistencyReport",
    "UtilityProbeResult",
    "accuracy",
    "check_clinical_plausibility",
    "check_lab_diagnosis_consistency",
    "check_medication_timeline",
    "condition_prevalence",
    "downstream_utility_probe",
    "extract_features",
    "fidelity_report",
    "find_clinical_plausibility_issues",
    "lab_value_marginals",
    "linked_lab_correlations",
    "pearson_correlation",
    "roc_auc",
    "temporal_consistency",
    "train_logistic",
    "validate_cohort",
    "validate_patient",
    "validate_patients",
    "visit_order_report",
]
