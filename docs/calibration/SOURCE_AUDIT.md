# Calibration source audit

**Date:** 2026-10-30. **Engine:** 1.7.0. **Method:** for each calibrated number
we checked three things:

1. **Code matches the registry.** Generate the cohort and measure it. All 99
   charted rows pass (`python -m hipaasynth.modules.run_all_modules`, then the
   two validators in `hipaasynth/modules/`).
2. **The citation is real.** Every DOI and journal/volume/page in the code and
   docs was looked up in PubMed. PMIDs are given below so anyone can re-check.
3. **The source says what we say it says.** We checked against the abstract or
   an authoritative summary. Where only the full text has the figure and we
   could not read it, the row says **not re-verified**.

This is a check of our own references, not a clinical validation. Clinical
review of the cohorts is a separate step (see `../CLINICAL_REVIEW_PACKET.md`).

## Summary

> Updated by the 2026-10-31 recheck (end of this file): two citations
> rescued, one likely-intended source identified, six confirmed not to exist.

| Result | Rows |
|---|---|
| Confirmed: real source, number matches | 31 |
| Close or supported: real source, number within the reported range | 14 |
| **Wrong value, corrected** | 3 |
| **Wrong value, flagged for clinical review** (changing it changes released module outputs) | 2 |
| **Citation did not exist, removed** (value kept, marked unsourced) | 8 |
| **Citation real but about something else, replaced or flagged** | 10 |
| Citation details wrong (journal, pages, author), corrected | 5 |
| Still unsourced, or figure only in paywalled full text | listed at the end |

The largest problem was not the numbers: most values sit inside published
ranges. It was the references. Eight cited papers do not exist: PubMed has no
article at that journal, volume and page, and the DOI given either fails to
resolve or belongs to an unrelated paper. Nine more pointed at real papers that
do not report the figure. Every one is listed below and removed or replaced in
this release. A value whose source could not be found is now labelled
**unsourced** instead of carrying a reference that would not survive a reader
checking it.

## Corrected in 1.7.0

| What | Was | Now | Evidence |
|---|---|---|---|
| Sepsis hypothermia (< 36 °C) among true cases | 8% drawn (about 7% realized) | **about 15% realized** (17% drawn; SIRS-negative redraws reset some temperatures) | 14.4% bacteraemic sepsis; 13.6% SEPSISPAM; 21% Queensland ICU; 23% Russian ICU (range about 14–23%) |
| Stroke mimics claim in `decision_cohort.py` | "up to 67% of stroke alerts" | **18–40% of stroke-code activations** | 25.3% of 411 code strokes (UCSD 2008); 40.2% of 584 (Lebanon); 18.5% of 314 (India) |
| OUD prevalence context | ~2.7M adults (NSDUH 2022) | **~6.1M people 12+ (NSDUH 2022)** | SAMHSA NSDUH 2022, DSM-5 criteria |

The hypothermia change moves the published-score results by at most one point
(SIRS sensitivity 87% to 88%, now exactly Kaukonen's figure);
`docs/REFERENCE_RESULTS.md` is regenerated.

## Flagged for clinical review (not changed)

| What | Code | Source says | Why not changed here |
|---|---|---|---|
| Fabry stroke/TIA history | ~15% | Sims et al., *Stroke* 2009;40:788 (PMID 19150871): stroke in 6.9% of males and 4.3% of females in the Fabry Registry (n = 2,446) | TIA is not counted in Sims; the module's cohort definition needs a clinician's call; changing it changes every Fabry cohort |
| Pulse-oximeter over-reading for Asian and Hispanic patients | about +0.4 and +0.5 points more than White (tone-driven model) | Fawzy et al., *JAMA Intern Med* 2022;182:730 (PMID 35639368): +1.7 Asian, +1.1 Hispanic, +1.2 Black vs White | The model follows skin tone (the FDA 2025 framing); Black patients match (+1.25), but Asian and Hispanic gaps are understated. Whether to add a non-tone component is a modelling decision for review |

## Citations that did not exist (removed)

The last row is a real article on another topic, counted with the mismatches.

| Where | Cited as | PubMed finding | Value now |
|---|---|---|---|
| `oud_generator.py` route of administration; registry "illicit fentanyl" | Cicero TJ et al. *NEJM* 2014;371(22):2063-2066, doi 10.1056/NEJMc1406300 | No such article. Cicero's 2014 heroin paper is *JAMA Psychiatry* 2014;71(7):821 (PMID 24871348) and does not give these shares | unsourced |
| `oud_generator.py` MOUD status | Jones CM et al. *JAMA Psychiatry* 2022;79(5):512-520 | No article at that volume, issue and pages, and the DOI (…2022.0246) is not in PubMed. Jones did publish two real 2022 *JAMA Psychiatry* papers on pandemic MOUD flexibilities: 79(10):981-992 (PMID 36044198, Medicare telehealth: 12.6% received MOUD) and 79(9):932-934 (PMID 35830198, take-home methadone); the citation was probably a garbled version of one of these, but neither gives the ~18% stated | **replaced**: Dowell D, …, Jones CM, et al. *MMWR* 2024;73(25):567-574 (PMID 38935567), 25.1% of adults needing OUD treatment received MOUD; supports 0.78 without MOUD |
| `oud_generator.py` ED visits; registry HCV | White AM et al. *Drug Alcohol Depend* 2021;227:109002 | No such article; the DOI is a Thai alcohol-screening study (PMID 34488075) | unsourced |
| `copd_generator.py`, `core/dependence.py` depression/anxiety | Yohannes AM et al. *Respir Care* 2014;59(7):1112-1120 | No such article; the DOI is an unrelated case report (PMID 24026185) | **replaced**: Yohannes & Alexopoulos, *Eur Respir Rev* 2014;23:345 (PMID 25176970), depression 26% |
| `diabetes/treatments.py` insulin use | Casagrande SS et al. *Diabetes Care* 2018;41:2020-2028 | No such article; the DOI is a glycaemic-control/infection study (PMID 30104296) | unsourced |
| `sepsis/observations.py`, three profiles: infection source | Rhee C et al. *JAMA Intern Med* 2017;177(7):944-951 | No such article; the DOI is an antibiotic adverse-event study (PMID 28604925) | unsourced |
| `sepsis/observations.py` oliguria | Rhoads CM et al. *Chest* 2019;155(4):744-752 | No such article | unsourced |
| `cardiology/medications.py` AF anticoagulation | Freedman B et al. *JAMA Cardiol* 2017;2(4):442-451 | No such article; that page is a review of AF, diabetes and NOACs (PMID 28122078); the DOI is a bivalirudin STEMI trial (PMID 28273285) | unsourced |
| `oud_generator.py` primary opioid type | Jones CM et al. *Drug Alcohol Depend* 2020;214:108174 | Real article, but about alcohol-use-disorder pharmacotherapy (PMID 32721788) | unsourced |

## Real papers that do not support the figure

| Value | Cited | What the paper is | Action |
|---|---|---|---|
| AI/AN diabetes 13.6% | Dai J et al. *Diabetes Obes Metab* 2024;27:328 (PMID 39434448) | Medication-use trends 2009–2013 | replaced with CDC National Diabetes Statistics Report |
| IHS nurse vacancy 23–40% | Brockie T et al. *J Clin Nurs* 2021;32:610 (PMID 33942940) | Discursive paper on Indigenous nursing leadership | replaced with GAO-18-580 (25%, 13–31% by area) |
| AI/AN hypertension (ND/SD) ~27% | Jolly SE et al. *J Clin Hypertens* 2015;17:812 (PMID 25644577) | Western **Alaska** Native cohort, 30% age-standardized | relabelled; an ND/SD source is still needed |
| COPD hypertension 0.55 | Chen W et al. *Lancet Respir Med* 2015;3:631 | Gives an odds ratio (1.33), not a prevalence | noted; value within cohort ranges |
| COPD diabetes 0.22 | Mirrakhimov AE. *Cardiovasc Diabetol* 2012;11:132 (PMID 23101436) | Narrative review, no pooled prevalence | noted; cohorts report 18.7–21% |
| Stroke NIHSS median 4, AF 28% | Winder K et al. *J Neuroimaging* 2023;33:575 (PMID 37129978) | Post-stroke epilepsy cohort, n = 809; these figures are not in the abstract | not re-verified |
| Stroke onset-to-door 83 min | Bergh E et al. *Acta Neurol Scand* 2022;146:61 (PMID 35445395) | Non-thrombolysis reasons, n = 535 (53% thrombolysed, which does support the tPA figure) | onset-to-door not re-verified |
| NIHSS severity bands | Feng L et al. *J Clin Lab Anal* 2018 (PMID 30069916) | lncRNA biomarker study | noted as weak |
| DM+HTN co-occurrence 77.9% | Walls ML et al. *J Diabetes Res* 2025 (PMID 40313359) | Trial baseline paper (n = 81 adults); figure not in the abstract | not re-verified |

## Citation details corrected

| Was | Now |
|---|---|
| Surviving Sepsis Campaign 2021, *Crit Care Med* 49(3):e299-e347 | Evans L et al. *Crit Care Med* 2021;49(11):e1063-e1143 (PMID 34605781) |
| Mack KA et al. *MMWR* 2017;66(19):506-512 | *MMWR Surveill Summ* 2017;66(19):1-12 (PMID 29049278) |
| Andrilla CHA et al. *J Rural Health* 2019;35(1):8-25 | 2019;35(1):108-112 (PMID 29923637) |
| Broderick JP et al. *Stroke* 2010;41:2108, doi …107.183689 (the 2007 guideline) | Morgenstern LB et al. *Stroke* 2010;41:2108 (PMID 20651276) |
| Shawon MS et al. *Respir Med* 2017;131:79-90 | *Sleep Med Rev* 2017;32:58-68 (PMID 28169105) |

## Confirmed (real source, number matches)

| Module | Value | Source (PMID) |
|---|---|---|
| 7AAST | Occult hypoxaemia 11.7% Black vs 3.6% White | Sjoding, *NEJM* 2020;383:2477 (33326721) |
| 7AAST | SIRS-negative sepsis 12% | Kaukonen, *NEJM* 2015;372:1629 (25776936): 12.1% |
| 7AAST | Monk Skin Tone in FDA guidance | FDA draft guidance on pulse oximeters, January 2025 |
| 7AAST | qSOFA, SIRS, NEWS2, ROSIER comparisons | Fernando 2018 (29404582); Seymour 2016 (26903335); Churpek 2017 (27649072); Nor 2005 (16239179) |
| COPD | Prevalence 6.2% | Wheaton, *MMWR* 2019;68:533 (31220055) |
| COPD | Depression 0.27 | Yohannes & Alexopoulos 2014 (25176970): 26% |
| CHF | 30-day readmission 0.22–0.24 | Dharmarajan, *JAMA* 2013;309:355 (23340637): 24.8% |
| CHF | NYHA III BNP 400–900 | Maisel, *NEJM* 2002;347:161 (12124404): class III 640 pg/mL |
| CHF | Mean age ~74 | Fonarow, *JAMA* 2007;297:61 (17200476): 72.0 |
| CHF | Hyponatraemia context | Gheorghiade, *Arch Intern Med* 2007;167:1998 (17923601): 23.8% ≤ 134 |
| OUD | No MOUD 0.78 | CDC *MMWR* 2024 (38935567); Larochelle 2018 (29913516) |
| OUD | Rural buprenorphine access low | Andrilla 2019 (29923637): 56.3% of rural counties without a provider |
| Stroke | Ischaemic share ~87% | Tsao, *Circulation* 2023;147:e93 (36695182) |
| Stroke | mRS 0–1 at discharge 81% in minor stroke | Duan, *CNS Neurosci Ther* 2023 (36942504): 18.85% disabled at discharge |
| Stroke | tPA mortality benefit at NIHSS ≥ 15 | de Havenon, *Ann Neurol* 2023;93:1106 (36852919) |
| Stroke | Hospital ischaemic ~2/3 | Habibi-Koolaee, *Neurol Res Int* 2018 (30147952) |
| Diabetes | Type 1 share 0.06 | CDC National Diabetes Statistics Report: 5.7% |
| Diabetes | T2DM progression to multiple therapies | UKPDS 49, *JAMA* 1999;281:2005 (10359389) |
| SMA | Type I/II/III split | Verhaart 2017 (28676062): type I ~60%; Lally 2017: 58/29/13 |
| SMA | SMN2 copies by type | Calucho 2018 (29433793) |
| SMA | Nusinersen trial | Finkel, *NEJM* 2017;377:1723 (29091570) |
| DMD | Diagnosis age 4.5 | CINRG natural history: 4.4 (SD 2.1) |
| DMD | Loss of ambulation 11–14 | Median 10.2 GC-naive, 12.0 prednisone, 14.0 deflazacort; McDonald, *Lancet* 2018 (29174484) |
| Fabry | Registry baseline | Eng, *J Inherit Metab Dis* 2007;30:184 (17347915); Wilcox 2008 (18037317) |
| Oncology | Site shares 0.44/0.34/0.22 | Siegel, *CA Cancer J Clin* 2024;74:12 (38230766): 313,510 / 234,580 / 152,810 |
| Oncology | HR+/HER2− 0.73, triple-negative 0.12 | Howlader, *JNCI* 2014 (24777111): 72.7% / 12.2% |
| Oncology | Colorectal distant ~0.24 | SEER Stat Facts: 22–23% |
| Oncology | Colon stage survival | O'Connell, *JNCI* 2004;96:1420 (15467030) |
| Oncology | MSI-H ~15% | Boland & Goel, *Gastroenterology* 2010 (20420947) |
| Tribal | AI/AN diabetes 13.6% | CDC National Diabetes Statistics Report |
| Sepsis | Sepsis-3; HFNC; LUNG SAFE; BTS O2 | Singer 2016 (26903338); Frat 2015 (25981908); Bellani 2016 (26903337); O'Driscoll 2017 (28507176) |

## Close or supported (within the reported range)

| Module | Value | Source says |
|---|---|---|
| 7AAST | Normotensive sepsis 60% | Hypotension at admission in 37.2% of one ED cohort; definitions vary |
| 7AAST | Leukopenia 8% | 6–13% across cohorts |
| COPD | Current smoker 0.38 | About 2 in 5 adults with COPD (BRFSS 2011) |
| COPD | Female 0.52 | Diagnosed COPD more common in women (NHIS, BRFSS) |
| COPD | Diabetes 0.22 | 18.7–21% in cohorts |
| COPD | Hypertension 0.55 | Within cohort ranges (cited source gives an odds ratio) |
| CHF | HFrEF/HFpEF/HFmrEF 0.48/0.38/0.14 | Registries: 41–58% / 25–43% / 16–18% |
| DMD | Deletion/duplication/small 0.65/0.10/0.25 | Bladen 2015 (25604253): 69% / 11% / 20% |
| Cardiology | Statin use 0.55 | Salami, *JAMA Cardiol* 2017 (27842171): 58.1% in established ASCVD |
| Oncology | Lung KRAS 0.25 | Kris, *JAMA* 2014 (24846037), real paper; per-gene figures in full text |
| Tribal | IHS vacancy | GAO-18-580: 25% (13–31%) |
| Tribal | AI/AN hypertension | WATCH (Alaska): 25% crude, 30% age-standardized |
| Stroke | tPA within 4.5 h ~47–53% | Bergh 2022: 53% thrombolysed |
| COPD | Never smoker 0.15 | Secondary sources say about a quarter never smoked; check |

## Still unsourced (needs a real reference or clinical sign-off)

- 7AAST: altered mental status 25%; Monk tone distribution by group; the
  look-alike ranges (already labelled "starting points for clinician sign-off").
- OUD: primary opioid type mix; route of administration; benzodiazepine co-use
  0.38; HCV 0.38; ED-visit ranges.
- Diabetes: insulin use ~26%.
- Cardiology: anticoagulation in AF 0.70.
- Sepsis: infection-source mix; oliguria thresholds.
- CHF: NYHA III+IV 0.83 (OPTIMIZE-HF is real, but the breakdown is not in the abstract).
- COPD: GOLD 1–4 split (the BOLD abstract gives only stage ≥ II prevalence).
- Tribal: CKD (conference abstract). Sepsis social determinants: confirmed in the recheck below (Ardabili, medRxiv 2024).

## Recheck, 2026-10-31 (wider search)

The first pass looked each citation up by its exact journal, volume and first
page, which misses a real paper whose details were mangled. This recheck
searched each author's papers in that journal (and nearby years) instead. The
verdicts are per citation as written; where a real paper is probably what was
meant, it is named so the reference can be repaired rather than dropped.

| Cited as | Exact citation | Closest real paper(s) found (PMID) | Does it support the value? |
|---|---|---|---|
| Jones CM et al. *JAMA Psychiatry* 2022;79(5):512-520 (MOUD ~18%) | does not exist | Jones CM et al. *JAMA Psychiatry* 2022;79(10):981-992 (36044198), Medicare telehealth and MOUD; Jones CM et al. 2022;79(9):932-934 (35830198), take-home methadone | No: 12.6% of Medicare beneficiaries with OUD received MOUD; a Medicare figure, not 18% overall. Replaced with Dowell D, …, Jones CM, et al. *MMWR* 2024 (25.1%) |
| Jones CM et al. *Drug Alcohol Depend* 2020;214:108174 (primary opioid type) | page belongs to another paper | Jones CM et al. *DAD* 2020;214:108169 (32682218), substance-use recovery; **Jiang X, …, Jones CM. *DAD* 2021;229:109160 (34740067), adults using illicitly manufactured fentanyl vs heroin vs prescription opioids** | 108169 no. 109160 is the right kind of source for the fentanyl/heroin/Rx mix; its shares need reading from the full text |
| Cicero TJ et al. *NEJM* 2014;371(22):2063-2066 (route of administration) | does not exist | Cicero's *NEJM* letters: 2012;367:187 (22784140), 2015;373:1789 (26510045), 2016;374:1295 (27028931); *JAMA Psychiatry* 2014;71:821 (24871348) | No route-of-administration shares in any |
| White AM et al. *DAD* 2021;227:109002 (HCV ~38%, ED visits) | does not exist (DOI is another paper) | Wagner K, …, White K, et al. *DAD* 2021;220:108527 (33465605), HCV in young rural PWID in New Mexico | Partly: anti-HCV 60.9%, current infection 44.8% among people who **inject**; supports a high HCV rate in injecting OUD, not 38% of all OUD |
| Yohannes AM et al. *Respir Care* 2014;59(7):1112-1120 (depression 0.27, anxiety 0.19) | does not exist | **Willgoss TG, Yohannes AM. *Respir Care* 2013;58(5):858-866 (22906542)**, anxiety in COPD systematic review; Yohannes & Alexopoulos *Eur Respir Rev* 2014;23:345 (25176970) | Yes: anxiety 13–46% in outpatients (Willgoss 2013) and depression 26% (2014 review). The citation was these two merged; both now cited |
| Casagrande SS et al. *Diabetes Care* 2018;41:2020-2028 (insulin ~26%) | does not exist | Casagrande's only 2016–19 *Diabetes Care* paper is on insurance (29475841) | No match found; stays unsourced |
| Rhee C et al. *JAMA Intern Med* 2017;177(7):944-951 (infection source) | does not exist | Rhee's only *JAMA Intern Med* paper is a 2023 COVID testing letter (37273229); his 2017 sepsis paper is *JAMA* 2017;318:1241 (28903154) | *JAMA* 2017 gives sepsis incidence and trends, not a source-of-infection mix; stays unsourced |
| Rhoads CM et al. *Chest* 2019;155(4):744-752 (oliguria) | does not exist | no Rhoads paper in *Chest* 2019; no *Chest* paper on oliguria in sepsis | stays unsourced |
| Freedman B et al. *JAMA Cardiol* 2017;2(4):442-451 (OAC in AF ~70%) | does not exist | Freedman's *JAMA Cardiol* papers: 2016;1:366 (27438123), 2019;4:91 (30586142), 2020;5:105 (31774461), 2022;7:247 (35076686) | None reports guideline OAC uptake; stays unsourced |
| Ardabili AK et al. *World Med Health Policy* 2025 (sepsis SDOH) | journal not indexed in PubMed | **Ardabili AK et al. medRxiv 2024 (39763570), "Social Determinants of Sepsis Mortality in the United States"**, 4.4 million patients | Yes: higher Area Deprivation Index and lower income associated with higher sepsis mortality. **Real; the earlier "not in PubMed" was wrong** |

Net change from the first pass: two citations are rescued (Ardabili; and the
Yohannes figures, now cited as Willgoss & Yohannes 2013 plus the 2014 review),
one likely-intended source is identified (Jiang/Jones 2021 for the opioid-type
mix), and six citations are confirmed not to exist under any reasonable
correction (Casagrande, Rhee, Rhoads, Freedman, Cicero, White).

## How to re-run this audit

```bash
python -m hipaasynth.modules.run_all_modules          # generate cohorts
python -m hipaasynth.modules.calibration_validator    # COPD, CHF, OUD
python -m hipaasynth.modules.calibration_validator_ext
python examples/reference_scores.py                   # 7AAST reference scores
```

Every PMID above can be checked at `https://pubmed.ncbi.nlm.nih.gov/<PMID>/`.
