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

"""Tests for the ACHILLES/DQD-style OMOP CDM audit adapter."""

import dataclasses

import pytest

from hipaasynth.core.config import GenerationConfig
from hipaasynth.core.schema import Medication
from hipaasynth.pipelines.population_pipeline import generate_patients
from hipaasynth.exporters.omop import build_cdm_tables, export_omop
from hipaasynth.ohdsi.cdm_audit import (
    audit_cdm,
    characterize,
    load_cdm_dir,
    render_markdown,
    run_dq_checks,
    main,
)


@pytest.fixture
def patients():
    return generate_patients(GenerationConfig(patient_count=25, seed=42))


@pytest.fixture
def tables(patients):
    return build_cdm_tables(patients)


# ── data-quality checks ──────────────────────────────────────────────────────

def test_clean_cohort_passes_all_checks(tables):
    report = audit_cdm(tables)
    failed = [c for c in report["data_quality"]["checks"] if c["status"] == "FAIL"]
    assert failed == [], failed
    assert report["passed"] is True


def test_checks_cover_all_three_categories(tables):
    cats = {c.category for c in run_dq_checks(tables)}
    assert cats == {"Conformance", "Completeness", "Plausibility"}


def test_detects_broken_foreign_key(tables):
    broken = {k: [dict(r) for r in v] for k, v in tables.items()}
    broken["condition_occurrence"][0]["person_id"] = 999999  # dangling FK
    checks = run_dq_checks(broken)
    fk = [c for c in checks if c.name == "condition_occurrence_person_fk"][0]
    assert fk.status == "FAIL"


def test_detects_implausible_birth_year(tables):
    broken = {k: [dict(r) for r in v] for k, v in tables.items()}
    broken["person"][0]["year_of_birth"] = 1700
    checks = run_dq_checks(broken)
    yob = [c for c in checks if c.name == "year_of_birth_plausible"][0]
    assert yob.status == "FAIL"


def test_detects_invalid_gender(tables):
    broken = {k: [dict(r) for r in v] for k, v in tables.items()}
    broken["person"][0]["gender_concept_id"] = 42
    checks = run_dq_checks(broken)
    g = [c for c in checks if c.name == "gender_concept_id_valid"][0]
    assert g.status == "FAIL"


def test_unmapped_drug_class_does_not_fail_condition_mapping(patients):
    # ATC-class drugs carry concept_id 0 by design; that must not flunk the
    # condition/measurement mapping checks (drugs have no mapping check here).
    p = dataclasses.replace(patients[0], medications=[Medication(name="beta_blocker")])
    tables = build_cdm_tables([p] + list(patients[1:]))
    report = audit_cdm(tables)
    assert report["passed"] is True


# ── characterization ─────────────────────────────────────────────────────────

def test_characterization_shape(tables, patients):
    ch = characterize(tables)
    assert ch["person_count"] == len(patients)
    assert set(ch["gender_distribution"]) <= {"Male", "Female", "Unknown/Other"}
    assert ch["record_counts"]["person"] == len(patients)
    # Every base-pipeline patient has at least one condition, so top_conditions
    # is populated.
    assert ch["top_conditions"]


def test_measurement_summary_has_stats(tables):
    ch = characterize(tables)
    for _lab, summ in ch["measurement_summary"].items():
        assert summ["n"] >= 1
        assert summ["min"] <= summ["mean"] <= summ["max"]


# ── loading from CSV dir + CLI + markdown ────────────────────────────────────

def test_audit_from_exported_dir(patients, tmp_path):
    out = tmp_path / "omop_cdm"
    export_omop(patients, str(out))
    loaded = load_cdm_dir(out)
    assert loaded["person"]  # non-empty
    report = audit_cdm(out)   # accepts a path directly
    assert report["passed"] is True


def test_render_markdown_contains_verdict(tables):
    md = render_markdown(audit_cdm(tables))
    assert "OMOP CDM Audit" in md
    assert "Data-quality verdict" in md
    assert "Characterization" in md


def test_cli_returns_zero_on_clean_cohort(patients, tmp_path):
    out = tmp_path / "omop_cdm"
    export_omop(patients, str(out))
    md = tmp_path / "audit.md"
    rc = main(["--omop-dir", str(out), "--out", str(md)])
    assert rc == 0
    assert md.exists() and "verdict" in md.read_text()


def test_cli_missing_dir_returns_two(tmp_path):
    assert main(["--omop-dir", str(tmp_path / "nope")]) == 2
