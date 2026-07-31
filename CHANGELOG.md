# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.4.0] — 2026-07-30

Interoperability and access. Earlier releases exposed the engine as an
importable Python package. This release adds a CLI, a REST API, an SDK, a web
UI, warehouse connectors, and container artifacts, without changing how
generation works. Determinism, the stdlib-only core, and zero PHI are
preserved: the core installs with no third-party dependencies, and every
integration that needs one is an optional extra, lazily imported.

Note on versioning: this entry covers work merged in PRs #81 and #83–#86, which
landed while the version string stayed at 1.3.0. Because `ENGINE_VERSION` is
sealed into every FairnessPassport, passports produced during that window record
`1.3.0` and cannot be distinguished by version from pre-1.4.0 output. If you are
reproducing a passport generated between 2026-07-27 and 2026-07-30, identify the
engine by commit rather than by the recorded version.
`tests/test_version_consistency.py` now prevents this from recurring.

### Added

- **CLI entry point** — `pip install hipaasynth` provides a `hipaasynth` command
  (`[project.scripts]`), with `--format {json,csv,fhir-bundle,ndjson,parquet,omop}`,
  `--scenario`, `--module`, `--viz`, and `--validate`. Existing flags and default
  output are unchanged.
- **REST API** (`hipaasynth/api.py`) — stdlib `http.server`, no framework
  dependency. `GET /health`, `/formats`, `/scenarios`, `GET|POST /generate`,
  `GET /viz/demographics`, `GET /viz/fairness`, and the web UI at `GET /`.
  NDJSON responses are chunk-streamed; `profile` is restricted to bundled names.
- **Python SDK** (`hipaasynth/sdk.py`) — `hipaasynth.generate(...) -> Cohort`,
  iterable and indexable, with `to_json`/`to_csv`/`to_fhir_bundle`/`to_ndjson`/
  `to_omop`/`to_parquet`, plus `validate()` and `summary()`.
- **Web UI** (`hipaasynth/ui/index.html`) — dependency-free HTML/CSS/JS served
  from the API on the same origin. Pick a module, profile, size and seed;
  preview a real sample record; download in any supported format.
- **Scenario blueprints** (`hipaasynth/scenarios.json`, `scenarios.py`) — eight
  named module+profile pairings (e.g. `tribal_sepsis` = `sepsis` +
  `nd_tribal_region_a`), validated at load against the real module and profile
  registries so an unknown name fails immediately.
- **SVG visualization** (`hipaasynth/viz/`) — hand-rolled, dependency-free
  cohort demographics and a per-form fairness heatmap.
- **OMOP/FHIR interoperability** — `MedicationRequest` alongside the existing
  `MedicationStatement`, FHIR Bulk Data NDJSON export, an offline structural
  FHIR validator, OMOP CDM 5.4 completion (`OBSERVATION_PERIOD`, visit linkage,
  full column set), and optional Parquet export via the `[parquet]` extra.
- **DuckDB connector** (`hipaasynth/connectors/duckdb.py`) — loads a cohort into
  a real DuckDB file as typed OMOP tables or the flat patient table. Optional
  `[duckdb]` extra, lazily imported.
- **BigQuery schema generation** (`hipaasynth/connectors/bigquery.py`) — emits
  GoogleSQL DDL, JSON load schemas, `LOAD DATA` statements and `bq` CLI strings.
  Text generation only: it never contacts BigQuery and adds no dependency.
- **Container artifacts** — `Dockerfile` (non-root, stdlib `/health`
  healthcheck) and a single-service `docker-compose.yml`.
- **Validation and fidelity suite** — statistical fidelity
  (`validation/fidelity.py`), a downstream-utility probe
  (`validation/utility_probe.py`), clinical-plausibility rules, and audit
  stability metrics (`dif/stability.py`: seed drift, bootstrap CI, threshold
  sensitivity). Each statistic is tested against a constructed case with a
  known analytic answer.
- **NOOA validation orchestrator** (`examples/nooa_validation_orchestrator.py`)
  — an example agent pairing deterministic, engine-grounded wrappers with an
  LLM interpretation layer. Verified end-to-end against a live model.

### Changed

- `ENGINE_VERSION` and `pyproject.toml`'s `version` are now covered by
  `tests/test_version_consistency.py`, which also requires a CHANGELOG entry for
  the current version. They were previously independent literals.
- The CI zero-dependency check uses a per-file allowlist, so the stdlib-only
  guarantee is enforced per module rather than waived wholesale.
- **`hipaasynth.validation` has a public surface.** It re-exports the validator,
  fidelity and utility-probe APIs. Its `__init__.py` was previously empty, so
  `fidelity` and `utility_probe` were reachable only by full module path and had
  no caller anywhere in the tree. `Cohort.fidelity()` and `Cohort.utility()` on
  the SDK expose the same statistics next to the existing `Cohort.validate()`.
- **CI exercises the optional capabilities.** A second `capabilities` job
  installs the `test-full` extra (which pulls `parquet`, `duckdb`,
  `test-browser` and `examples`), installs Chromium, and fails if *any* test
  reports skipped — parsed from the JUnit XML rather than scraped from stdout.
  The original job still installs only `[dev]`; its skips are intentional and
  are what prove the core needs no third-party packages. Before this, 11 tests
  skipped on every run, including every DuckDB and headless-browser test, so
  the capabilities they exist to prove were never regression-checked.
- **The README documents the non-Python surfaces** — CLI, REST API, SDK, web UI,
  scenario blueprints, cohort checks and optional extras — with
  `tests/test_readme_surfaces.py` guarding that the documented commands and
  endpoints keep matching the code. It previously described only the Python
  import path, leaving the audience Tier 5 was built for with no entry point.
- **The synthetic-data and mock-model disclaimers are now enforced by tests.**
  `tests/test_disclaimer_consistency.py` covers `ui/index.html` and the API
  responses, and the fairness heatmap carries its disclaimer inside the SVG
  itself, so the notice travels with the image if it is saved and reused
  elsewhere. The disclaimers were correct but unguarded, and the web UI is the
  surface whose audience is least able to infer the caveat.

### Fixed

- **API denial of service** — `do_POST` trusted `Content-Length` before reading,
  so a forged header pre-allocated arbitrarily large buffers and killed the
  handler thread. Bodies are now capped (`MAX_BODY_BYTES`), rejected with 413
  before allocation, and read in bounded chunks.
- **BigQuery identifier validation bypass** — `_validate_identifier` used
  `re.match`, which is not end-anchored and lets `$` match before a trailing
  newline, so a control character could reach generated DDL. Now uses
  `fullmatch`.
- **ATHENA tooling quote handling** — tab-delimited reads in the `tools/`
  scripts use `QUOTE_NONE`, matching the fix already applied to
  `vocabulary/validate.py`; bare quotes in `concept_name` no longer swallow
  subsequent rows.
- **Seismometer adapter dtype assertion under pandas 3** — a test asserted
  `patient_id` had `object` dtype, but pandas 3 gives `.astype(str)` columns a
  real `str` dtype (PDEP-14). It now asserts the property rather than the
  spelling, via `pandas.api.types.is_string_dtype`, which holds on pandas 2 and
  3. The failure had been carried as "pre-existing" while the module skipped
  for want of pandas, so it never actually ran — exactly the blind spot the new
  capabilities job closes.

### Known limitations

- The `Dockerfile` has not been verified by a real `docker build`; its tests are
  static checks on file contents (tracked in #91).
- The NOOA orchestrator example has no end-to-end runner: it cannot go from a
  preregistered plan through generation and audit to a rendered card, it never
  calls the engine itself, and its LLM-authored narrative has no groundedness
  check against the source passport. Pydantic constrains the *shape* of that
  output (a plan cannot name a profile that does not exist); it does not
  constrain the prose (tracked in #98).
- `GET /viz/fairness` runs a built-in mock model. It demonstrates the heatmap;
  it does not audit any real system.
- OMOP `concept_id`s remain partially ATHENA-verified; validate against a pinned
  ATHENA release before production use.

## [1.3.0] — 2026-07-24

Polymorphic fidelity: the seven documentation forms and the FairnessPassport are
now **fact-invariant** and **third-party-verifiable**, so decision divergence is
attributable to documentation form and every passport can be independently
re-rendered and confirmed. Implements audit findings F1–F6. Backward-compatible;
determinism, stdlib-only core, and zero PHI preserved. See
[`docs/POLYMORPHIC_FIDELITY.md`](docs/POLYMORPHIC_FIDELITY.md).

### Added

- **Canonical clinical fact set** (`hipaasynth/polymorphic/facts.py`) — shared by
  every form so all forms encode the same facts (F1). Lexical coverage for
  narrative forms; structural (coded-resource) coverage for FHIR.
- **Information-availability axis** — `PolymorphicFormEngine(information_mode=...)`:
  `same_facts` (default, every form encodes every fact) vs.
  `realistic_missingness` (patient/LEP/CHW forms may omit numeric labs, with the
  omission measured per form via `omitted_fact_categories`) (F1).
- **Form versioning + content hashing** — every rendered form carries
  `form_engine_version` and `content_sha256`; the passport seals `seed`,
  `run_date`, generation `anchor_hash`, engine/form-engine versions, and per-form
  hashes. `FairnessPassport.content_sha256()` and `verify()` make it
  byte-identical across runs and tamper-evident (F2).
- **Patient-specific SDoH** (`hipaasynth/polymorphic/sdoh.py`) — deterministic,
  locale-tunable per-patient social-determinant profile powering the CHW form;
  new `MockSDoHBiasedModel` makes the SAF metric demonstrable (F3).
- **Cohort aggregation** — `CohortFairnessSummary` / `summarize_cohort()` roll up
  per-patient passports into cohort means (with 95% CIs), pass rates, and the
  worst-performing form (F4).
- **Polymorphic-fidelity tests** (`tests/test_polymorphic_fidelity.py`, 22 tests).

### Changed

- **Forms** (`polymorphic/forms.py`) — every form now encodes labs (in
  register-appropriate language) in `same_facts` mode; the LEP form uses a short,
  interpreter-relayed register (F6). Builders take an `include_labs` flag.
- **Metrics** (`polymorphic/metrics.py`) — `PolymorphicMetrics.truth_evaluated`
  distinguishes a genuine pass from "no ground truth supplied"; the passport
  renders **NOT EVALUATED** instead of a silent PASS on truth-free runs (F5).
- **Passport** (`dif/report.py`) — deterministic `test_date` (defaults to
  `run_date`, no wall-clock), verification-seal section in the markdown.

## [1.2.1] — 2026-07-24

Conditional dependence for comorbidity clusters. COPD and CHF comorbidities are
no longer drawn as independent Bernoulli trials — they are conditioned on
primary-condition severity (COPD → GOLD stage, CHF → NYHA class) while preserving
every published national marginal exactly. Backward-compatible; no schema change;
determinism and all existing invariants intact. See
[`docs/CONDITIONAL_DEPENDENCE.md`](docs/CONDITIONAL_DEPENDENCE.md).

### Added

- **Conditional dependence module** (`hipaasynth/core/dependence.py`) — dedicated,
  stdlib-only home for correlation logic. Tilts each comorbidity's published
  marginal across severity strata with a literature-shaped, monotonic gradient
  that is normalized so the stratum-weighted mean equals the marginal exactly
  (marginal preserved by construction). Exposes `draw_copd_comorbidities`,
  `draw_chf_comorbidities`, resolved rate tables, and an optional
  `marginal_overrides` "locale knob" so a population profile can retarget any
  marginal and have the gradient re-center on it automatically.
- **Life-outcomes stage-7 scaffold** (`dependence.draw_life_outcomes`) — the
  sequential pipeline's final stage (relationship stability, employment, income
  band) conditional on functional status + condition burden + age + demographics.
  Provisional/uncalibrated and not part of the default record; structure and
  direction are test-locked, ready to calibrate and wire in later.
- **Joint-fidelity tests** (`tests/test_conditional_dependence.py`, 21 tests) —
  marginal preservation (analytic + sampled), directional severity gradients with
  anti-tamper thresholds that fail if dependence is flattened, and the
  one-draw-per-comorbidity determinism contract.

### Changed

- **COPD comorbidities** (`copd_generator.py`) — replaced the independent draw +
  blanket 1.3× for GOLD 3-4 with per-comorbidity GOLD-conditional rates. E.g.
  pulmonary hypertension now climbs ~0.08 → ~0.33 across GOLD 1 → 4 while its
  overall prevalence stays 0.18.
- **CHF comorbidities** (`chf_generator.py`) — replaced the fully independent draw
  with per-comorbidity NYHA-conditional rates. E.g. CKD climbs ~0.26 → ~0.60
  across NYHA I → IV while its overall prevalence stays 0.48. Ischemic → CAD
  forcing preserved.

## [1.2.0] — 2026-07-21

OHDSI ecosystem bridges (Phase 3). HipAAsynth now interoperates with OHDSI in
both directions: an ATLAS cohort definition can drive generation, and a generated
OMOP cohort can be characterized and quality-checked the way a real OMOP database
is. Backward-compatible; no schema change.

### Added

- **ATLAS cohort ingestion** (`hipaasynth/ohdsi/atlas_cohort.py`) — read an OHDSI
  ATLAS cohort definition (Circe JSON; bare or WebAPI-wrapped) and target a
  matching synthetic cohort. Reverse-maps the definition's concept sets through
  the vocabulary, reports matched/unmatched concept coverage, resolves the entry
  criteria to an index condition, and produces a ready `GenerationConfig` that
  seeds every synthetic patient with it. The bridge lets OHDSI define the cohort
  and HipAAsynth generate the under-represented population to stress-test.
- **`terms_for_concept_id`** — reverse vocabulary lookup (OMOP concept_id →
  HipAAsynth generator term), preferring generator-accepted terms.
- **ACHILLES / DQD-style CDM audit** (`hipaasynth/ohdsi/cdm_audit.py`) — run
  OHDSI-style characterization (ACHILLES) and data-quality checks
  (DataQualityDashboard) directly over a generated OMOP CDM cohort, pure Python
  and offline. Produces a realism/QA credential: characterization
  (counts, gender/age distributions, top conditions/drugs, measurement summaries)
  plus a representative check battery across Conformance / Completeness /
  Plausibility, with a Markdown/JSON report and a CLI
  (`python -m hipaasynth.ohdsi.cdm_audit`).
- **Extended medication vocabulary** — the medication map now covers the COPD,
  OUD, diabetes, cardiology, and SMA modules in addition to CHF (drug classes →
  ATC, single agents → RxNorm, combinations → components), 35 terms total.

### Changed

- `ENGINE_VERSION` 1.1.0 → 1.2.0 (`SCHEMA_VERSION` unchanged at 1.1.0).

## [1.1.0] — 2026-07-21

OHDSI / OMOP interoperability. HipAAsynth output is no longer text-only: the
generated vocabulary now carries standard clinical codes, and cohorts can be
emitted as OMOP CDM tables consumable by the OHDSI tool ecosystem (ATLAS,
ACHILLES, DataQualityDashboard, HADES). Backward-compatible: existing FHIR/CSV/
JSON exports are unchanged except for added `coding[]`, and the new `Patient`
field defaults to empty.

### Added

- **Vocabulary layer** (`hipaasynth/vocabulary/`) — a versioned concept map plus
  loader API mapping every internal generator term (conditions, labs, visit
  types, medications) to SNOMED CT, ICD-10-CM, LOINC, RxNorm, and ATC, with OMOP
  standard `concept_id`s. Lookups are case-insensitive; unmapped terms return
  `None`.
- **OMOP CDM v5.4 exporter** (`export_omop`) — writes `person`,
  `condition_occurrence`, `visit_occurrence`, `measurement`, and `drug_exposure`
  CSVs loadable into an existing OMOP database with no ETL. Unmapped terms use
  `concept_id 0` with the source value preserved.
- **FHIR standard codings** — `Condition`, `Observation`, and the new
  `MedicationStatement` resources now carry SNOMED/LOINC/RxNorm/ATC `coding[]`,
  degrading gracefully to text-only for unmapped terms.
- **Medication mapping** — drug *classes* (`beta_blocker`, `statin`, …) map to
  ATC classification concepts; single agents (`digoxin`, `aspirin`, …) to RxNorm
  ingredients; fixed-dose combinations to their components. Medication
  `concept_id`s are resolved from the ship-with codes during validation, never
  fabricated.
- **Concept-map validator** (`python -m hipaasynth.vocabulary.validate`) — checks
  every mapped concept against an ATHENA `CONCEPT.csv` (existence, standard flag,
  domain, code match) and resolves/fills medication `concept_id`s from their
  codes. Runs offline against the local file; non-zero exit gates CI.
- **`Medication`** dataclass and `Patient.medications` field (schema 1.1.0).

### Changed

- `SCHEMA_VERSION` 1.0.0 → 1.1.0 (added `Patient.medications`); `ENGINE_VERSION`
  1.0.2 → 1.1.0.

## [1.0.2] — 2026-07-08

Compliance-readiness hardening. No change to the synthetic-data generation
logic, determinism, calibration, or public API. Test count grew from 54 to 100+
and branch coverage roughly doubled (~25% → ~46%).

### Added

- **Identifier-safety & statistical-property tests** — every generated record is
  checked against a real-identifier deny-list (SSN/NPI/phone/email) and confirmed
  synthetic + disclaimer-stamped; demographic distributions are verified against
  the configured profile.
- **Smoke tests** for the DMD/Fabry/SMA/diabetes cohort generators (previously
  untested).
- **Coverage reporting** in CI with a ratcheting floor; **pre-commit** hooks
  (black, ruff, gitleaks secret scanning); **dependency audit + CycloneDX SBOM**
  workflow and **Dependabot**.
- **Docs**: `docs/ARCHITECTURE.md`, `docs/DATA_FLOW.md`, `docs/DEPLOYMENT.md`,
  `COMPLIANCE.md` (HIPAA shared-responsibility matrix), `.github/CODEOWNERS`, and
  an expanded `SECURITY.md` (incident response + data-handling).

### Changed

- **Every generator now stamps `synthetic=True` and one canonical disclaimer.**
  The DMD/Fabry/SMA/diabetes records previously carried no synthetic marker; the
  oud/chf/copd generators previously used a different disclaimer string. All paths
  now share `DEFAULT_SYNTHETIC_DISCLAIMER`.
- Exporters document their output-path trust model and fail-loud contract.
- The population-profile loader rejects pathologically oversized input before
  parsing (defense-in-depth); existing validation is unchanged.

## [1.0.1] — 2026-07-03

Packaging and documentation patch. No engine or source behavior changed; the
1.0.0 API, determinism, and calibration are unaffected. All 54 tests pass on
Python 3.11 and 3.12.

### Fixed

- **Recursive clones no longer fail.** Removed the `.gitmodules` reference to the
  private `hipaasynth-research` repository (and its submodule gitlink), which had
  caused `git clone --recurse-submodules` / `git submodule update --init` to fail
  for anyone without access to that private repo. The public engine has no
  dependency on the research repository and installs, tests, and runs on its own.

### Changed

- **README examples corrected.** All five example demos are now documented (was
  three), each labeled with its intended result so the biased-mock and fair-mock
  outputs read as by design rather than as failures. The Quick Start prints a
  single FairnessPassport and notes that `MockBiasedModel` fails by design (and
  how to swap in `MockFairModel` or a custom model). Added `python -m pytest -q`
  to the install block as an at-a-glance verification step.

## [1.0.0] — 2026-06-29

First stable release of the HipAAsynth engine — the open-source (AGPL v3)
fairness-testing core for clinical AI accountability. This release marks the
completion of the 7-Axis Adversarial Stress Test (7AAST) framework and a
verified, fully reproducible calibration baseline.

### Added

#### 7AAST framework

- **7-Axis Adversarial Stress Test (7AAST)** completed — all seven axes
  implemented and tested:
  - Axes 1–4: polymorphic fairness metrics (DCS, ISG, LFDI, SAF) via the DIF
    module.
  - Axis 5: adversarial perturbation (noise injection, missingness, temporal
    drift).
  - **Axis 6 — PSF (Population Sparsity Fairness)**, new in this release.
    Sparsity levels S1–S7; key metric Sparsity Degradation Index (SDI), FAIL if
    SDI < 0.80. Calibrated to the IHS Data Governance Framework (2022), Sequist
    (NEJM 2021), and Adler-Milstein (Health Aff 2017).
  - **Axis 7 — CC (Care Continuity)**, new in this release. Continuity profiles
    PROFILE_A through PROFILE_D; key metric Continuity Degradation Index (CDI),
    FAIL if CDI < 0.80, plus matched-pair transition-consistency analysis.
    Calibrated to Roberts (Health Aff 2018), AHRQ Statistical Brief #179, and
    HRSA (2023).

#### Clinical modules

- **6 calibrated clinical modules**: Stroke, Sepsis, COPD, CHF, OUD, and
  Diabetes. Each generates deterministic synthetic cohorts from anchor seeds.

#### Polymorphic engine and fairness audit

- **Polymorphic form engine** rendering each synthetic patient in 7 distinct
  documentation forms (FHIR structured, physician SOAP, mid-level abbreviated,
  patient high-literacy, patient low-literacy, LEP-translated, and CHW SDoH-rich).
- **DIF fairness audit** producing a per-patient FairnessPassport with four
  metrics: DCS (Decision Consistency Score), ISG (Information-Source Gradient),
  LFDI (Linguistic-Form Disadvantage Index), and SAF (SDoH Amplification Factor),
  each with a pass/fail determination.
- **Regulatory mapping** to the FDA Total Product Life Cycle (TPLC) framework and
  the EU AI Act.
- **Exporters** for JSON, CSV, and FHIR R5.

#### Calibration

- **17/17 calibration targets verified** against published reference
  distributions (CDC BRFSS, ACS, and IHS benchmarks), confirming that synthetic
  cohort distributions match their real-world anchors within tolerance.

#### Testing and architecture

- **54 automated tests passing**, 0 failures.
- **Zero external dependencies** — the engine runs on the pure Python standard
  library. This is enforced in CI by an AST-based import check that fails the
  build if any non-stdlib import is introduced.

### Infrastructure

- **GitHub branch protection and CI** configured. The `test.yml` workflow runs
  the full test suite on Python 3.11 and 3.12 and enforces the zero-external-
  dependency invariant on every push and pull request.
- **Privacy and professionalism audit completed.** The codebase contains no
  named individuals and no real facilities — only synthetic populations and
  region-level population anchors.

### Release provenance

- This v1.0.0 release is timestamped via **OpenTimestamps Bitcoin anchoring** as
  part of the **CAP (Certification Artifact Pipeline)**. The release artifact is
  fixed to a **SHA-256 anchor chain** and anchored to the Bitcoin blockchain,
  producing an independently verifiable proof of existence for the release.
  (The CAP pipeline itself is offered as a proprietary certification service and
  is not part of this open-source repository — see `README.md`.)

### Licensing

- **Dual-license model.** The engine and all core modules are published under
  **AGPL-3.0**. A **commercial license** is available for organizations that
  cannot meet the AGPL v3 source-disclosure obligations — see
  [COMMERCIAL-LICENSE.md](COMMERCIAL-LICENSE.md).

[1.0.0]: https://github.com/hipaasynth-svg/HipAAsynth/releases/tag/v1.0.0
</content>
</invoke>
