# HipAAsynth Data Flow

This document traces exactly what enters the engine, what moves between stages, and
what leaves — with an emphasis on the **security-relevant** claim that no PHI can
enter or exit. See [`ARCHITECTURE.md`](ARCHITECTURE.md) for the component map.

## Trust boundaries

```
   ┌──────────────────────── operator-controlled inputs ─────────────────────────┐
   │  seed (int)   ·   n (int)   ·   population profile (JSON: aggregate weights)  │
   └───────────────────────────────────┬──────────────────────────────────────────┘
                                        │  (no patient data crosses this line)
   ══════════════════════════ ENGINE TRUST BOUNDARY ═══════════════════════════════
                                        │
              anchor = H(seed, module, n)  ──►  namespaced RNG streams
                                        │
        demographics → anthropometrics → conditions → numerics  (pipelines/)
                                        │
                     condition module shaping  (modules/)
                                        │
        ┌───────────────┬───────────────┼───────────────┬───────────────┐
        ▼               ▼               ▼               ▼               ▼
   polymorphic     psf/cc/dif       exporters       run logs        manifest
   7 forms +       audit frames     CSV/JSON/FHIR    (JSONL)         (hashes)
   metrics
        │               │               │               │               │
   ═════╪═══════════════╪═══════════════╪═══════════════╪═══════════════╪════════
        ▼               ▼               ▼               ▼               ▼
             all outputs are SYNTHETIC + disclaimer-stamped + hash-anchored
```

## Inputs (what crosses into the engine)

| Input | Type | Notes |
|---|---|---|
| `seed` | int | Anchors determinism. Same seed ⇒ same cohort. |
| `n` / `patient_count` | int | Cohort size. |
| population profile | JSON file | **Aggregate** distributions only — sex ratio, ethnicity weights, age-band weights (`core/profile_loader.py`, `profiles/`). No individual records. |
| module selection | str | e.g. `oud`. Chooses the condition generator. |
| generation config | `GenerationConfig` (frozen dataclass) | Age bounds, visit/lab toggles, disclaimer text (`core/config.py`). |

**There is no input path that reads a patient record.** `profile_loader` reads
distribution weights; there is no CSV/EHR/FHIR *ingest* on the generation path.
(The Seismometer *adapter* under `examples/` reads canonical HipAAsynth cohort
files, which are themselves synthetic engine output — not external PHI.)

## Intermediate flow

1. **Anchor & RNG derivation** — `(seed, module, n)` → anchor hash → per-namespace
   `random.Random` streams (`demographics`, `clinical`, `labs`, …) so each facet is
   independently reproducible (`core/anchor.py`, `modules/*/*_generator.py`).
2. **Pipeline stages** — demographics → anthropometrics → conditions → numerics
   produce base `Patient` objects (`pipelines/`).
3. **Module shaping** — the selected condition module adds calibrated clinical,
   comorbidity, medication, and SDoH fields.
4. **Fan-out** — patients flow to the polymorphic renderer, the audit frameworks,
   and/or the exporters, independently.

## Outputs (what crosses out)

| Output | Path | Integrity |
|---|---|---|
| Synthetic cohort | `exporters/` → CSV / JSON / FHIR R5 | Parent dirs auto-created; writes fail loud (`RuntimeError`) on I/O error. FHIR bundle IDs are path-independent (`os.path.basename`). |
| FairnessPassport | in-memory / serialized | Per-patient structured audit record. |
| Run logs | `runs/<run_id>/logs/engine.jsonl` | Structured JSONL; event + hash records only — **not** patient field dumps (`core/logger.py`). |
| Manifest & snapshots | `runs/<run_id>/` | Config snapshot, environment snapshot (python/platform/cwd/pid), replay command, SHA-256 file hashes (`core/run_context.py`, `core/manifest.py`, `core/hashing.py`). |

Every emitted record carries `synthetic=True` and the disclaimer from
`DEFAULT_SYNTHETIC_DISCLAIMER`.

## Security-relevant properties of the flow

- **No network egress.** Nothing in the flow opens a socket. Output goes only to
  the local filesystem paths the operator specifies.
- **No PHI at any stage.** Since no PHI enters, none can be logged, exported, or
  leaked. Logs record events and hashes, not record contents.
- **Reproducible ⇒ non-archival.** Any output can be regenerated from its seed, so
  bulk output need not be retained (see `COMPLIANCE.md` §5).
- **Fail-loud I/O.** Exporters and run-context writers raise on failure rather than
  silently producing partial artifacts.

## Operator responsibilities at the boundary

- Choose an **output directory** with appropriate host permissions; the engine
  writes wherever told.
- Treat **profiles and seeds** as the reproducibility record and keep them in
  version control.
- If moving outputs across a network, apply TLS at that layer — the engine does not
  transmit.
