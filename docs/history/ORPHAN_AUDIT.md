# Orphaned Module Audit

**Generated:** 2026-06-27  
**Branch:** `verify-diabetes-calibration-4mzgm7`  
**Auditor:** HipAAsynth automated audit

---

## Update: 7AAST Axes 6 & 7 Implemented (2026-06-28)

The two adversarial axes described in the original task specification have been
fully implemented on branch `psf-cc-adversarial-axes`:

### PSF — Population Sparsity Fairness (Axis 6)

- **Module:** `hipaasynth/psf/` (`generator.py`, `framework.py`, `report.py`, `__init__.py`)
- **Sparsity levels:** S1–S7 (S1 = age/sex/race/geography/chief-complaint only; S7 = full EHR)
- **Key metric:** Sparsity Degradation Index (SDI) = mean_score(S1) / mean_score(S7); FAIL if SDI < 0.80
- **Calibration:** IHS Data Governance Framework (2022); Sequist NEJM 2021; Adler-Milstein Health Aff 2017
- **Tests:** 15 tests in `tests/test_psf.py` — all passing
- **Demo:** `examples/psf_demo.py`
- **MockClinicalModel result:** SDI = 0.1003 (FAIL — correct; model penalises sparse records)
- **ScoredMockModel demographic gap at S1:** AIAN 0.0316 vs White 0.1224 (gap 0.0908)

### CC — Care Continuity (Axis 7)

- **Module:** `hipaasynth/cc/` (`generator.py`, `framework.py`, `report.py`, `__init__.py`)
- **Continuity profiles:** PROFILE_A (full) → PROFILE_B → PROFILE_C → PROFILE_D (ED-only / no PCP)
- **Key metric:** Continuity Degradation Index (CDI) = mean_score(PROFILE_D) / mean_score(PROFILE_A); FAIL if CDI < 0.80
- **Transition consistency:** Matched pairs (same demographics, different continuity) measure continuity bias (delta = score_A − score_D)
- **Calibration:** Roberts ET Health Aff 2018 (Medicaid churn ~25%); AHRQ Statistical Brief #179 (~8% ED-only); HRSA 2023 (rural gap)
- **Tests:** 18 tests in `tests/test_cc.py` — all passing
- **Demo:** `examples/cc_demo.py`
- **MockClinicalModel result:** CDI = 0.2704 (FAIL — correct); 25/25 transition pairs positive (mean delta 0.7311)

### Full test suite after implementation

54 tests, 0 failures. Zero external dependencies (pure stdlib).

---

---

## Scope

Four modules import cleanly but are not wired into `population_pipeline.py` or
`run_all_modules.py`. This report documents their current state, assesses
citation coverage, identifies calibration gaps, and recommends work needed to
bring each to the same standard as the verified modules (sepsis, stroke, COPD,
CHF, OUD, diabetes).

**Modules audited:** `cardiology`, `fabry`, `sma`, `dmd`

**NOTE:** No modules were wired into the pipeline during this audit. Wiring is
an architecture decision for the maintainer after reviewing this report.

---

## 1. `cardiology`

### What it is

A **utility library**, not a standalone cohort generator. Contains two classes:

| File | Class | Purpose |
|---|---|---|
| `risk_scores.py` | `CardioRiskScores` | Computes ASCVD 10-yr risk, CHA₂DS₂-VASc, HAS-BLED, HEART score |
| `medications.py` | `CardioMedications` | Assigns antihypertensives, statins, anticoagulants, HF/DM meds |

There is **no top-level `generate_cardiology_cohort()` function** and no
patient demographic/phenotype generator. The `__init__.py` is empty — nothing
is exported. `CardioRiskScores.calculate()` expects a pre-built `data` dict
with columnar arrays (`data["age"]`, `data["sex"]`, etc.); it cannot be invoked
standalone.

### Current calibration state

- `risk_scores.py` docstring cites ACC/AHA 2013 PCE distributions and targets:
  low risk <5% (~25–30%), borderline 5–7.5% (~15–20%), intermediate 7.5–20%
  (~30–35%), high >20% (~15–20%). These match published PCE validation data.
- **No inline `Source:` citations** on individual parameter values.
- `medications.py` has no citations at all.
- Generates 0 patients independently; cannot be validated against a cohort
  benchmark.

### Work needed to reach sepsis/stroke standard

1. **Create a population generator** (`cardiology_generator.py`) that generates
   patient demographics (age, sex, race, comorbidities, lipids, BP) and then
   calls `CardioRiskScores` and `CardioMedications` as sub-components.
2. **Calibrate to real benchmarks:**
   - ASCVD category distribution: ACC/AHA 2013 PCE (Goff DC et al. *Circulation*
     2014;129:S49-S73)
   - Statin prescribing rate: ~55% of eligible adults
     (Salami JA et al. *JAMA Cardiol* 2017;2(1):56-65)
   - Anticoagulation in AF: ~70% CHA₂DS₂-VASc ≥2
     (Freedman B et al. *JAMA Cardiol* 2017;2(4):442-451)
3. **Add inline citations** on every numeric constant.
4. **Add `get_validation_stats()` method** and a CI-callable test.

### Effort estimate: HIGH (needs population generator written from scratch)

---

## 2. `fabry`

### What it is

A **complete cohort generator** (`FabryCohortGenerator` class, 440-line
`fabry.py`). Generates detailed synthetic Fabry disease patients including
phenotype assignment, mutation types, biomarkers (α-galactosidase A, lyso-Gb3),
organ progression (LVH, ESRD, stroke/TIA, neuropathic pain), and ERT status.
Generates 29 fields per patient.

```python
from hipaasynth.modules.fabry.fabry import FabryCohortGenerator
g = FabryCohortGenerator(seed=42)
patients = g.generate(n=200)  # works
```

### Current calibration state

| Metric | Generated (n=500, seed=42) | Known benchmark | Status |
|---|---|---|---|
| ERT rate | 55.4% | ~50–60% of registered Fabry patients (Fabry Registry) | Plausible |
| Male classic phenotype | ~60% | 60% males classic (Germain DP. *Orphanet J Rare Dis* 2010) | Plausible |
| Female classic phenotype | ~10% | ~10% females classic (Germain 2010) | Plausible |
| Lyso-Gb3 classic median | ~150 ng/mL | ~100–200 ng/mL (Nowak A et al. *J Inherit Metab Dis* 2017) | Plausible |
| **Vital status alive** | **0%** | **N/A (bug — all patients show `vital_status='dead'`)** | **BUG** |

**Critical bug:** `vital_status` is `'dead'` for 100% of patients in a 500-patient
cohort. The survival model appears to set death age ≤ current age for all
patients regardless of phenotype or treatment.

**Citation gaps:** The module header names "Fabry Registry, FOS (Fabry Outcome
Survey), FDA label" but provides **no inline `Source:` comments** on individual
numeric constants (e.g., `tia_stroke_risk_by_50: float = 0.25`, `esrd_onset_classic_mean: float = 42.0`).
These values need paper-level citations.

### Work needed to reach sepsis/stroke standard

1. **Fix vital status bug:** Debug the survival/censoring logic; alive patients
   should predominate in a treated cohort (ERT extends life by ~10 years per
   Schiffmann R et al. *Mol Genet Metab* 2016).
2. **Add inline citations** on every parameter in `FabryParameters`, citing:
   - Germain DP. *Orphanet J Rare Dis* 2010;5:30 (phenotype rates)
   - Kampmann C et al. *Eur Heart J* 2008;29:916-923 (LVH)
   - Wanner C et al. *N Engl J Med* 2003;349:481-492 (renal progression, ESRD age)
   - Sims K et al. *Mol Genet Metab* 2009;97:3-8 (stroke/TIA)
   - Nowak A et al. *J Inherit Metab Dis* 2017;40:733-743 (lyso-Gb3 levels)
3. **Add a validation block** and `get_validation_stats()` method with a
   benchmark table (alive rate, ESRD rate, stroke rate, ERT rate).
4. **Wire into pipeline** only after bug fix and citation pass.

### Effort estimate: MEDIUM (generator is complete; bug fix + citations needed)

---

## 3. `sma`

### What it is

A **complete cohort generator** (`SMACohortGenerator` class, 464-line `sma.py`).
Generates synthetic Spinal Muscular Atrophy patients with SMA type assignment
(I/II/III/IV), SMN2 copy number, motor milestone trajectory, disease-modifying
therapy (nusinersen, risdiplam, onasemnogene), ventilation status, and survival.
Generates 27 fields per patient.

```python
from hipaasynth.modules.sma.sma import SMACohortGenerator
g = SMACohortGenerator(seed=42)
patients = g.generate(n=200)  # works
```

### Current calibration state

| Metric | Generated (n=500, seed=42) | Known benchmark | Status |
|---|---|---|---|
| SMA Type I | 50.6% | ~50–60% of incident cases (Mercuri E et al. *Nat Rev Neurol* 2022) | PASS |
| SMA Type II | 34.6% | ~25–30% (Mercuri 2022) | Slightly high |
| SMA Type III | 13.8% | ~12–17% (Mercuri 2022) | PASS |
| SMA Type IV | 1.0% | ~1–2% (Mercuri 2022) | PASS |
| DMT use | 63.0% | ~50–70% of eligible patients post-2016 (SMArtCARE registry) | PASS |

**Citation gaps:** Module header cites "SPINRAZA trials, SMArtCARE registry, FDA
label" but no individual constants have inline `Source:` comments. Constants like
`NUSINERSEN_SURVIVAL_BENEFIT = 0.50` and all `SURVIVAL_PARAMS` hazard rates have
no cited source.

### Work needed to reach sepsis/stroke standard

1. **Add inline citations** on all numeric constants, particularly:
   - Type distribution: Mercuri E et al. *Nat Rev Neurol* 2022;18(1):46-58
   - SMN2 copy numbers by type: Feldkötter M et al. *Am J Hum Genet* 2002;70:358-368
   - Survival without treatment: Finkel RS et al. *N Engl J Med* 2017;377:1723-1732 (ENDEAR)
   - DMT efficacy: Darras BT et al. *N Engl J Med* 2019;380:1329-1340 (CHERISH)
2. **Verify SMA Type II rate** (34.6% vs benchmark ~25–30%); may need minor
   adjustment to `SMA_TYPE_RATES`.
3. **Add `get_validation_stats()`** method with a calibration table.
4. **Add a CI test** verifying determinism and type distribution.

### Effort estimate: LOW-MEDIUM (generator works; citation pass + 1 distribution fix)

---

## 4. `dmd`

### What it is

A **minimal cohort generator** (`DMDCohortGenerator` class, 248-line `dmd.py`).
Generates 13 fields per patient: age, diagnosis age, disease duration, mutation
type, steroid status, ambulation loss age, ambulatory status, cardiomyopathy,
ventilation, predicted survival age, and CK level.

```python
from hipaasynth.modules.dmd.dmd import DMDCohortGenerator
g = DMDCohortGenerator(seed=42)
patients = g.generate(n=200)  # works
```

### Current calibration state

| Metric | Generated (n=500, seed=42) | Known benchmark | Status |
|---|---|---|---|
| All patients male | 100% | ~99.7% (X-linked; female carriers rarely symptomatic) | PASS |
| Steroid use | 66.8% | ~60–70% in US/Europe (Birnkrant DJ et al. *Lancet Neurol* 2018) | PASS |
| Non-ambulatory | 47.6% | Depends on mean age; ~50% by age 12 (Birnkrant 2018) | Plausible |
| Cardiomyopathy | 16.0% | ~59% by age 18, ~90% by age 18 with CMR (Bushby K et al. *Lancet Neurol* 2010) | **LOW** |
| Mean age | 12.0 yrs | Pediatric cohort skew (~10–18 typical treatment cohort) | Plausible |

**Citation gaps:** The module has **no `Source:` citations anywhere** — not in
the docstring and not inline. `DMDParameters` values (e.g.,
`median_ambulation_loss_age: float = 10.5`, `steroid_ambulation_gain: float = 3.0`)
have no referenced sources.

**Thin field set:** 13 fields is sparse compared to other modules (CHF: ~45+,
OUD: ~40+). Missing: respiratory function (FVC %), exon skip eligibility,
eteplirsen/golodirsen/viltolarsen use, cardiac ejection fraction, scoliosis,
NSAA score, and SDOH fields that matter for rare disease access.

**Cardiomyopathy rate is low:** 16% vs real-world ~59% by age 18 in
non-treated cohorts (Bushby K et al. *Lancet Neurol* 2010;9:77-93). The
current age distribution (mean 12 yrs) partially explains this, but the
underlying rate model likely underestimates CMR-detected subclinical dysfunction.

### Work needed to reach sepsis/stroke standard

1. **Fix cardiomyopathy rate** — recalibrate to age-stratified prevalence:
   - <10 yrs: ~10–15%
   - 10–18 yrs: ~30–60%
   - >18 yrs: ~90%
   - Source: Bushby K et al. *Lancet Neurol* 2010;9:77-93
2. **Add inline citations** on all `DMDParameters` values, particularly:
   - Median diagnosis age: Birnkrant DJ et al. *Lancet Neurol* 2018;17(3):251-267
   - Ambulation loss: McDonald CM et al. *Muscle Nerve* 2013;48:343-356
   - Steroid benefit: Manzur AY et al. *Cochrane Database* 2008;4:CD003725
   - Predicted survival (without exon-skip/gene therapy): Rall S & Grimm T. *Eur J Hum Genet* 2012
3. **Expand the field set** to include FVC %, exon-skip eligibility, DMT use
   (eteplirsen, delandistrogene, gene therapy), cardiac EF, and NSAA functional score.
4. **Add `get_validation_stats()`** and a CI test.

### Effort estimate: MEDIUM-HIGH (needs cardiomyopathy fix, field expansion, full citation pass)

---

## Summary Table

| Module | Generator exists | Generates cleanly | Citation coverage | Calibration accuracy | Effort to standard |
|---|---|---|---|---|---|
| `cardiology` | ❌ (utility only) | N/A | Partial (no inline) | Cannot assess | HIGH |
| `fabry` | ✅ | ✅ | None inline | Plausible but vital-status bug | MEDIUM |
| `sma` | ✅ | ✅ | None inline | Good (minor Type II drift) | LOW–MEDIUM |
| `dmd` | ✅ | ✅ | None inline | Cardiomyopathy low; thin fields | MEDIUM–HIGH |

## Recommended prioritization

1. **SMA** — generator works, distributions are close, needs citation pass + minor rate fix.
2. **Fabry** — generator is feature-rich, needs vital-status bug fix + citation pass.
3. **DMD** — needs cardiomyopathy fix, field expansion, and full citation pass.
4. **Cardiology** — needs a population generator written from scratch before it
   can be wired in; treat as a separate design task.

None of these modules should be wired into `population_pipeline.py` until the
citation pass is complete and a CI validation test exists.
