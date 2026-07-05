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

"""Guardrails for the Seismometer demo notebook.

Pure stdlib (json only) so it runs in CI regardless of optional deps. Its job is
to make sure the synthetic-score disclaimer cannot be silently dropped from the
notebook in a future edit — a non-technical reader must always see, above any
plot, that ModelScore is a placeholder and the AUROC is not a performance result.
"""

import json
from pathlib import Path

NOTEBOOK = (
    Path(__file__).resolve().parent.parent
    / "examples"
    / "seismometer"
    / "hipaasynth_seismometer_demo.ipynb"
)


def _markdown_sources() -> list[str]:
    nb = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
    return ["".join(c["source"]) for c in nb["cells"] if c["cell_type"] == "markdown"]


def _cells() -> list[dict]:
    return json.loads(NOTEBOOK.read_text(encoding="utf-8"))["cells"]


def test_notebook_exists_and_is_valid_json():
    assert NOTEBOOK.is_file(), f"missing notebook: {NOTEBOOK}"
    nb = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
    assert nb.get("cells"), "notebook has no cells"


def test_disclaimer_cell_present_with_required_points():
    """The disclaimer markdown cell must exist and carry all three required points."""
    md = "\n".join(_markdown_sources()).lower()
    assert "synthetic placeholder" in md, "disclaimer must state ModelScore is a synthetic placeholder"
    assert "no model score" in md, "disclaimer must state HipAAsynth emits no model score"
    assert "not a performance result" in md, "disclaimer must state AUROC/AUPRC is not a performance result"
    assert "censor_min_count" in md, "disclaimer must frame the demo around the censoring/fairness pipeline"


def test_disclaimer_appears_before_any_code():
    """A literal reader must hit the disclaimer above the first code cell."""
    cells = _cells()
    first_code = next(i for i, c in enumerate(cells) if c["cell_type"] == "code")
    disclaimer_idx = next(
        i
        for i, c in enumerate(cells)
        if c["cell_type"] == "markdown" and "synthetic placeholder" in "".join(c["source"]).lower()
    )
    assert disclaimer_idx < first_code, "disclaimer must come before the first code cell"


def test_no_epic_endorsement_language():
    """We demonstrate compatibility with Epic's open-source tool, not a relationship."""
    md = "\n".join(_markdown_sources()).lower()
    # Affirmative endorsement phrases only — the disclaimer legitimately *negates*
    # a relationship ("not a partnership or endorsement"), so we don't ban bare words.
    for banned in ("endorsed by epic", "in partnership with", "official epic", "epic partner"):
        assert banned not in md, f"notebook must not imply an Epic relationship: found '{banned}'"
