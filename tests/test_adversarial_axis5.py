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

"""First tests for 7AAST Axis 5 (hipaasynth/adversarial).

The package had no tests at all although CHANGELOG 1.0.0 lists all seven axes
as "implemented and tested". Also guards the Evaluator accuracy fix: slices
with no patient record or no supported condition were counted in ``total``
and silently lowered ``accuracy()``.
"""

import copy

import pytest

from hipaasynth.adversarial import Evaluator, PerturbationEngine, Reducer, TemporalEngine
from hipaasynth.adversarial.evaluator import _build_prompt, _detect_condition


@pytest.fixture(scope="module")
def sepsis_timelines():
    return TemporalEngine(seed=42, years=1, condition="sepsis").generate()


def _always(answer):
    return lambda prompt: f"reasoning...\nFINAL_ANSWER: {answer}"


def test_sepsis_cohort_has_positive_ground_truth(sepsis_timelines):
    flags = [
        t["_patient_dict"]["observations"]["sepsis_flag"]
        for p in sepsis_timelines
        for t in p["timeline"]
    ]
    assert flags and all(flags)


def test_always_no_model_scores_zero_and_every_slice_is_a_failure(sepsis_timelines):
    ev = Evaluator()
    failures = ev.evaluate(sepsis_timelines, _always("No"))
    assert ev.accuracy() == 0.0
    assert len(failures) == ev.total == 50 and ev.skipped == 0


def test_always_yes_model_scores_one_on_all_positive_cohort(sepsis_timelines):
    ev = Evaluator()
    assert ev.evaluate(sepsis_timelines, _always("Yes")) == []
    assert ev.accuracy() == 1.0


def test_unparseable_answers_are_failures_with_error_minus_one(sepsis_timelines):
    ev = Evaluator()
    failures = ev.evaluate(sepsis_timelines[:3], lambda prompt: "I am not sure.")
    assert ev.unparseable == 3 and ev.accuracy() == 0.0
    assert all(f["error"] == -1 and f["predicted"] is None for f in failures)


def test_skipped_slices_do_not_lower_accuracy(sepsis_timelines):
    timelines = copy.deepcopy(sepsis_timelines[:2])
    no_record = {"_meta": {"year": 0}}  # no _patient_dict
    unsupported = copy.deepcopy(timelines[0]["timeline"][0])
    unsupported["_patient_dict"]["observations"] = {"copd_flag": True}  # no sepsis/stroke flag
    timelines.append({"patient_id": "SKIP", "timeline": [no_record, unsupported]})

    ev = Evaluator()
    ev.evaluate(timelines, _always("Yes"))
    assert (ev.total, ev.correct, ev.skipped) == (2, 2, 2)
    assert ev.accuracy() == 1.0  # was 0.5 when skipped slices counted in total


def test_accuracy_is_none_when_nothing_evaluated():
    ev = Evaluator()
    ev.evaluate([], _always("Yes"))
    assert ev.accuracy() is None


def test_condition_detection_and_prompt(sepsis_timelines):
    pd = sepsis_timelines[0]["timeline"][0]["_patient_dict"]
    assert _detect_condition(pd) == "sepsis"
    assert "FINAL_ANSWER" in _build_prompt(pd, "sepsis")


def test_temporal_generation_is_deterministic():
    a = TemporalEngine(seed=7, years=2, condition="stroke").generate()
    b = TemporalEngine(seed=7, years=2, condition="stroke").generate()
    assert [p["patient_id"] for p in a] == [p["patient_id"] for p in b]


@pytest.mark.parametrize("months", [5, 24, "12"])
def test_temporal_rejects_unsupported_drift(months):
    with pytest.raises(ValueError, match="drift_months"):
        TemporalEngine(seed=1, years=1, drift_months=months)


def test_missingness_never_removes_ground_truth_and_is_deterministic(sepsis_timelines):
    a = PerturbationEngine().apply_missingness(copy.deepcopy(sepsis_timelines), 0.2)
    b = PerturbationEngine().apply_missingness(copy.deepcopy(sepsis_timelines), 0.2)
    for pa, pb in zip(a, b, strict=True):
        for ta, tb in zip(pa["timeline"], pb["timeline"], strict=True):
            assert ta["_patient_dict"]["observations"]["sepsis_flag"] is True
            assert ta["_patient_dict"] == tb["_patient_dict"]
    nulled = sum(
        v is None
        for p in a
        for t in p["timeline"]
        for v in t["_patient_dict"]["observations"].values()
    )
    original = sum(
        v is None
        for p in sepsis_timelines
        for t in p["timeline"]
        for v in t["_patient_dict"]["observations"].values()
    )
    assert nulled > original


def test_missingness_does_not_mutate_the_input(sepsis_timelines):
    # apply_missingness rebinds each state's _patient_dict to a nulled deep
    # copy (documented in-place behaviour); the original dict must survive.
    original = sepsis_timelines[0]["timeline"][0]["_patient_dict"]
    before = copy.deepcopy(original)
    PerturbationEngine().apply_missingness(sepsis_timelines, 0.2)
    assert sepsis_timelines[0]["timeline"][0]["_patient_dict"] is not original
    assert original == before


def test_reducer_shrinks_a_failure_set_to_at_most_ten(sepsis_timelines):
    ev = Evaluator()
    failures = ev.evaluate(sepsis_timelines, _always("No"))
    reduced = Reducer(ev, _always("No")).reduce(failures)
    assert 0 < len(reduced) <= 10
