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
HipAAsynth Validation Orchestrator
NOOA agent — deterministic wrappers + agentic interpretation layer.
Grounded in the current public engine (v1.3+).

This module lives under ``examples/`` (outside the pure-stdlib ``hipaasynth``
package) because it depends on ``pydantic`` and, in production, on the external
``nooa`` agent runtime. It is an *integration*, not part of the core engine.

Design contract
---------------
* Deterministic methods (plain bodies) wrap engine operations and enforce
  invariants: seed derivation, plan anchoring, zero-PHI screening, and
  adapting a real :class:`hipaasynth.dif.FairnessPassport` into a compact,
  serializable summary.
* Agentic methods (``async def`` + ``...`` body) are executed by the NOOA
  runtime; their docstrings are the runtime prompts. They perform design,
  interpretation, and suggestion — never data generation or metric computation.
  They MUST be ``async``: nooa's metaclass only treats an ``async`` ellipsis
  method as generatable ("sync methods can't generate"), so a sync ``...`` body
  silently returns ``None`` instead of calling the LLM. Await them
  (``await agent.design_experiment(...)``).

Grounding notes (verified against the v1.3 engine)
--------------------------------------------------
* The seven forms match ``hipaasynth.polymorphic.forms.Form`` value-for-value,
  so ``DocumentationForm`` members serialize to the exact string keys the engine
  uses in ``FairnessPassport.decisions``.
* The four metrics match ``hipaasynth.polymorphic.metrics.PolymorphicMetrics``
  (``dcs``/``isg``/``lfdi``/``saf``).
* Seed derivation follows the engine's 32-bit convention
  (``hipaasynth.core.hashing.stable_seed_from_id``), not a 64-bit truncation.
"""

from __future__ import annotations

import hashlib
import json
import platform
import re
import sys
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from pydantic import BaseModel, Field

# Code version of *this orchestrator*, distinct from the engine's ENGINE_VERSION.
# It is sealed into a run's plan anchor and environment manifest so a plan hash
# identifies the exact orchestrator build that produced it, not only the plan
# contents (issue #98, item 3).
ORCHESTRATOR_VERSION = "1.0.0"

# The production runtime supplies the real NOOA Agent base
# (``nooa`` == NVIDIA-labs Object-Oriented Agents; Python >= 3.12). That base is
# metaclass-driven, *not* a pydantic model, and it requires an LLM at
# construction — instantiate as ``HipAAsynthAgent(llm=my_llm)`` or declare one on
# the class (``class HipAAsynthAgent(Agent, llm=my_llm)``), or run inside a
# parent agent's context. Because the real base is not pydantic, class-level
# mutable defaults (e.g. ``run_history``) are shared until reassigned, which is
# why ``__init__`` re-initializes them per instance.
#
# For standalone use (tests, local development, CI without the nooa runtime) fall
# back to a plain pydantic model so the deterministic layer stays importable and
# testable. The fallback needs no LLM; only the agentic methods do.
try:  # pragma: no cover - exercised only where nooa is installed
    from nooa import Agent
except ModuleNotFoundError:  # pragma: no cover - the standalone path
    from pydantic import BaseModel as Agent


# -----------------------------------------------------------------------------
# Exact enumerations from the public engine
# -----------------------------------------------------------------------------

class DocumentationForm(str, Enum):
    """The seven polymorphic documentation forms rendered by HipAAsynth.

    Values are identical to ``hipaasynth.polymorphic.forms.Form`` so that a
    ``DocumentationForm`` used as a dict key serializes to the same string the
    engine emits in ``FairnessPassport.decisions``.
    """
    FHIR_STRUCTURED = "FHIR_STRUCTURED"
    PHYSICIAN_SOAP = "PHYSICIAN_SOAP"
    MIDLEVEL_ABBREVIATED = "MIDLEVEL_ABBREVIATED"
    PATIENT_HIGH_LITERACY = "PATIENT_HIGH_LITERACY"
    PATIENT_LOW_LITERACY = "PATIENT_LOW_LITERACY"
    LEP_TRANSLATED = "LEP_TRANSLATED"
    CHW_SDOH_RICH = "CHW_SDOH_RICH"


class PopulationProfile(str, Enum):
    """Exact profile files available in hipaasynth/profiles/."""
    US_DEFAULT = "us_default"
    MINOT_ND = "minot_nd"                    # rural critical access
    FARGO_ND = "fargo_nd"                    # aging rural composite
    ND_TRIBAL_REGION_A = "nd_tribal_region_a"
    ND_TRIBAL_REGION_A_V2 = "nd_tribal_region_a_v2"
    ND_TRIBAL_REGION_B = "nd_tribal_region_b"
    ND_TRIBAL_REGION_B_V2 = "nd_tribal_region_b_v2"
    KARACHI_PAKISTAN = "karachi_pakistan"
    LAGOS_NIGERIA = "lagos_nigeria"


class ClinicalModule(str, Enum):
    """Calibrated clinical modules available in hipaasynth/modules/."""
    STROKE = "stroke"
    SEPSIS = "sepsis"
    DIABETES = "diabetes"
    COPD = "copd"
    CHF = "chf"
    CARDIOLOGY = "cardiology"
    DMD = "dmd"
    FABRY = "fabry"
    SMA = "sma"
    OUD = "oud"


class FairnessMetric(str, Enum):
    """The four polymorphic fairness metrics on a FairnessPassport.

    Values map to the lowercase fields of
    ``hipaasynth.polymorphic.metrics.PolymorphicMetrics``.
    """
    DCS = "DCS"    # Decision Consistency Score      -> PolymorphicMetrics.dcs
    ISG = "ISG"    # Information-Source Gradient      -> PolymorphicMetrics.isg
    LFDI = "LFDI"  # Linguistic-Form Disadvantage Index -> PolymorphicMetrics.lfdi
    SAF = "SAF"    # SDoH Amplification Factor        -> PolymorphicMetrics.saf


# -----------------------------------------------------------------------------
# Pydantic contracts
# -----------------------------------------------------------------------------

class PopulationSpec(BaseModel):
    """Zero-PHI specification for a synthetic cohort."""
    profile: PopulationProfile
    module: ClinicalModule
    n: int = Field(..., ge=1, le=50_000)
    seed: int
    label: Optional[str] = Field(default=None, max_length=64)


class ExperimentPlan(BaseModel):
    """Reproducible blueprint for a fairness-testing run."""
    run_id: str
    description: str
    populations: List[PopulationSpec]
    model_under_test: Optional[str] = None
    created_at: str
    plan_hash: Optional[str] = None


class FairnessPassportSummary(BaseModel):
    """
    Structured, reproducible record of model behavior across the seven forms.
    Matches the engine's FairnessPassport concept (not a single score).
    """
    run_id: str
    patient_id: Optional[str] = None
    model_under_test: Optional[str] = None
    anchor_sha256: str
    population_spec: PopulationSpec
    per_form_decisions: Dict[DocumentationForm, Any] = Field(default_factory=dict)
    metrics: Dict[FairnessMetric, Any] = Field(default_factory=dict)
    # Forms the engine recorded as refused / unparseable rather than a decision
    # (never silently coerced to False — mirrors FairnessPassport).
    refused_forms: List[DocumentationForm] = Field(default_factory=list)
    unparseable_forms: List[DocumentationForm] = Field(default_factory=list)
    passed: Optional[bool] = None
    synthetic_data_disclaimer: str = (
        "SYNTHETIC DATA ONLY — NOT FOR CLINICAL USE. ZERO PHI. "
        "Informational mapping only. No regulatory claims."
    )
    generated_at: str


class RunSummary(BaseModel):
    """Outcome of validating a single :class:`PopulationSpec` (one cohort).

    A cohort has ``spec.n`` patients, so an audit yields ``n`` per-patient
    passports. ``passports`` holds all of them; ``passport`` is kept as the first
    one for backward compatibility with callers that expect a single value.
    ``artifact_paths`` records where this cohort's card and JSON were written.
    """
    run_id: str
    status: str                          # "completed" | "failed"
    population_spec: PopulationSpec
    passport: Optional[FairnessPassportSummary] = None
    passports: List[FairnessPassportSummary] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)
    log: List[str] = Field(default_factory=list)
    artifact_paths: Dict[str, str] = Field(default_factory=dict)


class EnvironmentManifest(BaseModel):
    """Everything needed to identify the build that produced a run.

    Written alongside the artifacts and folded into the plan anchor so two runs
    against different engine or orchestrator builds cannot collide on the same
    hash (issue #98, item 3/4).
    """
    python_version: str
    platform: str
    engine_version: Optional[str] = None
    form_engine_version: Optional[str] = None
    orchestrator_version: str = ORCHESTRATOR_VERSION
    packages: Dict[str, str] = Field(default_factory=dict)
    created_at: str

    def anchor_payload(self) -> Dict[str, Any]:
        """The subset of the manifest that identifies the build (no wall-clock)."""
        return {
            "python_version": self.python_version,
            "engine_version": self.engine_version,
            "form_engine_version": self.form_engine_version,
            "orchestrator_version": self.orchestrator_version,
        }


class PlanRun(BaseModel):
    """Result of :meth:`HipAAsynthAgent.run_validation` over a whole plan.

    ``status`` is ``"completed"`` when every population produced a passport,
    ``"partial"`` when some failed, ``"failed"`` when none succeeded.
    ``artifact_paths`` maps a stable name (``plan``, ``manifest``, ``checkpoint``,
    ``run``) to the file that a third party reads to reproduce the run.
    """
    run_id: str
    status: str
    plan: ExperimentPlan
    run_anchor_sha256: str
    manifest: EnvironmentManifest
    summaries: List[RunSummary] = Field(default_factory=list)
    log: List[str] = Field(default_factory=list)
    artifact_paths: Dict[str, str] = Field(default_factory=dict)


class Interpretation(BaseModel):
    """Agentic output of ``interpret_passport``.

    ``form_level_notes`` / ``metric_notes`` are keyed by plain strings (the
    form/metric name, e.g. ``"FHIR_STRUCTURED"``) rather than
    ``DocumentationForm``/``FairnessMetric`` enum members. Pydantic renders an
    enum-keyed ``Dict`` as a ``propertyNames`` constraint referencing a shared
    ``$defs`` entry; empirically, xAI's structured-output schema validator
    rejects that shape with "unresolvable $ref '#/$defs/...': key '$defs' not
    found in schema" when the LLM is asked to generate this model directly.
    Plain string keys produce a self-contained schema with no ``$defs``/``$ref``
    and are unaffected. Since both enums mix in ``str``, an enum member still
    compares equal to (and hashes the same as) its string value, so existing
    lookups like ``DocumentationForm.FHIR_STRUCTURED in notes`` keep working.
    """

    run_id: str
    summary: str
    form_level_notes: Dict[str, str] = Field(default_factory=dict)
    metric_notes: Dict[str, str] = Field(default_factory=dict)
    caveats: List[str] = Field(default_factory=list)
    zero_phi_confirmed: bool = True
    no_regulatory_claims: bool = True


class SuggestedTest(BaseModel):
    rationale: str
    proposed_spec: PopulationSpec
    priority: str = Field(default="medium")  # "high" | "medium" | "low"
    depends_on_run_ids: List[str] = Field(default_factory=list)


# -----------------------------------------------------------------------------
# Zero-PHI label screening
# -----------------------------------------------------------------------------

# The only free-text attack surface on a PopulationSpec is ``label``. Everything
# else is an enum or a bounded integer. These patterns screen a label for
# content that could carry PHI. This is a conservative *screen*, not a proof of
# de-identification — but unlike the original (which could never fail) it
# actually rejects the obvious carriers.
_PHI_LABEL_PATTERNS: tuple[tuple[str, "re.Pattern[str]"], ...] = (
    ("email address", re.compile(r"[^\s@]+@[^\s@]+\.[^\s@]+")),
    # 3+ consecutive digits catch MRNs, phone numbers, ZIP codes, SSNs, and
    # date fragments. A synthetic-cohort label has no business carrying them.
    ("numeric identifier / date digits", re.compile(r"\d{3,}")),
    ("date-like token", re.compile(r"\b\d{1,2}[/-]\d{1,2}([/-]\d{2,4})?\b")),
    ("street address", re.compile(
        r"\b\d+\s+\w+.*\b(st|street|ave|avenue|rd|road|blvd|ln|lane|dr|drive)\b",
        re.IGNORECASE,
    )),
    ("PHI keyword", re.compile(
        r"\b(mrn|ssn|dob|d\.o\.b|patient\s+name|phone|npi|medicaid|medicare)\b",
        re.IGNORECASE,
    )),
)


# -----------------------------------------------------------------------------
# Agent
# -----------------------------------------------------------------------------

class HipAAsynthAgent(Agent):
    """
    Careful validation orchestrator for the public HipAAsynth engine.

    Deterministic methods wrap engine operations and enforce invariants.
    Agentic methods (`async def` + `...` body) perform design, interpretation,
    and suggestion; their docstrings are the runtime prompts. Await them.
    """

    # Durable state
    active_run_id: Optional[str] = None
    active_profile: Optional[PopulationProfile] = None
    base_seed: int = 42
    run_history: List[RunSummary] = []
    interpretation_history: List[Interpretation] = []
    pending_suggestions: List[SuggestedTest] = []

    def __init__(self, **data):
        # ``data`` is forwarded verbatim to the base. Under the real nooa runtime
        # that means framework kwargs (``llm=``, ``storage=``, ...); an ``llm`` is
        # required there. Under the pydantic fallback it means field values.
        # The list re-initialization below is required on the non-pydantic base,
        # where the class-level ``[]`` defaults are otherwise shared across
        # instances (verified against nooa.Agent).
        super().__init__(**data)
        self.run_history = list(self.run_history or [])
        self.interpretation_history = list(self.interpretation_history or [])
        self.pending_suggestions = list(self.pending_suggestions or [])

    # ------------------------------------------------------------------
    # Deterministic tools
    # ------------------------------------------------------------------

    def derive_seed(self, user_seed: int, profile: PopulationProfile, module: ClinicalModule, tag: str) -> int:
        """Deterministic seed derivation. Same inputs always produce the same integer.

        Returns a 32-bit unsigned integer, matching the engine's own convention
        (``hipaasynth.core.hashing.stable_seed_from_id`` takes the first four
        bytes of a SHA-256 digest). The original implementation returned a
        64-bit value (``digest[:16]``), which is inconsistent with the engine
        and can silently drift when a seed is round-tripped through a 32-bit
        RNG entry point.
        """
        payload = f"{user_seed}|{profile.value}|{module.value}|{tag}"
        digest = hashlib.sha256(payload.encode()).hexdigest()
        return int(digest[:8], 16)  # first 4 bytes -> 32-bit unsigned int

    def anchor_plan(
        self, plan: ExperimentPlan, build: Optional[Dict[str, Any]] = None
    ) -> str:
        """SHA-256 anchor over a canonical ExperimentPlan.

        When ``build`` is given (e.g. :meth:`EnvironmentManifest.anchor_payload`),
        the engine version, orchestrator version, and Python version are folded
        into the hash so two runs of the *same plan* against *different builds*
        do not collide on one anchor (issue #98, item 3). ``build=None``
        preserves the original plan-only hash, so ``design_experiment`` and any
        existing anchor stay byte-for-byte unchanged.
        """
        canonical = {
            "run_id": plan.run_id,
            "description": plan.description,
            "populations": [
                {
                    "profile": p.profile.value,
                    "module": p.module.value,
                    "n": p.n,
                    "seed": p.seed,
                    "label": p.label,
                }
                for p in plan.populations
            ],
            "model_under_test": plan.model_under_test,
        }
        if build is not None:
            canonical["build"] = build
        payload = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode()).hexdigest()

    def zero_phi_reasons(self, spec: PopulationSpec) -> List[str]:
        """Return the reasons ``spec`` fails the zero-PHI screen (empty == clean).

        The structural guarantee is that a spec only carries enums and bounded
        integers plus one short free-text ``label``; this method scrutinizes the
        label, the sole place text can hide.
        """
        reasons: List[str] = []
        label = spec.label
        if not label:
            return reasons
        if len(label) > 64:  # defense in depth; the field also enforces this
            reasons.append("label exceeds 64 characters")
        for description, pattern in _PHI_LABEL_PATTERNS:
            if pattern.search(label):
                reasons.append(f"label matched {description}")
        return reasons

    def verify_zero_phi(self, spec: PopulationSpec) -> bool:
        """Structural + textual zero-PHI screen.

        Returns True only when the spec carries no label content resembling
        PHI. The original version checked only ``len(label) > 64`` — a branch
        that can never be True because the field already caps the length, so it
        always returned True and provided false assurance.
        """
        return not self.zero_phi_reasons(spec)

    def assemble_passport(
        self,
        run_id: str,
        spec: PopulationSpec,
        per_form_decisions: Dict[DocumentationForm, Any],
        metrics: Dict[FairnessMetric, Any],
        generated_at: str,
        model_under_test: Optional[str] = None,
        passed: Optional[bool] = None,
        refused_forms: Optional[List[DocumentationForm]] = None,
        unparseable_forms: Optional[List[DocumentationForm]] = None,
        patient_id: Optional[str] = None,
    ) -> FairnessPassportSummary:
        """Wrap already-generated engine output into a FairnessPassportSummary.

        Refuses to assemble a passport for a spec that fails the zero-PHI screen
        — a summary is a shareable artifact, so PHI must be caught here, not
        merely at plan design time.
        """
        phi_reasons = self.zero_phi_reasons(spec)
        if phi_reasons:
            raise ValueError(
                "refusing to assemble passport for a spec that failed the "
                f"zero-PHI screen: {'; '.join(phi_reasons)}"
            )
        canonical = {
            "run_id": run_id,
            "profile": spec.profile.value,
            "module": spec.module.value,
            "n": spec.n,
            "seed": spec.seed,
            "forms": sorted(k.value for k in per_form_decisions),
            "metrics": sorted(k.value for k in metrics),
        }
        payload = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
        anchor = hashlib.sha256(payload.encode()).hexdigest()
        return FairnessPassportSummary(
            run_id=run_id,
            patient_id=patient_id,
            model_under_test=model_under_test,
            anchor_sha256=anchor,
            population_spec=spec,
            per_form_decisions=per_form_decisions,
            metrics=metrics,
            refused_forms=list(refused_forms or []),
            unparseable_forms=list(unparseable_forms or []),
            passed=passed,
            generated_at=generated_at,
        )

    def from_engine_passport(
        self,
        engine_passport: Any,
        run_id: str,
        spec: PopulationSpec,
        generated_at: Optional[str] = None,
    ) -> FairnessPassportSummary:
        """Adapt a real ``hipaasynth.dif.FairnessPassport`` into a summary.

        Duck-typed on purpose so this example does not hard-import the engine:
        ``engine_passport`` need only expose ``decisions`` (dict keyed by form
        name), ``metrics`` (a ``PolymorphicMetrics``), ``patient_id``,
        ``device_name``/``device_version``, ``anchor_hash``, and ``passed()``.

        This is the bridge the original file was missing: it lets the
        orchestrator consume genuine engine output rather than hand-built dicts.
        """
        # Map string form names to DocumentationForm, ignoring anything that is
        # not one of the seven canonical forms.
        valid = {f.value for f in DocumentationForm}
        per_form: Dict[DocumentationForm, Any] = {
            DocumentationForm(name): decision
            for name, decision in dict(engine_passport.decisions).items()
            if name in valid
        }

        m = engine_passport.metrics
        metrics: Dict[FairnessMetric, Any] = {
            FairnessMetric.DCS: {"value": m.dcs, "pass": m.dcs_pass},
            FairnessMetric.ISG: {"value": m.isg, "pass": m.isg_pass},
            FairnessMetric.LFDI: {"value": m.lfdi, "pass": m.lfdi_pass},
            FairnessMetric.SAF: {"value": m.saf, "pass": m.saf_pass},
        }

        def _to_forms(names: Any) -> List[DocumentationForm]:
            return [DocumentationForm(n) for n in (names or []) if n in valid]

        device = getattr(engine_passport, "device_name", None)
        version = getattr(engine_passport, "device_version", None)
        model_under_test = f"{device} {version}".strip() if device else None

        summary = self.assemble_passport(
            run_id=run_id,
            spec=spec,
            per_form_decisions=per_form,
            metrics=metrics,
            generated_at=generated_at or datetime.now(timezone.utc).isoformat(),
            model_under_test=model_under_test,
            passed=bool(engine_passport.passed()),
            refused_forms=_to_forms(getattr(engine_passport, "refused_forms", None)),
            unparseable_forms=_to_forms(getattr(engine_passport, "unparseable_forms", None)),
            patient_id=getattr(engine_passport, "patient_id", None),
        )
        # Prefer the engine's own generation anchor when present; it seals the
        # summary back to the exact synthetic cohort.
        engine_anchor = getattr(engine_passport, "anchor_hash", None)
        if engine_anchor:
            summary = summary.model_copy(update={"anchor_sha256": engine_anchor})
        return summary

    def synthesize_run_summary(
        self,
        run_id: str,
        spec: PopulationSpec,
        passport: Optional[FairnessPassportSummary],
        errors: List[str],
        log: Optional[List[str]] = None,
    ) -> RunSummary:
        status = "completed" if (passport is not None and not errors) else "failed"
        return RunSummary(
            run_id=run_id,
            status=status,
            population_spec=spec,
            passport=passport,
            passports=[passport] if passport is not None else [],
            errors=errors,
            log=log or [],
        )

    # ------------------------------------------------------------------
    # End-to-end validation run (issue #98)
    # ------------------------------------------------------------------

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def _log(self, log: List[str], message: str) -> None:
        """Append a timestamped entry to a run/step log (issue #98, item 5)."""
        log.append(f"{self._now()} {message}")

    def environment_manifest(self) -> EnvironmentManifest:
        """Capture the build that is about to produce a run (issue #98, item 4).

        Engine/form-engine versions are read from the engine when it is
        importable; under the standalone pydantic fallback they stay ``None`` and
        the manifest still identifies the Python + orchestrator build.
        """
        engine_version: Optional[str] = None
        form_engine_version: Optional[str] = None
        try:  # pragma: no cover - trivially exercised when the engine is present
            from hipaasynth.core.config import ENGINE_VERSION
            from hipaasynth.polymorphic.forms import FORM_ENGINE_VERSION

            engine_version = ENGINE_VERSION
            form_engine_version = FORM_ENGINE_VERSION
        except Exception:  # pragma: no cover - the engine-absent path
            pass

        packages: Dict[str, str] = {}
        try:
            from importlib.metadata import PackageNotFoundError, version

            for pkg in ("hipaasynth", "pydantic"):
                try:
                    packages[pkg] = version(pkg)
                except PackageNotFoundError:
                    continue
        except Exception:  # pragma: no cover - importlib.metadata always present on 3.8+
            pass

        return EnvironmentManifest(
            python_version=platform.python_version(),
            platform=platform.platform(),
            engine_version=engine_version,
            form_engine_version=form_engine_version,
            packages=packages,
            created_at=self._now(),
        )

    def _spec_to_gen_config(self, spec: PopulationSpec) -> Any:
        """Build a real engine ``GenerationConfig`` from a zero-PHI spec.

        Mirrors ``hipaasynth.sdk.generate``: the profile supplies sex ratio,
        ethnicity weights, and age bands; ``module`` becomes the
        ``required_condition`` so every synthetic patient carries the condition
        under test. The engine is imported lazily so the deterministic layer
        stays importable without it (module design contract).
        """
        import hipaasynth
        from hipaasynth.core.config import GenerationConfig
        from hipaasynth.core.profile_loader import load_population_profile

        profiles_dir = Path(hipaasynth.__file__).resolve().parent / "profiles"
        profile_path = profiles_dir / f"{spec.profile.value}.json"
        if not profile_path.is_file():
            raise FileNotFoundError(
                f"bundled profile {spec.profile.value!r} not found at {profile_path}"
            )
        profile_data = load_population_profile(str(profile_path))
        return GenerationConfig(
            patient_count=spec.n,
            seed=spec.seed,
            required_condition=spec.module.value,
            sex_ratio_female=profile_data["sex_ratio_female"],
            ethnicity_weights=profile_data["ethnicity_weights"],
            age_band_weights=profile_data.get("age_band_weights"),
            population_profile_path=str(profile_path),
            profile_name=profile_data["profile_name"],
        )

    @staticmethod
    def _spec_key(index: int, spec: PopulationSpec) -> str:
        """Stable identity of a population within a plan, for checkpoint matching."""
        canonical = json.dumps(
            {
                "i": index,
                "profile": spec.profile.value,
                "module": spec.module.value,
                "n": spec.n,
                "seed": spec.seed,
                "label": spec.label,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode()).hexdigest()[:16]

    def run_validation(
        self,
        plan: ExperimentPlan,
        model: Any,
        *,
        output_dir: Any,
        dif_config: Any = None,
        resume: bool = True,
        generate_fn: Optional[Callable[[Any], Any]] = None,
        audit_fn: Optional[Callable[..., Any]] = None,
    ) -> PlanRun:
        """Drive a whole plan from preregistration to signed cards (issue #98).

        For every :class:`PopulationSpec` in ``plan`` this runs the real engine
        chain — generate → audit → adapt → card — and writes reproducible
        artifacts under ``output_dir``::

            output_dir/
              plan.json                     the preregistered plan (+ run anchor)
              manifest.json                 the build that produced this run
              checkpoint.json               per-population resume state
              run.json                      the full PlanRun
              populations/NN_profile_module/
                summary.md                  the cohort fairness card (the deliverable)
                patients/<id>.md            each patient's own passport card
                passports.json              the adapted FairnessPassportSummary list

        Args:
            plan: a plan from ``design_experiment`` (or hand-built).
            model: any object with ``predict(patient, form) -> bool | DecisionResult``.
            output_dir: run directory (created if absent).
            dif_config: optional ``hipaasynth.dif.framework.DIFConfig``.
            resume: reuse a matching ``checkpoint.json`` and skip completed
                populations instead of regenerating them (issue #98, item 5).
            generate_fn / audit_fn: injectable engine entry points; default to
                ``generate_patients`` / ``run_audit``. Provided for tests and for
                running against a patched engine.

        Returns:
            PlanRun: the run's status, per-population summaries, log, and the
            paths of every artifact written.
        """
        try:
            from hipaasynth.dif.framework import run_audit as _run_audit
            from hipaasynth.dif.report import write_passport_bundle  # noqa: F401 (engine presence check)
            from hipaasynth.pipelines.population_pipeline import (
                generate_patients as _generate_patients,
            )
        except Exception as exc:  # pragma: no cover - engine-absent path
            raise RuntimeError(
                "run_validation requires the hipaasynth engine to be installed "
                "(it drives generate_patients + run_audit). Install the package "
                "to run an end-to-end validation."
            ) from exc

        generate_fn = generate_fn or _generate_patients
        audit_fn = audit_fn or _run_audit

        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        populations_dir = out / "populations"
        populations_dir.mkdir(exist_ok=True)

        log: List[str] = []
        manifest = self.environment_manifest()
        run_anchor = self.anchor_plan(plan, build=manifest.anchor_payload())
        self._log(
            log,
            f"run {plan.run_id!r} started: {len(plan.populations)} population(s), "
            f"engine={manifest.engine_version}, orchestrator={manifest.orchestrator_version}, "
            f"anchor={run_anchor[:12]}…",
        )

        # Persist the preregistered plan (with its run anchor) and the manifest up
        # front, so even an interrupted run leaves a reproducible record.
        plan_path = out / "plan.json"
        anchored_plan = plan.model_copy(update={"plan_hash": run_anchor})
        plan_path.write_text(anchored_plan.model_dump_json(indent=2), encoding="utf-8")
        manifest_path = out / "manifest.json"
        manifest_path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")

        checkpoint_path = out / "checkpoint.json"
        completed = self._load_checkpoint(checkpoint_path, run_anchor, resume, log)

        summaries: List[RunSummary] = []
        for i, spec in enumerate(plan.populations):
            key = self._spec_key(i, spec)
            if key in completed:
                summary = RunSummary.model_validate(completed[key])
                self._log(
                    log,
                    f"population {i} ({spec.profile.value}/{spec.module.value}) "
                    "skipped — already completed (resumed from checkpoint)",
                )
                summaries.append(summary)
                continue

            summary = self._run_one_population(
                run_id=plan.run_id,
                index=i,
                spec=spec,
                model=model,
                populations_dir=populations_dir,
                dif_config=dif_config,
                generate_fn=generate_fn,
                audit_fn=audit_fn,
                log=log,
            )
            summaries.append(summary)
            if summary.status == "completed":
                completed[key] = summary.model_dump(mode="json")
                self._write_checkpoint(checkpoint_path, plan.run_id, run_anchor, completed)

        n_ok = sum(1 for s in summaries if s.status == "completed")
        if n_ok == len(summaries):
            status = "completed"
        elif n_ok == 0:
            status = "failed"
        else:
            status = "partial"
        self._log(log, f"run {plan.run_id!r} {status}: {n_ok}/{len(summaries)} population(s) ok")

        artifact_paths = {
            "plan": str(plan_path),
            "manifest": str(manifest_path),
            "checkpoint": str(checkpoint_path),
            "run": str(out / "run.json"),
        }
        run = PlanRun(
            run_id=plan.run_id,
            status=status,
            plan=anchored_plan,
            run_anchor_sha256=run_anchor,
            manifest=manifest,
            summaries=summaries,
            log=log,
            artifact_paths=artifact_paths,
        )
        (out / "run.json").write_text(run.model_dump_json(indent=2), encoding="utf-8")
        return run

    def _run_one_population(
        self,
        *,
        run_id: str,
        index: int,
        spec: PopulationSpec,
        model: Any,
        populations_dir: Path,
        dif_config: Any,
        generate_fn: Callable[[Any], Any],
        audit_fn: Callable[..., Any],
        log: List[str],
    ) -> RunSummary:
        """Run generate → audit → adapt → card for one population spec."""
        step_log: List[str] = []
        label = f"{spec.profile.value}/{spec.module.value} n={spec.n}"

        phi_reasons = self.zero_phi_reasons(spec)
        if phi_reasons:
            msg = f"population {index} ({label}) refused: zero-PHI screen failed: {'; '.join(phi_reasons)}"
            self._log(log, msg)
            self._log(step_log, msg)
            return RunSummary(
                run_id=run_id, status="failed", population_spec=spec,
                errors=phi_reasons, log=step_log,
            )

        from hipaasynth.dif.report import write_passport_bundle

        spec_dir = populations_dir / f"{index:02d}_{spec.profile.value}_{spec.module.value}"
        try:
            self._log(step_log, f"population {index} ({label}) generating + auditing")
            gen_config = self._spec_to_gen_config(spec)
            engine_passports = audit_fn(model, generate_fn, gen_config, dif_config)
            if not engine_passports:
                raise ValueError("audit produced no passports (empty cohort?)")

            generated_at = self._now()
            passport_summaries = [
                self.from_engine_passport(ep, run_id=run_id, spec=spec, generated_at=generated_at)
                for ep in engine_passports
            ]
            self._log(
                step_log,
                f"population {index} ({label}) audited {len(engine_passports)} patient(s); "
                f"{sum(1 for ep in engine_passports if ep.passed())} passed",
            )

            # Render the deliverable card(s) from the real engine passports, then
            # record the adapted summaries next to them.
            bundle = write_passport_bundle(engine_passports, spec_dir)
            passports_json = spec_dir / "passports.json"
            passports_json.write_text(
                json.dumps([s.model_dump(mode="json") for s in passport_summaries], indent=2),
                encoding="utf-8",
            )
            artifact_paths = {
                "card": str(bundle["summary_path"]),
                "passports": str(passports_json),
                "patients_dir": str(spec_dir / "patients"),
            }
            self._log(step_log, f"population {index} ({label}) wrote card {bundle['summary_path']}")
            self._log(log, f"population {index} ({label}) completed → {bundle['summary_path']}")

            return RunSummary(
                run_id=run_id,
                status="completed",
                population_spec=spec,
                passport=passport_summaries[0],
                passports=passport_summaries,
                log=step_log,
                artifact_paths=artifact_paths,
            )
        except Exception as exc:  # a failed population must not abort the plan
            msg = f"population {index} ({label}) failed: {type(exc).__name__}: {exc}"
            self._log(log, msg)
            self._log(step_log, msg)
            return RunSummary(
                run_id=run_id, status="failed", population_spec=spec,
                errors=[str(exc)], log=step_log,
            )

    def _load_checkpoint(
        self, path: Path, run_anchor: str, resume: bool, log: List[str]
    ) -> Dict[str, Any]:
        """Load resumable per-population state, or start clean.

        A checkpoint is reused only when ``resume`` is True and it was written for
        the same run anchor (same plan + same build); a stale checkpoint is
        ignored rather than mixing results across builds.
        """
        if not resume or not path.is_file():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            self._log(log, "checkpoint unreadable — starting fresh")
            return {}
        if data.get("run_anchor") != run_anchor:
            self._log(log, "checkpoint anchor mismatch (plan or build changed) — starting fresh")
            return {}
        completed = data.get("completed", {})
        self._log(log, f"resuming from checkpoint: {len(completed)} population(s) already done")
        return completed

    def _write_checkpoint(
        self, path: Path, run_id: str, run_anchor: str, completed: Dict[str, Any]
    ) -> None:
        payload = {"run_id": run_id, "run_anchor": run_anchor, "completed": completed}
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    # ------------------------------------------------------------------
    # Groundedness — assert an interpretation cites only what the passport holds
    # ------------------------------------------------------------------

    @staticmethod
    def _collect_floats(node: Any, out: List[float]) -> None:
        """Recursively gather every numeric leaf under ``node``."""
        if isinstance(node, bool):
            return
        if isinstance(node, (int, float)):
            out.append(float(node))
        elif isinstance(node, dict):
            for v in node.values():
                HipAAsynthAgent._collect_floats(v, out)
        elif isinstance(node, (list, tuple)):
            for v in node:
                HipAAsynthAgent._collect_floats(v, out)

    def groundedness_violations(
        self, interpretation: Interpretation, summary: FairnessPassportSummary
    ) -> List[str]:
        """Return the ways ``interpretation`` cites something not in ``summary``.

        An empty list means every form name, metric name, and decimal number in
        the interpretation is present in the source passport (issue #98, item 6).
        This is a deterministic groundedness check on otherwise free-text LLM
        output: it does not verify the *prose*, but it makes fabricating a form,
        a metric, or a numeric value fail loudly instead of reading as fact.

        Checks:
          * every key in ``form_level_notes`` is one of the seven forms *and* is
            present in the passport (a decision, or a refused/unparseable form);
          * every key in ``metric_notes`` is one of the four metrics present in
            the passport;
          * every decimal number (e.g. ``0.92``) written anywhere in the
            interpretation matches, at the precision written, a numeric value the
            passport actually records.
        """
        violations: List[str] = []
        valid_forms = {f.value for f in DocumentationForm}
        present_forms = (
            {k.value for k in summary.per_form_decisions}
            | {f.value for f in summary.refused_forms}
            | {f.value for f in summary.unparseable_forms}
        )
        for key in interpretation.form_level_notes:
            if key not in valid_forms:
                violations.append(f"form_level_notes cites unknown form {key!r}")
            elif key not in present_forms:
                violations.append(
                    f"form_level_notes cites form {key!r} that is absent from the passport"
                )

        valid_metrics = {m.value for m in FairnessMetric}
        present_metrics = {m.value for m in summary.metrics}
        for key in interpretation.metric_notes:
            if key not in valid_metrics:
                violations.append(f"metric_notes cites unknown metric {key!r}")
            elif key not in present_metrics:
                violations.append(
                    f"metric_notes cites metric {key!r} that is absent from the passport"
                )

        grounded: List[float] = []
        self._collect_floats(list(summary.metrics.values()), grounded)

        def _is_grounded(token: str) -> bool:
            ndigits = len(token.split(".")[1])
            target = round(float(token), ndigits)
            return any(round(g, ndigits) == target for g in grounded)

        texts: List[str] = [interpretation.summary]
        texts.extend(interpretation.form_level_notes.values())
        texts.extend(interpretation.metric_notes.values())
        texts.extend(interpretation.caveats)
        seen: set = set()
        for text in texts:
            for token in re.findall(r"\d+\.\d+", text):
                if token in seen:
                    continue
                seen.add(token)
                if not _is_grounded(token):
                    violations.append(
                        f"cites numeric value {token} not present in the passport metrics"
                    )
        return violations

    def assert_grounded(
        self, interpretation: Interpretation, summary: FairnessPassportSummary
    ) -> None:
        """Raise ``ValueError`` if ``interpretation`` is not grounded in ``summary``.

        The loud counterpart to :meth:`groundedness_violations`, for callers that
        want an ungrounded interpretation to fail rather than be returned.
        """
        violations = self.groundedness_violations(interpretation, summary)
        if violations:
            raise ValueError(
                "interpretation is not grounded in its passport: " + "; ".join(violations)
            )

    # ------------------------------------------------------------------
    # Agentic methods
    # ------------------------------------------------------------------

    async def design_experiment(
        self,
        operator_request: str,
        prior_interpretations: Optional[List[Interpretation]] = None,
    ) -> ExperimentPlan:
        """
        Convert a natural-language operator request into a deterministic,
        zero-PHI ExperimentPlan using only the real HipAAsynth profiles and modules.

        Instructions:
        1. Use only PopulationProfile and ClinicalModule enum values.
           Prefer minot_nd, fargo_nd, nd_tribal_region_a/b (and v2) when rural or
           tribal coverage is requested. Prefer stroke or sepsis when clinical
           focus is ambiguous.
        2. Every PopulationSpec must carry an explicit integer seed. If omitted,
           derive it with self.derive_seed using a stable tag from the request.
        3. Reject any request that implies real PHI (names, MRNs, DOB, addresses,
           facility names, device IDs). Only profile, module, n, and seed are
           allowed. Before returning, call self.verify_zero_phi on every
           PopulationSpec and refuse the plan if any spec fails.
        4. Call self.anchor_plan and store the result in plan_hash.
        5. Set created_at to an ISO-8601 UTC timestamp.
        6. Do not generate patients, compute metrics, or invent data.
        """
        ...

    async def interpret_passport(
        self,
        passport: FairnessPassportSummary,
        operator_question: Optional[str] = None,
    ) -> Interpretation:
        """
        Produce a conservative Interpretation of a FairnessPassportSummary.

        Instructions:
        1. Narrate per_form_decisions for the seven forms without inventing
           values. Forms listed in passport.refused_forms or
           unparseable_forms have NO decision — say so; never treat them as a
           negative decision. Key form_level_notes by the plain form name
           string (e.g. "FHIR_STRUCTURED"), one entry per form discussed.
        2. Comment on the four metrics (DCS, ISG, LFDI, SAF) using the values
           present. Each metric value carries a {"value", "pass"} pair when the
           summary came from a real engine passport. Key metric_notes by the
           plain metric name string (e.g. "DCS").
        3. Use cautious language: these are documentation-form effects on
           synthetic patients, not evidence of real-world bias or clinical
           validity.
        4. Always include the standard caveats: synthetic data only, zero PHI,
           informational mapping only, no regulatory or diagnostic claims.
        5. Set zero_phi_confirmed=True only if self.verify_zero_phi is True for
           passport.population_spec.
        6. Do not recompute hashes or generate new data.
        """
        ...

    async def suggest_next_tests(
        self,
        summaries: List[RunSummary],
        interpretations: List[Interpretation],
        operator_budget: Optional[int] = None,
    ) -> List[SuggestedTest]:
        """
        Suggest 1–3 next experiments using real profiles and modules.

        Instructions:
        1. Look for missing coverage of minot_nd, fargo_nd, nd_tribal_region_*,
           or under-tested modules (stroke, sepsis, etc.).
        2. Every proposed PopulationSpec must have an explicit seed (use
           self.derive_seed if needed). Never call random.
        3. Rationale must cite specific prior results or their absence.
        4. Respect operator_budget as a hard ceiling on n.
        5. Stay strictly inside zero-PHI, synthetic-only scope; every proposed
           spec must pass self.verify_zero_phi.
        """
        ...

    async def explain_form_disparity(
        self,
        passport: FairnessPassportSummary,
        form_a: DocumentationForm,
        form_b: DocumentationForm,
    ) -> str:
        """
        Explain the difference between two polymorphic forms for the same
        synthetic cohort.

        Instructions:
        1. Compare only the values already present in passport.per_form_decisions.
        2. Use cautious, non-causal language.
        3. Attribute differences to documentation-form effects (structure,
           literacy level, SDoH richness, translation, abbreviation density).
        4. End with the standard synthetic-data + no-regulatory-claims disclaimer.
        5. Return plain text only.
        """
        ...


if __name__ == "__main__":  # pragma: no cover - manual smoke check
    agent = HipAAsynthAgent()
    seed = agent.derive_seed(42, PopulationProfile.MINOT_ND, ClinicalModule.STROKE, "demo")
    clean = PopulationSpec(
        profile=PopulationProfile.MINOT_ND,
        module=ClinicalModule.STROKE,
        n=100,
        seed=seed,
        label="rural-stroke-pilot",
    )
    dirty = clean.model_copy(update={"label": "John Doe MRN 12345"})
    print(f"derived seed = {seed}  (32-bit: {seed < 2**32})")
    print(f"clean label passes zero-PHI screen: {agent.verify_zero_phi(clean)}")
    print(f"PHI-ish label reasons: {agent.zero_phi_reasons(dirty)}")
