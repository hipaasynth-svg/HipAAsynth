# COPD Calibration Verification — Proof of Concept

**Date:** 2026-07-14 · **Module:** `hipaasynth/modules/copd/copd_generator.py`
**Method:** Every anchor constant in the COPD module was checked against the paper it cites. Sources were located via PubMed; where a paper was found, its reported figure was compared to the coded value. Nothing here is asserted from memory — a value is only marked `confirmed` when the cited source was retrieved and supports it.

> Source attribution: article metadata below was retrieved from **PubMed**. DOI links are included for every referenced article.

## What "verified" means here

The existing `calibration_validator.py` checks that the sampler reproduces the generator's *own* constants (e.g. it asserts `GOLD_1 ≈ 0.20`, which is the same `0.20` the generator samples from). That proves **sampling fidelity**, not **source fidelity**. This POC introduces an external targets file (`copd_targets.json`) whose `value` is tied to a cited paper and whose `status` records whether that link survives inspection. `verify_against_targets.py` reads that file and will only count a target as "passing" if its provenance is `confirmed`.

## Result: 2 of 19 targets have verified provenance

| Target | Coded value | Cited source | Verified outcome |
|---|---|---|---|
| GOLD stage distribution (20/38/28/14) | 0.20/0.38/0.28/0.14 | "Lamprecht B et al. Respir Res 2011;12:121" | **citation_mismatch** |
| Never-smoker fraction | 0.15 | "Salvi SS, Barnes PJ. Lancet 2009;374:733-743" | **value_mismatch** |
| Current / former smoker | 0.38 / 0.47 | (same Salvi block) | **unsourced** |
| Exacerbations/yr, GOLD 2 | range 0.5–1.5 | "Hurst JR et al. NEJM 2010;363:1128-1138" | **confirmed** ✅ |
| Exacerbations/yr, GOLD 1 | range 0.0–0.8 | (same Hurst) | **metric_mismatch** |
| Hospitalization rates by GOLD | 0.05/0.12/0.28/0.45 | (same Hurst) | **metric_mismatch** |
| COPD prevalence framing | 6.2% | "Wheaton AG et al. MMWR 2015;64(SS-7):1-20" | **citation_locus_wrong** |
| FEV1 GOLD-2 mean | 64.5 | GOLD band midpoint | definitional |
| age mean / SpO2 mean | 64 / 94.5 | none pinned | unsourced |
| sex, LTOT, HTN, T2DM, depression | — | named, not yet pulled | not_yet_verified |

## The four anchor findings (detail)

1. **GOLD stage distribution — citation does not resolve to a Lamprecht paper.**
   The cited locus *Respir Res* 2011;**12:121** resolves to Schuurhof A, et al., *"Local interleukin-10 production during respiratory syncytial virus bronchiolitis is associated with post-bronchiolitis wheeze,"* an **RSV bronchiolitis** study — not a COPD GOLD-distribution paper. PMID 21910858, [DOI 10.1186/1465-9921-12-121](https://doi.org/10.1186/1465-9921-12-121). The 20/38/28/14 split is therefore **unverified as cited**; the intended Lamprecht/BOLD source must be located and the exact figure pinned.

2. **Never-smoker fraction (0.15) — source confirmed but reports a different number.**
   Salvi SS, Barnes PJ, *"Chronic obstructive pulmonary disease in non-smokers,"* Lancet 2009;374(9691):733-743 — **confirmed** (PMID 19716966, [DOI 10.1016/S0140-6736(09)61303-9](https://doi.org/10.1016/S0140-6736(09)61303-9)). But it states *"an estimated 25–45% of patients with COPD have never smoked"* (a global, biomass-driven figure), **not 15%**. The coded 0.15 may be a defensible US value, but it is not what this source says. Either adjust the value or attach a US-specific reference. The current/former split (0.38/0.47) is not addressed by this paper at all.

3. **Exacerbation rates — confirmed for GOLD 2–4; wrong for GOLD 1 and for hospitalizations.**
   Hurst JR, et al. (ECLIPSE), NEJM 2010;363(12):1128-1138 — **confirmed** (PMID 20843247, [DOI 10.1056/NEJMoa0909883](https://doi.org/10.1056/NEJMoa0909883)). Year-1 rates: **0.85 (GOLD 2), 1.34 (GOLD 3), 2.00 (GOLD 4)** — all fall inside the coded ranges. However: ECLIPSE enrolled **GOLD 2–4 only**, so the coded GOLD-1 exacerbation range is unsupported by Hurst; and the coded **hospitalization** rates (0.05/0.12/0.28/0.45) are a *different quantity* than the paper's frequent-exacerbator percentages (22/33/47% with ≥2/yr). The Hurst citation should not be used for hospitalization rates.

4. **COPD prevalence (6.2%) — right author/year, wrong locus, slightly different value.**
   The real Wheaton 2015 MMWR is *MMWR Morb Mortal Wkly Rep* 2015;**64(11):289-95**, *"Employment and activity limitations among adults with COPD — United States, 2013"* (PMID 25811677, [DOI 10.15585/mmwr.mm6411a1](https://doi.org/10.15585/mmwr.mm6411a1)), reporting COPD prevalence **6.4%** (≈15.7M adults) — not the coded locus "64(SS-7):1-20" and slightly above the coded 6.2%. A related BRFSS analysis (Cunningham/Wheaton, COPD 2014, PMID 25207639, [DOI 10.3109/15412555.2014.949001](https://doi.org/10.3109/15412555.2014.949001)) independently reports **depression 27.4%** among current smokers, which is close to the module's coded depression rate of 0.27 — supportive but in a different population, so still `not_yet_verified` against the module's actual citation (Yohannes 2014).

## How to reproduce

```
python3 -m hipaasynth.modules.calibration.verify_against_targets \
    --targets hipaasynth/modules/calibration/copd_targets.json \
    [--cohort output/copd_1000/copd_calibration_n1000.csv]
```

Without a cohort CSV it runs provenance-only (the audit above). With a cohort it additionally measures the empirical value for any `confirmed` target and compares within tolerance — and never counts an unverified target as a pass.

## Interpretation

This does **not** mean COPD is "wrong." The exacerbation model checks out against ECLIPSE, and prevalence is within ~0.2 points of the real Wheaton figure. It means the *provenance layer* is what needs work: two citations point to the wrong locus, one value disagrees with its (correct) source, and several rows are cited loosely enough that a reader can't trace the number. Fixing those makes each green check a real, defensible claim. The same procedure now needs to be run across the remaining metrics and the other modules.
