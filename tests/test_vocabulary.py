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

"""Tests for the OHDSI/OMOP vocabulary layer and OMOP CDM exporter."""

import csv

import pytest

from hipaasynth.core.config import GenerationConfig
from hipaasynth.pipelines.population_pipeline import generate_patients
from hipaasynth.core.schema import Medication
from hipaasynth.vocabulary import (
    lookup_condition,
    lookup_measurement,
    lookup_medication,
    lookup_visit,
    unmapped_terms,
)
from hipaasynth.exporters.exporters import export_fhir
from hipaasynth.exporters.omop import build_cdm_tables, export_omop

# Terms the base pipeline can emit (generator_conditions.py / generator_numerics.py).
PIPELINE_CONDITIONS = [
    "congestive_heart_failure", "hypertension", "type2_diabetes",
    "chronic_kidney_disease", "atrial_fibrillation", "copd",
    "coronary_artery_disease", "depression", "asthma", "hyperlipidemia",
]
PIPELINE_MEASUREMENTS = ["Glucose", "Creatinine", "LDL", "WBC"]
PIPELINE_VISITS = ["outpatient", "urgent_care", "telehealth", "routine_check"]
# The CHF module medication set.
CHF_MEDICATIONS = [
    "acei_arb_arni", "beta_blocker", "mra", "sglt2i", "loop_diuretic",
    "digoxin", "hydralazine_nitrate", "ivabradine", "anticoagulant",
    "statin", "aspirin",
]
# Medication terms emitted by the other disease modules (COPD, OUD, diabetes,
# cardiology, SMA). Every one must resolve to an ATC/RxNorm concept.
MODULE_MEDICATIONS = [
    # COPD
    "saba_prn", "laba", "lama", "ics_laba", "triple_therapy",
    "oral_corticosteroid", "roflumilast",
    # OUD (MOUD treatments; "no_moud" is the absence of treatment, not a drug)
    "buprenorphine", "methadone_otp", "naltrexone_oral", "naltrexone_xr_im",
    # diabetes
    "metformin", "sulfonylurea", "dpp4_inhibitor", "glp1_agonist",
    "sglt2_inhibitor", "insulin",
    # cardiology
    "thiazide", "ace_inhibitor", "arb", "ccb",
    # SMA disease-modifying therapies
    "nusinersen", "risdiplam", "onasemnogene",
]


@pytest.fixture
def patients():
    return generate_patients(GenerationConfig(patient_count=5, seed=42))


# ── Vocabulary coverage ──────────────────────────────────────────────────────

def test_all_pipeline_terms_are_mapped():
    """Every term the base pipeline emits must resolve to a standard concept."""
    gaps = unmapped_terms(
        conditions=PIPELINE_CONDITIONS,
        measurements=PIPELINE_MEASUREMENTS,
        visits=PIPELINE_VISITS,
        medications=CHF_MEDICATIONS,
    )
    assert gaps == {"conditions": [], "measurements": [], "visits": [], "medications": []}, gaps


def test_all_module_medications_are_mapped():
    """Every medication term the disease modules emit must resolve."""
    gaps = unmapped_terms(medications=CHF_MEDICATIONS + MODULE_MEDICATIONS)
    assert gaps["medications"] == [], gaps["medications"]


def test_copd_and_oud_and_sma_medication_shapes():
    # COPD combination-inhaler class.
    assert lookup_medication("triple_therapy").atc == "R03AL"
    # OUD MOUD ingredient.
    assert lookup_medication("buprenorphine").rxnorm == "1819"
    # naltrexone oral and XR share the same ingredient code, different formulation.
    assert lookup_medication("naltrexone_oral").rxnorm == lookup_medication("naltrexone_xr_im").rxnorm
    # SMA disease-modifying therapy.
    assert lookup_medication("nusinersen").concept_type == "rxnorm_ingredient"


def test_medication_classes_map_to_atc():
    m = lookup_medication("beta_blocker")
    assert m is not None
    assert m.concept_type == "atc_class"
    assert m.atc == "C07"
    # concept_id is intentionally null until ATHENA validation resolves it.
    assert m.omop_concept_id is None


def test_medication_single_agent_maps_to_rxnorm():
    m = lookup_medication("digoxin")
    assert m.concept_type == "rxnorm_ingredient"
    assert m.rxnorm == "3407"


def test_medication_combination_carries_components():
    m = lookup_medication("hydralazine_nitrate")
    assert m.concept_type == "combination"
    codes = {c["rxnorm"] for c in m.components}
    assert codes == {"5470", "6058"}


def test_medication_fhir_coding_uses_rxnorm_or_atc():
    atc = lookup_medication("statin").fhir_coding()
    assert any(c["system"] == "http://www.whocc.no/atc" for c in atc)
    rx = lookup_medication("aspirin").fhir_coding()
    assert any(c["system"] == "http://www.nlm.nih.gov/research/umls/rxnorm" for c in rx)


def test_condition_lookup_is_case_insensitive():
    a = lookup_condition("congestive_heart_failure")
    b = lookup_condition("CONGESTIVE_HEART_FAILURE")
    assert a is not None and b is not None
    assert a.omop_concept_id == b.omop_concept_id == 316139
    assert a.snomed_code == "42343007"


def test_measurement_lookup_carries_loinc():
    m = lookup_measurement("Glucose")
    assert m is not None
    assert m.loinc == "2345-7"
    assert m.omop_concept_id == 3004501


def test_visit_lookup_maps_to_omop_concept():
    assert lookup_visit("telehealth").omop_concept_id == 5083
    assert lookup_visit("outpatient").omop_concept_id == 9202


def test_unmapped_term_returns_none():
    assert lookup_condition("definitely_not_a_real_term") is None


def test_fhir_coding_shape():
    coding = lookup_condition("hypertension").fhir_coding()
    systems = {c["system"] for c in coding}
    assert "http://snomed.info/sct" in systems
    assert "http://hl7.org/fhir/sid/icd-10-cm" in systems


# ── FHIR exporter integration ────────────────────────────────────────────────

def test_fhir_export_attaches_codings(patients, tmp_path):
    import json
    path = tmp_path / "bundle.json"
    export_fhir(patients, str(path))
    bundle = json.loads(path.read_text())
    conditions = [
        e["resource"] for e in bundle["entry"]
        if e["resource"]["resourceType"] == "Condition"
    ]
    assert conditions, "expected at least one Condition resource"
    # At least one condition must now carry a standard coding (not text-only).
    coded = [c for c in conditions if c["code"].get("coding")]
    assert coded, "no Condition carried a standard coding after vocabulary wiring"
    snomed = coded[0]["code"]["coding"][0]
    assert snomed["system"] == "http://snomed.info/sct"
    assert snomed["code"]


# ── OMOP CDM exporter ────────────────────────────────────────────────────────

def test_build_cdm_tables_structure(patients):
    tables = build_cdm_tables(patients)
    assert set(tables) == {
        "person", "condition_occurrence", "visit_occurrence", "measurement",
        "drug_exposure",
    }
    assert len(tables["person"]) == len(patients)
    # person_ids are unique sequential surrogate keys.
    ids = [r["person_id"] for r in tables["person"]]
    assert ids == list(range(1, len(patients) + 1))


def test_cdm_gender_concept_ids(patients):
    tables = build_cdm_tables(patients)
    valid = {8507, 8532, 0}
    assert all(r["gender_concept_id"] in valid for r in tables["person"])


def test_cdm_conditions_reference_persons(patients):
    tables = build_cdm_tables(patients)
    person_ids = {r["person_id"] for r in tables["person"]}
    for row in tables["condition_occurrence"]:
        assert row["person_id"] in person_ids
        # Standard concept or explicit 0 (no drop), plus preserved source value.
        assert isinstance(row["condition_concept_id"], int)
        assert row["condition_source_value"]


def test_drug_exposure_empty_when_no_medications(patients):
    # Base-pipeline patients carry no medications, so no drug rows are emitted.
    tables = build_cdm_tables(patients)
    assert tables["drug_exposure"] == []


def test_drug_exposure_from_medications(patients):
    import dataclasses
    p = dataclasses.replace(patients[0], medications=[
        Medication(name="beta_blocker"),   # ATC class -> concept_id 0, source kept
        Medication(name="digoxin"),        # RxNorm ingredient
    ])
    tables = build_cdm_tables([p])
    drugs = tables["drug_exposure"]
    assert len(drugs) == 2
    sources = {d["drug_source_value"] for d in drugs}
    assert sources == {"beta_blocker", "digoxin"}
    # concept_ids are null in the map until ATHENA validation, so exporter emits 0.
    assert all(d["drug_concept_id"] == 0 for d in drugs)
    assert all(d["person_id"] == 1 for d in drugs)


def test_fhir_medication_statement(patients, tmp_path):
    import dataclasses, json
    p = dataclasses.replace(patients[0], medications=[Medication(name="statin")])
    path = tmp_path / "bundle.json"
    export_fhir([p], str(path))
    bundle = json.loads(path.read_text())
    meds = [e["resource"] for e in bundle["entry"]
            if e["resource"]["resourceType"] == "MedicationStatement"]
    assert len(meds) == 1
    coding = meds[0]["medication"]["concept"]["coding"]
    assert any(c["system"] == "http://www.whocc.no/atc" for c in coding)


def test_export_omop_writes_valid_csvs(patients, tmp_path):
    counts = export_omop(patients, str(tmp_path / "omop_cdm"))
    out = tmp_path / "omop_cdm"
    for table in ("person", "condition_occurrence", "visit_occurrence", "measurement",
                  "drug_exposure"):
        path = out / f"{table}.csv"
        assert path.exists()
        with open(path, newline="") as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == counts[table]


def test_export_omop_fails_loud_on_io_error(patients, tmp_path):
    # Point the output dir at an existing *file* so mkdir under it fails.
    occupied = tmp_path / "occupied"
    occupied.write_text("x")
    with pytest.raises((RuntimeError, OSError, NotADirectoryError, FileExistsError)):
        export_omop(patients, str(occupied / "sub"))
