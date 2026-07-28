# HipAAsynth — Synthetic health data fairness testing for invisible populations.
# Copyright (C) 2026 HipAAsynth Contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published
# by the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.

"""REST API (Tier 2 step 2).

These tests run the **real** stdlib server in a background thread on an ephemeral
port and hit it over an actual localhost socket with urllib — there is no live
external deployment in this sandbox, so this in-process-server-over-real-HTTP is
how the network surface is verified (stated plainly, per the ground rules).
"""
import csv
import io
import json
import threading
import urllib.error
import urllib.request

import pytest

from hipaasynth.api import make_server, parse_generate_request, ApiError


@pytest.fixture
def server():
    """A running HipAAsynth API server on an ephemeral port; torn down after."""
    srv = make_server(host="127.0.0.1", port=0, max_count=500)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    host, port = srv.server_address[0], srv.server_address[1]
    yield f"http://{host}:{port}"
    srv.shutdown()
    srv.server_close()
    thread.join(timeout=5)


def _get(url):
    with urllib.request.urlopen(url, timeout=10) as resp:
        return resp.status, resp.headers.get("Content-Type"), resp.read()


def _post(url, body, content_type="application/json"):
    data = body if isinstance(body, bytes) else json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method="POST",
                                 headers={"Content-Type": content_type})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return resp.status, resp.headers.get("Content-Type"), resp.read()


# ── health / discovery ───────────────────────────────────────────────────────

def test_health(server):
    status, ctype, body = _get(f"{server}/health")
    assert status == 200
    payload = json.loads(body)
    assert payload["status"] == "ok"
    assert "engine_version" in payload


def test_formats_lists_capabilities(server):
    status, _, body = _get(f"{server}/formats")
    assert status == 200
    payload = json.loads(body)
    assert "json" in payload["formats"] and "ndjson" in payload["formats"]
    assert "sepsis" in payload["modules"] and "stroke" in payload["modules"]
    assert isinstance(payload["profiles"], list)


# ── generation happy paths ───────────────────────────────────────────────────

def test_generate_json_default(server):
    status, ctype, body = _get(f"{server}/generate?count=4&seed=7")
    assert status == 200
    assert "application/json" in ctype
    cohort = json.loads(body)
    assert isinstance(cohort, list) and len(cohort) == 4


def test_generate_is_deterministic_for_same_seed(server):
    _, _, a = _get(f"{server}/generate?count=5&seed=123")
    _, _, b = _get(f"{server}/generate?count=5&seed=123")
    assert a == b  # same seed => byte-identical cohort


def test_generate_different_seed_differs(server):
    _, _, a = _get(f"{server}/generate?count=5&seed=1")
    _, _, b = _get(f"{server}/generate?count=5&seed=2")
    assert a != b


def test_generate_csv(server):
    status, ctype, body = _get(f"{server}/generate?count=3&format=csv")
    assert status == 200
    assert "text/csv" in ctype
    rows = list(csv.DictReader(io.StringIO(body.decode())))
    assert len(rows) == 3
    assert "patient_id" in rows[0]


def test_generate_fhir_bundle(server):
    status, ctype, body = _get(f"{server}/generate?count=2&format=fhir-bundle")
    assert status == 200
    assert "fhir+json" in ctype
    bundle = json.loads(body)
    assert bundle["resourceType"] == "Bundle"
    assert bundle["entry"]


def test_generate_omop(server):
    status, ctype, body = _get(f"{server}/generate?count=3&format=omop")
    assert status == 200
    tables = json.loads(body)
    assert "person" in tables and len(tables["person"]) == 3


def test_generate_ndjson_streamed(server):
    """NDJSON is chunk-streamed; urllib de-chunks transparently."""
    status, ctype, body = _get(f"{server}/generate?count=3&format=ndjson")
    assert status == 200
    assert "x-ndjson" in ctype
    lines = [ln for ln in body.decode().splitlines() if ln.strip()]
    assert lines
    for ln in lines:
        resource = json.loads(ln)  # every line is a standalone JSON resource
        assert "resourceType" in resource


def test_generate_parquet(server):
    """Parquet format returns a real Parquet binary (optional pyarrow extra)."""
    pytest.importorskip("pyarrow")
    import pyarrow.parquet as pq

    status, ctype, body = _get(f"{server}/generate?count=3&format=parquet")
    assert status == 200
    assert "parquet" in ctype
    assert body[:4] == b"PAR1"  # Parquet magic bytes
    table = pq.read_table(io.BytesIO(body))
    assert table.num_rows == 3


def test_generate_module_stroke(server):
    status, _, body = _get(f"{server}/generate?count=3&module=stroke&format=csv")
    assert status == 200
    rows = list(csv.DictReader(io.StringIO(body.decode())))
    assert len(rows) == 3


def test_generate_post_json_body(server):
    status, ctype, body = _post(f"{server}/generate",
                                {"count": 6, "seed": 9, "format": "json"})
    assert status == 200
    assert len(json.loads(body)) == 6


def test_generate_with_bundled_profile(server):
    status, _, body = _get(f"{server}/generate?count=3&profile=us_default&format=json")
    assert status == 200
    assert len(json.loads(body)) == 3


# ── input validation / error responses ───────────────────────────────────────

def _expect_status(url, expected):
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            return resp.status
    except urllib.error.HTTPError as e:
        return e.code


def test_bad_count_non_integer_is_400(server):
    assert _expect_status(f"{server}/generate?count=abc", 400) == 400


def test_bad_count_zero_is_400(server):
    assert _expect_status(f"{server}/generate?count=0", 400) == 400


def test_count_over_max_is_400(server):
    # fixture max_count=500
    assert _expect_status(f"{server}/generate?count=999999", 400) == 400


def test_negative_seed_is_400(server):
    assert _expect_status(f"{server}/generate?seed=-1", 400) == 400


def test_unknown_format_is_400(server):
    assert _expect_status(f"{server}/generate?format=xml", 400) == 400


def test_unknown_module_is_400(server):
    assert _expect_status(f"{server}/generate?module=nope", 400) == 400


def test_unknown_profile_is_400(server):
    assert _expect_status(f"{server}/generate?profile=atlantis", 400) == 400


def test_error_body_is_json_with_message(server):
    try:
        urllib.request.urlopen(f"{server}/generate?count=abc", timeout=10)
        assert False, "expected HTTPError"
    except urllib.error.HTTPError as e:
        payload = json.loads(e.read())
        assert payload["status"] == 400
        assert "count" in payload["error"]


def test_unknown_route_is_404(server):
    assert _expect_status(f"{server}/nope", 404) == 404


def test_wrong_method_is_405(server):
    """POST to a GET-only route returns 405 with an Allow header."""
    req = urllib.request.Request(f"{server}/health", data=b"{}", method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=10)
        assert False, "expected HTTPError"
    except urllib.error.HTTPError as e:
        assert e.code == 405
        assert "GET" in (e.headers.get("Allow") or "")


def test_invalid_json_body_is_400(server):
    assert _expect_status_post(server, b"{not json", "application/json") == 400


def _expect_status_post(server, body, ctype):
    req = urllib.request.Request(f"{server}/generate", data=body, method="POST",
                                 headers={"Content-Type": ctype})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status
    except urllib.error.HTTPError as e:
        return e.code


# ── unit-level validation (no server) ────────────────────────────────────────

def test_parse_generate_request_defaults():
    req = parse_generate_request({})
    assert req["count"] == 100 and req["seed"] == 42
    assert req["format"] == "json" and req["module"] == "sepsis"


def test_parse_generate_request_rejects_bad_seed():
    with pytest.raises(ApiError) as exc:
        parse_generate_request({"seed": "not-an-int"})
    assert exc.value.status == 400
