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

"""Tests for the ATLAS cohort ingestion bridge."""

import json
from pathlib import Path

import pytest

from hipaasynth.core.config import GenerationConfig
from hipaasynth.pipelines.population_pipeline import generate_patients
from hipaasynth.ohdsi import (
    AtlasCohortPlan,
    load_atlas_cohort,
    parse_atlas_cohort,
)
from hipaasynth.vocabulary import terms_for_concept_id

FIXTURE = Path(__file__).parent / "fixtures" / "atlas_heart_failure_cohort.json"


@pytest.fixture
def cohort_data():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


# ── reverse vocabulary lookup ────────────────────────────────────────────────

def test_terms_for_concept_id_resolves_condition():
    terms = terms_for_concept_id(319835)
    assert ("conditions", "congestive_heart_failure") in terms


def test_terms_for_concept_id_unknown_is_empty():
    assert terms_for_concept_id(999999999) == []
    assert terms_for_concept_id(None) == []


def test_terms_for_concept_id_prefers_allowed_when_multiple():
    # 313217 maps to both 'afib' and 'atrial_fibrillation' in the map.
    terms = {t for _s, t in terms_for_concept_id(313217)}
    assert {"afib", "atrial_fibrillation"} <= terms


# ── parsing ──────────────────────────────────────────────────────────────────

def test_parse_matches_and_unmatches(cohort_data):
    plan = parse_atlas_cohort(cohort_data)
    assert isinstance(plan, AtlasCohortPlan)
    matched_terms = {m.hipaasynth_term for m in plan.matched}
    assert matched_terms == {"congestive_heart_failure", "atrial_fibrillation"}
    # Dementia (4182210) is not modeled -> unmatched.
    assert [u.concept_id for u in plan.unmatched] == [4182210]


def test_primary_criteria_sets_index_condition(cohort_data):
    plan = parse_atlas_cohort(cohort_data)
    # CodesetId 0 is the entry event = heart failure.
    assert plan.primary_codeset_ids == [0]
    assert plan.required_condition == "congestive_heart_failure"
    assert plan.is_generatable


def test_atrial_fibrillation_prefers_allowed_term(cohort_data):
    plan = parse_atlas_cohort(cohort_data)
    afib = [m for m in plan.matched if m.concept_id == 313217][0]
    assert afib.hipaasynth_term == "atrial_fibrillation"  # not "afib"


def test_coverage_summary_mentions_index(cohort_data):
    plan = parse_atlas_cohort(cohort_data)
    summary = plan.coverage_summary()
    assert "2/3" in summary
    assert "congestive_heart_failure" in summary


# ── loading variants ─────────────────────────────────────────────────────────

def test_load_from_path():
    plan = load_atlas_cohort(FIXTURE)
    assert plan.required_condition == "congestive_heart_failure"


def test_load_from_json_string(cohort_data):
    plan = load_atlas_cohort(json.dumps(cohort_data))
    assert plan.required_condition == "congestive_heart_failure"


def test_load_from_webapi_wrapped_expression(cohort_data):
    # ATLAS WebAPI wraps the definition as {"expression": "<json string>"}.
    wrapped = {"name": "wrapped", "expression": json.dumps(cohort_data)}
    plan = load_atlas_cohort(wrapped)
    assert plan.required_condition == "congestive_heart_failure"


# ── config bridge + end-to-end generation ────────────────────────────────────

def test_to_generation_config(cohort_data):
    plan = parse_atlas_cohort(cohort_data)
    cfg = plan.to_generation_config(patient_count=8, seed=7)
    assert isinstance(cfg, GenerationConfig)
    assert cfg.required_condition == "congestive_heart_failure"
    assert cfg.patient_count == 8
    assert cfg.seed == 7


def test_generated_cohort_all_have_index_condition(cohort_data):
    plan = parse_atlas_cohort(cohort_data)
    cfg = plan.to_generation_config(patient_count=10, seed=7)
    patients = generate_patients(cfg)
    assert len(patients) == 10
    for p in patients:
        names = {c.name for c in p.conditions}
        assert "congestive_heart_failure" in names


def test_ungeneratable_cohort_raises():
    # A definition whose only concept is not modeled cannot be generated.
    data = {
        "Name": "Unsupported",
        "ConceptSets": [
            {"id": 0, "name": "Dementia", "expression": {"items": [
                {"concept": {"CONCEPT_ID": 4182210, "CONCEPT_NAME": "Dementia",
                             "DOMAIN_ID": "Condition"}}]}}
        ],
        "PrimaryCriteria": {"CriteriaList": [{"ConditionOccurrence": {"CodesetId": 0}}]},
    }
    plan = parse_atlas_cohort(data)
    assert not plan.is_generatable
    with pytest.raises(ValueError):
        plan.to_generation_config()


def test_empty_definition_is_safe():
    plan = parse_atlas_cohort({})
    assert plan.matched == [] and plan.unmatched == []
    assert plan.required_condition is None
