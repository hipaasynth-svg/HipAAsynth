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

Latest run — engine `v1.0.2`, `n=1000` per module, **47 / 47 checks PASS**.

| Module | Checks | Result |
|---|---|---|
| COPD | 15 | ✅ 15 PASS / 0 FAIL |
| CHF  | 16 | ✅ 16 PASS / 0 FAIL |
| OUD  | 16 | ✅ 16 PASS / 0 FAIL |
| **Total** | **47** | **✅ 47 PASS / 0 FAIL** |

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

**Latest stamp** (engine `v1.0.2`, `n=1000`/module, 47/47 PASS):

| Artifact | SHA-256 |
|---|---|
| COPD cohort CSV | `c2e9d750fea83fec63dacb36cdfa0b680b53408dabb646afbcaebc54a8f15df6` |
| CHF cohort CSV  | `8790871cdcb864d259108a1fa8d8920785dc007389ca07294f10f174aace78f8` |
| OUD cohort CSV  | `38f5706d71bf2e5eed059ed3d362e71de09cce963585da52978b15263a028199` |
| Calibration report | `f2a1098c81acd58a1e8a72285025835a6e37f93d4b714768b8863dcfe18916ad` |
| **Chain hash** | `0495dd0fb3d6f4db36ea08a368761d9fc492a9d4d01b32863114e01b14168674` |

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

Last updated: 2026-07-20 by Cody Carlson
