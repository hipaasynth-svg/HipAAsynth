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

"""BigQuery connector (Tier 3 step 2) — generated SQL/DDL text only.

No live BigQuery account exists in this environment, so these tests assert on the
*generated text* (DDL, LOAD DATA, bq CLI, load-schema JSON). They do NOT connect to
BigQuery. Stdlib-only; no google-cloud-bigquery import.
"""
import pytest

from hipaasynth.connectors import bigquery as bq
from hipaasynth.connectors.omop_schema import OMOP_TABLES, table_columns


def test_table_ddl_qualified_name_and_types():
    ddl = bq.table_ddl("person", dataset="omop", project="my-proj")
    assert ddl.startswith("CREATE TABLE `my-proj.omop.person` (")
    # BigQuery scalar types, correctly mapped from the OMOP columns.
    assert "person_id INT64" in ddl
    assert "gender_concept_id INT64" in ddl
    assert "year_of_birth INT64" in ddl
    assert "person_source_value STRING" in ddl
    assert "birth_datetime DATETIME" in ddl


def test_table_ddl_dates_and_floats():
    cond = bq.table_ddl("condition_occurrence", dataset="omop")
    assert "condition_start_date DATE" in cond
    assert "condition_start_datetime DATETIME" in cond
    meas = bq.table_ddl("measurement", dataset="omop")
    assert "value_as_number FLOAT64" in meas
    assert "range_low FLOAT64" in meas


def test_table_ddl_without_project_omits_project():
    ddl = bq.table_ddl("person", dataset="omop")
    assert "`omop.person`" in ddl
    assert "my-proj" not in ddl


def test_if_not_exists_flag():
    ddl = bq.table_ddl("person", dataset="omop", if_not_exists=True)
    assert "CREATE TABLE IF NOT EXISTS `omop.person`" in ddl


def test_schema_ddl_covers_all_omop_tables():
    ddl = bq.schema_ddl(dataset="omop", project="p")
    for table in OMOP_TABLES:
        assert f"`p.omop.{table}`" in ddl
    # One CREATE TABLE per OMOP table, semicolon-terminated.
    assert ddl.count("CREATE TABLE ") == len(OMOP_TABLES)
    assert ddl.rstrip().endswith(";")


def test_table_schema_json_matches_columns():
    schema = bq.table_schema_json("drug_exposure")
    assert [f["name"] for f in schema] == table_columns("drug_exposure")
    assert all(set(f) == {"name", "type", "mode"} for f in schema)
    assert all(f["mode"] == "NULLABLE" for f in schema)
    # Spot-check a couple of types.
    by_name = {f["name"]: f["type"] for f in schema}
    assert by_name["drug_exposure_id"] == "INT64"
    assert by_name["quantity"] == "FLOAT64"
    assert by_name["drug_source_value"] == "STRING"


def test_load_data_sql_append_and_overwrite():
    into = bq.load_data_sql("person", "gs://bkt/person.csv", dataset="omop", project="p")
    assert into.startswith("LOAD DATA INTO `p.omop.person`")
    assert "format = 'CSV'" in into
    assert "uris = ['gs://bkt/person.csv']" in into
    assert "skip_leading_rows = 1" in into

    over = bq.load_data_sql("person", "gs://bkt/person.csv", dataset="omop",
                            overwrite=True)
    assert over.startswith("LOAD DATA OVERWRITE `omop.person`")


def test_load_data_sql_multiple_uris():
    sql = bq.load_data_sql("measurement", ["gs://b/m1.csv", "gs://b/m2.csv"],
                           dataset="omop")
    assert "uris = ['gs://b/m1.csv', 'gs://b/m2.csv']" in sql


def test_bq_load_command():
    cmd = bq.bq_load_command("person", "gs://bkt/person.csv", dataset="omop",
                             project="my-proj", replace=True)
    assert cmd == (
        "bq load --source_format=CSV --skip_leading_rows=1 --replace "
        "my-proj:omop.person gs://bkt/person.csv"
    )


def test_load_all_sql_maps_every_table_to_matching_csv():
    stmts = bq.load_all_sql(dataset="omop", gcs_prefix="gs://bkt/cohort/", project="p")
    assert set(stmts) == set(OMOP_TABLES)
    assert "uris = ['gs://bkt/cohort/person.csv']" in stmts["person"]
    assert "`p.omop.condition_occurrence`" in stmts["condition_occurrence"]


def test_unknown_table_raises():
    with pytest.raises(ValueError):
        bq.table_ddl("not_a_table", dataset="omop")


def test_identifier_injection_is_rejected():
    """A dataset/table id can't smuggle a backtick or SQL into the generated text."""
    with pytest.raises(ValueError):
        bq.qualified_name("person", dataset="omop`; DROP TABLE x; --")
    with pytest.raises(ValueError):
        bq.table_ddl("person; DROP TABLE x", dataset="omop")


def test_schema_json_column_set_matches_duckdb_schema_source():
    """Both connectors derive columns from the same omop_schema source (no drift)."""
    for table in OMOP_TABLES:
        assert [f["name"] for f in bq.table_schema_json(table)] == table_columns(table)
