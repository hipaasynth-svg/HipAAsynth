# Interoperability Roadmap — Change Log

Running log of the FHIR + OMOP interoperability work (Tier 1). One entry per
change: **what** was added/changed, **why** (which roadmap gap it closes), **how**
it was verified, and **known limitations**. Newest entries first.

The engine core stays pure-Python / standard-library. Optional interoperability
extras (e.g. Parquet) are gated behind `pip install hipaasynth[...]` and flagged
explicitly below.

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
