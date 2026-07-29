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

"""OMOP CDM 5.4 completeness (roadmap step 4).

Checks the CDM 5.4 required (NOT NULL) columns are present, that OBSERVATION_PERIOD
is emitted, that fact rows link to visits, that DRUG_EXPOSURE carries the
5.4-required end date, and that no emitted standard concept_id drifts from the
shipped vocabulary map.
"""
import dataclasses

import pytest

from hipaasynth.core.config import GenerationConfig
from hipaasynth.core.schema import Condition, Medication
from hipaasynth.exporters.omop import build_cdm_tables, export_omop
from hipaasynth.pipelines.population_pipeline import generate_patients
from hipaasynth.vocabulary import terms_for_concept_id


@pytest.fixture
def patients():
    return generate_patients(GenerationConfig(patient_count=12, seed=42))


# CDM 5.4 required (NOT NULL) columns per table.
_REQUIRED_54 = {
    "person": {"person_id", "gender_concept_id", "year_of_birth",
               "race_concept_id", "ethnicity_concept_id"},
    "condition_occurrence": {"condition_occurrence_id", "person_id",
                             "condition_concept_id", "condition_start_date",
                             "condition_type_concept_id"},
    "drug_exposure": {"drug_exposure_id", "person_id", "drug_concept_id",
                      "drug_exposure_start_date", "drug_exposure_end_date",
                      "drug_type_concept_id"},
    "measurement": {"measurement_id", "person_id", "measurement_concept_id",
                    "measurement_date", "measurement_type_concept_id"},
    "visit_occurrence": {"visit_occurrence_id", "person_id", "visit_concept_id",
                         "visit_start_date", "visit_end_date",
                         "visit_type_concept_id"},
    "observation_period": {"observation_period_id", "person_id",
                           "observation_period_start_date",
                           "observation_period_end_date",
                           "period_type_concept_id"},
}


def test_observation_period_table_present(patients):
    tables = build_cdm_tables(patients)
    assert "observation_period" in tables
    # One observation period per person that has at least one visit.
    persons_with_visits = [p for p in patients if p.visits]
    assert len(tables["observation_period"]) == len(persons_with_visits)


def test_required_columns_present_all_tables(patients):
    tables = build_cdm_tables(patients)
    p = dataclasses.replace(patients[0], medications=[Medication(name="statin")])
    tables = build_cdm_tables([p] + list(patients[1:]))
    for table, required in _REQUIRED_54.items():
        rows = tables[table]
        assert rows, f"{table} unexpectedly empty"
        cols = set(rows[0].keys())
        missing = required - cols
        assert not missing, f"{table} missing required CDM 5.4 columns: {missing}"


def test_observation_period_dates_ordered_and_ref_person(patients):
    tables = build_cdm_tables(patients)
    person_ids = {r["person_id"] for r in tables["person"]}
    for row in tables["observation_period"]:
        assert row["person_id"] in person_ids
        assert row["observation_period_start_date"] <= row["observation_period_end_date"]
        assert int(row["period_type_concept_id"]) != 0


def test_drug_exposure_has_end_date(patients):
    p = dataclasses.replace(patients[0], medications=[Medication(name="statin")])
    tables = build_cdm_tables([p])
    drug = tables["drug_exposure"][0]
    # 5.4 requires drug_exposure_end_date NOT NULL; we default it to the start date.
    assert drug["drug_exposure_end_date"]
    assert drug["drug_exposure_end_date"] == drug["drug_exposure_start_date"]


def test_measurement_links_to_visit_and_parses_range(patients):
    tables = build_cdm_tables(patients)
    visit_ids = {r["visit_occurrence_id"] for r in tables["visit_occurrence"]}
    linked = [m for m in tables["measurement"] if m.get("visit_occurrence_id")]
    assert linked, "expected measurements linked to a visit"
    for m in linked:
        assert m["visit_occurrence_id"] in visit_ids
    # At least one measurement with a "low-high" reference range parses into
    # numeric range_low/range_high (e.g. Glucose 70-99).
    parsed = [m for m in tables["measurement"]
              if m.get("range_low") not in (None, "") and m.get("range_high") not in (None, "")]
    assert parsed, "expected at least one parsed numeric reference range"
    for m in parsed:
        assert float(m["range_low"]) <= float(m["range_high"])


def test_condition_links_to_visit(patients):
    tables = build_cdm_tables(patients)
    visit_ids = {r["visit_occurrence_id"] for r in tables["visit_occurrence"]}
    linked = [c for c in tables["condition_occurrence"] if c.get("visit_occurrence_id")]
    assert linked
    for c in linked:
        assert c["visit_occurrence_id"] in visit_ids


def test_person_preserves_source_race_ethnicity(patients):
    tables = build_cdm_tables(patients)
    # HipAAsynth's single demographics.ethnicity string must not be dropped — it
    # is preserved in race_source_value for traceability.
    src = {p.demographics.patient_id: p.demographics.ethnicity for p in patients}
    for row in tables["person"]:
        assert row["race_source_value"] == src[row["person_source_value"]]


def test_condition_status_concept_id_reflects_active(patients):
    """condition_status_concept_id must be driven by Condition.active, not a
    hardcoded 0. An active vs. inactive condition get distinct, non-zero ids and
    the corresponding source_value.
    """
    p = dataclasses.replace(
        patients[0],
        conditions=[
            Condition(name="type_2_diabetes", onset_age=50, active=True),
            Condition(name="type_2_diabetes", onset_age=50, active=False),
        ],
    )
    tables = build_cdm_tables([p])
    rows = tables["condition_occurrence"]
    assert len(rows) == 2
    active_row, inactive_row = rows[0], rows[1]
    # Non-zero and distinct.
    assert active_row["condition_status_concept_id"] != 0
    assert inactive_row["condition_status_concept_id"] != 0
    assert (active_row["condition_status_concept_id"]
            != inactive_row["condition_status_concept_id"])
    # Source values carry the human-readable status for offline re-resolution.
    assert active_row["condition_status_source_value"] == "active"
    assert inactive_row["condition_status_source_value"] == "inactive"


def test_no_concept_id_drift_from_vocabulary(patients):
    """Every non-zero standard concept_id emitted must exist in the vocabulary map.

    Guards against the OMOP export drifting from the validated concept_map.json
    (PRs #75–#79).
    """
    p = dataclasses.replace(patients[0], medications=[Medication(name="statin")])
    tables = build_cdm_tables([p] + list(patients[1:]))
    concept_cols = {
        "condition_occurrence": "condition_concept_id",
        "measurement": "measurement_concept_id",
        "visit_occurrence": "visit_concept_id",
        "drug_exposure": "drug_concept_id",
    }
    for table, col in concept_cols.items():
        for row in tables[table]:
            cid = int(row[col])
            if cid != 0:
                assert terms_for_concept_id(cid), (
                    f"{table}.{col}={cid} not found in concept_map.json (drift)"
                )


def test_export_writes_observation_period_csv(patients, tmp_path):
    counts = export_omop(patients, str(tmp_path / "omop_cdm"))
    assert "observation_period" in counts
    assert (tmp_path / "omop_cdm" / "observation_period.csv").exists()
