# HipAAsynth Deployment Guide

How to install, run, and operate HipAAsynth in a controlled environment. See
[`ARCHITECTURE.md`](ARCHITECTURE.md) and [`DATA_FLOW.md`](DATA_FLOW.md) for what
the engine does internally, and [`../COMPLIANCE.md`](../COMPLIANCE.md) for the
shared-responsibility posture.

## Requirements

- **Python ≥ 3.11** (tested on 3.11 and 3.12 in CI).
- **No runtime dependencies.** The core engine is pure standard library.
- Optional extras, installed only if you use them:
  - `fhir` → `fhir.resources` (FHIR R5 export)
  - `seismometer` → Seismometer demo integration (`pandas`, `pyarrow`, `pyyaml`,
    `jupyter`, `nbconvert`)

## Install

```bash
# Core engine (nothing else pulled in)
pip install -e .

# With dev tooling (tests, coverage, linters, pre-commit)
pip install -e ".[dev]"

# With optional integrations
pip install -e ".[fhir]"
pip install -e ".[seismometer]"
```

Verify:

```bash
python -m pytest -q          # full suite
python -m pytest --cov       # with coverage (floor enforced in pyproject.toml)
```

## Run

Generate an auditable sample cohort:

```bash
python -m hipaasynth.run.generate_sample --count 1000 --seed 42
```

Generate a condition-specific cohort (example: OUD) programmatically:

```python
from hipaasynth.modules.oud.oud_generator import generate_oud_cohort, save_cohort

patients, anchor = generate_oud_cohort(seed=42, n=1000, label="us_oud_calibration")
save_cohort(patients, anchor, output_dir="./out", prefix="oud")
# -> out/oud_n1000.json, out/oud_n1000.csv, out/oud_manifest.json (with SHA-256)
```

Audit a model (you provide `predict(patient, form)`):

```python
from hipaasynth.psf import PSFAudit, PSFConfig
result = PSFAudit().run(your_model, PSFConfig(n_per_level=200, seed=42))
```

## Operational model

- **Stateless & offline.** Each run is self-contained, writes to a
  `runs/<run_id>/` directory (or the path you specify), and makes no network calls.
- **Reproducible.** Re-running with the same `(module, seed, n)` reproduces outputs
  byte-for-byte. Keep seeds/profiles/config; regenerate data rather than archiving
  it.
- **Run artifacts.** Each run emits structured JSONL logs, a config snapshot, an
  environment snapshot, a replay command, and a manifest of SHA-256 hashes under
  `runs/<run_id>/`.

## Hardening checklist for a regulated host

The engine handles no PHI, but the host running it should still be controlled:

- [ ] Run as a **non-root** user in a container or dedicated service account.
- [ ] Restrict filesystem access to the input (profiles) and output directories.
- [ ] Ship `runs/*/logs/engine.jsonl` to your **SIEM**; set retention per policy.
- [ ] If your data-classification policy requires it, place the output directory on
      an **encrypted volume** (defense-in-depth; output is synthetic).
- [ ] Pin optional extras in your own lockfile; run `pip-audit` at your build
      boundary and generate an SBOM.
- [ ] Keep the deployment host in scope for your organization's risk analysis.

## Upgrades

HipAAsynth follows semantic versioning. Patch releases (e.g. 1.0.x) do not change
engine behavior, determinism, or calibration. Pin a version and review the
`CHANGELOG.md` before upgrading; re-run your audit suite after any upgrade.

## Support

Security issues: see [`../SECURITY.md`](../SECURITY.md) (private reporting).
General: [hipaasynth.com](https://hipaasynth.com) · cody@hipaasynth.com
