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

"""Warehouse connectors for HipAAsynth cohorts.

Submodules are imported explicitly (``from hipaasynth.connectors import duckdb``)
rather than re-exported here, so importing this package pulls in **no** database
driver — the DuckDB connector's ``duckdb`` dependency stays lazy (the ``[duckdb]``
optional extra), preserving the stdlib-only core. The BigQuery connector
(``hipaasynth.connectors.bigquery``) and the shared OMOP schema metadata
(``hipaasynth.connectors.omop_schema``) are pure standard library.
"""
