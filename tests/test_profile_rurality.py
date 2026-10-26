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

"""Rural profiles must produce rural patients.

Regression guard: the sepsis, stroke, fabry and DKA observation hooks decided
rurality by looking for the word "rural" in ``profile_name``. No bundled
profile is named that way, so the tribal and Minot profiles — which carry
``"rural": true`` — produced 0% rural patients, fewer than a run with no
profile at all (~17%).
"""

import json
import statistics
from pathlib import Path

import pytest

import hipaasynth
from hipaasynth.core.profile_loader import profile_rurality
from hipaasynth.sdk import available_profiles, generate

_PROFILES_DIR = Path(hipaasynth.__file__).resolve().parent / "profiles"


def _flag(profile_name):
    return json.loads((_PROFILES_DIR / f"{profile_name}.json").read_text()).get("rural")


RURAL = [p for p in available_profiles() if _flag(p) is True]
NOT_RURAL = [p for p in available_profiles() if _flag(p) is not True]


def test_bundled_profiles_include_rural_ones():
    assert {"nd_tribal_region_a", "nd_tribal_region_b", "minot_nd"} <= set(RURAL)


@pytest.mark.parametrize(
    "profile, expected",
    [
        (None, None),
        ({}, None),
        ({"profile_name": "x", "rural": True}, True),
        ({"profile_name": "rural_county", "rural": False}, False),  # flag wins over name
        ({"profile_name": "rural_county"}, True),  # legacy name fallback
        ({"profile_name": "urban_county"}, False),
        ({"profile_name": "x", "rural": "yes"}, False),  # non-bool flag ignored
        ({"age_bands": []}, None),  # no flag, no name: module keeps its own fallback
    ],
)
def test_profile_rurality(profile, expected):
    assert profile_rurality(profile) is expected


@pytest.mark.parametrize("module", ["stroke", "dka", "fabry"])
@pytest.mark.parametrize("profile", RURAL)
def test_rural_profiles_yield_rural_patients(module, profile):
    cohort = generate(count=30, seed=7, module=module, profile=profile)
    flags = [(p.observations or {}).get("rural_presentation") for p in cohort]
    assert all(f is True for f in flags), f"{module}/{profile}: {flags.count(True)}/30 rural"


@pytest.mark.parametrize("module", ["stroke", "dka", "fabry"])
@pytest.mark.parametrize("profile", NOT_RURAL)
def test_non_rural_profiles_yield_no_rural_patients(module, profile):
    cohort = generate(count=30, seed=7, module=module, profile=profile)
    assert not any((p.observations or {}).get("rural_presentation") for p in cohort)


def test_rural_stroke_profiles_carry_the_late_presenter_tail():
    def p90(profile):
        cohort = generate(count=300, seed=7, module="stroke", profile=profile)
        times = sorted(p.observations["onset_to_door_minutes"] for p in cohort)
        return times[int(0.9 * len(times))]

    assert p90("nd_tribal_region_a") > 270  # documented rural tail: >270 min
    assert p90("us_default") <= 300  # documented non-rural ceiling
    assert statistics.median(
        [p.observations["onset_to_door_minutes"]
         for p in generate(count=300, seed=7, module="stroke", profile="nd_tribal_region_a")]
    ) >= statistics.median(
        [p.observations["onset_to_door_minutes"]
         for p in generate(count=300, seed=7, module="stroke", profile="us_default")]
    )
