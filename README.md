Fully reproducible synthetic cohorts with no external dependencies.

# HipAAsynth™

Deterministic synthetic clinical data engine.

Run locally for free, or request ready-to-use datasets.

• Zero external dependencies
• Fully reproducible (seed-based)
• No AI or black-box models
• Modular clinical pipeline (population → visits → export)

---

## What this is

HipAAsynth generates statistically realistic, fully synthetic patient cohorts for testing healthcare systems, models, and workflows.

No real patient data is used.

Every dataset is:

* deterministic
* auditable
* reproducible from a seed

---

## Why it exists

Most synthetic healthcare data tools are:

* black-box
* non-reproducible
* dependent on heavy ML frameworks

HipAAsynth is different:

> A transparent, deterministic system built from explicit logic and controlled randomness.

---

## Quickstart

Run a cohort locally:

```bash
python main.py
```

No installs. No setup.

---

## Reproducibility

HipAAsynth is fully deterministic.

Same seed → identical dataset
Different seed → different (but statistically consistent) dataset

Run:

```bash
python run/demo_reproducibility.py
```

Expected result:

```
Same seed match:      True
Different seed match: False
RESULT: DETERMINISM VERIFIED
```

---

## Core Pipeline

The core engine pipeline:

```
Population → Anthropometrics → Conditions → Visits → Export
```

* Labs are generated within conditions/visits
* Outcomes are part of specialty packs, not the core engine

Each stage is:

* deterministic
* auditable
* isolated

---

## RNG Architecture

All randomness is controlled centrally.

* Pipeline owns randomness
* One deterministic RNG per patient
* No global randomness in execution paths
* No hidden state

---

## Example Usage

Main CLI:

```bash
python main.py
```

Quick sample:

```bash
python run/generate_sample.py
```

Reproducibility demo:

```bash
python run/demo_reproducibility.py
```

---

## Output

Generated cohorts include:

* patient demographics
* conditions
* labs (embedded within pipeline stages)
* visits

All records are synthetic and contain no real patient data.

---

## Project Structure

```
core/           → engine logic
modules/        → clinical components
pipelines/      → execution flow
exporters/      → export logic
profiles/       → population definitions
run/            → CLI + demos
tests/          → deterministic validation
sample_data/    → example output (CSV + JSON)
```

---

## Versioning

```
engine_version: 0.2.0
```

Results are reproducible by:

* version
* seed
* configuration

---

## Status

v0.2.0 — Stable deterministic core
Reproducibility verified
Zero dependency runtime

---

## Contact / Use

Custom datasets / API access: [HipAAsynth@gmail.com](mailto:HipAAsynth@gmail.com)

---

## Governance

HipAAsynth follows a benevolent dictator model.

The project creator retains final authority over:
- architectural decisions
- core logic
- accepted contributions

Contributions are welcome, but must align with the deterministic design and system integrity of the engine.

---

## License

See LICENSE file.
