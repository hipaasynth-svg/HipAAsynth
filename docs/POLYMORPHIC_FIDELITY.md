# Polymorphic Fidelity — Technical Note (v1.3.0)

## Summary

This change strengthens the **highest-leverage** part of HipAAsynth — the seven
polymorphic documentation forms and the FairnessPassport built on them — so the
harness delivers on its two central promises: that decision divergence across
forms is **attributable to documentation form**, and that every FairnessPassport
is **independently verifiable** by a third party. It implements the six findings
(F1–F6) from the Priority-1 audit.

Backward-compatible: `run_audit`, the seven `Form` values, the four metrics
(DCS/ISG/LFDI/SAF), and the passport markdown sections are unchanged in shape;
new fields and behavior are additive. Determinism, stdlib-only core, and zero
PHI are preserved.

## F1 — Fact invariance + measured missingness

**Problem.** Patient/LEP/CHW forms dropped labs and the acuity line while
clinician forms kept them, so the disadvantaged forms carried *less clinical
information*. A model's divergence on them could not be cleanly attributed to
form vs. absent facts — undercutting the harness's core claim.

**Fix.** `hipaasynth/polymorphic/facts.py` defines a canonical `ClinicalFactSet`
(conditions, acute status, labs) extracted once and shared by every form.
Information availability is now an explicit, controlled axis:

- `information_mode="same_facts"` (default) — **every form encodes every fact**.
  Verified: `omitted_fact_categories == []` for all seven forms across
  stroke/sepsis/non-acute cohorts.
- `information_mode="realistic_missingness"` — patient/LEP/CHW forms may omit the
  numeric labs (mirroring under-resourced documentation), and the omission is
  **recorded and measured** per form (`omitted_fact_categories`), never silent.
  Conditions are always-present and never dropped in either mode.

Coverage is measured lexically for narrative forms and **structurally** (coded
Condition/Observation resource counts) for the FHIR form, which encodes facts as
OMOP codes rather than English.

## F2 — Versioned, hashed, sealed, verifiable

**Problem.** No form versioning or content hashing existed; the passport recorded
no seed/config/anchor and used a wall-clock `test_date`, so it was neither
byte-identical run-to-run nor third-party re-renderable.

**Fix.**

- Every rendered form carries `form_engine_version` (`FORM_ENGINE_VERSION =
  "poly_v2_sealed"`) and `content_sha256` of its text.
- `FairnessPassport` now seals: `seed`, `run_date`, generation `anchor_hash`,
  `engine_version`, `form_engine_version`, `information_mode`, and the per-form
  `form_hashes`. `test_date` defaults to the deterministic `run_date`, not
  wall-clock.
- `content_sha256()` seals the whole passport over its deterministic content;
  passports are **byte-identical across runs** of the same seed/config.
- `verify(patient)` re-renders the forms and confirms every sealed hash
  reproduces — and **fails on tampering** or a form-engine version mismatch.

## F3 — Patient-specific SDoH powers SAF

**Problem.** The CHW form hardcoded identical SDoH lines for every patient, so the
SDoH Amplification Factor had nothing to amplify.

**Fix.** `hipaasynth/polymorphic/sdoh.py` derives a **deterministic, per-patient**
SDoH profile (housing, transport, food security, insurance, `sdoh_burden_score`)
as a pure SHA-256 function of the anchor-rooted patient id — no new RNG, no change
to the generation stream. A population profile may raise adverse rates per locale
(`sdoh_adverse_rates`), matching the engine's "marginal knob" philosophy. The CHW
form renders the varying profile. A new `MockSDoHBiasedModel` under-triages
high-burden patients on the CHW form, making SAF **demonstrable**: SAF mean ~0.13
vs. 0.00 for the fair model, with `worst_form = CHW_SDOH_RICH`.

## F4 — Cohort aggregation

Per-patient ISG/LFDI/SAF are noisy (accuracy gaps over 1–3 forms). The new
`CohortFairnessSummary` / `summarize_cohort()` roll up a cohort: mean
DCS/ISG/LFDI/SAF with 95% normal-approx confidence half-widths, DCS/overall pass
rates, and the **worst-performing form** (highest ground-truth disagreement rate).
For `MockBiasedModel` the worst form is one of the disadvantaged patient/LEP forms;
for `MockSDoHBiasedModel` it is the CHW form.

## F5 — Not evaluated ≠ pass

**Problem.** Truth-free runs set ISG/LFDI/SAF to 0.0 and marked them `pass`, so a
real-model run without ground truth silently "passed" three of four fairness gates.

**Fix.** `PolymorphicMetrics.truth_evaluated` records whether ground truth was
supplied. The passport renders **NOT EVALUATED** for the truth-dependent metrics
(and annotates the overall result) rather than a misleading PASS. DCS, which needs
no ground truth, is always evaluated.

## F6 — LEP register shift

The LEP form now reads as short, simple, interpreter-relayed clauses (avg < 12
words/sentence) while retaining its verbatim interpreter marker, giving the form a
distinct linguistic register rather than clinician prose with a flag line.

## Validation

`tests/test_polymorphic_fidelity.py` (22 tests) covers all six findings: fact
invariance across stroke/sepsis/non-acute, measured missingness, form
versioning/hashing, byte-identical sealed passports, `verify()` + tamper
detection, deterministic and locale-tunable SDoH, the demonstrable SAF signal,
cohort aggregation, and the NOT-EVALUATED path. Full suite: all passing;
`ruff` clean and `black`-formatted on new files.

## Determinism & invariants

No new RNG is introduced. SDoH derivation and form hashing are pure functions of
anchor-rooted identifiers. The core path remains standard-library only. The
passport is now *more* verifiable than before: a third party with the public code
and the sealed `{seed, config, anchor_hash, form_engine_version}` can regenerate
the cohort, re-render the forms, and confirm every hash.
