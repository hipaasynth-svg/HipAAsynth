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

"""BigQuery connector — schema (DDL) and load-statement *text* generation.

This is the **schema/query-level** connector: it builds the SQL and load-command
text you would run against BigQuery, from the OMOP CDM 5.4 column sets shared in
:mod:`hipaasynth.connectors.omop_schema`. It is **pure standard library** — it does
**not** import `google-cloud-bigquery` and does **not** open any network
connection, so it adds no dependency and can be tested by asserting on the
generated text.

⚠️ **No live BigQuery was contacted.** There is no BigQuery account in this
project's test environment, so only the generated DDL / load SQL / `bq` CLI text is
verified (string assertions). Running these against a real dataset — and any
client-based loader — is intentionally out of scope here (a client loader is
deferred until it can be tested against a real account).

Why BigQuery (vs. Snowflake/Redshift/Databricks): it has the most widely
documented, stable GoogleSQL DDL + `LOAD DATA ... FROM FILES` DML + `bq load` CLI +
JSON load-schema, all of which are honestly generatable and assertable offline.

Typical use::

    from hipaasynth.connectors import bigquery as bq

    print(bq.schema_ddl(dataset="omop", project="my-proj"))          # CREATE TABLEs
    print(bq.load_data_sql("person", "gs://bkt/person.csv",
                           dataset="omop", project="my-proj"))       # LOAD DATA
    print(bq.bq_load_command("person", "gs://bkt/person.csv",
                             dataset="omop", project="my-proj"))     # bq CLI
"""
from __future__ import annotations

import re

from hipaasynth.connectors.omop_schema import (
    OMOP_TABLES,
    sql_type,
    table_columns,
)

_DIALECT = "bigquery"
# BigQuery dataset/table ids: letters, numbers, underscores. Project ids also
# allow hyphens. We validate to keep generated identifiers from being able to
# smuggle a backtick / injection into the SQL text.
_ID_RE = re.compile(r"^[A-Za-z0-9_]+$")
_PROJECT_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def _validate_identifier(value: str, kind: str, pattern=_ID_RE) -> str:
    # ``fullmatch`` (not ``match``): Python's ``$`` matches just before a trailing
    # newline, so ``pattern.match("person\n")`` succeeds and a control character
    # smuggles into the generated DDL. ``fullmatch`` anchors to the true
    # end-of-string and rejects a trailing newline.
    if not value or not pattern.fullmatch(value):
        raise ValueError(f"invalid BigQuery {kind}: {value!r}")
    return value


def qualified_name(table: str, dataset: str, project: str | None = None) -> str:
    """Backtick-quoted GoogleSQL name: `` `project.dataset.table` `` (project opt)."""
    _validate_identifier(table, "table")
    _validate_identifier(dataset, "dataset")
    parts = [dataset, table]
    if project:
        _validate_identifier(project, "project", _PROJECT_RE)
        parts.insert(0, project)
    return "`" + ".".join(parts) + "`"


def bq_target(table: str, dataset: str, project: str | None = None) -> str:
    """`bq` CLI target: ``[project:]dataset.table``."""
    _validate_identifier(table, "table")
    _validate_identifier(dataset, "dataset")
    prefix = ""
    if project:
        _validate_identifier(project, "project", _PROJECT_RE)
        prefix = f"{project}:"
    return f"{prefix}{dataset}.{table}"


def table_schema_json(table: str) -> list[dict]:
    """BigQuery load-schema JSON for one OMOP table.

    The shape ``[{"name", "type", "mode"}, ...]`` is what ``bq load --schema`` and
    the BigQuery client both accept.
    """
    return [
        {"name": col, "type": sql_type(col, _DIALECT), "mode": "NULLABLE"}
        for col in table_columns(table)
    ]


def table_ddl(table: str, dataset: str, project: str | None = None,
              *, if_not_exists: bool = False) -> str:
    """`CREATE TABLE` GoogleSQL DDL for one OMOP CDM table."""
    cols = [(c, sql_type(c, _DIALECT)) for c in table_columns(table)]
    body = ",\n".join(f"  {col} {typ}" for col, typ in cols)
    ine = "IF NOT EXISTS " if if_not_exists else ""
    return f"CREATE TABLE {ine}{qualified_name(table, dataset, project)} (\n{body}\n)"


def schema_ddl(dataset: str, project: str | None = None,
               *, if_not_exists: bool = False) -> str:
    """`CREATE TABLE` DDL for the full OMOP CDM 5.4 table set (semicolon-separated)."""
    stmts = [table_ddl(t, dataset, project, if_not_exists=if_not_exists) for t in OMOP_TABLES]
    return ";\n\n".join(stmts) + ";"


def load_data_sql(table: str, uris, dataset: str, project: str | None = None,
                  *, source_format: str = "CSV", overwrite: bool = False,
                  skip_leading_rows: int = 1) -> str:
    """GoogleSQL ``LOAD DATA`` statement to bulk-load file(s) into an OMOP table.

    ``uris`` is a GCS URI string or an iterable of them. ``overwrite=True`` emits
    ``LOAD DATA OVERWRITE`` (truncate) instead of ``LOAD DATA INTO`` (append).
    """
    uri_list = [uris] if isinstance(uris, str) else list(uris)
    if not uri_list:
        raise ValueError("at least one source URI is required")
    uri_sql = ", ".join("'" + u.replace("'", "\\'") + "'" for u in uri_list)
    into = "OVERWRITE" if overwrite else "INTO"
    opts = [f"format = '{source_format}'", f"uris = [{uri_sql}]"]
    if source_format.upper() == "CSV":
        opts.append(f"skip_leading_rows = {int(skip_leading_rows)}")
    opts_sql = ",\n  ".join(opts)
    return (
        f"LOAD DATA {into} {qualified_name(table, dataset, project)}\n"
        f"FROM FILES (\n  {opts_sql}\n)"
    )


def bq_load_command(table: str, uri: str, dataset: str, project: str | None = None,
                    *, source_format: str = "CSV", skip_leading_rows: int = 1,
                    replace: bool = False) -> str:
    """The equivalent ``bq load`` CLI invocation (string)."""
    parts = ["bq", "load", f"--source_format={source_format}"]
    if source_format.upper() == "CSV":
        parts.append(f"--skip_leading_rows={int(skip_leading_rows)}")
    if replace:
        parts.append("--replace")
    parts.append(bq_target(table, dataset, project))
    parts.append(uri)
    return " ".join(parts)


def load_all_sql(dataset: str, gcs_prefix: str, project: str | None = None,
                 *, overwrite: bool = False) -> dict[str, str]:
    """Map every OMOP table -> its ``LOAD DATA`` statement, expecting CSVs named
    ``{gcs_prefix}/{table}.csv`` (matching :func:`hipaasynth.exporters.export_omop`).
    """
    prefix = gcs_prefix.rstrip("/")
    return {
        table: load_data_sql(table, f"{prefix}/{table}.csv", dataset, project,
                             overwrite=overwrite)
        for table in OMOP_TABLES
    }
