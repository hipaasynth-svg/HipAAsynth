# HipAAsynth

![Tests](https://github.com/hipaasynth-svg/HipAAsynth/actions/workflows/test.yml/badge.svg)
[![License: AGPL v3](https://img.shields.io/badge/License-AGPL%20v3-blue.svg)](https://www.gnu.org/licenses/agpl-3.0)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)

**Open-source fairness-testing for clinical AI — reproducible, inspectable, vendor-neutral.**

HipAAsynth is an open-source fairness testing engine for clinical AI. It generates synthetic patients from populations that are under-represented in standard validation datasets — rural, tribal, uninsured, aging, non-English-speaking — and stress-tests clinical AI models across seven distinct patient presentations of the same case.

The output is a **FairnessPassport**: a structured, reproducible record of how a model performed across every presentation. Not a benchmark score — a testing record that organizations may use as part of their own validation evidence.

---

## The problem

Clinical AI models are being deployed in hospitals and clinics. Most have never been tested on the patients who need them most.

Standard validation cohorts draw from EHR data at academic medical centers — urban, insured, English-speaking patients. Rural patients, tribal health communities, the uninsured, patients with limited English — the people most likely to be harmed when a model fails at the edges — are absent from nearly every validation dataset that exists.

When a model fails in production, the question every vendor, hospital, and regulator faces is:

> *What did you do to verify this model before you put it in front of a patient?*

Today, most honest answers are: very little, with no verifiable record.

HipAAsynth produces the record.

---

## How it works

### Synthetic populations calibrated to real-world distributions

The engine generates deterministic synthetic patients from anchor seeds calibrated to CDC BRFSS, ACS, and IHS benchmarks. Zero PHI. No external data ingested. The same seed always produces the same population — making every audit reproducible by any third party.

Population profiles include:
- Rural North Dakota (IHS/tribal, frontier, aging uninsured)
- Urban Midwest (diverse, mixed payer)
- National BRFSS benchmarks

### Seven polymorphic presentations

The same synthetic patient is rendered in seven distinct clinical documentation styles. A fair model produces consistent decisions across all seven. A biased model performs well on the physician note and fails on the patient describing their own symptoms.

| Form | Description |
|------|-------------|
| `FHIR_STRUCTURED` | FHIR R5 Bundle — structured clinical data |
| `PHYSICIAN_SOAP` | Formal clinical prose, A/P format, medical abbreviations |
| `MIDLEVEL_ABBREVIATED` | Telegraphic, time-pressed documentation |
| `PATIENT_HIGH_LITERACY` | Lay medical terms, first-person, pain scale |
| `PATIENT_LOW_LITERACY` | Metaphorical, somatic, no medical terminology |
| `LEP_TRANSLATED` | Plain, simplified English; short sentences |
| `CHW_SDOH_RICH` | Community health worker intake with full SDoH context |

### The FairnessPassport

Every audit produces a `FairnessPassport` per patient — a structured artifact containing:

- Model decision on all seven forms
- Four polymorphic fairness metrics with pass/fail determinations:
  - **DCS** — Decision Consistency Score
  - **ISG** — Information-Source Gradient
  - **LFDI** — Linguistic-Form Disadvantage Index
  - **SAF** — SDoH Amplification Factor
- FDA Total Product Life Cycle (TPLC) compliance-context mapping (heuristic, non-binding)
- EU AI Act compliance-context mapping (heuristic, non-binding)
- Remediation recommendations

The FairnessPassport is the answer to *"what did you do to verify this model?"*

---

## Who audits the auditor?

Anyone.

The engine and all core modules are published under AGPL v3. The methodology is open, inspectable, and reproducible. Any researcher or regulator can independently reproduce the methodology without contacting us.

This is a structural answer to the most important question in third-party auditing. The defense is not "trust HipAAsynth." The defense is "here is the methodology — verify it yourself."

---

## What HipAAsynth is / is not

**What HipAAsynth is**
- An open-source engine that generates deterministic synthetic patients and tests a model's decision consistency across seven documentation styles of the same case.
- A producer of structured, reproducible `FairnessPassport` records.
- A methodology any third party can inspect and re-run.

**What HipAAsynth is not**
- Not a regulatory body, accreditation, or certification.
- Not an FDA / EU / CMS submission, and not a guarantee of clearance or payment.
- Not a legal opinion or evidence of compliance.
- Not a source of real patient data, and not a substitute for clinical validation on real-world populations.
- Not a guarantee that a model is fair — it surfaces specific, defined fairness signals only.

---

## Quick start — no Python required

You do not have to write Python to use the engine. Install it, start the server,
open a browser:

```bash
git clone https://github.com/hipaasynth-svg/HipAAsynth.git
cd HipAAsynth
pip install -e .
python -m hipaasynth.api
```

Then open **<http://127.0.0.1:8000>**. Pick a module, a population profile and a
cohort size; preview the cohort, download it in any supported format, and see the
population distribution charted.

> HipAAsynth is not on PyPI — install from a clone (above) or straight from git
> with `pip install git+https://github.com/hipaasynth-svg/HipAAsynth.git`.

The UI also renders a **fairness heatmap**. Read the label on it: that panel is a
*demonstration* audit run against a built-in **mock** model, so you can see what
the output looks like. It is **not** an audit of any real model — a stateless HTTP
request has no model under test. To audit your own model, use the Python API
below.

---

## Every way in

The same engine sits behind all five surfaces. Pick whichever fits.

| Surface | For | One-line example |
|---|---|---|
| **Web UI** | Non-programmers | `python -m hipaasynth.api` → <http://127.0.0.1:8000> |
| **CLI** | Scripts, pipelines, air-gapped runs | `hipaasynth --scenario tribal_stroke --count 200 --format csv --out ./out` |
| **Python SDK** | Notebooks, analysis | `hipaasynth.generate(count=200, seed=42, module="stroke")` |
| **REST API** | Any language, any tool | `curl "http://127.0.0.1:8000/generate?count=100&format=csv"` |
| **Docker** | Deployment | `docker compose up --build` → API on port 8000 |

### Python SDK

```python
import hipaasynth

cohort = hipaasynth.generate(count=200, seed=42, module="stroke")
cohort.to_fhir_bundle("cohort.json")   # or .to_csv(), .to_omop(), .to_parquet(), ...

cohort.validate()    # structural FHIR check
cohort.fidelity()    # are the cohort's statistics plausible?
cohort.utility()     # is the signal actually learnable?
```

### REST API

Served by `python -m hipaasynth.api` (stdlib `http.server`, no framework):

| Endpoint | Returns |
|---|---|
| `GET /` | the web UI |
| `GET /health` | `{"status": "ok", "engine_version": ...}` |
| `GET /formats` | supported formats, modules, profile + scenario names |
| `GET /scenarios` | the named scenario blueprints |
| `GET\|POST /generate` | a cohort (`json`, `csv`, `fhir-bundle`, `ndjson`, `omop`, `parquet`) |
| `GET /viz/demographics` | SVG of the cohort's age/sex/ethnicity distribution |
| `GET /viz/fairness` | SVG heatmap from a **demo audit of a mock model** (see above) |

`ndjson` is streamed with chunked transfer, so large cohorts never buffer in memory.

### DuckDB

```bash
pip install -e ".[duckdb]"
```

```python
from hipaasynth.connectors import duckdb
duckdb.load(cohort, "cohort.duckdb", mode="omop")   # or mode="flat"
```

`hipaasynth.connectors.bigquery` generates BigQuery DDL, load SQL and `bq` CLI
text. It is a **SQL generator only** — it opens no connection and needs no
credentials.

---

## Scenario blueprints

A scenario is a named `module` + `profile` shortcut, usable from the CLI
(`--scenario`), the API (`?scenario=`), and the web UI's dropdown. Eight ship:

| Scenario | Module | Profile | For |
|---|---|---|---|
| `us_baseline_sepsis` | sepsis | us_default | US national reference baseline (ACS/NHANES) |
| `fabry_baseline` | fabry | us_default | Rare-condition screening against a general US population |
| `tribal_sepsis` | sepsis | nd_tribal_region_a | Northern Plains tribal / IHS service area, air-gapped context |
| `tribal_stroke` | stroke | nd_tribal_region_a | Same population, acute-stroke decision support (ICU age bands) |
| `rural_nd_dka` | dka | minot_nd | Rural upper-Midwest, high diabetes burden |
| `urban_nd_sepsis` | sepsis | fargo_nd | Urban safety-net contrast to the rural ND scenarios |
| `karachi_dka` | dka | karachi_pakistan | LMIC urban; stresses limited-English/low-literacy forms |
| `lagos_sepsis` | sepsis | lagos_nigeria | Sub-Saharan LMIC; community-health-worker forms |

`GET /scenarios` returns the same list with full descriptions and default sizes.

---

## Optional extras

The engine core is **pure standard library**. Every extra below is optional and
lazily imported, so nothing is pulled in until you use that feature.

| Extra | Unlocks |
|---|---|
| `.[parquet]` | Parquet export (`cohort.to_parquet()`, `--format parquet`) |
| `.[duckdb]` | The DuckDB warehouse connector |
| `.[fhir]` | `fhir.resources`-backed FHIR support |
| `.[seismometer]` | Epic Seismometer fairness reports (`examples/seismometer/`) |
| `.[dev]` | pytest, black, ruff, mypy, pre-commit |
| `.[test-browser]` | Playwright, for the headless-browser UI tests |
| `.[examples]` | Third-party deps of the `examples/` scripts |
| `.[test-full]` | Everything above needed to run the suite with zero skips |

---

## Quick start — Python

```bash
pip install -e .
python -c "from hipaasynth.dif import run_audit; print('OK')"
python -m pytest -q          # verify the install end-to-end
```

Run a full fairness audit:

```python
from hipaasynth.core.config import DEFAULT_SYNTHETIC_DISCLAIMER, GenerationConfig
from hipaasynth.dif import DIFConfig, run_audit
from hipaasynth.dif.model_interface import MockBiasedModel
from hipaasynth.pipelines.population_pipeline import generate_patients

cfg = GenerationConfig(
    patient_count=5,
    seed=42,
    required_condition="stroke",
    synthetic_disclaimer=DEFAULT_SYNTHETIC_DISCLAIMER,
)

passports = run_audit(
    MockBiasedModel(),
    generate_patients,
    cfg,
    DIFConfig(device_name="Demo Model", device_version="1.0.0"),
)

for passport in passports:
    print(passport.patient_id, "PASS" if passport.passed() else "FAIL")

# Full markdown FairnessPassport for the first patient:
print(passports[0].to_markdown())
```

`MockBiasedModel` is a deliberately unfair reference model, so it FAILs every
patient — that is the expected output. Swap in `MockFairModel` (from the same
module) to see the passing case, or your own model implementing the
`predict(patient, form)` interface.

---

## Examples

See the [`examples/`](examples/) directory — each runs standalone with no model or
network (`python examples/<name>.py`):

- `examples/polymorphic_demo.py` — render one patient across all seven forms
- `examples/rare_disease_demo.py` — DIF audit contrasting a fair vs. biased mock (fair passes 3/3, biased fails)
- `examples/fairness_passport_demo.py` — generate a full markdown FairnessPassport (biased mock, fails by design)
- `examples/psf_demo.py` — Population Sparsity Fairness audit + determinism check
- `examples/cc_demo.py` — Care Continuity audit + determinism check

---

## Tests

```bash
python -m pytest          # full suite
python -m pytest --cov    # with coverage (floor enforced in pyproject.toml)
```

Tests gated on an optional dependency **skip silently** under a plain `.[dev]`
install, so `python -m pytest` can report a clean run while whole files never
execute. To run everything (DuckDB, Parquet, the example scripts and the
headless-browser UI drive):

```bash
pip install -e ".[test-full]"
python -m playwright install chromium
python -m pytest
```

CI runs both: a stdlib-only job proving the core needs no dependencies, and a
`capabilities` job that installs everything and fails if any test skips.

---

## Architecture, security & compliance docs

For contributors and reviewers:

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — component map and design invariants
- [`docs/DATA_FLOW.md`](docs/DATA_FLOW.md) — what enters/leaves the engine and trust boundaries (no PHI)
- [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) — install, run, and host-hardening checklist
- [`SECURITY.md`](SECURITY.md) — vulnerability reporting, incident response, data-handling
- [`COMPLIANCE.md`](COMPLIANCE.md) — HIPAA shared-responsibility matrix and gap list
- [`CONTRIBUTING.md`](CONTRIBUTING.md) — setup, test commands, PR requirements, code style

Contributors: `pip install -e ".[dev]" && pre-commit install` sets up formatting,
linting, and secret scanning (`.pre-commit-config.yaml`).

---

## Optional FHIR support

```bash
pip install -e '.[fhir]'
```

See [Optional extras](#optional-extras) for the full list.

---

## What's open, what's closed

| Component | Status | License |
|-----------|--------|---------|
| Population engine | Open | AGPL v3 |
| PSF module (Population Sparsity Fairness) | Open | AGPL v3 |
| CC module (Care Continuity) | Open | AGPL v3 |
| DIF module (Differential Impact Framework) | Open | AGPL v3 |
| Polymorphic layer (7 forms + metrics) | Open | AGPL v3 |
| CAP pipeline (Bitcoin-anchored certification) | Closed | Proprietary |
| FDA-Ready tier logic | Closed | Proprietary |
| LLM evaluators, clinical harnesses | Closed | BSL 1.1 |

For proprietary use without AGPL v3 obligations, see [COMMERCIAL-LICENSE.md](COMMERCIAL-LICENSE.md).

The CAP pipeline — cryptographic hash chain, OpenTimestamps Bitcoin anchor, and live verification server — is a separate proprietary service. It provides timestamped provenance for a FairnessPassport; it is not a regulatory certification, and the open engine does not itself certify, attest, or make any regulatory determination. Organizations seeking timestamped provenance for procurement or their own submission packages can use the CAP pipeline via [HipAAsynth.com](https://hipaasynth.com).

AGPL v3 means: any organization embedding this engine in a commercial product must either open-source their full stack or obtain a commercial license.

---

## Research extensions

Proprietary research extensions — including LLM evaluators, clinical validation pipelines, and model harnesses — are maintained in a **separate private repository** under BSL 1.1. These are not open source and are not included in this repository, and this repository has no dependency on them: everything here installs, tests, and runs on its own.

---

## Regulatory context

HipAAsynth is a testing tool — not a regulatory body, certification, or legal opinion. It makes no compliance determination; responsibility for any regulatory submission remains with the submitting organization.

Within that scope, the engine produces structured fairness-testing output that organizations *may use as one input within* processes such as:

- **FDA SaMD** — subgroup performance-consistency testing that may support a 510(k) evidence package
- **EU AI Act** — robustness and subgroup-consistency documentation that may support conformity-assessment activities for high-risk clinical AI
- **CMS NTAP** — supplementary validation output applicants may include in New Technology Add-on Payment materials
- **Post-market surveillance** — repeatable re-audit capability that may support model-drift monitoring

---


## License

AGPL-3.0-or-later. See [LICENSE.md](LICENSE.md).

Commercial licensing for organizations embedding this engine in proprietary products: [cody@hipaasynth.com](mailto:cody@hipaasynth.com)

---

## Contact

**HipAAsynth LLC** — Minot, North Dakota  
[hipaasynth.com](https://hipaasynth.com) · [cody@hipaasynth.com](mailto:cody@hipaasynth.com)  
HuggingFace: [HipAAsynth](https://huggingface.co/HipAAsynth)
