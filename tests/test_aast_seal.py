"""The seal on a 7AAST report: who ran it, a signature, and a Bitcoin timestamp."""

from __future__ import annotations

import base64
import copy
import hashlib
import json
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from hipaasynth.aast import ots, sign
from hipaasynth.aast.cli import main as aast_main
from hipaasynth.aast.demo import demo_adapter
from hipaasynth.aast.render import plain_english, render_page
from hipaasynth.aast.report import (
    build_document,
    chain,
    load_document,
    provenance,
    seal,
    timestamp_files,
    upgrade_seal,
    verify,
)
from hipaasynth.aast.run import run_7aast
from hipaasynth.aast.web import RequestError, run_request, upgrade_request, verify_request
from tests.ots_fake import BLOCK_TIME, HEIGHT, FakeCalendar

DATA = Path(__file__).parent / "data"


@pytest.fixture
def calendar(monkeypatch):
    fake = FakeCalendar()
    monkeypatch.setattr(ots, "CALENDARS", (fake.url,))
    monkeypatch.setattr(ots, "EXPLORERS", (fake.url + "/api",))
    yield fake
    fake.close()


@pytest.fixture
def key(tmp_path, monkeypatch):
    path = tmp_path / "key.json"
    monkeypatch.setenv("HIPAASYNTH_KEY", str(path))
    sign.new_key(path, signer="Jordan Lee", organization="Example Health")
    return sign.load_key(path)


def _doc(**prov):
    report = run_7aast(demo_adapter("demo_biased", "sepsis", "record"), "sepsis", n=40, demo=True)
    if prov:
        report.provenance = provenance("2026-11-01T14:00:00Z", "2026-11-01T14:01:00Z", **prov)
    return build_document(report)


# --- OpenTimestamps format ---------------------------------------------------------------


def test_reads_a_real_bitcoin_proof_from_the_opentimestamps_project():
    """examples/hello-world.txt.ots from opentimestamps-client: anchored in block 358391."""
    proof = (DATA / "hello-world.txt.ots").read_bytes()
    info = ots.info(proof)
    assert info.digest == hashlib.sha256(b"Hello World!\n").hexdigest()
    assert info.status == "BITCOIN" and info.bitcoin[0][0] == 358391
    assert ots.serialize_file(ots.parse_file(proof)) == proof  # byte-for-byte round trip
    with pytest.raises(ots.OTSError):
        ots.parse_file(proof[:-3])
    with pytest.raises(ots.OTSError):
        ots.parse_file(b"not a proof")


def test_stamp_upgrade_and_bitcoin_check(calendar):
    digest = hashlib.sha256(b"report").digest()
    proof, took = ots.stamp(digest)
    assert took == [calendar.url] and calendar.digests == [digest]
    assert ots.info(proof).status == "PENDING"
    with pytest.raises(ots.OTSError, match="no Bitcoin attestation"):
        ots.verify_bitcoin(proof)
    same, changed = ots.upgrade(proof)
    assert not changed and same == proof  # calendar has not committed yet
    calendar.mined = True
    done, changed = ots.upgrade(proof)
    info = ots.info(done)
    assert changed and info.status == "BITCOIN" and info.pending == []
    height, when = ots.verify_bitcoin(done)
    assert height == HEIGHT and when.startswith("2026-11-01")


def test_a_wrong_block_is_caught(calendar, monkeypatch):
    calendar.mined = True
    proof, _ = ots.stamp(hashlib.sha256(b"x").digest())
    done, _ = ots.upgrade(proof)
    monkeypatch.setattr("tests.ots_fake.merkle_root", lambda c: b"\x00" * 32)
    with pytest.raises(ots.OTSError, match="does not contain"):
        ots.verify_bitcoin(done)


def test_no_calendar_answers():
    with pytest.raises(ots.OTSError, match="no OpenTimestamps calendar"):
        ots.stamp(b"\x01" * 32, calendars=("http://127.0.0.1:9",), timeout=2)


def test_matches_the_official_library_when_installed(calendar):
    otslib = pytest.importorskip("opentimestamps.core.timestamp")
    ser = pytest.importorskip("opentimestamps.core.serialize")
    calendar.mined = True
    proof, _ = ots.upgrade(ots.stamp(hashlib.sha256(b"y").digest())[0])
    f = otslib.DetachedTimestampFile.deserialize(ser.BytesDeserializationContext(proof))
    assert f.file_digest == hashlib.sha256(b"y").digest()


# --- Ed25519 ----------------------------------------------------------------------------

RFC8032 = [
    ("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60",
     "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a", "",
     "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555fb8821590a33bacc61e39701c"
     "f9b46bd25bf5f0595bbe24655141438e7a100b"),
    ("4ccd089b28ff96da9db6c346ec114e0f5b8a319f35aba624da8cf6ed4fb8a6fb",
     "3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c", "72",
     "92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da085ac1e43e15996e458f3613d0"
     "f11d8c387b2eaeb4302aeeb00d291612bb0c00"),
]  # fmt: skip


@pytest.mark.parametrize("secret,public,msg,sig", RFC8032)
def test_ed25519_rfc8032_vectors(secret, public, msg, sig):
    sk, m = bytes.fromhex(secret), bytes.fromhex(msg)
    assert sign.public_key(sk).hex() == public
    assert sign.sign(sk, m).hex() == sig
    assert sign.verify(bytes.fromhex(public), m, bytes.fromhex(sig))
    assert not sign.verify(bytes.fromhex(public), m + b"!", bytes.fromhex(sig))


def test_key_files(tmp_path):
    path = tmp_path / "k.json"
    info = sign.new_key(path, signer="A")
    assert (path.stat().st_mode & 0o777) == 0o600
    assert len(info["fingerprint"]) == 39 and "private_key" not in info
    with pytest.raises(sign.SignatureError, match="already exists"):
        sign.new_key(path)
    data = json.loads(path.read_text())
    data["public_key"] = "00" * 32
    path.write_text(json.dumps(data))
    with pytest.raises(sign.SignatureError, match="does not match"):
        sign.load_key(path)


# --- provenance and the seal on a report ------------------------------------------------


def test_provenance_is_locked_into_the_hash():
    plain = _doc()
    assert "provenance" not in plain["method"]  # reports without it are unchanged
    doc = _doc(model_version="2.3.1", run_by="Jordan Lee", organization="Example Health",
               intended_use="", scenario="tribal_sepsis")  # fmt: skip
    prov = doc["method"]["provenance"]
    assert prov["model_version"] == "2.3.1" and "intended_use" not in prov
    assert prov["started_utc"] == "2026-11-01T14:00:00Z" and prov["tool"].startswith("HipAAsynth")
    assert verify(doc).ok
    doc["method"]["provenance"]["run_by"] = "Someone Else"
    assert not verify(doc).ok
    with pytest.raises(ValueError, match="unknown provenance"):
        provenance("a", "b", favourite_colour="red")


def test_signed_and_timestamped_report(calendar, key):
    doc = _doc(model_version="1", run_by="Jordan Lee")
    assert seal(doc, key=key, timestamp=True) == []
    names = {c.name: c for c in verify(doc).checks}
    assert names["signature"].ok and "Jordan Lee" in names["signature"].detail
    assert names["timestamp"].ok and "pending" in names["timestamp"].detail
    calendar.mined = True
    assert upgrade_seal(doc)
    result = verify(doc, bitcoin=True)
    assert result.ok and f"block {HEIGHT}" in result.checks[-1].detail
    text, proof = timestamp_files(doc)
    assert hashlib.sha256(text.encode()).hexdigest() == doc["chain"]["report"]
    assert ots.info(proof).digest == doc["chain"]["report"]


def test_a_rehashed_forgery_is_caught_by_the_seal(calendar, key):
    """Edit a result and recompute the whole chain: the hashes agree, the seal does not."""
    doc = _doc(run_by="Jordan Lee")
    seal(doc, key=key, timestamp=True)
    forged = copy.deepcopy(doc)
    forged["results"]["axes"][0]["status"] = "PASS"
    forged["results"]["overall"] = "PASS"
    forged["chain"].update(chain(forged["population"], forged["method"], forged["results"]))
    checks = {c.name: c for c in verify(forged).checks}
    assert checks["report hash"].ok  # the forger fixed the chain...
    assert not checks["signature"].ok  # ...but cannot re-sign with the key
    assert not checks["timestamp"].ok and "different report hash" in checks["timestamp"].detail
    swapped = copy.deepcopy(doc)
    other = sign.sign_hash({**key, "private_key": "11" * 32,
                            "public_key": sign.public_key(b"\x11" * 32).hex()},
                           doc["chain"]["report"])  # fmt: skip
    swapped["seal"]["signature"] = {
        **other,
        "fingerprint": key and doc["seal"]["signature"]["fingerprint"],
    }
    assert not {c.name: c for c in verify(swapped).checks}["signature"].ok


def test_failed_timestamp_is_a_note_not_an_error(key):
    doc = _doc()
    notes = seal(doc, key=key, timestamp=True, calendars=("http://127.0.0.1:9",))
    assert notes and "Not timestamped" in notes[0]
    assert "signature" in doc["seal"] and "opentimestamps" not in doc["seal"]


# --- the page ------------------------------------------------------------------------------


def test_report_page_has_seal_plain_english_and_charts(calendar, key):
    doc = _doc(model_version="2.3.1", run_by="Jordan <Lee>", organization="Example Health")
    seal(doc, key=key, timestamp=True)
    page = render_page(doc)
    assert "Sealed test record" in page and doc["seal"]["signature"]["fingerprint"] in page
    assert "Jordan &lt;Lee&gt;" in page and "Jordan <Lee>" not in page.split("report-data")[0]
    assert "2026-11-01T14:00:00Z" in page and "OpenTimestamps calendar" in page
    assert page.count("<svg") >= 3 and "heatmap" in page
    assert "How the model did, in plain English" in page and "Scorecard" in page
    assert page.index("Sealed test record") < page.index("<svg")  # seal on page one
    assert page.count("<script") == 1  # only the embedded report data
    paras = plain_english(doc)
    assert any(isinstance(p, str) and p.startswith("Bottom line") for p in paras)


def test_saved_html_keeps_the_seal(calendar, key, tmp_path):
    from hipaasynth.aast.report import save_document

    doc = _doc(run_by="J")
    seal(doc, key=key, timestamp=True)
    save_document(doc, tmp_path / "r.html")
    back = load_document(tmp_path / "r.html")
    assert back["seal"] == doc["seal"] and verify(back).ok


# --- CLI ----------------------------------------------------------------------------------


def test_cli_keygen_run_sign_stamp_upgrade_verify_proof(calendar, tmp_path, monkeypatch, capsys):
    keyfile = tmp_path / "me.json"
    monkeypatch.setenv("HIPAASYNTH_KEY", str(keyfile))
    assert aast_main(["keygen", "--signer", "Jordan Lee", "--organization", "Example"]) == 0
    assert "fingerprint" in capsys.readouterr().out
    report = tmp_path / "r.html"
    code = aast_main(["run", "--scenario", "tribal_sepsis", "--input", "record", "--n", "30",
                      "--demo", "demo_guideline", "--model-version", "9.9", "--run-by",
                      "Jordan Lee", "--sign", "--stamp", "--report", str(report)])  # fmt: skip
    assert code in (0, 2)
    out = capsys.readouterr().out
    assert "Sealed: signed by key" in out and "pending" in out
    doc = load_document(report)
    assert doc["method"]["provenance"]["scenario"] == "tribal_sepsis"
    assert doc["population"]["profile"] == "nd_tribal_region_a"
    assert aast_main(["upgrade", str(report)]) == 0
    assert "No Bitcoin proof yet" in capsys.readouterr().out
    calendar.mined = True
    assert aast_main(["upgrade", str(report)]) == 0
    assert aast_main(["verify", str(report), "--bitcoin", "--regenerate"]) == 0
    assert f"block {HEIGHT}" in capsys.readouterr().out
    assert aast_main(["proof", str(report), "--out", str(tmp_path / "p")]) == 0
    text = (tmp_path / "p.txt").read_bytes()
    assert (
        ots.info((tmp_path / "p.txt.ots").read_bytes()).digest == hashlib.sha256(text).hexdigest()
    )
    assert aast_main(["run", "--scenario", "tribal_sepsis", "--condition", "dka", "--input",
                      "record", "--demo", "demo_guideline"]) == 1  # fmt: skip


def test_cli_stamp_a_saved_report(calendar, key, tmp_path, capsys):
    report = tmp_path / "r.json"
    assert aast_main(["run", "--condition", "sepsis", "--input", "record", "--n", "30",
                      "--demo", "demo_guideline", "--report", str(report)]) in (0, 2)  # fmt: skip
    assert "seal" not in load_document(report)
    assert aast_main(["stamp", str(report), "--sign"]) == 0
    assert {c.name for c in verify(load_document(report)).checks} >= {"signature", "timestamp"}
    bad = load_document(report)
    bad["results"]["overall"] = "PASS" if bad["results"]["overall"] != "PASS" else "FAIL"
    report.write_text(json.dumps(bad))
    assert aast_main(["stamp", str(report)]) == 3  # never seal a report that does not verify


# --- web ----------------------------------------------------------------------------------

BASE = {"condition": "sepsis", "input": "record", "n": 30, "demo": "demo_guideline"}


def test_web_run_locks_provenance_and_seals(calendar, key):
    out = run_request({**BASE, "model_version": "4.0", "run_by": "Jordan Lee", "sign": True,
                       "stamp": True}, allow_url=True)  # fmt: skip
    doc = out["document"]
    assert out["seal_notes"] == [] and verify(doc).ok
    assert doc["method"]["provenance"]["model_version"] == "4.0"
    assert doc["method"]["provenance"]["started_utc"].endswith("Z")
    with pytest.raises(RequestError, match="local tool"):
        run_request({**BASE, "sign": True})
    with pytest.raises(RequestError, match="300"):
        run_request({**BASE, "run_by": "x" * 301}, allow_url=True)
    sc = run_request({**BASE, "condition": "", "scenario": "lagos_sepsis"})
    assert sc["document"]["population"]["profile"] == "lagos_nigeria"
    with pytest.raises(RequestError, match="is for"):
        run_request({**BASE, "condition": "dka", "scenario": "lagos_sepsis"})
    checked = verify_request({"document": doc, "regenerate": True})
    assert checked["ok"] and any(c["name"] == "signature" for c in checked["checks"])
    with pytest.raises(RequestError, match="local tool"):
        upgrade_request({"document": doc})
    calendar.mined = True
    up = upgrade_request({"document": doc}, allow_network=True)
    assert up["changed"] and "Bitcoin block" in up["html"]


def test_web_signing_key_is_made_on_first_use(calendar, tmp_path, monkeypatch):
    path = tmp_path / "new" / "key.json"
    monkeypatch.setenv("HIPAASYNTH_KEY", str(path))
    out = run_request({**BASE, "run_by": "Ana", "organization": "Clinic", "sign": True},
                      allow_url=True)  # fmt: skip
    assert path.exists() and out["document"]["seal"]["signature"]["signer"] == "Ana"


# --- in a real browser (the local tool) ----------------------------------------------------


def test_browser_sealed_run_print_and_check(calendar, key, tmp_path):
    from hipaasynth.api import make_server
    from tests.test_web_ui import _chromium_executable

    pw = pytest.importorskip("playwright.sync_api")
    srv = make_server("127.0.0.1", 0, allow_model_url=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    exe = _chromium_executable()
    try:
        with pw.sync_playwright() as p:
            try:
                browser = p.chromium.launch(**({"executable_path": exe} if exe else {}))
            except Exception as err:  # noqa: BLE001  # pragma: no cover
                pytest.skip(f"headless Chromium unavailable: {err}")
            pg = browser.new_page(accept_downloads=True)
            pg.goto(f"http://127.0.0.1:{srv.server_address[1]}/7aast", wait_until="networkidle")
            assert pg.is_visible("#signReport") and pg.is_visible("#stampReport")
            pg.select_option("#scenario", "lagos_sepsis")
            assert pg.input_value("#condition") == "sepsis" and pg.is_disabled("#condition")
            assert "Lagos" in pg.inner_text("#scenarioText")
            pg.check("input[name=input][value=record]")
            pg.fill("#modelVersion", "2.3.1")
            pg.fill("#runBy", "Jordan Lee")
            pg.fill("#organization", "Example Health")
            pg.click("details summary")
            pg.fill("#n", "30")
            pg.click("#runBtn")
            pg.wait_for_selector("#results:not(.hidden)", timeout=60_000)
            body = pg.frame_locator("#reportFrame").locator("body").inner_text()
            assert "Sealed test record" in body and "Jordan Lee" in body and "2.3.1" in body
            assert "lagos_sepsis" in body and "OpenTimestamps" in body
            assert "Signed with key" in pg.inner_text("#sealStatus")
            assert pg.is_visible("#printBtn") and pg.is_visible("#saveProof")
            downloads = []
            pg.on("download", lambda d: downloads.append(d))
            pg.click("#saveProof")
            pg.wait_for_timeout(500)
            files = {d.suggested_filename: Path(d.path()).read_bytes() for d in downloads}
            text, proof = files["7aast-report-hash.txt"], files["7aast-report-hash.txt.ots"]
            assert ots.info(proof).digest == hashlib.sha256(text).hexdigest()
            calendar.mined = True
            pg.click("#upgradeBtn")
            pg.wait_for_selector("#status.ok:has-text('Bitcoin proof added')", timeout=30_000)
            assert f"block {HEIGHT}" in pg.inner_text("#sealStatus")
            with pg.expect_download() as dl:
                pg.click("#saveHtml")
            saved = tmp_path / "saved.html"
            dl.value.save_as(saved)
            assert verify(load_document(saved), bitcoin=True).ok
            with pg.expect_download() as dl:
                pg.click("#saveJson")  # the saved data must verify too (no 20.0 -> 20 rewrite)
            saved_json = tmp_path / "saved.json"
            dl.value.save_as(saved_json)
            assert verify(load_document(saved_json), bitcoin=True).ok
            pg.set_input_files("#checkFile", str(saved))
            pg.wait_for_selector("#status.ok:has-text('checks out')", timeout=60_000)
            assert "signature" in pg.inner_text("#checkOut")
            pdf = tmp_path / "r.pdf"
            report_page = browser.new_page()
            report_page.goto(saved.as_uri())
            report_page.pdf(path=str(pdf), print_background=True)
            assert pdf.read_bytes()[:4] == b"%PDF"
            browser.close()
    finally:
        srv.shutdown()
        srv.server_close()


def test_shared_server_page_hides_signing(tmp_path):
    from hipaasynth.api import make_server

    srv = make_server("127.0.0.1", 0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        url = f"http://127.0.0.1:{srv.server_address[1]}"
        with urllib.request.urlopen(f"{url}/7aast", timeout=10) as resp:
            assert b'data-local-tool="1"' not in resp.read()
        req = urllib.request.Request(f"{url}/7aast/upgrade", method="POST",
                                     data=json.dumps({"document": _doc()}).encode(),
                                     headers={"Content-Type": "application/json"})  # fmt: skip
        with pytest.raises(urllib.error.HTTPError) as err:
            urllib.request.urlopen(req, timeout=30)
        assert err.value.code == 400
    finally:
        srv.shutdown()
        srv.server_close()


def test_proof_bytes_survive_base64():
    proof = (DATA / "hello-world.txt.ots").read_bytes()
    assert ots.decode(ots.encode(proof)) == proof == base64.b64decode(ots.encode(proof))
    with pytest.raises(ots.OTSError):
        ots.decode("not base64!!")
    assert BLOCK_TIME > 0


def test_web_llm_run_signed_never_records_the_api_key(calendar, key):
    """An LLM run with a typed-in key, signed and stamped: the API key goes nowhere."""
    from http.server import ThreadingHTTPServer

    from tests.test_aast_remote import _Model

    llm = ThreadingHTTPServer(("127.0.0.1", 0), _Model)
    threading.Thread(target=llm.serve_forever, daemon=True).start()
    try:
        out = run_request({"condition": "sepsis", "input": "text", "n": 30, "llm_provider": "openai",
                           "llm_model": "gpt-test", "llm_api_key": "sk-SECRET-typed",
                           "llm_base_url": f"http://127.0.0.1:{llm.server_address[1]}/v1",
                           "tests": ["groups"], "run_by": "Jordan Lee", "sign": True,
                           "stamp": True}, allow_url=True)  # fmt: skip
    finally:
        llm.shutdown()
        llm.server_close()
    assert out["document"]["seal"]["signature"]["signer"] == "Jordan Lee"
    assert verify(out["document"]).ok
    assert "SECRET" not in out["document_json"] + out["html"] + json.dumps(out["seal_notes"])
