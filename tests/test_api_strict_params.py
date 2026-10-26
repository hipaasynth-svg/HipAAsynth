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

"""The REST API must reject unknown parameters and answer every method in JSON.

Regression guard: a typo such as ``{"modul": "stroke"}`` was silently ignored
and returned a default (sepsis) cohort with HTTP 200; PUT/PATCH/DELETE/OPTIONS
fell through to http.server's HTML 501 page; and 405 responses had no body.
"""

import json
import threading
import urllib.error
import urllib.request

import pytest

from hipaasynth.api import make_server


@pytest.fixture
def server():
    srv = make_server(host="127.0.0.1", port=0, max_count=500)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield f"http://{srv.server_address[0]}:{srv.server_address[1]}"
    srv.shutdown()
    srv.server_close()
    thread.join(timeout=5)


def _request(url, method="GET", body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, resp.headers, resp.read()
    except urllib.error.HTTPError as err:
        return err.code, err.headers, err.read()


@pytest.mark.parametrize("path", [
    "/generate?count=2&modul=stroke",
    "/viz/demographics?count=5&colour=red",
    "/viz/fairness?count=5&modle=fair",
])
def test_unknown_query_param_is_400(server, path):
    status, headers, body = _request(server + path)
    assert status == 400
    assert headers.get("Content-Type") == "application/json"
    payload = json.loads(body)
    assert "unknown parameter(s)" in payload["error"] and "supported:" in payload["error"]


def test_unknown_json_body_key_is_400(server):
    status, _, body = _request(server + "/generate", "POST", {"count": 2, "modul": "stroke"})
    assert status == 400 and "modul" in json.loads(body)["error"]


@pytest.mark.parametrize("path", [
    "/generate?count=2&seed=1&module=stroke&format=csv",
    "/generate?count=2&scenario=tribal_stroke",
    "/viz/demographics?count=5&seed=1&module=stroke&profile=minot_nd",
    "/viz/demographics?count=5&format=json",  # format tolerated on viz routes
    "/viz/fairness?count=5&seed=1&scenario=tribal_stroke&model=biased",
])
def test_every_parameter_the_web_ui_sends_is_accepted(server, path):
    status, _, _ = _request(server + path)
    assert status == 200


@pytest.mark.parametrize("method", ["PUT", "PATCH", "DELETE", "OPTIONS"])
def test_unsupported_methods_get_json_405(server, method):
    status, headers, body = _request(server + "/generate", method)
    assert status == 405
    assert headers.get("Allow") == "GET, POST"
    assert headers.get("Content-Type") == "application/json"
    assert json.loads(body)["status"] == 405


def test_unsupported_method_on_unknown_route_is_json_404(server):
    status, _headers, body = _request(server + "/nope", "DELETE")
    assert status == 404 and json.loads(body)["status"] == 404


def test_post_to_get_only_route_has_json_body(server):
    status, headers, body = _request(server + "/health", "POST", {})
    assert status == 405 and headers.get("Allow") == "GET"
    assert json.loads(body)["error"].startswith("method POST not allowed for /health")
