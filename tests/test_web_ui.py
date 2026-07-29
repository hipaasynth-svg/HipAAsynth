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

"""Web UI (Tier 5 step 1) — driven in a *real* headless Chromium via Playwright.

Unlike prior tiers (no live browser), this sandbox ships Chromium + Playwright,
so the UI is verified for real: we launch the stdlib API server on an ephemeral
port, load ``GET /`` in headless Chromium, drive the form, and assert both that a
network request actually went to ``/generate`` and that the returned cohort is
rendered into the DOM. Tests that need a browser ``skip`` cleanly when Playwright
or the bundled Chromium is unavailable, so the suite still runs elsewhere.
"""
from __future__ import annotations

import glob
import threading

import pytest

from hipaasynth.api import make_server


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


def _chromium_executable() -> str | None:
    """Locate the sandbox's bundled Chromium (Playwright's own copy may be absent)."""
    for pattern in (
        "/opt/pw-browsers/chromium-*/chrome-linux/chrome",
        "/opt/pw-browsers/chromium_headless_shell-*/chrome-linux/headless_shell",
    ):
        hits = sorted(glob.glob(pattern))
        if hits:
            return hits[-1]
    return None


@pytest.fixture
def browser():
    pw = pytest.importorskip("playwright.sync_api")
    exe = _chromium_executable()
    launch_kwargs = {"executable_path": exe} if exe else {}
    with pw.sync_playwright() as p:
        try:
            b = p.chromium.launch(**launch_kwargs)
        except Exception as err:  # pragma: no cover - environment-dependent
            pytest.skip(f"headless Chromium unavailable: {err}")
        yield b
        b.close()


# ── plain-HTTP checks (no browser needed) ────────────────────────────────────


def test_root_serves_html(server):
    import urllib.request

    with urllib.request.urlopen(f"{server}/", timeout=10) as resp:
        assert resp.status == 200
        assert resp.headers.get("Content-Type").startswith("text/html")
        body = resp.read().decode("utf-8")
    assert "HipAAsynth" in body
    assert "/generate" in body  # the client wires itself to the real endpoint


# ── real headless-browser drive ──────────────────────────────────────────────


def test_ui_generates_cohort_in_browser(server, browser):
    page = browser.new_page()
    generate_calls: list[str] = []
    page.on("request", lambda req: generate_calls.append(req.url)
            if "/generate" in req.url else None)

    page.goto(server, wait_until="networkidle")
    # Capabilities loaded from the real /formats endpoint populate the selects.
    page.wait_for_selector("#status.ok", timeout=10_000)
    assert page.locator("#module option").count() >= 4  # sepsis/stroke/dka/fabry

    page.select_option("#module", "stroke")
    page.fill("#count", "7")
    page.fill("#seed", "5")
    page.click("#genBtn")

    # A real request must have gone out, and the rendered result must reflect it.
    page.wait_for_selector("#patientCount", timeout=15_000)
    assert page.inner_text("#patientCount") == "7"
    assert any("/generate" in u and "count=7" in u for u in generate_calls), generate_calls
    status = page.inner_text("#status")
    assert "7 synthetic patients" in status
    # The rendered sample is a real patient record from the engine.
    sample = page.inner_text("#sample")
    assert "demographics" in sample
    page.close()


def test_ui_scenario_dropdown_drives_generation(server, browser):
    page = browser.new_page()
    generate_calls: list[str] = []
    page.on("request", lambda req: generate_calls.append(req.url)
            if "/generate" in req.url else None)
    page.goto(server, wait_until="networkidle")
    page.wait_for_selector("#status.ok", timeout=10_000)

    # The scenario <select> is populated from the real /scenarios endpoint.
    assert page.locator("#scenario option").count() >= 5  # blank + blueprints
    page.select_option("#scenario", "tribal_stroke")
    # Picking a scenario reflects + locks its module/profile.
    assert page.input_value("#module") == "stroke"
    assert page.input_value("#profile") == "nd_tribal_region_a"
    assert page.locator("#module").is_disabled()
    desc = page.inner_text("#scenarioDesc")
    assert desc.strip()  # a human-readable description is shown

    page.fill("#count", "6")
    page.click("#genBtn")
    page.wait_for_selector("#patientCount", timeout=15_000)
    assert page.inner_text("#patientCount") == "6"
    assert any("scenario=tribal_stroke" in u for u in generate_calls), generate_calls
    page.close()


def test_ui_renders_viz_svgs_in_browser(server, browser):
    page = browser.new_page()
    page.goto(server, wait_until="networkidle")
    page.wait_for_selector("#status.ok", timeout=10_000)
    page.select_option("#module", "stroke")
    page.fill("#count", "20")
    page.click("#genBtn")
    page.wait_for_selector("#patientCount", timeout=15_000)
    # Both server-rendered SVGs must land in the #viz panel (population + fairness).
    page.wait_for_selector("#viz svg", timeout=15_000)
    page.wait_for_function("document.querySelectorAll('#viz svg').length >= 2",
                           timeout=15_000)
    viz_text = page.inner_text("#viz")
    assert "Population distribution" in viz_text
    assert "Fairness heatmap" in viz_text
    page.close()


def test_ui_download_triggers_download(server, browser):
    page = browser.new_page()
    page.goto(server, wait_until="networkidle")
    page.wait_for_selector("#status.ok", timeout=10_000)
    page.select_option("#module", "sepsis")
    page.fill("#count", "3")
    page.select_option("#format", "csv")
    with page.expect_download(timeout=15_000) as dl_info:
        page.click("#dlBtn")
    download = dl_info.value
    assert download.suggested_filename == "cohort.csv"
    page.close()
