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
| `run/` | CLI entry points and reproducibility demos. |

## The FairnessPassport

The engine's product is not a score but a **structured, reproducible record**: for
each synthetic patient, across each polymorphic form, whether a model's decisions
held. It carries heuristic, non-binding regulatory-context mappings (informational
only — HipAAsynth makes no regulatory determination).

## What is deliberately *not* here

- No model weights, no inference — the engine evaluates *your* model via a small
  `predict(patient, form)` interface (`core/model_interface.py`).
- No network, no telemetry, no data collection.
- No CAP pipeline (cryptographic certification / anchoring) — that is proprietary
  and maintained separately; this repository has no dependency on it.
