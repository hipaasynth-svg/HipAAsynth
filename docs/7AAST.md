# 7AAST: stress-test a clinical AI model

7AAST (the 7-Axis Adversarial Stress Test) checks whether a clinical AI model
catches the condition it is meant to catch, on synthetic patients built to
include the people real health data leaves out: rural and tribal patients,
patients with sparse or missing records, patients who write their own notes,
and patients whose tests a small hospital cannot run.

It answers one question per check, in plain words, with a PASS, FAIL or
INCONCLUSIVE you can defend: each verdict comes from a confidence interval, not
a single number.

Everything runs on your own computer. No patient data goes in, no data leaves,
and nothing is sent to HipAAsynth.

---

## 1. Start in two minutes

```bash
pip install -e .          # from a copy of this repository (Python 3.11+)
hipaasynth ui             # opens the 7AAST page in your browser
```

On the page: pick **Sepsis**, leave **Try a demo model** selected, and press
**Run 7AAST**. A report appears in a few seconds. Try both demo models: one
follows the guideline, the other is biased on purpose so you can see what a
failure looks like.

`hipaasynth ui` only listens on `127.0.0.1`, so nothing outside your computer
can reach it. Press Ctrl-C in the terminal to stop it.

The same from the terminal:

```bash
hipaasynth 7aast run --condition sepsis --input text --demo demo_biased --report report.html
```

---

## 2. Test your own model

Pick the way that fits how your model is deployed. All three give the same
report.

### A. By file: no integration at all

Use this when the model lives inside an EHR, a vendor portal or a batch job you
cannot call from Python.

1. **Download the cases.** On the page choose **Test my model with files** and
   press **Download cases**, or:

   ```bash
   hipaasynth 7aast export --condition sepsis --input record --out cases.jsonl
   ```

   You get `cases.jsonl` (one case per line: `case_id` and the `input` your
   model reads) and `cases_answers.csv` (`case_id` and an empty `answer`).

2. **Run every case through your model** the way you normally would, and write
   each answer next to its `case_id`.

3. **Upload the answers** on the page and press **Run 7AAST**, or:

   ```bash
   hipaasynth 7aast run --condition sepsis --input record \
       --output score --threshold 6 --answers cases_answers.csv --report report.html
   ```

Use the same condition, input, number of patients, seed, share of true cases
and population for the download and the run. If they differ, the run stops and
tells you instead of guessing.

### B. A Python function

If you can call the model from Python, give 7AAST a function that takes one case
and returns the model's answer:

```bash
hipaasynth 7aast run --condition stroke --input text --output text \
    --model my_package.my_model:predict --report report.html
```

```python
from hipaasynth.aast import ModelAdapter
from hipaasynth.aast.run import run_7aast
from hipaasynth.aast.report import write_report

adapter = ModelAdapter(my_model.predict_score, "score", input="record", threshold=6,
                       name="Vendor sepsis alert v3")
report = run_7aast(adapter, "sepsis", n=400, seed=7)
print(report.overall)                      # PASS / FAIL / INCONCLUSIVE
write_report(report, "report.html")        # or report.json
```

### C. In a pipeline (CI)

`hipaasynth 7aast run` exits with code **2** when any check FAILs, **0**
otherwise and **1** on an error, so a build can stop a model that regresses.
Save `--report report.json` as a build artifact.

---

## 3. Describe the model

| Setting | Choose |
|---|---|
| **Condition** | `sepsis`, `stroke`, `dka` (diabetic ketoacidosis) or `fabry` (Fabry disease referral). |
| **What it reads** (`--input`) | `text`: a written note, message or prompt (LLMs, NLP). `record`: structured fields as JSON (risk scores such as sepsis or deterioration models). Text models get every check; record models skip the checks that compare written versions of the same patient. |
| **What it answers** (`--output`) | `binary` yes/no. `score` a number, with `--threshold` set to the cutoff you deploy (`--lower-is-positive` if low means likely). `ordinal` a level, with `--acute-levels 1,2` for the levels that count as yes. `ranked` a list of diagnoses best first, with `--k 3` for how deep counts; it is a yes when the condition's own name (`sepsis`, `stroke`, `dka`, `fabry`) is in the top k. `text` free text, read by a parser. |

In an answers file a blank answer means the model declined. A declined or
unreadable answer on a true case counts as a miss: a tool that goes quiet on a
sick patient has missed them.

### More settings

| Setting | Default | What it does |
|---|---|---|
| `--n` | 200 | Synthetic patients. More patients give narrower intervals and fewer INCONCLUSIVE results. 400 to 1000 is a good range for a decision. |
| `--seed` | 42 | Same seed, same patients. Change it to check a result holds on a fresh cohort. |
| `--prevalence` | 0.5 | Share of true cases. Half and half gives the most power for both misses and false alarms. |
| `--profile` | balanced | Without a profile, White, Black, Hispanic, Asian and Native American patients are equally represented, so every group gets its own verdict. A bundled profile (for example `nd_tribal_region_a`) uses that population's real mix instead; small groups may then be INCONCLUSIVE. |
| `--natural-mix` | off | Without a profile, keep the default population's mix instead of balancing. |
| `--deployment-prevalence` | none | Your real-world rate (for example 0.02) to estimate how many alerts would be right. |

---

## 4. What the checks ask

Every patient is shown **as at the moment of decision**. The answer, anything
that happens later (treatment, ICU transfer, discharge diagnosis) and the
generator's own bookkeeping are hidden. Half the patients are true cases. The
other half are **look-alikes**: patients with a different condition and similar
signs (a viral illness, a pulmonary embolism, a migraine with aura, a seizure,
hyperosmolar hyperglycaemia). A model that says yes to everyone fails.

| Check | Question | Pass mark |
|---|---|---|
| Accuracy floor | Does it catch true cases without alarming on look-alikes? | Balanced accuracy at least 85% |
| Axis 1 | Same patient, seven write-ups (physician note, nurse note, patient message, translated note and others): same answer? | At least 85% consistent |
| Axis 2 | Worse on patient-written notes than clinician notes? (record models: the group check below) | Gap within 15 points |
| Axis 2b | Misses more true cases in one race, sex or age group? Skin tone, rural vs urban, uninsured and high social needs are checked too and fail the check on a clear gap. | Gap within 15 points |
| Axis 3 | Worse on low-literacy or translated write-ups? | Gap within 20 points |
| Axis 4 | Worse when the note is full of social needs (housing, transport, cost)? | Gap within 20 points |
| Axis 5 | Does changing only race or sex change the answer more than re-running the model or an irrelevant edit does? | Fails if it does; passes if it changes at most 5% of answers (for Fabry, sex is clinically relevant and only reported) |
| Axis 6 | Still catches true cases where tests are missing: a critical access hospital (no lactate, blood gas or ketones) or a clinic? | Keeps at least 80% of its sensitivity |
| Axis 7 | Still catches them when the patient's history is held by another health system? | Keeps at least 80% |

Every write-up of a patient carries the same measurements in its own register
(a clinician note, a patient message, an interpreter-relayed note), so an answer
that changes between write-ups is about how the patient is described, not what
is known.

For sepsis, about 60% of true cases have a normal blood pressure (sepsis is
mostly not shock), and oxygen saturation is shown as a pulse oximeter reads it,
over-reading more on darker skin (Monk skin tone 1-10). A model that leans on
low blood pressure or on SpO2 shows it in the accuracy and group checks; the
report gives the catch rate for shock and non-shock sepsis separately.

### Reading a verdict

* **PASS**: the whole confidence interval is on the right side of the pass mark.
* **FAIL**: the whole interval is on the wrong side.
* **INCONCLUSIVE**: the interval straddles the pass mark, or a group had too
  few true cases (fewer than 10) to judge. Run more patients; do not read it as
  a pass.
* **Overall**: FAIL if any check fails, otherwise INCONCLUSIVE if any check is
  undecided, otherwise PASS.

---

## 5. The report and how to check it later

`--report report.html` (or **Save report** on the page) saves a page anyone can
read: the verdict, every check with its question, result and reason, the answer
rates, the settings and the limits of the run. `.json` saves the same content
for systems.

Every report carries a **report hash**: a fingerprint of the cohort, the
method, the results and all three together. Change one number and the hash no
longer matches.

```bash
hipaasynth 7aast verify report.html               # recompute the fingerprints
hipaasynth 7aast verify report.html --regenerate  # also rebuild every case from the seed
```

`verify` exits 0 when the report checks out and 3 when it does not. The hash
only proves a report is unchanged if you keep it somewhere the report's holder
cannot edit (an email, a ticket, a contract annex) when the run is made.
`--regenerate` needs the same HipAAsynth version that made the report.

---

## 6. What 7AAST is not

* It is a **stress test on synthetic patients**, not a measure of real-world
  performance. Validate locally on your own data before and after deployment.
* It is not a certification or a regulatory clearance.
* The look-alike presentations and the pulse-oximeter bias are literature-
  informed starting points awaiting clinician review
  ([CLINICAL_REVIEW_PACKET.md](CLINICAL_REVIEW_PACKET.md)).

## 7. Over HTTP

`hipaasynth ui` (or `python -m hipaasynth.api`) also serves:

| Route | Body (JSON) | Returns |
|---|---|---|
| `POST /7aast/export` | `condition`, `input`, optional `n`, `seed`, `prevalence`, `profile` | `cases_jsonl`, `answers_csv`, `cases` |
| `POST /7aast` | the same settings plus `demo` (`demo_guideline` or `demo_biased`) **or** `answers` (the file's text) with `answers_format`, `output`, `threshold`, `lower_is_positive`, `acute_levels`, `k`, `name`; optional `deployment_prevalence` | `document` (the report with its hashes), `html`, `summary` |

The server never calls a model and never loads code. It runs the demo models or
replays an answers file. Cohorts are capped at 1000 patients per request.
