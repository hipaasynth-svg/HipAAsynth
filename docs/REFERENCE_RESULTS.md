# Reference results: published clinical scores through 7AAST

These are real rules hospitals run, reimplemented in
`hipaasynth/aast/reference.py` and tested with 7AAST exactly like any other
model. They answer two questions:

1. **What does 7AAST find on a deployed rule?**
2. **Does 7AAST agree with what the literature already knows about these
   rules?** If a synthetic stress test reproduced none of the known
   weaknesses, its findings on new models would deserve little trust.

Regenerate with `python examples/reference_scores.py 1000 42`.

## Results

n = 1000 synthetic patients per score (half true cases), seed 42, record input.

| Score | Overall | Catch rate (sensitivity) | Look-alikes cleared (specificity) | Failing checks |
|---|---|---|---|---|
| qsofa (sepsis) | FAIL | 42% (38%–47%) | 95% (93%–97%) | accuracy Accuracy floor |
| sirs (sepsis) | FAIL | 88% (85%–91%) | 51% (46%–55%) | accuracy Accuracy floor |
| news2 (sepsis) | FAIL | 79% (76%–83%) | 58% (54%–62%) | accuracy Accuracy floor |
| rosier (stroke) | FAIL | 91% (89%–94%) | 29% (25%–33%) | accuracy Accuracy floor |
| ada_dka (dka) | PASS | 100% (99%–100%) | 100% (99%–100%) | none |

Sepsis catch rate by presentation:

| Score | Septic shock | Normal blood pressure |
|---|---|---|
| qsofa | 73% (65%–79%) | 25% (21%–30%) |
| sirs | 100% (98%–100%) | 81% (76%–85%) |
| news2 | 95% (91%–98%) | 71% (65%–76%) |

## How this compares with published performance

| Score | Published | 7AAST | Agrees? |
|---|---|---|---|
| qSOFA ≥ 2 | Low sensitivity, high specificity outside the ICU (pooled sensitivity about 0.51, specificity about 0.83 for in-hospital mortality; Fernando et al., Ann Intern Med 2018). Seymour et al. (JAMA 2016) warned it is not a screening tool. | Catches 42%, clears 95%; catches only 25% of normotensive sepsis | Yes: the known weakness appears, and 7AAST shows where it comes from |
| SIRS ≥ 2 | About 1 in 8 patients with sepsis is SIRS-negative, sensitivity about 88% (Kaukonen et al., NEJM 2015), and SIRS fires on many infections without organ dysfunction (low specificity; Churpek et al., AJRCCM 2017) | Catches 88%, clears 51% | Yes, on both |
| NEWS2 ≥ 5 | Detects deterioration in infected patients better than qSOFA and SIRS, with more false alarms than qSOFA (Churpek et al., AJRCCM 2017; RCP 2017) | Catches 79%, clears 58%; between qSOFA and SIRS on both | Yes, in direction |
| ROSIER > 0 | High sensitivity, specificity varies widely with the mimic mix (Nor et al., Lancet Neurol 2005; later validations about 0.44–0.83) | Catches 91%, clears 29% | Sensitivity yes; specificity lower, because records carry the NIHSS total, not the ROSIER items, so every mimic with any deficit scores (see limits) |
| ADA DKA criteria | Defines DKA | Perfect | By construction: the generator labels DKA with these criteria, so this row checks the plumbing, not the rule |

## What this does and does not show

* It shows that 7AAST reproduces the **direction and rough size** of every
  known strength and weakness above, and explains the most important one: qSOFA
  misses sepsis because most sepsis is not hypotensive.
* It does **not** show that 7AAST predicts harm in real patients. That needs a
  study on real records (see the validation-partner proposal kept with the
  business documents).
* The scores are reimplemented from their publications. They are not any
  vendor's product, and reports label them `REFERENCE`.
* ROSIER is approximated from the NIHSS total; the specificity above is a
  property of that approximation as much as of ROSIER.

## Testing an LLM

The same run works on an LLM API (OpenAI-compatible servers or Anthropic):

```bash
OPENAI_API_KEY=... hipaasynth 7aast run --condition sepsis --input text \
    --llm openai --llm-model gpt-4o --n 200 --report llm_sepsis.html
ANTHROPIC_API_KEY=... hipaasynth 7aast run --condition sepsis --input text \
    --llm anthropic --llm-model claude-sonnet-5-5 --n 200 --report llm_sepsis.html
```

The LLM sees each blinded case with one fixed question and must end with
`FINAL_ANSWER: Yes` or `No`; temperature is 0 and the noise floor shows how
repeatable it still is. A 200-patient text run makes about 2,600 calls. No LLM
results are published here: the development environment had no API key.
