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

"""Shared pytest fixtures for the HipAAsynth engine test suite."""

import pytest

from hipaasynth.core.config import DEFAULT_SYNTHETIC_DISCLAIMER, GenerationConfig
from hipaasynth.core.schema import Patient
from hipaasynth.dif import DIFConfig
from hipaasynth.dif.model_interface import MockBiasedModel, MockFairModel
from hipaasynth.pipelines.population_pipeline import generate_patients


def _make_config(
    patient_count: int, required_condition: str | None, seed: int = 42
) -> GenerationConfig:
    return GenerationConfig(
        patient_count=patient_count,
        seed=seed,
        age_min=18,
        age_max=90,
        required_condition=required_condition,
        sex_ratio_female=0.5,
        ethnicity_weights=None,
        include_visits=True,
        include_labs=True,
        visits_min=1,
        visits_max=2,
        synthetic_disclaimer=DEFAULT_SYNTHETIC_DISCLAIMER,
        run_date="2026-06-24",
    )


@pytest.fixture
def gen_config() -> GenerationConfig:
    """Default generation config for tests (5 patients, deterministic seed)."""
    return _make_config(patient_count=5, required_condition=None, seed=42)


@pytest.fixture
def dif_config() -> DIFConfig:
    """Default DIF audit config."""
    return DIFConfig(
        device_name="TestModel",
        device_version="0.1.0",
    )


@pytest.fixture
def biased_model() -> MockBiasedModel:
    """Biased mock model that under-triages patient/LEP forms."""
    return MockBiasedModel()


@pytest.fixture
def fair_model() -> MockFairModel:
    """Fair mock model with consistent decisions across all forms."""
    return MockFairModel()


@pytest.fixture
def invisible_generator():
    """The canonical engine population pipeline."""
    return generate_patients


@pytest.fixture
def sample_patient() -> Patient:
    """A single generated patient with an acute vascular presentation (stroke/STEMI proxy)."""
    cfg = _make_config(patient_count=1, required_condition="stroke", seed=123)
    patients = generate_patients(cfg)
    return patients[0]
