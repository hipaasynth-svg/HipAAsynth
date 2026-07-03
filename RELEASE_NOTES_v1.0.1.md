# HipAAsynth v1.0.1 — packaging & documentation patch

**Release title (paste into GitHub):**
`v1.0.1 — clone trap removed; README demos accurate and runnable`

---

v1.0.1 is a **patch** release. It changes no engine or source behavior — the
1.0.0 API, determinism, and calibration are unaffected — and fixes the things
that made the public repository hard to actually use on a clean machine.

## Fixed

- **Recursive clones no longer fail.** The public repo carried a `.gitmodules`
  reference to the **private** `hipaasynth-research` repository, so
  `git clone --recurse-submodules` (and `git submodule update --init`) failed for
  anyone without access to that private repo. The submodule gitlink and
  `.gitmodules` have been removed. The public engine has **no dependency** on the
  research repository and installs, tests, and runs entirely on its own.

## Changed

- **README examples are accurate and runnable.** All five demos in `examples/`
  are now documented (previously three), each labeled with its intended result so
  the biased-mock (`0/3`) and fair-mock (`3/3`) outputs read as *by design*, not
  as failures. The Quick Start prints a single `FairnessPassport` and explains
  that `MockBiasedModel` fails on purpose (and how to swap in `MockFairModel` or
  your own model implementing `predict(patient, form)`). The install block now
  includes `python -m pytest -q` as an at-a-glance verification step.

## Verification

- `pip install -e .` → clean
- `python -m pytest -q` → **54 passed** (Python 3.11 and 3.12 in CI)
- All five `examples/*.py` run standalone with no model or network
- Plain and `--recurse-submodules` clones both succeed

## Upgrade

No action required for existing users — this is a documentation/packaging patch.
Fresh installs simply get a repository that clones and runs cleanly.

---

**Full changelog:** see [CHANGELOG.md](CHANGELOG.md).
**Contact:** HipAAsynth LLC — Minot, North Dakota · [hipaasynth.com](https://hipaasynth.com) · cody@hipaasynth.com
