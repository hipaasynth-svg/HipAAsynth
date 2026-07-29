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

"""Tests for the NOOA validation orchestrator example.

The orchestrator lives under ``examples/`` (outside the pure-stdlib
``hipaasynth`` package) and depends on ``pydantic``. These tests are skipped
where pydantic is not installed so the core test suite stays stdlib-only.
"""

import sys
from pathlib import Path

import pytest

pytest.importorskip("pydantic")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "examples"))

from nooa_validation_orchestrator import (  # noqa: E402
    ClinicalModule,
    DocumentationForm,
    FairnessMetric,
    HipAAsynthAgent,
    PopulationProfile,
    PopulationSpec,
)


@pytest.fixture()
def agent() -> HipAAsynthAgent:
    return HipAAsynthAgent()


# --- agentic methods must be async (nooa only generates async ellipsis) ------

@pytest.mark.parametrize(
    "name",
    ["design_experiment", "interpret_passport", "suggest_next_tests", "explain_form_disparity"],
)
def test_agentic_methods_are_coroutines(name):
    # nooa's metaclass treats only `async def` + `...` bodies as generatable;
    # a sync `...` method silently returns None instead of calling the LLM.
    import asyncio

    assert asyncio.iscoroutinefunction(getattr(HipAAsynthAgent, name))


def _spec(label=None, seed=1) -> PopulationSpec:
    return PopulationSpec(
        profile=PopulationProfile.MINOT_ND,
        module=ClinicalModule.STROKE,
        n=10,
        seed=seed,
        label=label,
    )


# --- derive_seed: engine-consistent 32-bit convention -----------------------

def test_derive_seed_is_deterministic(agent):
    a = agent.derive_seed(42, PopulationProfile.MINOT_ND, ClinicalModule.STROKE, "t")
    b = agent.derive_seed(42, PopulationProfile.MINOT_ND, ClinicalModule.STROKE, "t")
    assert a == b


def test_derive_seed_is_32_bit(agent):
    # The engine's stable_seed_from_id convention is a 32-bit unsigned int; the
    # original returned a 64-bit value (digest[:16]).
    for tag in ("a", "b", "rural-stroke", "sepsis-2"):
        seed = agent.derive_seed(42, PopulationProfile.FARGO_ND, ClinicalModule.SEPSIS, tag)
        assert 0 <= seed < 2**32


def test_derive_seed_matches_engine_convention(agent):
    # When the engine is importable, a byte-for-byte comparison against its own
    # 32-bit derivation would go here. We at least assert the width contract.
    seed = agent.derive_seed(7, PopulationProfile.US_DEFAULT, ClinicalModule.CHF, "x")
    assert seed.bit_length() <= 32


# --- verify_zero_phi: actually rejects PHI-like labels ----------------------

def test_clean_label_passes(agent):
    assert agent.verify_zero_phi(_spec(label="rural-stroke-pilot")) is True
    assert agent.verify_zero_phi(_spec(label=None)) is True


@pytest.mark.parametrize(
    "label",
    [
        "John Doe MRN 12345",
        "patient at 123 Main St",
        "dob 01/02/1990",
        "contact jane@example.com",
        "ssn on file",
        "call 5551234",
    ],
)
def test_phi_like_labels_are_rejected(agent, label):
    spec = _spec(label=label)
    assert agent.verify_zero_phi(spec) is False
    assert agent.zero_phi_reasons(spec)  # non-empty explanation


def test_assemble_passport_refuses_phi_label(agent):
    spec = _spec(label="MRN 000123")
    with pytest.raises(ValueError):
        agent.assemble_passport(
            run_id="r1",
            spec=spec,
            per_form_decisions={DocumentationForm.FHIR_STRUCTURED: True},
            metrics={FairnessMetric.DCS: 1.0},
            generated_at="2026-07-28T00:00:00Z",
        )


# --- from_engine_passport: adapts a real FairnessPassport-shaped object ------

class _FakeMetrics:
    dcs, isg, lfdi, saf = 0.92, 0.10, 0.05, 0.08
    dcs_pass = isg_pass = lfdi_pass = saf_pass = True


class _FakeEnginePassport:
    """Duck-typed stand-in matching hipaasynth.dif.FairnessPassport's surface."""

    device_name = "Demo Model"
    device_version = "1.0.0"
    patient_id = "SYN-0001"
    anchor_hash = "deadbeef"
    decisions = {
        "FHIR_STRUCTURED": True,
        "PHYSICIAN_SOAP": True,
        "PATIENT_LOW_LITERACY": False,
    }
    refused_forms = ["LEP_TRANSLATED"]
    unparseable_forms: list = []
    metrics = _FakeMetrics()

    def passed(self) -> bool:
        return True


def test_from_engine_passport_maps_forms_and_metrics(agent):
    spec = _spec(label="clean")
    summary = agent.from_engine_passport(_FakeEnginePassport(), run_id="r2", spec=spec)

    assert summary.patient_id == "SYN-0001"
    assert summary.model_under_test == "Demo Model 1.0.0"
    assert summary.passed is True
    # Engine anchor takes precedence over the locally computed one.
    assert summary.anchor_sha256 == "deadbeef"
    # String form names became DocumentationForm keys.
    assert summary.per_form_decisions[DocumentationForm.FHIR_STRUCTURED] is True
    assert summary.per_form_decisions[DocumentationForm.PATIENT_LOW_LITERACY] is False
    assert DocumentationForm.LEP_TRANSLATED in summary.refused_forms
    # All four metrics mapped with value/pass pairs.
    assert set(summary.metrics.keys()) == set(FairnessMetric)
    assert summary.metrics[FairnessMetric.DCS] == {"value": 0.92, "pass": True}


def test_summary_json_round_trips(agent):
    summary = agent.from_engine_passport(_FakeEnginePassport(), run_id="r3", spec=_spec())
    from nooa_validation_orchestrator import FairnessPassportSummary

    reloaded = FairnessPassportSummary.model_validate_json(summary.model_dump_json())
    assert reloaded.per_form_decisions == summary.per_form_decisions


# --- Interpretation must have a self-contained (no $defs/$ref) schema -------
#
# Empirically observed against a live xAI grok-3 call: a Dict keyed by a str
# Enum (DocumentationForm/FairnessMetric) renders as a `propertyNames` $ref
# into a `$defs` block, and xAI's structured-output validator rejects it
# ("unresolvable $ref '#/$defs/...': key '$defs' not found in schema") when
# asked to generate this model directly. Plain string keys avoid the $ref
# entirely. This test locks in that shape so it can't regress.

def _find_ref_keys(node):
    """Recursively collect any dict keys literally named '$ref' or '$defs'."""
    found = []
    if isinstance(node, dict):
        found.extend(k for k in ("$ref", "$defs") if k in node)
        for v in node.values():
            found.extend(_find_ref_keys(v))
    elif isinstance(node, list):
        for item in node:
            found.extend(_find_ref_keys(item))
    return found


def test_interpretation_schema_has_no_defs_or_refs():
    from nooa_validation_orchestrator import Interpretation

    schema = Interpretation.model_json_schema()
    # A structural check (dict keys), not a substring search — the class
    # docstring itself discusses "$ref"/"$defs" in prose.
    assert _find_ref_keys(schema) == []


def test_interpretation_accepts_string_keyed_notes():
    from nooa_validation_orchestrator import Interpretation

    interp = Interpretation(
        run_id="r1",
        summary="Documentation-form effects observed; no bias claim made.",
        form_level_notes={"FHIR_STRUCTURED": "consistent decision"},
        metric_notes={"DCS": "within threshold"},
    )
    # str-Enum equality/hash means the enum member still matches a plain key.
    assert DocumentationForm.FHIR_STRUCTURED in interp.form_level_notes
    assert FairnessMetric.DCS in interp.metric_notes
