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

"""Parquet export (roadmap step 5).

The engine core is pure-Python/standard-library; Parquet is an OPTIONAL feature
gated behind ``pip install hipaasynth[parquet]`` (pyarrow). These tests skip the
round-trip when pyarrow is absent, and always exercise the missing-dependency
error path via monkeypatch.
"""
import builtins

import pytest

from hipaasynth.core.config import GenerationConfig
from hipaasynth.exporters.exporters import export_csv, export_parquet
from hipaasynth.pipelines.population_pipeline import generate_patients


@pytest.fixture
def patients():
    return generate_patients(GenerationConfig(patient_count=6, seed=42))


def test_parquet_roundtrip_matches_csv_columns(patients, tmp_path):
    pa_parquet = pytest.importorskip("pyarrow.parquet")
    path = tmp_path / "out.parquet"
    export_parquet(patients, str(path))
    assert path.exists()
    table = pa_parquet.read_table(str(path))
    assert table.num_rows == len(patients)
    # Same schema as the CSV exporter (base fields present).
    cols = set(table.column_names)
    for expected in ("patient_id", "age", "sex", "ethnicity", "bmi", "conditions"):
        assert expected in cols


def test_parquet_values_match_csv(patients, tmp_path):
    pa_parquet = pytest.importorskip("pyarrow.parquet")
    import csv

    pq_path = tmp_path / "out.parquet"
    csv_path = tmp_path / "out.csv"
    export_parquet(patients, str(pq_path))
    export_csv(patients, str(csv_path))

    table = pa_parquet.read_table(str(pq_path)).to_pydict()
    with open(csv_path, newline="", encoding="utf-8") as f:
        csv_rows = list(csv.DictReader(f))

    # patient_id column agrees row-for-row between the two exporters.
    assert [str(v) for v in table["patient_id"]] == [r["patient_id"] for r in csv_rows]


def test_parquet_missing_dependency_is_graceful(patients, tmp_path, monkeypatch):
    """Without pyarrow, export_parquet raises a clear, actionable error."""
    real_import = builtins.__import__

    def _no_pyarrow(name, *args, **kwargs):
        if name.startswith("pyarrow"):
            raise ImportError("No module named 'pyarrow'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _no_pyarrow)
    with pytest.raises(RuntimeError) as exc:
        export_parquet(patients, str(tmp_path / "x.parquet"))
    msg = str(exc.value).lower()
    assert "pyarrow" in msg
    assert "parquet" in msg  # points at the optional extra
