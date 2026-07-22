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

"""Smoke + safety tests for the rare-disease / diabetes cohort generators.

These class-based generators (DMD, Fabry, SMA, diabetes) previously had ~0%
test coverage. This module exercises each one's public entry point and asserts
the invariants that matter for a synthetic-data engine — without changing any
engine code:

- a cohort of the requested size is produced;
- generation is deterministic (same seed ⇒ identical cohort);
- every record is a dict with a unique, non-empty patient id;
- no record contains a real-identifier shape (SSN / NPI / phone / email),
  extending the identifier-safety guarantee (issue #24) to these divergent-API
  modules.

Every record is also asserted to carry the ``synthetic`` / ``disclaimer`` stamp
(added to these generators to close issue #33).
"""

import re

import pytest

from hipaasynth.modules.dmd.dmd import DMDCohortGenerator
from hipaasynth.modules.fabry.fabry import FabryCohortGenerator
from hipaasynth.modules.sma.sma import SMACohortGenerator
from hipaasynth.modules.diabetes.population import DiabetesPopulationGenerator
from hipaasynth.modules.sepsis.oncology.cohort import OncologyCohortGenerator
from hipaasynth.modules.cardiology.cohort import CardiologyCohortGenerator

# Real-identifier shapes that must never appear (boundary-anchored so they can't
# match a digit run inside a hex string). Kept local to keep this test module
# independent of the sibling identifier-safety test.
_REAL_ID_PATTERNS = {
    "ssn": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    "phone": re.compile(r"\b\d{3}[.\-]\d{3}[.\-]\d{4}\b"),
    "email": re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"),
    "npi_or_long_numeric_id": re.compile(r"\b\d{9,}\b"),
}


def _iter_strings(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for value in obj.values():
            yield from _iter_strings(value)
    elif isinstance(obj, (list, tuple)):
        for value in obj:
            yield from _iter_strings(value)


def _assert_no_real_identifiers(record):
    for value in _iter_strings(record):
        for name, pattern in _REAL_ID_PATTERNS.items():
            assert not pattern.search(value), (
                f"real-identifier shape '{name}' found in synthetic value: {value!r}"
            )


# (name, factory) where factory(n) -> cohort list, seeded deterministically.
_MODULE_COHORTS = [
    ("dmd", lambda n: DMDCohortGenerator(seed=42).generate(n)),
    ("fabry", lambda n: FabryCohortGenerator(seed=42).generate(n)),
    ("sma", lambda n: SMACohortGenerator(seed=42).generate(n)),
    ("diabetes", lambda n: DiabetesPopulationGenerator(n=n, seed=42).generate()),
    ("oncology", lambda n: OncologyCohortGenerator(seed=42).generate(n)),
    ("cardiology", lambda n: CardiologyCohortGenerator(seed=42).generate(n)),
]


class TestModuleCohortSmoke:
    @pytest.mark.parametrize("name,factory", _MODULE_COHORTS)
    def test_generates_requested_size(self, name, factory):
        cohort = factory(30)
        assert isinstance(cohort, list), f"{name}: cohort is not a list"
        assert len(cohort) == 30, f"{name}: expected 30 records, got {len(cohort)}"

    @pytest.mark.parametrize("name,factory", _MODULE_COHORTS)
    def test_records_have_unique_nonempty_ids(self, name, factory):
        cohort = factory(30)
        ids = []
        for record in cohort:
            assert isinstance(record, dict), f"{name}: record is not a dict"
            pid = record.get("patient_id")
            assert isinstance(pid, str) and pid, f"{name}: missing/empty patient_id: {pid!r}"
            ids.append(pid)
        assert len(set(ids)) == len(ids), f"{name}: duplicate patient_ids"

    @pytest.mark.parametrize("name,factory", _MODULE_COHORTS)
    def test_generation_is_deterministic(self, name, factory):
        assert factory(30) == factory(30), f"{name}: same seed produced differing cohorts"

    @pytest.mark.parametrize("name,factory", _MODULE_COHORTS)
    def test_no_real_identifiers(self, name, factory):
        for record in factory(30):
            _assert_no_real_identifiers(record)

    @pytest.mark.parametrize("name,factory", _MODULE_COHORTS)
    def test_records_are_synthetic_stamped(self, name, factory):
        for record in factory(30):
            assert record.get("synthetic") is True, f"{name}: record not stamped synthetic=True"
            disclaimer = str(record.get("disclaimer", "")).upper()
            assert "SYNTHETIC" in disclaimer and "NO REAL PATIENT" in disclaimer, (
                f"{name}: record missing synthetic / no-real-patient disclaimer"
            )
