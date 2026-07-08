# Compliance Posture & Deployment Responsibility Matrix

**Scope of this document.** HipAAsynth is a deterministic **synthetic** health-data
generation and fairness-testing engine. It does **not** collect, receive, store,
process, or transmit Protected Health Information (PHI) or electronic PHI (ePHI).
Every record it emits is synthetic, carries an explicit synthetic-data
disclaimer, and is derived from region-level public reference distributions — not
from any individual's health record.

Because of that, HipAAsynth is **not itself a HIPAA-regulated information system.**
It is a software library that a Covered Entity (CE) or Business Associate (BA) may
run *inside* their own environment. HIPAA obligations attach to that environment,
not to this library.

This document therefore takes the form of a **shared-responsibility matrix**: for
each relevant HIPAA Security Rule control area it states what HipAAsynth does (or
deliberately does not do), and what the deploying organization remains responsible
for. This is an honest engineering statement of posture. **It is not legal advice,
a certification, an attestation, or a determination of HIPAA compliance.** Only the
deploying organization, with its own counsel and security team, can make that
determination.

Status legend:

| Mark | Meaning |
|------|---------|
| ✅ Implemented | Present in the engine today |
| 🟡 Partial | Partially present; gaps noted |
| ⛔ Not Started | Applicable to a deployment, not yet provided |
| N/A | Not applicable to a synthetic-data engine that never touches PHI |

---

## 1. Why most PHI controls are N/A here

The HIPAA Security Rule (45 CFR §164.302–318) governs the confidentiality,
integrity, and availability of **ePHI**. HipAAsynth handles none. The strongest
compliance statement it can make is therefore *negative and verifiable*:

- **No PHI ingress.** The engine's inputs are seeds, integer counts, and JSON
  population *profiles* (aggregate distributions). There is no code path that reads
  a patient record. See `DATA_FLOW.md`.
- **No PHI at rest.** All output is synthetic and disclaimer-stamped
  (`core/config.py: DEFAULT_SYNTHETIC_DISCLAIMER`, stamped into every record).
- **No PHI egress / no network.** The engine is pure Python standard library with
  **zero external dependencies** and makes no network calls. CI fails the build on
  any non-stdlib import (`.github/workflows/test.yml`).
- **Deterministic & reproducible.** Same `(module, seed, n)` → byte-identical
  cohort, anchored by a SHA-256 hash (`core/anchor.py`, `core/hashing.py`), so any
  third party can regenerate and re-verify outputs.

A reviewer's correct question is not "does it encrypt PHI at rest?" (it has none)
but "can I prove no real patient data can enter or leave it?" — which the design
above is built to answer.

---

## 2. HIPAA Security Rule — control-by-control matrix

### Administrative Safeguards (§164.308)

| Control | Engine status | Deploying-organization responsibility |
|---|---|---|
| Security Management / Risk Analysis (§164.308(a)(1)) | N/A (no ePHI) | Include the HipAAsynth deployment host in the org's risk analysis; scope this doc as an input. |
| Assigned Security Responsibility (§164.308(a)(2)) | N/A | Name a security official accountable for the host running the engine. |
| Workforce Security / Access Authorization (§164.308(a)(3–4)) | N/A at the data layer | Control who can run the engine and read its output directory via host IAM. |
| Security Awareness & Training (§164.308(a)(5)) | N/A | Train operators that engine output is synthetic and must not be mixed with real cohorts. |
| Security Incident Procedures (§164.308(a)(6)) | 🟡 Partial — see `SECURITY.md` (vuln reporting, response timelines) | Fold engine-host incidents into the org's IR plan. |
| Contingency Plan / Backup (§164.308(a)(7)) | ✅ by design — outputs are reproducible from a seed; nothing unique is lost | Back up seeds/profiles/config, not bulk output. |
| Business Associate Agreements (§164.308(b)) | N/A — no PHI is exchanged with this project | If you embed HipAAsynth in a product that *does* touch PHI, your BAAs cover that system, not this library. |

### Physical Safeguards (§164.310)

| Control | Engine status | Deploying-organization responsibility |
|---|---|---|
| Facility Access, Workstation Use/Security, Device & Media Controls (§164.310(a–d)) | N/A (no ePHI on any media) | Standard host/facility controls for the machine running the engine. |

### Technical Safeguards (§164.312)

| Control | Engine status | Deploying-organization responsibility |
|---|---|---|
| Access Control / Unique User ID (§164.312(a)(1)) | N/A at data layer | Enforce OS/container-level access to the process and output files. |
| Audit Controls (§164.312(b)) | 🟡 Partial — structured JSONL run logs, per-run manifest, environment + config snapshots, replay command (`core/logger.py`, `core/run_context.py`, `core/manifest.py`); exercised end-to-end by `tests/test_pipeline_logging_integration.py`, which also asserts no record payload leaks into logs | Ship these logs to your SIEM and set retention per your policy. |
| Integrity (§164.312(c)(1)) | ✅ SHA-256 file hashing + anchor manifest for outputs and checkpoints (`core/hashing.py`, `core/checkpoints.py`) | Verify manifest hashes when consuming outputs downstream. |
| Person/Entity Authentication (§164.312(d)) | N/A | Host responsibility. |
| Transmission Security / Encryption in transit (§164.312(e)(1)) | N/A — engine performs no transmission | If you move outputs across a network, use TLS at that layer. |
| Encryption at rest (§164.312(a)(2)(iv)) | N/A for PHI (none); output is synthetic | Use encrypted volumes for the output dir if your policy requires it for all data classes. |

### Breach Notification (§164.400–414)

| Control | Engine status | Notes |
|---|---|---|
| Breach Notification Rule | N/A | A disclosure of synthetic, non-identifiable data is not a breach of PHI. Confirm with counsel for your data classification. |

---

## 3. Beyond HIPAA — controls a hospital review will still expect

These are not PHI controls, but a hospital security review of *any* third-party
code will ask for them:

| Area | Status | Notes |
|---|---|---|
| Supply-chain / dependency risk | ✅ Strong — zero runtime dependencies; CI-enforced | Optional extras (`fhir.resources`, `seismometer`, `pandas`, `pyarrow`) are opt-in; pin them in your own lockfile. |
| Secret management | ✅ No secrets in repo; scanned | Pre-commit `gitleaks` + `detect-private-key` block new secrets. |
| SBOM | ✅ Generated in CI | CycloneDX SBOM produced and uploaded by the `Security` workflow (`.github/workflows/security.yml`). |
| Vulnerability disclosure | ✅ `SECURITY.md` with private reporting + timelines | — |
| License clarity | ✅ AGPL-3.0 (+ commercial) — see `LICENSE.md`, `COMMERCIAL-LICENSE.md` | AGPL network-use obligations apply if you expose a modified engine as a service. |
| Reproducibility / evidentiary integrity | ✅ deterministic + hash-anchored | Tag/signature signing recommended (Gap #6). |

---

## 4. Top 10 gaps that would block a hospital security review

Ranked by how likely each is to stop a review, with a concrete fix.

1. **Branch protection not enforced on `main`.** Requires GitHub admin. Enable:
   require 1 PR review, require the `Tests` status check, dismiss stale reviews,
   no direct pushes. *Fix: repo Settings → Branches (admin action).*
2. ✅ **Addressed — `.github/CODEOWNERS` added**, so the "require review from
   Code Owners" branch rule can route reviews to an accountable owner (enable the
   rule alongside gap #1).
3. 🟡 **Improved — branch coverage ~25% → ~46%.** The DMD/Fabry/SMA/diabetes
   generators now have smoke tests, and the generators + pipeline have
   identifier-safety and statistical-property tests; the CI floor ratchets and is
   never lowered. Remaining headroom is in the single-condition modules
   (sepsis-oncology, stroke); keep raising the floor as tests are added.
4. ✅ **Addressed — automated dependency scan in CI.** The `Security` workflow
   runs `pip-audit` (advisory) on every PR, push, and weekly, and Dependabot
   (`.github/dependabot.yml`) tracks pip + Actions updates.
5. ✅ **Addressed — identifier-safety regression tests.** `tests/test_identifier_safety.py`
   and `tests/test_module_smoke.py` fail loudly if any generated value matches a
   real-identifier shape (SSN/NPI/phone/email) across the generators and pipeline.
6. **Release tags/commits are unsigned.** The project markets outputs as
   evidentiary; unsigned tags weaken that. *Fix: sign tags (e.g. `git tag -s`) and
   enable signed-commit requirement.*
7. ✅ **Addressed — SBOM published.** The `Security` workflow generates a
   CycloneDX SBOM and uploads it as a build artifact.
8. **Audit-log retention/rotation is undefined.** The engine writes JSONL logs but
   defines no retention. *Fix: document retention expectations here + in
   `DEPLOYMENT.md`; leave rotation to the host.*
9. ✅ **Addressed — data retention/disposal documented** in §5 (outputs are
   regenerable-from-seed and treated as non-archival; inputs and run logs have
   stated retention guidance).
10. 🟡 **Partial — incident-response summary now in `SECURITY.md`** (report →
    acknowledge → assess → remediate → verify → disclose). A fuller step-by-step
    responder runbook under `docs/` is worth adding once a real deployment exists.

---

## 5. Data retention & disposal

- **Inputs** (seeds, counts, JSON profiles): retain in version control; they are
  the reproducibility record.
- **Outputs** (synthetic cohorts): treat as *regenerable, not archival*. Because
  `(module, seed, n)` reproduces any cohort exactly, the recommended posture is to
  **not** retain bulk generated data — regenerate on demand. This is the same
  principle applied to the Seismometer demo, which ships no committed cohort.
- **Run logs/manifests**: retain per the deploying org's audit-log policy; ship to
  a SIEM if used for audit evidence.

---

## 6. How to use this document in a review

1. Start from §1 — establish that no PHI enters the engine (the reproducible,
   zero-dependency, no-network design is the evidence).
2. Walk §2 to show which Security Rule controls are N/A *and why*, and which are
   the host's responsibility.
3. Track §4 gaps to closure; each maps to a GitHub issue or a config change in
   this repository.

*This document describes engineering posture and is not a legal compliance
determination. Consult your privacy/security officer and counsel for your specific
deployment.*
