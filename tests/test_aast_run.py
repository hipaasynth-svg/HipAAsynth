"""run_7aast, file in / file out, demo models and the ``hipaasynth 7aast`` command."""

import csv
import json
import random

import pytest

from hipaasynth.aast import ModelAdapter
from hipaasynth.aast.cases import (
    CARE_SETTINGS,
    case_id,
    control,
    fragmented,
    in_setting,
    present,
    twin,
)
from hipaasynth.aast.cli import main as aast_main
from hipaasynth.aast.demo import demo_adapter
from hipaasynth.aast.files import AnswerFileError, answers_adapter, export_cases, load_answers
from hipaasynth.aast.run import AXIS_ORDER, DESCRIPTIVE, NOT_APPLICABLE, run_7aast
from hipaasynth.aast.stats import FAIL, INCONCLUSIVE, PASS
from hipaasynth.decision_cohort import build_decision_cohort
from hipaasynth.run.main import main as hipaasynth_main

STATUSES = {PASS, FAIL, INCONCLUSIVE, DESCRIPTIVE, NOT_APPLICABLE}


def _const(value, input_type="record"):
    return ModelAdapter(lambda case: value, "binary", input=input_type, name=f"always {value}")


def _obs(case):
    return case["observations"]


@pytest.fixture(scope="module")
def text_reports():
    return {
        name: run_7aast(demo_adapter(name, "sepsis", "text"), "sepsis", n=100, demo=True)
        for name in ("demo_guideline", "demo_biased")
    }


# --- report shape -----------------------------------------------------------------


def test_text_model_gets_every_axis(text_reports):
    report = text_reports["demo_guideline"]
    assert [a.axis for a in report.axes] == list(AXIS_ORDER)
    assert all(a.status in STATUSES for a in report.axes)
    assert NOT_APPLICABLE not in {a.status for a in report.axes}
    assert report.axis("5").status == DESCRIPTIVE
    assert report.demo and report.limitations[0].startswith("DEMO")


def test_record_model_skips_the_written_form_axes():
    report = run_7aast(demo_adapter("demo_guideline", "stroke", "record"), "stroke", n=40)
    assert [a.axis for a in report.axes] == ["accuracy", "1", "2", "3", "4", "5", "6", "7"]
    for key in ("1", "3", "4"):
        assert report.axis(key).status == NOT_APPLICABLE
    assert report.axis("2").name.startswith("Group fairness")


def test_report_round_trips_to_json(text_reports):
    d = text_reports["demo_biased"].to_dict()
    assert json.loads(json.dumps(d)) == d
    assert d["overall"] == FAIL and d["settings"]["information_mode"] == "blinded_decision_time"


def test_same_seed_same_report():
    a = run_7aast(demo_adapter("demo_biased", "dka", "record"), "dka", n=40).to_dict()
    b = run_7aast(demo_adapter("demo_biased", "dka", "record"), "dka", n=40).to_dict()
    assert a == b


# --- the axes find what they should -------------------------------------------------


def test_form_biased_model_fails_axes_1_to_3(text_reports):
    biased, fair = text_reports["demo_biased"], text_reports["demo_guideline"]
    for key in ("1", "2", "3"):
        assert biased.axis(key).status == FAIL
        assert fair.axis(key).status != FAIL


@pytest.mark.parametrize("answer", [True, False])
def test_constant_models_fail_the_accuracy_floor(answer):
    report = run_7aast(_const(answer), "sepsis", n=60)
    assert report.axis("accuracy").status == FAIL
    assert report.overall == FAIL


def test_a_model_that_never_answers_fails_and_is_counted():
    report = run_7aast(_const(None), "stroke", n=40)
    assert report.axis("accuracy").status == FAIL
    assert report.answer_rates["abstained"] == report.answer_rates["cases"] == 40


def test_group_axis_catches_a_race_biased_record_model():
    report = run_7aast(demo_adapter("demo_biased", "stroke", "record"), "stroke", n=400)
    groups = report.axis("2").metrics["groups"]
    assert report.axis("2").status == FAIL
    assert groups["ethnicity=black"]["status"] == FAIL
    assert groups["ethnicity=black"]["miss_rate"] > 0.3


def test_setting_axis_fails_a_lactate_dependent_model():
    def lactate_only(case):
        return (_obs(case).get("lactate_initial") or 0) >= 2.0

    report = run_7aast(ModelAdapter(lactate_only, "binary", input="record"), "sepsis", n=200)
    assert report.axis("6").status == FAIL
    assert report.axis("6").metrics["clinic"]["sensitivity"] == 0.0


def test_continuity_axis_fails_a_history_dependent_model():
    def needs_history(case):
        obs = _obs(case)
        return obs.get("diabetes_type") in ("type1", "type2") and (obs["arterial_ph"] or 7.4) < 7.3

    report = run_7aast(ModelAdapter(needs_history, "binary", input="record"), "dka", n=200)
    assert report.axis("7").status == FAIL


def test_twin_axis_sees_a_race_driven_model():
    def race_driven(case):
        return case["demographics"]["ethnicity"] == "white"

    report = run_7aast(ModelAdapter(race_driven, "binary", input="record"), "sepsis", n=100)
    twins = report.axis("5").metrics
    assert twins["ethnicity"]["beyond_noise_and_control"] is True
    assert twins["sex"]["beyond_noise_and_control"] is False
    assert "ethnicity" in report.axis("5").summary


def test_noise_floor_detects_a_random_model():
    rng = random.Random(0)
    report = run_7aast(
        ModelAdapter(lambda case: rng.random() < 0.5, "binary", input="record"),
        "sepsis",
        n=60,
        noise_cases=20,
    )
    floor = report.axis("5").metrics["noise_floor"]
    assert floor["deterministic"] is False and floor["rate"]["estimate"] > 0.5
    assert report.axis("5").metrics["ethnicity"]["beyond_noise_and_control"] is False


def test_score_model_uses_its_threshold_and_reports_ppv():
    def score(case):
        return float(_obs(case).get("lactate_initial") or 0) * 3

    report = run_7aast(
        ModelAdapter(score, "score", input="record", threshold=6.0),
        "sepsis",
        n=60,
        deployment_prevalence=0.05,
    )
    ppv = report.axis("accuracy").metrics["ppv_at_deployment_prevalence"]
    assert 0 <= ppv <= 1 and report.model["threshold"] == 6.0


def test_small_cohort_groups_are_inconclusive_not_fail():
    report = run_7aast(demo_adapter("demo_biased", "stroke", "record"), "stroke", n=60)
    assert report.axis("2").status == INCONCLUSIVE


# --- cases ------------------------------------------------------------------------


@pytest.fixture(scope="module")
def patient():
    return build_decision_cohort("sepsis", 4, seed=1, prevalence=1.0)[0].patient


def test_present_text_and_record(patient):
    assert isinstance(present(patient, "text"), str)
    record = present(patient, "record")
    assert "sepsis_flag" not in record["observations"]
    with pytest.raises(ValueError):
        present(patient, "image")


def test_case_id_is_content_based(patient):
    record = present(patient, "record")
    reordered = json.loads(json.dumps(record, sort_keys=True))
    assert case_id(record) == case_id(reordered) and len(case_id("x")) == 64


def test_settings_remove_the_right_tests(patient):
    assert set(CARE_SETTINGS) == {"hospital", "critical_access", "clinic"}
    assert in_setting(patient, "hospital").observations == patient.observations
    cah = in_setting(patient, "critical_access").observations
    assert cah["lactate_initial"] is None and cah["heart_rate_initial"] is not None
    clinic = in_setting(patient, "clinic").observations
    assert clinic["wbc_initial"] is None and clinic["temperature_c_initial"] is not None
    with pytest.raises(ValueError):
        in_setting(patient, "moon")


def test_fragmented_drops_history_keeps_presentation(patient):
    f = fragmented(patient)
    assert f.conditions == [] and f.medications == [] and len(f.visits) <= 1
    assert f.observations["hypertension_flag"] is None
    assert f.observations["heart_rate_initial"] == patient.observations["heart_rate_initial"]


def test_twin_and_control_change_one_thing(patient):
    t = twin(patient, "ethnicity", "native")
    assert t.demographics.ethnicity == "native" and t.observations == patient.observations
    c = control(patient)
    assert c.visits[-1].visit_date != patient.visits[-1].visit_date
    assert c.observations == patient.observations and c.demographics == patient.demographics
    with pytest.raises(ValueError):
        twin(patient, "age", "90")


def test_demo_name_is_validated():
    with pytest.raises(ValueError, match="demo model"):
        demo_adapter("demo_magic", "sepsis", "text")


# --- file in / file out -----------------------------------------------------------


@pytest.mark.parametrize("input_type", ["record", "text"])
def test_file_round_trip_gives_the_same_report(tmp_path, input_type):
    out = export_cases(tmp_path / "cases.jsonl", condition="stroke", input_type=input_type, n=40)
    demo = demo_adapter("demo_biased", "stroke", input_type)
    rows = [json.loads(line) for line in (tmp_path / "cases.jsonl").read_text().splitlines()]
    assert len(rows) == out["cases"] and len({r["case_id"] for r in rows}) == len(rows)
    with open(out["answers_template"], "w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["case_id", "answer"])
        for r in rows:
            writer.writerow([r["case_id"], "yes" if demo.fn(r["input"]) else "no"])
    direct = run_7aast(demo, "stroke", n=40).to_dict()
    filed = run_7aast(answers_adapter(out["answers_template"], "binary", input=input_type),
                      "stroke", n=40).to_dict()  # fmt: skip
    direct.pop("model")
    filed.pop("model")
    assert direct == filed


def test_answers_must_match_the_export(tmp_path):
    out = export_cases(tmp_path / "c.jsonl", condition="dka", input_type="record", n=20)
    with pytest.raises(AnswerFileError, match="same condition"):
        run_7aast(answers_adapter(out["answers_template"], "binary", input="record"), "dka", n=21)


@pytest.mark.parametrize(
    "output, raw, expected",
    [
        ("binary", "Yes", True),
        ("binary", "0", False),
        ("binary", "", None),
        ("score", " 6.5 ", 6.5),
        ("ordinal", "2", 2),
        ("ranked", "Sepsis | UTI", ["Sepsis", "UTI"]),
        ("ranked", '["Sepsis", "UTI"]', ["Sepsis", "UTI"]),
        ("text", "FINAL_ANSWER: Yes", "FINAL_ANSWER: Yes"),
    ],
)
def test_answer_formats(tmp_path, output, raw, expected):
    from hipaasynth.aast.files import _parse

    assert _parse(raw, output, "c") == expected


@pytest.mark.parametrize(
    "output, raw", [("binary", "maybe"), ("score", "high"), ("ordinal", "2.5")]
)
def test_bad_answers_are_reported(output, raw):
    from hipaasynth.aast.files import _parse

    with pytest.raises(AnswerFileError, match="cannot read"):
        _parse(raw, output, "abcdef")


def test_jsonl_answers_and_bad_files(tmp_path):
    good = tmp_path / "a.jsonl"
    good.write_text('{"case_id": "x", "answer": "yes"}\n\n{"case_id": "y", "answer": null}\n')
    assert load_answers(good) == {"x": "yes", "y": ""}
    bad = tmp_path / "b.jsonl"
    bad.write_text("not json\n")
    with pytest.raises(AnswerFileError, match="b.jsonl:1"):
        load_answers(bad)
    no_header = tmp_path / "c.csv"
    no_header.write_text("x,yes\n")
    with pytest.raises(AnswerFileError, match="header"):
        load_answers(no_header)
    with pytest.raises(AnswerFileError, match="not found"):
        load_answers(tmp_path / "missing.csv")


# --- command line -----------------------------------------------------------------


def test_cli_demo_run_prints_report_and_exit_code(capsys, tmp_path):
    code = aast_main(["run", "--condition", "sepsis", "--input", "text", "--n", "60",
                      "--demo", "demo_biased", "--report", str(tmp_path / "r.json")])  # fmt: skip
    out = capsys.readouterr().out
    assert code == 2 and "OVERALL: FAIL" in out and "DEMO MODEL" in out
    assert json.loads((tmp_path / "r.json").read_text())["results"]["overall"] == FAIL


def test_cli_export_then_answers(capsys, tmp_path):
    cases = tmp_path / "cases.jsonl"
    assert aast_main(["export", "--condition", "fabry", "--input", "record", "--n", "20",
                      "--out", str(cases)]) == 0  # fmt: skip
    assert "Fill in the 'answer' column" in capsys.readouterr().out
    answers = tmp_path / "cases_answers.csv"
    rows = list(csv.reader(answers.open()))
    with answers.open("w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(rows[0])
        for cid, _ in rows[1:]:
            writer.writerow([cid, "no"])
    code = aast_main(["run", "--condition", "fabry", "--input", "record", "--n", "20",
                      "--answers", str(answers)])  # fmt: skip
    assert code == 2 and "OVERALL: FAIL" in capsys.readouterr().out


def test_cli_python_model(capsys, tmp_path, monkeypatch):
    (tmp_path / "my_model.py").write_text(
        "def predict(case):\n    return (case['observations'].get('nihss_score') or 0) >= 1\n"
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    code = aast_main(["run", "--condition", "stroke", "--input", "record", "--n", "40",
                      "--model", "my_model:predict"])  # fmt: skip
    assert code in (0, 2) and "my_model:predict" in capsys.readouterr().out


@pytest.mark.parametrize(
    "argv, message",
    [
        (["run", "--condition", "stroke", "--input", "record", "--model", "nope"], "module:function"),
        (["run", "--condition", "stroke", "--input", "record", "--answers", "/nope.csv"], "not found"),
        (["run", "--condition", "stroke", "--input", "record", "--output", "score",
          "--model", "math:fabs"], "threshold"),
    ],
)  # fmt: skip
def test_cli_errors_are_one_line(capsys, argv, message):
    assert aast_main(argv) == 1
    err = capsys.readouterr().err
    assert message in err and "Traceback" not in err


def test_hipaasynth_command_dispatches_7aast(capsys):
    code = hipaasynth_main(["7aast", "run", "--condition", "dka", "--input", "record", "--n", "40",
                            "--demo", "demo_guideline"])  # fmt: skip
    assert code in (0, 2) and "7AAST  dka" in capsys.readouterr().out


def test_cli_demo_rejects_non_binary_output(capsys):
    with pytest.raises(SystemExit):
        aast_main(["run", "--condition", "dka", "--input", "record", "--demo", "demo_guideline",
                   "--output", "score"])  # fmt: skip
