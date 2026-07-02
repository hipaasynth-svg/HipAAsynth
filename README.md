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

## Quick start

```bash
pip install -e .
python -c "from hipaasynth.dif import run_audit; print('OK')"
python -m pytest -q          # 54 passing — verify the install end-to-end
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
python -m pytest
```

---

## Optional FHIR support

```bash
pip install -e '.[fhir]'
```

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
