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

"""
seismometer_adapter — bridge HipAAsynth cohorts into Epic's Seismometer.

Seismometer (https://github.com/epic-open-source/seismometer) is Epic's
open-source AI-evaluation toolkit. Its loader expects, in a single ``config``
directory:

* ``predictions.parquet`` — one row per prediction: an entity-id key, a
  ``predict_time`` timestamp column, the model score column, and any cohort
  attribute columns.
* ``events.parquet`` — long-format outcomes: entity-id key + ``Type`` /
  ``EventTime`` / ``Value`` columns (names configurable).
* ``usage_config.yml`` (top-level key ``data_usage``) — declares the entity id,
  primary output (score) column, predict-time column, cohorts, the target
  event, and ``censor_min_count``.
* ``dictionary.yml`` — column dictionaries for predictions and events.
* ``config.yml`` (top-level key ``other_info``) — points at all of the above.
* ``metadata.json`` — model name + score thresholds (Seismometer opens this
  unconditionally at startup).

This module reads HipAAsynth's canonical ``patients.json`` + ``results.csv`` and
emits every one of those artifacts, dtype-correct, so that
``seismometer.run_startup(config_path=<out_dir>)`` renders fairness / ROC /
calibration plots without hand-editing.

Design commitments (see README in examples/seismometer):

* **Fail loud.** Any required column missing, or any patient-id mismatch between
  the JSON and CSV inputs, raises :class:`SchemaMismatchError` with the exact
  offending columns/ids. No silent coercion, no quiet column invention.
* **Explicit about invention.** HipAAsynth is a *data generator*: it emits
  neither a model score nor a prediction timestamp. Seismometer requires both.
  Every column this adapter has to synthesize is recorded on
  :class:`AdapterResult.invented_columns` and printed by the CLI.
* **Censoring is surfaced, not hidden.** :func:`censor_audit` reproduces
  Seismometer's own ``value_counts() > censor_min_count`` gate (see
  ``seismogram.Seismogram.create_cohorts``) and reports, per cohort subgroup,
  whether it survives the default fairness audit.
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

logger = logging.getLogger("seismometer_adapter")

# Fixed synthetic reference instant. HipAAsynth records are point-in-time
# snapshots with no event chronology, so every prediction and its paired outcome
# share one deterministic timestamp. This is enough for Seismometer's merge
# (entity is unique per row) while being obviously synthetic.
_REFERENCE_TIME = "2026-01-01T00:00:00"


class SchemaMismatchError(Exception):
    """Raised when canonical inputs do not satisfy the adapter's contract.

    Carries a human-readable message naming the exact columns or ids at fault so
    a caller sees *where* it broke rather than a downstream pandas/pyarrow error.
    """


# --------------------------------------------------------------------------- #
# Profiles
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class CohortSpec:
    """One cohort attribute to expose to Seismometer's fairness selectors."""

    source: str
    display_name: str
    dtype: str  # pandas dtype written into the dictionary / parquet
    splits: Optional[list[Any]] = None  # inner edges for numeric bucketing
    definition: str = ""


@dataclass(frozen=True)
class ScoreModel:
    """A transparent, deterministic risk score over *real* clinical features.

    This is **not** a HipAAsynth engine output — HipAAsynth emits no score. It is
    an auditable illustrative model so Seismometer has something to evaluate. The
    outcome field is deliberately excluded from ``terms`` so there is no label
    leakage: the ROC it produces is honest, not manufactured.

    score = sigmoid(intercept + sum_i term_i(row))
    """

    intercept: float
    # each term: (label, callable(row)->float contribution in log-odds)
    terms: list[tuple[str, Callable[[dict], float]]]
    feature_columns: list[str]  # source columns the terms read (for validation)


@dataclass(frozen=True)
class OutcomeSpec:
    """The binary clinical outcome mapped onto a Seismometer target event.

    Two forms:
      * **Native binary** — ``source`` names a boolean/0-1 column that already
        exists in the canonical data (e.g. OUD ``prior_overdose``, COPD
        ``hospitalized_prior_yr``). ``derive`` stays ``None``.
      * **Honestly derived** — a module has no native binary event, only a real
        count or score. Set ``derive`` to a ``row -> 0/1`` callable that
        binarizes existing *real* data (e.g. CHF: ``prior_hf_admissions_1yr >=
        1``). This is a documented binarization of real data, **not** a
        fabricated label — it is stamped onto ``invented_columns`` so the report
        never presents it as a HipAAsynth-emitted event. ``derived_from`` lists
        the columns the callable reads, so validation can require they exist.
    """

    source: str  # boolean/0-1 column, OR the primary column a derive() reads
    display_name: str  # Seismometer event display name (== primary_target)
    definition: str = ""
    derive: Optional[Callable[[dict], Any]] = None  # row -> truthy/0-1 when set
    derived_from: tuple[str, ...] = ()  # extra source columns derive() reads


@dataclass(frozen=True)
class ModuleProfile:
    """Everything module-specific needed to build a Seismometer package."""

    name: str
    entity_id: str
    cohorts: list[CohortSpec]
    outcome: OutcomeSpec
    score_model: ScoreModel
    predict_time_col: str = "PredictTime"
    score_col: str = "ModelScore"
    score_definition: str = ""


def _b(v: Any) -> bool:
    """Coerce a canonical truthy/booleanish value without silent surprises."""
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return v != 0
    if isinstance(v, str):
        return v.strip().lower() in {"true", "t", "1", "yes", "y"}
    return bool(v)


def _num(v: Any, default: float = 0.0) -> float:
    try:
        if v is None or (isinstance(v, float) and math.isnan(v)):
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


# --- OUD profile ----------------------------------------------------------- #
# Overdose-risk log-odds model. Weights are hand-set clinical priors, NOT fit to
# the data, and deliberately avoid the outcome (`prior_overdose`) and its direct
# proxies (`prior_overdose_count`, `prior_od_naloxone_reversed`, `ed_visits`).
_OUD_SCORE = ScoreModel(
    intercept=-1.0,
    terms=[
        ("iv_drug_use", lambda r: 0.9 * _b(r.get("iv_drug_use"))),
        ("fentanyl_exposure_risk", lambda r: 0.8 * _b(r.get("fentanyl_exposure_risk"))),
        ("uds_benzodiazepine(polysubstance)", lambda r: 0.5 * _b(r.get("uds_benzodiazepine"))),
        ("homelessness_unstable_housing", lambda r: 0.5 * _b(r.get("homelessness_unstable_housing"))),
        ("naloxone_access(protective)", lambda r: -0.7 * _b(r.get("naloxone_access"))),
        ("on_moud(protective)", lambda r: -0.6 * (str(r.get("moud_current", "no_moud")) != "no_moud")),
        ("dsm5_criteria_count", lambda r: 0.12 * (_num(r.get("dsm5_criteria_count"), 4) - 4)),
        ("distance_to_moud_provider_miles", lambda r: 0.004 * (_num(r.get("distance_to_moud_provider_miles"), 20) - 20)),
        ("cows_score", lambda r: 0.03 * (_num(r.get("cows_score"), 8) - 8)),
    ],
    feature_columns=[
        "iv_drug_use",
        "fentanyl_exposure_risk",
        "uds_benzodiazepine",
        "homelessness_unstable_housing",
        "naloxone_access",
        "moud_current",
        "dsm5_criteria_count",
        "distance_to_moud_provider_miles",
        "cows_score",
    ],
)

OUD_PROFILE = ModuleProfile(
    name="oud",
    entity_id="patient_id",
    cohorts=[
        CohortSpec("age", "Age", "int", splits=[35, 55], definition="Patient age in years."),
        CohortSpec("sex", "Sex", "object", definition="Recorded sex."),
        CohortSpec("ethnicity", "Race", "object", definition="Race / ethnicity category."),
        CohortSpec(
            "rurality",
            "Rurality",
            "object",
            definition="RUCA-style rurality band (urban/suburban/rural/frontier); the sparse-population axis this audit targets.",
        ),
        CohortSpec("insurance_status", "Insurance", "object", definition="Payer / insurance status."),
        CohortSpec("housing_status", "Housing", "object", definition="Housing stability status."),
    ],
    outcome=OutcomeSpec(
        source="prior_overdose",
        display_name="Overdose",
        definition="Documented prior overdose event (binary clinical outcome used as the evaluation label).",
    ),
    score_model=_OUD_SCORE,
    score_definition="Illustrative overdose-risk score in [0,1] derived from clinical risk factors (adapter-synthesized; HipAAsynth emits no model score).",
)

# --- CHF profile ----------------------------------------------------------- #
# Heart-failure severity log-odds model. CHF emits NO native binary event — only
# a readmission risk *score* and admission *counts* — so the outcome is honestly
# DERIVED (>=1 HF admission in the prior year). The score deliberately avoids
# every admission/readmission column (`prior_hf_admissions_1yr`,
# `prior_any_admissions_1yr`, `readmission_risk_30d`) so there is no leakage from
# the derived label into the score.
_CHF_SCORE = ScoreModel(
    intercept=-0.5,
    terms=[
        ("low_ejection_fraction", lambda r: -0.04 * (_num(r.get("ejection_fraction_pct"), 40) - 40)),
        ("ntprobnp_elevated", lambda r: 0.00003 * (_num(r.get("ntprobnp_pgml"), 1000) - 1000)),
        ("low_egfr", lambda r: -0.010 * (_num(r.get("egfr_ml_min_173m2"), 60) - 60)),
        ("hyponatremia", lambda r: -0.05 * (_num(r.get("sodium_meql"), 138) - 138)),
        ("low_systolic_bp", lambda r: -0.008 * (_num(r.get("systolic_bp_mmhg"), 120) - 120)),
        ("cad", lambda r: 0.3 * _b(r.get("cad"))),
        ("ckd", lambda r: 0.3 * _b(r.get("ckd"))),
        ("afib", lambda r: 0.3 * _b(r.get("afib"))),
        ("type2_diabetes", lambda r: 0.2 * _b(r.get("type2_diabetes"))),
    ],
    feature_columns=[
        "ejection_fraction_pct",
        "ntprobnp_pgml",
        "egfr_ml_min_173m2",
        "sodium_meql",
        "systolic_bp_mmhg",
        "cad",
        "ckd",
        "afib",
        "type2_diabetes",
    ],
)

CHF_PROFILE = ModuleProfile(
    name="chf",
    entity_id="patient_id",
    cohorts=[
        CohortSpec("age", "Age", "int", splits=[55, 75], definition="Patient age in years."),
        CohortSpec("sex", "Sex", "object", definition="Recorded sex."),
        CohortSpec("ethnicity", "Race", "object", definition="Race / ethnicity category."),
        CohortSpec("nyha_class", "NYHA class", "object", definition="NYHA functional class (I–IV)."),
        CohortSpec("acc_aha_stage", "ACC/AHA stage", "object", definition="ACC/AHA heart-failure stage (A–D)."),
    ],
    outcome=OutcomeSpec(
        source="prior_hf_admissions_1yr",
        display_name="HF admission (prior yr)",
        definition="Derived binary: ≥1 heart-failure admission in the prior year (from prior_hf_admissions_1yr).",
        derive=lambda r: 1 if _num(r.get("prior_hf_admissions_1yr"), 0) >= 1 else 0,
        derived_from=("prior_hf_admissions_1yr",),
    ),
    score_model=_CHF_SCORE,
    score_definition="Illustrative HF-severity score in [0,1] from EF, natriuretic peptides, renal function, sodium, BP, and comorbidities (adapter-synthesized; excludes all admission columns — no label leakage).",
)


# --- COPD profile ---------------------------------------------------------- #
# COPD *does* emit a native binary outcome (`hospitalized_prior_yr`). The score
# excludes the three admission/exacerbation proxies (`hospitalized_prior_yr`,
# `icu_admit_prior_yr`, `exacerbations_prior_yr`) to keep the ROC honest.
_COPD_SCORE = ScoreModel(
    intercept=-1.0,
    terms=[
        ("low_fev1_pct_predicted", lambda r: -0.03 * (_num(r.get("fev1_pct_predicted"), 60) - 60)),
        ("high_cat_score", lambda r: 0.04 * (_num(r.get("cat_score"), 10) - 10)),
        ("high_mmrc_dyspnea", lambda r: 0.25 * (_num(r.get("mmrc_dyspnea_grade"), 2) - 2)),
        ("low_spo2", lambda r: -0.06 * (_num(r.get("spo2_pct"), 94) - 94)),
        ("pack_years", lambda r: 0.008 * (_num(r.get("pack_years"), 20) - 20)),
        ("low_six_min_walk", lambda r: -0.002 * (_num(r.get("six_min_walk_m"), 350) - 350)),
        ("on_long_term_oxygen", lambda r: 0.6 * _b(r.get("ltot"))),
        ("pulmonary_hypertension", lambda r: 0.4 * _b(r.get("pulmonary_hypertension"))),
    ],
    feature_columns=[
        "fev1_pct_predicted",
        "cat_score",
        "mmrc_dyspnea_grade",
        "spo2_pct",
        "pack_years",
        "six_min_walk_m",
        "ltot",
        "pulmonary_hypertension",
    ],
)

COPD_PROFILE = ModuleProfile(
    name="copd",
    entity_id="patient_id",
    cohorts=[
        CohortSpec("age", "Age", "int", splits=[55, 70], definition="Patient age in years."),
        CohortSpec("sex", "Sex", "object", definition="Recorded sex."),
        CohortSpec("ethnicity", "Race", "object", definition="Race / ethnicity category."),
        CohortSpec("gold_stage", "GOLD stage", "object", definition="GOLD spirometric stage (1–4)."),
        CohortSpec("gold_abcd_group", "GOLD ABCD", "object", definition="GOLD ABCD symptom/risk group."),
    ],
    outcome=OutcomeSpec(
        source="hospitalized_prior_yr",
        display_name="COPD hospitalization (prior yr)",
        definition="Native binary: any COPD-related hospitalization in the prior year.",
    ),
    score_model=_COPD_SCORE,
    score_definition="Illustrative COPD-severity score in [0,1] from spirometry, symptom burden (CAT/mMRC), oxygenation, smoking, and exercise capacity (adapter-synthesized; excludes admission/exacerbation columns — no label leakage).",
)


# --- DMD profile ----------------------------------------------------------- #
# Duchenne is X-linked, so the cohort is all-male: `sex` is a degenerate axis and
# is intentionally omitted. Fairness axes are clinical/genetic instead of the
# demographic ones OUD carries. Outcome: loss of ambulation (native boolean). The
# score avoids `non_ambulatory` and its direct proxy `ambulation_loss_age`.
_DMD_SCORE = ScoreModel(
    intercept=-2.0,
    terms=[
        ("current_age", lambda r: 0.18 * (_num(r.get("current_age"), 10) - 10)),
        ("disease_duration", lambda r: 0.12 * (_num(r.get("disease_duration"), 6) - 6)),
        ("cardiomyopathy", lambda r: 0.5 * _b(r.get("cardiomyopathy"))),
        ("ck_level", lambda r: 0.00003 * (_num(r.get("ck_level"), 10000) - 10000)),
    ],
    feature_columns=["current_age", "disease_duration", "cardiomyopathy", "ck_level"],
)

DMD_PROFILE = ModuleProfile(
    name="dmd",
    entity_id="patient_id",
    cohorts=[
        CohortSpec("current_age", "Age", "int", splits=[8, 15], definition="Current patient age in years."),
        CohortSpec("mutation_type", "Mutation type", "object", definition="Dystrophin mutation class (deletion/duplication/point)."),
        CohortSpec("on_steroids", "On steroids", "object", definition="Corticosteroid treatment status (treatment-access axis)."),
    ],
    outcome=OutcomeSpec(
        source="non_ambulatory",
        display_name="Loss of ambulation",
        definition="Native binary: patient is non-ambulatory.",
    ),
    score_model=_DMD_SCORE,
    score_definition="Illustrative DMD-progression score in [0,1] from age, disease duration, cardiomyopathy, and CK (adapter-synthesized; excludes ambulation columns — no label leakage).",
)


# --- Fabry profile --------------------------------------------------------- #
# Fabry affects both sexes (X-linked, but heterozygous females are symptomatic),
# so `sex` is a real axis. Outcome: progression to ESRD (native boolean). The
# score avoids `progressed_to_esrd` and its proxy `age_esrd_onset_years`.
_FABRY_SCORE = ScoreModel(
    intercept=-1.5,
    terms=[
        ("low_enzyme_activity", lambda r: -0.02 * (_num(r.get("alpha_galactosidase_a_percent_normal"), 40) - 40)),
        ("high_lyso_gb3", lambda r: 0.004 * (_num(r.get("lyso_gb3_ng_ml"), 50) - 50)),
        ("has_proteinuria", lambda r: 0.8 * _b(r.get("has_proteinuria"))),
        ("has_lvh", lambda r: 0.4 * _b(r.get("has_left_ventricular_hypertrophy"))),
        ("on_ert(protective)", lambda r: -0.4 * _b(r.get("on_enzyme_replacement_therapy"))),
    ],
    feature_columns=[
        "alpha_galactosidase_a_percent_normal",
        "lyso_gb3_ng_ml",
        "has_proteinuria",
        "has_left_ventricular_hypertrophy",
        "on_enzyme_replacement_therapy",
    ],
)

FABRY_PROFILE = ModuleProfile(
    name="fabry",
    entity_id="patient_id",
    cohorts=[
        CohortSpec("sex", "Sex", "object", definition="Recorded sex (Fabry affects both)."),
        CohortSpec("age_at_diagnosis_years", "Age at diagnosis", "int", splits=[18, 40], definition="Age at Fabry diagnosis in years."),
        CohortSpec("phenotype", "Phenotype", "object", definition="Clinical phenotype (classic/late-onset/asymptomatic)."),
        CohortSpec("mutation_type", "Mutation type", "object", definition="GLA mutation class."),
    ],
    outcome=OutcomeSpec(
        source="progressed_to_esrd",
        display_name="Progression to ESRD",
        definition="Native binary: progressed to end-stage renal disease.",
    ),
    score_model=_FABRY_SCORE,
    score_definition="Illustrative Fabry-severity score in [0,1] from enzyme activity, lyso-Gb3, proteinuria, LVH, and ERT status (adapter-synthesized; excludes ESRD columns — no label leakage).",
)


# --- SMA profile ----------------------------------------------------------- #
# SMA records carry no `sex` field (autosomal). Fairness axes are the genetic and
# severity strata that drive SMA outcomes. Outcome: ventilatory support (native
# boolean). The score avoids `needs_ventilation` and its proxy `niv_hours_per_day`.
_SMA_SCORE = ScoreModel(
    intercept=0.5,
    terms=[
        ("smn2_copies(protective)", lambda r: -0.8 * (_num(r.get("smn2_copies"), 2) - 2)),
        ("early_onset", lambda r: -0.03 * (_num(r.get("age_at_onset_months"), 12) - 12)),
        ("achieved_sitting(protective)", lambda r: -1.0 * _b(r.get("achieved_sitting"))),
        ("on_dmt(protective)", lambda r: -0.5 * _b(r.get("on_disease_modifying_therapy"))),
        ("scoliosis", lambda r: 0.5 * _b(r.get("scoliosis"))),
    ],
    feature_columns=[
        "smn2_copies",
        "age_at_onset_months",
        "achieved_sitting",
        "on_disease_modifying_therapy",
        "scoliosis",
    ],
)

SMA_PROFILE = ModuleProfile(
    name="sma",
    entity_id="patient_id",
    cohorts=[
        CohortSpec("sma_type", "SMA type", "object", definition="SMA clinical type (I–IV); primary severity axis."),
        CohortSpec("smn2_copies", "SMN2 copies", "int", splits=[2, 3], definition="SMN2 copy number (genetic severity modifier)."),
        CohortSpec("age_at_diagnosis_months", "Age at dx (mo)", "int", splits=[6, 18], definition="Age at diagnosis in months."),
    ],
    outcome=OutcomeSpec(
        source="needs_ventilation",
        display_name="Ventilatory support",
        definition="Native binary: patient requires ventilatory support.",
    ),
    score_model=_SMA_SCORE,
    score_definition="Illustrative SMA-severity score in [0,1] from SMN2 copies, onset age, motor milestones, DMT status, and scoliosis (adapter-synthesized; excludes ventilation columns — no label leakage).",
)


# --- Diabetes profile ------------------------------------------------------ #
# Diabetes carries full demographics (race/sex/type). Outcome: diabetic
# nephropathy (native boolean). The score avoids `nephropathy_any` and its renal
# proxies (egfr_current, albuminuria_stage, ckd_stage, dialysis_initiated).
_DIABETES_SCORE = ScoreModel(
    intercept=-1.6,
    terms=[
        ("high_hba1c", lambda r: 0.35 * (_num(r.get("hba1c_current"), 7.0) - 7.0)),
        ("diabetes_duration", lambda r: 0.05 * (_num(r.get("diabetes_duration_years"), 10) - 10)),
        ("current_age", lambda r: 0.015 * (_num(r.get("current_age"), 55) - 55)),
        ("coronary_artery_disease", lambda r: 0.5 * _b(r.get("coronary_artery_disease"))),
        ("time_in_range(protective)", lambda r: -0.015 * (_num(r.get("time_in_range_pct"), 60) - 60)),
    ],
    feature_columns=[
        "hba1c_current",
        "diabetes_duration_years",
        "current_age",
        "coronary_artery_disease",
        "time_in_range_pct",
    ],
)

DIABETES_PROFILE = ModuleProfile(
    name="diabetes",
    entity_id="patient_id",
    cohorts=[
        CohortSpec("current_age", "Age", "int", splits=[40, 65], definition="Current patient age in years."),
        CohortSpec("sex", "Sex", "object", definition="Recorded sex."),
        CohortSpec("race", "Race", "object", definition="Race / ethnicity category."),
        CohortSpec("diabetes_type", "Diabetes type", "object", definition="Type 1 vs type 2 diabetes."),
    ],
    outcome=OutcomeSpec(
        source="nephropathy_any",
        display_name="Diabetic nephropathy",
        definition="Native binary: any diabetic nephropathy (kidney disease).",
    ),
    score_model=_DIABETES_SCORE,
    score_definition="Illustrative diabetes-complication score in [0,1] from HbA1c, disease duration, age, CAD, and time-in-range (adapter-synthesized; excludes renal columns — no label leakage).",
)


# --- Sepsis profile -------------------------------------------------------- #
# Longitudinal module (demographics + sepsis observation hook). Outcome: delayed
# hypotension (a native boolean deterioration event). The score uses baseline
# labs/comorbidities and avoids the outcome and its downstream shock/timing fields.
_SEPSIS_SCORE = ScoreModel(
    intercept=-1.2,
    terms=[
        ("high_lactate", lambda r: 0.35 * (_num(r.get("lactate_initial"), 2.0) - 2.0)),
        ("high_creatinine", lambda r: 0.4 * (_num(r.get("creatinine_initial"), 1.0) - 1.0)),
        ("age", lambda r: 0.02 * (_num(r.get("age"), 60) - 60)),
        ("ckd", lambda r: 0.4 * _b(r.get("ckd_flag"))),
        ("hypertension", lambda r: 0.2 * _b(r.get("hypertension_flag"))),
    ],
    feature_columns=["lactate_initial", "creatinine_initial", "age", "ckd_flag", "hypertension_flag"],
)

SEPSIS_PROFILE = ModuleProfile(
    name="sepsis",
    entity_id="patient_id",
    cohorts=[
        CohortSpec("age", "Age", "int", splits=[50, 70], definition="Patient age in years."),
        CohortSpec("sex", "Sex", "object", definition="Recorded sex."),
        CohortSpec("ethnicity", "Race", "object", definition="Race / ethnicity category."),
        CohortSpec("suspected_infection_source", "Infection source", "object", definition="Suspected source of infection."),
    ],
    outcome=OutcomeSpec(
        source="delayed_hypotension_flag",
        display_name="Delayed hypotension",
        definition="Native binary: delayed-onset hypotension (sepsis deterioration event).",
    ),
    score_model=_SEPSIS_SCORE,
    score_definition="Illustrative sepsis-severity score in [0,1] from lactate, creatinine, age, and comorbidities (adapter-synthesized; excludes shock/timing outcome fields — no label leakage).",
)


# --- Stroke profile -------------------------------------------------------- #
# Longitudinal module with a genuine equity outcome: whether the patient received
# thrombolysis (tPA). `rural_presentation` is exposed as a fairness axis. The score
# uses clinical severity/timing but excludes tpa_* and door_to_needle (label proxies).
_STROKE_SCORE = ScoreModel(
    intercept=-0.5,
    terms=[
        ("nihss_score", lambda r: 0.03 * (_num(r.get("nihss_score"), 8) - 8)),
        ("onset_to_door(delay lowers tPA)", lambda r: -0.006 * (_num(r.get("onset_to_door_minutes"), 120) - 120)),
        ("age", lambda r: -0.005 * (_num(r.get("age"), 65) - 65)),
        ("atrial_fibrillation", lambda r: 0.2 * _b(r.get("atrial_fibrillation"))),
        ("prior_stroke", lambda r: -0.2 * _b(r.get("prior_stroke"))),
    ],
    feature_columns=["nihss_score", "onset_to_door_minutes", "age", "atrial_fibrillation", "prior_stroke"],
)

STROKE_PROFILE = ModuleProfile(
    name="stroke",
    entity_id="patient_id",
    cohorts=[
        CohortSpec("age", "Age", "int", splits=[55, 75], definition="Patient age in years."),
        CohortSpec("sex", "Sex", "object", definition="Recorded sex."),
        CohortSpec("ethnicity", "Race", "object", definition="Race / ethnicity category."),
        CohortSpec("stroke_type", "Stroke type", "object", definition="Ischemic / hemorrhagic / TIA."),
        CohortSpec("rural_presentation", "Rural presentation", "object", definition="Presented at a rural site (sparse-population axis)."),
    ],
    outcome=OutcomeSpec(
        source="tpa_administered",
        display_name="tPA administered",
        definition="Native binary: received thrombolysis (an access/equity outcome).",
    ),
    score_model=_STROKE_SCORE,
    score_definition="Illustrative tPA-likelihood score in [0,1] from stroke severity, time-to-presentation, and history (adapter-synthesized; excludes tpa_eligible/door_to_needle — no label leakage).",
)


PROFILES: dict[str, ModuleProfile] = {
    "oud": OUD_PROFILE,
    "chf": CHF_PROFILE,
    "copd": COPD_PROFILE,
    "dmd": DMD_PROFILE,
    "fabry": FABRY_PROFILE,
    "sma": SMA_PROFILE,
    "diabetes": DIABETES_PROFILE,
    "sepsis": SEPSIS_PROFILE,
    "stroke": STROKE_PROFILE,
}


def profile_for(module: str) -> ModuleProfile:
    key = (module or "").strip().lower()
    if key not in PROFILES:
        raise SchemaMismatchError(
            f"No Seismometer profile registered for module '{module}'. "
            f"Known profiles: {sorted(PROFILES)}. "
            "Add a ModuleProfile (cohorts, outcome, score_model) to PROFILES in examples/seismometer/seismometer_adapter.py."
        )
    return PROFILES[key]


# --------------------------------------------------------------------------- #
# Result container
# --------------------------------------------------------------------------- #
@dataclass
class SubgroupAudit:
    cohort: str
    subgroup: str
    count: int
    survives: bool


@dataclass
class AdapterResult:
    out_dir: Path
    profile: ModuleProfile
    n_patients: int
    invented_columns: list[dict] = field(default_factory=list)
    censor_min_count: int = 10
    audit: list[SubgroupAudit] = field(default_factory=list)
    dropped_cohorts: list[str] = field(default_factory=list)

    @property
    def censored_subgroups(self) -> list[SubgroupAudit]:
        return [a for a in self.audit if not a.survives]

    @property
    def config_path(self) -> Path:
        return self.out_dir


# --------------------------------------------------------------------------- #
# Loading + validation
# --------------------------------------------------------------------------- #
def _require_pandas():
    try:
        import pandas as pd  # noqa: F401
    except ImportError as exc:  # pragma: no cover
        raise SchemaMismatchError(
            "pandas is required by seismometer_adapter but is not installed. "
            "Install with `pip install pandas pyarrow`."
        ) from exc
    return pd


def load_canonical(patients_json: Optional[str | Path], results_csv: Optional[str | Path]):
    """Load and reconcile HipAAsynth's canonical patients.json + results.csv.

    Either input may be omitted (but not both). When both are given, their
    ``patient_id`` sets must match exactly or a :class:`SchemaMismatchError` is
    raised — no silent inner-join that would drop patients.

    Returns a tuple ``(dataframe, module_name)``.
    """
    pd = _require_pandas()

    if not patients_json and not results_csv:
        raise SchemaMismatchError("Provide at least one of patients.json or results.csv; both were empty.")

    json_df = None
    module_name = None
    if patients_json:
        p = Path(patients_json)
        if not p.is_file():
            raise SchemaMismatchError(f"patients.json not found: {p}")
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise SchemaMismatchError(f"patients.json is not valid JSON ({p}): {exc}") from exc
        if isinstance(raw, dict):
            module_name = raw.get("module")
            records = raw.get("patients")
            if records is None:
                raise SchemaMismatchError(
                    f"patients.json object has no 'patients' key ({p}). "
                    f"Top-level keys present: {sorted(raw)}."
                )
        elif isinstance(raw, list):
            records = raw
        else:
            raise SchemaMismatchError(f"patients.json must be a list or an object with 'patients' ({p}).")
        if not records:
            raise SchemaMismatchError(f"patients.json contains zero patients ({p}).")
        json_df = pd.DataFrame(records)

    csv_df = None
    if results_csv:
        c = Path(results_csv)
        if not c.is_file():
            raise SchemaMismatchError(f"results.csv not found: {c}")
        csv_df = pd.read_csv(c)
        if csv_df.empty:
            raise SchemaMismatchError(f"results.csv contains zero rows ({c}).")

    # Reconcile
    if json_df is not None and csv_df is not None:
        if "patient_id" not in json_df.columns or "patient_id" not in csv_df.columns:
            raise SchemaMismatchError(
                "Both inputs must carry a 'patient_id' column to be reconciled. "
                f"patients.json has patient_id: {'patient_id' in json_df.columns}; "
                f"results.csv has patient_id: {'patient_id' in csv_df.columns}."
            )
        j_ids = set(json_df["patient_id"].astype(str))
        c_ids = set(csv_df["patient_id"].astype(str))
        if j_ids != c_ids:
            only_json = sorted(j_ids - c_ids)[:5]
            only_csv = sorted(c_ids - j_ids)[:5]
            raise SchemaMismatchError(
                "patient_id sets differ between patients.json and results.csv — refusing to silently join.\n"
                f"  only in patients.json ({len(j_ids - c_ids)}): {only_json}\n"
                f"  only in results.csv   ({len(c_ids - j_ids)}): {only_csv}"
            )
        # Prefer the CSV's flat typing; union any JSON-only columns.
        df = csv_df.copy()
        extra_cols = [col for col in json_df.columns if col not in df.columns]
        if extra_cols:
            merged = df.merge(
                json_df[["patient_id", *extra_cols]].assign(
                    patient_id=lambda d: d["patient_id"].astype(str)
                ),
                left_on=df["patient_id"].astype(str),
                right_on="patient_id",
                how="left",
                suffixes=("", "_json"),
            )
            df = merged.drop(columns=[col for col in merged.columns if col.endswith("_json") or col == "key_0"],
                             errors="ignore")
    else:
        df = json_df if json_df is not None else csv_df

    if module_name is None:
        module_name = _infer_module(df)
    return df, module_name


def _infer_module(df) -> Optional[str]:
    """Best-effort module inference from a cohort_label / conditions column."""
    for col in ("module", "cohort_label"):
        if col in df.columns and len(df):
            val = str(df[col].iloc[0]).lower()
            for key in PROFILES:
                if key in val:
                    return key
    return None


def _validate_columns(df, profile: ModuleProfile) -> None:
    """Fail loud if any column the adapter needs is absent from the inputs."""
    required = {profile.entity_id}
    required |= {c.source for c in profile.cohorts}
    required |= set(profile.score_model.feature_columns)
    outcome = profile.outcome
    if outcome.derive is None:
        # Native binary outcome: the source column itself must exist and be binary.
        required.add(outcome.source)
    else:
        # Derived outcome: the columns the derive() callable reads must exist.
        required.update(outcome.derived_from or (outcome.source,))

    missing = sorted(c for c in required if c not in df.columns)
    if missing:
        raise SchemaMismatchError(
            f"Canonical data for module '{profile.name}' is missing required columns: {missing}.\n"
            f"Columns present ({len(df.columns)}): {sorted(df.columns)}"
        )

    if outcome.derive is None:
        # Outcome must be binary-coercible.
        bad = _non_binary_values(df[outcome.source])
        if bad:
            raise SchemaMismatchError(
                f"Outcome column '{outcome.source}' is not binary/boolean; "
                f"unexpected values: {bad[:8]}. Seismometer targets must be 0/1."
            )
    else:
        # Derived outcome: derive_outcome fails loud if derive() returns a
        # non-binary value, so calling it here validates the derivation early.
        derive_outcome(df, profile)


def _non_binary_values(series) -> list:
    allowed = {True, False, 0, 1, 0.0, 1.0, "true", "false", "0", "1", "True", "False"}
    bad = []
    for v in series.dropna().unique():
        if v not in allowed:
            bad.append(v)
    return bad


# --------------------------------------------------------------------------- #
# Score / prediction / event construction
# --------------------------------------------------------------------------- #
def derive_score(df, profile: ModuleProfile):
    """Deterministic risk score in (0,1). See :class:`ScoreModel`."""
    pd = _require_pandas()
    sm = profile.score_model

    def _row_score(row: dict) -> float:
        logodds = sm.intercept + sum(term(row) for _, term in sm.terms)
        return 1.0 / (1.0 + math.exp(-logodds))

    records = df.to_dict(orient="records")
    scores = [_row_score(r) for r in records]
    return pd.Series(scores, index=df.index, dtype="float64")


def derive_outcome(df, profile: ModuleProfile):
    """Binary outcome Series (int 0/1) for a profile.

    Native outcomes read ``outcome.source`` directly; derived outcomes apply
    ``outcome.derive(row)`` over real columns. Kept separate from the score so a
    derived label can never silently pull in the very column it is derived from.
    """
    pd = _require_pandas()
    outcome = profile.outcome
    if outcome.derive is None:
        return df[outcome.source].map(_b).astype(int)
    # Derived path: fail loud (no silent coercion) if derive() returns anything
    # other than a boolean or 0/1, so a mis-written derive (e.g. returning a raw
    # count) is caught instead of being quietly treated as event-present.
    records = df.to_dict(orient="records")
    values = []
    for r in records:
        v = outcome.derive(r)
        if isinstance(v, bool):
            values.append(int(v))
        elif isinstance(v, (int, float)) and not isinstance(v, bool) and v in (0, 1):
            values.append(int(v))
        else:
            raise SchemaMismatchError(
                f"Derived outcome '{outcome.display_name}' derive() returned a "
                f"non-binary value {v!r}; it must return True/False or 0/1."
            )
    return pd.Series(values, index=df.index, dtype="int64")


def build_predictions(df, profile: ModuleProfile):
    """Build the Seismometer predictions frame with explicit dtypes."""
    pd = _require_pandas()
    out = pd.DataFrame()
    out[profile.entity_id] = df[profile.entity_id].astype(str)
    out[profile.predict_time_col] = pd.to_datetime(_REFERENCE_TIME)
    out[profile.score_col] = derive_score(df, profile).astype("float64")

    for c in profile.cohorts:
        col = df[c.source]
        if c.dtype == "int":
            out[c.source] = pd.to_numeric(col, errors="raise").astype("int64")
        elif c.dtype in ("float", "float64"):
            out[c.source] = pd.to_numeric(col, errors="raise").astype("float64")
        else:
            out[c.source] = col.astype(str)
    return out


def build_events(df, profile: ModuleProfile):
    """Build the long-format events frame (Id, Type, EventTime, Value)."""
    pd = _require_pandas()
    ev = pd.DataFrame()
    ev[profile.entity_id] = df[profile.entity_id].astype(str)
    ev["Type"] = profile.outcome.display_name
    ev["EventTime"] = pd.to_datetime(_REFERENCE_TIME)
    ev["Value"] = derive_outcome(df, profile).astype("float64")
    return ev


# --------------------------------------------------------------------------- #
# Censor audit — mirrors seismometer.seismogram.Seismogram.create_cohorts
# --------------------------------------------------------------------------- #
def censor_audit(predictions, profile: ModuleProfile, censor_min_count: int) -> tuple[list[SubgroupAudit], list[str]]:
    """Reproduce Seismometer's cohort-visibility gate.

    Seismometer keeps a subgroup only when ``value_counts() > censor_min_count``
    (strictly greater — see ``create_cohorts``). If *no* subgroup of an attribute
    survives, the entire cohort attribute is dropped from the notebook selectors.
    """
    pd = _require_pandas()
    audits: list[SubgroupAudit] = []
    dropped: list[str] = []

    for c in profile.cohorts:
        if c.splits:
            edges = [-math.inf, *c.splits, math.inf]
            labels = _numeric_labels(c.splits)
            binned = pd.cut(pd.to_numeric(predictions[c.source]), bins=edges, labels=labels, right=False)
            counts = binned.value_counts()
        else:
            counts = predictions[c.source].value_counts()

        any_survive = False
        for subgroup, n in counts.items():
            survives = int(n) > censor_min_count
            any_survive = any_survive or survives
            audits.append(SubgroupAudit(c.display_name, str(subgroup), int(n), survives))
        if not any_survive:
            dropped.append(c.display_name)
    return audits, dropped


def _numeric_labels(splits: list[Any]) -> list[str]:
    labels = [f"<{splits[0]}"]
    for lo, hi in zip(splits[:-1], splits[1:]):
        labels.append(f"{lo}-{hi}")
    labels.append(f">={splits[-1]}")
    return labels


# --------------------------------------------------------------------------- #
# Config writers
# --------------------------------------------------------------------------- #
def _yaml_dump(obj: Any) -> str:
    import yaml

    return yaml.safe_dump(obj, sort_keys=False, default_flow_style=False, allow_unicode=True)


def write_package(df, profile: ModuleProfile, out_dir: str | Path, censor_min_count: int = 10) -> AdapterResult:
    """Write every Seismometer artifact into ``out_dir`` and return the result."""
    pd = _require_pandas()
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    _validate_columns(df, profile)

    predictions = build_predictions(df, profile)
    events = build_events(df, profile)

    pred_path = out / "predictions.parquet"
    ev_path = out / "events.parquet"
    try:
        predictions.to_parquet(pred_path, index=False)
        events.to_parquet(ev_path, index=False)
    except Exception as exc:  # pyarrow missing or dtype problem — surface clearly
        raise SchemaMismatchError(f"Failed to write parquet ({exc}). Ensure pyarrow is installed.") from exc

    # dictionary.yml — one file, both prediction + event dictionaries.
    pred_items = [
        {"name": profile.entity_id, "dtype": "object", "definition": "Synthetic patient entity id (join key)."},
        {"name": profile.score_col, "definition": profile.score_definition},
    ]
    for c in profile.cohorts:
        pred_items.append({"name": c.source, "dtype": c.dtype, "definition": c.definition})
    dictionary = {
        "predictions": pred_items,
        "events": [
            {
                "name": profile.outcome.display_name,
                "dtype": "float",
                "definition": profile.outcome.definition,
            }
        ],
    }
    (out / "dictionary.yml").write_text(_yaml_dump(dictionary), encoding="utf-8")

    # usage_config.yml
    cohorts_yaml = []
    for c in profile.cohorts:
        entry: dict[str, Any] = {"source": c.source, "display_name": c.display_name}
        if c.splits:
            entry["splits"] = list(c.splits)
        cohorts_yaml.append(entry)
    usage = {
        "data_usage": {
            "entity_id": profile.entity_id,
            "primary_output": profile.score_col,
            "primary_target": profile.outcome.display_name,
            "predict_time": profile.predict_time_col,
            "outputs": [profile.score_col],
            "cohorts": cohorts_yaml,
            "events": [
                {
                    "source": profile.outcome.display_name,
                    "display_name": profile.outcome.display_name,
                    "window_hr": None,
                    "usage": "target",
                }
            ],
            "censor_min_count": int(censor_min_count),
        }
    }
    (out / "usage_config.yml").write_text(_yaml_dump(usage), encoding="utf-8")

    # config.yml
    config = {
        "other_info": {
            "data_dir": ".",
            "info_dir": "output",
            "usage_config": "usage_config.yml",
            "prediction_definition": "dictionary.yml",
            "event_definition": "dictionary.yml",
            "prediction_path": "predictions.parquet",
            "event_path": "events.parquet",
            "metadata_path": "metadata.json",
        }
    }
    (out / "config.yml").write_text(_yaml_dump(config), encoding="utf-8")

    # metadata.json — Seismometer opens this unconditionally.
    metadata = {
        "modelname": f"HipAAsynth {profile.name.upper()} — {profile.outcome.display_name} risk (synthetic demo)",
        "thresholds": [0.5, 0.2],
    }
    (out / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    audit, dropped = censor_audit(predictions, profile, censor_min_count)

    invented = [
        {
            "column": profile.predict_time_col,
            "table": "predictions.parquet",
            "dtype": "datetime64[ns]",
            "reason": (
                "Seismometer requires a predict_time column; HipAAsynth records are point-in-time "
                f"snapshots with no timestamp. Filled with a constant reference instant ({_REFERENCE_TIME})."
            ),
        },
        {
            "column": "EventTime",
            "table": "events.parquet",
            "dtype": "datetime64[ns]",
            "reason": (
                "Events table requires a time column. Set equal to the prediction time so the "
                "no-window target merge attaches the outcome to each prediction."
            ),
        },
        {
            "column": profile.score_col,
            "table": "predictions.parquet",
            "dtype": "float64",
            "reason": (
                "HipAAsynth emits no model score. Synthesized a deterministic, documented risk score "
                "(sigmoid over clinical risk factors, no outcome leakage) so Seismometer has an output to evaluate."
            ),
        },
        {
            "column": "Value",
            "table": "events.parquet",
            "dtype": "float64",
            "reason": (
                f"Binary encoding (0.0/1.0) of the canonical outcome field '{profile.outcome.source}'."
                if profile.outcome.derive is None
                else (
                    f"Binary outcome DERIVED from real data ({', '.join(profile.outcome.derived_from) or profile.outcome.source}): "
                    f"{profile.outcome.definition} Not a HipAAsynth-emitted event — an honest binarization for evaluation."
                )
            ),
        },
    ]

    return AdapterResult(
        out_dir=out,
        profile=profile,
        n_patients=len(df),
        invented_columns=invented,
        censor_min_count=censor_min_count,
        audit=audit,
        dropped_cohorts=dropped,
    )


def run(
    patients_json: Optional[str | Path],
    results_csv: Optional[str | Path],
    out_dir: str | Path,
    module: Optional[str] = None,
    outcome_field: Optional[str] = None,
    censor_min_count: int = 10,
) -> AdapterResult:
    """Full pipeline: load → validate → emit package → audit. Fails loud."""
    df, inferred = load_canonical(patients_json, results_csv)
    module = module or inferred
    if not module:
        raise SchemaMismatchError(
            "Could not determine which module this cohort is. Pass --module explicitly "
            f"(known: {sorted(PROFILES)})."
        )
    profile = profile_for(module)
    if outcome_field and outcome_field != profile.outcome.source:
        profile = ModuleProfile(
            **{
                **profile.__dict__,
                "outcome": OutcomeSpec(
                    source=outcome_field,
                    display_name=profile.outcome.display_name,
                    definition=f"Binary clinical outcome '{outcome_field}' (overridden via --outcome-field).",
                ),
            }
        )
    return write_package(df, profile, out_dir, censor_min_count=censor_min_count)


# --------------------------------------------------------------------------- #
# Reporting / CLI
# --------------------------------------------------------------------------- #
def print_report(result: AdapterResult, stream=sys.stdout) -> None:
    p = lambda *a: print(*a, file=stream)  # noqa: E731
    prof = result.profile
    p("")
    p("=" * 72)
    p(f"  HipAAsynth → Seismometer package written: {result.out_dir}")
    p("=" * 72)
    p(f"  module            : {prof.name}")
    p(f"  patients          : {result.n_patients}")
    p(f"  entity id         : {prof.entity_id}")
    p(f"  score column      : {prof.score_col}  (primary_output)")
    p(f"  target event      : {prof.outcome.display_name}  <- '{prof.outcome.source}'")
    p(f"  cohorts           : {', '.join(c.display_name for c in prof.cohorts)}")
    p(f"  censor_min_count  : {result.censor_min_count}  (subgroup kept iff count > threshold)")

    p("")
    p("  Columns the adapter had to INVENT (HipAAsynth does not emit these):")
    for inv in result.invented_columns:
        p(f"    - {inv['column']:<12} [{inv['table']}, {inv['dtype']}]")
        p(f"        {inv['reason']}")

    p("")
    p("  CENSOR AUDIT (Seismometer default fairness gate):")
    by_cohort: dict[str, list[SubgroupAudit]] = {}
    for a in result.audit:
        by_cohort.setdefault(a.cohort, []).append(a)
    for cohort, subs in by_cohort.items():
        dropped = cohort in result.dropped_cohorts
        flag = "  <-- ENTIRE COHORT DROPPED" if dropped else ""
        p(f"    {cohort}:{flag}")
        for a in sorted(subs, key=lambda x: -x.count):
            mark = "OK " if a.survives else "CENSORED"
            p(f"        [{mark}] {a.subgroup:<14} n={a.count}")

    censored = result.censored_subgroups
    p("")
    if not censored and not result.dropped_cohorts:
        p(f"  RESULT: ALL {len(result.audit)} subgroups survive censor_min_count="
          f"{result.censor_min_count}. Cohort renders fully; no larger N required.")
    else:
        p(f"  RESULT: {len(censored)} subgroup(s) censored, "
          f"{len(result.dropped_cohorts)} cohort attribute(s) dropped entirely.")
        for a in censored:
            p(f"    - {a.cohort}='{a.subgroup}' has n={a.count} (needs > {result.censor_min_count}).")
        p("  -> Increase generated N for these cohorts to clear the fairness audit.")
    p("=" * 72)
    p("")


def main(argv: Optional[list[str]] = None) -> int:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser(
        prog="seismometer_adapter",
        description="Convert a HipAAsynth cohort (patients.json + results.csv) into a Seismometer package.",
    )
    ap.add_argument("--patients", help="Path to canonical patients.json")
    ap.add_argument("--results", help="Path to canonical results.csv")
    ap.add_argument("--out", required=True, help="Output directory for the Seismometer config package")
    ap.add_argument("--module", help="Module/profile name (e.g. oud). Inferred from data when omitted.")
    ap.add_argument("--outcome-field", help="Override the canonical column used as the binary outcome.")
    ap.add_argument("--censor-min-count", type=int, default=10, help="Seismometer censor_min_count (default 10).")
    args = ap.parse_args(argv)

    if args.censor_min_count < 10:
        # Seismometer's own model pins this to >= 10; mirror that constraint loudly.
        print("ERROR: --censor-min-count must be >= 10 (Seismometer enforces this).", file=sys.stderr)
        return 2

    try:
        result = run(
            patients_json=args.patients,
            results_csv=args.results,
            out_dir=args.out,
            module=args.module,
            outcome_field=args.outcome_field,
            censor_min_count=args.censor_min_count,
        )
    except SchemaMismatchError as exc:
        print(f"\nSCHEMA MISMATCH — adapter refused to proceed:\n  {exc}\n", file=sys.stderr)
        return 1

    print_report(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
