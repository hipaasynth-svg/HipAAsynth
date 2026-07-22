# HipAAsynth Calibration Sources & Update Guide

## Core Principle
HipAAsynth uses **statistical anchors** (prevalence rates, distributions,
severity mixes) drawn from public, published sources. **No raw patient data is
ever ingested.** Every cohort is regenerated from SHA-256 anchor-rooted
deterministic randomness against these anchors. This guarantees:

- **Zero PHI** — nothing traceable to a real person is ever read or written.
- **Determinism** — the same seed + anchors reproduce the same cohort, bit for bit.
- **Auditability** — cohorts and calibration results are hashed and chain-stamped
  (see [CAP stamping](#cap-stamping-cryptographic-audit-pipeline)).

> Synthetic data only. Not for clinical use. See `COMPLIANCE.md` and the dataset
> disclaimer embedded in every generated record.

---

## Calibration Results at a Glance

Latest run — `n=1000` per module, **92 / 92 checks PASS across 9 modules**.

| Module | Checks | Result |
|---|---|---|
| COPD | 15 | ✅ 15 PASS / 0 FAIL |
| CHF  | 16 | ✅ 16 PASS / 0 FAIL |
| OUD  | 16 | ✅ 16 PASS / 0 FAIL |
| Stroke | 6 | ✅ 6 PASS / 0 FAIL |
| Diabetes | 7 | ✅ 7 PASS / 0 FAIL |
| SMA | 6 | ✅ 6 PASS / 0 FAIL |
| DMD | 7 | ✅ 7 PASS / 0 FAIL |
| Fabry | 6 | ✅ 6 PASS / 0 FAIL |
| Oncology | 13 | ✅ 13 PASS / 0 FAIL |
| **Total** | **92** | **✅ 92 PASS / 0 FAIL** |

COPD/CHF/OUD are validated by `calibration_validator.py`; the stroke, diabetes,
SMA, DMD, Fabry, and oncology modules are validated by
`calibration_validator_ext.py` (added so every module with a self-contained
cohort generator is calibrated, not just the original three). The oncology
sub-package (breast/lung/colon, six chained sub-modules) is driven by
`oncology/cohort.py::OncologyCohortGenerator`. Sepsis is a physiological
observation generator with no population-prevalence rows to calibrate — its
sources are catalogued in the citation registry.

**→ Full citation registry (every anchor, its source URL, and where to look so
you can verify one by one):**
[`docs/calibration/CITATIONS.md`](calibration/CITATIONS.md)

**Side-by-side chart (calibration targets vs. generated data):**
[`docs/calibration/calibration_vs_data.html`](calibration/calibration_vs_data.html)
— a self-contained, theme-aware page rendering every metric's published target
beside the synthetic cohort value, with the acceptance tolerance band shown.
Rebuild it any time with `python3 docs/calibration/build_chart.py`.

The full per-metric tables are in
[Appendix A: Calibration vs. Data](#appendix-a-calibration-vs-data-side-by-side).

---

## Primary Sources (Update Annually or When New Data Releases)

### 1. CDC BRFSS (Behavioral Risk Factor Surveillance System)
- **Why**: State-level chronic conditions, risk behaviors, healthcare access.
- **Latest ND data**: https://www.cdc.gov/brfss/annual_data/annual_2023.html
  (replace `2023` with the newest release year when updating).
- **Key tables for ND rural**: Diabetes, hypertension, stroke/TIA, smoking,
  obesity, preventive services.
- **How to update**: Download state-specific CSV → extract prevalence by
  rural/urban or race/ethnicity strata.

### 2. American Community Survey (ACS)
- **Why**: Demographics, insurance, poverty, disability at county/PUMA level.
- **Tool**: https://data.census.gov (filter North Dakota, rural counties around
  the Minot / Trinity Health catchment).
- **Key fields**: Age distribution, AI/AN population %, uninsured rate,
  disability, household income.
- **Vintage in use**: ACS 2020–2024 5-Year Estimates (see the ND tribal region
  profiles under `hipaasynth/profiles/`).

### 3. Indian Health Service (IHS) – Great Plains Area
- **Why**: Tribal-specific health disparities for ND AI/AN populations.
- **Sources**: IHS Great Plains Area reports; Special Diabetes Program for
  Indians (SDPI) data summaries; *Trends in Indian Health 2014–2015*.
- **Key**: Higher diabetes, cardiovascular, and access-related rates in tribal
  populations. IHS nurse vacancy rate 23–40% is used as context for access
  limitations (not a population-representative filter).

### 4. Supplemental (Stroke / Late Presenters)
- CDC PLACES (county-level chronic disease).
- Published rural-health literature on symptom-to-door delays.

---

## Module-Specific Anchor Sources (as calibrated in code)

Each generator header (`hipaasynth/modules/<module>/*.py`) records the anchors it
targets. These are the sources behind the numbers in the calibration chart.

### COPD — `modules/copd/copd_generator.py`
- NHANES 2017–2020 spirometry and prevalence data.
- CDC BRFSS 2022 state-level COPD burden.
- GOLD 2024 COPD management guidelines (stage distribution, LTOT).
- ATS/ERS spirometric reference equations (GLI-2012).
- NHLBI COPD National Action Plan epidemiology.

### CHF — `modules/chf/chf_generator.py`
- AHA/ACC 2022 Heart Failure Guidelines; AHA 2021 statistics.
- NHANES 2017–2020 cardiovascular data.
- CMS Hospital Readmissions Reduction Program (HRRP) benchmarks (~22% 30-day rate).
- MAGGIC meta-analysis (39,372 patients) for mortality/readmission risk.
- OPTIMIZE-HF registry — Fonarow GC et al. *JAMA* 2007;297(1):61-70 (hospitalized
  NYHA severity mix; **this is an acute inpatient cohort, not community HF**).
- ESC Heart Failure Long-Term Registry.

### OUD — `modules/oud/oud_generator.py`
- SAMHSA NSDUH 2022 (National Survey on Drug Use and Health).
- CDC Drug Overdose Surveillance 2022–2023.
- NIDA Opioid Overdose Crisis statistics.
- DSM-5-TR OUD diagnostic criteria; ASAM Clinical Practice Guideline 2023.
- PCSS-MATS clinical guidance; AHRQ MOUD evidence review 2021.
- Rural-urban OUD disparity — Mack KA et al. *MMWR* 2017.
- IHS / tribal OUD burden — Sequist TD. *NEJM* 2021.

### ND Tribal Region Profiles — `hipaasynth/profiles/nd_tribal_region_*.json`
Peer-reviewed anchors carried with DOIs in the profile `sources` block:
- **Diabetes (AI/AN)**: Dai J et al. *Diabetes Obes Metab.* 2024;27(1):328-337.
  doi:10.1111/dom.16021 — AI/AN diabetes prevalence 13.6% (2019–2021), ~2× the
  6.9% non-Hispanic White rate.
- **Hypertension (AI/AN)**: Jolly SE et al. WATCH Study. *J Clin Hypertens.*
  2015;17(10):812-818. doi:10.1111/jch.12483; Strong Heart Study (ND/SD) baseline
  HTN ~27%.
- **DM+HTN comorbidity**: Walls ML et al. *J Diabetes Res.* 2025.
  doi:10.1155/jdr/6591307 — 77.9% of AI/AN adults with T2D also have HTN.
- **CKD**: Nephrology Mini Orals. *Nephrology.* 2021;26(S2):17-32.
  doi:10.1111/nep.13930.
- **Sepsis SDOH**: Ardabili AK et al. *World Med Health Policy.* 2025;17(4):823-830.
  doi:10.1002/wmh3.70043.
- **Sepsis-3**: Singer M et al. *JAMA.* 2016;315(8):801-810. doi:10.1001/jama.2016.0287.
- **Afebrile elderly infection**: Gavazzi G, Krause KH. *Lancet Infect Dis.*
  2002;2(11):659-666. doi:10.1016/S1473-3099(02)00437-1.
- **IHS workforce**: Brockie T et al. *J Clin Nurs.* 2021;32(3-4):610-624.
  doi:10.1111/jocn.15801 — IHS nurse vacancy 23–40%.

> **Documented calibration gaps** (carried in each profile's `calibration_notes`):
> the engine currently applies US-baseline comorbidity generation; AI/AN-specific
> prevalence (e.g. 13.6% diabetes) is documented but not yet applied as a regional
> adjustment. These gaps are recorded, not hidden.

---

## How to Update Anchors in Code
1. Download the latest tables from the source above.
2. Convert to the simple DataFrame / dict-of-targets format expected by
   `CalibrationValidator` (`hipaasynth/modules/calibration_validator.py`) — one
   `check(label, actual, target, tol)` per anchored metric.
3. Regenerate cohorts and re-run validation on a 10k–50k patient cohort
   (`python3 hipaasynth/modules/run_all_modules.py` generates n=1000 calibration
   cohorts and writes `output/calibration_report.json`).
4. Re-stamp with the CAP and commit the new `target_tables` + report + hashes
   (see below).

---

## Validation Methodology

### Tolerance-based acceptance (current implementation)
`calibration_validator.py` compares each generated distribution/mean against its
published target with an **absolute tolerance** (default `±0.08` on
proportions; wider, metric-appropriate tolerances on continuous values and
rarer strata). A metric is `PASS` when `|actual − target| ≤ tolerance`. The
default tolerance is deliberately conservative for `n=1000` sampling noise; the
per-metric tolerances are recorded in the report and shown in the chart.

### Statistical threshold (for distributional anchors)
For anchors expressed as full distributions rather than point prevalences, we use
**p > 0.05 on chi-square (categorical) or Kolmogorov–Smirnov (continuous) tests**
as "no significant difference" from the real-world anchor. **Any deviation must be
documented** in the profile `calibration_notes` and/or this file — for example the
COPD SpO2 mean and CHF HFrEF EF mean run at the low edge of their bands
intentionally (severity framing), and OUD HCV runs above target reflecting the
IV-use-heavy rural cohort.

### Cohort framing caveats (do not mis-compare)
- **CHF** is a *hospitalized/acute* cohort (OPTIMIZE-HF severity mix); do not
  compare to outpatient or population HF registries.
- **OUD** is a *treatment-seeking, rural/frontier-weighted* cohort; not the
  general population.
- **ND tribal profiles** represent patients who *reached* ICU/clinical care, not
  the full community — access limitations bias who appears.

---

## CAP Stamping (Cryptographic Audit Pipeline)

Calibration data is stamped so any later tampering is detectable. The
`docs/calibration/stamp_calibration.py` tool is the calibration analogue of the
suite-level `cap_pipeline.py` in the research repo: instead of chaining module
result hashes (psf/dif/cc/adv), it chains the per-module calibration **cohort CSV
hashes** plus the **calibration report hash** into a single SHA-256 chain hash.

**Stamp / re-stamp:**
```bash
python3 hipaasynth/modules/run_all_modules.py          # regenerate cohorts + report
python3 docs/calibration/stamp_calibration.py          # write CAP stamp + statement
```

This writes into `docs/calibration/`:
- `calibration_stamp.json` — machine-readable stamp (per-file hashes, chain hash).
- `calibration_cap_statement.txt` — human-readable certification statement.
- `calibration_chain_hash.txt` — the single chain hash to anchor.

**Chain integrity:** any edit to a cohort CSV or the report changes the chain
hash; the certification is valid only when the recomputed chain hash matches the
recorded value.

**Latest stamp** (`n=1000`/module, 92/92 PASS across 9 modules):

| Artifact | SHA-256 |
|---|---|
| COPD cohort CSV | `7882ecb037786469c7eb15e04d048cf7354160852f9ba2fd199f09c3be4b47c3` |
| CHF cohort CSV  | `a7efc6b042a6179204bdca43b2394aac5f75dbbbf1b3887c643455ef3f7f2987` |
| OUD cohort CSV  | `937a0cc02a4de62e06d3ba7dde4252ece841dc0b42cd3bdeac84dd5c2c3dd535` |
| Stroke cohort CSV | `703833e9c5bc4f21c3cda3696027d7ef9fc619a1046fa9467a738117149fb0ab` |
| Diabetes cohort CSV | `49da9d45e151333b0fef3e9317979c40859e3aa99e11c8574f840c9ff1c65cde` |
| SMA cohort CSV | `5cd84f39b77fd31e79680bf3904f88bd5430a0a1cd18be5233fe271e903c26db` |
| DMD cohort CSV | `529db66c1ab790b23da95a2c91b8b8b979df222b1753cff1ed2cb514243a26e7` |
| Fabry cohort CSV | `998f4c533fdf279c8d030b90557602862f49bfc6ee024b4fffa3282456cd8402` |
| Oncology cohort CSV | `cbd7eb6227c83cfcec951b530ae23b432327f94965fbc44095758ee3d901330f` |
| Calibration report (content, excl. timestamp) | `5b91bc406051eb129321bd37fa73c75907551d81400c3e1807dff2435ee2b216` |
| **Chain hash** | `665cc9e06b53a72b804edda27ca79d81c9ae799a63671712f55b9cd62a29c37f` |

> The chain hash is computed over the cohort CSV hashes plus a **canonical
> content hash** of the report (the wall-clock `generated_utc` is excluded), so
> re-running the pipeline on the same engine + seeds reproduces the identical
> chain hash — verified deterministic across runs.

**OpenTimestamps anchor:** `PENDING`. Submit `calibration_chain_hash.txt` to
https://opentimestamps.org to anchor the certification to the Bitcoin blockchain,
then run `cap_upgrade.py` (research repo) to mark it `CONFIRMED`.

> Cohort CSVs themselves are not committed (they live under the git-ignored
> `output/` directory and are regenerable from seed); their hashes above make the
> committed report + stamp independently verifiable.

---

## Appendix A: Calibration vs. Data (Side-by-Side)

Generated from `docs/calibration/calibration_report.json`. Proportions shown as
percentages; continuous metrics (age, FEV1%, SpO2, EF, BNP, sodium) shown as
values. `Δ` is `|actual − target|`.

### COPD — 15 PASS / 0 FAIL

| Metric | Target | Actual | Tolerance | Δ | Status |
|---|---|---|---|---|---|
| COPD age mean | 64.0 | 64.1 | ±4.0 | 0.1 | ✅ PASS |
| COPD female proportion | 52.0% | 51.8% | ±8.0% | 0.2% | ✅ PASS |
| GOLD_1 proportion | 20.0% | 20.7% | ±8.0% | 0.7% | ✅ PASS |
| GOLD_2 proportion | 38.0% | 36.4% | ±8.0% | 1.6% | ✅ PASS |
| GOLD_3 proportion | 28.0% | 28.9% | ±8.0% | 0.9% | ✅ PASS |
| GOLD_4 proportion | 14.0% | 14.0% | ±8.0% | 0.0% | ✅ PASS |
| COPD current smoker | 38.0% | 37.3% | ±8.0% | 0.7% | ✅ PASS |
| COPD former smoker | 47.0% | 47.4% | ±8.0% | 0.4% | ✅ PASS |
| COPD never smoker | 15.0% | 15.3% | ±8.0% | 0.3% | ✅ PASS |
| COPD hypertension | 55.0% | 60.6% | ±10.0% | 5.6% | ✅ PASS |
| COPD T2DM | 22.0% | 26.6% | ±10.0% | 4.6% | ✅ PASS |
| COPD depression | 27.0% | 32.3% | ±10.0% | 5.3% | ✅ PASS |
| GOLD_2 FEV1% mean | 64.5 | 64.7 | ±6.0 | 0.2 | ✅ PASS |
| GOLD_4 LTOT rate | 42.0% | 41.4% | ±12.0% | 0.6% | ✅ PASS |
| COPD SpO2 mean | 94.5 | 92.4 | ±2.5 | 2.1 | ✅ PASS |

### CHF — 16 PASS / 0 FAIL

| Metric | Target | Actual | Tolerance | Δ | Status |
|---|---|---|---|---|---|
| CHF age mean | 74.0 | 71.9 | ±4.0 | 2.1 | ✅ PASS |
| CHF male proportion | 52.0% | 50.7% | ±8.0% | 1.3% | ✅ PASS |
| CHF Black ethnicity | 20.0% | 18.8% | ±10.0% | 1.2% | ✅ PASS |
| HFrEF proportion | 48.0% | 48.1% | ±8.0% | 0.1% | ✅ PASS |
| HFpEF proportion | 38.0% | 36.7% | ±8.0% | 1.3% | ✅ PASS |
| HFmrEF proportion | 14.0% | 15.2% | ±8.0% | 1.2% | ✅ PASS |
| NYHA III+IV proportion | 83.0% | 83.2% | ±8.0% | 0.2% | ✅ PASS |
| HFrEF EF mean | 29.0 | 24.8 | ±6.0 | 4.2 | ✅ PASS |
| CHF hypertension | 73.0% | 73.6% | ±10.0% | 0.6% | ✅ PASS |
| CHF T2DM | 45.0% | 45.1% | ±10.0% | 0.1% | ✅ PASS |
| CHF afib | 45.0% | 44.6% | ±10.0% | 0.4% | ✅ PASS |
| CHF CKD | 48.0% | 48.8% | ±10.0% | 0.8% | ✅ PASS |
| NYHA III BNP mean | 650 | 750 | ±250 | 100 | ✅ PASS |
| CHF sodium mean | 138 | 137 | ±3.0 | 1.2 | ✅ PASS |
| 30-day readmission risk mean | 24.0% | 25.1% | ±6.0% | 1.1% | ✅ PASS |
| HFrEF beta blocker | 82.0% | 85.2% | ±10.0% | 3.2% | ✅ PASS |

### OUD — 16 PASS / 0 FAIL

| Metric | Target | Actual | Tolerance | Δ | Status |
|---|---|---|---|---|---|
| OUD age mean | 38.0 | 38.2 | ±5.0 | 0.2 | ✅ PASS |
| OUD male proportion | 57.0% | 56.2% | ±8.0% | 0.8% | ✅ PASS |
| OUD rural+frontier | 33.0% | 34.7% | ±8.0% | 1.7% | ✅ PASS |
| OUD severe proportion | 54.0% | 53.6% | ±8.0% | 0.4% | ✅ PASS |
| Illicit fentanyl | 35.0% | 33.5% | ±8.0% | 1.5% | ✅ PASS |
| IV drug use | 32.0% | 31.5% | ±8.0% | 0.5% | ✅ PASS |
| No MOUD (treatment gap) | 78.0% | 80.6% | ±8.0% | 2.6% | ✅ PASS |
| OUD depression | 55.0% | 55.1% | ±10.0% | 0.1% | ✅ PASS |
| OUD tobacco | 72.0% | 72.3% | ±10.0% | 0.3% | ✅ PASS |
| OUD HCV | 38.0% | 47.1% | ±12.0% | 9.1% | ✅ PASS |
| OUD AUD comorbid | 38.0% | 39.4% | ±10.0% | 1.4% | ✅ PASS |
| OUD PTSD | 35.0% | 32.7% | ±10.0% | 2.3% | ✅ PASS |
| Severe OUD prior overdose | 52.0% | 51.9% | ±12.0% | 0.1% | ✅ PASS |
| Frontier naloxone access | 18.0% | 15.1% | ±12.0% | 2.9% | ✅ PASS |
| Benzo co-use on UDS | 38.0% | 39.1% | ±10.0% | 1.1% | ✅ PASS |
| Medicaid insurance | 42.0% | 39.7% | ±10.0% | 2.3% | ✅ PASS |

### STROKE — 6 PASS / 0 FAIL
(intrinsic anchors, clean base; see `calibration_validator_ext.py` and CITATIONS.md § Stroke)

| Metric | Target | Actual | Tolerance | Status |
|---|---|---|---|---|
| Ischemic stroke proportion | 84.0% | 82.2% | ±6.0% | ✅ PASS |
| Hemorrhagic stroke proportion | 13.0% | 12.8% | ±5.0% | ✅ PASS |
| TIA proportion | 5.0% | 5.0% | ±4.0% | ✅ PASS |
| NIHSS mild category proportion | 50.0% | 49.2% | ±10.0% | ✅ PASS |
| Atrial fibrillation in stroke | 28.0% | 26.8% | ±8.0% | ✅ PASS |
| Onset-to-door median minutes | 83.0 | 88.0 | ±22.0 | ✅ PASS |

### DIABETES — 7 PASS / 0 FAIL

| Metric | Target | Actual | Tolerance | Status |
|---|---|---|---|---|
| Type 1 diabetes proportion | 6.0% | 5.6% | ±3.0% | ✅ PASS |
| Type 2 diabetes proportion | 94.0% | 94.4% | ±3.0% | ✅ PASS |
| White proportion | 55.0% | 55.7% | ±8.0% | ✅ PASS |
| Black proportion | 18.0% | 18.3% | ±7.0% | ✅ PASS |
| Hispanic proportion | 15.0% | 13.7% | ±7.0% | ✅ PASS |
| Asian proportion | 8.0% | 8.6% | ±5.0% | ✅ PASS |
| Diabetes current-age mean | 55.0 | 55.5 | ±6.0 | ✅ PASS |

### SMA — 6 PASS / 0 FAIL

| Metric | Target | Actual | Tolerance | Status |
|---|---|---|---|---|
| SMA-I proportion | 55.0% | 54.4% | ±8.0% | ✅ PASS |
| SMA-II proportion | 30.0% | 31.4% | ±8.0% | ✅ PASS |
| SMA-III proportion | 14.0% | 12.9% | ±6.0% | ✅ PASS |
| On DMT / nusinersen | 65.0% | 65.8% | ±8.0% | ✅ PASS |
| SMA-II scoliosis | 60.0% | 57.0% | ±12.0% | ✅ PASS |
| SMA-I feeding support | 85.0% | 83.3% | ±12.0% | ✅ PASS |

### DMD — 7 PASS / 0 FAIL

| Metric | Target | Actual | Tolerance | Status |
|---|---|---|---|---|
| Male proportion | 100.0% | 100.0% | ±0.1% | ✅ PASS |
| Deletion mutation | 65.0% | 63.6% | ±8.0% | ✅ PASS |
| Duplication mutation | 10.0% | 9.1% | ±5.0% | ✅ PASS |
| Point mutation | 25.0% | 27.3% | ±8.0% | ✅ PASS |
| On corticosteroids | 70.0% | 69.6% | ±8.0% | ✅ PASS |
| Diagnosis age mean years | 4.5 | 4.5 | ±1.0 | ✅ PASS |
| Ambulation-loss age mean years | 12.5 | 12.6 | ±2.0 | ✅ PASS |

### FABRY — 6 PASS / 0 FAIL

| Metric | Target | Actual | Tolerance | Status |
|---|---|---|---|---|
| Male classic phenotype | 60.0% | 58.4% | ±10.0% | ✅ PASS |
| Female late-cardiac phenotype | 35.0% | 39.2% | ±10.0% | ✅ PASS |
| Missense mutation | 60.0% | 59.3% | ±8.0% | ✅ PASS |
| Nonsense mutation | 15.0% | 14.3% | ±6.0% | ✅ PASS |
| On enzyme replacement therapy | 55.0% | 55.1% | ±8.0% | ✅ PASS |
| Stroke/TIA history | 15.0% | 14.2% | ±8.0% | ✅ PASS |

### ONCOLOGY — 13 PASS / 0 FAIL
(breast/lung/colon; six chained sub-modules via `oncology/cohort.py`; see CITATIONS.md § Oncology)

| Metric | Target | Actual | Tolerance | Status |
|---|---|---|---|---|
| Breast site share | 44.0% | 41.7% | ±8.0% | ✅ PASS |
| Lung site share | 34.0% | 36.5% | ±8.0% | ✅ PASS |
| Colon site share | 22.0% | 21.8% | ±7.0% | ✅ PASS |
| Breast metastatic at dx (stage IV) | 6.0% | 3.6% | ±5.0% | ✅ PASS |
| Lung metastatic at dx (stage IV) | 57.0% | 55.6% | ±10.0% | ✅ PASS |
| Colon metastatic at dx (stage IV) | 24.0% | 20.6% | ±8.0% | ✅ PASS |
| Breast overall 5-yr survival | 90.0% | 92.3% | ±8.0% | ✅ PASS |
| Lung overall 5-yr survival | 27.0% | 26.9% | ±10.0% | ✅ PASS |
| Colon overall 5-yr survival | 62.0% | 59.2% | ±10.0% | ✅ PASS |
| Breast HR+/HER2- luminal | 73.0% | 74.3% | ±8.0% | ✅ PASS |
| Breast triple-negative | 12.0% | 11.8% | ±5.0% | ✅ PASS |
| Colon MSI-H | 15.0% | 13.8% | ±6.0% | ✅ PASS |
| Lung KRAS+ | 25.0% | 26.6% | ±8.0% | ✅ PASS |

> **Documented gaps** (not asserted as calibrated): stroke tPA-within-window
> (~27% vs literature 47–53%) and SBP>185 fraction (~15% vs 20–25% target) are
> catalogued in CITATIONS.md § Documented gaps rather than charted as PASS.

---

## Reproducing This Report
```bash
# 1. Generate calibration cohorts (n=1000/module) + calibration_report.json
python3 hipaasynth/modules/run_all_modules.py

# 2. Copy the report into the committed docs directory
cp hipaasynth/modules/output/calibration_report.json docs/calibration/

# 3. CAP-stamp the cohorts + report (writes hashes + statement)
python3 docs/calibration/stamp_calibration.py

# 4. Rebuild the side-by-side chart
python3 docs/calibration/build_chart.py
```

All four steps use only the Python standard library. Zero external dependencies,
zero network calls, zero PHI.

---

Last updated: 2026-07-22 by Cody Carlson
