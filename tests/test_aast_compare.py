"""Paired runs: a scenario's patients against the US baseline."""

from __future__ import annotations

import copy
import json

import pytest

from hipaasynth.aast.cli import main as aast_main
from hipaasynth.aast.compare import (
    ComparisonError,
    build_comparison,
    compare,
    newcombe,
    plain_english,
)
from hipaasynth.aast.demo import demo_adapter
from hipaasynth.aast.report import (
    build_document,
    load_document,
    render_html,
    seal,
    timestamp_files,
    verify_document,
)
from hipaasynth.aast.run import run_7aast
from hipaasynth.aast.web import RequestError, run_request, verify_request


@pytest.mark.parametrize(
    "counts,expected",
    [
        ((56, 70, 48, 80), (0.0524, 0.3339)),  # Newcombe 1998, Table II, example (a)
        ((9, 10, 3, 10), (0.1705, 0.8090)),  # example (b)
        ((5, 56, 0, 29), (-0.0381, 0.1926)),  # example (e)
    ],
)
def test_newcombe_matches_the_published_examples(counts, expected):
    d = newcombe(*counts)
    assert (d["low"], d["high"]) == pytest.approx(expected, abs=1e-4)


def _pair(model="demo_biased", n=300):
    a = demo_adapter(model, "sepsis", "record")
    t = build_document(run_7aast(a, "sepsis", n=n, profile="tribal_rural_a"))
    b = build_document(run_7aast(a, "sepsis", n=n, profile="us_default"))
    return t, b


def test_a_model_biased_against_native_patients_is_worse_on_the_tribal_profile():
    doc = build_comparison(*_pair())
    comp = doc["comparison"]
    assert comp["sensitivity_finding"] == "WORSE"
    assert comp["rows"][0]["difference"]["high"] < 0
    assert comp["target_label"] == "Northern Plains Tribal Health Region A"
    assert "worse for these patients" in plain_english(comp, "sepsis")
    assert verify_document(doc).ok


def test_a_fair_model_shows_no_clear_gap():
    t, b = _pair("demo_guideline")
    assert compare(t, b)["sensitivity_finding"] != "WORSE"


def test_tampering_with_any_part_is_caught():
    doc = build_comparison(*_pair(n=100))
    for edit in (
        lambda d: d["comparison"]["rows"][0].update(target=0.99),
        lambda d: d["target"]["results"].update(overall="PASS"),
        lambda d: d["chain"].update(baseline="0" * 64),
    ):
        bad = copy.deepcopy(doc)
        edit(bad)
        assert not verify_document(bad).ok


def test_reports_that_differ_cannot_be_compared():
    t, _ = _pair(n=100)
    other = build_document(run_7aast(demo_adapter("demo_biased", "sepsis", "record"), "sepsis",
                                     n=100, seed=7, profile="us_default"))  # fmt: skip
    with pytest.raises(ComparisonError, match="seed"):
        compare(t, other)


def test_comparison_can_be_sealed_and_rendered(tmp_path):
    from hipaasynth.aast import sign

    doc = build_comparison(*_pair(n=100))
    sign.new_key(tmp_path / "k.json", signer="J")
    seal(doc, key=sign.load_key(tmp_path / "k.json"))
    names = {c.name: c.ok for c in verify_document(doc).checks}
    assert names["signature"] and names["comparison hash"]
    page = render_html(doc)
    assert "US baseline" in page and "Sealed test record" in page and page.count("<svg") >= 3
    text, _ = timestamp_files({**doc, "seal": {"opentimestamps": {"proof": ""}}})
    import hashlib

    assert hashlib.sha256(text.encode()).hexdigest() == doc["chain"]["report"]


def test_cli_compare_baseline(tmp_path, capsys):
    out = tmp_path / "pair.html"
    code = aast_main(["run", "--scenario", "tribal_sepsis", "--input", "record", "--n", "200",
                      "--demo", "demo_biased", "--compare-baseline", "--report", str(out)])  # fmt: skip
    assert code == 2  # worse on the scenario
    printed = capsys.readouterr().out
    assert "COMPARISON:" in printed and "US BASELINE" in printed
    doc = load_document(out)
    assert doc["format"] == "hipaasynth-7aast-comparison/1"
    assert doc["target"]["method"]["provenance"]["scenario"] == "tribal_sepsis"
    assert aast_main(["verify", str(out), "--regenerate"]) == 0
    assert aast_main(["run", "--condition", "sepsis", "--input", "record", "--demo",
                      "demo_biased", "--compare-baseline"]) == 1  # fmt: skip


def test_web_compare_baseline():
    base = {"scenario": "tribal_dka", "input": "record", "n": 100, "demo": "demo_biased"}
    out = run_request({**base, "compare_baseline": True})
    doc = out["document"]
    assert doc["format"] == "hipaasynth-7aast-comparison/1"
    assert doc["target"]["population"]["profile"] == "tribal_rural_b"
    assert doc["baseline"]["population"]["profile"] == "us_default"
    assert json.loads(out["reports"]["target"]["document_json"]) == doc["target"]
    assert verify_request({"document": json.loads(out["document_json"])})["ok"]
    with pytest.raises(RequestError, match="other than the US baseline"):
        run_request({"condition": "dka", "input": "record", "n": 30, "demo": "demo_biased",
                     "compare_baseline": True})  # fmt: skip
    with pytest.raises(RequestError, match="answers file"):
        run_request({**base, "demo": None, "answers": "case_id,answer\n",
                     "compare_baseline": True})  # fmt: skip


def test_browser_compare_checkbox(tmp_path):
    import threading

    from hipaasynth.api import make_server
    from tests.test_web_ui import _chromium_executable

    pw = pytest.importorskip("playwright.sync_api")
    srv = make_server("127.0.0.1", 0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    exe = _chromium_executable()
    try:
        with pw.sync_playwright() as p:
            try:
                browser = p.chromium.launch(**({"executable_path": exe} if exe else {}))
            except Exception as err:  # noqa: BLE001  # pragma: no cover
                pytest.skip(f"headless Chromium unavailable: {err}")
            pg = browser.new_page()
            pg.goto(f"http://127.0.0.1:{srv.server_address[1]}/7aast", wait_until="networkidle")
            assert not pg.is_visible("#compareBaseline")
            pg.select_option("#scenario", "tribal_sepsis")
            pg.check("input[name=input][value=record]")
            pg.select_option("#demo", "demo_biased")
            pg.check("#compareBaseline")
            pg.click("details summary")
            pg.fill("#n", "200")
            pg.click("#runBtn")
            pg.wait_for_selector("#results:not(.hidden)", timeout=90_000)
            assert pg.inner_text("#overall") == "WORSE"
            assert pg.is_visible("#saveTarget") and pg.is_visible("#saveBaseline")
            body = pg.frame_locator("#reportFrame").locator("body").inner_text()
            assert "US baseline" in body and "Northern Plains Tribal Health Region A" in body
            browser.close()
    finally:
        srv.shutdown()
        srv.server_close()
