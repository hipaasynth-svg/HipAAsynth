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

logger = logging.getLogger("hipaasynth.seismometer_adapter")

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
    """The binary clinical outcome mapped onto a Seismometer target event."""

    source: str  # boolean/0-1 column in the canonical data
    display_name: str  # Seismometer event display name (== primary_target)
    definition: str = ""


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

PROFILES: dict[str, ModuleProfile] = {"oud": OUD_PROFILE}


def profile_for(module: str) -> ModuleProfile:
    key = (module or "").strip().lower()
    if key not in PROFILES:
        raise SchemaMismatchError(
            f"No Seismometer profile registered for module '{module}'. "
            f"Known profiles: {sorted(PROFILES)}. "
            "Add a ModuleProfile (cohorts, outcome, score_model) to hipaasynth.seismometer_adapter.PROFILES."
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
    required.add(profile.outcome.source)
    required |= set(profile.score_model.feature_columns)

    missing = sorted(c for c in required if c not in df.columns)
    if missing:
        raise SchemaMismatchError(
            f"Canonical data for module '{profile.name}' is missing required columns: {missing}.\n"
            f"Columns present ({len(df.columns)}): {sorted(df.columns)}"
        )

    # Outcome must be binary-coercible.
    bad = _non_binary_values(df[profile.outcome.source])
    if bad:
        raise SchemaMismatchError(
            f"Outcome column '{profile.outcome.source}' is not binary/boolean; "
            f"unexpected values: {bad[:8]}. Seismometer targets must be 0/1."
        )


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
    ev["Value"] = df[profile.outcome.source].map(_b).astype(int).astype("float64")
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
            "reason": f"Binary encoding (0.0/1.0) of the canonical outcome field '{profile.outcome.source}'.",
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
