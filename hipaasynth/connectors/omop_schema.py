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

"""Shared OMOP CDM 5.4 schema metadata for warehouse connectors.

Single source of truth for **column → SQL type** across every connector (DuckDB,
BigQuery, …). The *column sets* come straight from
:data:`hipaasynth.exporters.omop._TABLE_COLUMNS` (the same lists the OMOP CSV
exporter writes), so a connector's schema can never drift from the exported data.

Pure standard library — no database driver is imported here; this module only
builds type metadata and (optionally) DDL/SQL *text*.
"""
from __future__ import annotations

from hipaasynth.exporters.omop import _TABLE_COLUMNS

# Canonical table order (person first, then the period/fact tables).
OMOP_TABLES: tuple[str, ...] = tuple(_TABLE_COLUMNS.keys())

# Logical types, dialect-independent. Connectors map these to concrete SQL types.
INT = "int"
FLOAT = "float"
DATE = "date"
TIMESTAMP = "timestamp"
STRING = "string"

# Columns whose OMOP CDM 5.4 type is NOT inferable from the name suffix rules
# below (e.g. `year_of_birth` is an integer but doesn't end in `_id`). Listed
# explicitly so the mapping is correct, not merely convention-guessed.
_COLUMN_TYPE_OVERRIDES = {
    "year_of_birth": INT,
    "month_of_birth": INT,
    "day_of_birth": INT,
    "measurement_time": STRING,   # CDM stores the time-of-day as a varchar
    "value_as_number": FLOAT,
    "range_low": FLOAT,
    "range_high": FLOAT,
    "quantity": FLOAT,
    "refills": INT,
    "days_supply": INT,
    "stop_reason": STRING,
    "sig": STRING,
    "lot_number": STRING,
}


def logical_type(column: str) -> str:
    """Return the dialect-independent logical type for an OMOP CDM column.

    Precedence: explicit override → ``*_concept_id``/``*_id`` (INT) →
    ``*_datetime`` (TIMESTAMP) → ``*_date`` (DATE) → STRING. Note ``*_source_value``
    columns end in ``_value`` and correctly fall through to STRING.
    """
    if column in _COLUMN_TYPE_OVERRIDES:
        return _COLUMN_TYPE_OVERRIDES[column]
    if column.endswith("_concept_id") or column.endswith("_id"):
        return INT
    if column.endswith("_datetime"):
        return TIMESTAMP
    if column.endswith("_date"):
        return DATE
    return STRING


# Logical type -> concrete SQL type, per dialect.
_SQL_TYPES = {
    "duckdb": {
        INT: "BIGINT",
        FLOAT: "DOUBLE",
        DATE: "DATE",
        TIMESTAMP: "TIMESTAMP",
        STRING: "VARCHAR",
    },
    "bigquery": {
        INT: "INT64",
        FLOAT: "FLOAT64",
        DATE: "DATE",
        TIMESTAMP: "DATETIME",  # OMOP datetimes are local/tz-naive -> DATETIME
        STRING: "STRING",
    },
}

SUPPORTED_DIALECTS = tuple(_SQL_TYPES.keys())


def sql_type(column: str, dialect: str) -> str:
    """Concrete SQL type string for ``column`` in ``dialect`` (e.g. 'BIGINT')."""
    try:
        types = _SQL_TYPES[dialect]
    except KeyError:
        raise ValueError(
            f"unknown dialect {dialect!r}; supported: {', '.join(SUPPORTED_DIALECTS)}"
        )
    return types[logical_type(column)]


def table_columns(table: str) -> list[str]:
    """Ordered column names for an OMOP CDM table."""
    try:
        return list(_TABLE_COLUMNS[table])
    except KeyError:
        raise ValueError(
            f"unknown OMOP table {table!r}; known: {', '.join(OMOP_TABLES)}"
        )


def column_types(table: str, dialect: str) -> list[tuple[str, str]]:
    """List of ``(column, sql_type)`` pairs for a table in the given dialect."""
    return [(c, sql_type(c, dialect)) for c in table_columns(table)]
