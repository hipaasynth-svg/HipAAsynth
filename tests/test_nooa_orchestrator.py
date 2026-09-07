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


# --- anchor_plan: build info seals the engine/orchestrator build (issue #98) -

def _plan(agent, populations):
    from nooa_validation_orchestrator import ExperimentPlan

    return ExperimentPlan(
        run_id="run-1",
        description="unit-test plan",
        populations=populations,
        created_at=agent._now(),
    )


def test_anchor_plan_build_changes_hash_but_default_is_unchanged(agent):
    plan = _plan(agent, [_spec(label="clean", seed=7)])
    plain = agent.anchor_plan(plan)
    # Same call twice with no build → identical (backward-compatible, plan-only).
    assert plain == agent.anchor_plan(plan)
    # Folding a build in changes the hash, and different builds differ.
    with_build = agent.anchor_plan(plan, build={"engine_version": "1.4.0"})
    other_build = agent.anchor_plan(plan, build={"engine_version": "9.9.9"})
    assert with_build != plain
    assert with_build != other_build


def test_environment_manifest_records_engine_build(agent):
    manifest = agent.environment_manifest()
    # The engine is importable in the test env, so its version is captured.
    assert manifest.engine_version is not None
    assert manifest.orchestrator_version
    assert manifest.python_version
    # anchor_payload excludes the wall-clock timestamp (build identity only).
    assert "created_at" not in manifest.anchor_payload()


# --- run_validation: full plan → generate → audit → card (issue #98) ---------
#
# These exercise the real engine chain with the in-repo MockFairModel, so they
# assert the orchestrator actually drives generate_patients + run_audit and
# writes reproducible artifacts — the gap issue #98 was opened for.

@pytest.fixture()
def fair_model():
    from hipaasynth.dif.model_interface import MockFairModel

    return MockFairModel()


def test_run_validation_end_to_end_writes_artifacts(agent, fair_model, tmp_path):
    from nooa_validation_orchestrator import PlanRun

    plan = _plan(
        agent,
        [
            PopulationSpec(profile=PopulationProfile.MINOT_ND, module=ClinicalModule.STROKE,
                           n=3, seed=101, label="rural-stroke"),
            PopulationSpec(profile=PopulationProfile.FARGO_ND, module=ClinicalModule.SEPSIS,
                           n=2, seed=202, label="aging-sepsis"),
        ],
    )
    run = agent.run_validation(plan, fair_model, output_dir=tmp_path)

    assert run.status == "completed"
    assert [s.status for s in run.summaries] == ["completed", "completed"]
    # One passport per generated patient, adapted from the real engine passport.
    assert len(run.summaries[0].passports) == 3
    assert len(run.summaries[1].passports) == 2

    # The run anchor covers the build, and the persisted plan carries it.
    assert run.plan.plan_hash == run.run_anchor_sha256
    assert run.run_anchor_sha256 != agent.anchor_plan(plan)  # build folded in

    # Run-level artifacts exist on disk.
    for name in ("plan.json", "manifest.json", "checkpoint.json", "run.json"):
        assert (tmp_path / name).is_file()
    # Each population wrote a card, per-patient passports, and adapted JSON.
    for sub, n in (("00_minot_nd_stroke", 3), ("01_fargo_nd_sepsis", 2)):
        pop = tmp_path / "populations" / sub
        assert (pop / "summary.md").is_file()
        assert (pop / "passports.json").is_file()
        assert len(list((pop / "patients").glob("*.md"))) == n

    # The debug log is populated (issue #98, item 5), not left empty.
    assert run.log
    assert any("started" in line for line in run.log)
    assert run.summaries[0].log

    # PlanRun serializes and round-trips from its own artifact.
    reloaded = PlanRun.model_validate_json((tmp_path / "run.json").read_text())
    assert reloaded.run_anchor_sha256 == run.run_anchor_sha256


def test_run_validation_resumes_and_skips_completed(agent, fair_model, tmp_path):
    plan = _plan(
        agent,
        [PopulationSpec(profile=PopulationProfile.MINOT_ND, module=ClinicalModule.STROKE,
                        n=2, seed=1, label="clean")],
    )
    agent.run_validation(plan, fair_model, output_dir=tmp_path)
    card = tmp_path / "populations" / "00_minot_nd_stroke" / "summary.md"
    first_mtime = card.stat().st_mtime_ns

    # A second run over the same dir must reuse the checkpoint, not regenerate.
    run2 = agent.run_validation(plan, fair_model, output_dir=tmp_path)
    assert run2.status == "completed"
    assert any("resuming from checkpoint" in line for line in run2.log)
    assert any("skipped" in line for line in run2.log)
    assert card.stat().st_mtime_ns == first_mtime  # untouched


def test_run_validation_resume_false_ignores_checkpoint(agent, fair_model, tmp_path):
    plan = _plan(
        agent,
        [PopulationSpec(profile=PopulationProfile.MINOT_ND, module=ClinicalModule.STROKE,
                        n=2, seed=1, label="clean")],
    )
    agent.run_validation(plan, fair_model, output_dir=tmp_path)
    run2 = agent.run_validation(plan, fair_model, output_dir=tmp_path, resume=False)
    assert not any("resuming from checkpoint" in line for line in run2.log)
    assert run2.summaries[0].status == "completed"


def test_run_validation_refuses_phi_spec_and_marks_partial(agent, fair_model, tmp_path):
    plan = _plan(
        agent,
        [
            PopulationSpec(profile=PopulationProfile.MINOT_ND, module=ClinicalModule.STROKE,
                           n=2, seed=1, label="clean"),
            PopulationSpec(profile=PopulationProfile.FARGO_ND, module=ClinicalModule.SEPSIS,
                           n=2, seed=2, label="John Doe MRN 12345"),
        ],
    )
    run = agent.run_validation(plan, fair_model, output_dir=tmp_path)
    assert run.status == "partial"
    ok, bad = run.summaries
    assert ok.status == "completed"
    assert bad.status == "failed"
    assert bad.errors  # zero-PHI reasons recorded
    # The refused population never produced a card.
    assert not (tmp_path / "populations" / "01_fargo_nd_sepsis").exists()


# --- groundedness validator (issue #98, item 6) ------------------------------

def _real_summary(agent, fair_model, tmp_path):
    plan = _plan(
        agent,
        [PopulationSpec(profile=PopulationProfile.MINOT_ND, module=ClinicalModule.STROKE,
                        n=2, seed=9, label="clean")],
    )
    run = agent.run_validation(plan, fair_model, output_dir=tmp_path)
    return run.summaries[0].passports[0]


def test_groundedness_accepts_grounded_interpretation(agent, fair_model, tmp_path):
    from nooa_validation_orchestrator import Interpretation

    summary = _real_summary(agent, fair_model, tmp_path)
    dcs = summary.metrics[FairnessMetric.DCS]["value"]
    interp = Interpretation(
        run_id=summary.run_id,
        summary=f"Decision consistency was {dcs:.3f} across the seven forms.",
        form_level_notes={"FHIR_STRUCTURED": "consistent decision"},
        metric_notes={"DCS": "within threshold"},
    )
    assert agent.groundedness_violations(interp, summary) == []


def test_groundedness_flags_unknown_form_metric_and_number(agent, fair_model, tmp_path):
    from nooa_validation_orchestrator import Interpretation

    summary = _real_summary(agent, fair_model, tmp_path)
    interp = Interpretation(
        run_id=summary.run_id,
        summary="The model scored 0.42 overall.",  # fabricated value
        form_level_notes={"MADE_UP_FORM": "x"},     # not one of the seven
        metric_notes={"ZZZ": "y"},                  # not one of the four
    )
    violations = agent.groundedness_violations(interp, summary)
    assert any("unknown form" in v for v in violations)
    assert any("unknown metric" in v for v in violations)
    assert any("0.42" in v for v in violations)
    with pytest.raises(ValueError):
        agent.assert_grounded(interp, summary)


def test_groundedness_flags_valid_form_absent_from_passport(agent):
    from nooa_validation_orchestrator import (
        FairnessPassportSummary,
        Interpretation,
        PopulationSpec,
    )

    spec = _spec(label="clean")
    # A summary that only recorded one form.
    summary = FairnessPassportSummary(
        run_id="r",
        anchor_sha256="x",
        population_spec=spec,
        per_form_decisions={DocumentationForm.FHIR_STRUCTURED: True},
        metrics={FairnessMetric.DCS: {"value": 0.90, "pass": True}},
        generated_at="2026-07-28T00:00:00Z",
    )
    # LEP_TRANSLATED is a real form, but this passport never recorded it.
    interp = Interpretation(
        run_id="r",
        summary="ok",
        form_level_notes={"LEP_TRANSLATED": "no decision"},
    )
    violations = agent.groundedness_violations(interp, summary)
    assert any("absent from the passport" in v for v in violations)
