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

"""Guard rails for the population-profile loader (issue #26).

Profiles are small, trusted, hand-authored JSON. The loader rejects a
pathologically large input before parsing it into memory. These tests confirm
the guard fires on an oversized file and — crucially — that it does not reject
any real bundled profile.
"""

import os

import pytest

import hipaasynth
from hipaasynth.core.profile_loader import (
    MAX_PROFILE_BYTES,
    ProfileError,
    load_population_profile,
)

PROFILES_DIR = os.path.join(os.path.dirname(hipaasynth.__file__), "profiles")


def _bundled_profiles():
    return [
        os.path.join(PROFILES_DIR, f)
        for f in os.listdir(PROFILES_DIR)
        if f.endswith(".json")
    ]


def test_bundled_profiles_load_and_are_well_under_limit():
    """Regression: the size guard must not reject any real profile."""
    profiles = _bundled_profiles()
    assert profiles, "no bundled profiles found"
    for path in profiles:
        assert os.path.getsize(path) < MAX_PROFILE_BYTES
        result = load_population_profile(path)  # must not raise
        assert isinstance(result, dict)


def test_oversized_profile_is_rejected_before_parsing(tmp_path):
    huge = tmp_path / "huge_profile.json"
    # Valid JSON, but larger than the limit — must be rejected on size alone.
    huge.write_text('{"_pad": "' + "x" * (MAX_PROFILE_BYTES + 1024) + '"}', encoding="utf-8")
    with pytest.raises(ProfileError, match="too large"):
        load_population_profile(str(huge))


def test_small_valid_profile_still_loads(tmp_path):
    small = tmp_path / "tiny.json"
    small.write_text('{"sex_ratio_female": 0.5}', encoding="utf-8")
    result = load_population_profile(str(small))
    assert result["sex_ratio_female"] == 0.5
