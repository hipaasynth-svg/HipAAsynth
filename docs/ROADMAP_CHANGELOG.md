# Interoperability Roadmap — Change Log

Running log of the FHIR + OMOP interoperability work (Tier 1 + Tier 2 + Tier 3).
One entry per change: **what** was added/changed, **why** (which roadmap gap it
closes), **how** it was verified, and **known limitations**. Newest entries first.

The engine core stays pure-Python / standard-library. Optional interoperability
extras (e.g. Parquet, DuckDB) are gated behind `pip install hipaasynth[...]` and
flagged explicitly below.

> **Base branch note (Tier 2).** Tier 1 (PR #81) was still an *open draft* — not
> merged into `main` — when Tier 2 began, so the Tier-2 branch is stacked directly
> on the Tier-1 branch. Until #81 merges, the Tier-2 PR diff includes the Tier-1
> commits; it targets `main` and collapses to Tier-2-only once #81 lands.
>
> **Base branch note (Tier 3).** By the time Tier 3 began, both #81 (Tier 1) and
> #83 (Tier 2) had **merged into `main`**, so Tier 3 is built directly on `main`
> (no stacking) on a branch restarted from the latest `main`.

---

# Tier 3 — warehouse connectors + container packaging

Getting a generated cohort *into* the systems people actually analyze it in: a
real embedded warehouse (DuckDB), a cloud-warehouse schema/load-SQL generator
(BigQuery), and a container image for the REST API. Each change is additive and
gated on a fails-before / passes-after test.

## Step 11 — Docker packaging for the REST API (`Dockerfile`, `docker-compose.yml`)

**What.** A `Dockerfile` (and `.dockerignore` + a minimal `docker-compose.yml`)
that installs the package and runs the REST API as the container entrypoint:
  - `FROM python:3.11-slim`; copies `pyproject.toml`/`README.md`/`LICENSE.md` +
    `hipaasynth/` and runs `pip install --no-cache-dir .` (hatchling build).
  - Runs as a **non-root** user (`appuser`, uid 10001) — it's a network-facing
    service — `EXPOSE 8000`, a stdlib-only `HEALTHCHECK` hitting `/health`, and
    `ENTRYPOINT python -m hipaasynth.api` / `CMD --host 0.0.0.0 --port 8000`.
  - `docker-compose.yml`: one `api` service, `build: .`, `8000:8000`, `restart:
    unless-stopped`, and a tunable `--max-count` via `${HIPAASYNTH_MAX_COUNT}`.
  - `.dockerignore` keeps the context/image small (drops `.git`, `tests/`,
    `docs/`, caches, `*.duckdb`) while keeping the `README.md`/`LICENSE.md` the
    build needs.

**Why.** Roadmap Tier 3 step 3 — a deployable artifact for the REST API. Core-only
install keeps the image lean and stdlib-true; the `format=parquet` path returns a
clean 400 telling the caller to add the `[parquet]` extra (documented inline).

**Dependency decision.** None — the image installs only the stdlib-only core; no
optional extra is baked in by default.

**How verified — Dockerfile written; `docker` daemon UNAVAILABLE in this sandbox,
so NOT verified with a real `docker build`/`docker run`.** `docker build` here fails
with `failed to connect to the docker API at unix:///var/run/docker.sock … daemon`
(the CLI exists, the daemon does not). The Dockerfile's real logic was instead
verified by a **shell dry-run that executes the same steps**: staged the exact COPY
set, created a clean virtualenv (stand-in for `python:3.11-slim`), ran the
Dockerfile's `pip install .` (→ `Successfully installed hipaasynth-1.3.0`, console
script present), then ran the exact ENTRYPOINT+CMD (`python -m hipaasynth.api --host
0.0.0.0 --port 8000`) and confirmed the **verbatim HEALTHCHECK command returns exit
0**, `GET /health` → `{"status":"ok",…}`, and `GET /generate?...` → 200.
Additionally, `tests/test_docker.py` (9 tests) statically guards the artifacts:
base image, package-install step, EXPOSE/ENTRYPOINT/CMD, non-root ordering,
healthcheck endpoint, `.dockerignore` rules, compose build/port/YAML validity, and
port consistency across all three files.

**Known limitations (stated plainly).** The image was **never actually built or
run** (no Docker daemon here) — a human should run `docker build`/`docker run`
before relying on it. No multi-stage slimming, no pinned base-image digest, no TLS/
auth (deploy behind a reverse proxy). **Helm/Kubernetes is deferred** (Tier 3 step
4): not built, as it can't be tested without a cluster.

---

## Step 10 — BigQuery connector, schema/query text only (`hipaasynth/connectors/bigquery.py`)

**What.** A **schema/query-level** BigQuery connector that generates, from the
shared OMOP CDM 5.4 column sets, the text you would run against BigQuery:
  - `table_ddl(table, dataset, project=, if_not_exists=)` and
    `schema_ddl(dataset, project=)` — GoogleSQL `CREATE TABLE` DDL with BigQuery
    scalar types (`INT64`/`FLOAT64`/`DATE`/`DATETIME`/`STRING`).
  - `table_schema_json(table)` — the `[{"name","type","mode"}]` load-schema JSON
    that `bq load --schema` and the BigQuery client accept.
  - `load_data_sql(table, uris, …, overwrite=)` — GoogleSQL `LOAD DATA
    INTO|OVERWRITE … FROM FILES(...)`; `bq_load_command(...)` — the equivalent
    `bq load` CLI string; `load_all_sql(dataset, gcs_prefix)` — a statement per
    OMOP table expecting `{prefix}/{table}.csv` (matching `export_omop`'s layout).
  - Identifier validation rejects anything that could smuggle a backtick / SQL into
    the generated text.

**Why.** Roadmap Tier 3 step 2 — a second connector at the level that is honestly
testable without a live account. **BigQuery chosen** (over Snowflake/Redshift/
Databricks) because its GoogleSQL DDL, `LOAD DATA … FROM FILES` DML, `bq load` CLI,
and JSON load-schema are the most stable, well-documented text to generate and
assert offline.

**Dependency decision.** **None** — the connector is pure standard library. It
deliberately does **not** import `google-cloud-bigquery` and opens no connection,
so it needs no optional extra and no CI zero-dep exemption. (A client-based loader
is **deferred**, not built, because it cannot be tested against a real account
here.)

**How verified — generated SQL/DDL TEXT ONLY; a live BigQuery warehouse was NEVER
contacted (no account in this sandbox).** `tests/test_connector_bigquery.py`
(13 tests) asserts on the generated strings: qualified names with/without project,
every BigQuery type mapping (INT64/FLOAT64/DATE/DATETIME/STRING), `IF NOT EXISTS`,
full-schema DDL covering all six tables, load-schema JSON column/type/mode, `LOAD
DATA INTO` vs `OVERWRITE`, multi-URI, the `bq load` CLI string, per-table load map,
unknown-table `ValueError`, identifier-injection rejection, and that the BigQuery
column set matches the DuckDB one (same `omop_schema` source, no drift).

**Known limitations (stated plainly).** Text generation only — **not executed**
against BigQuery; no dataset creation, no partitioning/clustering, and no
client-based load path (deferred until testable). Types are the OMOP-faithful
scalar choices; a team may prefer `NUMERIC` over `FLOAT64` for exact decimals.

---

## Step 9 — DuckDB connector (`hipaasynth/connectors/duckdb.py`)

**What.** A connector that loads a cohort into a **real local DuckDB database
file**. `load(cohort, database, *, mode="omop"|"flat", if_exists="replace"|"append")
-> {table: row_count}`:
  - `mode="omop"` (default) creates the six OMOP CDM 5.4 tables with **typed**
    columns and inserts `build_cdm_tables()` rows (empty CSV values → real SQL
    NULLs).
  - `mode="flat"` loads the single flat patient table (base fields typed;
    observation columns typed `DOUBLE` when all-numeric, else `VARCHAR`).
  - Accepts a `Cohort` or a plain list of patients; `create_table_ddl(table)`
    exposes the DDL text.
  - Column→SQL types come from a new shared `hipaasynth/connectors/omop_schema.py`,
    which derives its **column sets from `omop._TABLE_COLUMNS`** (the same lists the
    CSV exporter writes) — so a connector's schema can never drift from the export.

**Why.** Roadmap Tier 3 step 1: there was no way to get a cohort into a warehouse.
DuckDB is embedded (no server/account/network), so it is the connector that can be
**fully integration-tested here**, and the reference for connector shape.

**Dependency decision (flagged, pyarrow-style).** `duckdb` is a new **optional
extra** (`pip install 'hipaasynth[duckdb]'`), imported **lazily** inside
`load()` — importing `hipaasynth`, `hipaasynth.connectors`, or `omop_schema` pulls
in nothing new. The engine core stays stdlib-only; the CI zero-dep check's per-file
allowlist was extended to exempt exactly `connectors/duckdb.py` (nothing else).

**How verified — ran against a REAL local DuckDB file (not a mock).**
`tests/test_connector_duckdb.py` (11 tests, skipped when `duckdb` is absent):
row-count summary equals `build_cdm_tables`; data is queryable after reopening the
`.duckdb` file (incl. a real CDM join); columns are correctly typed
(`person_id`→BIGINT, `condition_start_date`→DATE, `value_as_number`→DOUBLE,
`person_source_value`→VARCHAR); empty OMOP values load as `NULL`;
`condition_status_concept_id` survives as a non-zero int; flat mode; replace-vs-
append; plain-list input; and a missing-`duckdb` path that raises a clear
`RuntimeError` with the install hint. Verified locally against `duckdb 1.5.5`.

**Known limitations.** Loads via parameterized `executemany` (fine for the cohort
sizes this generates; not a bulk-COPY path for millions of rows). `mode="flat"`
infers observation-column types from the data, not a fixed schema.

---

# Tier 2 — new capabilities (CLI, REST API, SDK)

New network- and developer-facing surfaces built on the Tier 1 exporters. Each
change is additive and gated on a fails-before / passes-after test.

**Deferred (roadmap step 4): webhooks / push streaming.** Not built — flagged for a
later tier rather than speculatively added. The one place streaming was genuinely
warranted, large-cohort responses, is covered by the REST API's chunked NDJSON
endpoint (Step 7); a webhook/callback or server-push (SSE/WebSocket) delivery model
has no consumer yet, so it is deliberately left out.

## Step 7 hardening — REST API bounds the POST body (forged `Content-Length` DoS)

**What.** `hipaasynth/api.py`: `do_POST` no longer trusts the client's
`Content-Length`. New `MAX_BODY_BYTES = 1_000_000` constant (a `/generate` JSON
body — `{count, seed, module, profile, format}` — is well under a kilobyte, so
1 MB is already absurdly generous). `do_POST` now rejects any `Content-Length`
over `MAX_BODY_BYTES` with a **`413`** *before* reading or allocating toward it,
and reads the body via a new `_read_body()` that pulls fixed 64 KiB chunks and
stops at `min(Content-Length, MAX_BODY_BYTES)` — so neither a forged huge header
nor a small header followed by a longer stream can push the server past the cap.

**Why (real crash, not hypothetical).** The old line
`raw = self.rfile.read(length)` handed the trusted header straight to a sized read.
A `POST /generate` with `Content-Length: 999999999999` made CPython pre-allocate a
~1 TB bytes buffer and killed the handler thread with **`MemoryError`** — while
every *value* param (`count`/`seed`/`format`/`module`/`profile`) was already
carefully validated. This closes that gap: the request framing is now bounded like
everything else.

**How verified — reproduced exactly as the bug was found (raw socket, not urllib,
which always sends a truthful length).** `tests/test_api.py` adds three raw-socket
tests: a forged `Content-Length: 999999999999` now returns a clean **413** (and a
follow-up `GET /health` confirms the server is still alive — no downed thread); a
`Content-Length` of `MAX_BODY_BYTES + 1` returns 413; and a legitimately-sized body
still returns 200. Fails-before proof: with the fix surgically reverted, the forged
test fails with `MemoryError` at `self.rfile.read(length)` in the server thread and
no response — the exact reported crash. Full suite green (**325 passed, 1 skipped**).

**Known limitations.** `MAX_BODY_BYTES` is a fixed constant (not operator-tunable
like `--max-count`); the 1 MB ceiling is far above any legitimate `/generate` body,
so this wasn't parameterized.

## Step 8 — Python SDK facade (`hipaasynth/sdk.py`) + notebook example

**What.** A new high-level facade for notebooks/scripts (no naming collision —
there was no `sdk.py`/`Cohort`/`generate` before):
  - `hipaasynth.generate(count=, seed=, module=, profile=, ...) -> Cohort` — one
    call, no argparse, no `GenerationConfig` assembly. `module` is one of
    `sepsis|stroke|dka|fabry`; `profile` accepts a bundled name **or** a path
    (the SDK is trusted local code).
  - `Cohort` — iterable/indexable over its patients, with return-**or**-write
    exporters: `to_json`, `to_csv`, `to_fhir_bundle`, `to_ndjson`, `to_omop`,
    `to_parquet` (each returns the data when called with no path, or writes a file
    and returns the path), plus `fhir_resources()`, `fhir_bundle()`, `summary()`,
    and `validate()` (the structural FHIR validator).
  - Re-exported at the package root: `import hipaasynth; hipaasynth.generate(...)`.
  - `examples/sdk_quickstart.py` — a **jupytext "percent" notebook** (`# %%`
    cells, Jupyter/VS Code/Colab-compatible) that also runs as a plain script,
    walking generate → export (all formats) → validate.

**Shared module map (no drift).** The canonical decision-module map lives in the
SDK (`MODULES`); `hipaasynth/api.py` now imports it (`MODULE_TO_CONDITION` is
`sdk.MODULES`), so the CLI-less SDK and the REST API can't disagree about which
modules exist. Asserted by `test_api_uses_sdk_module_map`.

**Why.** Roadmap Tier 2 step 3: before this, "use HipAAsynth from a notebook" meant
hand-assembling a `GenerationConfig` and calling `generate_patients` +
individual file-writing exporters. The SDK makes the common path a few lines.

**Dependency decision.** None added — the SDK is stdlib-only and reuses the
existing exporters; `to_parquet` inherits the lazy `[parquet]` optional extra.

**How verified.** `tests/test_sdk.py` (15 tests): size/determinism, top-level
re-export, module selection (valid + `ValueError` on unknown), every exporter in
both return-data and write-file modes, `validate()` clean on a generated cohort,
bundled-profile selection + unknown-profile `ValueError`, and a **runpy smoke test
that executes `examples/sdk_quickstart.py` end-to-end**. The example was also run by
hand: 25-patient stroke cohort → JSON/CSV/FHIR-bundle/NDJSON/OMOP/Parquet written →
`FHIR structural validation: PASS (311 resources)`. Full suite green (322 passed,
1 skipped). **Not done here:** running inside a real Jupyter/Colab kernel (no
notebook runtime in this sandbox) — the script is import/exec-verified and
jupytext-formatted; a human should open it in a live kernel to confirm the
cell-by-cell UX.

**Known limitations.** `profile` path support is intentionally SDK-only (the REST
API restricts to bundled names); the example writes to a system temp dir.

---

## Step 7 — REST API for on-demand generation (`hipaasynth/api.py`)

**What.** A new `hipaasynth/api.py` — the project's first network-facing surface —
serving on-demand cohort generation:
  - `GET /health` → liveness + engine version.
  - `GET /formats` → supported formats, decision modules, bundled profile names,
    and the server's `max_count`.
  - `GET|POST /generate` → generate a cohort and return it in an existing export
    format. Params (query string or JSON body): `count`, `seed`, `module`
    (`sepsis|stroke|dka|fabry`), `profile` (a **bundled** profile name), `format`
    (`json|csv|fhir-bundle|ndjson|omop|parquet`).
  - `make_server(host, port, max_count)` (bind `port=0` for an ephemeral test
    port) and `main()` (`python -m hipaasynth.api --host --port --max-count`).

**Framework decision — flagged (the Tier-1-style dependency callout).** Built on
the **standard library** `http.server` (`ThreadingHTTPServer`) — **zero new
dependencies** — to preserve the "stdlib-only core" value. A microframework
(Flask/FastAPI) would give nicer routing/validation but adds a hard runtime
dependency for a small, well-scoped API. If the surface grows, add a microframework
as an **optional extra** (the pyarrow pattern), not a core dep. *(The `[parquet]`
extra is the only optional dependency reachable here, via `format=parquet`, and it
is delegated to `export_parquet` — `api.py` itself imports nothing outside the
stdlib, verified by the CI zero-dep check, which in fact caught an accidental
`import pyarrow` in an early draft of this file.)*

**Input validation / error responses (this is a network surface, so it doesn't get
skipped).** `parse_generate_request()` rejects: non-integer or out-of-range
`count` (1..`max_count`, default cap 10 000) and `seed` (0..2³²−1); unknown
`format`, `module`, or `profile`. Unknown routes → `404`; wrong method → `405` with
an `Allow` header; malformed JSON body → `400`. Every error is a JSON
`{"error", "status"}` body. `profile` is restricted to **bundled** names — a
network client cannot supply an arbitrary filesystem path.

**Streaming.** `format=ndjson` is streamed with HTTP **chunked** transfer
(`_stream_ndjson`), so a large cohort's FHIR resources are written to the socket as
they are produced rather than buffered whole. Per the roadmap's step-4 guidance,
this is the one place streaming was genuinely warranted; no speculative
webhook/streaming machinery was added.

**Why.** Roadmap Tier 2 step 2: there was no REST API / on-demand generation — the
only way to produce a cohort was the CLI or importing the package.

**How verified — no live external deployment in this sandbox, stated plainly.**
`tests/test_api.py` (26 tests) starts the **real** server in a background thread on
an ephemeral port and drives it over an **actual localhost socket** with `urllib`:
health/discovery, every format (JSON/CSV/FHIR-bundle/OMOP/NDJSON/Parquet),
determinism (same seed → byte-identical), module + bundled-profile selection, POST
JSON body, and the full validation matrix (400/404/405). Additionally smoke-tested
by hand: `python -m hipaasynth.api --port 8765` then `curl /health`,
`curl '/generate?count=2&format=fhir-bundle'`, and 400s for `count=abc` /
`count=99999`. **Not done here:** deploying behind a real WSGI/ASGI server, TLS,
auth, and load — see "needs a live environment" in the Tier 2 report.

**Known limitations.** Single-process dev server (`ThreadingHTTPServer`); no
auth/rate-limiting/TLS (deploy behind a reverse proxy for anything real); `omop` is
returned as a JSON object of tables (not a multi-file CSV bundle); `count` is capped
to protect the process.

---

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
