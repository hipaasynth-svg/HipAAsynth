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

"""CLI surface (Tier 2 step 1).

Covers the console-script entry point, the additive ``--format`` /``--validate``
flags, and — critically — that the pre-Tier-2 default behavior is unchanged.
"""
import tomllib
from pathlib import Path

import pytest

from hipaasynth.run.main import FORMATS, build_parser, main

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_entry_point_registered_in_pyproject():
    """`pip install -e .` must expose a real `hipaasynth` console command."""
    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    scripts = data.get("project", {}).get("scripts", {})
    assert scripts.get("hipaasynth") == "hipaasynth.run.main:main"


def test_legacy_default_flags_still_parse():
    """Every pre-Tier-2 flag still parses to the same attributes."""
    args = build_parser().parse_args(
        ["--demo", "--count", "5", "--seed", "7", "--out", "o", "--profile", "p.json"]
    )
    assert args.demo and args.count == 5 and args.seed == 7
    assert args.out == "o" and args.profile == "p.json"
    # New flags default to the legacy behavior.
    assert args.format is None and args.validate is False


def test_default_run_writes_legacy_triple(tmp_path):
    """No --format => the same JSON + CSV + FHIR-bundle filenames as before."""
    rc = main(["--count", "3", "--seed", "42", "--out", str(tmp_path)])
    assert rc == 0
    assert (tmp_path / "cohort.json").exists()
    assert (tmp_path / "cohort.csv").exists()
    assert (tmp_path / "cohort_fhir.json").exists()
    # And nothing extra from the new formats.
    assert not (tmp_path / "cohort_fhir_ndjson").exists()
    assert not (tmp_path / "omop_cdm").exists()


def test_format_ndjson_writes_bulk_dir(tmp_path):
    rc = main(["--count", "3", "--out", str(tmp_path), "--format", "ndjson"])
    assert rc == 0
    ndjson_dir = tmp_path / "cohort_fhir_ndjson"
    assert ndjson_dir.is_dir()
    assert list(ndjson_dir.glob("*.ndjson"))
    # Only ndjson was requested — the legacy triple must NOT be written.
    assert not (tmp_path / "cohort.json").exists()


def test_format_omop_writes_cdm_dir(tmp_path):
    rc = main(["--count", "3", "--out", str(tmp_path), "--format", "omop"])
    assert rc == 0
    omop_dir = tmp_path / "omop_cdm"
    assert omop_dir.is_dir()
    assert (omop_dir / "person.csv").exists()


def test_multiple_formats(tmp_path):
    rc = main(["--count", "3", "--out", str(tmp_path), "--format", "json", "csv"])
    assert rc == 0
    assert (tmp_path / "cohort.json").exists()
    assert (tmp_path / "cohort.csv").exists()
    assert not (tmp_path / "cohort_fhir.json").exists()


def test_validate_passes_on_clean_cohort(tmp_path, capsys):
    rc = main(["--count", "3", "--out", str(tmp_path),
               "--format", "fhir-bundle", "--validate"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "FHIR validation" in out and "PASS" in out


def test_validate_without_fhir_format_uses_in_memory(tmp_path, capsys):
    """--validate is meaningful even when no FHIR format is written."""
    rc = main(["--count", "3", "--out", str(tmp_path),
               "--format", "csv", "--validate"])
    assert rc == 0
    assert "in-memory FHIR resources" in capsys.readouterr().out


def test_bad_format_is_rejected(tmp_path):
    with pytest.raises(SystemExit):
        main(["--out", str(tmp_path), "--format", "xml"])


def test_parquet_format(tmp_path):
    pytest.importorskip("pyarrow")
    rc = main(["--count", "3", "--out", str(tmp_path), "--format", "parquet"])
    assert rc == 0
    assert (tmp_path / "cohort.parquet").exists()


def test_all_formats_constant_matches_choices():
    """FORMATS drives the argparse choices — guard against drift."""
    action = next(a for a in build_parser()._actions if a.dest == "format")
    assert tuple(action.choices) == FORMATS
