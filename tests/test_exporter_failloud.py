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

"""Fail-loud contract for the exporters (issue #25).

The exporters must never leave a silent partial artifact: any I/O failure is
re-raised as ``RuntimeError``. These tests exercise that contract by pointing
each exporter at a path that is an existing directory, so the underlying
``open(path, "w")`` raises ``IsADirectoryError`` (an ``OSError``) — which the
exporter must surface as ``RuntimeError``.
"""

import pytest

from hipaasynth.core.config import GenerationConfig
from hipaasynth.pipelines.population_pipeline import generate_patients
from hipaasynth.exporters.exporters import (
    export_csv,
    export_csv_stream,
    export_fhir,
    export_json,
)


@pytest.fixture
def patients():
    return generate_patients(GenerationConfig(patient_count=5, seed=42))


@pytest.mark.parametrize("exporter", [export_csv, export_json, export_fhir])
def test_buffered_exporters_fail_loud_on_io_error(exporter, patients, tmp_path):
    target = tmp_path / "occupied"
    target.mkdir()  # target path is a directory -> open(..., "w") fails
    with pytest.raises(RuntimeError):
        exporter(patients, str(target))


def test_csv_stream_fails_loud_on_io_error(patients, tmp_path):
    target = tmp_path / "occupied"
    target.mkdir()
    with pytest.raises(RuntimeError):
        export_csv_stream(iter(patients), str(target))
