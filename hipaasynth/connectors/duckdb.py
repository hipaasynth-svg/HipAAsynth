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

"""DuckDB connector — load a cohort into a real local DuckDB database.

DuckDB is embedded (no server, no account, no network), so this is the reference
connector implementation and the one that is genuinely integration-tested against
a real database file in this project's test suite.

``duckdb`` is an **optional** dependency (the ``[duckdb]`` extra), imported lazily
inside :func:`load` — importing this module, or ``hipaasynth`` itself, pulls in
nothing new, preserving the stdlib-only core (the same pattern as ``pyarrow`` /
``[parquet]``).

Entry point::

    from hipaasynth import generate
    from hipaasynth.connectors import duckdb as duckdb_connector

    cohort = generate(count=100, seed=42)
    summary = duckdb_connector.load(cohort, "cohort.duckdb")   # OMOP CDM tables
    # -> {"person": 100, "condition_occurrence": ..., ...}

All records are synthetic (no PHI).
"""
from __future__ import annotations

from datetime import date, datetime

from hipaasynth.connectors.omop_schema import (
    OMOP_TABLES,
    column_types,
    logical_type,
    table_columns,
)
from hipaasynth.exporters.exporters import _flat_patient_rows
from hipaasynth.exporters.omop import build_cdm_tables


def _import_duckdb():
    try:
        import duckdb  # top-level library (absolute import; not this module)
    except ImportError as exc:  # pragma: no cover - exercised via monkeypatch test
        raise RuntimeError(
            "The DuckDB connector requires the optional 'duckdb' dependency, which "
            "is not installed. Install it with: pip install 'hipaasynth[duckdb]'"
        ) from exc
    return duckdb


def _patients_of(cohort):
    """Accept a hipaasynth.Cohort or a plain iterable of Patient records."""
    return list(getattr(cohort, "patients", cohort))


def _coerce(value, ltype: str):
    """Coerce an OMOP CSV-shaped value to a typed Python value (''/None -> NULL)."""
    if value is None or value == "":
        return None
    if ltype == "int":
        return int(value)
    if ltype == "float":
        return float(value)
    if ltype == "date":
        return value if isinstance(value, date) else date.fromisoformat(str(value))
    if ltype == "timestamp":
        return value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    return str(value)


def _quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def create_table_ddl(table: str, dialect: str = "duckdb") -> str:
    """CREATE TABLE DDL for an OMOP CDM table (used internally; also handy in tests)."""
    cols = ", ".join(f"{_quote_ident(c)} {t}" for c, t in column_types(table, dialect))
    return f"CREATE TABLE {_quote_ident(table)} ({cols})"


def _create(con, table: str, if_exists: str):
    cols = ", ".join(f"{_quote_ident(c)} {t}" for c, t in column_types(table, "duckdb"))
    if if_exists == "replace":
        con.execute(f"DROP TABLE IF EXISTS {_quote_ident(table)}")
        con.execute(f"CREATE TABLE {_quote_ident(table)} ({cols})")
    elif if_exists == "append":
        con.execute(f"CREATE TABLE IF NOT EXISTS {_quote_ident(table)} ({cols})")
    else:
        raise ValueError(f"if_exists must be 'replace' or 'append', got {if_exists!r}")


def _insert_rows(con, table: str, columns, ltypes, rows):
    if not rows:
        return 0
    placeholders = ", ".join(["?"] * len(columns))
    stmt = f"INSERT INTO {_quote_ident(table)} VALUES ({placeholders})"
    data = [
        tuple(_coerce(row.get(col, ""), lt) for col, lt in zip(columns, ltypes))
        for row in rows
    ]
    con.executemany(stmt, data)
    return len(data)


def _load_omop(con, patients, if_exists):
    tables = build_cdm_tables(patients)
    summary = {}
    for table in OMOP_TABLES:
        columns = table_columns(table)
        ltypes = [logical_type(c) for c in columns]
        _create(con, table, if_exists)
        summary[table] = _insert_rows(con, table, columns, ltypes, tables[table])
    return summary


# Flat patient table: base fields have known types; observation columns are typed
# as DOUBLE when every present value is numeric, else VARCHAR.
_FLAT_BASE_TYPES = {
    "patient_id": "VARCHAR", "seed": "BIGINT", "age": "BIGINT",
    "sex": "VARCHAR", "ethnicity": "VARCHAR",
    "height_cm": "DOUBLE", "weight_kg": "DOUBLE", "bmi": "DOUBLE",
    "bmi_category": "VARCHAR", "conditions": "VARCHAR",
    "num_visits": "BIGINT", "num_labs": "BIGINT",
    "engine_version": "VARCHAR", "schema_version": "VARCHAR",
    "synthetic": "BOOLEAN", "disclaimer": "VARCHAR",
}
_SQL_TO_LOGICAL = {
    "VARCHAR": "string", "BIGINT": "int", "DOUBLE": "float", "BOOLEAN": "bool",
}


def _is_number(value) -> bool:
    if value is None or value == "":
        return True  # empty -> NULL, doesn't disqualify a numeric column
    try:
        float(value)
        return True
    except (TypeError, ValueError):
        return False


def _coerce_flat(value, sqltype):
    if value is None or value == "":
        return None
    if sqltype == "BIGINT":
        return int(value)
    if sqltype == "DOUBLE":
        return float(value)
    if sqltype == "BOOLEAN":
        return bool(value)
    return str(value)


def _load_flat(con, patients, table_name, if_exists):
    fieldnames, rows = _flat_patient_rows(patients)
    sqltypes = {}
    for col in fieldnames:
        if col in _FLAT_BASE_TYPES:
            sqltypes[col] = _FLAT_BASE_TYPES[col]
        else:  # dynamic observation column
            sqltypes[col] = "DOUBLE" if all(_is_number(r.get(col)) for r in rows) else "VARCHAR"
    cols_sql = ", ".join(f"{_quote_ident(c)} {sqltypes[c]}" for c in fieldnames)
    if if_exists == "replace":
        con.execute(f"DROP TABLE IF EXISTS {_quote_ident(table_name)}")
        con.execute(f"CREATE TABLE {_quote_ident(table_name)} ({cols_sql})")
    elif if_exists == "append":
        con.execute(f"CREATE TABLE IF NOT EXISTS {_quote_ident(table_name)} ({cols_sql})")
    else:
        raise ValueError(f"if_exists must be 'replace' or 'append', got {if_exists!r}")
    if rows:
        placeholders = ", ".join(["?"] * len(fieldnames))
        stmt = f"INSERT INTO {_quote_ident(table_name)} VALUES ({placeholders})"
        data = [tuple(_coerce_flat(r.get(c), sqltypes[c]) for c in fieldnames) for r in rows]
        con.executemany(stmt, data)
    return {table_name: len(rows)}


def load(cohort, database, *, mode: str = "omop", if_exists: str = "replace",
         flat_table: str = "patient") -> dict:
    """Load a cohort into a DuckDB database and return ``{table: row_count}``.

    Args:
        cohort: a :class:`hipaasynth.Cohort` or an iterable of ``Patient`` records.
        database: path to a ``.duckdb`` file (created if absent), or ``":memory:"``.
        mode: ``"omop"`` (default) loads the six OMOP CDM 5.4 tables with typed
            columns; ``"flat"`` loads the single flat patient table.
        if_exists: ``"replace"`` (drop + recreate, default) or ``"append"``.
        flat_table: table name for ``mode="flat"``.

    Returns:
        dict mapping loaded table name -> number of rows inserted.
    """
    duckdb = _import_duckdb()
    patients = _patients_of(cohort)
    con = duckdb.connect(str(database))
    try:
        if mode == "omop":
            return _load_omop(con, patients, if_exists)
        if mode == "flat":
            return _load_flat(con, patients, flat_table, if_exists)
        raise ValueError(f"mode must be 'omop' or 'flat', got {mode!r}")
    finally:
        con.close()
