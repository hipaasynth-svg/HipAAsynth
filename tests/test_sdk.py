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

"""SDK facade (Tier 2 step 3)."""
import csv
import io
import json

import pytest

import hipaasynth
from hipaasynth.sdk import Cohort, MODULES, available_profiles, generate


def test_generate_returns_cohort_of_requested_size():
    cohort = generate(count=5, seed=42)
    assert isinstance(cohort, Cohort)
    assert len(cohort) == 5
    assert len(list(cohort)) == 5           # iterable
    assert cohort[0] is cohort.patients[0]  # indexable


def test_top_level_reexport():
    """`import hipaasynth; hipaasynth.generate(...)` is the notebook one-liner."""
    assert hipaasynth.generate is generate
    assert hipaasynth.Cohort is Cohort
    cohort = hipaasynth.generate(count=2, seed=1)
    assert len(cohort) == 2


def test_generation_is_deterministic():
    a = generate(count=4, seed=99).to_json()
    b = generate(count=4, seed=99).to_json()
    assert a == b


def test_module_selection_valid_and_invalid():
    assert set(MODULES) == {"sepsis", "stroke", "dka", "fabry"}
    assert len(generate(count=3, module="fabry")) == 3
    with pytest.raises(ValueError):
        generate(count=3, module="not-a-module")


def test_to_json_returns_string_and_writes_file(tmp_path):
    cohort = generate(count=3, seed=7)
    text = cohort.to_json()
    assert isinstance(text, str)
    assert len(json.loads(text)) == 3
    path = cohort.to_json(tmp_path / "cohort.json")
    assert path.exists()
    assert len(json.loads(path.read_text())) == 3


def test_to_csv_returns_string_and_writes_file(tmp_path):
    cohort = generate(count=3, seed=7)
    text = cohort.to_csv()
    rows = list(csv.DictReader(io.StringIO(text)))
    assert len(rows) == 3 and "patient_id" in rows[0]
    path = cohort.to_csv(tmp_path / "cohort.csv")
    assert path.exists()


def test_to_fhir_bundle_returns_dict_and_validates(tmp_path):
    cohort = generate(count=4, seed=3)
    bundle = cohort.to_fhir_bundle()
    assert bundle["resourceType"] == "Bundle" and bundle["entry"]
    path = cohort.to_fhir_bundle(tmp_path / "b.json")
    assert path.exists()
    # The structural validator agrees the generated bundle is clean.
    report = cohort.validate()
    assert report.ok, report.errors


def test_to_ndjson_writes_dir(tmp_path):
    out = generate(count=3, seed=2).to_ndjson(tmp_path / "ndjson")
    assert out.is_dir()
    assert list(out.glob("*.ndjson"))


def test_to_omop_returns_tables_and_writes(tmp_path):
    cohort = generate(count=3, seed=2)
    tables = cohort.to_omop()
    assert "person" in tables and len(tables["person"]) == 3
    out = cohort.to_omop(tmp_path / "omop")
    assert (out / "person.csv").exists()


def test_summary():
    stats = generate(count=6, seed=5).summary()
    assert stats["count"] == 6
    assert "sex_counts" in stats


def test_profile_by_bundled_name():
    profiles = available_profiles()
    assert profiles  # the package ships profiles
    cohort = generate(count=3, profile=profiles[0])
    assert len(cohort) == 3
    assert cohort.config.profile_name is not None


def test_unknown_profile_raises():
    with pytest.raises(ValueError):
        generate(count=3, profile="definitely-not-a-profile")


def test_to_parquet_writes_file(tmp_path):
    pytest.importorskip("pyarrow")
    path = generate(count=3, seed=1).to_parquet(tmp_path / "c.parquet")
    assert path.exists() and path.read_bytes()[:4] == b"PAR1"


def test_api_uses_sdk_module_map():
    """The REST API and SDK share one module map (no drift)."""
    from hipaasynth.api import MODULE_TO_CONDITION
    assert MODULE_TO_CONDITION is MODULES


def test_quickstart_example_runs():
    """The notebook-style example executes end-to-end (generate→export→validate)."""
    import runpy
    from pathlib import Path

    example = Path(__file__).resolve().parent.parent / "examples" / "sdk_quickstart.py"
    assert example.exists()
    # runpy executes it as __main__; it writes only to a system temp dir.
    runpy.run_path(str(example), run_name="__main__")
