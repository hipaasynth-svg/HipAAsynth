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

"""Guards that the engine version cannot silently drift from the release version.

``ENGINE_VERSION`` is not a display string. ``dif/framework.py`` stamps it into
every :class:`~hipaasynth.dif.report.FairnessPassport`, and the passport's
verification seal is what lets a third party confirm which engine produced a
given result (audit finding F2).

That guarantee only holds while the recorded version actually distinguishes one
build from another. Between releases 1.3.0 and 1.4.0 the engine gained a REST
API, a CLI entry point, an SDK, warehouse connectors, a validation suite, and a
web UI while ``ENGINE_VERSION`` stayed at ``"1.3.0"`` — so passports from either
side of that work are indistinguishable by the field meant to distinguish them.

``ENGINE_VERSION`` and ``pyproject.toml``'s ``version`` are separate string
literals with no import relationship, so nothing but this test stops them from
diverging again.
"""

import re
import tomllib
from pathlib import Path

from hipaasynth.core.config import ENGINE_VERSION

_PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"
_CHANGELOG = Path(__file__).resolve().parent.parent / "CHANGELOG.md"

# Keep a Changelog heading, e.g. "## [1.4.0] — 2026-07-30".
_RELEASE_HEADING = re.compile(r"^## \[(?P<version>[0-9]+\.[0-9]+\.[0-9]+)\]", re.MULTILINE)


def _pyproject_version() -> str:
    with _PYPROJECT.open("rb") as handle:
        return tomllib.load(handle)["project"]["version"]


def test_engine_version_matches_pyproject_version():
    """The sealed engine version must equal the distributed release version."""
    assert ENGINE_VERSION == _pyproject_version(), (
        f"ENGINE_VERSION ({ENGINE_VERSION}) != pyproject version "
        f"({_pyproject_version()}). ENGINE_VERSION is sealed into every "
        "FairnessPassport; bump both together so a passport identifies its engine."
    )


def test_changelog_documents_the_current_version():
    """The current version needs a CHANGELOG entry before it can be released.

    Catches the other half of the same mistake: bumping the version but shipping
    without telling anyone what changed.
    """
    versions = _RELEASE_HEADING.findall(_CHANGELOG.read_text(encoding="utf-8"))
    assert ENGINE_VERSION in versions, (
        f"No '## [{ENGINE_VERSION}]' section in CHANGELOG.md. "
        f"Documented versions: {versions[:5]}"
    )


def test_changelog_newest_entry_is_the_current_version():
    """The newest CHANGELOG entry should be the version we are shipping."""
    versions = _RELEASE_HEADING.findall(_CHANGELOG.read_text(encoding="utf-8"))
    assert versions, "CHANGELOG.md has no release headings"
    assert versions[0] == ENGINE_VERSION, (
        f"Newest CHANGELOG entry is {versions[0]} but ENGINE_VERSION is "
        f"{ENGINE_VERSION}. Add the new section above the previous release."
    )
