# Conditional Dependence — Technical Note (v1.2.1)

## Summary

Comorbidity clusters for the **COPD** and **CHF** modules are no longer generated
as independent Bernoulli draws. They are now drawn **conditional on primary-condition
severity** (COPD → GOLD stage; CHF → NYHA class) through a single dedicated module,
`hipaasynth/core/dependence.py`. Published national marginal prevalences are
**preserved exactly** while realistic severity gradients are introduced (sicker
patients carry more comorbidity burden).

This closes the "independent draws for high-impact variables" gap without disturbing
any existing design invariant: pure-stdlib core path, SHA-256 anchor-rooted
determinism, zero PHI, and byte-identical reproducibility given the same seed,
profile, and n.

## What was independent before

| Module | Old behavior | Location |
| --- | --- | --- |
| COPD | `rate * (1.3 if GOLD_3/4 else 1.0)`, then `rng.random() < rate` — a single blanket multiplier applied uniformly to **every** comorbidity | `copd_generator.py` comorbidity loop |
| CHF | `rng.random() < rate` — **no** severity conditioning at all (only ischemic etiology forcing `cad=True`) | `chf_generator.py` comorbidity loop |

Stroke and sepsis observation hooks were audited and found to be **already
conditional** (severity computed from comorbidities; NIHSS conditional on stroke
type; vasopressors conditional on oliguria + lactate), so they were left intact.
OUD carries partial conditioning (IV use → HCV/endocarditis/HIV; rurality → ACEs);
its psychiatric comorbidities remain severity-independent and are a documented
candidate for a future pass.

## The model: marginal-preserving severity gradient

For each comorbidity we keep the published **marginal** `m` and tilt it across the
primary condition's severity strata with a monotonic **gradient** of multipliers,
normalized so its stratum-weighted mean is exactly `1.0`:

```
rate[stratum] = m * g_norm[stratum]      where   Σ_s w[s] · g_norm[s] = 1
```

Because the weighted mean of the multiplier is `1.0`, the weighted mean of the rate
is exactly `m` — **marginal preserved by construction**. The per-stratum rate
`m · g_norm[s]` produces the directional gradient.

**Trade-off policy: preserve the marginal.** If a steep gradient would push a
stratum rate past the probability cap (`0.97`) it is clamped and the (tiny) marginal
drift is accepted. The shipped tables are tuned so **no clamping occurs** — verified
analytically (`test_*_weighted_mean_equals_marginal`, exact to 1e-6) and in sampled
cohorts. This keeps the marginal an honest per-locale knob (see below).

### Severity strata & distributions

- **COPD / GOLD** — `GOLD_1 0.20, GOLD_2 0.38, GOLD_3 0.28, GOLD_4 0.14`
  (Buist AS et al., BOLD Study, *Lancet* 2007;370(9589):741-750; GOLD 2024).
- **CHF / NYHA** — `I 0.03, II 0.14, III 0.54, IV 0.29`
  (Fonarow GC et al., OPTIMIZE-HF, *JAMA* 2007;297(1):61-70).

### Named gradient shapes

Shapes describe how strongly a comorbidity tracks primary-condition severity.
Raw multipliers are normalized to the stratum distribution at table-build time.

| Shape | Meaning | COPD raw (GOLD 1→4) | CHF raw (NYHA I→IV) |
| --- | --- | --- | --- |
| `shallow` | weak dependence (common baseline) | 0.85, 0.95, 1.08, 1.20 | 0.85, 0.92, 1.00, 1.10 |
| `moderate` | symptom-burden linked | 0.70, 0.92, 1.14, 1.42 | 0.70, 0.82, 1.00, 1.20 |
| `steep` | organ-damage / progression linked | 0.55, 0.85, 1.25, 1.70 | 0.55, 0.72, 1.00, 1.30 |
| `very_steep` | pathophysiologically downstream of severity | 0.45, 0.80, 1.30, 1.90 | 0.40, 0.62, 1.00, 1.42 |

## COPD comorbidity dependence (conditional on GOLD stage)

Marginals unchanged from the published `COMORBIDITY_RATES`. Resolved rates
(marginal preserved exactly; GOLD_1 → GOLD_4 shown):

| Comorbidity | Marginal | Shape | GOLD_1 | GOLD_4 | Source for gradient |
| --- | --- | --- | --- | --- | --- |
| hypertension | 0.55 | shallow | 0.47 | 0.66 | highly prevalent, weak GOLD link |
| cardiovascular_disease | 0.25 | steep | 0.14 | 0.42 | Chen W et al. *Lancet Respir Med* 2015;3(8):631-639 |
| type2_diabetes | 0.22 | shallow | 0.19 | 0.26 | Mirrakhimov AE. *Cardiovasc Diabetol* 2012;11:132 |
| depression | 0.27 | moderate | 0.19 | 0.38 | Yohannes AM et al. *Respir Care* 2014;59(7):1112-1120 |
| anxiety | 0.19 | moderate | 0.13 | 0.27 | Yohannes AM et al. 2014 |
| osa | 0.15 | moderate | 0.10 | 0.21 | Shawon MS et al. *Respir Med* 2017;131:79-90 |
| pulmonary_hypertension | 0.18 | very_steep | 0.08 | 0.33 | Chaouat A et al. *Eur Respir J* 2008;32(5):1371-1385 |
| osteoporosis | 0.24 | steep | 0.13 | 0.40 | Graat-Verboom L et al. *Eur Respir J* 2009;34:209-218 |
| lung_cancer_history | 0.04 | very_steep | 0.02 | 0.07 | de-Torres JP et al. *AJRCCM* 2015;191(3):285-291 |

## CHF comorbidity dependence (conditional on NYHA class)

Marginals unchanged from the published `COMORBIDITY_RATES`. Resolved rates
(NYHA I → NYHA IV shown):

| Comorbidity | Marginal | Shape | NYHA I | NYHA IV | Source for gradient |
| --- | --- | --- | --- | --- | --- |
| hypertension | 0.73 | shallow | 0.61 | 0.79 | near-universal, weak NYHA link |
| type2_diabetes | 0.45 | shallow | 0.38 | 0.49 | metabolic comorbidity |
| ckd | 0.48 | steep | 0.26 | 0.60 | Ronco C et al. *JACC* 2008;52(19):1527-1539 (cardiorenal) |
| afib | 0.45 | moderate | 0.31 | 0.53 | Dharmarajan K et al. *JAMA* 2013;309(4):355-363 |
| copd | 0.28 | shallow | 0.24 | 0.30 | coincident airway disease |
| cad† | 0.55 | moderate | 0.38 | 0.65 | ischemic substrate more common in worse HF |
| prior_mi | 0.32 | moderate | 0.22 | 0.38 | tracks ischemic severity |
| prior_cabg_or_pci | 0.28 | shallow | 0.24 | 0.30 | revascularization history |
| anemia | 0.37 | steep | 0.20 | 0.47 | Groenveld HF et al. *JACC* 2008;52:818-827 |
| sleep_apnea | 0.24 | moderate | 0.16 | 0.28 | SDB rises with HF severity |
| depression | 0.22 | moderate | 0.15 | 0.26 | Rutledge T et al. *JACC* 2006;48:1527-1537 |
| peripheral_vascular_disease | 0.18 | moderate | 0.12 | 0.21 | systemic atherosclerosis |
| stroke_tia_history | 0.14 | moderate | 0.10 | 0.16 | thromboembolic risk |
| liver_disease | 0.08 | steep | 0.04 | 0.10 | Samsky MD et al. *JACC* 2013;61:2397-2405 (congestive hepatopathy) |

† `cad` is additionally forced `True` for ischemic cardiomyopathy (pre-existing
behavior), so its *observed* marginal exceeds the model value by design. Its
marginal is excluded from the sampled marginal-preservation test for that reason.

## Geographic / locale tuning (the marginal knob)

Every rate-building function accepts an optional `marginal_overrides` mapping. A
population profile for a specific locale (e.g. rural IHS, tribal) can override the
base marginal for any comorbidity, and the **same normalized gradient re-centers on
the new value automatically**. The number a profile dials in is the marginal the
cohort reproduces (verified: `test_locale_override_recenters_marginal`). This is
the reason the trade-off policy is "preserve the marginal" — it keeps the locale
knob exact and reasoned-about, with dependence layered on top as a separate,
reusable structure.

## Determinism contract

- No RNG is created inside `dependence.py`; callers pass the existing anchor-rooted,
  namespaced `random.Random`.
- Each `draw_*` helper consumes **exactly one** `rng.random()` per comorbidity in a
  **fixed key order** — identical stream structure to the independent-draw version
  it replaced. Verified by `test_*_draw_consumes_exactly_one_per_comorbidity`.
- Result: same seed + n → byte-identical cohorts
  (`test_copd_byte_identical`, `test_chf_byte_identical`).

## Sequential generation order

The engine already follows, and this change reinforces, the strict conditional
order: **demographics + geography/profile → anthropometrics (age/sex) → primary
condition + severity/stage → comorbidity cluster (conditional on severity, age,
sex) → labs & vitals (conditional on conditions + severity) → functional status
(conditional on severity)**. Life-outcome variables (relationship stability,
employment, income band) are scaffolded as the **final** stage in
`dependence.draw_life_outcomes(...)`, conditional on functional status + condition
burden + age + demographics. This stage is **provisional / uncalibrated** and is
intentionally not part of the default record, so it does not affect existing
outputs, determinism, or the FairnessPassport; it is deterministic and its
direction is test-locked, ready to be calibrated and wired in later.

## Validation

`tests/test_conditional_dependence.py` (21 tests) enforces:

1. **Marginal preservation** — analytic (weighted mean == marginal, exact to 1e-6)
   and sampled (within ±0.05 at n=4000).
2. **Joint fidelity** — comorbidity rates rise with severity above an anti-tamper
   threshold (COPD Δ>0.12, CHF Δ>0.10); functional scores (6MWD, mMRC) worsen with
   GOLD stage. Reverting to independent draws collapses these spreads to ~0 and
   fails the suite (demonstrated: conditional PH span +0.25 vs flattened −0.00).
3. **Determinism** — byte-identical cohorts and the one-draw-per-comorbidity
   stream contract.
