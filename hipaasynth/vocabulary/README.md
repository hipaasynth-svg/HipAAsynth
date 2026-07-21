# HipAAsynth Vocabulary Layer (OHDSI / OMOP)

This package maps the finite, controlled set of internal term strings that
HipAAsynth generators emit — condition names, lab names, visit types — to
standard clinical terminologies and OMOP standard `concept_id`s. It is the
foundation for HipAAsynth's integration with the OHDSI tool ecosystem.

## Why this exists

HipAAsynth output was previously **text-only**: a condition was the string
`"congestive_heart_failure"`, a lab was `"bnp"`. Text strings are not queryable
in [ATLAS](https://atlas-demo.ohdsi.org/), cannot populate OMOP CDM tables, and
fail every vocabulary check in
[DataQualityDashboard](https://github.com/OHDSI/DataQualityDashboard). Mapping
each term to a standard concept unlocks the entire OHDSI stack — ATLAS,
ACHILLES, DQD, HADES — plus makes the FHIR export valid for coding-aware EHR
tooling.

Because HipAAsynth generates from a bounded internal vocabulary (not free text),
this is a small, curated, versioned map — not an open-ended NLP mapping problem.

## What's in the map

`concept_map.json` has three sections:

| Section | Source terms | Standard codes attached |
|--------------|----------------------------------|--------------------------------------|
| `conditions` | e.g. `congestive_heart_failure`  | SNOMED CT, ICD-10-CM, OMOP concept_id |
| `measurements` | e.g. `Glucose`, `bnp`, `egfr`  | LOINC, OMOP concept_id, UCUM unit     |
| `visits`     | e.g. `outpatient`, `telehealth`  | OMOP visit concept_id                 |

## API

```python
from hipaasynth.vocabulary import (
    lookup_condition, lookup_measurement, lookup_visit, unmapped_terms,
)

m = lookup_condition("congestive_heart_failure")
m.snomed_code        # "42343007"
m.omop_concept_id    # 316139
m.fhir_coding()      # [{"system": "http://snomed.info/sct", ...}, ...]

# CI coverage check — assert nothing a generator emits is unmapped:
unmapped_terms(conditions=[...], measurements=[...], visits=[...])
```

Lookups are case-insensitive and return `None` for unmapped terms (callers
decide whether that is fatal; the exporters degrade gracefully to text-only /
`concept_id = 0`).

## ⚠️ Validation status: `curated-pending-athena`

The **terminology codes** (SNOMED / ICD-10-CM / LOINC) are stable identifiers.
The **OMOP `concept_id` values are release-versioned** and are curated
best-effort — the map metadata carries `"validation_status":
"curated-pending-athena"` and `"vocabulary_release": "UNVALIDATED"`.

**Before using OMOP output in production tooling**, validate the `concept_id`
values against a pinned [ATHENA](https://athena.ohdsi.org/) vocabulary download.
This is automated — you do not check it by hand:

1. Download the vocabulary bundle from ATHENA (SNOMED, LOINC, RxNorm, ICD-10-CM
   at minimum) and note the release date — this becomes the pinned
   `vocabulary_release`. (ATHENA bundles are license-gated: you register, accept
   per-vocabulary terms, and receive the bundle. There is no anonymous download,
   which is why this step is run by a human with an account rather than fetched
   automatically.)
2. Run the validator against the bundle's `CONCEPT.csv`:

   ```bash
   python -m hipaasynth.vocabulary.validate --concept-csv /path/to/CONCEPT.csv
   ```

   It checks every mapped `concept_id` for existence, `standard_concept = 'S'`,
   the expected `domain_id`, and (for conditions/measurements) that
   `concept_code` equals the SNOMED/LOINC code recorded here. Exit code is
   non-zero if anything fails, so it can gate CI. No network access is needed at
   runtime — it reads the local file.

3. Once it passes, record the release and flip the status in one step:

   ```bash
   python -m hipaasynth.vocabulary.validate --concept-csv /path/to/CONCEPT.csv \
       --write-status --release "ATHENA 2026-07"
   ```

4. Use [Usagi](https://github.com/OHDSI/Usagi) to review any *additions* when new
   generator terms are introduced — it fuzzy-matches source terms to standard
   concepts with human review, which is the OHDSI-sanctioned workflow — then
   re-run the validator.

## Adding a new generator term

1. Add the term to the appropriate section of `concept_map.json` (Usagi-assisted).
2. Add it to the coverage list in `tests/test_vocabulary.py` so CI enforces it.
3. Re-run validation against the pinned ATHENA release.

## Licensing note

LOINC and RxNorm are freely redistributable. SNOMED CT use is covered in the US
via the UMLS Metathesaurus license (free) and in other territories via national
SNOMED affiliate licensing. The OMOP `concept_id` integer layer is the standard
interchange mechanism across the OHDSI network and is what most downstream tools
key on.
