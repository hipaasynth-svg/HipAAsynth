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

"""examples/rare_disease_demo.py must audit Fabry patients and expose the biased model.

Regression guard: the demo printed "Fabry disease patients" but generated
``required_condition="chronic_kidney_disease"``. CKD has no DIF ground truth,
so the built-in *biased* model passed 3/3 -- contradicting README.md
("fair passes 3/3, biased fails").
"""

import runpy
from pathlib import Path

_DEMO = Path(__file__).resolve().parent.parent / "examples" / "rare_disease_demo.py"


def test_demo_generates_fabry_and_biased_model_fails(capsys):
    runpy.run_path(str(_DEMO), run_name="__main__")
    out = capsys.readouterr().out
    fair, biased = out.split("--- Biased model")
    assert "Passports: 3/3 pass" in fair
    assert "Passports: 0/3 pass" in biased
    assert biased.count("-> FAIL") == 3


def test_demo_cohort_is_fabry():
    src = _DEMO.read_text()
    assert 'required_condition="fabry"' in src
    assert "chronic_kidney_disease" not in src
