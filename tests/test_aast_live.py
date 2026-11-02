"""Watching a run live: every call recorded, progress, Stop, and a sealed transcript."""

from __future__ import annotations

import hashlib
import json
import threading
import time
import urllib.error
import urllib.request

import pytest

from hipaasynth.aast.demo import demo_adapter
from hipaasynth.aast.live import Cancelled, Jobs, Recorder
from hipaasynth.aast.run import run_7aast
from hipaasynth.aast.web import run_request
from hipaasynth.api import make_server


def test_recorder_records_every_call_and_does_not_change_results():
    a = demo_adapter("demo_biased", "sepsis", "text")
    plain = run_7aast(a, "sepsis", n=40, demo=True)
    rec = Recorder(live=True)
    rec.estimate(a, lambda stub: run_7aast(stub, "sepsis", n=40, demo=True))
    watched = run_7aast(rec.watch(a), "sepsis", n=40, demo=True)
    assert [x.status for x in watched.axes] == [x.status for x in plain.axes]
    assert len(rec.entries) == watched.model_calls == rec.expected
    e = rec.entries[0]
    assert e["i"] == 1 and e["run"] == "target" and e["read_as"] in ("yes", "no")
    assert e["case"] and e["answer"] in ("true", "false")
    lines = rec.transcript("target").splitlines()
    assert len(lines) == len(rec.entries) and json.loads(lines[0])["case_id"] == e["case_id"]


def test_transcript_hash_is_sealed_in_the_report():
    out = run_request({"condition": "sepsis", "input": "record", "n": 30, "demo": "demo_biased",
                       "tests": ["groups"]})  # fmt: skip
    prov = out["document"]["method"]["provenance"]
    assert len(prov["transcript_sha256"]) == 64
    assert "Transcript" in out["html"]


def test_stop_cancels_a_run():
    jobs = Jobs()

    def slow(rec: Recorder):
        rec.cancel.wait(5)
        raise Cancelled("stopped by the user")

    job = jobs.start(slow)
    jobs.cancel(job)
    for _ in range(50):
        if jobs.status(job)["state"] != "running":
            break
        time.sleep(0.05)
    assert jobs.status(job)["state"] == "stopped"
    with pytest.raises(KeyError):
        jobs.status("nope")


def _post(url, body):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json"})  # fmt: skip
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as err:
        return err.code, json.loads(err.read())


def test_http_live_run_with_comparison_and_transcripts():
    srv = make_server("127.0.0.1", 0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        code, body = _post(f"{url}/7aast/start", {"scenario": "tribal_sepsis", "input": "record",
                                                  "n": 40, "demo": "demo_biased",
                                                  "compare_baseline": True})  # fmt: skip
        assert code == 200
        job, since, events = body["job"], 0, []
        for _ in range(400):
            _, st = _post(f"{url}/7aast/job", {"job": job, "since": since})
            since += len(st["events"])
            events += st["events"]
            if st["state"] != "running":
                break
            time.sleep(0.05)
        assert st["state"] == "done" and st["calls"] == st["expected"] == len(events)
        assert {e["run"] for e in events} == {"target", "baseline"}
        doc = st["result"]["document"]
        _, t = _post(f"{url}/7aast/job", {"job": job, "transcripts": True})
        for side in ("target", "baseline"):
            sha = hashlib.sha256(t["transcripts"][side].encode()).hexdigest()
            assert sha == doc[side]["method"]["provenance"]["transcript_sha256"]
        code, err = _post(f"{url}/7aast/start", {"condition": "sepsis", "input": "text", "n": 30})
        assert code == 400 and "exactly one" in err["error"]
        code, err = _post(f"{url}/7aast/job", {"job": "nope"})
        assert code == 400 and "no such run" in err["error"]
    finally:
        srv.shutdown()
        srv.server_close()


def test_browser_shows_calls_live_and_can_stop(tmp_path):
    """A slow fake LLM: the page lists answers while the run is still going, then Stop."""
    from http.server import ThreadingHTTPServer

    from tests.test_aast_remote import _Model
    from tests.test_web_ui import _chromium_executable

    pw = pytest.importorskip("playwright.sync_api")

    class Slow(_Model):
        def do_POST(self):
            time.sleep(0.05)
            super().do_POST()

    fake = ThreadingHTTPServer(("127.0.0.1", 0), Slow)
    local = make_server("127.0.0.1", 0, allow_model_url=True)
    for srv in (fake, local):
        threading.Thread(target=srv.serve_forever, daemon=True).start()
    exe = _chromium_executable()
    try:
        with pw.sync_playwright() as p:
            try:
                browser = p.chromium.launch(**({"executable_path": exe} if exe else {}))
            except Exception as err:  # noqa: BLE001  # pragma: no cover
                pytest.skip(f"headless Chromium unavailable: {err}")
            pg = browser.new_page(accept_downloads=True)
            pg.goto(f"http://127.0.0.1:{local.server_address[1]}/7aast", wait_until="networkidle")
            pg.check("input[name=source][value=llm]")
            pg.select_option("#llmProvider", "compatible")
            pg.fill("#llmBaseUrl", f"http://127.0.0.1:{fake.server_address[1]}/v1")
            pg.fill("#llmModel", "Orinn-1.7")
            pg.uncheck("#signReport")
            pg.uncheck("#stampReport")
            pg.click("details summary")
            pg.fill("#n", "40")
            pg.click("#runBtn")
            pg.wait_for_selector("#liveList details", timeout=30_000)
            assert pg.is_visible("#live") and "call" in pg.inner_text("#liveText")
            first = pg.locator("#liveList details").first
            first.click()
            text = first.inner_text()
            assert "Case shown to the model" in text and "FINAL_ANSWER" in text
            pg.select_option("#liveFilter", "yes")
            pg.select_option("#liveFilter", "all")
            pg.click("#stopBtn")
            pg.wait_for_selector("#status.err:has-text('Stopped')", timeout=30_000)
            assert pg.locator("#liveList details").count() > 0
            # A small run to the end: the transcript can be saved.
            for key in ("forms", "twins", "settings", "history"):
                pg.uncheck(f"#test-{key}")
            pg.fill("#n", "30")
            pg.click("#runBtn")
            pg.wait_for_selector("#results:not(.hidden)", timeout=60_000)
            with pg.expect_download() as dl:
                pg.click("#saveTranscript")
            path = tmp_path / "t.jsonl"
            dl.value.save_as(path)
            rows = [json.loads(x) for x in path.read_text().splitlines()]
            assert len(rows) == 30 and all(r["read_as"] in ("yes", "no") for r in rows)
            body = pg.frame_locator("#reportFrame").locator("body").inner_text()
            sha = hashlib.sha256(path.read_bytes()).hexdigest()
            assert sha[:32] in body.replace("\n", "")
            browser.close()
    finally:
        for srv in (fake, local):
            srv.shutdown()
            srv.server_close()
