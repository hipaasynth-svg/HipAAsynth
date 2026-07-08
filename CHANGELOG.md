# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
