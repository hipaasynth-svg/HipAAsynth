"""Decision cohorts: true cases mixed with clinical mimics.

Regression guard for the 2026-10 7AAST review finding that cohorts were 100%
positive (with ``required_condition``) or 0% positive (without), so an
always-"yes" model passed every DIF passport and false alarms could not be
measured. Mimics must be separable only by the clinical picture, never by
which fields they carry.
"""

import json
from collections import Counter

import pytest

from hipaasynth.core.config import GenerationConfig
from hipaasynth.decision_cohort import (
    MIMICS,
    MIXED_CONDITIONS,
    NO_INFECTION,
    RULE_OUT,
    TRUTH_FLAG,
    build_decision_cohort,
)
from hipaasynth.dif.framework import DIFConfig, run_audit
from hipaasynth.dif.model_interface import MockFairModel
from hipaasynth.pipelines.population_pipeline import generate_patients
from hipaasynth.polymorphic.blinding import blind_record
from hipaasynth.polymorphic.forms import (
    INFO_MODE_BLINDED,
    PolymorphicFormEngine,
    _blinded_measurements,
)

ALL = ["sepsis", "stroke", "dka", "fabry"]
ENGINE = PolymorphicFormEngine(information_mode=INFO_MODE_BLINDED)


def _shape(value, prefix=""):
    """Every key path in a nested record, ignoring values."""
    out = set()
    if isinstance(value, dict):
        for k, v in value.items():
            out |= {prefix + k} | _shape(v, prefix + k + ".")
    elif isinstance(value, list):
        for v in value:
            out |= _shape(v, prefix + "[].")
    return out


@pytest.fixture(scope="module", params=ALL)
def cohort(request):
    return request.param, build_decision_cohort(request.param, 120, seed=7)


def test_mixed_cohorts_have_cases_and_every_mimic(cohort):
    cond, cases = cohort
    kinds = Counter(c.kind for c in cases)
    assert kinds["case"] > 0 and sum(not c.truth for c in cases) > 0
    if cond in MIXED_CONDITIONS:
        assert kinds["case"] == 60
        assert set(MIMICS[cond]) <= set(kinds) - {"case"} <= set(MIMICS[cond]) | {RULE_OUT}


def test_truth_matches_the_ground_truth_flag(cohort):
    cond, cases = cohort
    for c in cases:
        assert bool(c.patient.observations[TRUTH_FLAG[cond]]) is c.truth
        assert (c.kind == "case") is c.truth


def test_patient_ids_are_unique(cohort):
    _, cases = cohort
    ids = [c.patient.demographics.patient_id for c in cases]
    assert len(set(ids)) == len(ids)


def test_cases_and_mimics_have_identical_record_structure(cohort):
    # The leak audit: in a blinded record, only values may differ.
    _, cases = cohort
    pos = set().union(*(_shape(blind_record(c.patient.to_dict())) for c in cases if c.truth))
    neg = set().union(*(_shape(blind_record(c.patient.to_dict())) for c in cases if not c.truth))
    assert pos == neg


def test_cases_and_mimics_show_the_same_measurements(cohort):
    _, cases = cohort

    def labels(c):
        return tuple(label for label, _ in _blinded_measurements(c.patient.observations))

    assert {labels(c) for c in cases if c.truth} == {labels(c) for c in cases if not c.truth}


def test_no_blinded_form_reveals_the_mimic(cohort):
    cond, cases = cohort
    for c in cases[:30]:
        for form in ENGINE.express_all(c.patient):
            low = form["full_text"].lower()
            assert "mimic" not in low
            for name in MIMICS.get(cond, {}):
                assert name.replace("_", " ") not in low and name not in low


def test_same_seed_same_cohort_byte_for_byte():
    a = [c.patient.to_dict() for c in build_decision_cohort("sepsis", 30, seed=3)]
    b = [c.patient.to_dict() for c in build_decision_cohort("sepsis", 30, seed=3)]
    c = [c.patient.to_dict() for c in build_decision_cohort("sepsis", 30, seed=4)]
    assert json.dumps(a) == json.dumps(b) and json.dumps(a) != json.dumps(c)


def test_order_is_shuffled_not_cases_first():
    truths = [c.truth for c in build_decision_cohort("stroke", 40, seed=2)]
    assert truths != sorted(truths, reverse=True)


@pytest.mark.parametrize("prevalence, n_pos", [(0.0, 0), (0.1, 4), (0.5, 20), (1.0, 40)])
def test_prevalence(prevalence, n_pos):
    cases = build_decision_cohort("dka", 40, seed=1, prevalence=prevalence)
    assert len(cases) == 40 and sum(c.truth for c in cases) == n_pos


@pytest.mark.parametrize(
    "kwargs",
    [
        {"condition": "copd", "n": 10},
        {"condition": "sepsis", "n": 0},
        {"condition": "sepsis", "n": 10, "prevalence": 1.5},
        {"condition": "sepsis", "n": True},
    ],
)
def test_bad_arguments(kwargs):
    with pytest.raises(ValueError):
        build_decision_cohort(seed=1, **kwargs)


def test_profile_is_applied_to_cases_and_mimics():
    from hipaasynth.sdk import _resolve_profile

    path = _resolve_profile("nd_tribal_region_a")
    cases = build_decision_cohort("stroke", 40, seed=9, population_profile_path=path)
    ethnicities = Counter(c.patient.demographics.ethnicity for c in cases)
    assert ethnicities.most_common(1)[0][0] == "native"
    rural = {c.truth: c.patient.observations["rural_presentation"] for c in cases}
    assert set(rural) == {True, False}


def test_no_infection_is_rendered_not_dropped():
    cases = build_decision_cohort("sepsis", 40, seed=4)
    values = {c.patient.observations["suspected_infection_source"] for c in cases}
    assert NO_INFECTION in values and None not in values


def test_stroke_discriminators_on_every_case():
    for c in build_decision_cohort("stroke", 40, seed=6):
        for key in ("seizure_at_onset", "migraine_history", "forehead_weakness"):
            assert isinstance(c.patient.observations[key], bool)


def test_always_yes_no_longer_passes_dif():
    class AlwaysYes:
        def predict(self, patient, form):
            return True

    cohort = build_decision_cohort("sepsis", 20, seed=5)
    passports = run_audit(
        AlwaysYes(),
        lambda cfg: [c.patient for c in cohort],
        GenerationConfig(patient_count=20, seed=5),
        DIFConfig(information_mode=INFO_MODE_BLINDED),
    )
    # On the unmixed cohort it passed 20/20; every mimic is now a false alarm.
    assert sum(p.passed() for p in passports) == sum(c.truth for c in cohort)
    unmixed = run_audit(
        AlwaysYes(),
        generate_patients,
        GenerationConfig(patient_count=20, seed=5, required_condition="sepsis"),
    )
    assert all(p.passed() for p in unmixed)


def test_fair_model_still_passes_on_mixed_cohort():
    cohort = build_decision_cohort("stroke", 16, seed=8)
    passports = run_audit(
        MockFairModel(),
        lambda cfg: [c.patient for c in cohort],
        GenerationConfig(patient_count=16, seed=8),
        DIFConfig(information_mode=INFO_MODE_BLINDED),
    )
    assert all(p.passed() for p in passports)


# --- the task is solvable from the evidence, and not trivial ----------------------


def _sepsis_rule(o):
    q = (
        int((o["resp_rate_initial"] or 0) >= 22)
        + int((o["sbp_initial"] or 999) <= 100)
        + int(bool(o.get("altered_mental_status_only_flag")))
    )
    infection = o["suspected_infection_source"] not in (None, NO_INFECTION)
    return infection and (q >= 2 or (o["lactate_initial"] or 0) >= 2.0)


def _stroke_rule(o):
    return (
        (o["nihss_score"] or 0) >= 1
        and (o["glucose_admission"] or 100) >= 60
        and not o["seizure_at_onset"]
        and not o["forehead_weakness"]
        and not (o["migraine_history"] and (o["nihss_score"] or 0) <= 3)
    )


def _dka_rule(o):
    return (
        (o["arterial_ph"] or 7.4) < 7.30
        and (o["bicarbonate_meq_l"] or 24) < 18
        and (o["beta_hydroxybutyrate_mmol_l"] or 0) >= 3.0
        and o["diabetes_type"] in ("type1", "type2")
    )


@pytest.mark.parametrize(
    "cond, rule, ceiling",
    [
        # Sepsis and stroke are judgement calls: a textbook rule must beat chance
        # by a wide margin (the mimics are clinically coherent) without being
        # perfect (they are not trivially easy).
        ("sepsis", _sepsis_rule, 0.98),
        ("stroke", _stroke_rule, 0.98),
        # DKA is defined by the ADA lab criteria and the module sets its flag by
        # exactly those criteria, so applying them correctly (including to
        # euglycemic DKA, which a glucose-led model misses) is exact.
        ("dka", _dka_rule, 1.0),
    ],
)
def test_a_textbook_rule_does_well(cond, rule, ceiling):
    cases = build_decision_cohort(cond, 400, seed=11)
    accuracy = sum(rule(c.patient.observations) == c.truth for c in cases) / len(cases)
    assert 0.70 <= accuracy <= ceiling, accuracy


def test_a_glucose_only_dka_model_is_caught():
    # The shortcut a weak model takes: "glucose high = DKA". It misses euglycemic
    # DKA and calls HHS and plain hyperglycaemia DKA.
    cases = build_decision_cohort("dka", 400, seed=11)
    accuracy = sum(
        ((c.patient.observations["glucose_mg_dl"] or 0) >= 250) == c.truth for c in cases
    ) / len(cases)
    assert accuracy < 0.8, accuracy


@pytest.mark.parametrize(
    "finding, phrase",
    [
        ("seizure_at_onset", "shaking all over"),
        ("forehead_weakness", "even my forehead"),
        ("migraine_history", "headaches like this"),
    ],
)
def test_stroke_findings_are_described_exactly_when_present(finding, phrase):
    from hipaasynth.polymorphic.forms import symptom_sentences

    cases = build_decision_cohort("stroke", 120, seed=12)
    assert any(c.patient.observations[finding] for c in cases)
    for c in cases:
        obs = c.patient.observations
        text = symptom_sentences(obs, "first")
        expected = bool(obs[finding]) and (finding != "forehead_weakness" or obs["nihss_score"])
        assert (phrase in text) == bool(expected), (c.kind, obs[finding], text)


def test_hypoglycaemia_reads_shaky():
    from hipaasynth.polymorphic.forms import symptom_sentences

    cases = [c for c in build_decision_cohort("stroke", 80, seed=12) if c.kind == "hypoglycaemia"]
    assert cases and all(
        "shaky" in symptom_sentences(c.patient.observations, "first") for c in cases
    )


def test_dka_drowsy_reads_as_confused():
    from hipaasynth.polymorphic.forms import symptom_sentences

    assert "confused" in symptom_sentences({"dka_flag": True, "mental_status": "drowsy"}, "first")
