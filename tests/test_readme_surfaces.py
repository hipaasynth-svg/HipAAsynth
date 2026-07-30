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

"""The README describes surfaces that actually exist (issue #89).

Tier 2-5 shipped the CLI, SDK, REST API, web UI, DuckDB connector and the
scenario blueprints, and the README mentioned **none** of them — all of it was
logged in `docs/ROADMAP_CHANGELOG.md`, an internal build log, instead. Docs drift
silently: nothing fails when a README goes stale, which is how it got that far
behind in the first place.

These tests tie the claims to the code. They deliberately check *existence and
agreement*, not prose, so the README stays editable without fighting the suite.
"""

import re
from pathlib import Path

import pytest

from hipaasynth.api import API_FORMATS
from hipaasynth.scenarios import available_scenarios, scenario_summaries
from hipaasynth.sdk import MODULES

README = Path(__file__).resolve().parents[1] / "README.md"


@pytest.fixture(scope="module")
def readme() -> str:
    return README.read_text(encoding="utf-8")


# ── the surfaces exist ───────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "surface",
    [
        "python -m hipaasynth.api",  # web UI + REST API
        "hipaasynth --scenario",  # CLI
        "hipaasynth.generate(",  # SDK
        "docker compose up",  # Docker
        "hipaasynth.connectors import duckdb",  # DuckDB connector
    ],
)
def test_readme_documents_each_shipped_surface(readme, surface):
    assert surface in readme, f"README no longer documents: {surface}"


def test_readme_documents_every_sdk_module(readme):
    for module in MODULES:
        assert module in readme, f"module {module!r} is undocumented"


def test_readme_documents_every_api_format(readme):
    for fmt in API_FORMATS:
        assert fmt in readme, f"format {fmt!r} is undocumented"


# ── the scenario table matches the engine ────────────────────────────────────


def test_readme_lists_every_scenario_blueprint(readme):
    for name in available_scenarios():
        assert name in readme, f"scenario {name!r} is missing from the README"


def _scenario_rows(readme: str) -> dict:
    """Parse the scenario table into {name: [cells]}.

    Cells, not substrings: a naive ``module in row`` check passes spuriously
    because `tribal_stroke`'s description contains the word "stroke", so a row
    claiming the wrong module would sail through.
    """
    rows = {}
    for line in readme.splitlines():
        match = re.match(r"^\| `([a-z0-9_]+)` \|(.*)\|\s*$", line)
        if match:
            rows[match.group(1)] = [c.strip() for c in match.group(2).split("|")]
    return rows


def test_readme_scenario_table_names_the_right_module_and_profile(readme):
    """Guards against the table going stale in the subtler way: right scenario
    names, wrong module/profile pairing."""
    rows = _scenario_rows(readme)
    for summary in scenario_summaries():
        cells = rows.get(summary["name"])
        assert cells, f"no README table row for scenario {summary['name']!r}"
        assert cells[0] == summary["module"], (
            f"{summary['name']}: README says module {cells[0]!r}, "
            f"engine says {summary['module']!r}"
        )
        assert cells[1] == summary["profile"], (
            f"{summary['name']}: README says profile {cells[1]!r}, "
            f"engine says {summary['profile']!r}"
        )


def test_readme_does_not_invent_scenarios(readme):
    """A row for a scenario the engine does not ship is worse than no row."""
    known = set(available_scenarios())
    documented = set(
        re.findall(r"`((?:us|tribal|rural|urban|karachi|lagos|fabry)_[a-z_]+)`", readme)
    )
    assert documented <= known, f"README documents non-existent scenarios: {documented - known}"


# ── the extras table matches pyproject ───────────────────────────────────────


def test_readme_documents_every_declared_extra(readme):
    import tomllib

    pyproject = README.parent / "pyproject.toml"
    with pyproject.open("rb") as fh:
        extras = tomllib.load(fh)["project"]["optional-dependencies"]

    for extra in extras:
        assert f".[{extra}]" in readme, f"extra {extra!r} is declared but undocumented"


# ── honesty about the mock-model demo ────────────────────────────────────────


def test_readme_states_the_fairness_heatmap_is_a_mock_demonstration(readme):
    """The disclosure exists in the UI and in api.py. Issue #89 asked for it to
    exist in the docs too, so someone evaluating the project from the README
    alone cannot mistake the heatmap for a real audit."""
    lowered = readme.lower()
    assert "mock" in lowered
    assert (
        "not** an audit of any real model" in lowered or "not an audit of any real model" in lowered
    )


def test_readme_does_not_claim_a_pypi_install(readme):
    """There is no PyPI publish step in .github/workflows/release.yml, so
    `pip install hipaasynth` would send a reader to a package that isn't there.
    If the project is published later, delete this test in the same PR."""
    assert not re.search(r"pip install\s+hipaasynth(?![\w/.-])", readme)
