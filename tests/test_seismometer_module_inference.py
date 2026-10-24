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

"""Seismometer adapter module inference must match whole label tokens.

Regression guard: ``_infer_module`` did a first-hit substring match over the
PROFILES keys, so "cloud_export" was read as OUD, "plasma_study" as SMA, and a
label naming two modules resolved to whichever key came first.
"""

import sys
from pathlib import Path

import pytest

pandas = pytest.importorskip("pandas")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "examples" / "seismometer"))

from seismometer_adapter import PROFILES, _infer_module  # noqa: E402


def _infer(label, col="cohort_label"):
    return _infer_module(pandas.DataFrame({col: [label]}))


@pytest.mark.parametrize("label, expected", [
    ("us_oud_calibration", "oud"),
    ("us_copd_hf_public", "copd"),
    ("us_chf_calibration", "chf"),
    ("us_sma_calibration", "sma"),
    ("COPD", "copd"),
    ("fabry", "fabry"),
])
def test_real_labels_resolve(label, expected):
    assert _infer(label) == expected


@pytest.mark.parametrize("label", ["cloud_export", "plasma_study", "loud_noise", "chfx", ""])
def test_substrings_do_not_match(label):
    assert _infer(label) is None


def test_label_naming_two_modules_is_ambiguous():
    assert _infer("stroke_sepsis_overlap") is None


def test_module_column_is_checked_first():
    df = pandas.DataFrame({"module": ["dmd"], "cohort_label": ["us_oud_calibration"]})
    assert _infer_module(df) == "dmd"


@pytest.mark.parametrize("module", sorted(PROFILES))
def test_every_profile_key_resolves_from_its_default_label(module):
    assert _infer(f"us_{module}_calibration") == module
