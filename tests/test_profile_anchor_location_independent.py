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

"""A population profile must produce the same cohort wherever its file lives.

Regression guard: the generation anchor (the root of every patient seed) used
the profile's *file path* string. The same profile and seed therefore produced
a different cohort in every install location — a third party could not
reproduce a tribal or rural audit just by installing the package elsewhere.
"""

import json
import shutil
from pathlib import Path

import hipaasynth
from hipaasynth.core.config import GenerationConfig
from hipaasynth.pipelines.population_pipeline import generate_one_patient, generate_patients
from hipaasynth.sdk import generate

_BUNDLED = Path(hipaasynth.__file__).resolve().parent / "profiles" / "nd_tribal_region_a.json"


def _ids(path, n=5, seed=11):
    cfg = GenerationConfig(patient_count=n, seed=seed, population_profile_path=str(path),
                           run_date="2026-01-01")
    return [p.demographics.patient_id for p in generate_patients(cfg)]


def test_same_profile_in_different_directories_gives_same_cohort(tmp_path):
    a = tmp_path / "a" / "profile.json"
    b = tmp_path / "b" / "nested" / "other_name.json"
    for dst in (a, b):
        dst.parent.mkdir(parents=True)
        shutil.copy(_BUNDLED, dst)
    assert _ids(a) == _ids(b) == _ids(_BUNDLED)


def test_formatting_and_line_endings_do_not_matter(tmp_path):
    data = json.loads(_BUNDLED.read_text())
    crlf = tmp_path / "crlf.json"
    crlf.write_bytes(_BUNDLED.read_text().replace("\n", "\r\n").encode())
    compact = tmp_path / "compact.json"
    compact.write_text(json.dumps(data, separators=(",", ":")))
    assert _ids(crlf) == _ids(compact) == _ids(_BUNDLED)


def test_changing_profile_content_changes_the_cohort(tmp_path):
    data = json.loads(_BUNDLED.read_text())
    data["sex_ratio_female"] = 0.42
    edited = tmp_path / "edited.json"
    edited.write_text(json.dumps(data))
    assert _ids(edited) != _ids(_BUNDLED)


def test_bundled_name_and_explicit_path_agree():
    by_name = [p.demographics.patient_id for p in generate(count=5, seed=11, module="stroke",
                                                           profile="nd_tribal_region_a")]
    by_path = [p.demographics.patient_id for p in generate(count=5, seed=11, module="stroke",
                                                           profile=str(_BUNDLED))]
    assert by_name == by_path


def test_generate_one_patient_matches_batch(tmp_path):
    copy = tmp_path / "p.json"
    shutil.copy(_BUNDLED, copy)
    cfg = GenerationConfig(patient_count=4, seed=11, population_profile_path=str(copy),
                           run_date="2026-01-01")
    assert generate_one_patient(cfg, 3).demographics.patient_id == _ids(_BUNDLED, n=4)[3]


def test_no_profile_output_unchanged():
    # Golden IDs from main @ 7cfc3de: runs without a profile must not move.
    cfg = GenerationConfig(patient_count=3, seed=11, run_date="2026-01-01")
    assert [p.demographics.patient_id for p in generate_patients(cfg)] == [
        "SYN-39202a05", "SYN-04c7e0a4", "SYN-0849b4b7",
    ]
