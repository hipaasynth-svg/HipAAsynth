# HipAAsynth v1.0.0 — Evidentiary infrastructure for clinical AI fairness, complete and reproducible

**Release title (paste into GitHub):**
`v1.0.0 — 7AAST framework complete: reproducible, zero-dependency fairness testing for clinical AI`

---

HipAAsynth v1.0.0 is the first stable release of the open-source (AGPL v3)
fairness-testing engine for clinical AI. It completes the 7-Axis Adversarial
Stress Test (7AAST) framework, ships six calibrated clinical modules, and
establishes a fully reproducible calibration baseline verified against published
public-health benchmarks.

This release is infrastructure, not a benchmark score. Every audit it produces is
deterministic, third-party reproducible, and traceable to a cited reference
distribution.

## What's New

- **7AAST framework complete** — all seven adversarial axes implemented and
  tested.
- **Axis 6 — PSF (Population Sparsity Fairness)** added this release. Measures how
  a model degrades as the patient record thins from full EHR to bare
  demographics (sparsity levels S1–S7), via the Sparsity Degradation Index (SDI;
  FAIL if SDI < 0.80).
- **Axis 7 — CC (Care Continuity)** added this release. Measures how a model
  degrades across continuity profiles from established-PCP to ED-only care, via
  the Continuity Degradation Index (CDI; FAIL if CDI < 0.80) and matched-pair
  transition-consistency analysis.
- **FairnessPassport** — every audit produces a per-patient, structured,
  independently verifiable record across four polymorphic fairness metrics (DCS,
  ISG, LFDI, SAF), with FDA TPLC and EU AI Act regulatory mappings.
- **54 automated tests passing**, 0 failures.

## Clinical Modules

Six calibrated clinical modules generate deterministic synthetic cohorts from
anchor seeds:

| Module | Condition |
|--------|-----------|
| Stroke | Acute cerebrovascular presentation |
| Sepsis | Systemic infection / organ dysfunction |
| COPD | Chronic obstructive pulmonary disease |
| CHF | Congestive heart failure |
| OUD | Opioid use disorder |
| Diabetes | Type 2 diabetes mellitus |

Each module renders patients across all seven polymorphic documentation forms so
the same case can be stress-tested as a FHIR bundle, a physician SOAP note, a
mid-level abbreviated note, a high- or low-literacy patient narrative, an
LEP-translated account, and a community-health-worker SDoH-rich intake.

## Calibration

- **17/17 calibration targets verified.** Synthetic cohort distributions are
  validated against published reference distributions from **CDC BRFSS**, the
  **American Community Survey (ACS)**, and **Indian Health Service (IHS)**
  benchmarks, and match their real-world anchors within tolerance.
- Calibration is reproducible: the same seed always produces the same population,
  so any third party can regenerate and re-verify every reported figure.

## Architecture

- **Zero external dependencies — by design.** The engine runs on the pure Python
  standard library. This is a feature, not a limitation: it eliminates supply-
  chain risk, makes the engine auditable end-to-end with no opaque transitive
  dependencies, and guarantees that an audit run today reproduces identically
  years from now. CI enforces this invariant with an AST-based import check that
  fails the build on any non-stdlib import.
- **Deterministic and reproducible.** Anchor-seeded generation means every audit
  is reproducible by any third party — the defense is "here is the methodology,
  verify it yourself," not "trust us."
- **No PHI, ever.** All populations are synthetic. The codebase contains no named
  individuals and no real facilities; population anchors are region-level only.
- **Tested on Python 3.11 and 3.12** in CI, with branch protection enforced on
  the default branch.

## Release Provenance

This release is timestamped via **OpenTimestamps Bitcoin anchoring** as part of
the **CAP (Certification Artifact Pipeline)**. The v1.0.0 artifact is fixed to a
SHA-256 anchor chain and anchored to the Bitcoin blockchain, producing an
independently verifiable proof of existence for the release. The CAP pipeline is
offered as a proprietary certification service and is not part of this
open-source repository.

## Licensing

HipAAsynth is dual-licensed:

- **AGPL-3.0** for the public, open-source engine and all core modules.
- **Commercial license** available for organizations embedding the engine in
  proprietary products that cannot meet the AGPL v3 source-disclosure
  obligations. See [COMMERCIAL-LICENSE.md](../../COMMERCIAL-LICENSE.md).

## Breaking Changes

None — this is the first stable release.

---

**Full changelog:** see [CHANGELOG.md](../../CHANGELOG.md).
**Contact:** HipAAsynth LLC — Minot, North Dakota · [hipaasynth.com](https://hipaasynth.com) · cody@hipaasynth.com
</content>
