# HipAAsynth Calibration Citation Registry

**Purpose:** one row per calibration anchor, with the exact source and where to
look, so each number can be verified independently. This is the companion to
[`../CALIBRATION_SOURCES.md`](../CALIBRATION_SOURCES.md) (the guide) and the
side-by-side chart [`calibration_vs_data.html`](calibration_vs_data.html).

Every metric charted in the calibration report maps to a row below.

## How to verify a row
- **DOI** → open `https://doi.org/<doi>` (resolves to the publisher's page).
- **PubMed** (for journal citations without a DOI in-code) → search
  `https://pubmed.ncbi.nlm.nih.gov/?term=<Author>+<Journal>+<Year>` using the
  first author, journal, and year in the citation.
- **Agency data** → the linked government/registry page; the "where to look"
  column names the table, survey, or field.

## Provenance column key
- **[in-code]** — the citation is written in the module's source (docstring or
  inline comment); grep the file named in the module heading to see it.
- **[canonical]** — the module encodes a well-established epidemiological
  constant without an inline paper; the public source given here is the standard
  reference for that value, provided so you can still verify it.

---

## National data sources (websites)

| Source | URL | Where to look |
|---|---|---|
| CDC NHANES 2017–2020 | https://wwwn.cdc.gov/nchs/nhanes/ | Continuous NHANES demographic, examination (spirometry), and questionnaire data files |
| CDC BRFSS (latest annual) | https://www.cdc.gov/brfss/annual_data/annual_2023.html | Prevalence & Trends Data → select state (ND) and condition (COPD, diabetes, HTN, smoking) |
| CDC PLACES | https://www.cdc.gov/places/ | County-level chronic disease estimates |
| GOLD 2024 Report | https://goldcopd.org/2024-gold-report/ | Chapters 2–3: spirometric staging (GOLD 1–4), pharmacologic management, LTOT |
| US Census ACS 2020–2024 5-yr | https://data.census.gov | Filter North Dakota → tables B01001 (age/sex), B02001 (race), B27001 (insurance), C17002 (poverty) |
| SAMHSA NSDUH 2022 | https://www.samhsa.gov/data/release/2022-national-survey-drug-use-and-health-nsduh-releases | Detailed tables 5.x: opioid use disorder prevalence, treatment receipt |
| CDC Overdose (WONDER) | https://wonder.cdc.gov | Multiple Cause of Death; drug-overdose ICD codes for fentanyl trend |
| CMS HRRP | https://www.cms.gov/medicare/quality/value-based-programs/hospital-readmissions | Heart-failure excess-readmission ratio; national ~22% 30-day HF readmission |
| IHS *Trends in Indian Health* | https://www.ihs.gov/dps/publications/trends2014/ | AI/AN diabetes, cardiovascular, and access statistics |
| ADA Standards of Care 2024 | https://diabetesjournals.org/care/issue/47/Supplement_1 | Section 9 (pharmacologic approaches to glycemic treatment) |
| SMArtCARE registry | https://www.smartcare.de/en/ | SMA natural-history and treatment outcomes |
| TREAT-NMD DMD registry | https://treat-nmd.org/ | Duchenne global registry data & natural-history reports |
| Fabry Registry (Genzyme) | https://www.registrynxt.com/ | Fabry phenotype, ERT, and organ-outcome summaries |

---

## COPD  (`hipaasynth/modules/copd/copd_generator.py`)

| Metric | Target | Source | Verify | Where to look | Prov. |
|---|---|---|---|---|---|
| Overall COPD prevalence context | ~6.2% adults | Wheaton AG et al. *MMWR Morb Mortal Wkly Rep* 2019;68(24):533-538 | https://doi.org/10.15585/mmwr.mm6824a1 | 6.2% age-adjusted BRFSS prevalence (abstract) | [in-code] |
| Age mean (diagnosed) | ~64 | NHANES 2017–2020 | NHANES site | COPD-diagnosed adult age distribution | [in-code] |
| Female proportion | 0.52 | NHANES 2017–2020 | NHANES site | COPD sex distribution | [in-code] |
| GOLD 1/2/3/4 split | 0.20/0.38/0.28/0.14 | Buist AS et al. International variation in the prevalence of COPD (BOLD Study). *Lancet* 2007;370(9589):741-750; GOLD 2024 staging framework | https://doi.org/10.1016/S0140-6736(07)61377-4 | BOLD post-bronchodilator spirometry GOLD-grade distribution; GOLD 2024 §2 staging | [in-code] |
| Smoking current/former/never | 0.38/0.47/0.15 | NHANES / CDC BRFSS 2022; GOLD 2024 | NHANES / BRFSS sites | Smoking status among COPD adults | [in-code] |
| Hypertension comorbidity | 0.55 | Chen W et al. *Lancet Respir Med* 2015;3(8):631-639 | https://doi.org/10.1016/S2213-2600(15)00241-6 | CV comorbidity meta-analysis (HTN OR 1.33 vs non-COPD) | [in-code] |
| Type 2 diabetes comorbidity | 0.22 | Mirrakhimov AE. *Cardiovasc Diabetol* 2012;11:132 | https://doi.org/10.1186/1475-2840-11-132 | COPD & glucose metabolism review | [in-code] |
| Depression comorbidity | 0.27 | Yohannes AM et al. *Respir Care* 2014;59(7):1112-1120 | https://doi.org/10.4187/respcare.02458 | Depression/anxiety in COPD | [in-code] |
| GOLD_2 FEV1% mean | 64.5 | GOLD 2024; ATS/ERS GLI-2012 | GOLD site | FEV1% predicted band for GOLD 2 (50–79%) | [in-code] |
| GOLD_4 LTOT rate | 0.42 | Nocturnal Oxygen Therapy Trial Group. *Ann Intern Med* 1980;93(3):391-398; GOLD 2024 | https://doi.org/10.7326/0003-4819-93-3-391 | Landmark LTOT survival trial; GOLD 2024 LTOT recommendation | [in-code] |
| SpO2 mean | ~94.5 | GOLD 2024 Report (oximetry/LTOT thresholds) | https://goldcopd.org/2024-gold-report/ | SpO2 monitoring; LTOT triggered at SpO2 ≤88%, so non-severe stable COPD sits ~92-96% | [canonical] |

Additional in-code comorbidity sources: OSA — Shawon MS et al. *Respir Med*
2017;131:79-90; Pulmonary HTN — Chaouat A et al. *Eur Respir J*
2008;32(5):1371-1385; exacerbations — Hurst JR et al. *NEJM*
2010;363(12):1128-1138 (https://doi.org/10.1056/NEJMoa0909883);
CAT score — Jones PW et al. *ERJ* 2009;34(3):648-654.

---

## CHF  (`hipaasynth/modules/chf/chf_generator.py`)

| Metric | Target | Source | Verify | Where to look | Prov. |
|---|---|---|---|---|---|
| HF prevalence / sex / Black % | age 74, male 0.52, Black 0.20 | Virani SS et al. *Circulation* 2021;143:e254-e743 (AHA stats) | https://doi.org/10.1161/CIR.0000000000000950 | Heart failure statistics chapter | [in-code] |
| HFrEF/HFpEF/HFmrEF | 0.48/0.38/0.14 | McDonagh TA et al. *Eur Heart J* 2021;42(36):3599-3726 (ESC) | https://doi.org/10.1093/eurheartj/ehab368 | HF phenotype definitions & epidemiology | [in-code] |
| NYHA III+IV (hospitalized) | 0.83 | Fonarow GC et al. *JAMA* 2007;297(1):61-70 (OPTIMIZE-HF) | https://doi.org/10.1001/jama.297.1.61 | NYHA class distribution, n=48,612 admissions | [in-code] |
| HFrEF EF mean | ~29% | McDonagh 2021 (ESC HFrEF ≤40%) | https://doi.org/10.1093/eurheartj/ehab368 | HFrEF EF band | [in-code] |
| 30-day readmission risk | ~0.22–0.24 | CMS HRRP; Dharmarajan K et al. *JAMA* 2013;309(4):355-363 | https://doi.org/10.1001/jama.2012.216476 | 30-day HF readmission rate | [in-code] |
| NYHA III BNP mean | 400–900 pg/mL | Maisel AS et al. *NEJM* 2002;347(3):161-167 | https://doi.org/10.1056/NEJMoa020233 | BNP by NYHA class (Breathing Not Properly) | [in-code] |
| Sodium mean / hyponatremia | 136–140 | Gheorghiade M et al. *Arch Intern Med* 2007;167(18):1998-2005 | https://doi.org/10.1001/archinte.167.18.1998 | Admission serum sodium in HF | [in-code] |
| CKD comorbidity | 0.48 | Ronco C et al. *J Am Coll Cardiol* 2008;52(19):1527-1539 | https://doi.org/10.1016/j.jacc.2008.07.051 | Cardiorenal syndrome prevalence | [in-code] |
| HFrEF beta-blocker (GDMT) | 0.82 | Heidenreich PA et al. *Circulation* 2022;145(18):e895-e1032 | https://doi.org/10.1161/CIR.0000000000001063 | 2022 AHA/ACC/HFSA HF guideline, GDMT | [in-code] |

---

## OUD  (`hipaasynth/modules/oud/oud_generator.py`)

| Metric | Target | Source | Verify | Where to look | Prov. |
|---|---|---|---|---|---|
| OUD prevalence context | ~2.7M adults | SAMHSA NSDUH 2022 | NSDUH releases | Detailed table 5.x, opioid use disorder | [in-code] |
| Rural/frontier proportion | 0.33 | Mack KA et al. *MMWR* 2017;66(19):506-512 | PubMed: Mack MMWR 2017 | Rural-urban overdose/OUD disparity | [in-code] |
| Illicit fentanyl dominance | 0.35 | Cicero TJ et al. *NEJM* 2014;371(22):2063-2066 | https://doi.org/10.1056/NEJMc1406300 | Shift to fentanyl/heroin | [in-code] |
| Benzo co-use on UDS | 0.38 | Jones CM et al. *JAMA Psychiatry* 2022;79(5):512-520 | https://doi.org/10.1001/jamapsychiatry.2022.0246 | Benzodiazepine co-involvement | [in-code] |
| No-MOUD treatment gap | 0.78 | Larochelle MR et al. *Ann Intern Med* 2018;169(3):137-145 | https://doi.org/10.7326/M17-3107 | MOUD receipt after overdose | [in-code] |
| Frontier naloxone/buprenorphine access | low (0.18) | Andrilla CHA et al. *J Rural Health* 2019;35(1):8-25 | https://doi.org/10.1111/jrh.12307 | Rural buprenorphine prescriber geography | [in-code] |
| HCV comorbidity | ~0.38 | White AM et al. *Drug Alcohol Depend* 2021;227:109002 | https://doi.org/10.1016/j.drugalcdep.2021.109002 | HCV in people who inject drugs | [in-code] |
| Prior-authorization/rural prescribing | context | Rando J et al. *J Rural Health* 2021;37(3):526-534 | PubMed: Rando J Rural Health 2021 | Rural OUD treatment barriers | [in-code] |

Severity, IV use, depression, tobacco, PTSD, AUD, Medicaid anchors calibrate to
SAMHSA NSDUH 2022 and ASAM Clinical Practice Guideline 2023 (in-code module
header). DSM-5-TR criteria define OUD severity strata.

---

## Stroke  (`hipaasynth/modules/stroke/observations.py`)

Intrinsic anchors (validated against a clean base — see notes in
`calibration_validator_ext.py`).

| Metric | Target | Source | Verify | Where to look | Prov. |
|---|---|---|---|---|---|
| Ischemic proportion | 0.84 | Tsao CW et al. (AHA) *Circulation* 2023;147(8):e93-e621 | https://doi.org/10.1161/CIR.0000000000001123 | Stroke subtype frequencies (ischemic ~87% of strokes) | [in-code] |
| Hemorrhagic proportion | 0.13 | Tsao CW et al. (AHA) *Circulation* 2023;147(8):e93-e621 | https://doi.org/10.1161/CIR.0000000000001123 | Ischemic vs hemorrhagic split (~13% hemorrhagic) | [in-code] |
| TIA proportion | 0.05 | Modeled (acute presentation subtype) | — | Module docstring, TIA carve-out | [in-code] |
| NIHSS mild category | 0.50 | Winder K et al. *J Neuroimaging* 2023;33(4):575-581 (median NIHSS 4) | https://doi.org/10.1111/jon.13110 | NIHSS median 4 (IQR 2–10), n=809 | [in-code] |
| Atrial fibrillation | 0.28 | Winder K et al. *J Neuroimaging* 2023;33(4):575-581 | https://doi.org/10.1111/jon.13110 | AF 28% in ischemic stroke | [in-code] |
| Onset-to-door median | 83 min | Bergh E et al. *Acta Neurol Scand* 2022;146(1):61-69 | https://doi.org/10.1111/ane.13622 | Onset-to-door median 83 min | [in-code] |

Also cited in-code (used in tPA logic / severity, not charted as pass/fail —
see **Documented gaps**): Feng L et al. *J Clin Lab Anal* 2018;33(1)
(https://doi.org/10.1002/jcla.22629, NIHSS severity bands); Havenon A et al.
*Ann Neurol* 2023;93(6):1106-1116 (https://doi.org/10.1002/ana.26621);
Duan C et al. *CNS Neurosci Ther* 2023;29(8):2308-2317
(https://doi.org/10.1111/cns.14164, mRS 0–1 81% in minor stroke);
Broderick JP et al. *Stroke* 2010;41(9):2108-2129
(https://doi.org/10.1161/STROKEAHA.107.183689, ICH severity); AHA/ASA
Guidelines *Stroke* 2019 (tPA 4.5h window, DTN <60 min).

---

## Diabetes  (`hipaasynth/modules/diabetes/`)

| Metric | Target | Source | Verify | Where to look | Prov. |
|---|---|---|---|---|---|
| Type 1 vs Type 2 split | 0.06 / 0.94 | CDC National Diabetes Statistics Report; NHANES | https://www.cdc.gov/diabetes/php/data-research/ | ~5–10% of diagnosed diabetes is Type 1 | [in-code] |
| Race distribution | W 0.55 / B 0.18 / H 0.15 / A 0.08 / O 0.04 | CDC/NHANES diabetes epidemiology | https://www.cdc.gov/diabetes/php/data-research/ | Diagnosed-diabetes prevalence by race/ethnicity | [in-code] |
| Current-age mean | 50–60 | CDC/NHANES age distribution of diagnosed diabetes | NHANES site | Age-at-interview among diabetic adults | [canonical] |
| Insulin use in treated T2DM | ~26% | Casagrande SS et al. *Diabetes Care* 2018;41:2020-2028 | https://doi.org/10.2337/dc18-0287 | NHANES 2013–2016 insulin use | [in-code] |
| T2DM insulin progression | ~50% by 10 yr | Turner RC et al. *JAMA* 1999;281:2005-2012 (UKPDS) | https://doi.org/10.1001/jama.281.21.2005 | UKPDS glycemic-control progression | [in-code] |

---

## SMA  (`hipaasynth/modules/sma/sma.py`)

Module header cites: SPINRAZA (nusinersen) trials, SMArtCARE registry, FDA label.

| Metric | Target | Source | Verify | Where to look | Prov. |
|---|---|---|---|---|---|
| Type I/II/III/IV split | 0.55/0.30/0.14/0.01 | Verhaart IEC et al. *Orphanet J Rare Dis* 2017;12:124 | https://doi.org/10.1186/s13023-017-0671-8 | SMA type frequency at diagnosis | [canonical] |
| On DMT (nusinersen) | 0.65 | Finkel RS et al. *NEJM* 2017;377:1723-1732 (ENDEAR); SMArtCARE | https://doi.org/10.1056/NEJMoa1702752 | Treatment uptake / trial population | [canonical] |
| SMA-II scoliosis | 0.60 | Natural history (SMArtCARE); Mercuri E et al. *Neuromuscul Disord* 2018;28(2):103-115 | https://doi.org/10.1016/j.nmd.2017.11.005 | Orthopedic complications by type | [canonical] |
| SMA-I feeding support | 0.85 | SMA-I natural history; Finkel RS et al. *Neurology* 2014;83(9):810-817 | https://doi.org/10.1212/WNL.0000000000000741 | Bulbar/feeding involvement in Type I | [canonical] |

SMN2 copy-number distributions by type (`SMN2_DIST`) follow standard
genotype-phenotype correlation (Calucho M et al. *Neuromuscul Disord*
2018;28(3):208-215, https://doi.org/10.1016/j.nmd.2018.01.003) — [canonical].

---

## DMD  (`hipaasynth/modules/dmd/dmd.py`)

Parameters encode standard Duchenne natural history (TREAT-NMD / CINRG).

| Metric | Target | Source | Verify | Where to look | Prov. |
|---|---|---|---|---|---|
| Male proportion (X-linked) | 1.0 | Mendelian X-linked recessive inheritance | — | Established genetics | [canonical] |
| Deletion / duplication / point | 0.65/0.10/0.25 | Bladen CL et al. *Hum Mutat* 2015;36(4):395-402 (TREAT-NMD DMD variations) | https://doi.org/10.1002/humu.22758 | Dystrophin mutation-type frequencies | [canonical] |
| On corticosteroids | 0.70 | Bushby K et al. *Lancet Neurol* 2010;9(1):77-93 (DMD care) | https://doi.org/10.1016/S1474-4422(09)70271-6 | Glucocorticoid standard of care | [canonical] |
| Diagnosis age mean | 4.5 yr | Bushby K et al. *Lancet Neurol* 2010;9(1):77-93 | https://doi.org/10.1016/S1474-4422(09)70271-6 | Mean age at DMD diagnosis | [canonical] |
| Ambulation-loss age mean | 11–14 yr | McDonald CM et al. *Lancet* 2018;391(10119):451-461 (CINRG) | https://doi.org/10.1016/S0140-6736(17)32160-8 | Loss of ambulation, steroid vs non-steroid | [canonical] |

---

## Fabry  (`hipaasynth/modules/fabry/fabry.py`)

Module header cites: Fabry Registry, FOS (Fabry Outcome Survey), FDA label.

| Metric | Target | Source | Verify | Where to look | Prov. |
|---|---|---|---|---|---|
| Male classic phenotype | 0.60 | Eng CM et al. *J Inherit Metab Dis* 2007;30(2):184-192 (Fabry Registry) | https://doi.org/10.1007/s10545-007-0521-2 | Male classic vs later-onset phenotype | [canonical] |
| Female late-cardiac phenotype | 0.35 | Wilcox WR et al. *Mol Genet Metab* 2008;93(2):112-128 (Fabry Registry, females) | https://doi.org/10.1016/j.ymgme.2007.09.013 | Female phenotype heterogeneity | [canonical] |
| Missense / nonsense split | 0.60 / 0.15 | Fabry mutation databases (GLA variants) | https://doi.org/10.1007/s10545-007-0521-2 | GLA mutation-type frequencies | [canonical] |
| On enzyme replacement therapy | 0.55 | Fabry Registry / FOS treatment uptake | https://www.registrynxt.com/ | ERT receipt among registry patients | [canonical] |
| Stroke/TIA history | ~0.15 | Sims K et al. *Stroke* 2009;40(3):788-794 (Fabry Registry) | https://doi.org/10.1161/STROKEAHA.108.526293 | Cerebrovascular events in Fabry | [canonical] |

---

## Oncology  (`hipaasynth/modules/sepsis/oncology/`)

Six sub-modules (`population`, `staging`, `biomarkers`, `comorbidity`,
`treatment`, `outcomes`) driven deterministically by
`oncology/cohort.py::OncologyCohortGenerator`. Covers three primary sites
(breast, lung, colon). Stage rows use the SEER summary-stage grouping
(localized ≈ I/II, regional ≈ III, distant ≈ stage IV / M1); the charted
metric is the distant (stage IV) fraction, which maps cleanly to M1.

| Metric | Target | Source | Verify | Where to look | Prov. |
|---|---|---|---|---|---|
| Breast site share (of 3 sites) | 0.44 | Siegel RL et al. *CA Cancer J Clin* 2024;74(1):12-49 | https://doi.org/10.3322/caac.21820 | US annual incidence (breast/lung/colorectal) normalized to 3 sites | [in-code] |
| Lung site share (of 3 sites) | 0.34 | Siegel RL et al. *CA Cancer J Clin* 2024;74(1):12-49 | https://doi.org/10.3322/caac.21820 | US annual incidence, normalized | [in-code] |
| Colon site share (of 3 sites) | 0.22 | Siegel RL et al. *CA Cancer J Clin* 2024;74(1):12-49 | https://doi.org/10.3322/caac.21820 | US annual incidence, normalized | [in-code] |
| Breast metastatic (stage IV) at dx | 0.06 | SEER Cancer Stat Facts — Female Breast | https://seer.cancer.gov/statfacts/html/breast.html | Stage distribution: distant 6% | [in-code] |
| Lung metastatic (stage IV) at dx | 0.57 | SEER Cancer Stat Facts — Lung & Bronchus | https://seer.cancer.gov/statfacts/html/lungb.html | Stage distribution: distant 57% | [in-code] |
| Colon metastatic (stage IV) at dx | 0.24 | SEER Cancer Stat Facts — Colorectal | https://seer.cancer.gov/statfacts/html/colorect.html | Stage distribution: distant ~24% | [in-code] |
| Breast overall 5-yr survival | 0.90 | SEER Cancer Stat Facts — Female Breast (localized ~99% / regional ~86% / distant ~30%) | https://seer.cancer.gov/statfacts/html/breast.html | 5-yr relative survival by stage | [in-code] |
| Lung overall 5-yr survival | 0.27 | SEER / ACS non-small-cell lung (localized ~65% / regional ~37% / distant ~9%) | https://seer.cancer.gov/statfacts/html/lungb.html | 5-yr relative survival by stage | [in-code] |
| Colon overall 5-yr survival | 0.62 | O'Connell JB et al. *J Natl Cancer Inst* 2004;96(19):1420-1425 (SEER AJCC 6th; I 93.2% / II ~83% / III ~60% / IV 8.1%; overall 65.2%) | https://doi.org/10.1093/jnci/djh275 | Stage-specific 5-yr survival, n=119,363 | [in-code] |
| Breast HR+/HER2- (luminal) | 0.73 | Howlader N et al. *J Natl Cancer Inst* 2014;106(5):dju055 (SEER) | https://doi.org/10.1093/jnci/dju055 | Joint HR/HER2 subtype incidence (HR+/HER2- 72.7%) | [in-code] |
| Breast triple-negative | 0.12 | Howlader N et al. *J Natl Cancer Inst* 2014;106(5):dju055 (SEER) | https://doi.org/10.1093/jnci/dju055 | Triple-negative 12.2% | [in-code] |
| Colon MSI-H | 0.15 | Boland CR, Goel A. *Gastroenterology* 2010;138(6):2073-2087 | https://doi.org/10.1053/j.gastro.2009.12.064 | MSI-H ~15% of sporadic CRC (right-sided enriched) | [in-code] |
| Lung KRAS+ | 0.25 | Kris MG et al. *JAMA* 2014;311(19):1998-2006 (Lung Cancer Mutation Consortium) | https://doi.org/10.1001/jama.2014.3741 | KRAS 25% of lung adenocarcinoma | [in-code] |

Additional in-code biomarker sources (modeled, not charted as pass/fail — see
**Documented gaps**): breast ER/PR/HER2 marginals and BRCA (Howlader 2014,
above); lung EGFR/ALK/BRAF driver frequencies conditioned on smoking status and
ancestry (Kris MG et al. *JAMA* 2014, https://doi.org/10.1001/jama.2014.3741);
colon BRAF V600E in MSI-H (Lochhead P et al. *J Natl Cancer Inst*
2013;105(15):1151-1156, https://doi.org/10.1093/jnci/djt173) and KRAS ~40% of
CRC (Neumann J et al. *Pathol Res Pract* 2009;205(12):858-862). Treatment
selection (surgery/chemo/targeted/IO by stage and biomarker) follows NCCN-style
standard-of-care logic and is not asserted as a calibrated prevalence.

---

## Cardiology  (`hipaasynth/modules/cardiology/`)

`cardiology/` shipped two utility classes (`risk_scores.py`, `medications.py`)
but no population generator. `cardiology/cohort.py::CardiologyCohortGenerator`
supplies that front half: a **CV-risk-enriched adult clinic population** (ages
40–79, the PCE applicability window; risk factors correlated by a
cardiometabolic-burden latent) that then calls the risk-score and medication
utilities as sub-components. Because the cohort is deliberately CV-enriched (not
a general NHANES sample), comorbidity prevalences run at clinic — not
population — levels, the same framing CHF uses for its hospitalized cohort.

| Metric | Target | Source | Verify | Where to look | Prov. |
|---|---|---|---|---|---|
| ASCVD 10-yr low risk (<5%) | 0.28 | Goff DC et al. *Circulation* 2014;129(25 Suppl 2):S49-S73 (ACC/AHA Pooled Cohort Equations) | https://doi.org/10.1161/01.cir.0000437741.48606.98 | PCE risk-tier thresholds; low tail | [in-code] |
| ASCVD 10-yr high risk (≥20%) | 0.16 | Goff DC et al. *Circulation* 2014;129(25 Suppl 2):S49-S73 | https://doi.org/10.1161/01.cir.0000437741.48606.98 | PCE risk-tier thresholds; high tail | [in-code] |
| Statin use among eligible | 0.55 | Salami JA et al. *JAMA Cardiol* 2017;2(1):56-65 | https://doi.org/10.1001/jamacardio.2016.4700 | Statin use in guideline-eligible US adults (~55.5%) | [in-code] |
| Anticoagulation in AF (CHA₂DS₂-VASc ≥2) | 0.70 | Freedman B et al. *JAMA Cardiol* 2017;2(4):442-451 | https://doi.org/10.1001/jamacardio.2016.5975 | Guideline-indicated OAC in AF; ~70% treated | [in-code] |
| Current smoker | 0.14 | CDC MMWR 2023; AHA Heart Disease & Stroke Statistics 2023 | https://www.cdc.gov/tobacco/ | Adult cigarette smoking prevalence | [in-code] |
| Diabetes prevalence | 0.15 | CDC National Diabetes Statistics Report 2022 | https://www.cdc.gov/diabetes/php/data-research/ | Diagnosed diabetes in adults (~13-15%) | [in-code] |
| Hypertension prevalence | 0.50 | AHA Heart Disease & Stroke Statistics 2023 (2017 ACC/AHA threshold) | https://doi.org/10.1161/CIR.0000000000001123 | Adult hypertension prevalence (~48%) | [in-code] |

Additional in-code sources: lipid means — Carroll MD et al. *NCHS Data Brief*
2017 (No. 290); atrial-fibrillation prevalence — Go AS et al. *JAMA*
2001;285:2370-2375 (ATRIA). The CHA₂DS₂-VASc, HAS-BLED, and HEART scores follow
their original derivation rules and are computed, not charted as prevalence.

---

## ND Tribal Region Profiles  (`hipaasynth/profiles/nd_tribal_region_*.json`)

These anchors carry DOIs directly in each profile's `sources` block.

| Anchor | Value | Source | Verify | Prov. |
|---|---|---|---|---|
| AI/AN diabetes prevalence | 13.6% | Dai J et al. *Diabetes Obes Metab* 2024;27(1):328-337 | https://doi.org/10.1111/dom.16021 | [in-code] |
| AI/AN hypertension (ND/SD) | ~27% | Jolly SE et al. *J Clin Hypertens* 2015;17(10):812-818 (WATCH) | https://doi.org/10.1111/jch.12483 | [in-code] |
| DM+HTN co-occurrence | 77.9% | Walls ML et al. *J Diabetes Res* 2025 | https://doi.org/10.1155/jdr/6591307 | [in-code] |
| CKD association | elevated | Nephrology Mini Orals. *Nephrology* 2021;26(S2):17-32 | https://doi.org/10.1111/nep.13930 | [in-code] |
| Sepsis SDOH mortality | ADI-associated | Ardabili AK et al. *World Med Health Policy* 2025;17(4):823-830 | https://doi.org/10.1002/wmh3.70043 | [in-code] |
| Sepsis-3 definition | — | Singer M et al. *JAMA* 2016;315(8):801-810 | https://doi.org/10.1001/jama.2016.0287 | [in-code] |
| Afebrile elderly infection | — | Gavazzi G, Krause KH. *Lancet Infect Dis* 2002;2(11):659-666 | https://doi.org/10.1016/S1473-3099(02)00437-1 | [in-code] |
| IHS nurse vacancy | 23–40% | Brockie T et al. *J Clin Nurs* 2021;32(3-4):610-624 | https://doi.org/10.1111/jocn.15801 | [in-code] |

---

## Sepsis  (`hipaasynth/modules/sepsis/observations.py`)

Sepsis is a **physiological observation generator**, not a prevalence model, so
it has no population-prevalence rows in the calibration chart. Its clinical
targets are sourced in-code:

| Anchor | Source | Verify |
|---|---|---|
| Sepsis-3 organ-dysfunction definition | Singer M et al. *JAMA* 2016;315(8):801-810 | https://doi.org/10.1001/jama.2016.0287 |
| Initial fluid 30 mL/kg; vasopressor targets | Surviving Sepsis Campaign 2021. *Crit Care Med* 2021;49(3):e299-e347 | https://doi.org/10.1097/CCM.0000000000005337 |
| Infection source / rural | Rhee C et al. *JAMA Intern Med* 2017;177(7):944-951 | https://doi.org/10.1001/jamainternmed.2017.1938 |
| Ventilation modes (LUNG SAFE) | Bellani G et al. *JAMA* 2016;315(8):788-800 | https://doi.org/10.1001/jama.2016.0291 |
| HFNC vs NIV | Frat JP et al. *NEJM* 2015;372(23):2185-2196 | https://doi.org/10.1056/NEJMoa1503326 |
| O2 targets (COPD 88–92%) | O'Driscoll BR et al. *Thorax* 2017;72(Suppl 1):ii1-ii90 | https://doi.org/10.1136/thoraxjnl-2016-209729 |

---

## Documented gaps (not asserted as calibrated)

Honesty about what is *not* yet a passing calibrated row:

- **Stroke tPA-eligibility within 4.5 h window** — literature ~47–53% (Bergh
  2022); the engine realizes ~27% among ischemic patients arriving in-window.
  Under-calls tPA eligibility. Not charted as PASS.
- **Stroke SBP >185 mmHg fraction** — internal-review target 20–25%; engine
  realizes ~15%. Not charted as PASS.
- **Stroke AF/HTN via full pipeline** — the intrinsic overlay is calibrated
  here on a clean base; end-to-end values depend on the base cohort's
  comorbidity mix and should be re-checked at pipeline-integration time.
- **AI/AN regional prevalence** — profiles document AI/AN-specific rates (e.g.
  13.6% diabetes) but the engine still applies US-baseline comorbidity
  generation; regional adjustment is a documented, unimplemented gap
  (`calibration_notes` in each profile JSON).
- **DMD/SMA/Fabry `[canonical]` rows** — the module encodes the value as a
  parameter; the source given is the standard reference for that constant, not
  an inline code citation. Verify the value against the linked source.
- **Oncology lung EGFR/ALK prevalence** — modeled conditionally on smoking
  status and ancestry (Kris 2014). In a mixed-histology, smoker-inclusive
  synthetic cohort the emergent all-lung EGFR+ (~6–12%) is lower than the
  adenocarcinoma-only 17% reported by the Lung Cancer Mutation Consortium, so
  EGFR/ALK are documented here rather than charted as a PASS row; lung KRAS
  (~25%) is charted.
- **Oncology stage mapping** — SEER publishes summary stage
  (localized/regional/distant); the module emits AJCC I–IV. The charted stage
  row is the distant (stage IV / M1) fraction, which maps cleanly; the I/II/III
  split within localized+regional is modeled to reproduce the summary-stage
  totals, not asserted stage-by-stage.
- **Cardiology ASCVD intermediate band** — only the low (<5%) and high (≥20%)
  PCE tails are charted. The intermediate band (7.5–20%, a ~2.7× risk span)
  captures ~40% of the cohort and is descriptive, not asserted as a PASS row.
  Comorbidity prevalences reflect a CV-risk-enriched clinic population, not a
  general-population sample.

---

Last updated: 2026-07-22 by Cody Carlson
