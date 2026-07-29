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

"""Hand-rolled SVG visualizations (Tier 5 step 3).

Covers the pure aggregation, the well-formed-XML SVG output (parsed with the
stdlib XML parser — no rendering library needed), the per-form error-rate helper
added to the DIF report layer, and the two API endpoints that serve the SVGs.
"""
import threading
import urllib.error
import urllib.request
import xml.dom.minidom as minidom

import pytest

from hipaasynth.core.config import GenerationConfig
from hipaasynth.dif import DIFConfig, per_form_error_rates, run_audit
from hipaasynth.dif.model_interface import MockBiasedModel, MockFairModel
from hipaasynth.pipelines.population_pipeline import generate_patients
from hipaasynth.viz import (
    cohort_demographics,
    demographics_distribution_svg,
    fairness_heatmap_svg,
)


def _cohort(n=40, seed=7, condition="stroke"):
    cfg = GenerationConfig(
        patient_count=n, seed=seed, age_min=18, age_max=90,
        required_condition=condition, sex_ratio_female=0.5, ethnicity_weights=None,
        include_visits=True, include_labs=True, visits_min=1, visits_max=2,
        synthetic_disclaimer="synthetic", run_date="2026-07-29",
    )
    return cfg, generate_patients(cfg)


# ── demographics ─────────────────────────────────────────────────────────────


def test_cohort_demographics_counts_sum_to_n():
    _, patients = _cohort(n=50)
    dist = cohort_demographics(patients)
    for key in ("age", "sex", "ethnicity"):
        assert sum(c for _, c in dist[key]) == 50


def test_demographics_svg_is_wellformed_and_shows_counts():
    _, patients = _cohort(n=30)
    svg = demographics_distribution_svg(patients)
    minidom.parseString(svg)  # must be well-formed XML or this raises
    assert svg.startswith("<svg") and svg.endswith("</svg>")
    assert "n=30" in svg
    assert "no PHI" in svg  # the synthetic disclaimer is on the chart


def test_demographics_svg_reflects_actual_sex_split():
    _, patients = _cohort(n=40)
    dist = cohort_demographics(patients)
    svg = demographics_distribution_svg(patients)
    # Every observed sex label appears in the rendered SVG.
    for label, _ in dist["sex"]:
        assert label in svg


# ── per-form error rates + fairness heatmap ──────────────────────────────────


def test_per_form_error_rates_biased_model_hits_patient_forms():
    cfg, _ = _cohort(n=25)
    passports = run_audit(MockBiasedModel(), generate_patients, cfg,
                          DIFConfig(device_name="Biased", device_version="0.1"))
    rates = per_form_error_rates(passports)
    # The biased model under-triages patient/LEP forms but not clinician forms.
    assert rates["FHIR_STRUCTURED"] == 0.0
    assert rates["PATIENT_LOW_LITERACY"] > 0.0
    assert rates["LEP_TRANSLATED"] > 0.0


def test_fairness_heatmap_svg_is_wellformed():
    cfg, _ = _cohort(n=30)
    passports = run_audit(MockBiasedModel(), generate_patients, cfg,
                          DIFConfig(device_name="Biased", device_version="0.1"))
    svg = fairness_heatmap_svg(passports)
    minidom.parseString(svg)
    # All seven form labels and all four metric names are present.
    for label in ("FHIR", "Physician SOAP", "CHW"):
        assert label in svg
    for metric in ("DCS", "ISG", "LFDI", "SAF"):
        assert metric in svg


def test_fair_model_heatmap_all_zero_error():
    cfg, _ = _cohort(n=20)
    passports = run_audit(MockFairModel(), generate_patients, cfg,
                          DIFConfig(device_name="Fair", device_version="0.1"))
    rates = per_form_error_rates(passports)
    assert all(rate == 0.0 for rate in rates.values())


def test_fairness_heatmap_empty_raises():
    with pytest.raises(ValueError):
        fairness_heatmap_svg([])


# ── API endpoints ────────────────────────────────────────────────────────────


@pytest.fixture
def server():
    from hipaasynth.api import make_server

    srv = make_server(host="127.0.0.1", port=0, max_count=500)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    host, port = srv.server_address[0], srv.server_address[1]
    yield f"http://{host}:{port}"
    srv.shutdown()
    srv.server_close()
    thread.join(timeout=5)


def _get(url):
    with urllib.request.urlopen(url, timeout=30) as resp:
        return resp.status, resp.headers.get("Content-Type"), resp.read()


def test_viz_demographics_endpoint_returns_svg(server):
    status, ctype, body = _get(f"{server}/viz/demographics?scenario=tribal_stroke&count=20&seed=1")
    assert status == 200
    assert ctype.startswith("image/svg+xml")
    minidom.parseString(body)
    assert b"Population distribution" in body


def test_viz_fairness_endpoint_returns_svg(server):
    status, ctype, body = _get(f"{server}/viz/fairness?module=stroke&count=20&seed=2&model=biased")
    assert status == 200
    assert ctype.startswith("image/svg+xml")
    minidom.parseString(body)
    assert b"Fairness audit" in body


def test_viz_fairness_rejects_unknown_model(server):
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        _get(f"{server}/viz/fairness?model=bogus&count=5")
    assert excinfo.value.code == 400


def test_viz_fairness_rejects_oversized_count(server):
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        _get(f"{server}/viz/fairness?count=301&model=fair")
    assert excinfo.value.code == 400


# ── CLI --viz file output ────────────────────────────────────────────────────


def test_cli_viz_writes_svg_file(tmp_path):
    from hipaasynth.run.main import main

    rc = main([
        "--scenario", "us_baseline_sepsis", "--count", "10", "--seed", "1",
        "--format", "json", "--viz", "--out", str(tmp_path),
    ])
    assert rc == 0
    svg_path = tmp_path / "demographics.svg"
    assert svg_path.exists()
    minidom.parse(str(svg_path))  # well-formed XML
    assert "Population distribution" in svg_path.read_text()
