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

"""HipAAsynth SDK — a high-level facade for notebooks and scripts.

The one-liner most users want::

    import hipaasynth
    cohort = hipaasynth.generate(count=100, seed=42, module="stroke")
    cohort.to_fhir_bundle("cohort.json")     # or .to_csv(), .to_omop(), ...
    report = cohort.validate()               # structural FHIR check
    stats = cohort.fidelity()                # are the statistics plausible?
    probe = cohort.utility()                 # is the signal learnable?

No argparse, no manual ``GenerationConfig`` assembly, and every exporter is a
method that either **returns** the data (no path given) or **writes** a file (path
given). This wraps the same engine the CLI and REST API use — it adds no new
behavior, just an ergonomic surface.

Pure standard library (Parquet stays optional via the lazy ``[parquet]`` extra).
All records are synthetic — no PHI.
"""
from __future__ import annotations

import csv
import io
import json
from datetime import date
from pathlib import Path
from typing import Optional, Union

from hipaasynth.core.config import (
    DEFAULT_SYNTHETIC_DISCLAIMER,
    GenerationConfig,
)
from hipaasynth.core.profile_loader import load_population_profile
from hipaasynth.exporters.exporters import (
    _flat_patient_rows,
    _patient_to_fhir,
    export_csv,
    export_fhir,
    export_fhir_ndjson,
    export_json,
    export_parquet,
    summary_stats,
)
from hipaasynth.exporters.fhir_validate import FhirValidationReport, validate_resources
from hipaasynth.exporters.omop import build_cdm_tables, export_omop
from hipaasynth.pipelines.population_pipeline import generate_patients
from hipaasynth.validation import (
    UtilityProbeResult,
    downstream_utility_probe,
    fidelity_report,
)

# Canonical decision-module → GenerationConfig.required_condition map. The REST
# API imports this so the two surfaces never drift.
MODULES: dict[str, Optional[str]] = {
    "sepsis": None,  # engine default
    "stroke": "stroke",
    "dka": "dka",
    "fabry": "fabry",
}

_PROFILES_DIR = Path(__file__).resolve().parent / "profiles"

PathLike = Union[str, Path]


def available_profiles() -> list[str]:
    """Names of the population profiles bundled with HipAAsynth."""
    return sorted(p.stem for p in _PROFILES_DIR.glob("*.json"))


def _resolve_profile(profile: Optional[PathLike]) -> Optional[str]:
    """Resolve a profile argument to a JSON path.

    Accepts either a bundled profile *name* (e.g. ``"us_default"``) or an explicit
    path to a profile JSON file (the SDK is trusted local code, unlike the network
    API, so a path is allowed here). ``None`` means no profile.
    """
    if profile in (None, ""):
        return None
    name = str(profile)
    bundled = _PROFILES_DIR / f"{name}.json"
    if bundled.is_file():
        return str(bundled)
    if Path(name).is_file():
        return name
    raise ValueError(
        f"unknown profile {profile!r}. Provide a path to a profile JSON, or one "
        f"of the bundled names: {', '.join(available_profiles())}"
    )


class Cohort:
    """A generated synthetic cohort plus its configuration, with export helpers.

    Iterable and indexable over its patients. Every ``to_*`` method returns the
    serialized data when called without a path, or writes a file (and returns the
    path) when given one.
    """

    def __init__(self, patients, config: GenerationConfig):
        self.patients = list(patients)
        self.config = config

    # ── container protocol ───────────────────────────────────────────────────
    def __len__(self) -> int:
        return len(self.patients)

    def __iter__(self):
        return iter(self.patients)

    def __getitem__(self, idx):
        return self.patients[idx]

    def __repr__(self) -> str:
        module = next((k for k, v in MODULES.items()
                       if v == self.config.required_condition), "sepsis")
        return (f"<Cohort n={len(self.patients)} seed={self.config.seed} "
                f"module={module!r}>")

    # ── summaries ────────────────────────────────────────────────────────────
    def summary(self) -> dict:
        """Aggregate stats (counts, age/BMI, sex & condition breakdowns)."""
        return summary_stats(self.patients)

    # ── FHIR helpers ─────────────────────────────────────────────────────────
    def fhir_resources(self) -> list[dict]:
        """The flat list of FHIR resources for the whole cohort."""
        return [r for p in self.patients for r in _patient_to_fhir(p)]

    def fhir_bundle(self) -> dict:
        """The cohort as a single in-memory FHIR R5 collection Bundle."""
        return {
            "resourceType": "Bundle",
            "type": "collection",
            "entry": [
                {"fullUrl": f"urn:uuid:{r['id']}", "resource": r}
                for r in self.fhir_resources()
            ],
        }

    def validate(self) -> FhirValidationReport:
        """Run the structural FHIR validator over the cohort's resources.

        Structural R5 check only — NOT a substitute for the official HL7 FHIR IG
        validator (see :mod:`hipaasynth.exporters.fhir_validate`).
        """
        return validate_resources(self.fhir_resources())

    # ── trustworthiness (Tier 4) ─────────────────────────────────────────────
    # `validate()` above asks "is this well-formed FHIR?". These two ask the
    # different and harder question the Tier 4 modules exist for: is the data
    # itself any good? Keep them distinct — a cohort can be perfectly valid FHIR
    # and still be statistically implausible.
    def fidelity(self) -> dict:
        """Statistical-fidelity report: are the cohort's statistics plausible?

        Lab-value marginals, condition prevalence, physiologically linked lab
        correlations, temporal ordering, and visit sequencing. Returns a plain
        JSON-friendly dict, so it serializes next to an OMOP/FHIR export.

        Needs a non-empty cohort; raises ``ValueError`` otherwise.
        """
        return fidelity_report(self.patients)

    def utility(self, **kwargs) -> UtilityProbeResult:
        """Train-on-synthetic probe: is the cohort's signal actually learnable?

        Trains a pure-Python logistic model on part of the cohort and reports
        held-out accuracy, ROC-AUC and lift over the majority-class baseline. An
        AUC well above 0.5 is evidence the feature→label signal is real.

        Keyword args pass through to
        :func:`~hipaasynth.validation.utility_probe.downstream_utility_probe`
        (``target``, ``test_fraction``, ``seed``, ``epochs``, ``lr``).

        The default ``target`` is a *comorbidity* that varies across the cohort,
        deliberately not the module's own condition: a ``module="stroke"`` cohort
        is 100% stroke by construction, so probing for it would leave a single
        class and tell you nothing. Raises ``ValueError`` if the cohort is too
        small or a split ends up single-class.
        """
        return downstream_utility_probe(self.patients, **kwargs)

    # ── exporters (return-or-write) ──────────────────────────────────────────
    def to_json(self, path: Optional[PathLike] = None):
        if path is not None:
            export_json(self.patients, str(path))
            return Path(path)
        return json.dumps([p.to_dict() for p in self.patients],
                          indent=2, ensure_ascii=False)

    def to_csv(self, path: Optional[PathLike] = None):
        if path is not None:
            export_csv(self.patients, str(path))
            return Path(path)
        fieldnames, rows = _flat_patient_rows(self.patients)
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
        return buf.getvalue()

    def to_fhir_bundle(self, path: Optional[PathLike] = None):
        if path is not None:
            export_fhir(self.patients, str(path))
            return Path(path)
        return self.fhir_bundle()

    def to_ndjson(self, output_dir: PathLike) -> Path:
        """Write the FHIR Bulk Data ($export) NDJSON layout (a directory)."""
        export_fhir_ndjson(self.patients, str(output_dir))
        return Path(output_dir)

    def to_omop(self, output_dir: Optional[PathLike] = None):
        """Return OMOP CDM tables in-memory (dict), or write the CSV set to a dir."""
        if output_dir is not None:
            export_omop(self.patients, str(output_dir))
            return Path(output_dir)
        return build_cdm_tables(self.patients)

    def to_parquet(self, path: PathLike) -> Path:
        """Write Apache Parquet (requires the optional ``[parquet]`` extra)."""
        export_parquet(self.patients, str(path))
        return Path(path)


def generate(
    count: int = 100,
    seed: int = 42,
    module: str = "sepsis",
    profile: Optional[PathLike] = None,
    *,
    age_min: int = 18,
    age_max: int = 90,
    sex_ratio_female: float = 0.5,
) -> Cohort:
    """Generate a synthetic cohort and return a :class:`Cohort`.

    Args:
        count: number of patients (>= 1).
        seed: RNG seed — the same seed always reproduces the same cohort.
        module: decision module — one of :data:`MODULES`
            (``sepsis`` (default), ``stroke``, ``dka``, ``fabry``).
        profile: a bundled profile name (see :func:`available_profiles`) or a path
            to a profile JSON; ``None`` for the engine default.
        age_min / age_max / sex_ratio_female: demographic overrides (a profile, if
            given, supplies sex ratio / ethnicity / age bands).

    Returns:
        Cohort: the generated patients plus the resolved ``GenerationConfig``.
    """
    if module not in MODULES:
        raise ValueError(
            f"unknown module {module!r}; choose one of: {', '.join(MODULES)}"
        )
    profile_path = _resolve_profile(profile)
    profile_data = load_population_profile(profile_path) if profile_path else None
    cfg = GenerationConfig(
        patient_count=count,
        seed=seed,
        age_min=age_min,
        age_max=age_max,
        required_condition=MODULES[module],
        sex_ratio_female=profile_data["sex_ratio_female"] if profile_data else sex_ratio_female,
        ethnicity_weights=profile_data["ethnicity_weights"] if profile_data else None,
        include_visits=True,
        include_labs=True,
        visits_min=1,
        visits_max=3,
        synthetic_disclaimer=DEFAULT_SYNTHETIC_DISCLAIMER,
        run_date=date.today().isoformat(),
        age_band_weights=profile_data.get("age_band_weights") if profile_data else None,
        population_profile_path=profile_path,
        profile_name=profile_data["profile_name"] if profile_data else None,
    )
    return Cohort(generate_patients(cfg), cfg)
