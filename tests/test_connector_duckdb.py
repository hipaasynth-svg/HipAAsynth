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

"""DuckDB connector (Tier 3 step 1) — real integration against a local .duckdb file.

The whole module skips if the optional ``duckdb`` extra is absent (e.g. on CI,
which installs only ``[dev]``). Where it runs, it loads into and queries a **real**
DuckDB database — not a mock.
"""
import sys

import pytest

duckdb = pytest.importorskip("duckdb")

from hipaasynth import generate
from hipaasynth.connectors import duckdb as dc
from hipaasynth.exporters.omop import build_cdm_tables


@pytest.fixture
def cohort():
    return generate(count=20, seed=42, module="stroke")


def test_load_omop_returns_rowcounts_matching_exporter(cohort, tmp_path):
    """The connector's summary must match build_cdm_tables row counts exactly."""
    db = tmp_path / "cohort.duckdb"
    summary = dc.load(cohort, db)
    expected = {t: len(rows) for t, rows in build_cdm_tables(cohort.patients).items()}
    assert summary == expected
    assert summary["person"] == 20


def test_data_is_queryable_in_real_db_file(cohort, tmp_path):
    db = tmp_path / "cohort.duckdb"
    dc.load(cohort, db)
    con = duckdb.connect(str(db))
    try:
        assert con.execute("SELECT COUNT(*) FROM person").fetchone()[0] == 20
        # A real join across CDM tables works.
        joined = con.execute(
            "SELECT COUNT(*) FROM condition_occurrence c "
            "JOIN person p USING(person_id)"
        ).fetchone()[0]
        assert joined == len(build_cdm_tables(cohort.patients)["condition_occurrence"])
    finally:
        con.close()


def test_columns_are_typed_not_all_varchar(cohort, tmp_path):
    db = tmp_path / "cohort.duckdb"
    dc.load(cohort, db)
    con = duckdb.connect(str(db))
    try:
        def dtype(table, col):
            return con.execute(
                "SELECT data_type FROM information_schema.columns "
                "WHERE table_name=? AND column_name=?", [table, col]
            ).fetchone()[0]

        assert dtype("person", "person_id") == "BIGINT"
        assert dtype("person", "gender_concept_id") == "BIGINT"
        assert dtype("condition_occurrence", "condition_start_date") == "DATE"
        assert dtype("measurement", "value_as_number") == "DOUBLE"
        assert dtype("person", "person_source_value") == "VARCHAR"
    finally:
        con.close()


def test_empty_omop_values_become_null(cohort, tmp_path):
    """OMOP CSV uses '' for null; the DB must store real NULLs, not empty strings."""
    db = tmp_path / "cohort.duckdb"
    dc.load(cohort, db)
    con = duckdb.connect(str(db))
    try:
        # birth_datetime is always '' in the exporter -> must be NULL in the DB.
        nulls = con.execute(
            "SELECT COUNT(*) FROM person WHERE birth_datetime IS NULL"
        ).fetchone()[0]
        assert nulls == 20
    finally:
        con.close()


def test_condition_status_concept_id_loaded_as_int(cohort, tmp_path):
    """Regression tie-in: the Tier-2 condition_status fix survives into the warehouse."""
    db = tmp_path / "cohort.duckdb"
    dc.load(cohort, db)
    con = duckdb.connect(str(db))
    try:
        vals = con.execute(
            "SELECT DISTINCT condition_status_concept_id FROM condition_occurrence "
            "WHERE condition_status_concept_id IS NOT NULL"
        ).fetchall()
        assert vals  # non-empty
        assert all(isinstance(v[0], int) and v[0] != 0 for v in vals)
    finally:
        con.close()


def test_flat_mode_loads_single_typed_table(cohort, tmp_path):
    db = tmp_path / "flat.duckdb"
    summary = dc.load(cohort, db, mode="flat")
    assert summary == {"patient": 20}
    con = duckdb.connect(str(db))
    try:
        assert con.execute("SELECT COUNT(*) FROM patient").fetchone()[0] == 20
        dt = con.execute(
            "SELECT data_type FROM information_schema.columns "
            "WHERE table_name='patient' AND column_name='bmi'"
        ).fetchone()[0]
        assert dt == "DOUBLE"
    finally:
        con.close()


def test_if_exists_replace_vs_append(cohort, tmp_path):
    db = tmp_path / "cohort.duckdb"
    dc.load(cohort, db)                       # replace (default)
    dc.load(cohort, db, if_exists="append")   # append same cohort
    con = duckdb.connect(str(db))
    try:
        assert con.execute("SELECT COUNT(*) FROM person").fetchone()[0] == 40
    finally:
        con.close()
    dc.load(cohort, db)                        # replace again -> back to 20
    con = duckdb.connect(str(db))
    try:
        assert con.execute("SELECT COUNT(*) FROM person").fetchone()[0] == 20
    finally:
        con.close()


def test_load_accepts_plain_patient_list(cohort, tmp_path):
    db = tmp_path / "cohort.duckdb"
    summary = dc.load(list(cohort.patients), db)  # not a Cohort, a list
    assert summary["person"] == 20


def test_invalid_mode_raises(cohort, tmp_path):
    with pytest.raises(ValueError):
        dc.load(cohort, tmp_path / "x.duckdb", mode="nonsense")


def test_missing_duckdb_dependency_raises_runtimeerror(cohort, tmp_path, monkeypatch):
    """When the optional 'duckdb' extra is absent, load() gives a clear RuntimeError."""
    monkeypatch.setitem(sys.modules, "duckdb", None)  # force `import duckdb` to fail
    with pytest.raises(RuntimeError, match="pip install 'hipaasynth\\[duckdb\\]'"):
        dc.load(cohort, tmp_path / "x.duckdb")


def test_create_table_ddl_text():
    ddl = dc.create_table_ddl("person", "duckdb")
    assert ddl.startswith('CREATE TABLE "person" (')
    assert '"person_id" BIGINT' in ddl
    assert '"person_source_value" VARCHAR' in ddl
