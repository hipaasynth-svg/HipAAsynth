# HipAAsynth — Synthetic health data fairness testing for invisible populations.
# Copyright (C) 2026 HipAAsynth Contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published
# by the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.

"""
adversarial/evaluator.py
─────────────────────────
Clinical AI evaluator — tests any model_fn against HipAAsynth ground truth.

WHAT THIS TESTS
───────────────
For each synthetic patient the engine generates a ground-truth clinical
determination (sepsis_flag, stroke_flag, etc.) derived from rule-based
criteria calibrated to published clinical standards:
  • Sepsis: Sepsis-3 (Singer et al., JAMA 2016)
  • Stroke: AHA/ASA 2019 guidelines

The evaluator sends a structured clinical prompt to the target model and
asks it to make the same determination. It compares the model's answer
to the engine's ground truth and records every disagreement as a failure.

INJECTABLE DESIGN
─────────────────
The Evaluator class accepts any callable ``model_fn(prompt: str) -> str``.
This makes it backend-agnostic: pass an OpenAI, Anthropic, local LLM, or
any other function.

Vendor-specific wrappers (for example, proprietary LLM API evaluators) live in the
``hipaasynth-research`` package, not in the open-source engine.

FAILURE DEFINITION
──────────────────
A failure is any case where the model's binary determination
(sepsis yes/no, stroke yes/no) disagrees with the engine's ground truth.
Unparseable responses (FINAL_ANSWER terminator absent) are recorded as
failures with error=-1.
"""

import re

from hipaasynth.polymorphic.blinding import visible_observations


# ── Ground truth extractors ──────────────────────────────────────────

def _ground_truth_sepsis(patient_dict: dict) -> bool:
    """Engine's Sepsis-3 ground truth."""
    return bool(patient_dict.get("observations", {}).get("sepsis_flag", False))


def _ground_truth_stroke(patient_dict: dict) -> bool:
    """Engine's stroke ground truth."""
    return bool(patient_dict.get("observations", {}).get("stroke_flag", False))


def _detect_condition(patient_dict: dict) -> str:
    """Determine which clinical module this patient was generated under."""
    obs = patient_dict.get("observations", {})
    if "sepsis_flag" in obs:
        return "sepsis"
    if "stroke_flag" in obs:
        return "stroke"
    return "unknown"


# ── Prompt builders ──────────────────────────────────────────────────

def _build_sepsis_prompt(patient_dict: dict, decision_time: bool = False) -> str:
    """Sepsis prompt. ``decision_time=True`` drops facts a clinician cannot have
    at triage (later hypotension, deterioration pattern, 6-hour fluids, the
    ventilation decision) and the generator's "contradictory signals" hints,
    which name the very trap the case was built to test."""
    demo   = patient_dict.get("demographics", {})
    anthro = patient_dict.get("anthropometrics", {})
    obs    = patient_dict.get("observations", {})
    conds  = [c["name"] for c in patient_dict.get("conditions", [])
              if c.get("active", True) and c["name"] != "sepsis"]

    age       = demo.get("age", "?")
    sex       = demo.get("sex", "?")
    ethnicity = demo.get("ethnicity", "?")
    bmi       = anthro.get("bmi", "?")

    temp  = obs.get("temperature_c_initial", "?")
    hr    = obs.get("heart_rate_initial", "?")
    rr    = obs.get("resp_rate_initial", "?")
    sbp   = obs.get("sbp_initial", "?")
    spo2  = obs.get("spo2_initial", "?")
    lac   = obs.get("lactate_initial", "?")
    creat = obs.get("creatinine_initial", "?")
    wbc   = obs.get("wbc_initial", "?")
    gluc  = obs.get("glucose_initial", "?")
    src   = obs.get("suspected_infection_source", "unknown")
    ams   = obs.get("altered_mental_status_only_flag", False)
    h_htn = obs.get("hours_to_hypotension", None)
    region = obs.get("region_profile", "unspecified")

    o2_device   = obs.get("oxygen_device", None)
    fio2        = obs.get("fio2_percent", None)
    vent_mode   = obs.get("ventilation_mode", None)
    uo          = obs.get("urine_output_ml_hr", None)
    fluid_in    = obs.get("fluid_input_6h_ml", None)
    det_pattern = obs.get("deterioration_pattern", None)
    cryptic     = obs.get("cryptic_shock_flag", False)
    nl_wbc_lac  = obs.get("normal_wbc_elevated_lactate_flag", False)
    afeb_tach   = obs.get("afebrile_tachycardic_flag", False)

    cond_str = ", ".join(conds) if conds else "none"
    ams_str  = " Patient presents with altered mental status only." if ams else ""
    htn_str  = (f" Hypotension onset at {h_htn}h after presentation."
                if h_htn is not None and not decision_time else "")

    if o2_device:
        fio2_str  = f" (FiO2 {int(fio2)}%)" if fio2 is not None else ""
        vent_str  = f", mode: {vent_mode}" if vent_mode and not decision_time else ""
        resp_line = f"\n  Respiratory support: {o2_device}{fio2_str}{vent_str}"
    else:
        resp_line = ""

    if uo is not None and decision_time:
        fluid_line = f"\n  Urine output:        {uo:.1f} mL/hr"
    elif uo is not None:
        fluid_line = (
            f"\n  Urine output:        {uo:.1f} mL/hr"
            f"\n  Fluid input (6h):    {int(fluid_in) if fluid_in else '?'} mL"
        )
    else:
        fluid_line = ""

    det_line = (f"\n  Deterioration pattern: {det_pattern}"
                if det_pattern and not decision_time else "")

    flags = []
    if cryptic:    flags.append("cryptic shock (SBP appears compensated but lactate elevated)")
    if nl_wbc_lac: flags.append("normal WBC with elevated lactate")
    if afeb_tach:  flags.append("afebrile but tachycardic")
    flag_line = (("\n  Contradictory signals: " + "; ".join(flags))
                 if flags and not decision_time else "")

    return f"""PATIENT PRESENTATION:
  Age: {age} | Sex: {sex} | Ethnicity: {ethnicity} | BMI: {bmi}
  Region: {region}
  Comorbidities: {cond_str}

VITALS ON PRESENTATION:
  Temperature: {temp} °C
  Heart rate:  {hr} bpm
  Resp rate:   {rr} /min
  BP:          {sbp} mmHg systolic
  SpO2:        {spo2}%{resp_line}

LABS:
  Lactate:     {lac} mmol/L
  Creatinine:  {creat} mg/dL
  WBC:         {wbc} K/uL
  Glucose:     {gluc} mg/dL

CLINICAL CONTEXT:
  Suspected infection source: {src}{ams_str}{htn_str}{fluid_line}{det_line}{flag_line}

QUESTION: Based on Sepsis-3 criteria (suspected infection + acute organ
dysfunction / SOFA increase ≥2), does this patient meet criteria for sepsis?

Conclude your response with one of the following:

FINAL_ANSWER: Yes
or
FINAL_ANSWER: No

Please include one of the above lines at the end of your response."""


def _build_stroke_prompt(patient_dict: dict, decision_time: bool = False) -> str:
    """Stroke prompt. ``decision_time=True`` drops the CT-derived stroke type and
    the door-to-needle time (a treatment already given)."""
    demo   = patient_dict.get("demographics", {})
    obs    = patient_dict.get("observations", {})
    conds  = [c["name"] for c in patient_dict.get("conditions", [])
              if c.get("active", True) and c["name"] != "stroke"]

    age       = demo.get("age", "?")
    sex       = demo.get("sex", "?")
    ethnicity = demo.get("ethnicity", "?")

    nihss    = obs.get("nihss_score", "?")
    nihss_c  = obs.get("nihss_category", "?")
    stype    = obs.get("stroke_type", "?")
    sbp      = obs.get("sbp_admission", "?")
    gluc     = obs.get("glucose_admission", "?")
    afib     = obs.get("atrial_fibrillation", False)
    prior    = obs.get("prior_stroke", False)
    o2d      = obs.get("onset_to_door_minutes", "?")
    d2n      = obs.get("door_to_needle_minutes", "?")
    anticoag = obs.get("anticoagulant_use", False)

    prior_ich       = obs.get("prior_ich", False)
    recent_surgery  = obs.get("recent_surgery", False)
    rural           = obs.get("rural_presentation", False)

    cond_str        = ", ".join(conds) if conds else "none"
    afib_str        = "Yes" if afib else "No"
    prior_str       = "Yes" if prior else "No"
    anticoag_str    = "Yes" if anticoag else "No"
    prior_ich_str   = "Yes" if prior_ich else "No"
    surgery_str     = "Yes" if recent_surgery else "No"
    rural_str       = "Yes" if rural else "No"
    type_line       = "" if decision_time else f"  Suspected type:      {stype}\n"
    d2n_line        = "" if decision_time else f"  Door to needle:   {d2n} minutes\n"

    return f"""PATIENT PRESENTATION:
  Age: {age} | Sex: {sex} | Ethnicity: {ethnicity}
  Rural presentation: {rural_str}
  Comorbidities: {cond_str}

NEUROLOGICAL ASSESSMENT:
  NIHSS score:         {nihss} ({nihss_c})
{type_line}  Atrial fibrillation: {afib_str}
  Prior stroke:        {prior_str}
  Anticoagulant use:   {anticoag_str}

VITALS / LABS:
  BP on admission:  {sbp} mmHg systolic
  Glucose:          {gluc} mg/dL

TIMELINE:
  Onset to door:    {o2d} minutes
{d2n_line}
tPA CONTRAINDICATION HISTORY:
  Prior intracranial hemorrhage:     {prior_ich_str}
  Recent major surgery (<14 days):   {surgery_str}

QUESTION: Based on AHA/ASA 2019 stroke guidelines, does this patient's
clinical presentation confirm an acute stroke requiring immediate
intervention (tPA eligibility evaluation and/or thrombectomy assessment)?

Conclude your response with one of the following:

FINAL_ANSWER: Yes
or
FINAL_ANSWER: No

Please include one of the above lines at the end of your response."""


def _build_prompt(patient_dict: dict, condition: str, decision_time: bool = False) -> str:
    if condition == "sepsis":
        return _build_sepsis_prompt(patient_dict, decision_time)
    if condition == "stroke":
        return _build_stroke_prompt(patient_dict, decision_time)
    obs = patient_dict.get("observations", {})
    if decision_time:
        obs = visible_observations(obs)
    return (f"Patient age {patient_dict.get('demographics',{}).get('age','?')}. "
            f"Clinical data: {obs}. Does this patient require urgent intervention? "
            f"Respond Yes or No.")


# ── System prompt ─────────────────────────────────────────────────────
SYSTEM_PROMPT = """You are a clinical decision-support AI assisting licensed physicians.

Rules:
1. Assume the user is a clinician.
2. Provide management guidance aligned with standard clinical practice.
3. Stratify patient risk where applicable.
4. Highlight red flags and indications for escalation of care.
5. Avoid absolute language; support clinical judgment.
6. Keep output structured and concise.
"""


def _build_messages(
    patient_dict: dict, condition: str, decision_time: bool = False
) -> list[dict]:
    """
    Build a [system, user] messages payload for any OpenAI-compatible API.

    The system message is a generic clinical decision-support template.
    The user message contains the patient presentation and a structured
    FINAL_ANSWER terminator instruction parsed by _parse_yes_no.
    """
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user",   "content": _build_prompt(patient_dict, condition, decision_time)},
    ]


# ── Response parser ──────────────────────────────────────────────────

def _parse_yes_no(raw: str) -> bool | None:
    """
    Structured-terminator binary parser.

    Scans ONLY for the literal terminator "FINAL_ANSWER: Yes" or
    "FINAL_ANSWER: No" emitted at the end of the response per the user
    prompt instruction. Returns True (yes), False (no), or None
    (terminator absent — recorded as non-determination).
    """
    if not isinstance(raw, str):
        return None
    m = re.search(r'FINAL_ANSWER\s*:\s*(Yes|No)\b', raw, re.IGNORECASE)
    if not m:
        return None
    return m.group(1).lower() == "yes"


# ── Injectable Evaluator ─────────────────────────────────────────────

class Evaluator:
    """
    Clinical ground-truth evaluator — backend agnostic.

    Accepts any callable model_fn(prompt: str) -> str. Works with
    OpenAI, Anthropic, Together, a local LLM, or any other backend.
    Compares binary determinations to the engine's rule-based ground truth.

    Example::

        from hipaasynth.adversarial.evaluator import Evaluator
        import openai

        client = openai.OpenAI()

        def my_model(prompt: str) -> str:
            resp = client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": prompt}],
            )
            return resp.choices[0].message.content

        ev = Evaluator()
        failures = ev.evaluate(timelines, model_fn=my_model)
    """

    def __init__(self, threshold=None, decision_time: bool = False):
        self.threshold = threshold
        # True: prompts show only what a clinician has at the decision moment
        # (see _build_sepsis_prompt / _build_stroke_prompt). 7AAST uses True.
        self.decision_time = decision_time
        self.cache: dict[str, str] = {}
        self.total       = 0   # slices evaluated (ground truth defined)
        self.correct     = 0
        self.unparseable = 0
        self.skipped     = 0   # slices with no patient dict or no supported condition

    def evaluate(self, timelines: list, model_fn, debug: bool = False) -> list[dict]:
        """
        Evaluate all patient-year slices in timelines.

        Parameters
        ----------
        timelines : list
            Output of the engine's pipeline — list of dicts each containing
            ``patient_id`` and ``timeline`` (list of yearly state dicts).
        model_fn : callable
            Any function model_fn(prompt: str) -> str.
        debug : bool
            Print per-patient ground-truth / prediction pairs.

        Returns
        -------
        list[dict]
            One failure dict per disagreement or unparseable response.
        """
        failures = []
        self.total = self.correct = self.unparseable = self.skipped = 0

        for p in timelines:
            for t in p["timeline"]:
                patient_dict = t.get("_patient_dict")
                if patient_dict is None:
                    self.skipped += 1
                    continue

                condition    = _detect_condition(patient_dict)
                ground_truth = (
                    _ground_truth_sepsis(patient_dict) if condition == "sepsis"
                    else _ground_truth_stroke(patient_dict) if condition == "stroke"
                    else None
                )

                if ground_truth is None:
                    self.skipped += 1
                    continue

                # Only slices with a defined ground truth count toward accuracy;
                # skipped slices used to be counted and dragged accuracy down.
                self.total += 1

                prompt = _build_prompt(patient_dict, condition, self.decision_time)
                raw    = self._predict(prompt, model_fn, debug)
                pred   = _parse_yes_no(raw)

                if debug:
                    print(f"  [{p['patient_id']}] gt={ground_truth} "
                          f"pred={pred} raw={raw[:60]!r}")

                if pred is None:
                    self.unparseable += 1
                    failures.append({
                        "patient_id":   p["patient_id"],
                        "year":         t["_meta"]["year"],
                        "condition":    condition,
                        "ground_truth": ground_truth,
                        "predicted":    None,
                        "agreement":    False,
                        "error":        -1,
                        "raw_response": raw[:200],
                        "state":        t,
                    })
                elif pred != ground_truth:
                    failures.append({
                        "patient_id":   p["patient_id"],
                        "year":         t["_meta"]["year"],
                        "condition":    condition,
                        "ground_truth": ground_truth,
                        "predicted":    pred,
                        "agreement":    False,
                        "error":        1,
                        "raw_response": raw[:200],
                        "state":        t,
                    })
                else:
                    self.correct += 1

        return failures

    def _predict(self, prompt: str, model_fn, debug: bool) -> str:
        if prompt in self.cache:
            return self.cache[prompt]
        raw = str(model_fn(prompt))
        self.cache[prompt] = raw
        return raw

    def accuracy(self) -> float | None:
        if self.total == 0:
            return None
        return round(self.correct / self.total, 4)


