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

"""Identifier-safety and statistical-property regression tests.

Guards the two guarantees the engine's value proposition rests on:

1. **Zero real identifiers.** Generated cohorts must never contain a value
   shaped like a real-world identifier (SSN, NPI, phone, email), and every
   record must be explicitly ``synthetic=True`` and disclaimer-stamped.
2. **Statistical fidelity.** The generated demographic distribution must match
   the configured population profile within tolerance.

These are behavioral assertions on the public generators — they make **no**
change to the engine.

Note on patient-ID formats: they are intentionally *not* uniform across modules
(``SYN-OUD-…``, ``SYN-CHF-…``, ``SYN-{seed:08x}`` on the pipeline path, and
``DMD-…`` / ``DM_…`` / ``FABRY-…`` in other modules). The safety guarantee is
therefore expressed as a real-identifier **deny-list**, not a single-prefix
allow-list — a naive "everything starts with SYN-" check would be wrong.
"""

import re
from collections import Counter

import pytest

from hipaasynth.core.config import GenerationConfig
from hipaasynth.pipelines.population_pipeline import generate_patients
from hipaasynth.modules.oud.oud_generator import generate_oud_cohort
from hipaasynth.modules.chf.chf_generator import generate_chf_cohort
from hipaasynth.modules.copd.copd_generator import generate_copd_cohort

# Cohort generators sharing the (seed, n[, label]) -> (patients, anchor) API.
_MODULE_GENERATORS = [
    ("oud", generate_oud_cohort),
    ("chf", generate_chf_cohort),
    ("copd", generate_copd_cohort),
]

# Real-identifier shapes that must NEVER appear in synthetic output. Each is
# word-boundary anchored, so it cannot match a digit run *inside* a hex anchor
# hash (digit↔hex-letter is not a word boundary).
_REAL_ID_PATTERNS = {
    "ssn": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    "phone": re.compile(r"\b\d{3}[.\-]\d{3}[.\-]\d{4}\b"),
    "email": re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"),
    # SSN without dashes, NPI (10 digits), or a long numeric MRN.
    "npi_or_long_numeric_id": re.compile(r"\b\d{9,}\b"),
}


def _iter_strings(obj):
    """Yield every string leaf value in a nested record (dict / list / scalar).

    Ints and floats are deliberately skipped: numeric clinical fields — and the
    32-bit demographics ``seed`` (a legitimately 10-digit integer) — are values,
    not identifiers, and would otherwise trip the long-numeric pattern.
    """
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


def _assert_synthetic_stamp(record):
    assert record.get("synthetic") is True, "record is not stamped synthetic=True"
    # Two disclaimer phrasings exist in the engine — the module generators say
    # "No PHI", the pipeline path says "No real patient information is present".
    # Assert the shared semantic guarantee, not one specific wording.
    disclaimer = str(record.get("disclaimer", "")).upper()
    assert "SYNTHETIC" in disclaimer and "NO REAL PATIENT" in disclaimer, (
        f"record missing synthetic / no-real-patient disclaimer: {record.get('disclaimer')!r}"
    )


class TestNoRealIdentifiers:
    """The central safety claim: synthetic output carries zero real identifiers."""

    @pytest.mark.parametrize("name,generator", _MODULE_GENERATORS)
    def test_module_cohort_has_no_real_identifiers(self, name, generator):
        patients, _anchor = generator(seed=42, n=200)
        assert patients, f"{name}: generator returned no patients"
        for record in patients:
            _assert_no_real_identifiers(record)
            _assert_synthetic_stamp(record)
            assert str(record["patient_id"]).startswith("SYN-"), (
                f"{name}: patient_id not SYN-prefixed: {record['patient_id']!r}"
            )

    def test_pipeline_cohort_has_no_real_identifiers(self):
        records = [p.to_dict() for p in generate_patients(GenerationConfig(patient_count=200, seed=42))]
        assert records, "pipeline returned no patients"
        for record in records:
            _assert_no_real_identifiers(record)
            _assert_synthetic_stamp(record)
            patient_id = record["demographics"]["patient_id"]
            assert patient_id.startswith("SYN-"), (
                f"pipeline patient_id not SYN-prefixed: {patient_id!r}"
            )


class TestDeterminism:
    """Reproducibility is a core guarantee: same seed ⇒ identical cohort."""

    @pytest.mark.parametrize("name,generator", _MODULE_GENERATORS)
    def test_same_seed_reproduces_cohort(self, name, generator):
        first, _ = generator(seed=123, n=100)
        second, _ = generator(seed=123, n=100)
        assert [r["patient_id"] for r in first] == [r["patient_id"] for r in second]
        assert first == second, f"{name}: identical seed produced differing cohorts"


class TestStatisticalProperties:
    """Generated demographics must match the configured profile within tolerance."""

    # Deterministic generation with these seeds/sizes lands well inside 0.04.
    TOLERANCE = 0.04

    def test_sex_ratio_matches_config(self):
        cfg = GenerationConfig(patient_count=2000, seed=7, sex_ratio_female=0.30)
        demographics = [p.to_dict()["demographics"] for p in generate_patients(cfg)]
        female_fraction = sum(d["sex"] == "female" for d in demographics) / len(demographics)
        assert abs(female_fraction - 0.30) < self.TOLERANCE, (
            f"female fraction {female_fraction:.3f} deviates from configured 0.30"
        )

    def test_ethnicity_distribution_matches_config(self):
        # Keys must match the engine's lowercase ethnicity options; mismatched
        # casing silently zeroes the weights and collapses to a single group.
        weights = {
            "white": 0.50,
            "black": 0.20,
            "hispanic": 0.20,
            "asian": 0.05,
            "native": 0.03,
            "other": 0.02,
        }
        cfg = GenerationConfig(patient_count=2000, seed=7, ethnicity_weights=weights)
        demographics = [p.to_dict()["demographics"] for p in generate_patients(cfg)]
        total = len(demographics)
        counts = Counter(d["ethnicity"] for d in demographics)
        for ethnicity, target in weights.items():
            fraction = counts.get(ethnicity, 0) / total
            assert abs(fraction - target) < self.TOLERANCE, (
                f"{ethnicity}: {fraction:.3f} deviates from configured {target}"
            )
