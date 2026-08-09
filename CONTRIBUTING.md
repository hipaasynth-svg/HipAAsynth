# Contributing to HipAAsynth

HipAAsynth is an open standard for clinical AI fairness testing. Contributions that strengthen the methodology, expand population coverage, or improve the seven-form polymorphic layer are welcome.

This document explains what's in scope, what's out of scope, and how to contribute effectively.

---

## What this project is

HipAAsynth generates synthetic patients from populations historically absent from clinical AI validation datasets and audits models across seven distinct presentations of the same case. The output is a FairnessPassport — a structured record of where a model's decisions held and where they didn't.

The methodology is the product. Contributions that make the methodology more rigorous, more reproducible, or more relevant to invisible populations are the highest-value contributions this project can receive.

---

## What's open and what's closed

| Component | Open | Notes |
|-----------|------|-------|
| Population engine | ✓ | Core generation logic, anchor seeds, demographic calibration |
| PSF module | ✓ | Population Stability Framework |
| CC module | ✓ | Consistency Checker |
| DIF module | ✓ | Differential Impact Framework |
| Polymorphic layer | ✓ | Seven forms + fairness metrics |
| CAP pipeline | ✗ | Cryptographic certification, Bitcoin anchoring — proprietary |
| FDA-Ready tier | ✗ | Regulatory submission packaging — proprietary |
| Research extensions | ✗ | LLM harnesses, clinical evaluators — BSL 1.1 private submodule |

Do not submit contributions that touch or reproduce CAP pipeline logic. That boundary is permanent.

---

## How to contribute

### Report a methodology issue

If you find a flaw in how a population profile is calibrated, how a polymorphic form misrepresents a clinical scenario, or how a fairness metric produces misleading results — open an issue. Label it `methodology`. These are the most important issues in this repo.

Be specific. Describe the population segment, the form, the observed behavior, and what you believe the correct behavior should be. If you have supporting evidence (clinical literature, demographic data, EHR distribution data), include it.

### Add or improve a population profile

Population profiles are calibrated to real-world demographic distributions. If you have domain expertise in a population that is underrepresented or miscalibrated — tribal health, rural frontier, aging uninsured, specific linguistic communities — open an issue first to discuss scope, then submit a PR.

Requirements for a new population profile:
- Must be calibrated to a publicly citable benchmark (CDC BRFSS, ACS, IHS, or equivalent)
- Must include documentation of the calibration source
- Must not incorporate any PHI or real patient records in any form
- Must be deterministic from an anchor seed

### Improve the polymorphic forms

The seven forms are the core of the fairness audit. If a form misrepresents how a patient population actually communicates — if `LEP_TRANSLATED` doesn't reflect realistic patterns, if `PATIENT_LOW_LITERACY` uses terminology that is too clinical or not somatic enough — open an issue or submit a PR.

Changes to forms require clinical or linguistic justification. Assert what the form should represent and why the current implementation falls short.

### Add a clinical module

New disease modules (sepsis, stroke, COPD, etc.) expand the range of conditions the engine can test. Open an issue before building a new module to confirm it's in scope and not already in progress.

Requirements:
- Module must generate clinically plausible synthetic presentations
- Must include edge cases relevant to invisible populations (delayed presentation, atypical symptoms, comorbidity patterns common in underserved populations)
- Must include at least one test covering each of the seven polymorphic forms

### Bug fixes and tests

Bug fixes and test coverage improvements are always welcome. If a test is failing or a known edge case is uncovered, open a PR with a clear description of the issue and the fix.

---

## Code standards

- Python 3.11+
- Zero runtime dependencies (stdlib only). Do not add external imports to the engine core.
- `black` for formatting (`line-length = 100`)
- `ruff` for linting
- `mypy` for type checking
- All new code must include tests

Run the full suite before submitting:

```bash
pip install -e ".[dev]"
python -m pytest
black --check .
ruff check .
mypy hipaasynth/
```

### Running *everything*

`.[dev]` deliberately installs no optional capability, which mirrors CI's
stdlib-only job and proves the engine core needs nothing external. The trade-off
is that the tests gated on an optional dependency **skip silently** — you will see
something like `437 passed, 12 skipped` and it looks like a clean full run.

Those skips hide entire files. To actually run all of them:

```bash
pip install -e ".[test-full]"
python -m playwright install chromium   # browser binary; pip ships only the driver
python -m pytest
```

That unlocks the DuckDB connector, Parquet export, the example scripts, and the
headless-Chromium drive of the web UI — 64 further tests. CI runs this as the
`capabilities` job and **fails if anything skips**, so if you add a test behind a
new optional dependency, add that dependency to the `test-full` extra in
`pyproject.toml` or CI will go red.

---

## What we won't accept

- Contributions that require external dependencies in the engine core
- Contributions that ingest, process, or reference real patient data in any form
- Contributions that reproduce or approximate CAP pipeline logic
- Changes to the AGPL v3 license or any attempt to relicense engine components
- Contributions that narrow the focus away from invisible or underrepresented populations

---

## Commercial use

This project is licensed under AGPL v3. Any organization embedding HipAAsynth in a commercial product must either open-source their full stack under a compatible license or obtain a commercial license.

For commercial licensing: [cody@hipaasynth.com](mailto:cody@hipaasynth.com)

---

## Questions

Open an issue or reach out directly at [cody@hipaasynth.com](mailto:cody@hipaasynth.com).
