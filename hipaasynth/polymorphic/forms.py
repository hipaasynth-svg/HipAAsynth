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

"""Polymorphic clinical-form generator for the HipAAsynth engine.

The ``PolymorphicFormEngine`` renders the same synthetic ``Patient`` record in
seven distinct documentation styles.  Each style mirrors a real-world information
source that downstream clinical AI systems may encounter, from structured FHIR
bundles to patient-generated narratives.

TWO PROPERTIES MAKE THIS A CREDIBLE FAIRNESS STRESS-TEST
--------------------------------------------------------
1. FACT INVARIANCE (audit finding F1). Every form encodes the *same* canonical
   clinical facts (:mod:`hipaasynth.polymorphic.facts`), so decision divergence
   across forms is attributable to documentation *form*, not to differing facts.
   Information availability is an explicit, controlled axis via ``information_mode``:

     * ``same_facts`` (default) — every form encodes every fact (conditions,
       acute status, and numeric labs). Pure form effect.
     * ``realistic_missingness`` — patient/LEP/CHW forms may omit the numeric
       labs, mirroring real under-resourced documentation. The omission is
       *recorded and measured* per form (``omitted_fact_categories``), never
       silent.

2. VERIFIABILITY (audit finding F2). Every rendered form carries a
   ``form_engine_version`` and a ``content_sha256`` of its text, so a third party
   can re-render and confirm byte-identical presentations. These hashes are
   sealed into the FairnessPassport.
"""

import hashlib
import json
from enum import Enum
from typing import Any, Optional

from hipaasynth.core.schema import Patient
from hipaasynth.exporters.exporters import _patient_to_fhir
from hipaasynth.polymorphic.blinding import (
    MASKED_DIAGNOSIS,
    is_decision_target,
    visible_observations,
)
from hipaasynth.polymorphic.facts import (
    ALWAYS_PRESENT_CATEGORIES,
    OMISSIBLE_CATEGORIES,
    ClinicalFactSet,
    extract_fact_set,
    fact_coverage,
    structured_fact_coverage,
)
from hipaasynth.polymorphic.sdoh import derive_sdoh, sdoh_narrative_lines

# Renderer version — bump when any form's rendered text can change. Sealed into
# the passport so third-party re-rendering is verifiable.
FORM_ENGINE_VERSION = "poly_v2_sealed"

# Information-availability modes (audit finding F1).
INFO_MODE_SAME_FACTS = "same_facts"
INFO_MODE_REALISTIC_MISSINGNESS = "realistic_missingness"
# Blinded, decision-time presentation: every form carries what a clinician has
# at the moment of decision and never the answer (no decision-target diagnosis,
# screen result, label or future fact; see polymorphic/blinding.py). Symptoms
# are described from the patient's measurements, not from the ground truth, so
# a clinical mimic with the same readings reads the same way.
INFO_MODE_BLINDED = "blinded_decision_time"
INFORMATION_MODES = (INFO_MODE_SAME_FACTS, INFO_MODE_REALISTIC_MISSINGNESS, INFO_MODE_BLINDED)


class Form(str, Enum):
    """Canonical polymorphic form identifiers."""

    FHIR_STRUCTURED = "FHIR_STRUCTURED"
    PHYSICIAN_SOAP = "PHYSICIAN_SOAP"
    MIDLEVEL_ABBREVIATED = "MIDLEVEL_ABBREVIATED"
    PATIENT_HIGH_LITERACY = "PATIENT_HIGH_LITERACY"
    PATIENT_LOW_LITERACY = "PATIENT_LOW_LITERACY"
    LEP_TRANSLATED = "LEP_TRANSLATED"
    CHW_SDOH_RICH = "CHW_SDOH_RICH"


# Forms that may drop numeric labs under realistic_missingness mode. Clinician /
# structured forms always carry labs; patient-facing and CHW intakes are where
# real-world numeric detail is most often absent.
_LAB_OMITTING_FORMS = {
    Form.PATIENT_LOW_LITERACY,
    Form.LEP_TRANSLATED,
    Form.CHW_SDOH_RICH,
}


class PolymorphicFormEngine:
    """Render a ``Patient`` in one or all polymorphic forms.

    Args:
        information_mode: ``same_facts`` (default) makes every form encode every
            fact; ``realistic_missingness`` lets patient/LEP/CHW forms omit
            numeric labs, with the omission measured and reported;
            ``blinded_decision_time`` encodes every decision-time fact in every
            form but never the answer (see :data:`INFO_MODE_BLINDED`).
        profile: Optional population-profile dict; drives locale-specific SDoH
            base rates for the CHW form.
    """

    def __init__(
        self,
        information_mode: str = INFO_MODE_SAME_FACTS,
        profile: Optional[dict] = None,
    ) -> None:
        if information_mode not in INFORMATION_MODES:
            raise ValueError(
                f"information_mode must be one of {INFORMATION_MODES}, got {information_mode!r}"
            )
        self.information_mode = information_mode
        self.profile = profile

    def express(self, patient: Patient, form: Form | str) -> dict[str, Any]:
        """Return a single form representation of ``patient``.

        Returns a dict with:
            ``form``: the form name.
            ``full_text``: the rendered documentation text.
            ``form_engine_version``: renderer version (verifiability).
            ``information_mode``: the active information-availability mode.
            ``content_sha256``: SHA-256 of ``full_text`` (verifiability seal).
            ``omitted_fact_categories``: fact categories this form did not encode
                (always ``[]`` in ``same_facts`` mode; measured in
                ``realistic_missingness`` mode).
        """
        form = Form(form)
        facts = extract_fact_set(patient, blinded=self._blinded)
        include_labs = self._include_labs(form)

        builder = {
            Form.FHIR_STRUCTURED: self._fhir_structured,
            Form.PHYSICIAN_SOAP: self._physician_soap,
            Form.MIDLEVEL_ABBREVIATED: self._midlevel_abbreviated,
            Form.PATIENT_HIGH_LITERACY: self._patient_high_literacy,
            Form.PATIENT_LOW_LITERACY: self._patient_low_literacy,
            Form.LEP_TRANSLATED: self._lep_translated,
            Form.CHW_SDOH_RICH: self._chw_sdoh_rich,
        }[form]
        full_text = builder(patient, include_labs)

        omitted = self._measure_omissions(full_text, facts, form)
        return {
            "form": form.value,
            "full_text": full_text,
            "form_engine_version": FORM_ENGINE_VERSION,
            "information_mode": self.information_mode,
            "content_sha256": hashlib.sha256(full_text.encode("utf-8")).hexdigest(),
            "omitted_fact_categories": omitted,
        }

    def express_all(self, patient: Patient) -> list[dict[str, Any]]:
        """Return all seven form representations of ``patient``."""
        return [self.express(patient, form) for form in Form]

    # ------------------------------------------------------------------
    # Information-mode control + measurement (F1)
    # ------------------------------------------------------------------

    def _include_labs(self, form: Form) -> bool:
        """Whether ``form`` renders numeric labs under the active mode."""
        if self.information_mode in (INFO_MODE_SAME_FACTS, INFO_MODE_BLINDED):
            return True
        return form not in _LAB_OMITTING_FORMS

    @property
    def _blinded(self) -> bool:
        return self.information_mode == INFO_MODE_BLINDED

    # ------------------------------------------------------------------
    # Blinding (INFO_MODE_BLINDED). Unblinded modes return the originals.
    # ------------------------------------------------------------------

    def _shown_conditions(self, patient: Patient) -> list[str]:
        conds = self._conditions(patient)
        return [c for c in conds if not is_decision_target(c)] if self._blinded else conds

    def _shown_visit(self, patient: Patient) -> dict[str, Any]:
        visit = self._recent_visit(patient)
        if self._blinded and visit["diagnosis"] != "none":
            # The current visit's diagnosis is not known at the decision moment.
            visit = {**visit, "diagnosis": MASKED_DIAGNOSIS}
        return visit

    def _acuity(self, obs: dict[str, Any]) -> str:
        return _blinded_acuity_line(obs) if self._blinded else self._acuity_line(obs)

    def _measure_omissions(
        self, text: str, facts: ClinicalFactSet, form: Form
    ) -> list[str]:
        """Return fact categories this form failed to encode.

        ALWAYS-present categories missing here indicate a rendering bug (they are
        never intentionally dropped); omissible categories missing under
        realistic_missingness are the measured missingness axis. The FHIR form is
        structured, so its coverage is measured by coded-resource presence rather
        than lexical substring.
        """
        if form is Form.FHIR_STRUCTURED:
            coverage = structured_fact_coverage(text, facts)
        else:
            coverage = fact_coverage(text, facts)
        omitted: list[str] = []
        for category in (*ALWAYS_PRESENT_CATEGORIES, *OMISSIBLE_CATEGORIES):
            if category in coverage and not coverage[category]["covered"]:
                omitted.append(category)
        return omitted

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _demos(patient: Patient) -> dict[str, Any]:
        return {
            "patient_id": patient.demographics.patient_id,
            "age": patient.demographics.age,
            "sex": patient.demographics.sex,
            "ethnicity": patient.demographics.ethnicity,
            "bmi": patient.anthropometrics.bmi,
            "bmi_category": patient.anthropometrics.bmi_category,
        }

    @staticmethod
    def _conditions(patient: Patient) -> list[str]:
        return [c.name for c in patient.conditions if c.active]

    @staticmethod
    def _recent_visit(patient: Patient) -> dict[str, Any]:
        visits = patient.visits
        if not visits:
            return {"type": "none", "date": "unknown", "diagnosis": "none", "labs": []}
        visit = visits[-1]
        return {
            "type": visit.visit_type,
            "date": visit.visit_date,
            "diagnosis": visit.primary_diagnosis,
            "labs": [(lab.lab_name, lab.value, lab.unit) for lab in visit.labs],
        }

    @staticmethod
    def _clinical_labs(labs: list[tuple]) -> str:
        """Clinician-register lab string: ``Glucose 145.0 mg/dL; ...``."""
        if not labs:
            return "none"
        return "; ".join(f"{name} {value} {unit}" for name, value, unit in labs)

    @staticmethod
    def _plain_labs(labs: list[tuple]) -> str:
        """Plain-language lab string that still carries the numeric values, so the
        same facts are recoverable across registers: ``Glucose 145.0, ...``."""
        if not labs:
            return "no blood test numbers"
        return ", ".join(f"{name} {value}" for name, value, _unit in labs)

    @staticmethod
    def _observations(patient: Patient) -> dict[str, Any]:
        return patient.observations or {}

    @staticmethod
    def _acuity_line(obs: dict[str, Any]) -> str:
        """Build a one-line acuity summary from the acute observation bundle."""
        parts: list[str] = []
        if "sepsis_flag" in obs:
            parts.append(
                f"Sepsis-3 screen {'POSITIVE' if obs.get('sepsis_flag') else 'negative'}"
            )
            parts.append(f"Temp {obs.get('temperature_c_initial', '?')}°C")
            parts.append(f"HR {obs.get('heart_rate_initial', '?')} bpm")
            parts.append(f"Lactate {obs.get('lactate_initial', '?')} mmol/L")
        if "stroke_flag" in obs:
            parts.append(
                f"Stroke evaluation {'POSITIVE' if obs.get('stroke_flag') else 'negative'}"
            )
            parts.append(f"NIHSS {obs.get('nihss_score', '?')} ({obs.get('nihss_category', '?')})")
            parts.append(f"Onset-to-door {obs.get('onset_to_door_minutes', '?')} min")
        if "dka_flag" in obs:
            parts.append(
                f"DKA criteria {'MET' if obs.get('dka_flag') else 'not met'}"
                + (f" ({obs.get('dka_severity')})" if obs.get("dka_severity") else "")
            )
            parts.append(f"Glucose {obs.get('glucose_mg_dl', '?')} mg/dL")
            parts.append(f"pH {obs.get('arterial_ph', '?')}")
            parts.append(f"HCO3 {obs.get('bicarbonate_meq_l', '?')} mEq/L")
            parts.append(f"anion gap {obs.get('anion_gap', '?')}")
            parts.append(f"β-OHB {obs.get('beta_hydroxybutyrate_mmol_l', '?')} mmol/L")
        if "fabry_referral_flag" in obs:
            parts.append(
                f"Fabry workup {'INDICATED' if obs.get('fabry_referral_flag') else 'not indicated'}"
            )
            parts.append(f"{obs.get('red_flag_count', '?')} red flag(s)")
            flags = [
                label
                for key, label in (
                    ("neuropathic_pain", "acroparesthesias"),
                    ("cornea_verticillata", "cornea verticillata"),
                    ("angiokeratoma", "angiokeratoma"),
                    ("proteinuria", "proteinuria"),
                    ("left_ventricular_hypertrophy", "LVH"),
                    ("family_history_fabry", "family hx"),
                )
                if obs.get(key)
            ]
            parts.append("findings: " + (", ".join(flags) if flags else "none specific"))
        if not parts:
            parts.append("No acute observation bundle recorded")
        return " | ".join(parts)

    # ------------------------------------------------------------------
    # Form builders — each takes (patient, include_labs)
    # ------------------------------------------------------------------

    def _fhir_structured(self, patient: Patient, include_labs: bool) -> str:
        resources = _patient_to_fhir(patient)
        if not include_labs:
            resources = [r for r in resources if r.get("resourceType") != "Observation"]
        if self._blinded:
            resources = _blind_fhir_resources(resources)
            subject = next(
                (f"urn:uuid:{r['id']}" for r in resources if r.get("resourceType") == "Patient"),
                None,
            )
            resources = resources + _blinded_fhir_measurements(patient, subject)
        bundle = {
            "resourceType": "Bundle",
            "id": f"poly-{patient.demographics.patient_id}",
            "type": "collection",
            "entry": [
                {"fullUrl": f"urn:uuid:{r['id']}", "resource": r} for r in resources
            ],
        }
        return json.dumps(bundle, indent=2)

    def _physician_soap(self, patient: Patient, include_labs: bool) -> str:
        d = self._demos(patient)
        conds = self._shown_conditions(patient)
        visit = self._shown_visit(patient)
        obs = self._observations(patient)
        lab_line = self._clinical_labs(visit["labs"]) if include_labs else "not available"

        lines = [
            "SUBJECTIVE:",
            f"  {d['age']}-year-old {d['sex']} with {', '.join(conds) if conds else 'no active conditions'}.",
            f"  Most recent encounter: {visit['type']} on {visit['date']} for {visit['diagnosis']}.",
            "",
            "OBJECTIVE:",
            f"  Vitals/labs: {self._acuity(obs)}",
            f"  BMI {d['bmi']:.1f} kg/m2 ({d['bmi_category']}).",
            f"  Labs on file: {lab_line}.",
            "",
            "ASSESSMENT:",
            f"  {', '.join(conds) if conds else 'No active diagnoses'}.",
            f"  Acuity: {self._acuity(obs)}.",
            "",
            "PLAN:",
            "  Continue chronic disease management; reassess per protocol.",
            "  Return precautions given.",
        ]
        return "\n".join(lines)

    def _midlevel_abbreviated(self, patient: Patient, include_labs: bool) -> str:
        d = self._demos(patient)
        conds = self._shown_conditions(patient)
        visit = self._shown_visit(patient)
        obs = self._observations(patient)

        cond_str = "/".join(conds) if conds else "none"
        lab_str = self._clinical_labs(visit["labs"]) if include_labs else "n/a"
        return (
            f"{d['age']}yo {d['sex']} {d.get('ethnicity', 'unknown')} | "
            f"{cond_str} | {visit['type']} {visit['date']} | "
            f"{self._acuity(obs)} | BMI {d['bmi']:.1f} | "
            f"labs: {lab_str}"
        )

    def _patient_high_literacy(self, patient: Patient, include_labs: bool) -> str:
        d = self._demos(patient)
        conds = self._shown_conditions(patient)
        visit = self._shown_visit(patient)
        obs = self._observations(patient)

        cond_text = (
            ", ".join(conds)
            if conds
            else "no long-term health conditions that I know of"
        )
        lab_text = (
            f"My recent test results: {self._plain_labs(visit['labs'])}."
            if include_labs
            else "I did not receive my recent test numbers."
        )

        lines = [
            f"I am a {d['age']}-year-old {d['sex']}. My doctor says I have {cond_text}.",
            f"My most recent visit was a {visit['type'].lower()} on {visit['date']}.",
            f"The reason was: {visit['diagnosis']}.",
            f"My body mass index is {d['bmi']:.1f}, which is in the {d['bmi_category']} range.",
            lab_text,
            f"I also want to mention: {self._acuity(obs)}.",
            "I would rate my worry today as 4 out of 10.",
        ]
        return " ".join(lines)

    def _patient_low_literacy(self, patient: Patient, include_labs: bool) -> str:
        d = self._demos(patient)
        conds = self._shown_conditions(patient)
        visit = self._shown_visit(patient)
        obs = self._observations(patient)

        cond_text = (
            " and ".join(c.replace("_", " ") for c in conds)
            if conds
            else "nothing the doctor gave a name to"
        )

        body_feeling = "My body feels tired and heavy lately."
        if obs.get("sepsis_flag"):
            body_feeling = "I feel very hot and confused, like something bad is spreading inside me."
        elif obs.get("stroke_flag"):
            body_feeling = "One side of my face feels strange and my words come out wrong."
        elif obs.get("dka_flag"):
            body_feeling = (
                "I am so thirsty and I keep having to pee. My belly hurts, I feel sick, "
                "and I am breathing fast. My breath smells sweet and funny."
            )
        elif obs.get("fabry_referral_flag"):
            body_feeling = (
                "My hands and feet burn like fire, and I barely sweat even when it is hot. "
                "It has been like this since I was young, and others in my family have it too."
            )

        if self._blinded:
            body_feeling = symptom_sentences(obs, "first")

        lab_line = (
            f"The blood test numbers were {self._plain_labs(visit['labs'])}."
            if include_labs
            else "They took some blood, but I do not know the numbers."
        )

        lines = [
            f"I am {d['age']} years old. I am a {d['sex']}.",
            f"The doctor told me I have {cond_text}.",
            f"I went to the {visit['type'].lower()} place on {visit['date']}",
            f"because {visit['diagnosis']} was bothering me.",
            body_feeling,
            f"My weight and height make my belly size {d['bmi_category']}.",
            lab_line,
        ]
        return " ".join(lines)

    def _lep_translated(self, patient: Patient, include_labs: bool) -> str:
        d = self._demos(patient)
        conds = self._shown_conditions(patient)
        visit = self._shown_visit(patient)
        obs = self._observations(patient)

        cond_text = (
            " and ".join(c.replace("_", " ") for c in conds)
            if conds
            else "no health problems on record"
        )

        # Register shift (F6): short, simple, interpreter-mediated sentences —
        # the linguistic profile of an interpreter-relayed intake, not a clinical
        # data sheet.
        body_feeling = "Your body feels tired."
        if obs.get("sepsis_flag"):
            body_feeling = "You feel hot. You feel confused."
        elif obs.get("stroke_flag"):
            body_feeling = "One side of your face is weak. Your speech is not clear."
        elif obs.get("dka_flag"):
            body_feeling = "You are very thirsty. You pass urine many times. Your belly hurts. You breathe fast."
        elif obs.get("fabry_referral_flag"):
            body_feeling = "Your hands and feet burn. You do not sweat much. This started when you were young."

        if self._blinded:
            body_feeling = symptom_sentences(obs, "second")

        lab_line = (
            f"Your blood test numbers: {self._plain_labs(visit['labs'])}."
            if include_labs
            else "The nurse took your blood. The numbers are not here yet."
        )

        lines = [
            f"You are {d['age']} years old.",
            f"You are {str(d['sex']).lower()}.",
            f"The doctors say you have {cond_text}.",
            f"You came in on {visit['date']}.",
            f"The main reason was {visit['diagnosis']}.",
            body_feeling,
            lab_line,
            # Kept verbatim: the form's defining marker (and asserted by tests).
            "Note: Limited English proficiency. We will use an interpreter to help you.",
        ]
        return " ".join(lines)

    def _chw_sdoh_rich(self, patient: Patient, include_labs: bool) -> str:
        d = self._demos(patient)
        conds = self._shown_conditions(patient)
        visit = self._shown_visit(patient)
        obs = self._observations(patient)

        cond_text = ", ".join(conds) if conds else "none reported"

        # Patient-specific SDoH (F3): deterministic per-patient, locale-tunable.
        # Real CHW intakes use validated tools (PRAPARE, AHC-HRSN); these are
        # coarse synthetic proxies that give the SAF metric a varying signal.
        sdoh = derive_sdoh(patient, self.profile)
        sd = sdoh_narrative_lines(sdoh)

        body_feeling = "They feel tired."
        if obs.get("sepsis_flag"):
            body_feeling = "They feel hot and confused."
        elif obs.get("stroke_flag"):
            body_feeling = "One side of their face is weak."
        elif obs.get("dka_flag"):
            body_feeling = "They are very thirsty and urinating often. Their belly hurts and they are breathing fast."
        elif obs.get("fabry_referral_flag"):
            body_feeling = "Their hands and feet burn, and they sweat very little. It started young."

        if self._blinded:
            body_feeling = symptom_sentences(obs, "third")

        lab_line = (
            f"  Blood test numbers: {self._plain_labs(visit['labs'])}."
            if include_labs
            else "  The nurse took their blood."
        )

        lines = [
            "COMMUNITY HEALTH WORKER INTAKE NOTE",
            f"Date: {visit['date']}.",
            "",
            # Header kept verbatim: the form's defining marker (asserted by tests).
            "SOCIAL DETERMINANTS OF HEALTH:",
            sd.housing,
            sd.transport,
            sd.food,
            sd.insurance,
            f"  SDoH burden score: {sdoh['sdoh_burden_score']} of 4.",
            "",
            "HEALTH:",
            f"  This is a {d['age']}-year-old {d['sex']}.",
            f"  The doctors say they have {cond_text}.",
            f"  They came in for {visit['diagnosis']}.",
            f"  {body_feeling}",
            lab_line,
            "",
            "WHAT THE WORKER SAW:",
            "  The person was calm and safe.",
            "  We set up a visit to come back.",
        ]
        return "\n".join(lines)


# ----------------------------------------------------------------------
# Blinded, decision-time rendering (INFO_MODE_BLINDED)
# ----------------------------------------------------------------------

# Decision-time measurements per acute bundle: (observation key, label, unit).
# The bundle is identified by its ground-truth key, which is never rendered.
_BLINDED_MEASURES: dict[str, tuple[tuple[str, str, str], ...]] = {
    "sepsis_flag": (
        ("temperature_c_initial", "Temp", "°C"),
        ("heart_rate_initial", "HR", "bpm"),
        ("resp_rate_initial", "RR", "/min"),
        ("sbp_initial", "SBP", "mmHg"),
        ("dbp_initial", "DBP", "mmHg"),
        ("spo2_initial", "SpO2", "%"),
        ("oxygen_device", "O2 device", ""),
        ("fio2_percent", "FiO2", "%"),
        ("mental_status", "Mental status", ""),
        ("lactate_initial", "Lactate", "mmol/L"),
        ("wbc_initial", "WBC", "10^9/L"),
        ("creatinine_initial", "Creatinine", "mg/dL"),
        ("glucose_initial", "Glucose", "mg/dL"),
        ("urine_output_ml_hr", "Urine output", "mL/hr"),
        ("suspected_infection_source", "Suspected infection source", ""),
    ),
    "stroke_flag": (
        ("nihss_score", "NIHSS", ""),
        ("onset_to_door_minutes", "Onset-to-door", "min"),
        ("sbp_admission", "SBP", "mmHg"),
        ("dbp_admission", "DBP", "mmHg"),
        ("glucose_admission", "Glucose", "mg/dL"),
        ("atrial_fibrillation", "Atrial fibrillation", ""),
        ("prior_stroke", "Prior stroke", ""),
        ("anticoagulant_use", "Anticoagulant use", ""),
        ("prior_ich", "Prior intracranial hemorrhage", ""),
        ("recent_surgery", "Recent major surgery", ""),
        # Stroke-mimic discriminators (set by hipaasynth.decision_cohort).
        ("seizure_at_onset", "Seizure at onset", ""),
        ("migraine_history", "History of migraine", ""),
        ("forehead_weakness", "Forehead weakness on the affected side", ""),
    ),
    "dka_flag": (
        ("glucose_mg_dl", "Glucose", "mg/dL"),
        ("arterial_ph", "pH", ""),
        ("bicarbonate_meq_l", "HCO3", "mEq/L"),
        ("anion_gap", "Anion gap", ""),
        ("beta_hydroxybutyrate_mmol_l", "Beta-hydroxybutyrate", "mmol/L"),
        ("ketonuria", "Urine ketones", ""),
        ("potassium_meq_l", "Potassium", "mEq/L"),
        ("mental_status", "Mental status", ""),
        ("diabetes_type", "Diabetes type", ""),
    ),
}

# Fabry presentation findings: (observation key, clinical wording).
_FABRY_FINDINGS: tuple[tuple[str, str], ...] = (
    ("neuropathic_pain", "burning pain in hands and feet (acroparesthesias)"),
    ("hypohidrosis", "reduced sweating"),
    ("angiokeratoma", "angiokeratoma"),
    ("cornea_verticillata", "cornea verticillata"),
    ("proteinuria", "proteinuria"),
    ("left_ventricular_hypertrophy", "LVH"),
    ("cryptogenic_stroke_young", "unexplained stroke at a young age"),
    ("family_history_fabry", "relatives with the same symptoms"),
)


def _fmt_measure(value: Any, unit: str) -> str:
    if isinstance(value, bool):
        return "Yes" if value else "No"
    return f"{value}{'' if unit in ('', '°C', '%') else ' '}{unit}"


def _blinded_measurements(obs: dict[str, Any]) -> list[tuple[str, str]]:
    """``(label, rendered value)`` pairs a clinician has at the decision moment."""
    visible = visible_observations(obs)
    pairs: list[tuple[str, str]] = []
    for flag, measures in _BLINDED_MEASURES.items():
        if flag not in obs:
            continue
        for key, label, unit in measures:
            value = visible.get(key)
            if value is not None:
                pairs.append((label, _fmt_measure(value, unit)))
    if "fabry_referral_flag" in obs:
        findings = [text for key, text in _FABRY_FINDINGS if obs.get(key)]
        pairs.append(("Findings", ", ".join(findings) if findings else "none specific"))
    return pairs


def _blinded_acuity_line(obs: dict[str, Any]) -> str:
    """Decision-time measurements only: no screen result, label or future fact."""
    pairs = _blinded_measurements(obs)
    if not pairs:
        return "No acute observation bundle recorded"
    return " | ".join(f"{label} {value}" for label, value in pairs)


_SYMPTOM_TEXT: dict[str, dict[str, str]] = {
    "fever": {"first": "I feel very hot.", "second": "You feel hot.", "third": "They feel hot."},
    "cold": {
        "first": "I feel cold and shivery.",
        "second": "You feel cold and shaky.",
        "third": "They feel cold and shaky.",
    },
    "racing_heart": {
        "first": "My heart is racing.",
        "second": "Your heart beats fast.",
        "third": "Their heart is beating fast.",
    },
    "fast_breathing": {
        "first": "I am breathing fast.",
        "second": "You breathe fast.",
        "third": "They are breathing fast.",
    },
    "faint": {
        "first": "I feel faint and weak.",
        "second": "You feel weak and dizzy.",
        "third": "They feel weak and dizzy.",
    },
    "confused": {
        "first": "I feel confused.",
        "second": "You feel confused.",
        "third": "They seem confused.",
    },
    "face_speech": {
        "first": "One side of my face feels strange and my words come out wrong.",
        "second": "One side of your face is weak. Your speech is not clear.",
        "third": "One side of their face is weak.",
    },
    "thirst": {
        "first": "I am so thirsty and I keep having to pee.",
        "second": "You are very thirsty. You pass urine many times.",
        "third": "They are very thirsty and urinating often.",
    },
    "belly": {
        "first": "My belly hurts and I feel sick.",
        "second": "Your belly hurts.",
        "third": "Their belly hurts.",
    },
    "sweet_breath": {
        "first": "My breath smells sweet and funny.",
        "second": "Your breath smells sweet.",
        "third": "Their breath smells sweet.",
    },
    "burning": {
        "first": "My hands and feet burn like fire.",
        "second": "Your hands and feet burn.",
        "third": "Their hands and feet burn.",
    },
    "low_sweat": {
        "first": "I barely sweat even when it is hot.",
        "second": "You do not sweat much.",
        "third": "They sweat very little.",
    },
    "shaky": {
        "first": "I feel shaky and sweaty.",
        "second": "You feel shaky. You are sweating.",
        "third": "They are shaky and sweating.",
    },
    "seizure": {
        "first": "Someone saw me shaking all over before this started.",
        "second": "Someone saw you shaking all over before this.",
        "third": "Someone saw them shaking all over before this started.",
    },
    "usual_headache": {
        "first": "I get bad headaches like this sometimes.",
        "second": "You get bad headaches like this sometimes.",
        "third": "They get bad headaches like this sometimes.",
    },
    "whole_face": {
        "first": "My whole face droops on one side, even my forehead.",
        "second": "Your whole face droops on one side, even your forehead.",
        "third": "Their whole face droops on one side, even the forehead.",
    },
    "family": {
        "first": "Others in my family have the same problems.",
        "second": "Others in your family have the same problems.",
        "third": "Others in their family have the same problems.",
    },
    "tired": {
        "first": "My body feels tired and heavy lately.",
        "second": "Your body feels tired.",
        "third": "They feel tired.",
    },
}


def _num(obs: dict[str, Any], key: str) -> float | None:
    value = obs.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _symptom_keys(obs: dict[str, Any]) -> list[str]:
    """Symptoms implied by the measurements, never by the ground-truth flag."""
    keys: list[str] = []
    temp = _num(obs, "temperature_c_initial")
    if temp is not None and temp >= 38.0:
        keys.append("fever")
    elif temp is not None and temp < 36.0:
        keys.append("cold")
    hr = _num(obs, "heart_rate_initial")
    if hr is not None and hr >= 100:
        keys.append("racing_heart")
    rr = _num(obs, "resp_rate_initial")
    ph = _num(obs, "arterial_ph")
    if (rr is not None and rr >= 22) or (ph is not None and ph < 7.30):
        keys.append("fast_breathing")
    sbp = _num(obs, "sbp_initial")
    if sbp is not None and sbp < 90:
        keys.append("faint")
    if obs.get("altered_mental_status_only_flag") or obs.get("mental_status") in (
        "altered",
        "confused",
        "drowsy",
        "obtunded",
        "stupor",
        "stuporous",
        "comatose",
    ):
        keys.append("confused")
    nihss = _num(obs, "nihss_score")
    if nihss is not None and nihss >= 1:
        keys.append("whole_face" if obs.get("forehead_weakness") else "face_speech")
    low_glucose = _num(obs, "glucose_admission")
    if low_glucose is not None and low_glucose < 60:
        keys.append("shaky")
    if obs.get("seizure_at_onset"):
        keys.append("seizure")
    if obs.get("migraine_history"):
        keys.append("usual_headache")
    glucose = _num(obs, "glucose_mg_dl")
    if glucose is not None and glucose >= 250:
        keys.append("thirst")
    hco3 = _num(obs, "bicarbonate_meq_l")
    if (ph is not None and ph < 7.30) or (hco3 is not None and hco3 < 18):
        keys.append("belly")
    bohb = _num(obs, "beta_hydroxybutyrate_mmol_l")
    if bohb is not None and bohb >= 3.0:
        keys.append("sweet_breath")
    if obs.get("neuropathic_pain"):
        keys.append("burning")
    if obs.get("hypohidrosis"):
        keys.append("low_sweat")
    if obs.get("family_history_fabry"):
        keys.append("family")
    return keys or ["tired"]


def symptom_sentences(obs: dict[str, Any], person: str) -> str:
    """Plain-language symptoms in the first, second or third person.

    Derived from the measurements, so a clinical mimic with the same readings is
    described the same way as a true case.
    """
    if person not in ("first", "second", "third"):
        raise ValueError(f"person must be 'first', 'second' or 'third', got {person!r}")
    return " ".join(_SYMPTOM_TEXT[k][person] for k in _symptom_keys(obs))


def _blind_fhir_resources(resources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Blind a FHIR resource list and add the decision-time measurements.

    Decision-target Conditions are dropped, every Encounter reason is masked, and
    each decision-time measurement becomes a text-coded Observation so the
    structured form carries the same facts as the narrative forms.
    """
    out: list[dict[str, Any]] = []
    for resource in resources:
        kind = resource.get("resourceType")
        if kind == "Condition":
            text = resource.get("code", {}).get("text")
            if is_decision_target(text):
                continue
            # Exporter ids are positional, so dropping a target condition would
            # shift every later id. Re-derive them from the condition itself so
            # the bundle is identical whether or not a target was present.
            subject = resource.get("subject", {}).get("reference")
            resource = {**resource, "id": _content_uuid(f"blinded-condition::{subject}::{text}")}
        if kind == "Encounter" and "reason" in resource:
            resource = json.loads(json.dumps(resource))
            for reason in resource["reason"]:
                for value in reason.get("value", []):
                    concept = value.get("concept", {})
                    if "text" in concept:
                        concept["text"] = MASKED_DIAGNOSIS
        out.append(resource)
    return out


def _content_uuid(key: str) -> str:
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return f"{digest[:8]}-{digest[8:12]}-{digest[12:16]}-{digest[16:20]}-{digest[20:32]}"


def _blinded_fhir_measurements(patient: Patient, subject: str | None) -> list[dict[str, Any]]:
    obs = patient.observations or {}
    pid = patient.demographics.patient_id
    resources: list[dict[str, Any]] = []
    for i, (label, value) in enumerate(_blinded_measurements(obs)):
        observation: dict[str, Any] = {
            "resourceType": "Observation",
            "id": _content_uuid(f"blinded::{pid}::{i}::{label}"),
            "status": "final",
            "code": {"text": label},
            "valueString": value,
        }
        if subject:
            observation["subject"] = {"reference": subject}
        resources.append(observation)
    return resources
