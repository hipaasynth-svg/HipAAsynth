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

"""The DIF audit must not invent decisions from malformed model output.

Regression guard: ``run_audit`` stored ``bool(model.predict(...))``. A model
returning ``None`` was recorded as "do not treat" for every form and passed all
four polymorphic metrics; ``"no"`` was recorded as ``True``. It also ran
silently on cohorts with no positive ground truth, where under-triage cannot be
observed and a model that never flags anyone passes.
"""

import warnings

import pytest

from hipaasynth.core.config import GenerationConfig
from hipaasynth.dif import DIFConfig, run_audit
from hipaasynth.dif.model_interface import DecisionResult, MockBiasedModel, MockFairModel
from hipaasynth.pipelines.population_pipeline import generate_patients


def _cfg(condition="stroke", n=3):
    return GenerationConfig(patient_count=n, seed=1, required_condition=condition,
                            run_date="2026-01-01")


class _Returns:
    def __init__(self, value):
        self.value = value

    def predict(self, patient, form):
        return self.value


@pytest.mark.parametrize("bad", [None, "yes", "no", 1, 0, 0.5, [], {}])
def test_non_boolean_prediction_is_rejected(bad):
    with pytest.raises(TypeError, match="expected bool or DecisionResult"):
        run_audit(_Returns(bad), generate_patients, _cfg(), DIFConfig())


@pytest.mark.parametrize("bad", ["yes", 1])
def test_non_boolean_decision_inside_decision_result_is_rejected(bad):
    model = _Returns(DecisionResult(raw_response="x", decision=bad, refused=False,
                                    parse_confidence=1.0))
    with pytest.raises(TypeError, match="expected bool or DecisionResult"):
        run_audit(model, generate_patients, _cfg(), DIFConfig())


def test_boolean_and_decision_result_still_accepted():
    for model in (
        MockFairModel(),
        _Returns(True),
        _Returns(DecisionResult(raw_response="YES", decision=True, refused=False,
                                parse_confidence=1.0)),
        _Returns(DecisionResult(raw_response="?", decision=None, refused=False,
                                parse_confidence=0.0)),
        _Returns(DecisionResult(raw_response="no", decision=None, refused=True,
                                parse_confidence=0.0)),
    ):
        assert len(run_audit(model, generate_patients, _cfg(), DIFConfig())) == 3


def test_numpy_bool_accepted_without_numpy_dependency():
    class bool_:  # same type name as numpy.bool_
        def __init__(self, v):
            self.v = v

        def __bool__(self):
            return self.v

    passports = run_audit(_Returns(bool_(True)), generate_patients, _cfg(), DIFConfig())
    assert all(all(d is True for d in p.decisions.values()) for p in passports)


def test_warns_when_cohort_has_no_positive_ground_truth():
    with pytest.warns(UserWarning, match="no patient in this cohort has a positive ground truth"):
        run_audit(MockBiasedModel(), generate_patients, _cfg(condition="copd"), DIFConfig())


@pytest.mark.parametrize("condition", ["sepsis", "stroke", "dka", "fabry"])
def test_no_warning_when_cohort_has_positives(condition):
    with warnings.catch_warnings():
        warnings.simplefilter("error", UserWarning)
        run_audit(MockBiasedModel(), generate_patients, _cfg(condition=condition, n=10),
                  DIFConfig())
