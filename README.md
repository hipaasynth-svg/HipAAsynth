# HipAAsynth

Deterministic clinical data generation.

Same seed → same patients → every time.

---

## What this is

This is an engine that generates synthetic patient populations.

Not random.
Not AI-generated.
Not black box.

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
- `core/schema.py` → data contract  
- `core/anchor.py` → identity + state control  
- `core/anchor_stamp.py` → reproducibility tracking  

---

## Pipelines

Pipelines generate full cohorts.

They orchestrate modules and produce output.

Examples:

```bash
python3 pipelines/population_pipeline.py
python3 pipelines/diabetes_pipeline.py
python3 pipelines/cardiology_pipeline.py
python3 pipelines/rare_disease_pipeline.py
