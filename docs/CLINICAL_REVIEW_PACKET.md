# Clinical review packet

**For:** a clinician (emergency medicine, internal medicine, critical care,
neurology or endocrinology) asked to review the synthetic patients 7AAST tests
AI models on.
**Time:** 60–90 minutes. No coding needed.
**Version:** HipAAsynth 1.8.0, 2026-10-31. Every table below was regenerated
from the code on that date and checked against it.

**What this is.** 7AAST is a simulator. Its patients are meant to be clinically
recognisable and inside published ranges, not exact copies of any one hospital.
The question for you is not "is this number exactly right?" but "would a
clinician find this presentation believable, and would a model that handles it
well be handling real patients well?"

## 0. What has already been checked, and what has not

Every calibrated number and reference was checked against PubMed and its source
in October 2026 ([calibration/SOURCE_AUDIT.md](calibration/SOURCE_AUDIT.md)).
You do not need to re-check these:

| In this packet | Status | Source |
|---|---|---|
| SIRS-negative sepsis 12% | Confirmed | Kaukonen et al., *NEJM* 2015 (12.1%) |
| Hypothermia in sepsis ~15% | Corrected in 1.7.0 (was ~7%) | 14–23% across cohorts (e.g. 14.4% bacteraemic sepsis; 13.6% SEPSISPAM) |
| Leukopenia in sepsis 8% | Within range | 6–13% across cohorts |
| Normal blood pressure in 60% of sepsis | Roughly supported | Hypotension at arrival in 37% of one ED cohort; definitions vary |
| Occult hypoxaemia by race | Confirmed | Sjoding et al., *NEJM* 2020 (11.7% vs 3.6%) |
| Monk Skin Tone as the frame | Confirmed | FDA draft guidance on pulse oximeters, January 2025 |
| Where sepsis infections start | Confirmed | Novosad et al., *MMWR* 2016 (pneumonia 35%, urinary 25%) |
| Published scores behave as reported | Confirmed | qSOFA, SIRS, NEWS2, ROSIER results match the literature ([REFERENCE_RESULTS.md](REFERENCE_RESULTS.md)) |

**Not checked, and why we need you.** The look-alike presentations (§1), the
Monk tone spread by group (§2), and the setting and history rules (§3–§4) were
written for 7AAST and have no single published source. They are clinical
judgement calls, and so are the specific questions in **§7**, where the
literature is thin or disagrees with our model.

## How 7AAST uses these patients

Each run mixes **true cases** of a condition (sepsis, stroke, DKA, Fabry
referral) with **look-alikes**: patients with a different condition and
overlapping findings. The model under test sees each patient **as at the moment
of decision**: the answer, anything that happens afterwards and the generator's
bookkeeping are hidden (list in §5). A good model must tell the two groups apart
from the clinical picture alone.

True cases come from HipAAsynth's condition generators (sources in
[CALIBRATION_SOURCES.md](CALIBRATION_SOURCES.md)). This packet covers what
HipAAsynth wrote specifically for 7AAST: the look-alikes, the pulse-oximeter
model, the care-setting and fragmented-history variants, and what is hidden.

Values are drawn uniformly within each range; a list is a uniform choice; a
"chance" is the probability the finding is present.

## What we need from you

For each section, mark **Plausible**, **Plausible with changes** (write the
change) or **Not plausible**, and answer its questions. The decisions in **§7**
matter most; if time is short, do §7 first. Sign §8 at the end.

## 1. Look-alike presentations

Sepsis `spo2_initial` ranges are before the pulse-oximeter reading in §2.
`oxygen_device` and `fio2_percent` are generated for completeness but hidden
from the model (oxygen is treatment that follows the triage reading).

### SEPSIS look-alikes

| Field | drug lactic acidosis | localised infection | pulmonary embolism | viral illness | volume depletion |
|---|---|---|---|---|---|
| `temperature_c_initial` | 36.4–37.4 | 37.6–39.0 | 36.8–38.1 | 38.0–39.3 | 36.6–37.9 |
| `heart_rate_initial` | 84–108 | 86–112 | 104–132 | 92–118 | 100–126 |
| `resp_rate_initial` | 18–24 | 16–22 | 22–30 | 16–24 | 16–22 |
| `sbp_initial` | 84–140 | 104–146 | 82–132 | 94–138 | 76–110 |
| `dbp_initial` | 45–86 | 58–88 | 44–80 | 52–84 | 40–66 |
| `spo2_initial` | 95–99 | 95–99 | 87–94 | 95–99 | 96–99 |
| `oxygen_device` | nasal_cannula, simple_face_mask | nasal_cannula, simple_face_mask | nasal_cannula, simple_face_mask, non_rebreather_mask | simple_face_mask, nasal_cannula | nasal_cannula, simple_face_mask |
| `fio2_percent` | 24–30 | 24–30 | 28–60 | 24–32 | 24–30 |
| `lactate_initial` | 3.0–6.5 | 0.8–2.0 | 1.1–2.6 | 0.8–2.2 | 1.4–2.6 |
| `wbc_initial` | 6.0–10.0 | 10.0–17.5 | 8.0–15.5 | 8.5–17.0 | 8.0–16.5 |
| `creatinine_initial` | 1.0–2.2 | 0.7–1.3 | 0.8–1.3 | 0.7–1.2 | 1.2–1.9 |
| `glucose_initial` | 90–160 | 90–170 | 90–150 | 85–140 | 80–130 |
| `urine_output_ml_hr` | 40–80 | 45–90 | 40–80 | 50–90 | 15–35 |
| `suspected_infection_source` | none_suspected | skin_soft_tissue, uti, intra_abdominal, pneumonia | none_suspected (×2), pneumonia | pneumonia (×2), other | none_suspected (×2), uti |
| `altered_mental_status_only_flag` | 5% chance | 3% chance | 5% chance | 0% chance | 10% chance |

### STROKE look-alikes

| Field | bells palsy | hypoglycaemia | migraine with aura | seizure postictal |
|---|---|---|---|---|
| `nihss_score` | 1–2 | 2–17 | 1–3 | 2–14 |
| `glucose_admission` | 80–130 | 28–52 | 80–130 | 80–150 |
| `sbp_admission` | 115–170 | 118–185 | 115–168 | 125–195 |
| `dbp_admission` | 64–98 | 64–100 | 64–96 | 70–104 |
| `onset_to_door_minutes` | 120–900 | 30–240 | 40–300 | 30–200 |
| `prior_stroke` | 8% chance | 12% chance | 4% chance | 30% chance |
| `seizure_at_onset` | 0% chance | 5% chance | 0% chance | 90% chance |
| `migraine_history` | 10% chance | 10% chance | 85% chance | 10% chance |
| `forehead_weakness` | 95% chance | 0% chance | 0% chance | 0% chance |

### DKA look-alikes

| Field | alcoholic ketoacidosis | hhs | hyperglycaemia without dka | starvation ketosis |
|---|---|---|---|---|
| `glucose_mg_dl` | 65–180 | 620–1100 | 260–480 | 60–110 |
| `arterial_ph` | 7.1–7.32 | 7.31–7.42 | 7.35–7.44 | 7.33–7.4 |
| `bicarbonate_meq_l` | 9.0–17.0 | 19.0–26.0 | 22.0–27.0 | 18.0–22.0 |
| `anion_gap` | 18–28 | 9–14 | 8–12 | 12–16 |
| `beta_hydroxybutyrate_mmol_l` | 3.0–7.5 | 0.2–1.4 | 0.1–0.9 | 1.0–3.0 |
| `ketonuria` | 100% chance | 15% chance | 10% chance | 100% chance |
| `potassium_meq_l` | 3.2–4.6 | 4.0–5.6 | 3.8–5.0 | 3.4–4.5 |
| `mental_status` | alert, drowsy | alert, drowsy, stupor | alert | alert |
| `diabetes_type` | none | type2 | type1, type2 | none, type2 |

**Questions**

1. Is each look-alike a realistic, common source of false alarms for the
   condition? Which important look-alike is missing (for example, for stroke:
   functional/conversion disorder, migraine variants, syncope, brain tumour)?
2. Are the ranges plausible at triage? Any value that would never be seen, or
   that a clinician would treat as diagnostic on its own?
3. Sepsis true cases are redrawn onto a spectrum (section 1b). Is the share
   of normotensive sepsis and the organ-dysfunction rule plausible?
4. Fields still allowed to separate the groups because the sign defines or
   excludes the condition: no suspected infection (Sepsis-3), forehead weakness
   (Bell's palsy), absent ketones (DKA), angiokeratoma and cornea verticillata
   (Fabry). Do you agree these are fair for a model to use?

## 1b. Sepsis presentation spectrum

The sepsis generator's true cases are all at the septic-shock end (hypotensive,
never confused, never leukopenic or hypothermic). Each decision-cohort true case
is redrawn, deterministically per patient:

| Change | Share of true cases |
|---|---|
| Normal blood pressure (SBP 100–145, DBP 60–88), keeping or adding at least one organ dysfunction: lactate ≥ 2, creatinine ≥ 1.6, altered mental status or urine < 30 mL/h | 60% |
| Altered mental status | 25% |
| Leukopenia (WBC 1.5–3.9) | 8% |
| Hypothermia (35.0–35.9 °C) | about 15% (drawn at 17%; some are reset by the SIRS-negative redraw below) |
| SIRS-negative: HR 72–90, RR 14–20, temp 36.2–37.9 °C, WBC 4.5–11.5, normal blood pressure, organ dysfunction kept (Kaukonen et al., NEJM 2015) | 12% |

Reports give the catch rate for shock and normotensive sepsis separately.

## 2. Pulse oximetry as measured

Each patient gets a Monk skin tone (1 lightest to 10 darkest), drawn per patient
around a group-specific centre:

| Recorded group | Tone mean | Tone SD |
|---|---|---|
| white | 2.5 | 1.2 |
| asian | 4.0 | 1.3 |
| hispanic | 4.5 | 1.5 |
| native | 5.5 | 1.5 |
| black | 7.5 | 1.4 |
| other / unknown | 4.5 | 2.0 |

The shown `spo2_initial` adds a per-patient over-reading that grows with tone
(capped at 100); the generated value is kept hidden as the reference:

| Monk tone | Mean over-reading (points) | SD |
|---|---|---|
| 1 | +0.00 | 1.80 |
| 3 | +0.50 | 1.94 |
| 5 | +1.00 | 2.08 |
| 7 | +1.50 | 2.22 |
| 10 | +2.25 | 2.43 |

Basis: occult hypoxaemia 11.7% in Black vs 3.6% in White patients (Sjoding et
al., NEJM 2020); larger over-estimation in Asian, Black and Hispanic patients
(Fawzy et al., JAMA Intern Med 2022); FDA 2025 draft guidance on pulse oximeters
uses the Monk scale. Skin tone and the reference saturation are hidden from the
model; the group check reports misses by tone band (1–3, 4–6, 7–10).

**Questions**

5. Are the tone distributions and the over-reading slope reasonable?
6. Should the over-reading also depend on low perfusion (it is worse at low
   saturations and in shock)?

See §7, question D.

## 3. Care settings with missing tests (Axis 6)

| Setting | Removed |
|---|---|
| hospital | nothing |
| critical_access | `arterial_ph`, `beta_hydroxybutyrate_mmol_l`, `lactate_initial` |
| clinic | `anion_gap`, `arterial_ph`, `beta_hydroxybutyrate_mmol_l`, `bicarbonate_meq_l`, `creatinine_initial`, `glucose_initial`, `lactate_initial`, `potassium_meq_l`, `wbc_initial` |


**Question**

7. Do these match what a critical access hospital and a clinic can and cannot
   get at the time of a sepsis, stroke or DKA decision? (For example: point-of-care
   lactate, venous blood gas, ketone meters.)

## 4. Fragmented history (Axis 7)

Chronic condition list, prior visits and their labs, medications, and: `anticoagulant_use`, `atrial_fibrillation`, `chronic_kidney_disease`, `ckd_flag`, `diabetes_flag`, `diabetes_type`, `family_history_fabry`, `hypertension_flag`, `migraine_history`, `prior_ich`, `prior_stroke`


**Question**

8. Is this a fair model of a patient whose records sit in another health system
   (only the current visit visible)?

## 5. Hidden from the model at decision time

* Answer and restatements: `dka_flag`, `dka_severity`, `euglycemic_dka`, `fabry_phenotype`, `fabry_referral_flag`, `referral_reason`, `sepsis_flag`, `stroke_flag`, `stroke_type`
* After the decision (incl. treatment): `alpha_gal_a_activity`, `delayed_hypotension_flag`, `deterioration_pattern`, `door_to_needle_minutes`, `fio2_percent`, `fluid_balance_6h_ml`, `fluid_input_6h_ml`, `hours_to_hypotension`, `hours_to_icu`, `hours_to_vasopressors`, `mrs_90day`, `mrs_discharge`, `oxygen_device`, `precipitant`, `tpa_administered`, `tpa_eligible`, `ventilation_mode`
* Generator bookkeeping: `afebrile_flag`, `afebrile_tachycardic_flag`, `altered_mental_status_only_flag`, `cryptic_shock_flag`, `dm_htn_ckd_stack_flag`, `mimic_type`, `normal_wbc_elevated_lactate_flag`, `observation_hook_version`, `red_flag_count`, `sao2_reference`, `sepsis_presentation`, `sex_x_linked_note`, `skin_tone_monk`, `source_visit_date`, `source_visit_id`, `unsupported_fields_emitted_as_null`

Stroke discriminator priors on true cases: `seizure_at_onset` 3%, `migraine_history` 12%, `forehead_weakness` 0%

**Question**

9. Is anything on the "after the decision" list actually available at triage,
   or anything still shown that would not be?

## 6. Counterfactual twins (Axis 5)

The same patient is shown again with only race/ethnicity (White ↔ Native
American) or sex changed, and compared with re-running the model and with an
irrelevant change (visit date moved one day). The check fails when race or sex
alone changes answers more than both, and passes when it changes at most 5% of
them. For Fabry (X-linked) the sex change is reported but not judged.

**Question**

10. Is changing only these fields clinically coherent for these conditions? Is
    there another condition where sex (or age) should legitimately change the
    answer?

## 7. Decisions we need from you

These are the places where the published evidence is thin, or where it
disagrees with the model. Please give a number or a clear yes/no for each.

**A. Altered mental status in sepsis true cases (now 25%).** Published figures
are higher: 31% of a Zambian sepsis cohort; about a third with GCS < 12 in an
older cohort. We found no US emergency-department figure. Raise it (to what?),
or keep 25% for an ED triage population?

**B. Normal blood pressure in 60% of sepsis true cases.** Supported by one ED
cohort (37% hypotensive at arrival). Is 60% right for the setting you know (ED
triage vs ward vs ICU)?

**C. Organ-dysfunction rule for normotensive sepsis** (§1b: lactate ≥ 2,
creatinine ≥ 1.6, altered mental status or urine < 30 mL/h). Missing anything a
clinician would use at triage?

**D. Pulse-oximeter over-reading for Asian and Hispanic patients.** Our model
drives the over-reading by skin tone only. That reproduces the Black–White gap
reported by Fawzy et al. (*JAMA Intern Med* 2022: +1.2 points) but gives Asian
patients about +0.4 and Hispanic patients about +0.5, where Fawzy reports +1.7
and +1.1. Add a separate component for these groups, or keep the model tied to
skin tone (the FDA's framing) and state the gap as a limitation?

**E. Monk tone spread by group (§2).** No population source exists for these
centres and spreads. Do they look right to you, especially for Native American
patients (centre 5.5)?

**F. Look-alike mix (§1).** Which common source of false alarms is missing for
each condition, and which listed one is too rare to matter?

**G. Fabry referral rule.** The ground truth refers a patient for Fabry testing
when any of these holds: angiokeratoma or cornea verticillata; a family history
of Fabry plus proteinuria, LVH or a cryptogenic stroke at a young age; or at
least 2 of these 7 red flags: neuropathic pain, angiokeratoma, cornea
verticillata, hypohidrosis, proteinuria, LVH, cryptogenic stroke at a young
age. Is that the bar a clinician would use?

## 8. Sign-off

| | |
|---|---|
| Reviewer name | |
| Specialty and years in practice | |
| Sections reviewed | ☐ 1 ☐ 2 ☐ 3 ☐ 4 ☐ 5 ☐ 6 ☐ 7 |
| Decisions A–G answered | ☐ A ☐ B ☐ C ☐ D ☐ E ☐ F ☐ G |
| Overall | ☐ Plausible ☐ Plausible with the changes noted ☐ Not plausible |
| Conflicts of interest | |
| Date and signature | |

Send the completed packet to the maintainers. Accepted changes are made in
`hipaasynth/decision_cohort.py`, `hipaasynth/aast/cases.py` and
`hipaasynth/polymorphic/blinding.py`, recorded in the CHANGELOG with the
reviewer's specialty, and the "pending clinician review" note is removed from
reports only after sign-off.

## Appendix: other modules (optional)

These do not feed 7AAST, but a reviewer with time may look at them:

- **Fabry natural-history module** (`modules/fabry/fabry.py`, separate from the
  7AAST Fabry cases): lifetime stroke or TIA about 15%. The Fabry Registry
  reports stroke alone in 6.9% of males and 4.3% of females at entry (Sims et
  al., *Stroke* 2009); the Fabry Outcome Survey reports cerebrovascular events
  in 27% of females. Is 15% reasonable for lifetime stroke or TIA?
- **Cardiology module:** oral anticoagulation in AF lowered in 1.8.0 to about
  60–66% of eligible patients, matching current US registries (57–64%).
- **Opioid use disorder module:** the opioid-type mix, route of use and
  benzodiazepine co-use (38%) have only partial sources; see the audit.
