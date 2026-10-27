"""Blinded, decision-time mode: the answer must not be readable from the case.

Regression guard for a validity bug found in the 2026-10 7AAST review: every
form named the diagnosis ("female with sepsis", "Sepsis-3 screen POSITIVE",
"ASSESSMENT: sepsis"), records carried the ground-truth flag, and the Axis 5
prompts printed facts from after the decision ("Hypotension onset at 1h",
"Door to needle") plus the generator's own "Contradictory signals" hints.
"""

import copy
import dataclasses
import json
import re

import pytest

from hipaasynth.adversarial.evaluator import Evaluator, _build_messages
from hipaasynth.adversarial.temporal import TemporalEngine
from hipaasynth.core.config import GenerationConfig
from hipaasynth.dif.framework import DIFConfig, run_audit
from hipaasynth.dif.model_interface import MockFairModel
from hipaasynth.pipelines.population_pipeline import generate_patients
from hipaasynth.polymorphic.blinding import (
    ANSWER_FIELDS,
    DECISION_TARGET_CONDITIONS,
    FUTURE_FIELDS,
    GENERATOR_FIELDS,
    MASKED_DIAGNOSIS,
    blind_record,
    visible_observations,
)
from hipaasynth.polymorphic.forms import (
    INFO_MODE_BLINDED,
    INFORMATION_MODES,
    PolymorphicFormEngine,
    symptom_sentences,
)

CONDITIONS = ["sepsis", "stroke", "dka", "fabry"]
TRUTH_FLAG = {
    "sepsis": "sepsis_flag",
    "stroke": "stroke_flag",
    "dka": "dka_flag",
    "fabry": "fabry_referral_flag",
}
# Words that restate a screen or work-up result.
SCREEN_PHRASES = re.compile(
    r"screen (positive|negative)|criteria (met|not met)|work-?up (indicated|not indicated)|"
    r"evaluation (positive|negative)",
    re.IGNORECASE,
)
# "stroke" legitimately appears in history ("Prior stroke") and as a Fabry
# finding ("unexplained stroke at a young age"); everything else is the answer.
_ALLOWED_STROKE = re.compile(r"prior stroke|stroke at a young age", re.IGNORECASE)

ENGINE = PolymorphicFormEngine(information_mode=INFO_MODE_BLINDED)


def _patients(cond, n=12, seed=21):
    return generate_patients(GenerationConfig(patient_count=n, seed=seed, required_condition=cond))


def _assert_no_answer(text, cond):
    low = _ALLOWED_STROKE.sub("", text).lower()
    for target in DECISION_TARGET_CONDITIONS:
        assert target not in low, (target, text[:300])
    assert "ketoacidosis" not in low
    assert not SCREEN_PHRASES.search(text), text[:300]


@pytest.mark.parametrize("cond", CONDITIONS)
def test_no_blinded_form_names_the_answer(cond):
    for patient in _patients(cond):
        for form in ENGINE.express_all(patient):
            _assert_no_answer(form["full_text"], cond)


@pytest.mark.parametrize("cond", CONDITIONS)
def test_unblinded_forms_still_name_it(cond):
    # The bug this guards against is real in the default mode.
    text = PolymorphicFormEngine().express_all(_patients(cond, n=1)[0])[1]["full_text"]
    assert cond in text.lower()


@pytest.mark.parametrize("cond", CONDITIONS)
def test_flipping_the_ground_truth_changes_nothing(cond):
    # The strongest property: a true case and an otherwise identical negative
    # render to the same bytes, so the answer cannot be read from the case.
    for patient in _patients(cond, n=6):
        observations = {**patient.observations, TRUTH_FLAG[cond]: False}
        flipped = dataclasses.replace(
            patient,
            observations=observations,
            conditions=[c for c in patient.conditions if c.name != cond],
        )
        a = [f["full_text"] for f in ENGINE.express_all(patient)]
        b = [f["full_text"] for f in ENGINE.express_all(flipped)]
        assert a == b


@pytest.mark.parametrize("cond", CONDITIONS)
def test_blinded_forms_carry_every_decision_time_fact(cond):
    for patient in _patients(cond):
        for form in ENGINE.express_all(patient):
            assert form["omitted_fact_categories"] == []
            assert form["information_mode"] == INFO_MODE_BLINDED


def test_hidden_values_never_reach_a_form():
    for patient in _patients("sepsis", n=20):
        for form in ENGINE.express_all(patient):
            text = form["full_text"]
            for phrase in ("Hypotension onset", "Deterioration", "Contradictory", "6h"):
                assert phrase not in text
            for value in ("sudden_collapse", "gradual_decline", "NRB_escalation"):
                assert value not in text


def test_blinded_fhir_has_no_target_condition_and_carries_the_vitals():
    patient = _patients("sepsis", n=1)[0]
    bundle = json.loads(ENGINE.express(patient, "FHIR_STRUCTURED")["full_text"])
    resources = [e["resource"] for e in bundle["entry"]]
    conditions = [r["code"]["text"] for r in resources if r["resourceType"] == "Condition"]
    assert "sepsis" not in conditions
    labels = {r["code"]["text"] for r in resources if r["resourceType"] == "Observation"}
    assert {"Temp", "HR", "RR", "SBP", "Lactate"} <= labels
    assert "sepsis" not in json.dumps(bundle).lower()


def test_fhir_exporter_is_untouched_by_blinding():
    # _patient_to_fhir feeds every exporter; blinding filters a copy only.
    from hipaasynth.exporters.exporters import _patient_to_fhir

    patient = _patients("sepsis", n=1)[0]
    before = json.dumps(_patient_to_fhir(patient), sort_keys=True)
    ENGINE.express_all(patient)
    assert json.dumps(_patient_to_fhir(patient), sort_keys=True) == before
    assert "sepsis" in before.lower()


@pytest.mark.parametrize(
    "obs, expected",
    [
        ({"sepsis_flag": True, "temperature_c_initial": 39.1, "heart_rate_initial": 112}, "hot"),
        ({"sepsis_flag": True, "temperature_c_initial": 35.2}, "cold"),
        ({"sepsis_flag": True, "temperature_c_initial": 37.0, "resp_rate_initial": 26}, "fast"),
        ({"stroke_flag": True, "nihss_score": 4}, "face"),
        ({"dka_flag": True, "glucose_mg_dl": 480, "arterial_ph": 7.1}, "thirsty"),
        ({"fabry_referral_flag": True, "neuropathic_pain": True}, "burn"),
        ({"sepsis_flag": True}, "tired"),
    ],
)
def test_symptoms_follow_the_measurements(obs, expected):
    assert expected in symptom_sentences(obs, "first").lower()
    negative = {k: (False if k in TRUTH_FLAG.values() else v) for k, v in obs.items()}
    assert symptom_sentences(negative, "first") == symptom_sentences(obs, "first")


def test_afebrile_sepsis_no_longer_says_hot():
    # The default mode says "I feel very hot" for every sepsis case, including
    # afebrile ones; blinded mode follows the thermometer.
    obs = {"sepsis_flag": True, "temperature_c_initial": 36.8, "heart_rate_initial": 118}
    text = symptom_sentences(obs, "first")
    assert "hot" not in text and "heart" in text


def test_symptom_person_is_validated():
    with pytest.raises(ValueError, match="person"):
        symptom_sentences({}, "fourth")


def test_mode_is_registered_and_old_modes_unchanged():
    assert INFORMATION_MODES == ("same_facts", "realistic_missingness", "blinded_decision_time")
    with pytest.raises(ValueError):
        PolymorphicFormEngine(information_mode="blinded")


def test_dif_audit_runs_blinded():
    passports = run_audit(
        MockFairModel(),
        generate_patients,
        GenerationConfig(patient_count=4, seed=3, required_condition="stroke"),
        DIFConfig(information_mode=INFO_MODE_BLINDED),
    )
    assert len(passports) == 4 and all(p.passed() for p in passports)


# --- records -------------------------------------------------------------------


@pytest.mark.parametrize("cond", CONDITIONS)
def test_blind_record_hides_the_answer_and_the_future(cond):
    record = _patients(cond, n=1)[0].to_dict()
    original = copy.deepcopy(record)
    blinded = blind_record(record)
    assert record == original  # input untouched
    obs = blinded["observations"]
    assert not (set(obs) & (ANSWER_FIELDS | FUTURE_FIELDS | GENERATOR_FIELDS))
    assert not any(k.endswith("_observation_version") for k in obs)
    assert cond not in [c["name"] for c in blinded["conditions"]]
    assert all(v["primary_diagnosis"] == MASKED_DIAGNOSIS for v in blinded["visits"])
    assert "seed" not in blinded["demographics"]
    assert cond not in json.dumps(blinded["conditions"]).lower()


def test_blind_record_keeps_clinical_facts():
    record = _patients("sepsis", n=1)[0].to_dict()
    obs = blind_record(record)["observations"]
    for key in ("temperature_c_initial", "heart_rate_initial", "lactate_initial", "sbp_initial"):
        assert key in obs
    masked = [v["primary_diagnosis"] for v in blind_record(record)["visits"]]
    assert MASKED_DIAGNOSIS in masked


def test_mental_status_survives_as_an_observation():
    assert visible_observations({"altered_mental_status_only_flag": True}) == {
        "mental_status": "altered"
    }


# --- Axis 5 decision-time prompts ---------------------------------------------


@pytest.fixture(scope="module")
def timelines():
    return {
        cond: TemporalEngine(seed=42, years=1, condition=cond).generate()
        for cond in ("sepsis", "stroke")
    }


@pytest.mark.parametrize(
    "cond, hidden",
    [
        ("sepsis", ["Hypotension onset", "Deterioration pattern", "Fluid input", "mode:"]),
        ("stroke", ["Suspected type", "Door to needle"]),
    ],
)
def test_decision_time_prompts_drop_future_facts(timelines, cond, hidden):
    for p in timelines[cond]:
        for t in p["timeline"]:
            pd = t.get("_patient_dict")
            if not pd:
                continue
            default = _build_messages(pd, cond)[1]["content"]
            blinded = _build_messages(pd, cond, decision_time=True)[1]["content"]
            assert "Contradictory signals" not in blinded
            for phrase in hidden:
                assert phrase not in blinded
            assert "FINAL_ANSWER: Yes" in blinded and blinded != "" and default != ""


def test_default_prompts_keep_their_old_text(timelines):
    pd = timelines["stroke"][0]["timeline"][0]["_patient_dict"]
    assert "Door to needle" in _build_messages(pd, "stroke")[1]["content"]


def test_evaluator_decision_time_flag(timelines):
    seen = []

    def model(prompt):
        seen.append(prompt)
        return "FINAL_ANSWER: Yes"

    Evaluator(decision_time=True).evaluate(timelines["sepsis"], model)
    assert seen and not any("Hypotension onset" in s for s in seen)
    assert Evaluator().decision_time is False
