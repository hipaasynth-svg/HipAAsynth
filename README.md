# HipAAsynth

Deterministic clinical data generation.

Same seed → same patients → every time.

No black box. No hidden randomness. No drift.

This is a deterministic engine for generating synthetic patient populations.

---

## Show me

    python3 run/demo_reproducibility.py

Expected result:

    Same seed match:      True
    Different seed match: False

    RESULT: DETERMINISM VERIFIED

---

## What this is

This is an engine that generates synthetic patient populations.

Not random.  
Not AI-generated.  
Not a black box.

You can reproduce every dataset exactly.  
You can audit how it was generated.  

---

## What it does

- generates synthetic patient cohorts  
- reproduces identical datasets from the same seed  
- uses pipeline-based generation across domains (population, diabetes, cardiology, rare disease)  
- exports to CSV and JSON  
- includes validation and analysis components  

---

## What it is not

This does not attempt to fully model real-world clinical systems.

The core engine provides:
- structure  
- patients  
- controlled execution  

The core engine does not define clinical realism.  
It provides the framework for it.

---

## System layout

Core → deterministic execution  
Pipelines → cohort generation  
Modules → clinical behavior  
Analysis → validation and inspection  

---

## Core

The core enforces:

- no hidden randomness  
- no module-level RNG  
- no global random state  
- single master seed  
- deterministic execution  

Key files:
- core/schema.py → data structure  
- core/anchor.py → deterministic identity  
- core/anchor_stamp.py → reproducibility tracking  

---

## Pipelines

Pipelines generate cohorts.

Examples:

    python3 pipelines/population_pipeline.py
    python3 pipelines/diabetes_pipeline.py
    python3 pipelines/cardiology_pipeline.py
    python3 pipelines/rare_disease_pipeline.py

Each pipeline:
- builds a population  
- applies domain logic  
- outputs a dataset  

---

## Modules

Modules define clinical behavior.

Examples include:
- condition logic  
- lab generation  
- comorbidity relationships  

Core remains stable.  
Modules can change independently.

---

## Analysis + Validation

Includes components for:

- bias detection  
- drift monitoring  
- data inspection  
- basic validation  

Examples:

    python3 validation/validator.py
    python3 validation/master_report.py

---

## API

Run:

    python3 -c "from core.api import serve; serve()"

Endpoints:
- GET /health  
- POST /generate  

---

## Lab UI

    cd lab
    python3 app.py

---

## Experiments

    python3 run/demo_reproducibility.py
    python3 run/population_shift_experiment.py
    python3 run/one_model_five_hospitals.py

---

## Determinism

- same seed → identical output  
- different seed → controlled variation  

No exceptions.

---

## Output

- CSV  
- JSON  

---

## Why this exists

Healthcare data is restricted.

Models still need data.

Most synthetic data:
- is not reproducible  
- cannot be audited  
- changes unpredictably  

This provides a controlled alternative.

---

## Summary

Core = deterministic execution  
Pipelines = generation  
Modules = behavior  
Analysis = inspection  

---

## Clinical modules

The core engine is open.

Additional modules have been developed and are available separately.

https://HipAAsynth.com
