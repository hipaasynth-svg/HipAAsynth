# HipAAsynth Architecture

HipAAsynth is a deterministic, zero-dependency engine for generating synthetic
clinical cohorts and auditing clinical-AI models for fairness across the seven
polymorphic presentations of the same case. This document describes the moving
parts and how they fit together. For how data moves through them, see
[`DATA_FLOW.md`](DATA_FLOW.md); for running it in an environment, see
[`DEPLOYMENT.md`](DEPLOYMENT.md).

## Design invariants

These are load-bearing properties enforced by tests and CI, not aspirations:

1. **Zero external runtime dependencies.** The engine imports only the Python
   standard library. CI (`.github/workflows/test.yml`) fails the build on any
   non-stdlib import. Optional integrations (`fhir.resources`, `seismometer`) are
   opt-in extras and never imported on the core path.
2. **Determinism.** Given `(module, seed, n)`, output is byte-identical across
   processes and machines. No reliance on process-randomized `hash()`; seeds are
   derived via SHA-256 (`core/hashing.py: stable_seed_from_id`).
3. **No PHI.** Inputs are seeds, counts, and aggregate population *profiles*.
   Every output record is synthetic and disclaimer-stamped.
4. **Integrity-anchored.** Every cohort is anchored by a hash
   (`core/anchor.py`), and files/checkpoints are SHA-256 hashed
   (`core/hashing.py`, `core/checkpoints.py`) for third-party re-verification.

## Component map

```
                         ┌─────────────────────────────────────────────┐
   seed, n, profile ───► │                  core/                      │
                         │  config · anchor · hashing · run_context ·  │
                         │  logger · manifest · profile_loader · schema│
                         └───────────────┬─────────────────────────────┘
                                         │ RNG streams (namespaced by anchor)
                         ┌───────────────▼─────────────────────────────┐
                         │                pipelines/                   │
                         │  demographics → anthropometrics →           │
                         │  conditions → numerics → population_pipeline│
                         └───────────────┬─────────────────────────────┘
                                         │ base Patient records
                         ┌───────────────▼─────────────────────────────┐
                         │                 modules/                    │
                         │  oud · stroke · sepsis · chf · copd ·       │
                         │  diabetes · dmd · fabry · sma · cardiology  │
                         │  (condition-specific calibrated cohorts)    │
                         └───────────────┬─────────────────────────────┘
             ┌───────────────────────────┼───────────────────────────┐
             ▼                           ▼                           ▼
     ┌───────────────┐          ┌─────────────────┐         ┌────────────────┐
     │ polymorphic/  │          │  audit frames   │         │  exporters/    │
     │ 7 forms +     │          │  psf · cc · dif │         │ CSV · JSON ·   │
     │ fairness      │          │  (degradation   │         │ FHIR R5 bundle │
     │ metrics       │          │   indices)      │         │                │
     └───────┬───────┘          └────────┬────────┘         └────────────────┘
             └───────────────┬───────────┘
                             ▼
                    FairnessPassport
              (per-patient structured audit record)
```

### 7AAST: the stress test of a model

```
  decision_cohort.py ── true cases + clinical look-alikes, sepsis spectrum,
        │               Monk skin tone + pulse-oximeter reading, balanced groups
        ▼
  polymorphic/blinding.py ── what is visible at the moment of decision
        ▼
  aast/cases.py ── the case the model is shown (7 written forms or a record),
        │          care-setting and fragmented-history variants, twins
        ▼
  aast/adapter.py ◄── the model: Python function · answers file (files.py) ·
        │             URL or LLM API (remote.py) · demo or published score
        │             (demo.py, reference.py)
        ▼
  aast/run.py ── accuracy floor, Axes 1-7 with intervals (stats.py) ──► AASTReport
        ▼
  aast/report.py ── JSON / HTML report with a 4-stage SHA-256 chain, verify
```

Front doors: `hipaasynth 7aast run|export|verify` (`aast/cli.py`), the page and
`POST /7aast`, `POST /7aast/export` (`api.py`, `aast/web.py`, `ui/7aast.html`),
and `hipaasynth ui`, which serves them on 127.0.0.1.

## Subsystem responsibilities

| Package | Responsibility |
|---|---|
| `core/` | Config & disclaimer constants, anchor/seed derivation, SHA-256 hashing, run context (dirs, snapshots, replay), structured logging, run manifest, profile loading, schema. |
| `pipelines/` | Ordered generation stages that turn a config + profile into base `Patient` records: demographics → anthropometrics → conditions → numerics. |
| `modules/` | Condition-specific cohort generators (OUD, stroke, sepsis, CHF, COPD, diabetes, DMD, Fabry, SMA, cardiology) calibrated to public reference distributions. |
| `polymorphic/` | Renders each patient across seven documentation forms (FHIR, SOAP, mid-level note, high/low-literacy patient narratives, LEP-translated, CHW SDoH intake) and computes fairness metrics (DCS, ISG, LFDI, SAF). |
| `psf/` · `cc/` · `dif/` | Adversarial audit frameworks: Population Sparsity Fairness, Care Continuity, Differential Impact — each produces a degradation index with a documented FAIL threshold. |
| `exporters/` | Serialize cohorts to CSV (streaming + buffered), JSON, and FHIR R5 bundles. All writes create parent dirs and fail loud on I/O errors. |
| `validation/` | Post-generation schema/consistency validation. |
| `run/` | CLI entry points (`hipaasynth`, `hipaasynth 7aast`, `hipaasynth ui`) and reproducibility demos. |
| `decision_cohort.py` | 7AAST cohorts: true cases mixed with clinical look-alikes, the sepsis presentation spectrum, skin tone and pulse-oximeter readings, balanced or natural group mix. |
| `aast/` | 7AAST: model adapters, statistics and verdicts, what the model sees, the run, file/URL/LLM/reference model sources, the hash-chained report, CLI and web handlers. |
| `api.py`, `ui/`, `sdk.py` | REST API and pages (cohort generator, 7AAST), Python SDK. |

## The FairnessPassport

The engine's product is not a score but a **structured, reproducible record**: for
each synthetic patient, across each polymorphic form, whether a model's decisions
held. It carries heuristic, non-binding regulatory-context mappings (informational
only — HipAAsynth makes no regulatory determination).

## What is deliberately *not* here

- No model weights, no inference — the engine evaluates *your* model through
  `aast/adapter.py` (or `predict(patient, form)` for the older audit frames).
- No telemetry, no data collection. The only network calls are the ones the
  operator asks for: sending synthetic 7AAST cases to a model URL or an LLM API
  (`aast/remote.py`); the shared API server refuses to make them.
- No CAP pipeline (cryptographic certification / anchoring) — that is proprietary
  and maintained separately; this repository has no dependency on it.
