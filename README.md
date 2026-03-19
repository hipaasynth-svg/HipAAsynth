# HipAAsynth

Deterministic synthetic healthcare cohort generation engine.

Zero dependencies. Stdlib-only Python. Clone and run.

## What This Does

HipAAsynth generates clinically realistic synthetic patient populations calibrated against real CDC/NHANES data. Every record is:

- **Fully synthetic** — no real patient data, HIPAA-safe by design
- **Deterministic** — same seed = same output, every time
- **Auditable** — SHA-256 anchor hash stamped on every record
- **Exportable** — JSON, CSV, FHIR R5

## Quick Start

```bash
git clone https://github.com/hipaasynth-svg/HipAAsynth.git
cd HipAAsynth

# Generate a 1,000-patient cohort
python3 run/main.py

# Generate a quick sample
python3 run/generate_sample.py

# Verify determinism
python3 tests/test_determinism.py
```

No pip install. No virtual environment. Just Python 3.8+.

## How It Works

A single master seed drives all randomness through derived sub-seeds:

```
seed=42 → anchor hash → demographics seed
                       → anthropometrics seed
                       → conditions seed
                       → numerics seed
```

Same seed, same config = byte-identical output on any machine.

## What's Included

| Directory | Contents |
|---|---|
| `core/` | Anchor system, schema, config, profile loader |
| `pipelines/` | Population generator, demographics, anthropometrics, labs, conditions |
| `exporters/` | JSON, CSV, FHIR R5 export |
| `profiles/` | US default population profile |
| `run/` | CLI runners |
| `tests/` | Determinism verification |

## Output Fields

Each synthetic patient includes:
- Demographics (age, sex, ethnicity, BMI, blood pressure)
- Conditions (diabetes, hypertension, COPD, CKD, etc.)
- Lab values (A1C, cholesterol, creatinine, eGFR, etc.)
- Visits and encounter history
- Anchor hash + synthetic disclaimer

## Specialty Packs (Licensed)

Specialty clinical modules are available for licensing:

- **Cardiology** — ASCVD risk scoring, MACE outcomes, Framingham-calibrated
- **Diabetes** — Glycemic control, complications, NHANES-validated (90.4% AUC transfer to real data)
- **Oncology** — Staging, biomarkers, treatment response
- **Rare Disease** — SMA, DMD, Fabry disease modules
- **Analysis Suite** — Bias detection, drift monitoring, fidelity scoring, privacy guards
- **Validation Suite** — NHANES transfer benchmark, validation assault testing
- **Lab Web App** — Browser-based cohort generation interface
- **API Server** — HTTP API for programmatic cohort generation
- **Custom Profiles** — Region-specific population calibration

Contact: HipAAsynth@gmail.com

## License

Apache License 2.0 — see [LICENSE](LICENSE)

Copyright 2026 Cody Carlson
