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

"""A consistently wrong model must not pass the DIF audit.

Regression guard: DCS, ISG, LFDI and SAF all measure *consistency* across the
seven forms. A model that answers "no" for every acute stroke patient on every
form is perfectly consistent (DCS 1.0, gaps 0.0) and used to receive an
"Overall result: PASS" passport.
"""

import pytest

from hipaasynth.core.config import GenerationConfig
from hipaasynth.dif import DIFConfig, run_audit
from hipaasynth.dif.model_interface import MockBiasedModel, MockFairModel
from hipaasynth.pipelines.population_pipeline import generate_patients
from hipaasynth.polymorphic.metrics import PolymorphicMetricCalculator, PolymorphicMetrics


class _Always:
    def __init__(self, answer):
        self.answer = answer

    def predict(self, patient, form):
        return self.answer


def _audit(model, condition="stroke", **cfg):
    gen = GenerationConfig(patient_count=8, seed=1, required_condition=condition,
                           run_date="2026-01-01")
    return run_audit(model, generate_patients, gen, DIFConfig(**cfg))


@pytest.mark.parametrize("condition", ["sepsis", "stroke", "dka", "fabry"])
def test_model_that_never_flags_fails_on_positive_cases(condition):
    passports = [p for p in _audit(_Always(False), condition) if p.ground_truth]
    assert passports, "fixture must contain positive cases"
    assert not any(p.passed() for p in passports)
    assert all(p.metrics.accuracy == 0.0 and not p.metrics.accuracy_pass for p in passports)


def test_passport_markdown_reports_accuracy_and_fails():
    md = _audit(_Always(False))[0].to_markdown()
    assert "| Accuracy | 0.000 | FAIL |" in md
    assert "**Overall result:** FAIL" in md
    assert "Consistency alone is not safety" in md


def test_fair_model_still_passes_and_biased_still_fails():
    assert all(p.passed() for p in _audit(MockFairModel()))
    assert not any(p.passed() for p in _audit(MockBiasedModel()))


def test_floor_can_be_disabled():
    assert all(p.passed() for p in _audit(_Always(False), accuracy_threshold=0.0))


@pytest.mark.parametrize(
    "n_wrong, expected", [(0, True), (1, True), (2, False), (7, False)]
)
def test_threshold_boundary_one_wrong_form_of_seven_passes(n_wrong, expected):
    forms = [f"form{i}" for i in range(7)]
    decisions = {f: (i >= n_wrong) for i, f in enumerate(forms)}  # wrong ones are False
    m = PolymorphicMetricCalculator().calculate(decisions, ground_truth=True)
    assert m.accuracy == pytest.approx((7 - n_wrong) / 7)
    assert m.accuracy_pass is expected


def test_no_ground_truth_leaves_accuracy_unevaluated():
    m = PolymorphicMetricCalculator().calculate({"a": False, "b": False}, ground_truth=None)
    assert m.truth_evaluated is False and m.accuracy_pass is True


def test_no_decisions_fails_accuracy():
    m = PolymorphicMetricCalculator().calculate({}, ground_truth=True)
    assert m.accuracy == 0.0 and not m.accuracy_pass


def test_older_constructor_without_accuracy_still_works():
    m = PolymorphicMetrics(dcs=1.0, isg=0.0, lfdi=0.0, saf=0.0,
                           dcs_pass=True, isg_pass=True, lfdi_pass=True, saf_pass=True)
    assert m.all_pass()


def test_passport_seal_unchanged_by_accuracy_fields():
    # accuracy is derived from the already-sealed decisions + ground truth, so it is
    # deliberately not part of the seal: passports sealed before this change verify.
    p = _audit(MockFairModel())[0]
    assert "accuracy" not in p._seal_payload()["metrics"]
