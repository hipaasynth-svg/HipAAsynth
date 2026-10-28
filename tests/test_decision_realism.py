"""Clinical realism of decision cohorts: no answer leaks, measured pulse oximetry."""

import dataclasses
import statistics
from collections import Counter

import pytest

from hipaasynth.aast.demo import demo_adapter
from hipaasynth.aast.run import run_7aast
from hipaasynth.decision_cohort import OXIMETER_BIAS, as_measured, build_decision_cohort
from hipaasynth.polymorphic.blinding import blind_record
from hipaasynth.polymorphic.forms import INFO_MODE_BLINDED, PolymorphicFormEngine

#: Values that only one side has for a sound clinical reason (the sign defines
#: or excludes the condition); anything else that separates perfectly is a leak.
CLINICAL_TELLS = {
    ("sepsis", "suspected_infection_source", "none_suspected"),  # Sepsis-3 needs infection
    ("stroke", "forehead_weakness", "True"),  # forehead sparing: peripheral palsy
    ("stroke", "nihss_category", "severe"),  # NIHSS > 20 mimics are rare
    ("dka", "diabetes_type", "none"),
    ("dka", "ketonuria", "False"),  # DKA needs ketones
    ("fabry", "angiokeratoma", "True"),  # pathognomonic signs
    ("fabry", "cornea_verticillata", "True"),
}


@pytest.fixture(scope="module", params=["sepsis", "stroke", "dka", "fabry"])
def blinded(request):
    cohort = build_decision_cohort(request.param, 300, seed=5)
    rows = [(c.truth, blind_record(c.patient.to_dict())["observations"]) for c in cohort]
    return request.param, rows


def _auc(pos, neg):
    wins = sum((a > b) + 0.5 * (a == b) for a in pos for b in neg)
    auc = wins / (len(pos) * len(neg))
    return max(auc, 1 - auc)


def test_no_single_number_separates_cases_from_mimics(blinded):
    condition, rows = blinded
    keys = {k for _, obs in rows for k in obs}
    for key in sorted(keys):
        values = [(t, obs.get(key)) for t, obs in rows]
        nums = [(t, v) for t, v in values if isinstance(v, (int, float)) and not isinstance(v, bool)]
        if len(nums) < 0.8 * len(values):
            continue
        pos = [v for t, v in nums if t]
        neg = [v for t, v in nums if not t]
        if pos and neg:
            assert _auc(pos, neg) < 0.95, f"{condition}.{key} alone separates the groups"


def test_no_category_appears_on_one_side_only(blinded):
    condition, rows = blinded
    keys = {k for _, obs in rows for k in obs}
    for key in sorted(keys):
        pos = Counter(str(obs.get(key)) for t, obs in rows if t)
        neg = Counter(str(obs.get(key)) for t, obs in rows if not t)
        if len(pos) + len(neg) > 12:
            continue  # free-valued field, covered by the numeric check
        for value in (set(pos) ^ set(neg)) - {"None"}:
            share = (pos[value] or neg[value]) / sum((pos if pos[value] else neg).values())
            if share > 0.1:
                assert (condition, key, value) in CLINICAL_TELLS, (
                    f"{condition}.{key}={value} appears only in "
                    f"{'true cases' if pos[value] else 'mimics'} ({share:.0%})"
                )


def test_treatment_and_generator_summaries_are_hidden():
    for condition in ("sepsis", "fabry"):
        for case in build_decision_cohort(condition, 20, seed=2):
            obs = blind_record(case.patient.to_dict())["observations"]
            assert not {"oxygen_device", "fio2_percent", "red_flag_count", "sao2_reference"} & set(
                obs
            )
    engine = PolymorphicFormEngine(information_mode=INFO_MODE_BLINDED)
    patient = build_decision_cohort("sepsis", 4, seed=2)[0].patient
    for form in engine.express_all(patient):
        text = form["full_text"].lower()
        assert "fio2" not in text and "non_rebreather" not in text and "o2 device" not in text


def test_stroke_mimics_can_have_prior_stroke_and_high_blood_pressure():
    cohort = build_decision_cohort("stroke", 400, seed=9)
    mimics = [c.patient.observations for c in cohort if not c.truth and c.kind != "rule_out"]
    assert sum(bool(o.get("prior_stroke")) for o in mimics) >= 10
    assert max(o["sbp_admission"] for o in mimics) >= 175


# --- pulse oximetry ---------------------------------------------------------------------


def test_pulse_oximeter_reading_is_measured_and_deterministic():
    cohort = build_decision_cohort("sepsis", 60, seed=4)
    again = build_decision_cohort("sepsis", 60, seed=4)
    assert [c.patient.observations for c in cohort] == [c.patient.observations for c in again]
    for c in cohort:
        obs = c.patient.observations
        assert 70 <= obs["spo2_initial"] <= 100
        assert isinstance(obs["sao2_reference"], int)


def test_oximeter_over_reads_more_in_black_than_white_patients():
    base = build_decision_cohort("sepsis", 1, seed=1)[0].patient
    raw = {**base.observations, "spo2_initial": 88}
    raw.pop("sao2_reference")

    def bias(ethnicity):
        out = []
        for i in range(400):
            demo = dataclasses.replace(base.demographics, ethnicity=ethnicity, patient_id=f"p{i}")
            p = as_measured(dataclasses.replace(base, demographics=demo, observations=raw))
            out.append(p.observations["spo2_initial"] - 88)
        return statistics.mean(out)

    assert bias("black") - bias("white") > 0.8
    assert OXIMETER_BIAS["black"][0] > OXIMETER_BIAS["white"][0]


def test_patient_without_spo2_is_unchanged():
    patient = build_decision_cohort("stroke", 1, seed=1)[0].patient
    assert as_measured(patient) is patient


def test_sepsis_report_states_the_measurement_and_its_gap():
    report = run_7aast(demo_adapter("demo_guideline", "sepsis", "record"), "sepsis", n=20)
    notes = " ".join(report.limitations)
    assert "pulse oximeter" in notes and "normotensive sepsis" in notes
