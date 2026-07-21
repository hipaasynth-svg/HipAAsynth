# HipAAsynth ⇄ OHDSI bridges

Bridges between HipAAsynth and the OHDSI tool ecosystem. Where
`hipaasynth/vocabulary/` and the OMOP exporter make HipAAsynth *output* speak
OHDSI, this package lets OHDSI artifacts *drive* HipAAsynth.

## ATLAS cohort ingestion (`atlas_cohort.py`)

Read an OHDSI ATLAS cohort definition (Circe JSON) and target a matching
synthetic cohort. **OHDSI defines the cohort; HipAAsynth generates the
under-represented population for it and stress-tests a model for fairness.**

```python
from hipaasynth.ohdsi import load_atlas_cohort
from hipaasynth.pipelines.population_pipeline import generate_patients

plan = load_atlas_cohort("heart_failure_cohort.json")   # path, JSON string, or dict
print(plan.coverage_summary())
# "2/3 concept(s) map to HipAAsynth terms; index condition = 'congestive_heart_failure'"

cfg = plan.to_generation_config(patient_count=500, seed=42)  # + profile=... etc.
patients = generate_patients(cfg)   # every patient carries the cohort's index condition
```

### What it does

- Reads the definition's **concept sets** and reverse-maps each concept through
  the HipAAsynth vocabulary (`terms_for_concept_id`).
- Reports coverage: `plan.matched` (concepts HipAAsynth can generate) and
  `plan.unmatched` (concepts it can't yet — surfaced, never silently dropped).
- Resolves the **entry/primary criteria** to an index condition and seeds every
  synthetic patient with it via `GenerationConfig.required_condition`.
- Accepts both a bare Circe `expression` and the ATLAS WebAPI wrapper
  (`{"expression": "<json string>"}`).

### Scope (v1)

Condition concept sets and the primary condition drive generation. Measurement
and drug criteria are reported as matched/unmatched but do not yet parameterize
the cohort. Full Circe inclusion-rule evaluation (temporal windows, nested
criteria) is out of scope — this targets the cohort's clinical *content*, not
its full logical definition.

### Reverse mapping quality

Reverse lookup uses the OMOP `concept_id`s in the vocabulary map, which are
`curated-pending-athena` until validated (see `hipaasynth/vocabulary/README.md`).
Concepts map to the generator term that HipAAsynth actually accepts
(`ALLOWED_CONDITIONS`) when several synonyms exist.

## ACHILLES / DQD-style CDM audit (`cdm_audit.py`)

Run OHDSI-style **characterization** (ACHILLES) and **data-quality checks**
(DataQualityDashboard) directly over a HipAAsynth OMOP CDM cohort — pure Python,
no OMOP database, R/Java, or network access required. The output is a **realism /
QA credential**: evidence that a synthetic cohort passes the same structural and
plausibility checks a real OMOP database is held to.

```python
from hipaasynth.exporters.omop import build_cdm_tables
from hipaasynth.ohdsi import audit_cdm, render_markdown

report = audit_cdm(build_cdm_tables(patients))   # or a path to exported CSVs
print(render_markdown(report))
```

Or from the command line, against an exported cohort:

```bash
python -m hipaasynth.ohdsi.cdm_audit --omop-dir omop_cdm --out audit.md --json audit.json
```

- **Characterization** — person/record counts, gender and age-band distributions,
  top conditions and drugs, per-measurement value summaries.
- **Data-quality checks** — a representative battery across DQD's three
  categories: **Conformance** (required fields, unique/valid keys, person foreign
  keys), **Completeness** (populated dates/values, standard-concept mapping
  rates), and **Plausibility** (birth-year range, non-negative values, ordered
  visit dates). Each check has a failure threshold and PASS / FAIL /
  NOT_APPLICABLE status; the CLI exits non-zero if any check fails.

Scope: a defensible representative subset, not a re-implementation of DQD's full
check catalogue. Drug rows with `concept_id = 0` (ATC-class terms) are expected
and are not counted against condition/measurement mapping completeness.
