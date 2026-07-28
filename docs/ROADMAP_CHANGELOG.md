# Interoperability Roadmap — Change Log

Running log of the FHIR + OMOP interoperability work (Tier 1). One entry per
change: **what** was added/changed, **why** (which roadmap gap it closes), **how**
it was verified, and **known limitations**. Newest entries first.

The engine core stays pure-Python / standard-library. Optional interoperability
extras (e.g. Parquet) are gated behind `pip install hipaasynth[...]` and flagged
explicitly below.

---

## Step 5 — Parquet export

**What.** New `export_parquet(patients, filename="output.parquet")` in
`hipaasynth/exporters/exporters.py` (re-exported from `hipaasynth.exporters`). It
writes the same flat patient table as `export_csv` — the row/column builder was
extracted into a shared `_flat_patient_rows()` helper so the two exporters can
**never drift** — but in columnar Apache Parquet, suited to analytics engines
(DuckDB, Spark, pandas, the Seismometer adapter).

**Why.** Roadmap step 5. CSV existed; Parquet did not.

**Dependency decision — flagged for the user to sanity-check.** The PR template
checklist states *"No external dependencies added (the engine is pure Python
standard library)."* Parquet inherently needs a columnar writer, so I did **not**
add a hard dependency:
  - The engine **core stays stdlib-only.** `pyarrow` is imported **lazily inside
    `export_parquet`** — importing `hipaasynth` or any core module pulls in nothing
    new.
  - `pyarrow` is exposed as a new **optional extra**: `pip install
    'hipaasynth[parquet]'` (added to `pyproject.toml`). `pyarrow` was already a
    dependency of the existing `seismometer` extra, so it introduces no new
    project-level supply-chain surface.
  - Calling `export_parquet` without pyarrow installed raises a clear
    `RuntimeError` naming the extra — no `ImportError` leaking from an optional path.

  **This is the one place Tier 1 touches the "no external dependencies" value.** It
  is confined to an opt-in extra and an opt-in function; please confirm this is the
  trade-off you want (vs. e.g. a hand-rolled minimal Parquet writer, which would be
  far more code and risk for less correctness).

**How verified.** `tests/test_parquet_export.py`:
  - `test_parquet_roundtrip_matches_csv_columns` — writes, reads back with pyarrow,
    row count and base columns match.
  - `test_parquet_values_match_csv` — `patient_id` column agrees row-for-row with
    the CSV exporter.
  - `test_parquet_missing_dependency_is_graceful` — monkeypatches the import to
    simulate pyarrow absent; asserts a `RuntimeError` mentioning `pyarrow` and the
    `parquet` extra. (This one runs with or without pyarrow installed.)

  The round-trip tests `pytest.importorskip("pyarrow")`. pyarrow **was installed in
  this sandbox** to exercise them for real (they pass, 25.0.0); in a stdlib-only CI
  they skip while the missing-dependency test still runs. `export_csv`'s refactor to
  the shared helper is covered by the unchanged existing CSV tests (still green).
  Full suite green (258 passed).

**CI note.** The Tests workflow has a "Check zero external dependencies" step that
AST-walks `hipaasynth/` and fails on any non-stdlib import (`ast.walk` sees
function-level imports too, so the lazy `import pyarrow` is caught). The check
already pre-declares the `fhir` optional extra in its allowlist; `pyarrow` was
added the same way (`.github/workflows/test.yml`). The core remains free of any
*required* runtime dependency — this only permits the declared optional extra.

**Known limitations.** Parquet mirrors the flat *patient-level* table (like
`export_csv`), not the OMOP CDM tables or the FHIR resources. Per-column type is
inferred by pyarrow, with a string fallback for any heterogeneously-typed
observation column.

---

## Step 4 — Complete OMOP CDM 5.4 export

**Audit — what was missing (before this change).** `build_cdm_tables()` emitted the
5 fact/dimension tables with only their required NOT-NULL columns plus a few source
values. Measured against the CDM 5.4 spec, the gaps were:

| Table | Gap found |
|---|---|
| *(whole CDM)* | **`OBSERVATION_PERIOD` table entirely absent** — OHDSI cohort tooling (ATLAS/ACHILLES) effectively requires it; cohorts are defined relative to observation periods. |
| `DRUG_EXPOSURE` | **`drug_exposure_end_date` missing** — it is NOT NULL in CDM 5.4. Real conformance gap. |
| `PERSON` | `demographics.ethnicity` was **dropped** (race/ethnicity concept_ids 0 and no source value preserved). Plus missing `*_source_concept_id`, `month/day_of_birth`, etc. |
| `CONDITION_OCCURRENCE` | no `visit_occurrence_id` link; missing `condition_end_date`, `condition_status_concept_id`, `*_datetime`. |
| `MEASUREMENT` | no `visit_occurrence_id` link; `range_low`/`range_high` not populated (the lab reference range was discarded); missing `unit_concept_id`, `value_as_concept_id`, `operator_concept_id`. |
| `VISIT_OCCURRENCE` | missing `visit_source_concept_id`, `*_datetime`, `admitted_from`/`discharged_to`, `preceding_visit_occurrence_id`. |

**What was changed.** `hipaasynth/exporters/omop.py`:
  - **Added `OBSERVATION_PERIOD`** — one row per person spanning `min`→`max` visit
    date, `period_type_concept_id = 32817` (EHR). Written as `observation_period.csv`.
  - **Filled every table to the full CDM 5.4 column set** (required + high-value
    optional). Columns HipAAsynth does not model are emitted **empty** rather than
    omitted, so the CSVs load directly against the standard OHDSI CDM DDL without
    column-mismatch errors — the concrete "usable dataset" win.
  - **`drug_exposure_end_date`** now populated (NOT NULL fix). Duration is not
    modeled, so `end == start` (a single-day exposure) — an honest default, not a
    fabricated span.
  - **Visit linkage** — `condition_occurrence`, `drug_exposure`, and `measurement`
    now carry `visit_occurrence_id` (measurements to their own visit; conditions/
    drugs to the person's first visit, matching the existing start-date logic).
  - **Reference range preserved** — `measurement.range_low`/`range_high` parsed
    from the lab's reference range for plain numeric `low-high` strings (e.g.
    `70-99`); non-numeric ranges like `<100` are left empty rather than guessed.
  - **Race/ethnicity source preserved** — HipAAsynth's single demographic category
    (`demographics.ethnicity`, which is race-like) is written to
    `race_source_value` so it is no longer dropped. Standard race/ethnicity
    concept mapping stays `0` (unmapped/unvalidated), unchanged.

**Concept-id drift cross-check (roadmap requirement).** A new test asserts that
**every non-zero standard `*_concept_id` the exporter emits exists in
`concept_map.json`** (via the vocabulary reverse index), so the OMOP export cannot
silently drift from the vocabulary work validated in PRs #75–#79. No new
concept_ids were invented — all values still come from `hipaasynth.vocabulary`
lookups; `concept_map.json` metadata confirms `omop_cdm_version: 5.4`.

**How verified.** `tests/test_omop_cdm54.py` (new, 9 tests) — observation_period
present/one-per-person/dates-ordered/valid FK; all CDM 5.4 required columns present
in every table; drug end date populated and equal to start; measurement→visit link
+ parsed numeric range; condition→visit link; race source preserved; **no
concept_id drift**; export writes `observation_period.csv`. The pre-existing
`test_vocabulary.py` structure assertion was updated to include the new
`observation_period` table (intentional addition). All fail before the change and
pass after; full suite green (255 passed). The existing ACHILLES/DQD-style audit
(`hipaasynth/ohdsi/cdm_audit.py`) still passes clean over the expanded tables.

**Known limitations.**
  - The bundled DQD-style adapter (`cdm_audit.py`) audits the 5 core fact/dimension
    tables; it does **not yet** run checks over the new `OBSERVATION_PERIOD` table.
    The table is written and structurally correct, but not covered by that adapter's
    battery (a reasonable follow-up).
  - concept_ids remain **UNVALIDATED / athena-verified-partial** per the vocabulary
    map metadata — validate against a pinned ATHENA release before production use.
  - Optional columns HipAAsynth does not model (provider/care_site links, datetimes,
    days_supply, etc.) are intentionally empty.

---

## Step 3 — Structural FHIR validator

**What.** New module `hipaasynth/exporters/fhir_validate.py` — an offline,
pure-Python **structural** validator for the exporter's FHIR output:
  - `validate_resource(resource) -> list[str]` — single-resource checks.
  - `validate_resources(resources) -> FhirValidationReport` — batch + referential
    integrity.
  - `validate_bundle(bundle)` / `validate_ndjson_dir(dir)` — convenience wrappers
    over the Bundle (step-1) and NDJSON (step-2) artifacts.
  - `main()` CLI: `python -m hipaasynth.exporters.fhir_validate --bundle b.json`
    or `--ndjson-dir dir/` (exit 0 = clean, 1 = errors).

  Checks performed (against **FHIR R5** shapes):
  1. `resourceType` present and one HipAAsynth emits;
  2. required (1..1) fields present per type (e.g. Observation needs `status` +
     `code`; MedicationRequest needs `status`/`intent`/`subject`/`medication`);
  3. value-set membership for bound fields we can check offline (Patient.gender,
     the four resource `status` sets, MedicationRequest.intent);
  4. `CodeableConcept` fields carry a `coding[]` or `text`, and each coding has a
     `system` + `code`;
  5. **referential integrity** — every intra-bundle `urn:uuid:` reference resolves
     to a resource `id` present in the set.

**Why.** Roadmap step 3. Gives a fast, dependency-free pre-flight check that
catches the structural mistakes an exporter is most likely to make, runnable in CI
with no network.

**⚠️ Explicit limitation — NOT a conformance validator.** This does not load
StructureDefinitions, does not check terminology bindings against a terminology
server, does not evaluate FHIRPath invariants, and does not verify US Core / any
Implementation Guide profile. **No offline official IG validator is available in
this sandbox** (no network to the HL7 registry / `validator_cli.jar`). Before any
conformance claim, a human must run the official HL7 FHIR validator
(https://validator.fhir.org) against the exported artifacts. The module docstring,
the report's `disclaimer` field, and the CLI output all say this.

**Validated / not validated (be precise):**
  - *Checked by me:* the required-field, value-set, CodeableConcept, and
    referential-integrity rules above; the whole generated cohort (with meds)
    passes clean; the CLI validates both a real Bundle and a real NDJSON dir (37
    resources, PASS).
  - *NOT checked (needs the official validator / a live server):* profile
    conformance, terminology binding correctness, invariant/FHIRPath rules, and
    whether a real EHR will ingest the output.

**How verified.** `tests/test_fhir_validate.py`: clean cohort passes; missing
`code`, unknown resourceType, invalid gender, empty CodeableConcept, and a dangling
reference are each flagged; an exported Bundle validates clean. Tests fail before
the module exists (ModuleNotFoundError) and pass after. Full suite green (246
passed).

---

## Step 2 — Bulk / NDJSON FHIR export

**What.** New `export_fhir_ndjson(patients, output_dir="fhir_ndjson")` in
`hipaasynth/exporters/exporters.py` (also re-exported from
`hipaasynth.exporters`). It groups every resource from `_patient_to_fhir()` by
`resourceType` and writes one `{ResourceType}.ndjson` file per type (e.g.
`Patient.ndjson`, `Condition.ndjson`, `MedicationRequest.ndjson`), one resource
per line. Returns `{resourceType: count}`. Fails loud (`RuntimeError`) on any I/O
error, consistent with the other exporters.

**Why.** Roadmap step 2 — the FHIR Bulk Data Access (`$export`) convention. Bulk
ingestion pipelines (SMART Bulk Data, many EHR import tools) expect
newline-delimited resource files grouped by type, not a single Bundle.

**Additive.** The existing single-Bundle `export_fhir()` is untouched; both modes
are available and (verified) cover the same resource set.

**How verified.** `tests/test_fhir_interop.py`:
  - `test_ndjson_export_one_file_per_resource_type` — every declared type has a
    file; each line is standalone JSON of the correct `resourceType`; line count
    matches returned count.
  - `test_ndjson_one_patient_line_per_patient` — `Patient.ndjson` has exactly one
    line per patient.
  - `test_ndjson_matches_bundle_resource_set` — per-type counts equal the
    single-Bundle export's counts (no resource dropped or duplicated).
  - `test_ndjson_fails_loud_on_io_error` — surfaces I/O errors.

  All fail before the function exists (ImportError) and pass after. Full suite
  green (239 passed).

**Known limitations.** Writes plain `.ndjson` files only; it does not implement the
`$export` *kickoff/polling REST protocol* or emit a Bulk Data `manifest`/
`OperationOutcome`. The files are the on-disk artifact that protocol would serve.

---

## Step 1 — Complete the FHIR resource set

### 1a. Add `MedicationRequest` alongside `MedicationStatement`

**What.** `_patient_to_fhir()` (`hipaasynth/exporters/exporters.py`) now emits a
`MedicationRequest` resource for every `Medication` on a patient, *in addition to*
the existing `MedicationStatement`. Both share the same `CodeableConcept`
(vocabulary-derived ATC/RxNorm coding + text). The `MedicationRequest` carries the
R5-required fields: `status` (`active` when the med is active, else `stopped`),
`intent` (`order`), `subject`, and `medication.concept`. Resource ids are
SHA-anchored/deterministic (`medicationrequest::{pid}::{name}::{i}` via `uuid5`),
consistent with the rest of the exporter.

**Why.** Roadmap step 1 asks for `MedicationRequest`. It closes an interoperability
gap: US Core / USCDI model the "Medications" data class primarily on
`MedicationRequest`, so consumers (EHR ingestion, US Core validators) look for it,
not `MedicationStatement`.

**Decision — keep both, do not replace (for the user to sanity-check).**
`MedicationStatement` is retained because:
  1. It is already depended on — `tests/test_vocabulary.py::test_fhir_medication_statement`
     asserts it, and `hipaasynth/polymorphic/forms.py::_fhir_structured` consumes
     `_patient_to_fhir()` output. Replacing it would be a breaking change and
     violates the roadmap's "additive only" ground rule.
  2. The two resources carry genuinely different FHIR semantics —
     `MedicationStatement` is a *recorded fact* that the patient is/was on the drug;
     `MedicationRequest` is the *order/intent* behind it. A synthetic `Medication`
     (name + active flag) can defensibly project to both.

  **Known limitation / caveat to sanity-check:** emitting both means naïve
  analytics that count *all* medication resources will double-count. Consumers
  should filter by `resourceType`. If a single-resource projection is preferred
  later, `MedicationRequest` is the USCDI-aligned choice to keep.

**How verified.** `tests/test_fhir_interop.py` (new):
  - `test_medication_request_emitted_alongside_statement` — both resources present.
  - `test_medication_request_required_fields_and_coding` — `status`/`intent`/`subject`/
    `medication` present; ATC coding attached for `statin` (ATC `C10AA`).
  - `test_inactive_medication_request_is_stopped` — inactive → `status: stopped`.
  - `test_medication_request_id_is_deterministic` — stable ids across runs.

  All 4 fail against the pre-change exporter (`StopIteration`: no MedicationRequest)
  and pass after. Full suite: `python -m pytest` green (235 passed), no regressions.

### 1b. FHIR R4/R5 required-field audit of the existing resources

**What.** Manual audit (GitNexus MCP/CLI unavailable in this sandbox — see note at
bottom — so the call graph was traced by hand with grep/read) of the four existing
resource builders against FHIR required-field (1..1) cardinality and required
codings. Findings:

| Resource | Required fields (R4 & R5) | Status in exporter |
|---|---|---|
| `Patient` | *(none required)* | OK — carries `identifier`, `gender` (bound to AdministrativeGender via `_normalize_gender`), `birthDate`. |
| `Condition` | `subject` (1..1) | OK — `subject`, plus `clinicalStatus`/`verificationStatus`/`code` (CodeableConcept always has `text`). |
| `Observation` | `status` (1..1), `code` (1..1) | OK — `status="final"`, `code` always present with `text`. |
| `Encounter` | `status` (1..1); R4 also `class` (1..1) | OK — `status`, `class` present. |
| `MedicationStatement` | `status`, `subject`, `medication` (all 1..1) | OK. |
| `MedicationRequest` | `status`, `intent`, `subject`, `medication` (all 1..1) | OK (added in 1a). |

No required-field gaps were found that needed a code fix; the audit is recorded
here as the roadmap deliverable, and the structural checks are enforced
programmatically by the validator added in **Step 3**.

**Dialect note (important — R5, not dual-dialect).** The exporter emits **FHIR R5**
structural shapes, matching the module's existing docstring and behavior:
  - `Encounter.class` is emitted as an array of `CodeableConcept` (R5); R4 expects a
    single `Coding`.
  - `Encounter` period is `actualPeriod` (R5); R4 uses `period`.
  - `Encounter.status` uses `completed` (R5); R4 uses `finished`.
  - `Encounter.reason` uses the R5 `reason[].value` shape; R4 uses
    `reasonCode`/`reasonReference`.
  - `Medication[x]` uses the R5 `medication.concept` (CodeableReference); R4 uses
    `medicationCodeableConcept`.

The *required-field/cardinality* rules audited above hold for both R4 and R5, but
the **serialization** is R5. Producing R4-dialect output would be a separate,
explicitly-scoped change and is **not** claimed here.

---

## Sandbox limitations (applies to all entries)

- **GitNexus unavailable.** No GitNexus MCP tools are registered in this session,
  there is no `.gitnexus/run.cjs`, and `npx gitnexus analyze` exits non-zero with no
  usable output (the known native-binary failure). Impact/blast-radius analysis was
  therefore done manually (grep + read of the call graph) and is noted per change.
- **No official FHIR IG validator.** See Step 3 — the structural validator added
  there is not a substitute for the official HL7 FHIR validator, which must be run
  separately by a human before any conformance claim.
