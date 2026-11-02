"""Models behind a URL or an LLM API, and the published clinical scores."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import ClassVar

import pytest

from hipaasynth.aast.cli import main as aast_main
from hipaasynth.aast.demo import _record_measurements
from hipaasynth.aast.reference import (
    REFERENCE_MODELS,
    news2,
    qsofa,
    reference_adapter,
    rosier,
    sirs,
)
from hipaasynth.aast.remote import (
    RemoteModelError,
    llm_adapter,
    llm_prompt,
    public_endpoint,
    url_adapter,
)
from hipaasynth.aast.run import TESTS, run_7aast
from hipaasynth.aast.web import RequestError, run_request


def _sepsis_rule(case):
    """A model server's logic: flag when the lactate in the record is >= 2."""
    if isinstance(case, str):
        return "FINAL_ANSWER: Yes" if "Lactate" in case else "FINAL_ANSWER: No"
    return (case.get("observations", {}).get("lactate_initial") or 0) >= 2.0


class _Model(BaseHTTPRequestHandler):
    seen: ClassVar[list] = []

    def log_message(self, *args):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        path = self.path.split("?")[0]
        headers = {k.lower(): v for k, v in self.headers.items()}
        _Model.seen.append((path, headers, body))
        if path == "/predict":
            reply = {"answer": _sepsis_rule(body["case"])}
        elif path == "/plain":
            reply = None
        elif path == "/broken":
            reply = {"result": 1}
        elif path == "/v1/chat/completions":
            case = body["messages"][1]["content"]
            reply = {"choices": [{"message": {"content": "Reasoning.\n" + _llm(case)}}]}
        elif path == "/v1/messages":
            reply = {"content": [{"type": "text", "text": _llm(body["messages"][0]["content"])}]}
        else:
            self.send_response(404)
            self.end_headers()
            return
        data = b"yes" if reply is None else json.dumps(reply).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain" if reply is None else "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def _llm(prompt: str) -> str:
    return "FINAL_ANSWER: Yes" if "lactate" in prompt.lower() else "FINAL_ANSWER: No"


@pytest.fixture(scope="module")
def server():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Model)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()
    srv.server_close()


# --- model at a URL -------------------------------------------------------------------


def test_url_model_runs_and_never_records_secrets(server):
    adapter = url_adapter(f"{server}/predict?key=SECRET", "binary", input="record",
                          condition="sepsis", headers={"Authorization": "Bearer TOKEN"})  # fmt: skip
    report = run_7aast(adapter, "sepsis", n=20)
    assert report.model["name"] == f"model at {server}/predict"
    blob = json.dumps(report.to_dict())
    assert "SECRET" not in blob and "TOKEN" not in blob
    path, headers, body = _Model.seen[-1]
    assert path.startswith("/predict") and headers["authorization"] == "Bearer TOKEN"
    assert set(body) == {"case", "condition", "input"} and body["condition"] == "sepsis"


def test_url_model_plain_text_and_bad_replies(server):
    plain = url_adapter(f"{server}/plain", "binary", input="record", condition="sepsis")
    assert run_7aast(plain, "sepsis", n=10).axis("accuracy").metrics["false_alarms"] == 5
    broken = url_adapter(f"{server}/broken", "binary", input="record", condition="sepsis")
    with pytest.raises(RemoteModelError, match="without an 'answer'"):
        run_7aast(broken, "sepsis", n=10)
    missing = url_adapter(f"{server}/nope", "binary", input="record", condition="sepsis")
    with pytest.raises(RemoteModelError, match="HTTP 404"):
        run_7aast(missing, "sepsis", n=10)
    with pytest.raises(ValueError, match="http"):
        url_adapter("file:///etc/passwd", "binary", input="record", condition="sepsis")


def test_public_endpoint_strips_credentials():
    assert public_endpoint("https://u:p@host:8443/v1/x?key=1#f") == "https://host:8443/v1/x"


def test_cli_url_and_header(server, capsys):
    code = aast_main(["run", "--condition", "sepsis", "--input", "record", "--n", "20",
                      "--url", f"{server}/predict", "--header", "X-Key: abc"])  # fmt: skip
    out = capsys.readouterr().out
    assert code in (0, 2) and "OVERALL" in out
    assert _Model.seen[-1][1]["x-key"] == "abc"
    assert aast_main(["run", "--condition", "sepsis", "--input", "record",
                      "--url", f"{server}/predict", "--header", "nocolon"]) == 1  # fmt: skip


# --- LLM APIs -------------------------------------------------------------------------


@pytest.mark.parametrize("provider", ["openai", "anthropic"])
def test_llm_adapter_speaks_both_formats(server, provider):
    adapter = llm_adapter(provider, "test-model", input="text", condition="sepsis",
                          base_url=f"{server}/v1", api_key="KEY")  # fmt: skip
    report = run_7aast(adapter, "sepsis", n=20)
    assert report.model["name"] == f"{provider}:test-model"
    assert report.answer_rates["unreadable"] == 0
    path, headers, body = _Model.seen[-1]
    assert body["temperature"] == 0
    if provider == "anthropic":
        assert path == "/v1/messages" and headers["x-api-key"] == "KEY"
    else:
        assert path == "/v1/chat/completions" and headers["authorization"] == "Bearer KEY"
    assert "KEY" not in json.dumps(report.to_dict())


def test_llm_needs_a_key_for_the_public_api(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        llm_adapter("openai", "gpt-x", input="text", condition="sepsis")
    with pytest.raises(ValueError, match="provider"):
        llm_adapter("mystery", "m", input="text", condition="sepsis")


def test_llm_prompt_asks_one_question_and_shows_the_case():
    prompt = llm_prompt({"observations": {"x": 1}}, "stroke")
    assert prompt.startswith("Is this patient having an acute stroke") and '"x": 1' in prompt


# --- published clinical scores --------------------------------------------------------


def test_scores_follow_their_published_rules():
    infected = {"Suspected infection source": "pneumonia"}
    assert qsofa({**infected, "RR": "24", "SBP": "98", "Mental status": "alert"}) is True
    assert qsofa({**infected, "RR": "24", "SBP": "120", "Mental status": "alert"}) is False
    assert qsofa({"Suspected infection source": "none_suspected", "RR": "30", "SBP": "80"}) is False
    assert sirs({**infected, "Temp": "38.5", "HR": "95", "RR": "16", "WBC": "8"}) is True
    assert sirs({**infected, "Temp": "37", "HR": "80", "RR": "16", "WBC": "3.5"}) is False
    # NEWS2: RR 25 (3) + SpO2 91 (3) + SBP 95 (2) + HR 115 (2) + temp 39.5 (2) + confusion (3)
    assert news2({"RR": "25", "SpO2": "91", "SBP": "95", "HR": "115", "Temp": "39.5",
                  "Mental status": "altered"}) == 15  # fmt: skip
    assert news2({"RR": "16", "SpO2": "98", "SBP": "125", "HR": "75", "Temp": "37"}) == 0
    assert rosier({"NIHSS": "6", "Glucose": "110"}) is True
    assert rosier({"NIHSS": "6", "Glucose": "40"}) is False  # hypoglycaemia excluded first
    assert rosier({"NIHSS": "2", "Glucose": "110", "Seizure at onset": "Yes"}) is False


def test_reference_scores_reproduce_their_known_behaviour():
    """qSOFA misses many cases; SIRS raises many false alarms (as the literature reports)."""
    results = {}
    for name in ("qsofa", "sirs"):
        report = run_7aast(reference_adapter(name, "record"), "sepsis", n=200)
        results[name] = report.axis("accuracy").metrics
        assert report.limitations[0].startswith("REFERENCE")
    assert results["qsofa"]["sensitivity"]["estimate"] < 0.6
    assert results["sirs"]["sensitivity"]["estimate"] > 0.8  # ~1 in 8 sepsis is SIRS-negative
    assert results["sirs"]["specificity"]["estimate"] < 0.7
    split = results["qsofa"]["sensitivity_by_presentation"]
    assert split["normotensive"]["estimate"] < split["septic_shock"]["estimate"]


@pytest.mark.parametrize("name", sorted(REFERENCE_MODELS))
def test_reference_scores_read_text_and_records_the_same_way(name):
    condition = REFERENCE_MODELS[name][0]
    text = run_7aast(reference_adapter(name, "text"), condition, n=60)
    record = run_7aast(reference_adapter(name, "record"), condition, n=60)
    assert (
        text.axis("accuracy").metrics["sensitivity"]
        == record.axis("accuracy").metrics["sensitivity"]
    )


def test_record_measurements_carry_what_the_scores_need():
    case = {"observations": {"spo2_initial": 93, "wbc_initial": 3.2, "dbp_initial": 60}}
    assert _record_measurements(case) == {"SpO2": 93, "WBC": 3.2, "DBP": 60}


def test_cli_reference_must_match_the_condition(capsys):
    assert aast_main(["run", "--condition", "stroke", "--input", "record",
                      "--reference", "qsofa"]) == 1  # fmt: skip
    assert "decides sepsis" in capsys.readouterr().err


# --- over the web API -----------------------------------------------------------------


def test_web_reference_and_url_rules(server):
    base = {"condition": "sepsis", "input": "record", "n": 20}
    result = run_request({**base, "reference": "news2"})
    assert result["document"]["method"]["model"]["output"] == "score"
    with pytest.raises(RequestError, match="only accepted by the local tool"):
        run_request({**base, "url": f"{server}/predict"})
    ok = run_request({**base, "url": f"{server}/predict"}, allow_url=True)
    assert ok["document"]["method"]["model"]["name"].startswith("model at ")
    with pytest.raises(RequestError, match="exactly one"):
        run_request({**base, "reference": "qsofa", "demo": "demo_guideline"})
    with pytest.raises(RequestError, match="decides stroke"):
        run_request({**base, "reference": "rosier"})


# --- LLM with a typed-in key, and choosing which checks run (the 7AAST page) -----------


def test_web_llm_with_typed_key_never_records_it(server):
    _Model.seen.clear()
    params = {"condition": "sepsis", "input": "text", "n": 30, "llm_provider": "openai",
              "llm_model": "gpt-test", "llm_base_url": f"{server}/v1",
              "llm_api_key": "sk-typed-SECRET-123"}  # fmt: skip
    out = run_request(params, allow_url=True)
    assert out["document"]["method"]["model"]["name"] == "openai:gpt-test"
    assert any(h.get("authorization") == "Bearer sk-typed-SECRET-123" for _, h, _ in _Model.seen)
    text = json.dumps(out["document"]) + out["html"] + out["summary"]
    assert "SECRET" not in text
    with pytest.raises(RequestError, match="only accepted by the local tool"):
        run_request(params)
    with pytest.raises(RequestError, match="llm_model"):
        run_request({**params, "llm_model": " "}, allow_url=True)
    with pytest.raises(RequestError, match="llm_provider"):
        run_request({**params, "llm_provider": "gemini"}, allow_url=True)


def test_web_anthropic_key_goes_in_its_header(server):
    _Model.seen.clear()
    run_request({"condition": "sepsis", "input": "record", "n": 30, "llm_provider": "anthropic",
                 "llm_model": "claude-test", "llm_base_url": f"{server}/v1",
                 "llm_api_key": "anthropic-key", "tests": ["groups"]},
                allow_url=True)  # fmt: skip
    assert all(h.get("x-api-key") == "anthropic-key" for p, h, _ in _Model.seen)
    assert {p for p, _, _ in _Model.seen} == {"/v1/messages"}


def test_chosen_tests_skip_their_calls_and_are_hashed():
    from hipaasynth.aast.demo import demo_adapter
    from hipaasynth.aast.report import build_document, verify

    adapter = demo_adapter("demo_guideline", "sepsis", "text")
    full = run_7aast(adapter, "sepsis", n=40, demo=True)
    part = run_7aast(adapter, "sepsis", n=40, demo=True, tests=["groups"])
    assert {a.axis for a in part.axes} == {"accuracy", "2b"}
    assert part.model_calls == 40 < full.model_calls
    assert part.settings["tests"] == ["groups"] and "tests" not in full.settings
    assert "PARTIAL RUN" in part.limitations[1] and part.limitations[0].startswith("DEMO")
    assert not any("PARTIAL" in x for x in full.limitations)
    doc = build_document(part)
    assert verify(doc).ok
    doc["method"]["settings"]["tests"] = list(TESTS)  # claim every check ran
    assert not verify(doc).ok
    with pytest.raises(ValueError, match="unknown test"):
        run_7aast(adapter, "sepsis", n=40, tests=["axis9"])
    with pytest.raises(RequestError, match="unknown test"):
        run_request({"condition": "sepsis", "input": "text", "n": 30, "demo": "demo_guideline",
                     "tests": ["axis9"]})  # fmt: skip
    with pytest.raises(RequestError, match="list"):
        run_request({"condition": "sepsis", "input": "text", "n": 30, "demo": "demo_guideline",
                     "tests": "groups"})  # fmt: skip


def test_cli_tests_flag(capsys):
    assert aast_main(["run", "--condition", "sepsis", "--input", "record", "--n", "30",
                      "--demo", "demo_guideline", "--tests", "groups,history"]) in (0, 2)  # fmt: skip
    out = capsys.readouterr().out
    assert "PARTIAL RUN" in out
    assert aast_main(["run", "--condition", "sepsis", "--input", "record", "--n", "30",
                      "--demo", "demo_guideline", "--tests", "nope"]) == 1  # fmt: skip


def test_local_tool_refuses_other_hosts_and_origins():
    import urllib.error
    import urllib.request

    from hipaasynth.api import make_server

    srv = make_server("127.0.0.1", 0, allow_model_url=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]
    body = json.dumps({"condition": "sepsis", "input": "record", "n": 30,
                       "demo": "demo_guideline", "tests": ["groups"]}).encode()  # fmt: skip

    def post(extra):
        req = urllib.request.Request(f"http://127.0.0.1:{port}/7aast", data=body, method="POST",
                                     headers={"Content-Type": "application/json", **extra})  # fmt: skip
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return resp.status
        except urllib.error.HTTPError as err:
            return err.code

    try:
        assert post({}) == 200
        assert post({"Origin": f"http://localhost:{port}"}) == 200
        assert post({"Host": f"evil.example:{port}"}) == 403  # DNS rebinding
        assert post({"Origin": "https://evil.example"}) == 403  # another site's page
    finally:
        srv.shutdown()
        srv.server_close()


def test_llm_answer_length_is_sent_recorded_and_checked(server):
    base = {"condition": "sepsis", "input": "record", "n": 30, "llm_provider": "openai",
            "llm_model": "Orinn-1.7", "llm_base_url": f"{server}/v1", "llm_api_key": "k",
            "tests": ["groups"]}  # fmt: skip
    _Model.seen.clear()
    out = run_request(base, allow_url=True)
    assert {b["max_tokens"] for _, _, b in _Model.seen} == {1024}  # the default
    assert out["document"]["method"]["model"]["name"] == "openai:Orinn-1.7"
    _Model.seen.clear()
    out = run_request({**base, "llm_max_tokens": 4096}, allow_url=True)
    assert {b["max_tokens"] for _, _, b in _Model.seen} == {4096}
    assert out["document"]["method"]["model"]["name"] == "openai:Orinn-1.7 (max 4096 tokens)"
    for bad in (0, 99999, "lots"):
        with pytest.raises(RequestError, match="llm_max_tokens"):
            run_request({**base, "llm_max_tokens": bad}, allow_url=True)
    with pytest.raises(ValueError, match="max_tokens"):
        llm_adapter("openai", "m", input="text", condition="sepsis", api_key="k", max_tokens=5)


def test_cli_llm_max_tokens(server, monkeypatch, capsys):
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    _Model.seen.clear()
    code = aast_main(["run", "--condition", "sepsis", "--input", "record", "--n", "30",
                      "--llm", "openai", "--llm-model", "Orinn-1.7", "--llm-base-url",
                      f"{server}/v1", "--llm-max-tokens", "2048", "--tests", "groups"])  # fmt: skip
    assert code in (0, 2)
    assert {b["max_tokens"] for _, _, b in _Model.seen} == {2048}
