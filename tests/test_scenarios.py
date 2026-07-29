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

"""Scenario blueprints (Tier 5 step 2).

A scenario is a named ``(module, profile)`` shortcut. These tests pin that every
bundled blueprint resolves to a *real* engine module and a *real* bundled
profile (no invented conditions), and that the shortcut is wired additively into
the CLI and REST API without changing what ``--module``/``--profile`` do alone.
"""
import json
import threading
import urllib.error
import urllib.request

import pytest

from hipaasynth.api import make_server, parse_generate_request
from hipaasynth.sdk import MODULES, available_profiles
from hipaasynth.scenarios import (
    ScenarioError,
    available_scenarios,
    get_scenario,
    load_scenarios,
    resolve_scenario,
    scenario_summaries,
)


# ── blueprint integrity ──────────────────────────────────────────────────────


def test_scenarios_are_non_empty():
    assert len(available_scenarios()) >= 4


def test_every_scenario_uses_a_real_module_and_profile():
    profiles = set(available_profiles())
    for name, scenario in load_scenarios().items():
        assert scenario.module in MODULES, f"{name} → fake module {scenario.module!r}"
        assert scenario.profile in profiles, f"{name} → fake profile {scenario.profile!r}"
        assert scenario.description.strip(), f"{name} has no description"


def test_resolve_scenario_returns_module_and_profile():
    resolved = resolve_scenario("tribal_sepsis")
    assert resolved == {"module": "sepsis", "profile": "nd_tribal_region_a"}


def test_unknown_scenario_raises():
    with pytest.raises(ScenarioError):
        get_scenario("does_not_exist")


def test_scenario_summaries_are_json_serializable():
    summaries = scenario_summaries()
    json.dumps(summaries)  # must not raise
    assert {"name", "module", "profile", "description", "label"} <= set(summaries[0])


# ── API wiring ───────────────────────────────────────────────────────────────


def test_parse_generate_request_expands_scenario():
    req = parse_generate_request({"scenario": "karachi_dka", "count": "5"})
    assert req["module"] == "dka"
    assert req["profile"] == "karachi_pakistan"
    assert req["scenario"] == "karachi_dka"


def test_explicit_module_overrides_scenario_module():
    # Scenario is additive: an explicit module still wins (doesn't change what
    # --module does on its own).
    req = parse_generate_request({"scenario": "karachi_dka", "module": "stroke"})
    assert req["module"] == "stroke"
    assert req["profile"] == "karachi_pakistan"  # profile still from scenario


def test_parse_generate_request_rejects_unknown_scenario():
    from hipaasynth.api import ApiError

    with pytest.raises(ApiError) as excinfo:
        parse_generate_request({"scenario": "not_a_scenario"})
    assert excinfo.value.status == 400


@pytest.fixture
def server():
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
        return resp.status, json.loads(resp.read())


def test_scenarios_endpoint_lists_blueprints(server):
    status, payload = _get(f"{server}/scenarios")
    assert status == 200
    names = {s["name"] for s in payload["scenarios"]}
    assert set(available_scenarios()) == names


def test_formats_includes_scenario_names(server):
    _, payload = _get(f"{server}/formats")
    assert "scenarios" in payload
    assert set(payload["scenarios"]) == set(available_scenarios())


def test_generate_via_scenario_over_http(server):
    status, patients = _get(f"{server}/generate?scenario=tribal_stroke&count=6&seed=1")
    assert status == 200
    assert len(patients) == 6


# ── CLI wiring ───────────────────────────────────────────────────────────────


def test_cli_scenario_generates(tmp_path):
    from hipaasynth.run.main import main

    rc = main([
        "--scenario", "us_baseline_sepsis", "--count", "4", "--seed", "3",
        "--format", "json", "--out", str(tmp_path),
    ])
    assert rc == 0
    cohort = json.loads((tmp_path / "cohort.json").read_text())
    assert len(cohort) == 4


def test_cli_scenario_conflicts_with_module(tmp_path):
    from hipaasynth.run.main import main

    with pytest.raises(SystemExit):  # argparse parser.error
        main([
            "--scenario", "us_baseline_sepsis", "--module", "stroke",
            "--out", str(tmp_path),
        ])
