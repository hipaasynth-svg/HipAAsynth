# HipAAsynth Datasheet v1

This document is a code-derived datasheet for the synthetic-cohort **modules and profiles** in the HipAAsynth repository. Every age bound, field, range, cap, calibration-source name, and seeding method below was extracted directly from the source files at commit **`cae9b145e70cc55990e8639aed8a45a8100fd61e`** (committed 2026‑07‑11; audit performed 2026‑07‑14). Nothing here is inferred from outside knowledge: where a value or a source is not stated in the code, the entry says **"not specified in code."** The modules themselves are the source of truth; this datasheet is only a collector and index. All file references are repo‑relative and include line numbers so any claim can be checked against the code.

---

## A note on sourcing

A note on sourcing: This datasheet exists because the HipAAsynth domain is large enough that my mind had drifted on exact module parameters during conversation. Rather than ask anyone to trust my memory, every value here is extracted directly from the code, with file references so it can be verified independently. The calibration source for any given field is whatever is described in the module where that field lives, or wherever it lives in the code — this document simply collects those statements in one place. Built solo over seven months; the modules, not this summary, are the canonical source of truth.

---

## Inventory

Two families of artifacts define patient parameters in this repo.

### Clinical cohort modules (`hipaasynth/modules/`)

| # | Module | Defining file(s) | How it produces patients | Wired into a package pipeline/CLI? |
|---|--------|------------------|--------------------------|-------------------------------------|
| 1 | COPD | `hipaasynth/modules/copd/copd_generator.py` | Self-contained cohort generator | Yes — `hipaasynth/modules/run_all_modules.py` |
| 2 | CHF readmission | `hipaasynth/modules/chf/chf_generator.py` | Self-contained cohort generator | Yes — `run_all_modules.py` |
| 3 | OUD | `hipaasynth/modules/oud/oud_generator.py` | Self-contained cohort generator | Yes — `run_all_modules.py` |
| 4 | Stroke | `hipaasynth/modules/stroke/observations.py` | Observation hook over engine-generated patients | Yes — `hipaasynth/pipelines/population_pipeline.py:51,203` |
| 5 | Sepsis | `hipaasynth/modules/sepsis/observations.py` | Observation hook over engine-generated patients | Yes — `population_pipeline.py:50,212` |
| 6 | Oncology | `hipaasynth/modules/sepsis/oncology/{population,staging,biomarkers,comorbidity,treatment,outcomes}.py` | Six chained sub-modules | **No** — no in-package driver imports them (see Global Limitations) |
| 7 | Diabetes | `hipaasynth/modules/diabetes/{population,glycemic,complications,treatments,outcomes}.py` | Five chained sub-modules | Yes — `hipaasynth/run/diabetes_pipeline.py` |
| 8 | Cardiology | `hipaasynth/modules/cardiology/{risk_scores,medications}.py` | Two scorer/medication modules over caller-supplied data | **No** — referenced only in `tests/test_seismometer_adapter.py` |
| 9 | DMD | `hipaasynth/modules/dmd/dmd.py` | Self-contained cohort generator | Standalone `__main__` only |
| 10 | Fabry | `hipaasynth/modules/fabry/fabry.py` | Self-contained cohort generator | Standalone `__main__` only |
| 11 | SMA | `hipaasynth/modules/sma/sma.py` | Self-contained cohort generator | Standalone `__main__` only |

### Population profiles (`hipaasynth/profiles/*.json`)

Nine geographic profiles that override engine demographics (age-band weights, sex ratio, ethnicity, rural flag) for the profile-driven hooks (Stroke, Sepsis): `us_default.json`, `fargo_nd.json`, `minot_nd.json`, `nd_tribal_region_a.json`, `nd_tribal_region_a_v2.json`, `nd_tribal_region_b.json`, `nd_tribal_region_b_v2.json`, `karachi_pakistan.json`, `lagos_nigeria.json`. Profile schema and an example are described in the Profiles section.

### Engine-wide constants (source of the shared fields)

`hipaasynth/core/config.py:29-30` defines the values actually emitted into every COPD/CHF/OUD record:
- `ENGINE_VERSION = "1.0.2"`
- `SCHEMA_VERSION = "1.0.0"`

`hipaasynth/core/config.py:58-62` defines `DEFAULT_SYNTHETIC_DISCLAIMER`, imported by every module as the `disclaimer` field.

> **Provenance (verify at `copd_generator.py:27-28`, `chf_generator.py:44-45`, `oud_generator.py:36-37` vs `config.py:29-30`):** The COPD/CHF/OUD module docstrings now state "Engine: HipAAsynth v1.0.2 / Schema: v1.0.0," matching the `ENGINE_VERSION`/`SCHEMA_VERSION` constants imported from `config.py` and written to every record. A prior discrepancy — docstrings stale at v1.0.1 / v1.1.0 while records carried 1.0.2 / 1.0.0 — was corrected.

---

## Module 1 — COPD

**File:** `hipaasynth/modules/copd/copd_generator.py`
**Module name emitted:** `copd` (`:48`)

### Determinism / seeding
SHA-256 anchor-rooted. `make_anchor(seed, module, n)` hashes a sorted JSON of `{seed, module, n}` (`:53-55`). `derive_rng(anchor, namespace)` hashes `"{anchor}:{namespace}"`, mods by 10⁹, and seeds a `random.Random` (`:57-62`). Nine independent namespaced RNGs: `demographics, gold_staging, smoking, comorbidities, labs, medications, functional, exacerbations, patient_ids` (`:307-315`). Run wiring uses seeds 3001 (n=50) and 3002 (n=1000) (`run_all_modules.py:56-62`).

### Age bounds (traced)
`PROFILE["age_range"] = (40, 85)` (`:72`). Age is drawn by picking a weighted band from `age_weights` — `(40,49):0.12, (50,59):0.22, (60,69):0.30, (70,79):0.25, (80,85):0.11` — then `randint(band_lo, band_hi)` (`:74-80, 323-326`). **Real enforced bounds: 40–85 inclusive.**

### Fields & calibration sources
All records carry the core schema block (`:431-445`): `patient_id` (str, `SYN-COPD-` + 8 hex, `:275-277`), `age` (int), `sex` (str male/female), `ethnicity` (str), `height_cm` (float), `weight_kg` (float), `bmi` (float), `bmi_category` (str), `conditions` (str, `;`-joined), `engine_version`/`schema_version` (str, from config), `synthetic` (bool True), `disclaimer` (str).

COPD-specific fields and the source **as stated in the module**:

| Field group | Fields (type) | Source as stated in code | Location |
|---|---|---|---|
| Population/demographics | age, sex, ethnicity | "Calibrated to US national COPD burden (NHANES / CDC BRFSS 2022)"; "Wheaton AG et al. MMWR 2015;64(SS-7):1-20." | `:65-90` |
| GOLD stage | `gold_stage` (str) | "Lamprecht B et al. Respir Res 2011;12:121." | `:93-100` |
| Spirometry | `fev1_pct_predicted` (float), `fev1_fvc_ratio` (float), `fev1_absolute_l` (float) | FEV1 ranges no explicit citation (`GOLD_FEV1`); FEV1/FVC "GOLD 2024 Global Strategy for COPD"; absolute FEV1 "GLI-2012 reference; sex/age/height adjusted" | `:102-117, 347-353` |
| ABCD group | `gold_abcd_group` (str A/B/E) | "ABCD grouping (GOLD 2023+)" — no journal source stated | `:419-426` |
| Smoking | `smoking_status` (str), `pack_years` (float) | "Salvi SS, Barnes PJ. Lancet 2009;374(9691):733-743." | `:119-133` |
| Comorbidities (9 bool) | hypertension, cardiovascular_disease, type2_diabetes, depression, anxiety, osa, pulmonary_hypertension, osteoporosis, lung_cancer_history | Sin DD Chest 2006; Mirrakhimov Cardiovasc Diabetol 2012; Yohannes Respir Care 2014; Shawon Respir Med 2017; Chaouat Eur Respir J 2008 | `:135-152` |
| Medications (7 bool) | med_saba_prn, med_laba, med_lama, med_ics_laba, med_triple_therapy, med_oral_corticosteroid, med_roflumilast | "GOLD 2024 pharmacotherapy recommendations" | `:191-230` |
| Oxygen | `ltot` (bool) | "NOTT Trial; ATS statement on LTOT" | `:232-240` |
| Functional | `mmrc_dyspnea_grade` (int 0-4), `cat_score` (int), `six_min_walk_m` (float) | mMRC & CAT "Jones PW et al. ERJ 2009;34(3):648-654."; 6MWD "Enright PL, Sherrill DL. Am J Respir Crit Care Med 1998;158(5):1384-1387." | `:172-189, 250-257` |
| Exacerbations | `exacerbations_prior_yr` (int), `hospitalized_prior_yr` (bool), `icu_admit_prior_yr` (bool) | "Hurst JR et al. NEJM 2010;363(12):1128-1138."; ICU 22% inline, no source stated | `:154-170, 394` |
| Labs/vitals | `spo2_pct` (float), `hemoglobin_gdl` (float), `bnp_pgml` (float), `creatinine_mgdl` (float), `sodium_meql` (float), `glucose_mgdl` (float) | Hgb "Cote C et al. Chest 2007;131(6):1635-1643."; BNP "Stolz D et al. Chest 2008;133(4):952-960."; SpO2/creatinine/sodium/glucose — **no source stated in module** | `:242-272, 408-417` |

### Hard-coded ranges / caps / clamps
Height clamp `max(148, min(205))`, weight `max(38, min(160))` (`:294-295`). Comorbidity rate `× 1.3` if GOLD_3/4, capped at 0.95 (`:367-368`). Creatinine clamp 0.4–4.0 (`:410`); sodium 128–150 (`:413`); glucose 55–350 (`:417`); hemoglobin clamped to its GOLD range (`:403`). Per-GOLD FEV1, FEV1/FVC, CAT, SpO2, 6MWD, Hgb, BNP, exacerbation and pack-year ranges are hard-coded dicts (`:103-272`).

### Limitations
- SpO2, creatinine, sodium, glucose have **no calibration source stated** in the module.
- Comorbidity/medication booleans are independent Bernoulli draws; no joint dependency structure beyond the GOLD_3/4 × 1.3 comorbidity multiplier.
- No explicit TODO/FIXME comments in file.

---

## Module 2 — CHF readmission

**File:** `hipaasynth/modules/chf/chf_generator.py`
**Module name emitted:** `chf_readmission` (`:63`)

### Determinism / seeding
Same anchor scheme as COPD (`:68-77`). Eight namespaced RNGs: `demographics, phenotype, comorbidities, labs, medications, risk_scores, admissions, patient_ids` (`:358-365`). Run seeds 4001 / 4002 (`run_all_modules.py:70-76`).

### Age bounds (traced)
`PROFILE["age_range"] = (45, 90)` (`:86`); bands `(45,54):0.08, (55,64):0.17, (65,74):0.28, (75,84):0.32, (85,90):0.15` → `randint` within band (`:87-93, 372-375`). **Enforced bounds: 45–90 inclusive.**

### Explicit cohort framing (stated in code)
Docstring `:31-42`: this is a **HOSPITALIZED/ACUTE** HF cohort. NYHA distribution (I 3%, II 14%, III 54%, IV 29% as coded at `:123-128`; docstring prose cites I 8%/II 9% but the code dict is the truth) intentionally skewed to severe disease, mirroring OPTIMIZE-HF (Fonarow GC et al. JAMA 2007;297(1):61-70). The code explicitly says **not** to compare to outpatient/community registries.

### Fields & calibration sources
Core schema block as in COPD (`:516-530`), patient_id prefix `SYN-CHF-` (`:350-352`).

| Field group | Fields (type) | Source as stated in code | Location |
|---|---|---|---|
| Demographics | age, sex, ethnicity | "Virani SS et al. Circulation 2021;143:e254-e743." (Black burden noted inline) | `:79-103` |
| Phenotype | `hf_phenotype` (str), `ejection_fraction_pct` (int), `nyha_class` (str), `acc_aha_stage` (str), `hf_etiology` (str) | Phenotype/EF "McDonagh TA et al. Eur Heart J 2021;42(36):3599-3726."; NYHA "Fonarow GC JAMA 2007"; etiology "Gheorghiade M, Bonow RO. Circulation 1998;97(3):282-289."; ACC/AHA stage — **no source stated** | `:105-146, 383-401` |
| Vitals | `systolic_bp_mmhg` (float), `heart_rate_bpm` (float), `spo2_pct` (float), `acute_weight_gain_kg` (float) | **No source stated**; SBP means keyed by phenotype inline | `:406-426` |
| Comorbidities (13 bool) | hypertension, type2_diabetes, ckd, afib, copd, cad, prior_mi, prior_cabg_or_pci, anemia, sleep_apnea, depression, peripheral_vascular_disease, stroke_tia_history | "Dharmarajan K et al. JAMA 2013;309(4):355-363."; "Rich MW et al. J Am Geriatr Soc 2013;61(6):917-925." | `:148-166` |
| Labs | `bnp_pgml`, `ntprobnp_pgml`, `troponin_i_hs_ngl`, `troponin_elevated` (bool), `sodium_meql`, `creatinine_mgdl`, `egfr_ml_min_173m2`, `potassium_meql`, `hemoglobin_gdl` | BNP "Maisel AS NEJM 2002"; NT-proBNP "Januzzi JL Am J Cardiol 2005"; DOSE "Felker GM NEJM 2011"; troponin "Peacock WF Am Heart J 2008"; sodium "Gheorghiade M Arch Intern Med 2007"; creatinine "Ronco C JACC 2008"; eGFR (MDRD formula, no citation) | `:168-209, 439-465` |
| Admissions | `prior_hf_admissions_1yr` (int), `prior_any_admissions_1yr` (int), `index_los_days` (int) | "Krumholz HM et al. Circ Heart Fail 2009;2(5):543-550." | `:467-475` |
| Medications (8 bool emitted) | med_acei_arb_arni, med_beta_blocker, med_mra, med_sglt2i, med_loop_diuretic, med_digoxin, med_anticoagulant, med_statin | "Heidenreich PA et al. Circulation 2022;145(18):e895-e1032." | `:211-253` |
| Devices (3 bool emitted) | device_icd, device_crt_d, device_lvad | "Moss AJ et al. NEJM 2002;346(12):877-883. (MADIT-CRT)" | `:255-262` |
| Risk scores | `maggic_1yr_risk_score` (int, cap 40), `readmission_risk_30d` (float, cap 0.70), `cha2ds2_vasc` (int or None) | MAGGIC "Pocock SJ et al. Eur Heart J 2013;34(19):1404-1413."; LACE "van Walraven C CMAJ 2010"; 30-day "national CMS HRRP mean ~22%" | `:264-328, 485-512` |

### Hard-coded ranges / caps / clamps
Height 145–200, weight 35–180 (`:341-342`); SBP 70–220, HR 45–140, SpO2 82–100 (`:414-423`); creatinine floor 0.4 (`:456`), eGFR floor 5.0 (`:458`), potassium 2.8–6.5 (`:461`), hemoglobin 6.0–18.0 (`:465`). MAGGIC capped at 40 (`:313`); readmission risk capped at 0.70 (`:328`). Ischemic etiology forces `cad=True` (`:434-435`).

### Limitations
- Vitals block and ACC/AHA stage distribution carry **no stated source**.
- `readmission_risk_30d` and `maggic` are simplified/hand-tuned additive models (the MAGGIC docstring at `:271-274` explicitly says "Simplified"); not the full published instruments.
- Several computed fields (`hf_etiology`, `prior_cabg_or_pci`, `anemia`, full device set, `troponin_i_hs`) are generated but **not all emitted** in the output row (e.g., `crt_p`, `lvad`/`iabp_prior` partially, `hydralazine_nitrate`, `ivabradine`, `aspirin` meds are computed at `:479-482` but omitted from the record `:581-593`).

---

## Module 3 — OUD (Opioid Use Disorder)

**File:** `hipaasynth/modules/oud/oud_generator.py`
**Module name emitted:** `oud` (`:54`)

### Determinism / seeding
Anchor scheme identical to COPD (`:59-68`). Eight namespaced RNGs: `demographics, clinical, comorbidities, social_determinants, labs, medications, history, patient_ids` (`:342-349`). Run seeds 5001 / 5002 (`run_all_modules.py:84-90`).

### Age bounds (traced)
`PROFILE["age_range"] = (18, 65)` (`:77`); bands `(18,24):0.15, (25,34):0.28, (35,44):0.25, (45,54):0.20, (55,65):0.12` (`:78-84, 356-359`). **Enforced bounds: 18–65 inclusive.**

### Fields & calibration sources
Core schema block (`:479-492`), patient_id prefix `SYN-OUD-` (`:334-336`). Explicitly targets rural/IHS/frontier under-representation (docstring `:31-34`).

| Field group | Fields (type) | Source as stated in code | Location |
|---|---|---|---|
| Demographics + rurality | age, sex, ethnicity, `rurality` (urban/suburban/rural/frontier) | "SAMHSA. NSDUH 2022 …PEP23-07-01-006"; sex "SAMHSA 2022"; rurality "Mack KA et al. MMWR 2017;66(19):506-512." | `:70-105` |
| OUD clinical | `oud_severity` (str), `dsm5_criteria_count` (int), `primary_opioid` (str), `route_of_admin` (str), `iv_drug_use` (bool), `years_of_opioid_use` (float), `fentanyl_exposure_risk` (bool), `cows_score` (int) | Severity "APA DSM-5-TR 2022"; opioid "Jones CM et al. Drug Alcohol Depend 2020;214:108174."; route "Cicero TJ et al. NEJM 2014;371(22):2063-2066."; COWS "Wesson DR, Ling W. J Psychoactive Drugs 2003;35(2):253-259."; fentanyl "CDC. Drug Overdose Deaths. 2023." | `:107-243, 471-474` |
| MOUD | `moud_type` (str), `moud_current` (bool), `buprenorphine_dose_mgd` (float/None), `methadone_dose_mgd` (float/None), `naloxone_access` (bool), `distance_to_moud_provider_miles` (float) | MOUD status "Jones CM et al. JAMA Psychiatry 2022;79(5):512-520."; naloxone "Rando J et al. J Rural Health 2021;37(3):526-534."; distance "Andrilla CHA et al. J Rural Health 2019;35(1):8-25." | `:145-168, 444-451` |
| Prior history | `prior_overdose` (bool), `prior_overdose_count` (int), `prior_od_naloxone_reversed` (bool), `ed_visits_prior_yr` (int), `hx_inpatient_detox` (bool), `hx_residential_tx` (bool) | Prior OD "Larochelle MR et al. Ann Intern Med 2018;169(3):137-145."; ED "White AM et al. Drug Alcohol Depend 2021;227:109002." | `:170-234, 405-469` |
| Vitals (withdrawal) | `heart_rate_bpm`, `systolic_bp_mmhg`, `resp_rate`, `temperature_c` | **No source stated** (calibrated to withdrawal presentation, keyed off COWS) | `:245-276` |
| Labs | `alt_ul`, `ast_ul`, `creatinine_mgdl`, `sodium_meql`, `potassium_meql`, `hemoglobin_gdl`, `wbc_per_nl`, `uds_opioid`, `uds_benzodiazepine`, `uds_stimulant`, `uds_cannabis`, `uds_alcohol` (bool UDS) | **No source stated** for lab ranges | `:278-316` |
| Comorbidities (12 emitted bool) | depression, anxiety, ptsd, bipolar_disorder, alcohol_use_disorder, stimulant_use_disorder, tobacco_use_disorder, hepatitis_c, hiv, endocarditis_history, chronic_pain, adverse_childhood_experiences | "SAMHSA 2022"; "Edelman EJ et al. Drug Alcohol Depend 2019;200:14-23." | `:178-201` |
| Social determinants | `employment_status`, `insurance_status`, `housing_status`, `incarceration_history`, `homelessness_unstable_housing` | **No source stated** for employment/insurance/housing distributions | `:203-226` |

### Hard-coded ranges / caps / clamps
Buprenorphine dose 4.0–32.0, methadone 20.0–120.0 (`:156-158`). Height 148–204, weight 38–155 (`:325-326`). HR clamp 50–140, SBP 80–200, RR 10–36, temp 36.0–39.5 (`:255-274`). Lab clamps: creatinine 0.4–6.0, sodium 122–150, potassium 2.5–6.5, hgb 6–18, wbc 2–30 (`:286-299`). IV-use comorbidity multipliers: HCV ×1.8 cap 0.95, endocarditis ×2.2 cap 0.30, HIV ×1.5 cap 0.20; rural/frontier ACE & incarceration ×1.15 cap 0.95 (`:416-424`). Distance-to-MOUD ranges are rurality-keyed uniforms (urban 0.5–8, frontier 40–180 mi) (`:446-451`).

### Limitations
- Vitals, labs, and social-determinant distributions carry **no stated source**.
- The module contains an explicit self-documented pitfall note (`:510-513`): `"no_moud"` is truthy in Python, so downstream code must use the boolean `moud_current`, not `moud_type`.
- `uds_opioid` is a constant `True` (`:302`) — a placeholder, not a modeled value.

---

## Module 4 — Stroke (observation hook)

**File:** `hipaasynth/modules/stroke/observations.py`
**Emitted marker:** `stroke_observation_version = "stroke_generator_v2_calibrated"` (`:230,401`)

### Determinism / seeding
Not self-seeding. It is a hook called by `population_pipeline.py:203` with a per-patient RNG derived from the engine anchor (`obs_seed = anchor.derive_seed("observations:{patient_id}")`, `population_pipeline.py:193`). Randomness uses Box–Muller `_normal` on that RNG (`:90-94`).

### Age bounds (traced)
The module does **not** generate age; it consumes `demographics.age` from the engine (`:176`). Engine defaults are `age_min=18, age_max=90` (`config.py:93-94`), and profiles override the age-band weights (e.g., tribal profiles use `[[45,64,0.4],[65,90,0.6]]`, `nd_tribal_region_a.json`). The only age logic inside the module: `age_group = '65_plus' if age >= 65 else '18_64'` (`:175`), and `age < 18` is an absolute tPA contraindication (`:138-139`). **Enforced age range is inherited from the engine/profile, not from this module.**

### Fields & calibration sources
For non-stroke patients most fields are `None` with `stroke_flag=False` (`:208-231`). For stroke patients (`:380-402`):

| Field (type) | Source as stated in code | Location |
|---|---|---|
| `stroke_flag` (bool), `stroke_type` (str ischemic/hemorrhagic/tia) | "Ischemic 87%, Hemorrhagic 13% — Ren et al. MedComm 2025 [1]"; TIA modeled ~10% (coded thresholds r<0.11 hemorrhagic, <0.16 tia) | `:240-251` |
| `nihss_score` (int), `nihss_category` (str) | "Winder K et al. J Neuroimaging 2023 [2]"; categories "Feng L et al. J Clin Lab Anal 2018 [3]"; hemorrhagic conditioning "Broderick JP Stroke 2010 [11]" | `:97-102, 272-300` |
| `tpa_eligible` (bool), `tpa_administered` (bool), `door_to_needle_minutes` (int/None) | "AHA/ASA Guidelines 2019 [7]"; "Bergh E et al. Acta Neurol Scand 2022 [4]"; "Havenon A et al. Ann Neurol 2023 [5]" | `:105-157, 348-364` |
| `onset_to_door_minutes` (int) | "Bergh 2022 [4]"; rural tail "Internal calibration review, 2026-04-30 [10]" | `:321-336` |
| `sbp_admission` (int), `dbp_admission` (int) | "Internal calibration review 2026 [10]"; HTN 90% "Winder 2023 [2]" | `:302-319` |
| `atrial_fibrillation` (bool) | "AF present in 28% … Winder et al. 2023 [2]" | `:233-238` |
| `prior_stroke`, `prior_ich`, `recent_surgery`, `anticoagulant_use` (bool) | "internal review 2026 [10]: prior ICH 2-5%, recent surgery 2-4%" | `:338-346` |
| `mrs_discharge` (int 0-6), `mrs_90day` (int 0-6) | "mRS 0-1 at discharge 81% in minor stroke — Duan C et al. 2023 [6]" — explicitly **modeled, not epidemiologically precise** (`:53-55`) | `:366-378` |
| `rural_presentation` (bool), `region_profile` (str/None) | Profile-name detection; non-profile fallback `rng.random() < 0.17` | `:178-189` |

Full citation list `[1]-[12]` is in the module docstring (`:23-79`), including three internal calibration reviews ([10] 2026-04-30, [12] 2026-05-01).

### Hard-coded ranges / caps / clamps
Severity capped 0.85 (`:270`). NIHSS clamps by band: mild 0–4, moderate 5–15, severe 16–42, TIA 0–2 (`:288-298`). SBP clamp 118–230, DBP 58–120 (`:317-319`). Onset-to-door: rural late tail `Normal(400,90)` clamped 271–600; else clamped 10–300 (`:333-336`). DTN clamp 15–120 (`:364`). mRS clamp 0–6 (`:376-378`). tPA base prob 0.60 with multiplicative penalties (`:145-157`); `tpa_administered` only 40% of eligible (`:362`).

### Limitations (stated in code)
- `:51-61` "IMPORTANT BOUNDARIES": mRS outcome is **modeled, directionally consistent, not epidemiologically precise**. Racial/ethnic stroke-incidence differences are documented in literature but **NOT applied** as subgroup parameters — severity is comorbidity-driven only ("Documented limitation").
- Rural late-presenter tail activates **only** when a profile with `rural` in its name is loaded; with `PROFILE=None`, `rural_presentation=False` for all (`:56-61`).
- Known-issue note `[12]` (`:47-49`): `rural_presentation` null when no profile loaded is a config-level issue, not the module.

---

## Module 5 — Sepsis (observation hook)

**File:** `hipaasynth/modules/sepsis/observations.py`
**Emitted marker:** `observation_hook_version = "sepsis_generator_v3_bedside"` (`:276,504`)

### Determinism / seeding
Hook called by `population_pipeline.py:212` with the same per-patient engine-derived RNG as stroke. Box–Muller `_normal` (`:74-78`).

### Age bounds (traced)
Same as stroke: age comes from `demographics.age` (`:218`), engine default 18–90, profile-overridable. In-module age logic only: `age_group = "65_plus" if age >= 65 else "18_64"` (`:219`) and age-conditioned severity/afebrile/AMS probabilities. **Age range inherited from engine/profile.**

### Fields & calibration sources
Non-sepsis patients get a mostly-null dict with `sepsis_flag=False` (`:239-280`). Sepsis patients (`:459-508`):

| Field group | Fields (type) | Source as stated in code | Location |
|---|---|---|---|
| Infection | `suspected_infection_source` (str) | "Rhee C et al. JAMA Intern Med 2017 [S3]" (rural adjustment) | `:89-124` |
| Vitals | `temperature_c_initial`, `heart_rate_initial`, `resp_rate_initial`, `sbp_initial`, `dbp_initial`, `spo2_initial` (num) | "Singer M et al. Sepsis-3. JAMA 2016 [S1]"; afebrile elderly "Gavazzi G, Krause KH. Lancet Infect Dis 2002 [S2]" | `:322-348` |
| O2 support | `spo2_target_range` (str), `oxygen_device` (str), `fio2_percent` (float), `ventilation_mode` (str/None) | "Surviving Sepsis Campaign 2021 [S4]"; "Frat JP NEJM 2015 [S5]"; "Bellani G JAMA 2016 [S6]"; COPD target "O'Driscoll BR Thorax 2017 / GOLD 2024 [S10]" | `:127-174, 350-353` |
| Renal/fluid | `urine_output_ml_hr` (float), `fluid_input_6h_ml` (float), `fluid_balance_6h_ml` (float) | "Rhoads CM Chest 2019 [S7]"; "Cecconi M Intensive Care Med 2014 [S8]"; SSC 2021 [S4] | `:177-212, 386-444` |
| Labs | `wbc_initial`, `creatinine_initial`, `glucose_initial`, `lactate_initial` (float) | Threshold logic anchored to Sepsis-3 [S1]; **profile lab floors** referenced (WBC Singer 2016, Glucose ADA 2024, Creatinine KDIGO 2022) | `:355-383` |
| Comorbidity flags | `diabetes_flag`, `hypertension_flag`, `ckd_flag`, `dm_htn_ckd_stack_flag` (bool) | Derived from engine condition names | `:216-230` |
| Presentation pattern | `afebrile_flag`, `altered_mental_status_only_flag`, `delayed_hypotension_flag` (bool), `deterioration_pattern` (str) | "internal review 2026 [S9]" (four archetypes) | `:293-321` |
| Timeline | `hours_to_hypotension`, `hours_to_icu`, `hours_to_vasopressors` (int/None) | Pressor logic "SSC 2021 [S4]; internal review [S9]" | `:328-422` |
| Contradictory signals | `cryptic_shock_flag`, `normal_wbc_elevated_lactate_flag`, `afebrile_tachycardic_flag` (bool) | "internal review 2026 [S9]" | `:446-457` |

Citations `[S1]-[S10]` in docstring (`:28-63`), including internal review [S9] (2026-04-22).

### Hard-coded ranges / caps / clamps
Severity capped 0.88 (`:291`); afebrile prob capped 0.45 (`:294`); AMS 0.50 (`:298`); delayed-hypotension 0.55 (`:302`); pressor prob capped 0.95 (`:414`). Temp clamps 35.4–38.0 (afebrile) / 36.0–40.8 (`:324-326`); HR 82–156, RR 20–38 (`:328-329`); SBP 72–126 depending on branch, DBP 40–82 (`:331-345`); SpO2 84–99 (`:348`); WBC 3–24, creatinine 0.5–5.5, glucose 70–430, lactate 0.8–8.0 (`:357-383`). Glucose floor jitter +0–4.5 to avoid exact-floor artifact (`:375-376`). Oliguria threshold `0.5 × weight_kg` (`:185`).

### Limitations (stated in code)
- `:22-27` explicit boundary: values are **synthetic modeled observations**, "not claimed to be region-validated epidemiologic estimates."
- Field `unsupported_fields_emitted_as_null` (bool, `:277,505`) is a self-describing metadata flag.
- Behavior is versioned (v1.0.2/v1.0.3 changelog `:44-63`) documenting prior gaps (missing ventilation_mode for NRB/HFNC; no-pressor-in-shock gap) now addressed.

---

## Module 6 — Oncology (sepsis/oncology sub-package)

**Files:** `hipaasynth/modules/sepsis/oncology/population.py`, `staging.py`, `biomarkers.py`, `comorbidity.py`, `treatment.py`, `outcomes.py`
**Wiring:** No in-package driver imports these (see Global Limitations). Each class takes a shared `random.Random` from a hypothetical caller.

### Determinism / seeding
Every sub-module takes an externally-supplied `rng` (`population.py:38`, `staging.py:38`, etc.); no internal seeding. Determinism depends entirely on the caller passing a seeded RNG.

### Age bounds (traced)
`population.py` — `age_bounds = (18, 90)` (`:59`). Age is site-specific Gaussian, clipped: breast `N(55,8)`, lung `N(68,9)`, colon `N(70,8)`, then `max(18, min(90, int(age)))` (`:47-60, 83-95`). **Enforced bounds: 18–90.** No source is cited for the age means/SDs (default config is hard-coded, `:43-60`).

### Fields & calibration sources (source: mostly **not stated in code**)

| Sub-module | Fields (type) | Source stated? |
|---|---|---|
| population | `site` (breast/lung/colon), `age` (int), `sex` (M/F), `race` (str) | **No source stated** — distributions hard-coded in `_default_config` (`:43-60`) |
| staging | `stage` (I-IV), `t_stage` (T1-T4), `n_stage` (N0-N3), `m_stage` (M0/M1) | **No source stated** — site-specific stage probs hard-coded (`:43-51`) |
| biomarkers | breast: `er_status,pr_status,her2_status,ki67_percent,brca_mutation,subtype`; lung: `never_smoker,egfr_status,alk_status,ros1_status,braf_status,kras_status,pd_l1_tps,histology`; colon: `msi_status,nras_status,cea_at_dx,primary_side` (+her2/kras/braf) | **No source stated** — probabilities inline (`:113-219`) |
| comorbidity | hypertension, cad, prior_mi, heart_failure, hf_type, atrial_fibrillation, prior_stroke, diabetes, diabetes_type, bmi, dyslipidemia, copd, asthma, pack_years, asbestos_exposure, egfr, ckd_stage, on_dialysis, chronic_liver_disease, hepatitis, hepatitis_type, lft_abnormal, charlson_index | **No source stated** — logistic/additive risk formulas inline (`:46-195`) |
| treatment | surgery, surgery_type, radiation, chemotherapy, chemo_regimen, chemo_cycles, targeted_therapy, targeted_agent, immunotherapy, io_agent, io_cycles, endocrine_therapy, endocrine_agent, chemo_toxicity_grade, chemo_discontinuation, io_toxicity_type, io_discontinuation | **No source stated** — guideline-shaped decision tree, no citations (`:50-189`) |
| outcomes | best_response, response_month, progression, progression_month, progression_site, death, death_month | **No source stated** — stage-keyed progression/survival constants inline (`:120-136`) |

### Hard-coded ranges / caps / clamps
Age clip 18–90 (`population.py:92`). ki67 clip 1–95 (`biomarkers.py:128`); PD-L1 TPS 0–100 (`:173-177`); CEA lognormal clip 0.5–5000 (`:211`). Comorbidity caps: cad 0.6, hf 0.4, afib 0.25, stroke 0.2, diabetes 0.35, dyslipidemia 0.7, copd 0.4, asthma 0.15, liver 0.15; eGFR clip 10–150, BMI clip 18–50 (`comorbidity.py:58-170`). Outcomes: progression_month/death_month capped at 60 (`outcomes.py:94,114`); median_os degraded `× 0.9^CCI` (`:108`).

### Limitations
- **No calibration source is stated anywhere** in the oncology sub-package; all distributions are hard-coded literals with no citation comments.
- Not wired into any package pipeline/CLI — orphaned generators.
- Determinism is caller-dependent (no seed owned by the modules).

---

## Module 7 — Diabetes (5-stage pipeline)

**Files:** `population.py`, `glycemic.py`, `complications.py`, `treatments.py`, `outcomes.py` (all under `hipaasynth/modules/diabetes/`)
**Driver:** `hipaasynth/run/diabetes_pipeline.py` (N=1000, MASTER_SEED=42)

### Determinism / seeding
`Anchor(seed=42, config={population, pipeline})` derives a distinct seed per stage — `population, glycemic, complications, treatments, outcomes` — each fed to a fresh `random.Random` (`diabetes_pipeline.py:34-45`). `population.py` seeds its own `random.Random(seed)` (`:43`); the other four take the derived RNG.

### Age bounds (traced)
`population.py:_assign_current_ages` (`:76-90`): `r<0.25 → randint(18,44)`, `r<0.65 → randint(45,64)`, else `randint(65,85)`. **Current-age bounds: 18–85.** `age_at_diagnosis = max(1, current_age − duration)` (`:51`), so **diagnosis age can floor at 1**. Duration for Type 1: `randint(5, min(30, age−5))` or `randint(1, min(15, age−5))`; Type 2: `min(12+(age−50)·0.2, age−18)` ± `randint(-5,5)`, floored at 1 (`:115-144`).

### Fields & calibration sources
Overall calibration statement is prose-level: "Validated against CDC/NHANES diabetes epidemiology" (`population.py:22`). Only two inline literature citations exist in the whole pack, both in treatments:

| Stage | Fields (type) | Source as stated in code | Location |
|---|---|---|---|
| population | patient_id (`DM_#####`), current_age (int), diabetes_type (type1/type2), age_at_diagnosis (int), diabetes_duration_years (int), sex (M/F), race (str) | "Validated against CDC/NHANES" (prose, no per-field citation); Type-1 base prevalence 0.06 hard-coded | `:17-174` |
| glycemic | hba1c_current, glycemic_control, hba1c_target, hba1c_at_diagnosis, hba1c_mean_historical, hba1c_variability_sd, hba1c_tests_per_year, has_cgm, time_in_range_pct, time_below_range_pct, time_above_range_pct, gmi, severe_hypoglycemia_annual, severe_hypoglycemia_history, hypoglycemia_unawareness, documented_hypoglycemia_annual, glucose_cv, glycemic_risk_index | **No source stated**; GMI formula `3.31 + 0.02392·(180−1.8·TIR)` inline | `:66-251` |
| complications | retinopathy_any/severity, diabetic_macular_edema, laser_photocoagulation, anti_vegf_treatment, visual_impairment, legal_blindness, albuminuria_stage, nephropathy_any, egfr_current, ckd_stage, on_dialysis, prior_transplant, neuropathy_any, distal_symmetric_polyneuropathy, autonomic_neuropathy, gastroparesis, foot_ulcer_history, prior_amputation, cvd_any + CAD/MI/stroke/PAD/HF/silent_mi/PCI/CABG, any_complication, microvascular_complications | **No source stated**; exponential risk models inline; race adds risk (Black/Hispanic +0.10 retino, Black/Native +0.12 nephro) | `:94-365` |
| treatments | on_metformin, on_sulfonylurea, on_dpp4_inhibitor, on_glp1_agonist, on_sglt2_inhibitor, on_insulin, insulin_type, on_cgm, number_of_oral_agents, number_of_injectables, years_to_intensification, basal/bolus/total_daily_insulin, insulin_units_per_kg, total_diabetes_meds, medication_adherence_estimate, treatment_satisfaction_score | "ADA Standards of Care 2024, Section 9"; "UKPDS … Turner RC JAMA 1999;281:2005-2012"; "Casagrande SS Diabetes Care 2018;41:2020-2028" | `:172-278` |
| outcomes | follow_up_months, censored, retinopathy_progressed, ckd_progressed/stage_at_5yr, dialysis_initiated, foot_complication_new, amputation_new, mi_new, stroke_new, hf_hospitalization_new, death/date/cause, endo_visits_annual, pc_visits_annual, hospitalizations_5yr, ed_visits_5yr, total_costs_5yr, annual_cost_estimate, eq5d_index, diabetes_distress_score | **No source stated**; 5-year horizon, cost/QoL weights inline | `:44-303` |

### Hard-coded ranges / caps / clamps
HbA1c clip 5.0–14.0 (`glycemic.py:90`); at-diagnosis 5.5–16.0 (`:123`); historical 6.0–13.0 (`:131`); glucose_cv 15–60 (`:243`); TIR 30–95 (`:176`). eGFR clip 10–150 (`complications.py:206`). Insulin dosing uses a **fixed weight proxy** `weight = bmi × 1.65²` (`treatments.py:227`) — height is assumed 1.65 m for everyone. Cost clip 5000–500000 (`outcomes.py:267`); EQ-5D clip 0.3–1.0 (`:292`); distress 0–12 (`:302`); follow-up default 60 months (`:48`).

### Limitations (baked-in assumptions a clinician should know)
- **complications/treatments read fields the population/glycemic stages never generate.** `complications.py` calls `p.get('systolic_bp', 130)`, `p.get('smoking_status','never')`, `p.get('ldl_cholesterol',100)`, `p.get('bmi',25)` — none of these are produced upstream in the diabetes pipeline, so retinopathy/nephropathy/neuropathy/CVD **always use the fallback constants** (BP=130, non-smoker, LDL=100, BMI=25). Verify at `complications.py:98,167,262-299` and `treatments.py:117,131`.
- Insulin dose assumes a **constant 1.65 m height** for all patients (`treatments.py:227`).
- Per-field calibration sources are absent except the three treatment citations; the pack's validation is prose-level ("Validated against CDC/NHANES").

---

## Module 8 — Cardiology (risk scores + medications)

**Files:** `hipaasynth/modules/cardiology/risk_scores.py`, `medications.py`
**Wiring:** Not used by any package pipeline; referenced only by `tests/test_seismometer_adapter.py`.

### Determinism / seeding
`CardioRiskScores` takes `n` only, no RNG — its scores are deterministic functions of the input `data` dict (`risk_scores.py:37`). `CardioMedications` takes `(n, rng)` and uses `rng.random()`/`rng.randrange` (`medications.py:30`). Neither owns a seed; determinism is caller-supplied.

### Age bounds (traced)
Neither module generates age. Both consume `data["age"][i]` supplied by the caller (`risk_scores.py:55`, `medications.py:38`). **No age bounds enforced in these modules.** Age thresholds used: ASCVD `age<40` down-weights risk (`:76-77`); CHA₂DS₂ ≥65/≥75; HAS-BLED >65; HEART >50/≥45/≥65.

### Fields & calibration sources
`risk_scores.py` (`:40-48`) returns: `ascvd_10yr` (float), `ascvd_category` (low/borderline/intermediate/high), `cha2ds2_vasc` (int), `has_bled` (int), `heart_score` (int).
- Source as stated: ASCVD "simplified logistic model calibrated to PCE distributions … ACC/AHA 2013 PCE-like distribution" with explicit target bands (low <5% ~25-30%, borderline 5-7.5% ~15-20%, intermediate 7.5-20% ~30-35%, high >20% ~15-20%) (`:26-31`). The logit coefficients are hand-set (`:63-72`), **not the published PCE equation.**
- CHA₂DS₂-VASc, HAS-BLED, HEART: **no source cited**; HAS-BLED implements only 2 of the usual components (SBP>160, age>65) (`:126-140`), and HEART is a partial reconstruction (`:142-175`).

`medications.py` (`:158-179`) returns: `on_antihypertensive`+`htn_meds`, `on_statin`+`statin_intensity`, `on_anticoagulant`+`anticoagulant_type`, `on_antiplatelet`+`antiplatelet_type`, `on_hf_therapy`+`hf_meds`, `on_diabetes_meds`+`diabetes_meds`, `total_meds`. **No calibration source stated**; prescribing is a guideline-shaped probabilistic decision tree (`:50-152`).

### Hard-coded ranges / caps / clamps
ASCVD risk clamped 0.005–0.75 (`risk_scores.py:79`); `age<40` multiplier `max(0.1,(age−20)/20)` (`:76-77`). All medication probabilities are hard-coded literals (e.g., HTN treatment 0.7, DOAC vs warfarin 0.8, `medications.py:51,91`).

### Limitations
- ASCVD is a **simplified logistic surrogate**, not the ACC/AHA Pooled Cohort Equations (stated `:22`).
- HAS-BLED and HEART are **partial** implementations (missing components).
- No calibration source for the medication module.
- Orphaned from the main engine (test-only usage).

---

## Module 9 — DMD (Duchenne Muscular Dystrophy)

**File:** `hipaasynth/modules/dmd/dmd.py`

### Determinism / seeding
`DeterministicRNG(seed)` wraps `random.Random(seed)` and tracks a `call_count`; `fingerprint()` = SHA-256 of `"{seed}:{call_count}"` (`:69-103`). Default seed 42 (`:112`).

### Age bounds (traced)
`current_age = clip(normal(12, 6), 2, 40)` → **2–40 years** (`:147`). `diagnosis_age = clip(normal(4.5,1.2), 1, 10)` → **1–10** (`:149-153`). `ambulation_loss_age` clip 6–20 (`:190`); `predicted_survival_age` clip 18–50 (`:211`). All patients `sex='male'` (X-linked, `:146`).

### Fields & calibration sources
Fields (`:127-228`): patient_id (`DMD-n`), synthetic, disclaimer, sex, current_age, diagnosis_age, disease_duration, mutation_type (deletion/duplication/point_mutation), on_steroids (bool), ambulation_loss_age, non_ambulatory (bool), cardiomyopathy (bool), requires_ventilation (bool), predicted_survival_age, ck_level (int).
**Calibration source: not specified in code** — `DMDParameters` are hard-coded dataclass defaults (deletion 0.65 / duplication 0.10 / point 0.25; steroid ambulation gain 3.0 yr; survival gain 7.5 yr; CK diagnostic mean 15000; ventilation threshold 25 yr) with no citations (`:39-63`). The docstring cites no registries.

### Hard-coded ranges / caps / clamps
CK level clip 200–50000 with `(1 − 0.15)^years` decline (`:226-228`). Steroid probability fixed 0.7 (`:179`). Base survival 28 yr (`:206`). Cardiac onset `N(18,3)`, ventilation threshold 25 (`:53-54,194-203`).

### Limitations
- **No calibration source of any kind** is stated (no registry, no literature).
- Cardiomyopathy and ventilation are deterministic age thresholds, not risk models.
- Steroid effect is a flat additive constant.

---

## Module 10 — Fabry disease

**File:** `hipaasynth/modules/fabry/fabry.py`
**Version string:** `0.1.0-FABRY` (`:21`)

### Determinism / seeding
`FabryCohortGenerator(seed=42, treatment_rate=0.55)` seeds `random.Random(seed)` and tracks `call_count` via `_tracked_*` wrappers; `fingerprint()` = SHA-256 `"{seed}:{call_count}"` (`:118-156`). A `_cohort_checksum` over patient key fields is also provided (`:390-395`).

### Age bounds (traced)
No single "age" field. `age_at_onset_years` by phenotype (`:250-259`): classic `max(2.0, N(6,2.5))`; late_cardiac `max(20, N(40,8))`; late_renal `max(18, N(35,7))`; asymptomatic `uniform(30,60)`. `age_at_death_or_censor_years = onset + survival`, where survival is **censored at 85** (`if base_survival > 85−onset: return 85−onset, "censored"`, `:384-385`). **Effective maximum modeled age ≈ 85.**

### Fields & calibration sources
Docstring calibration statement (`:20-21`): "Calibration: Fabry Registry, FOS (Fabry Outcome Survey), FDA label." No per-field citations. Fields (`:215-235` + organ/biomarker updates): patient_id, synthetic, disclaimer, sex (M/F, 55% M `:172`), phenotype (classic/late_cardiac/late_renal/asymptomatic), mutation_type (missense/nonsense/splice/rearrangement), specific_mutation (str; hotspots p.N215S, p.R301Q, p.G328R, p.A143T `:39`), age_at_onset_years, age_at_diagnosis_years, diagnosis_delay_years, on_enzyme_replacement_therapy (bool), ert_type, age_at_death_or_censor_years, vital_status (deceased/censored), rng_calls; organ block (`:269-328`): has_neuropathic_pain, age_pain_onset_years, pain_severity_0_10, pain_episodes_per_month, has_left_ventricular_hypertrophy, age_lvh_onset_years, ivs_thickness_mm, has_proteinuria, age_proteinuria_onset_years, progressed_to_esrd, age_esrd_onset_years, had_stroke_or_tia, age_stroke_tia_years; biomarkers (`:330-358`): alpha_galactosidase_a_percent_normal, lyso_gb3_ng_ml, urinary_gb3_present (bool).
**Source: "not specified in code" at field level** — all rates are `FabryParameters` dataclass literals (`:42-91`).

### Hard-coded ranges / caps / clamps
Phenotype rates differ by sex (male classic 0.60 vs female 0.10, `:44-52`). ERT effects: ESRD delay +15 yr, survival +10 yr, cardiac stabilization 0.80 (`:74-76`). Pain severity clamp 1–10 (`:276`). IVS thickness `N(15,3)` if LVH else `N(9,1)` (`:294`). Lyso-Gb3 halved on ERT (`:352`); urinary_gb3 threshold >10 (`:357`). Stroke base risk 0.25 classic / 0.10 other, ×0.6 for female (`:317-319`).

### Limitations
- Calibration is named at the cohort level (Registry/FOS/FDA label) but **no field-level provenance**.
- Contains deliberate RNG-parity padding calls (`self._rng.random()` discarded when a branch isn't taken, `:197-199, 324-326`) to keep the call stream stable — a determinism device, not a modeled value.
- Version `0.1.0-FABRY` signals pre-release maturity.

---

## Module 11 — SMA (Spinal Muscular Atrophy)

**File:** `hipaasynth/modules/sma/sma.py`
**Version string:** `0.2.0-SMA` (`:21`)

### Determinism / seeding
`SMACohortGenerator(rng=None, seed=None, treatment_rate=0.65)` — accepts an injected RNG or a seed (`:129-136`). `_call_count` reset **per patient** (`:181`). `main()` uses `random.Random(42)` (`:415`).

### Age bounds (traced)
Onset is in **months**, type-specific Gaussian clamped `[0.1, mean+4·std]` (`:175-177`): SMA-I `N(2.5,1.5)`→0.1–8.5; SMA-II `N(10,3)`→0.1–22; SMA-III `N(36,12)`→0.1–84; SMA-IV `N(240,60)`→0.1–480 months. `age_at_death_or_censor_years = (onset+survival)/12`; survival capped at type `max_months` (SMA-I 240, II 600, III 720, IV 600 → censored, `:341-358`). **Effective age ceilings differ by type (up to ~60 yr for SMA-III).**

### Fields & calibration sources
Docstring calibration (`:20-21`): "Calibration: SPINRAZA trials, SMArtCARE registry, FDA label." No per-field citations. Fields (`:321-339`): patient_id (`SMA-######`), synthetic, disclaimer, sma_type (SMA-I…IV), age_at_onset_months, age_at_diagnosis_months, on_disease_modifying_therapy (bool), treatment_start_months, presymptomatic_treatment (bool), dmt_type (nusinersen/None), age_at_death_or_censor_years, vital_status, survival_months_from_onset, rng_calls; genetics (`:311-319`): smn1_status (constant `homozygous_deletion`), smn2_copies (int), smn2_full_length_transcripts, c_859c_t_mutation (bool); motor (`:242-305`): achieved_sitting, age_sitting_months, achieved_walking, age_walking_months, lost_ambulation, age_ambulation_lost_months; respiratory (`:360-394`): needs_ventilation, niv_hours_per_day, tracheostomy, scoliosis, feeding_support.
**Source: "not specified in code" at field level** — all rates are module-level literals: `SMA_TYPE_RATES` `[0.55,0.30,0.14,0.01]` (`:35`), `SMN2_DIST`, `ONSET_PARAMS`, `SURVIVAL_PARAMS` hazards, `VENTILATION_RATES`, `MILESTONE_PARAMS` (`:37-86`).

### Hard-coded ranges / caps / clamps
`NUSINERSEN_SURVIVAL_BENEFIT = 0.50` (SMA-I hazard ×0.5; SMA-II ×0.7) (`:74,347-350`). SMN2 modifier `clip(1 − 0.15·(copies−2), 0.5, 1.2)` (`:208-209`). Treatment-effect multiplier 0.4/0.6/0.8 by timing (`:211-219`). NIV hours clamp 0–24 (`:367-373`). `smn1_status` is a **constant** `homozygous_deletion` (`:315`). `c_859c_t_mutation` fixed 5% (`:318`).

### Limitations
- Field-level calibration sources are **not specified** (only cohort-level names).
- `smn1_status` is a constant placeholder (always `homozygous_deletion`).
- `_estimate_cost` exists (`:396-411`) with hard-coded drug costs (nusinersen 375000, etc.) but is **not called** in `_generate_patient` — dead/aux code.
- SMA-IV motor milestones are constant literals (sits 8.0 mo, walks 14.0 mo, `:298-305`).

---

## Population profiles (`hipaasynth/profiles/*.json`)

Nine JSON profiles override engine demographics for the profile-driven hooks (Stroke, Sepsis). They do **not** define per-field clinical parameters; they set `sex_ratio_female`, `ethnicity_weights`, `age_band_weights`, `rural` flag, and carry a `sources` block plus `calibration_notes`. Example — `nd_tribal_region_a.json`:
- `age_band_weights = [[45,64,0.4],[65,90,0.6]]` (ICU-stroke recalibration, not community median age 28.4 — stated in the profile's `age_distribution` source note).
- `ethnicity_weights`: native 0.847, white 0.121, other 0.032; `sex_ratio_female` 0.502; `rural: true`.
- `sources` cites ACS 2020-2024, IHS Trends 2014-2015, Espey DK Am J Public Health 2014, Brinkworth & Shaw Am J Biol Anthropol 2022, Singer Sepsis-3 2016, and lab floors (Singer 2016 / ADA 2024 / KDIGO 2022 / Grundy 2019).
- `calibration_notes` explicitly flag **documented gaps**: engine "does not yet apply regional comorbidity override" for elevated AI/AN diabetes and HTN burden.

The engine consumes profiles via `age_band_weights` in `generator_demographics.py:80-100` (default US bands `[(18,44,0.45),(45,64,0.33),(65,80,0.22)]`, ACS 2022 [D1]) and via `_resolved_profile` in the hooks (`stroke/observations.py:182`, `sepsis/observations.py:220`).

---

## Global limitations

1. **Two module classes are not wired into any package pipeline.** Cardiology (`modules/cardiology/*`) is referenced only in `tests/test_seismometer_adapter.py`; the Oncology sub-package (`modules/sepsis/oncology/*`) has **no importer** anywhere in the package. Confirm via repo-wide search for `CardioRiskScores`/`StagingModule`/`BiomarkerModule`. These modules produce data only if a caller supplies a seeded RNG and input dicts.

2. **Determinism model is not uniform across modules.** COPD/CHF/OUD use SHA-256 anchor→namespaced RNGs; Stroke/Sepsis are engine-anchor per-patient hooks; Diabetes uses `core.anchor.Anchor` derived seeds; DMD/Fabry/SMA use `random.Random(seed)` with self-tracked call counts; Oncology/Cardiology own no seed at all. A single global seed does **not** reproduce every module the same way.

3. **Engine/schema version strings are consistent.** Records carry `ENGINE_VERSION=1.0.2`, `SCHEMA_VERSION=1.0.0` (`core/config.py:29-30`), and the COPD/CHF/OUD docstrings now state the same 1.0.2 / 1.0.0 (previously stale at 1.0.1 / 1.1.0).

4. **Calibration-source density varies enormously.** COPD/CHF/OUD/Stroke/Sepsis carry dense inline literature citations. DMD, Fabry, SMA, Oncology, Cardiology, and the Diabetes pack carry little to no field-level provenance (cohort-level names or none). Where a field's source is not in the module, this datasheet reports "no source stated."

5. **Cross-stage field dependencies can silently fall back to defaults** (Diabetes pack): downstream stages read `systolic_bp`, `smoking_status`, `ldl_cholesterol`, `bmi` that upstream stages never set, so complication/treatment logic runs on constants. Verify at `diabetes/complications.py:98,167,262-299`.

6. **Dependencies & environment.** All modules are pure Python stdlib (no numpy/pandas) — stated in module docstrings (e.g., `copd_generator.py:32`, `dmd.py:22`). `pyproject.toml` is the packaging source of truth. Distribution/portability claim: "Zero PHI. Zero external dependencies. Pure Python stdlib."

7. **What clients receive vs. what stays internal.** Standalone generators (COPD/CHF/OUD) write JSON + CSV + a SHA-256 manifest via `save_cohort` (`copd_generator.py:508-564`); the run script produces both an n=50 "HuggingFace public" cohort and an n=1000 "calibration" cohort per module (`run_all_modules.py`). Intermediate computed values that are **not** placed in the output row (e.g., several CHF meds/devices computed at `chf_generator.py:479-482`) stay internal and never reach a downstream client.

8. **Modeled ≠ validated (stated in code).** Stroke mRS outcomes and racial-incidence effects, and all Sepsis observations, are explicitly labeled modeled/not-region-validated (`stroke/observations.py:51-61`, `sepsis/observations.py:22-27`).

9. **This datasheet covers the `HipAAsynth` repo modules/profiles only.** The separate `hipaasynth-research` repo (DIF/PSF/care-continuity harnesses) is out of scope for this per-module extraction.

---

## How to verify

| To confirm… | Open these files |
|---|---|
| Which modules/profiles exist and how they're wired | `hipaasynth/modules/run_all_modules.py`; `hipaasynth/pipelines/population_pipeline.py:50-51,193-230`; `hipaasynth/run/diabetes_pipeline.py`; `hipaasynth/profiles/*.json` |
| Engine/schema version & disclaimer actually emitted | `hipaasynth/core/config.py:29-30,58-62` (compare to module docstrings) |
| COPD age bounds, fields, sources, clamps | `hipaasynth/modules/copd/copd_generator.py` (PROFILE `:69-90`; ranges `:92-272`; assembly `:431-498`) |
| CHF cohort framing, NYHA/phenotype, risk scores | `hipaasynth/modules/chf/chf_generator.py` (`:31-42`, `:105-146`, `:264-328`) |
| OUD rurality/MOUD/comorbidity multipliers | `hipaasynth/modules/oud/oud_generator.py` (`:70-243`, `:416-451`) |
| Stroke/Sepsis calibration citations & boundaries | `hipaasynth/modules/stroke/observations.py:23-79`; `hipaasynth/modules/sepsis/observations.py:28-63` |
| Oncology/Cardiology non-wiring & absent sources | `hipaasynth/modules/sepsis/oncology/*.py`; `hipaasynth/modules/cardiology/*.py`; `tests/test_seismometer_adapter.py` |
| Diabetes stage seeding & fallback-default issue | `hipaasynth/run/diabetes_pipeline.py:33-45`; `hipaasynth/modules/diabetes/complications.py:98,167,262-299`; `treatments.py:172-191,227` |
| DMD/Fabry/SMA parameters & determinism | `hipaasynth/modules/dmd/dmd.py:39-63,147-228`; `hipaasynth/modules/fabry/fabry.py:42-91,250-388`; `hipaasynth/modules/sma/sma.py:33-86,175-411` |
| Profile overrides applied to demographics | `hipaasynth/pipelines/generator_demographics.py:64-107`; `hipaasynth/profiles/nd_tribal_region_a.json` |

*Audit commit: `cae9b145e70cc55990e8639aed8a45a8100fd61e` (HipAAsynth), 2026‑07‑11. Generated 2026‑07‑14.*
