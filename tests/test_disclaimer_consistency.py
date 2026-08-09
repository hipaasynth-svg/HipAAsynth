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

"""All generators emit one canonical synthetic-data disclaimer (issue #31).

Previously the module generators (oud/chf/copd) carried a different disclaimer
string from the pipeline path. This locks in the consolidation: every generator
stamps records with ``DEFAULT_SYNTHETIC_DISCLAIMER``.

The second half of this file extends that invariant to the *rendered* surfaces —
the web UI and the SVG visualizations (issue #92). Those are the surfaces built
for people who are not reading the source, and they are the ones with no type
checker behind them: plain HTML and hand-assembled SVG strings, where a styling
edit can quietly delete a paragraph of disclosure and every other test still
passes.
"""

import re
import threading
import urllib.request
from pathlib import Path

import pytest

import hipaasynth.modules.chf.chf_generator as chf
import hipaasynth.modules.copd.copd_generator as copd
import hipaasynth.modules.oud.oud_generator as oud
from hipaasynth.core.config import DEFAULT_SYNTHETIC_DISCLAIMER, GenerationConfig
from hipaasynth.dif import DIFConfig, run_audit
from hipaasynth.dif.model_interface import MockBiasedModel
from hipaasynth.modules.diabetes.population import DiabetesPopulationGenerator
from hipaasynth.modules.dmd.dmd import DMDCohortGenerator
from hipaasynth.modules.fabry.fabry import FabryCohortGenerator
from hipaasynth.modules.sma.sma import SMACohortGenerator
from hipaasynth.pipelines.population_pipeline import generate_patients
from hipaasynth.viz import demographics_distribution_svg, fairness_heatmap_svg


def test_module_disclaimer_constants_are_canonical():
    for module in (oud, chf, copd):
        assert module.DISCLAIMER == DEFAULT_SYNTHETIC_DISCLAIMER


def test_every_generator_stamps_the_canonical_disclaimer():
    records = []
    records.append(oud.generate_oud_cohort(seed=1, n=1)[0][0])
    records.append(chf.generate_chf_cohort(seed=1, n=1)[0][0])
    records.append(copd.generate_copd_cohort(seed=1, n=1)[0][0])
    records.append(DMDCohortGenerator(seed=1).generate(1)[0])
    records.append(FabryCohortGenerator(seed=1).generate(1)[0])
    records.append(SMACohortGenerator(seed=1).generate(1)[0])
    records.append(DiabetesPopulationGenerator(n=1, seed=1).generate()[0])
    records.append(generate_patients(GenerationConfig(patient_count=1, seed=1))[0].to_dict())

    for record in records:
        assert record["disclaimer"] == DEFAULT_SYNTHETIC_DISCLAIMER


# ── rendered surfaces: web UI + SVG (issue #92) ───────────────────────────────

_UI_INDEX = Path(__file__).resolve().parents[1] / "hipaasynth" / "ui" / "index.html"


def _visible_text(html: str) -> str:
    """Strip what the browser never renders: HTML comments, ``<style>``/``<script>``
    bodies, and the JS comments inside them.

    The point of stripping rather than grepping the raw file is that a disclosure
    living *only* in a source comment reads as present to `grep` and is invisible
    to the user it was written for. That was the actual state of the strongest
    wording here before this test existed, so the stripper is the assertion.

    Text the script *injects* into the page is kept: the fairness caveat is built
    as a JS string literal, and it genuinely reaches the screen. Quoted strings
    are pulled back in below, which is why JS line comments must go first.
    """
    html = re.sub(r"<!--.*?-->", " ", html, flags=re.DOTALL)
    scripts = re.findall(r"<script\b[^>]*>(.*?)</script>", html, flags=re.DOTALL)
    html = re.sub(r"<script\b[^>]*>.*?</script>", " ", html, flags=re.DOTALL)
    html = re.sub(r"<style\b[^>]*>.*?</style>", " ", html, flags=re.DOTALL)
    html = re.sub(r"<[^>]+>", " ", html)

    for script in scripts:
        # Order matters: kill comments before harvesting string literals, so a
        # commented-out disclosure never counts as rendered.
        body = re.sub(r"/\*.*?\*/", " ", script, flags=re.DOTALL)
        body = re.sub(r"//[^\n]*", " ", body)
        html += " " + " ".join(re.findall(r'"((?:[^"\\]|\\.)*)"', body))

    return re.sub(r"\s+", " ", html)


def test_web_ui_states_the_data_is_synthetic_where_a_user_can_see_it():
    text = _visible_text(_UI_INDEX.read_text(encoding="utf-8")).lower()
    assert "synthetic" in text
    assert "no phi" in text


def test_web_ui_labels_the_fairness_panel_as_a_mock_demonstration():
    """The heatmap is the highest-misinterpretation-risk element in the project:
    a "fairness heatmap" shown to a non-technical user reads as a real audit."""
    text = _visible_text(_UI_INDEX.read_text(encoding="utf-8")).lower()
    assert "mock" in text
    assert "demo" in text
    assert "not an audit of any real model" in text


def test_web_ui_fairness_caveat_is_not_hidden_in_a_source_comment():
    """Guards the guard. If someone moves the caveat into a ``//`` comment, the
    raw file still greps clean — this asserts the stripper would catch that."""
    commented = "<body><script>\n// this is not an audit of any real model\n</script></body>"
    assert "not an audit of any real model" not in _visible_text(commented).lower()


def _demo_passports(n=12, seed=5):
    cfg = GenerationConfig(patient_count=n, seed=seed, required_condition="stroke")
    dif_cfg = DIFConfig(device_name="Demo biased model", device_version="0.0.0")
    return run_audit(MockBiasedModel(), generate_patients, cfg, dif_cfg)


def test_demographics_svg_carries_the_synthetic_notice():
    patients = generate_patients(GenerationConfig(patient_count=15, seed=3))
    assert "synthetic — no PHI" in demographics_distribution_svg(patients)


def test_fairness_svg_carries_the_synthetic_notice():
    assert "synthetic — no PHI" in fairness_heatmap_svg(_demo_passports())


def test_fairness_svg_is_not_stamped_as_a_demo_unless_the_caller_says_so():
    """A real audit of a real device must not be labelled a demonstration, so the
    note is opt-in. This pins the default so the opt-in stays meaningful."""
    svg = fairness_heatmap_svg(_demo_passports())
    assert "mock" not in svg.lower()
    assert "demonstration" not in svg.lower()


def test_fairness_svg_note_is_rendered_as_visible_text():
    svg = fairness_heatmap_svg(_demo_passports(), note="Demonstration audit of a mock.")
    assert ">Demonstration audit of a mock.</text>" in svg


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


def test_viz_fairness_response_stamps_the_mock_model_caveat(server):
    """The served SVG gets saved, pasted into decks and mailed on. Once it is
    detached from the page that framed it, the image is the only thing carrying
    the caveat — so the caveat has to be inside the image."""
    from hipaasynth.api import VIZ_FAIRNESS_MOCK_NOTE

    url = f"{server}/viz/fairness?count=10&seed=1&model=biased"
    with urllib.request.urlopen(url, timeout=60) as resp:
        body = resp.read().decode("utf-8")

    assert VIZ_FAIRNESS_MOCK_NOTE in body
    assert "synthetic — no PHI" in body


def test_web_ui_is_served_with_its_disclaimers_intact(server):
    with urllib.request.urlopen(f"{server}/", timeout=30) as resp:
        body = resp.read().decode("utf-8")

    text = _visible_text(body).lower()
    assert "synthetic" in text and "no phi" in text
    assert "not an audit of any real model" in text
