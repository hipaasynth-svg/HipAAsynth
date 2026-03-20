# HipAAsynth

Deterministic clinical data generation.

Same seed → same patients → every time.

---

## What this is

This is an engine that generates synthetic patient populations.

Not random.  
Not AI-generated.  
Not a black box.  

Deterministic.

You can reproduce every dataset exactly.  
You can audit every output.  
You can trace how it was built.

---

## What it does

- generates full patient cohorts  
- controls all randomness through a single seed  
- produces identical output given identical inputs  
- supports multiple clinical domains  
- exports to CSV, JSON, FHIR  

---

## What it is not

This is not trying to simulate the entire healthcare system out of the box.

The core engine gives you:
- structure  
- patients  
- controlled execution  

Real clinical behavior is layered on top.

---

## System layout

Core → guarantees determinism  
Pipelines → generate cohorts  
Modules → add clinical behavior  
Analysis → proves it works  

---

## Core

The core enforces the rules:

- no hidden randomness  
- no module-level RNG  
- single master seed  
- fixed execution path  

Files:
- core/schema.py → data contract  
- core/anchor.py → identity + state control  
- core/anchor_stamp.py → reproducibility tracking  

---

## Pipelines

Pipelines generate full cohorts.

They orchestrate modules and produce output.

Examples:

    python3 pipelines/population_pipeline.py
    python3 pipelines/diabetes_pipeline.py
    python3 pipelines/cardiology_pipeline.py
    python3 pipelines/rare_disease_pipeline.py

Each pipeline:
- builds a population  
- applies domain logic  
- outputs a complete dataset  

---

## Modules

Modules control behavior.

This is where realism comes from:
- disease progression  
- outcomes  
- lab dynamics  
- comorbidities  

Core stays stable.  
Modules evolve.

Some modules are included.  
Advanced domain modules are distributed separately.

---

## Analysis + Validation

This is what separates this from a toy.

Included:

- bias detection  
- drift monitoring  
- fidelity scoring  
- privacy checks  
- temporal validation  
- trust scoring  

Examples:

    python3 validation/validator.py
    python3 validation/master_report.py

You can measure:
- how realistic the data is  
- how stable it is across runs  
- whether it leaks real-world patterns  

---

## API

Run the engine as a service:

    python3 -c "from core.api import serve; serve()"

Endpoints:

- GET /health → engine status  
- POST /generate → generate cohort  

---

## Lab UI

Simple web interface:

    cd lab
    python3 app.py

Used to:
- generate cohorts  
- compare outputs  
- run experiments  

---

## Experiments

Reproducibility:

    python3 run/demo_reproducibility.py

Population shift:

    python3 run/population_shift_experiment.py

Model testing:

    python3 run/one_model_five_hospitals.py

---

## Determinism

This is the point.

- same seed → identical output  
- different seed → controlled variation  

No exceptions.

---

## Output

- CSV  
- JSON  
- FHIR  

Designed for:
- testing  
- simulation  
- model training  
- system validation  

---

## Why this exists

Healthcare data is restricted.

Models still need data.

Most synthetic data:
- isn’t reproducible  
- can’t be audited  
- drifts unpredictably  

This fixes that.

---

## Summary

Core = engine  
Pipelines = generation  
Modules = behavior  
Analysis = proof  

Everything deterministic.

---

## Access modules

https://HipAAsynth.com
