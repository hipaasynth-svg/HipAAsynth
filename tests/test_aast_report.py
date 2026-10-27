"""The 7AAST report file: JSON / HTML output, the hash chain and ``verify``."""

import copy
import json

import pytest

from hipaasynth.aast.cli import main as aast_main
from hipaasynth.aast.demo import demo_adapter
from hipaasynth.aast.report import (
    FORMAT,
    STAGES,
    ReportFileError,
    build_document,
    canonical,
    chain,
    load_document,
    render_html,
    verify,
    write_report,
)
from hipaasynth.aast.run import run_7aast


@pytest.fixture(scope="module")
def report():
    return run_7aast(demo_adapter("demo_biased", "sepsis", "text"), "sepsis", n=60, demo=True)


@pytest.fixture(scope="module")
def doc(report):
    return build_document(report)


def _failed(result):
    return [c.name for c in result.checks if not c.ok]


# --- document ---------------------------------------------------------------------


def test_document_sections_and_population(report, doc):
    assert doc["format"] == FORMAT
    assert set(doc) == {"format", "population", "method", "results", "chain"}
    cases = doc["population"]["cases"]
    assert len(cases) == 60 == len(report.population)
    assert sum(c["truth"] for c in cases) == doc["population"]["true_cases"] == 30
    assert all(len(c["case_id"]) == 64 for c in cases)
    assert doc["method"]["pass_marks"]["accuracy_floor"] == 0.85
    assert doc["results"]["overall"] == report.overall
    assert set(doc["chain"]) == {"algorithm", *STAGES}


def test_same_run_same_hashes(doc):
    again = run_7aast(demo_adapter("demo_biased", "sepsis", "text"), "sepsis", n=60, demo=True)
    assert build_document(again)["chain"] == doc["chain"]


def test_chain_links_each_stage_to_the_ones_before():
    base = chain({"a": 1}, {"b": 2}, {"c": 3})
    for i, section in enumerate(({"a": 9}, {"b": 9}, {"c": 9})):
        args = [{"a": 1}, {"b": 2}, {"c": 3}]
        args[i] = section
        changed = chain(*args)
        for j, stage in enumerate(STAGES):
            assert (changed[stage] != base[stage]) == (j >= i)


def test_canonical_is_key_order_free_and_refuses_nan():
    assert (
        canonical({"b": 1, "a": [1, 2]}) == canonical({"a": [1, 2], "b": 1}) == '{"a":[1,2],"b":1}'
    )
    with pytest.raises(ValueError):
        canonical({"x": float("nan")})


# --- verify -----------------------------------------------------------------------


def test_untouched_report_verifies_and_rebuilds(doc):
    result = verify(doc, regenerate=True)
    assert result.ok, result.text()
    assert "VERIFIED" in result.text()


@pytest.mark.parametrize(
    ("edit", "first_failure"),
    [
        (lambda d: d["results"]["axes"][0]["metrics"].update(false_alarms=0), "results hash"),
        (lambda d: d["population"]["cases"][0].update(truth=None), "population hash"),
        (lambda d: d["method"]["pass_marks"].update(accuracy_floor=0.5), "method hash"),
        (lambda d: d["results"].update(overall="PASS"), "results hash"),
        (lambda d: d["chain"].update(report="0" * 64), "report hash"),
    ],
)
def test_any_edit_breaks_the_chain(doc, edit, first_failure):
    tampered = copy.deepcopy(doc)
    edit(tampered)
    failed = _failed(verify(tampered))
    assert failed and failed[0] == first_failure


def test_rehashed_edit_is_caught_by_rebuilding_the_cohort(doc):
    tampered = copy.deepcopy(doc)
    case = tampered["population"]["cases"][3]
    case["truth"] = not case["truth"]
    tampered["chain"].update(chain(tampered["population"], tampered["method"], tampered["results"]))
    assert verify(tampered).ok  # internally consistent ...
    assert _failed(verify(tampered, regenerate=True)) == ["cohort rebuilt from settings"]


def test_overall_must_match_axes(doc):
    tampered = copy.deepcopy(doc)
    tampered["results"]["overall"] = "PASS"
    tampered["chain"].update(chain(tampered["population"], tampered["method"], tampered["results"]))
    assert _failed(verify(tampered)) == ["overall verdict"]


def test_other_engine_version_cannot_be_rebuilt(doc):
    other = copy.deepcopy(doc)
    other["population"]["engine_version"] = "0.0.1"
    other["chain"].update(chain(other["population"], other["method"], other["results"]))
    check = verify(other, regenerate=True).checks[-1]
    assert not check.ok and "0.0.1" in check.detail


def test_missing_section_is_reported(doc):
    broken = {k: v for k, v in doc.items() if k != "method"}
    result = verify(broken)
    assert not result.ok and result.checks[0].name == "structure"


# --- files and HTML ---------------------------------------------------------------


def test_json_and_html_round_trip(report, tmp_path):
    for name in ("r.json", "r.html"):
        written = write_report(report, tmp_path / name)
        assert load_document(tmp_path / name) == written
        assert verify(load_document(tmp_path / name)).ok


def test_html_is_plain_english_self_contained_and_labelled_demo(doc):
    page = render_html(doc)
    assert "DEMO MODEL: NOT A CLINICAL TOOL" in page
    assert "not a certification" in page
    assert doc["chain"]["report"] in page
    assert "<script src" not in page and "http" not in page.split("<script")[0].lower()
    for axis in doc["results"]["axes"]:
        assert axis["summary"].replace("'", "&#x27;") in page


def test_html_escapes_model_text(doc):
    hostile = copy.deepcopy(doc)
    hostile["method"]["model"]["name"] = "<img src=x onerror=alert(1)>"
    hostile["results"]["axes"][0]["summary"] = "</script><script>alert(1)</script>"
    page = render_html(hostile)
    assert "<img src=x" not in page and "<script>alert" not in page
    assert page.count("</script>") == 1


def test_non_demo_report_has_no_demo_banner(doc):
    plain = copy.deepcopy(doc)
    plain["method"]["demo"] = False
    assert "NOT A CLINICAL TOOL" not in render_html(plain)


def test_load_document_errors(tmp_path):
    with pytest.raises(ReportFileError, match="not found"):
        load_document(tmp_path / "missing.json")
    (tmp_path / "bad.json").write_text("{nope", encoding="utf-8")
    with pytest.raises(ReportFileError, match="not valid JSON"):
        load_document(tmp_path / "bad.json")
    (tmp_path / "other.json").write_text(json.dumps({"format": "x"}), encoding="utf-8")
    with pytest.raises(ReportFileError, match="not a 7AAST report"):
        load_document(tmp_path / "other.json")
    (tmp_path / "page.html").write_text("<html></html>", encoding="utf-8")
    with pytest.raises(ReportFileError, match="no embedded"):
        load_document(tmp_path / "page.html")


# --- CLI --------------------------------------------------------------------------


def test_cli_run_report_then_verify(capsys, tmp_path):
    out = tmp_path / "report.html"
    argv = ["run", "--condition", "sepsis", "--input", "text", "--demo", "demo_biased", "--n", "40"]
    aast_main([*argv, "--report", str(out)])
    printed = capsys.readouterr().out
    doc = load_document(out)
    assert f"Report hash: {doc['chain']['report']}" in printed

    assert aast_main(["verify", str(out), "--regenerate"]) == 0
    assert "VERIFIED" in capsys.readouterr().out

    tampered = tmp_path / "t.json"
    doc["results"]["model_calls"] += 1
    tampered.write_text(json.dumps(doc), encoding="utf-8")
    assert aast_main(["verify", str(tampered)]) == 3
    assert "NOT VERIFIED" in capsys.readouterr().out


def test_cli_verify_bad_file_is_one_line(capsys, tmp_path):
    assert aast_main(["verify", str(tmp_path / "nope.json")]) == 1
    assert capsys.readouterr().err.strip().startswith("hipaasynth 7aast: error: report not found")
