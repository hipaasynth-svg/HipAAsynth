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

"""Tests for the Seismometer adapter.

These exercise the adapter's contract (schema validation, fail-loud behavior,
deterministic scoring, and the censor audit) without requiring Seismometer
itself to be installed. Skipped if pandas/pyarrow/yaml are unavailable.
"""

import json
import sys
from pathlib import Path

import pytest

pytest.importorskip("pandas")
pytest.importorskip("pyarrow")
pytest.importorskip("yaml")

# The adapter lives under examples/ (outside the pure-stdlib hipaasynth package),
# so make it importable by path.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "examples" / "seismometer"))

from seismometer_adapter import (  # noqa: E402
    CHF_PROFILE,
    COPD_PROFILE,
    OUD_PROFILE,
    PROFILES,
    SchemaMismatchError,
    build_events,
    build_predictions,
    censor_audit,
    derive_outcome,
    derive_score,
    load_canonical,
    run,
)


def _patient(pid, **over):
    base = {
        "patient_id": pid,
        "age": 40,
        "sex": "male",
        "ethnicity": "white",
        "rurality": "frontier",
        "insurance_status": "medicaid",
        "housing_status": "unstable",
        "prior_overdose": False,
        "iv_drug_use": False,
        "fentanyl_exposure_risk": False,
        "uds_benzodiazepine": False,
        "homelessness_unstable_housing": False,
        "naloxone_access": True,
        "moud_current": "buprenorphine",
        "dsm5_criteria_count": 4,
        "distance_to_moud_provider_miles": 20,
        "cows_score": 8,
    }
    base.update(over)
    return base


def _cohort(n, **over):
    import pandas as pd

    return pd.DataFrame([_patient(f"SYN-{i:04d}", **over) for i in range(n)])


class TestLoadAndReconcile:
    def test_json_and_csv_id_mismatch_fails_loud(self, tmp_path):
        pj = tmp_path / "patients.json"
        rc = tmp_path / "results.csv"
        pj.write_text(json.dumps({"module": "oud", "patients": [_patient("A"), _patient("B")]}))
        # csv has a different id set
        import pandas as pd

        pd.DataFrame([_patient("A"), _patient("C")]).to_csv(rc, index=False)
        with pytest.raises(SchemaMismatchError, match="patient_id sets differ"):
            load_canonical(pj, rc)

    def test_both_inputs_empty_fails(self):
        with pytest.raises(SchemaMismatchError):
            load_canonical(None, None)

    def test_missing_required_column_fails_loud(self, tmp_path):
        rc = tmp_path / "results.csv"
        df = _cohort(20).drop(columns=["rurality"])
        df.to_csv(rc, index=False)
        with pytest.raises(SchemaMismatchError, match="missing required columns.*rurality"):
            run(None, rc, tmp_path / "out", module="oud")

    def test_unknown_module_fails_loud(self, tmp_path):
        rc = tmp_path / "results.csv"
        _cohort(20).to_csv(rc, index=False)
        with pytest.raises(SchemaMismatchError, match="No Seismometer profile"):
            run(None, rc, tmp_path / "out", module="diabetes")


class TestScoreAndFrames:
    def test_score_is_deterministic_and_in_unit_interval(self):
        df = _cohort(30, iv_drug_use=True)
        s1 = derive_score(df, OUD_PROFILE)
        s2 = derive_score(df, OUD_PROFILE)
        assert (s1 == s2).all()
        assert s1.between(0.0, 1.0).all()
        assert str(s1.dtype) == "float64"

    def test_higher_risk_factors_raise_score(self):
        low = derive_score(_cohort(1, naloxone_access=True, moud_current="buprenorphine"), OUD_PROFILE).iloc[0]
        high = derive_score(
            _cohort(1, iv_drug_use=True, fentanyl_exposure_risk=True, naloxone_access=False,
                    moud_current="no_moud", homelessness_unstable_housing=True),
            OUD_PROFILE,
        ).iloc[0]
        assert high > low

    def test_predictions_frame_dtypes(self):
        pred = build_predictions(_cohort(10), OUD_PROFILE)
        assert pred["patient_id"].dtype == object
        assert str(pred["PredictTime"].dtype).startswith("datetime64")
        assert str(pred["ModelScore"].dtype) == "float64"
        assert str(pred["age"].dtype) == "int64"

    def test_events_frame_is_binary_long_format(self):
        ev = build_events(_cohort(10, prior_overdose=True), OUD_PROFILE)
        assert set(ev.columns) == {"patient_id", "Type", "EventTime", "Value"}
        assert set(ev["Value"].unique()) <= {0.0, 1.0}
        assert (ev["Type"] == "Overdose").all()


class TestCensorAudit:
    def test_subgroup_survives_strictly_above_threshold(self):
        # 11 frontier patients: 11 > 10 -> survives; 10 would not.
        pred = build_predictions(_cohort(11, rurality="frontier"), OUD_PROFILE)
        audit, dropped = censor_audit(pred, OUD_PROFILE, censor_min_count=10)
        rur = [a for a in audit if a.cohort == "Rurality" and a.subgroup == "frontier"][0]
        assert rur.count == 11 and rur.survives is True

    def test_exactly_threshold_is_censored(self):
        pred = build_predictions(_cohort(10, rurality="frontier"), OUD_PROFILE)
        audit, dropped = censor_audit(pred, OUD_PROFILE, censor_min_count=10)
        rur = [a for a in audit if a.cohort == "Rurality" and a.subgroup == "frontier"][0]
        assert rur.count == 10 and rur.survives is False
        # only one subgroup, none survive -> whole cohort dropped
        assert "Rurality" in dropped


class TestEndToEnd:
    def test_writes_full_package(self, tmp_path):
        rc = tmp_path / "results.csv"
        _cohort(40).to_csv(rc, index=False)
        result = run(None, rc, tmp_path / "pkg", module="oud")
        pkg = result.out_dir
        for name in (
            "config.yml",
            "usage_config.yml",
            "dictionary.yml",
            "predictions.parquet",
            "events.parquet",
            "metadata.json",
        ):
            assert (pkg / name).is_file(), f"missing {name}"
        # metadata is valid json with thresholds
        meta = json.loads((pkg / "metadata.json").read_text())
        assert "thresholds" in meta and "modelname" in meta
        # invented columns are surfaced
        cols = {c["column"] for c in result.invented_columns}
        assert {"PredictTime", "EventTime", "ModelScore", "Value"} <= cols


# --------------------------------------------------------------------------- #
# Multi-module support (oud + chf + copd) and the derived-outcome contract.
# --------------------------------------------------------------------------- #
def _chf_patient(pid, **over):
    base = {
        "patient_id": pid,
        "age": 71,
        "sex": "male",
        "ethnicity": "white",
        "nyha_class": "III",
        "acc_aha_stage": "C",
        "prior_hf_admissions_1yr": 2,
        "ejection_fraction_pct": 30,
        "ntprobnp_pgml": 4000.0,
        "egfr_ml_min_173m2": 60.0,
        "sodium_meql": 138.0,
        "systolic_bp_mmhg": 120.0,
        "cad": True,
        "ckd": False,
        "afib": False,
        "type2_diabetes": False,
    }
    base.update(over)
    return base


def _copd_patient(pid, **over):
    base = {
        "patient_id": pid,
        "age": 73,
        "sex": "female",
        "ethnicity": "white",
        "gold_stage": "GOLD_2",
        "gold_abcd_group": "B",
        "hospitalized_prior_yr": False,
        "fev1_pct_predicted": 64.0,
        "cat_score": 13,
        "mmrc_dyspnea_grade": 3,
        "spo2_pct": 94.0,
        "pack_years": 20.0,
        "six_min_walk_m": 350.0,
        "ltot": False,
        "pulmonary_hypertension": False,
    }
    base.update(over)
    return base


class TestMultiModule:
    def test_supported_modules_all_have_profiles(self):
        # generate_demo_cohort's supported set must stay in lockstep with PROFILES.
        import generate_demo_cohort

        assert set(generate_demo_cohort.SUPPORTED_MODULES) == set(PROFILES)
        assert set(PROFILES) == {"oud", "chf", "copd"}

    def test_no_profile_leaks_its_outcome_into_the_score(self):
        # A profile's score model must never read the outcome column or the columns
        # its outcome is derived from — that would manufacture the ROC.
        for prof in PROFILES.values():
            leak = set(prof.score_model.feature_columns) & (
                {prof.outcome.source} | set(prof.outcome.derived_from)
            )
            assert not leak, f"{prof.name}: score leaks outcome column(s) {leak}"

    def test_copd_native_binary_outcome(self, tmp_path):
        import pandas as pd

        rc = tmp_path / "results.csv"
        rows = [_copd_patient(f"C{i:03d}", hospitalized_prior_yr=(i % 4 == 0)) for i in range(40)]
        pd.DataFrame(rows).to_csv(rc, index=False)
        result = run(None, rc, tmp_path / "pkg", module="copd")
        ev = pd.read_parquet(result.out_dir / "events.parquet")
        assert set(ev["Value"].unique()) <= {0.0, 1.0}
        assert (ev["Type"] == "COPD hospitalization (prior yr)").all()

    def test_chf_derived_outcome_is_binary_and_disclosed(self, tmp_path):
        import pandas as pd

        # Mix of 0 and >=1 admissions -> derived label must be 0/1 with both classes.
        rows = [_chf_patient(f"H{i:03d}", prior_hf_admissions_1yr=(i % 3)) for i in range(30)]
        df = pd.DataFrame(rows)
        derived = derive_outcome(df, CHF_PROFILE)
        assert set(derived.unique()) == {0, 1}
        # i%3 -> 0 admissions for 1/3 of rows -> those are the only zeros
        assert (derived == 0).sum() == sum(1 for i in range(30) if i % 3 == 0)

        rc = tmp_path / "results.csv"
        df.to_csv(rc, index=False)
        result = run(None, rc, tmp_path / "pkg", module="chf")
        value_note = next(c for c in result.invented_columns if c["column"] == "Value")
        assert "DERIVED" in value_note["reason"]
        assert "prior_hf_admissions_1yr" in value_note["reason"]

    def test_derived_outcome_rejects_non_binary_derive(self, tmp_path):
        # A derive() that returns something non-0/1 must fail loud, not silently pass.
        import pandas as pd
        from dataclasses import replace
        from seismometer_adapter import load_canonical, write_package

        bad_profile = replace(
            CHF_PROFILE,
            outcome=replace(CHF_PROFILE.outcome, derive=lambda r: 7),
        )
        rc = tmp_path / "results.csv"
        pd.DataFrame([_chf_patient("H1")]).to_csv(rc, index=False)
        df, _ = load_canonical(None, rc)
        with pytest.raises(SchemaMismatchError, match="non-binary"):
            write_package(df, bad_profile, tmp_path / "pkg2")
