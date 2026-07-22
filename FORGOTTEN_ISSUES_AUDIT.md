# Forgotten-Issues Audit

**Generated:** 2026-07-21
**Method:** Walked the full commit history from the first commit (`b5d671d`,
PR #2, 2026-06-26) through the latest (`2a1f9ae`, PR #67, 2026-07-21) —
50 commits — cross-referencing every commit that promised a fix, flagged a
gap, or deferred work, against the code and docs as they stand today. The
question asked of each: *was this actually followed through, or did it fall
through the cracks?*

This is not a re-run of `ORPHAN_AUDIT.md` or `COMPLIANCE.md` §4 — both of
those already track their own open items faithfully and are not "forgotten."
The findings below are things that were raised *somewhere* in the project's
own history (a commit message, a report, a recovery plan) and then never
checked off, revisited, or even referenced again.

---

## 1. The SNF module's own recovery plan was deleted along with the module — and never done

**Where:** `d9290e2` (PR #3, 2026-06-26), first commit after the initial
import.

The commit removed the entire `snf/` (Skilled Nursing Facility) module —
generator source, cohort CSV/JSON, and a validation report showing **19/19
CMS quality measures PASS**. The module's own `README.md`, deleted in the
same commit, stated:

> **Status: SOURCE LOST — OUTPUT PROVEN**
> ...
> ## Recovery plan
> Reconstruct generator from output spec and validation details.
> **This is scheduled work — do not fabricate the source.**

That recovery plan — reconstructing a generator from a proven, cited output
spec — was the plan of record at the moment the module was deleted. In the
48 commits since, `snf` is never mentioned again anywhere in the repository
(commit messages, code, docs, tests — confirmed via full-history grep). No
later PR revisits it, no issue tracks it, and `COMPLIANCE.md`/`CHANGELOG.md`
never note the module as removed-and-pending. A generator with independently
verified 19/19 CMS benchmark passes was quietly dropped and its own
documented recovery task forgotten.

**Recommendation:** Either explicitly retire the SNF module (state that
decision in `CHANGELOG.md`/`COMPLIANCE.md` so it stops looking abandoned-in-
progress), or open a tracked issue for the reconstruction using the deleted
`twin_validation_details.json` citations as the calibration source — those
citations no longer exist anywhere in the repo, only in this deleted commit's
diff.

---

## 2. `ORPHAN_AUDIT.md`'s own remediation plan was mostly never carried out

**Where:** `1fcd55b` (PR #6, 2026-06-26 → updated 2026-06-28) added
`ORPHAN_AUDIT.md`, a full audit of four unwired modules (`cardiology`,
`fabry`, `sma`, `dmd`) with a specific, numbered work plan per module. It is
still sitting at the repo root, unmodified since 2026-06-28, and nothing in
the 40+ commits since references it.

Checking each of its recommendations against the code as of `2a1f9ae`:

| Recommendation (from `ORPHAN_AUDIT.md`) | Done? |
|---|---|
| Add inline `Source:` citations to every numeric constant in fabry/sma/dmd/cardiology | **No** — `grep -rn "Source:"` across all four modules returns zero matches, unchanged since the audit was written. |
| Add a `get_validation_stats()` method to each module | **No** — the method does not exist anywhere in the codebase. |
| Fix Fabry `vital_status` (audit reported 0% alive in a 500-patient cohort) | **Unclear / not verifiably done** — the survival logic (`fabry.py`, `_model_survival`) has not been touched since the initial commit (only two commits ever touch this file, and neither changes this logic). Regenerating the same `seed=42, n=500` cohort today yields ~22% censored/alive, not 0%. Either the original 0% reading was a one-off measurement error, or something upstream of this function changed the RNG draw sequence without editing this file (organ/biomarker generation order feeds into `_model_survival`'s inputs). Nobody re-ran or closed out the audit's finding either way — there's no follow-up commit, no regression test asserting a non-degenerate vital-status distribution, and no note reconciling the discrepancy. |
| Recalibrate DMD cardiomyopathy rate (audit measured 16% vs ~59% benchmark; recommended age-stratified fix) | **No** — `cardiac_onset_mean = 18.0` / `cardiac_onset_std = 3.0` in `dmd.py` are unchanged since the initial commit. |
| Verify/adjust SMA Type II rate (audit measured 34.6% vs 25–30% benchmark) | **No** — `SMA_TYPE_RATES = [0.55, 0.30, 0.14, 0.01]` unchanged since the initial commit. (Note: 0.30 is the *configured* rate and is within the audit's own PASS range — the 34.6% reading looks like sampling noise on n=500, so this one is likely a non-issue, but it was never re-verified as such.) |
| Build a `cardiology` population generator (flagged effort: HIGH, "treat as a separate design task") | **No** — `hipaasynth/modules/cardiology/` still contains only `risk_scores.py` and `medications.py`; `__init__.py` is still empty; there is still no `generate_cardiology_cohort()` or any patient-generating entry point. |
| Add CI tests validating each module's calibration | **Partially** — `cc7fba9` (#32) added smoke tests for fabry/sma/dmd (existence, determinism, synthetic-stamp checks), but no calibration/distribution assertions per the audit's recommended benchmark tables. `cardiology` has no tests of its own at all (only a negative test in `test_seismometer_adapter.py` confirming it correctly raises `SchemaMismatchError` for being unregistered). |
| Wire fabry/sma/dmd/cardiology into `population_pipeline.py` / `run_all_modules.py` once the above is done | **Still not done**, consistent with the audit's gate ("none of these modules should be wired into `population_pipeline.py` until the citation pass is complete") — but three of the four (`fabry`, `sma`, `dmd`, not `cardiology`) *were* wired into the separate Seismometer adapter's `PROFILES` registry in `19bea31` (#53), without the citation pass or calibration fixes the audit made a precondition of any wiring. |

**Net effect:** the one thing that *did* happen (Seismometer wiring for three
of the four modules, `19bea31`/#53) happened in spite of the audit's own
stated precondition, while the actual precondition work (citations, bug
verification, recalibration, validation methods) was never picked up. The
document reads today exactly as it did on 2026-06-28 — a plan nobody came
back to.

---

## 3. `COMPLIANCE.md` gap #6 ("sign tags") has a documented fix recipe that was never implemented, across multiple later touches to the same workflow

**Where:** `COMPLIANCE.md` §4 gap #6: *"Release tags/commits are unsigned...
Fix: sign tags (e.g. `git tag -s`) and enable signed-commit requirement."*
This gap has never been marked ✅, including in the dedicated gap-refresh
commit `bfc057f` (#47, "Refresh COMPLIANCE.md gap status").

The release workflow (`d23731d` #14, hardened in `c725f14` #15, dependency-
bumped in `05ac2e6` #35) creates the release tag via GitHub's release-creation
API. Inspecting the current tags (`V1.0.0`, `v1.0.1`, `v1.0.2`): they are
lightweight refs pointing at already GPG-signed *commits* (GitHub's
commit-signing), not GPG-signed *tag objects* — `git verify-tag v1.0.2` fails
with "cannot verify a non-tag object of type commit." The workflow was
touched three separate times after this gap was first written down, and none
of those touches added a signing step. This is a gap that keeps getting
walked past rather than closed or explicitly re-scoped.

**Recommendation:** either add `git tag -s` (or equivalent GitHub API signed-
tag creation) to `release.yml`, or update gap #6's text to reflect that commit
signing (already present) is the deliberate substitute and tag-object signing
is out of scope — right now it reads as an open promise, not a decision.

---

## 4. Minor / lower-confidence observations

- **`COMPLIANCE.md` §4 gap #3** ("branch coverage ~25% → ~46%") was last
  measured as of whichever PR wrote that line; no later commit re-states a
  current coverage number, so the figure may now be stale in either
  direction. Worth re-running and refreshing rather than trusting a
  months-old percentage.
- **Branch protection on `main` (gap #1) and signed-commit *requirement***
  (as opposed to signed commits happening to occur) are GitHub admin settings
  this audit cannot verify from the repository contents alone — flagging
  rather than claiming either way.

---

## Summary

| # | Forgotten issue | Age (still open as of) | Severity |
|---|---|---|---|
| 1 | SNF module recovery plan deleted with the module, never reconstructed | 48 commits / ~1 month | Medium — a previously-validated module (19/19 CMS measures) is simply gone with no tracked path back |
| 2 | `ORPHAN_AUDIT.md` remediation plan (citations, validation methods, bug fixes, cardiology generator) never executed | 40+ commits / ~3.5 weeks | Medium-High — citation debt on 3 shipped-and-wired modules, one module (`cardiology`) never started at all |
| 3 | Tag-signing gap (#6) never implemented despite 3 later touches to the release workflow | Since `bfc057f` (#47) | Low-Medium — evidentiary-integrity claim in `COMPLIANCE.md` is weaker than the doc implies |
| 4 | Stale coverage % / unverifiable admin-only gaps | — | Low |
