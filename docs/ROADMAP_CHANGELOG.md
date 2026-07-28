# Interoperability Roadmap — Change Log

Running log of the FHIR + OMOP interoperability work (Tier 1 + Tier 2). One entry
per change: **what** was added/changed, **why** (which roadmap gap it closes),
**how** it was verified, and **known limitations**. Newest entries first.

The engine core stays pure-Python / standard-library. Optional interoperability
extras (e.g. Parquet) are gated behind `pip install hipaasynth[...]` and flagged
explicitly below.

> **Base branch note (Tier 2).** Tier 1 (PR #81) was still an *open draft* — not
> merged into `main` — when Tier 2 began, so the Tier-2 branch is stacked directly
> on the Tier-1 branch. Until #81 merges, the Tier-2 PR diff includes the Tier-1
> commits; it targets `main` and collapses to Tier-2-only once #81 lands.

---

# Tier 2 — new capabilities (CLI, REST API, SDK)

New network- and developer-facing surfaces built on the Tier 1 exporters. Each
change is additive and gated on a fails-before / passes-after test.

## Step 6 — CLI polish + real `hipaasynth` entry point

**What.**
  - `pyproject.toml` now declares `[project.scripts] hipaasynth =
    "hipaasynth.run.main:main"`, so `pip install -e .` yields a real `hipaasynth`
    console command (there was **no** installable entry point before).
  - `hipaasynth/run/main.py` gains two additive flags:
    - `--format {json,csv,fhir-bundle,ndjson,parquet,omop}` (one or more) — exposes
      every Tier 1 export format from the CLI. Written to deterministic paths under
      `--out` (`cohort.json`, `cohort.csv`, `cohort_fhir.json`,
      `cohort_fhir_ndjson/`, `cohort.parquet`, `omop_cdm/`).
    - `--validate` — runs the Step-3 structural FHIR validator over the generated
      cohort (the written bundle/NDJSON if one was exported, else in-memory FHIR
      resources) and exits non-zero on structural failure.
  - `main()` is now `main(argv=None)` and returns an int exit code, so it is both
    the console-script target and directly testable.

**Backwards compatibility (explicit).** Every pre-Tier-2 flag
(`--demo --count --seed --out --profile`) is unchanged, and **with no `--format`**
the CLI writes the exact same JSON + CSV + FHIR-bundle triple to the exact same
filenames as before — verified by `test_default_run_writes_legacy_triple` and
`test_legacy_default_flags_still_parse`.

**Why.** Roadmap Tier 2 step 1: there was no installable command, and the Tier 1
formats (NDJSON/Parquet/OMOP/validator) were unreachable from the CLI.

**Dependency decision.** None added — `--format parquet` reuses the existing lazy
`pyarrow` import inside `export_parquet` (the `[parquet]` optional extra); the CLI
itself is stdlib-only (`argparse`).

**How verified.** `tests/test_cli.py` (11 tests): entry-point declaration (fails on
the pre-Tier-2 `pyproject.toml`), legacy-triple default, each new format writes its
artifact, multi-format, `--validate` PASS on a clean cohort (both written-artifact
and in-memory paths), bad-format rejection. Beyond the unit tests, the **real
installed command** was run: `pip install -e .` then
`hipaasynth --count 3 --format json ndjson --validate` → exit 0, artifacts written,
`FHIR validation (written NDJSON export): 41 resources — PASS`. Full suite green
(281 passed, 1 skipped — the pre-existing pandas-dtype seismometer skip).

**Known limitations.** `--format` writes to fixed filenames under `--out` (no
per-format path override); the validator remains structural-only (see Step 3).

---

# Tier 2 — review fixes to the Tier 1 FHIR/OMOP work

Six defects found in review of the Tier 1 exporters, each fixed with a
fails-before / passes-after test. Applied on the Tier-2 branch (see base-branch
note above).

## Tier 2 review fix 6 — CI zero-dep check scoped to the file that owns the extra

**What.** `.github/workflows/test.yml` "Check zero external dependencies" no longer
whitelists `pyarrow`/`fhir` by bare module name across the whole `hipaasynth/`
tree. The exemption is now a per-file allowlist — `EXEMPT = {'hipaasynth/exporters/
exporters.py': {'pyarrow', 'fhir'}}` — so those optional-extra imports are tolerated
only in the file that lazily imports them behind a `[project.optional-dependencies]`
extra. Any external import elsewhere (including an accidental `pyarrow`/`fhir`
import in another core module) fails the check.

**Why.** The tree-wide whitelist weakened the guardrail meant to keep the rest of
the core stdlib-only: an accidental `import pyarrow` anywhere would have passed
silently.

**How verified (item-6 fake-import test, run locally and then removed):**
  - Clean tree → `Zero external dependencies: PASS` (exit 0).
  - Temporarily appended `import pyarrow` to `hipaasynth/core/config.py` (an
    unrelated core file) → check now **FAILS**: `EXTERNAL DEPS FOUND (outside their
    allowed file): hipaasynth/core/config.py: pyarrow` (exit 1). The **old**
    tree-wide whitelist would have passed this.
  - The same import inside the exempt `exporters.py` still PASSES (exemption
    preserved for the file that owns the extra).
  - Fake import removed; tree restored → PASS (exit 0); `git status` clean.

**Known limitations.** The allowlist is keyed by exact repo-relative path, so if
`export_parquet` is ever split into a new module the allowlist must be updated in
lockstep (intentional — a new file importing an extra should be a conscious
decision, not silent).

---

## Tier 2 review fix 5 — FHIR `Encounter.actualPeriod` now carries `end`

**What.** `_patient_to_fhir()` in `hipaasynth/exporters/exporters.py` now emits
`actualPeriod: {"start": visit.visit_date, "end": visit.visit_date}` for each
Encounter (previously only `start`).

**Why.** The OMOP exporter already sets `visit_end_date = visit_start_date` under
an explicit same-day-visit assumption; the FHIR Encounter dropped the end entirely,
so the two exporters disagreed on the same modeled fact.

**How verified.** `tests/test_fhir_interop.py::test_encounter_actual_period_has_end_equal_to_start`
asserts every Encounter's `actualPeriod["end"] == actualPeriod["start"]`. Fails
before (`actualPeriod is missing 'end'`, verified by stashing the source), passes
after. Full suite green.

**Known limitations.** Same-day is a modeling assumption HipAAsynth makes across
both exporters, not a claim visits are truly zero-length; documented inline.

---

## Tier 2 review fix 4 — validator API re-exported from `hipaasynth.exporters`

**What.** `hipaasynth/exporters/__init__.py` now re-exports `validate_resource`,
`validate_resources`, `validate_bundle`, `validate_ndjson_dir`, and
`FhirValidationReport` from `fhir_validate`, and gains an `__all__` covering the
whole exporter surface.

**Why.** Every other exporter (`export_csv`, `export_fhir`, `export_parquet`,
`build_cdm_tables`, …) is reachable via `from hipaasynth.exporters import X`; the
validator functions were only importable from the deep submodule path — an
inconsistency for callers (and the upcoming SDK/CLI).

**How verified.** `tests/test_fhir_validate.py::test_validator_functions_reexported_from_package`
imports all five from the package root, asserts they are the *same objects* as the
submodule's, and smoke-runs `validate_resources`. Fails before (`ImportError`,
verified by stashing `__init__.py`), passes after. Full suite green.

**Known limitations.** None — pure re-export, no behavior change.

---

## Tier 2 review fix 3 — OMOP `condition_status_concept_id` driven by `Condition.active`

**What.** `hipaasynth/exporters/omop.py`: new `_CONDITION_STATUS_CONCEPT` lookup
(keyed by `active: True/False`) and `_condition_status()` helper (mirrors
`_gender_concept_id`). The condition row's `condition_status_concept_id` and
`condition_status_source_value` are now populated from `cond.active` instead of
being hardcoded to `0`/`""`.

**Why.** `Condition.active` already drives the FHIR `clinicalStatus` coding, but
the OMOP condition row threw the information away (`condition_status_concept_id`
was always `_NO_CONCEPT`).

**⚠️ Dependency/validation note — UNVALIDATED concept_ids (flagged, same as the
rest of this map).** OMOP's dedicated *Condition Status* vocabulary encodes
diagnosis **position** (primary/secondary/admission/discharge), **not**
active/inactive — the active/inactive distinction is a SNOMED clinical-status
concept. The two ids used (`4230911` active, `4033240` inactive) are **best-effort
SNOMED clinical-status concepts** and are **not** confirmed against a pinned ATHENA
release in this sandbox (no ATHENA network here — the whole OMOP map is
`athena-verified-partial`). The active/inactive **text** is preserved in
`condition_status_source_value` so a consumer can re-resolve the ids offline. These
ids are metadata concepts, not clinical concepts, so they are deliberately outside
the `concept_map.json` drift guard (like `gender_concept_id` and
`condition_type_concept_id`, which are also standard OMOP concepts not in the map).

**How verified.** `tests/test_omop_cdm54.py::test_condition_status_concept_id_reflects_active`:
an active vs. inactive condition get **distinct, non-zero** ids and the matching
`"active"`/`"inactive"` source_value. Fails before the change (`assert 0 != 0`,
verified by stashing the source), passes after. Full suite green. *What is
verified is the behavior (driven by `active`, distinct, non-zero, correct source
text) — not the exact concept_ids, which need ATHENA confirmation.*

---

## Tier 2 review fix 2 — CLI entry point `fhir_validate.main()` now under test

**What.** `tests/test_fhir_validate.py` gains four tests that exercise the CLI
entry point directly: `main(["--bundle", path])` on a clean cohort (exit 0), on a
structurally broken Bundle (exit 1), with `--json report.json` (asserts the report
file is written and carries the `total_resources`/`error_count`/`ok`/`errors`/
`disclaimer` keys), and `main(["--ndjson-dir", dir])` on a real bulk-export
directory (exit 0).

**Why.** The Step-3 tests only called the library functions; `main()` — argument
parsing, Bundle-vs-NDJSON dispatch, JSON-report writing, exit codes — had **zero**
coverage, so a regression to the CLI would pass CI. This is added coverage, not a
behavior change (the CLI already worked when run by hand).

**How verified.** New tests pass; the broken-Bundle test asserts a non-zero exit,
proving `main()` actually surfaces validation failures (not a vacuous exit-0). Full
suite green.

**Known limitations.** Exercises the in-process `main(argv)` path; does not spawn a
subprocess, so it doesn't cover `__main__`/`SystemExit` shell wiring (that line is
a one-liner `raise SystemExit(main())`).

---

## Tier 2 review fix 1 — validator now checks all emitted CodeableConcept fields

**What.** `hipaasynth/exporters/fhir_validate.py`: `_CODEABLE_CONCEPT_FIELDS` now
also registers `Condition.clinicalStatus`, `Condition.verificationStatus`,
`Encounter.class`, and `Encounter.type`. Because `Encounter.class`/`.type` are
0..* **lists** of CodeableConcept (not a single dict), `validate_resource` now
detects a list at a path and checks each element (existing single-dict paths are
unchanged). The module docstring and the Step-3 entry above were corrected to
enumerate exactly which fields are checked.

**Why.** `_patient_to_fhir()` emits those four as CodeableConcept-shaped data, but
the Step-3 validator never looked at them: an empty `clinicalStatus: {}`, a
`verificationStatus.coding` missing its `code`, or an `Encounter.class` coding
missing its `code` all returned `[]` (no error) — false assurance.

**How verified.** `tests/test_fhir_validate.py`: four new broken-input tests
(`test_broken_condition_clinical_status_is_flagged`,
`test_broken_condition_verification_status_is_flagged`,
`test_broken_encounter_class_is_flagged`, `test_broken_encounter_type_is_flagged`)
plus a false-positive guard (`test_valid_encounter_class_and_type_pass`). The four
broken-input tests fail on the pre-fix validator (verified by stashing the source:
all four `AssertionError: []`) and pass after. Full suite green.

**Known limitations.** Still structural-only — unchanged from Step 3 (not a
substitute for the official HL7 FHIR IG validator).

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
  4. the `CodeableConcept`-shaped fields the exporter actually emits carry a
     `coding[]` or `text`, and each coding has a `system` + `code`. **The checked
     set is explicit** (see `_CODEABLE_CONCEPT_FIELDS`): `Condition.code`,
     `Condition.clinicalStatus`, `Condition.verificationStatus`, `Observation.code`,
     `Encounter.class`, `Encounter.type` (the last two are 0..* lists), and
     `{MedicationStatement,MedicationRequest}.medication.concept`. *(The
     `clinicalStatus`/`verificationStatus`/`Encounter.class`/`Encounter.type`
     entries — and list-at-path support — were added in Tier 2 review fix 1; the
     original Step-3 validator only checked `Condition.code`, `Observation.code`,
     and the two medication concepts, so the status/class/type fields were emitted
     but never validated.)*
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
