"""The 7AAST page, ``POST /7aast``, ``POST /7aast/export`` and ``hipaasynth ui``."""

from __future__ import annotations

import csv
import io
import json
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from hipaasynth.aast.report import verify
from hipaasynth.aast.web import MAX_N, RequestError, export_request, run_request
from hipaasynth.api import make_server, ui_main
from tests.test_web_ui import _chromium_executable

SMALL = {"condition": "sepsis", "input": "record", "n": 30}


@pytest.fixture(scope="module")
def server():
    srv = make_server(host="127.0.0.1", port=0)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()
    srv.server_close()
    thread.join(timeout=5)


def _post(url, body, ctype="application/json"):
    data = body if isinstance(body, bytes) else json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": ctype}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as err:
        return err.code, json.loads(err.read())


def _filled(answers_csv, answer):
    rows = list(csv.DictReader(io.StringIO(answers_csv)))
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["case_id", "answer"])
    for row in rows:
        writer.writerow([row["case_id"], answer])
    return out.getvalue()


# --- request handling (no server) -----------------------------------------------------


def test_demo_run_returns_verified_document_html_and_summary():
    result = run_request({**SMALL, "demo": "demo_guideline"})
    assert set(result) == {"document", "html", "summary"}
    assert verify(result["document"], regenerate=True).ok
    assert "DEMO MODEL" in result["html"] and "DEMO MODEL" in result["summary"]


def test_answers_run_matches_the_cli_file_round_trip():
    exported = export_request(SMALL)
    assert exported["cases"] == len(exported["cases_jsonl"].splitlines())
    result = run_request({**SMALL, "answers": _filled(exported["answers_csv"], "yes")})
    doc = result["document"]
    assert doc["method"]["model"]["name"] == "uploaded answers"
    assert doc["method"]["demo"] is False and "DEMO MODEL" not in result["html"]
    accuracy = doc["results"]["axes"][0]
    assert accuracy["metrics"]["false_alarms"] == 15  # always-yes alarms on every mimic
    assert accuracy["status"] == "FAIL"


@pytest.mark.parametrize(
    ("params", "message"),
    [
        ({**SMALL, "condition": "flu", "demo": "demo_guideline"}, "'condition' must be one of"),
        ({**SMALL, "input": "image", "demo": "demo_guideline"}, "'input' must be one of"),
        ({**SMALL, "n": MAX_N + 1, "demo": "demo_guideline"}, "'n' must be between"),
        ({**SMALL, "n": 12.5, "demo": "demo_guideline"}, "whole number"),
        ({**SMALL, "seed": True, "demo": "demo_guideline"}, "'seed' must be a number"),
        (
            {**SMALL, "profile": "../../etc/passwd", "demo": "demo_guideline"},
            "'profile' must be one of",
        ),
        ({**SMALL, "demo": "gpt"}, "'demo' must be one of"),
        (SMALL, "exactly one of 'demo'"),
        ({**SMALL, "demo": "demo_guideline", "answers": "x"}, "exactly one of 'demo'"),
        ({**SMALL, "answers": "case_id,answer\n", "output": "vibes"}, "'output' must be one of"),
        ({**SMALL, "answers": "case_id,answer\n", "answers_format": "xlsx"}, "'answers_format'"),
        (
            {**SMALL, "answers": "case_id,answer\n", "output": "ordinal", "acute_levels": "a"},
            "whole numbers",
        ),
        ({**SMALL, "demo": "demo_guideline", "model": "os:system"}, "unknown field(s): model"),
    ],
)
def test_bad_requests_are_explained(params, message):
    with pytest.raises(RequestError, match=message.replace("(", r"\(").replace(")", r"\)")):
        run_request(params)


def test_export_rejects_run_fields():
    with pytest.raises(RequestError, match="unknown field"):
        export_request({**SMALL, "demo": "demo_guideline"})


# --- over HTTP --------------------------------------------------------------------------


def test_page_is_served(server):
    with urllib.request.urlopen(f"{server}/7aast", timeout=10) as resp:
        assert resp.status == 200 and resp.headers["Content-Type"].startswith("text/html")
        page = resp.read().decode()
    assert "7AAST" in page and "/7aast/export" in page and "<script src" not in page
    with urllib.request.urlopen(f"{server}/", timeout=10) as resp:
        assert 'href="/7aast"' in resp.read().decode()


def test_http_demo_run_and_errors(server):
    status, body = _post(f"{server}/7aast", {**SMALL, "demo": "demo_biased"})
    assert status == 200 and body["document"]["chain"]["report"] in body["html"]

    status, body = _post(f"{server}/7aast", {**SMALL, "demo": "nope"})
    assert status == 400 and "'demo' must be one of" in body["error"]
    status, body = _post(f"{server}/7aast", b"{not json")
    assert status == 400 and body["error"] == "invalid JSON body"
    status, body = _post(f"{server}/7aast", b"[]")
    assert status == 400 and "object" in body["error"]
    status, body = _post(
        f"{server}/7aast", b"condition=sepsis", "application/x-www-form-urlencoded"
    )
    assert status == 415


def test_http_answers_must_match_the_cases(server):
    status, exported = _post(f"{server}/7aast/export", SMALL)
    assert status == 200
    status, body = _post(
        f"{server}/7aast", {**SMALL, "seed": 7, "answers": _filled(exported["answers_csv"], "no")}
    )
    assert status == 400 and "export the cases again" in body["error"]


def test_http_methods(server):
    req = urllib.request.Request(f"{server}/7aast/export", method="GET")
    with pytest.raises(urllib.error.HTTPError) as err:
        urllib.request.urlopen(req, timeout=10)
    assert err.value.code == 405 and err.value.headers["Allow"] == "POST"


def test_generate_body_limit_is_unchanged(server):
    from hipaasynth.api import MAX_BODY_BYTES

    req = urllib.request.Request(
        f"{server}/generate",
        data=b"{}",
        headers={"Content-Type": "application/json", "Content-Length": str(MAX_BODY_BYTES + 1)},
        method="POST",
    )
    with pytest.raises(urllib.error.HTTPError) as err:
        urllib.request.urlopen(req, timeout=10)
    assert err.value.code == 413


# --- hipaasynth ui -------------------------------------------------------------------------


def test_ui_command_opens_the_page_on_localhost(monkeypatch, capsys):
    from hipaasynth import api

    opened = []

    class Server:
        server_address = ("127.0.0.1", 54321)

        def serve_forever(self):
            raise KeyboardInterrupt

        def server_close(self):
            opened.append("closed")

    calls = []

    def fake_make_server(host, port):
        calls.append((host, port))
        if port == 8765:
            raise OSError("in use")
        return Server()

    monkeypatch.setattr(api, "make_server", fake_make_server)
    assert ui_main([], open_browser=opened.append) == 0
    assert calls == [("127.0.0.1", 8765), ("127.0.0.1", 0)]  # busy port -> any free port
    assert opened == ["http://127.0.0.1:54321/7aast", "closed"]
    assert "runs on this computer only" in capsys.readouterr().out


def test_hipaasynth_ui_dispatch(monkeypatch):
    from hipaasynth import api
    from hipaasynth.run.main import main

    seen = []
    monkeypatch.setattr(api, "ui_main", lambda argv: seen.append(argv) or 0)
    assert main(["ui", "--no-browser"]) == 0
    assert seen == [["--no-browser"]]


# --- in a real browser ------------------------------------------------------------------


@pytest.fixture
def page(server):
    pw = pytest.importorskip("playwright.sync_api")
    exe = _chromium_executable()
    with pw.sync_playwright() as p:
        try:
            browser = p.chromium.launch(**({"executable_path": exe} if exe else {}))
        except Exception as err:  # noqa: BLE001  # pragma: no cover - environment-dependent
            pytest.skip(f"headless Chromium unavailable: {err}")
        pg = browser.new_page(accept_downloads=True)
        pg.goto(f"{server}/7aast", wait_until="networkidle")
        yield pg
        browser.close()


def test_browser_demo_run_shows_report(page):
    page.click("details summary")
    page.fill("#n", "30")
    page.click("#runBtn")
    page.wait_for_selector("#results:not(.hidden)", timeout=60_000)
    assert page.inner_text("#overall") in {"PASS", "FAIL", "INCONCLUSIVE"}
    assert len(page.inner_text("#hash")) == 64
    frame = page.frame_locator("#reportFrame")
    assert "DEMO MODEL" in frame.locator("body").inner_text()
    assert page.evaluate("document.documentElement.scrollWidth") <= 1280
    with page.expect_download() as dl:
        page.click("#saveHtml")
    assert dl.value.suggested_filename == "7aast-report.html"


def test_browser_file_workflow(page, tmp_path):
    page.check("input[name=source][value=file]")
    page.check("input[name=input][value=record]")
    assert page.is_visible("#fileOpts") and not page.is_visible("#demoOpts")
    page.click("details summary")
    page.fill("#n", "30")
    downloads = []
    page.on("download", lambda d: downloads.append(d))
    page.click("#exportBtn")
    page.wait_for_selector("#status.ok", timeout=60_000)
    page.wait_for_timeout(500)
    names = sorted(d.suggested_filename for d in downloads)
    assert names == ["cases.jsonl", "cases_answers.csv"]
    template = next(d for d in downloads if d.suggested_filename.endswith(".csv"))
    answers = tmp_path / "answers.csv"
    answers.write_text(
        _filled(Path(template.path()).read_text(encoding="utf-8"), "no"), encoding="utf-8"
    )

    page.set_input_files("#answersFile", str(answers))
    page.fill("#modelName", "Never-alarm model")
    page.click("#runBtn")
    page.wait_for_selector("#results:not(.hidden)", timeout=60_000)
    assert page.inner_text("#overall") == "FAIL"
    body = page.frame_locator("#reportFrame").locator("body").inner_text()
    assert "Never-alarm model" in body and "DEMO MODEL" not in body


def test_browser_score_needs_threshold(page):
    page.check("input[name=source][value=file]")
    page.select_option("#output", "score")
    assert page.is_visible("#threshold")
    page.set_input_files(
        "#answersFile", {"name": "a.csv", "mimeType": "text/csv", "buffer": b"case_id,answer\n"}
    )
    page.click("#runBtn")
    page.wait_for_selector("#status.err")
    assert "threshold" in page.inner_text("#status")
