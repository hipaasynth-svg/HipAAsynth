# History

How HipAAsynth got here, in one page. The full record is in
[CHANGELOG.md](../CHANGELOG.md) (every release), the build log
[ROADMAP_CHANGELOG.md](ROADMAP_CHANGELOG.md) (Tier 1–5 interoperability work,
step by step) and the git history. Older reports that used to sit in the
repository root are kept unchanged in [history/](history/).

## Timeline

| When | Version | What changed |
|---|---|---|
| 2026-06 | 1.0.0–1.0.1 | Synthetic population engine, sepsis and stroke decision modules, seven polymorphic presentations, the FairnessPassport (DIF Axes 1–4), PSF and CC (Axes 6–7). Release notes: [history/RELEASE_NOTES_v1.0.0.md](history/RELEASE_NOTES_v1.0.0.md), [v1.0.1](history/RELEASE_NOTES_v1.0.1.md). |
| 2026-07 | 1.0.2 | Compliance hardening: one canonical synthetic-data disclaimer, logging and run-context contracts, core docstrings. |
| 2026-07 | 1.1.0–1.2.1 | OHDSI/OMOP vocabulary and CDM export, medications, ATLAS bridge, conditional comorbidity dependence (COPD, CHF), calibration sources and citation fixes. |
| 2026-07 | 1.3.0 | Fact-invariant polymorphic forms and a verifiable passport; DKA and Fabry-referral decision modules; ATHENA concept validation. |
| 2026-07 | 1.4.0 | Interoperability Tiers 1–5: FHIR R5 bulk/NDJSON and a structural validator, OMOP CDM 5.4, Parquet, `hipaasynth` CLI, REST API, Python SDK, DuckDB and BigQuery connectors, Docker, validation and fidelity reports, the web UI, scenario blueprints and SVG charts. |
| 2026-08/09 | — | Linked per-patient passport bundles, NOOA validation runner, end-to-end tests of fair, biased and refusing models, cardiology coherence tests. |
| 2026-10 | 1.5.0 | **Audit and 7AAST.** A full audit (October 2026) found 15 defects, all fixed and tested (#106–#120): sepsis cohorts not generating sepsis, rurality read from profile names, non-reproducible Axis 6/7 seeds, a consistently wrong model passing, and others. 7AAST was then rebuilt as one runnable test (#122–#129): a model adapter for every output type, exact intervals with PASS/FAIL/INCONCLUSIVE, blinded decision-time cases, true cases mixed with clinical look-alikes, `run_7aast`, test-by-file, a hash-chained report with `verify`, the `hipaasynth ui` laptop page, and a leak scan with pulse-oximeter bias. |

## Lessons the project paid for

* **A test that cannot fail is not a test.** Before 1.5.0 every 7AAST cohort
  was 100% positive and the answer was written into the case, so a model that
  said "yes" to everyone passed. Mixed cohorts, blinding and a leak-scan test
  (`tests/test_decision_realism.py`) now guard against that.
* **Determinism is a contract.** Python's `hash()` is salted per process; seeds
  now come from `stable_seed_from_id`, and old outputs are checked byte for byte
  when engine code changes.
* **Say what is not covered.** Reports carry their limits (synthetic patients,
  pending clinician review, the normotensive-sepsis gap) next to the verdict.

## Reports kept for the record

| File | What it was |
|---|---|
| [history/FORGOTTEN_ISSUES_AUDIT.md](history/FORGOTTEN_ISSUES_AUDIT.md) | July 2026 walk through every commit for promised work that was never done. |
| [history/ORPHAN_AUDIT.md](history/ORPHAN_AUDIT.md) | July 2026 state of the modules no entry point reached (cardiology, SMA, DMD, oncology). |
| [history/RELEASE_NOTES_v1.0.0.md](history/RELEASE_NOTES_v1.0.0.md), [v1.0.1](history/RELEASE_NOTES_v1.0.1.md) | The first release notes, before the CHANGELOG took over. |

## Core and extras

7AAST and the FairnessPassport rest on: `core/`, `pipelines/`, `profiles/`,
`modules/sepsis`, `modules/stroke`, `modules/diabetes` (DKA), `modules/fabry`,
`polymorphic/`, `dif/`, `psf/`, `cc/`, `adversarial/`, `aast/`,
`decision_cohort.py`, `exporters/` and the front doors (`run/main.py`,
`api.py`, `sdk.py`, `ui/`).

The other disease generators (`modules/chf`, `copd`, `oud`, `dmd`, `sma`,
`cardiology`, `sepsis/oncology`, the calibration validators and
`run_all_modules.py`), the warehouse connectors, OMOP/OHDSI tooling, the
fidelity and utility reports, `examples/seismometer/` and `tools/` are
**extras**: tested and working, but not part of the 7AAST verdict. They stay in
place because the CLI, API, SDK, examples and tests import them; moving them
would break documented imports for no gain.
