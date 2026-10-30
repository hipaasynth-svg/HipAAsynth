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

"""Conditions generator — CDC/NHANES/AHA calibrated prevalence rates."""
from hipaasynth.core.schema import Condition

# CDC NDSR 2022, NHANES 2017-2020
AGE_STRATIFIED_DIABETES_RATES = [(18, 44, 0.030), (45, 64, 0.135), (65, 200, 0.244)]
AGE_STRATIFIED_HTN_RATES = [(18, 39, 0.224), (40, 59, 0.546), (60, 200, 0.745)]
AGE_STRATIFIED_LIPID_RATES = [(20, 39, 0.203), (40, 59, 0.458), (60, 200, 0.521)]
AGE_STRATIFIED_CKD_RATES = [(18, 44, 0.060), (45, 64, 0.124), (65, 200, 0.381)]
AGE_STRATIFIED_COPD_RATES = [(18, 44, 0.028), (45, 64, 0.077), (65, 200, 0.126)]
AGE_STRATIFIED_DEPRESSION_RATES = [(18, 25, 0.170), (26, 49, 0.081), (50, 200, 0.057)]
AGE_STRATIFIED_ASTHMA_RATES = [(18, 44, 0.082), (45, 64, 0.080), (65, 200, 0.065)]
AGE_STRATIFIED_CHF_RATES = [(20, 39, 0.003), (40, 59, 0.015), (60, 79, 0.045), (80, 200, 0.083)]
AGE_STRATIFIED_AFIB_RATES = [(18, 54, 0.005), (55, 64, 0.020), (65, 74, 0.055), (75, 200, 0.091)]
AGE_STRATIFIED_CAD_RATES = [(20, 39, 0.003), (40, 59, 0.034), (60, 79, 0.096), (80, 200, 0.141)]
CKD_DIABETIC_MULTIPLIER = 2.0


def _lookup_age_rate(age, table):
    for age_min, age_max, rate in table:
        if age_min <= age <= age_max:
            return rate
    return 0.0


def _generate_onset_age(rng, current_age, min_age=0, max_lookback=20):
    floor = max(min_age, current_age - max_lookback)
    if floor > current_age:
        return current_age
    return rng.randint(floor, current_age)


def _bmi_adjustment(bmi, mild=0.02, moderate=0.03, severe=0.02):
    adj = 0.0
    if bmi >= 25.0:
        adj += mild
    if bmi >= 30.0:
        adj += moderate
    if bmi >= 35.0:
        adj += severe
    return adj


def generate_conditions(rng, age, bmi, required_condition):
    conditions = {}
    if required_condition is not None:
        onset_age = _generate_onset_age(rng, age)
        conditions[required_condition] = Condition(
            name=required_condition, onset_age=onset_age, active=True
        )

    diabetes_prob = _lookup_age_rate(age, AGE_STRATIFIED_DIABETES_RATES) + _bmi_adjustment(
        bmi, 0.01, 0.015, 0.01
    )
    if age >= 18 and rng.random() < min(diabetes_prob, 0.45):
        onset_age = _generate_onset_age(rng, age, min_age=18)
        if "type2_diabetes" not in conditions:
            conditions["type2_diabetes"] = Condition(
                name="type2_diabetes", onset_age=onset_age, active=True
            )

    has_diabetes = "type2_diabetes" in conditions

    htn_base = _lookup_age_rate(age, AGE_STRATIFIED_HTN_RATES)
    if has_diabetes:
        htn_base = min(htn_base + 0.10, 0.82)
    htn_prob = htn_base + _bmi_adjustment(bmi, 0.005, 0.01, 0.005)
    if age >= 18 and rng.random() < min(htn_prob, 0.90):
        onset_age = _generate_onset_age(rng, age, min_age=18)
        if "hypertension" not in conditions:
            conditions["hypertension"] = Condition(
                name="hypertension", onset_age=onset_age, active=True
            )

    lipid_prob = _lookup_age_rate(age, AGE_STRATIFIED_LIPID_RATES) + _bmi_adjustment(
        bmi, 0.01, 0.02, 0.02
    )
    if age >= 20 and rng.random() < min(lipid_prob, 0.70):
        onset_age = _generate_onset_age(rng, age, min_age=20)
        if "hyperlipidemia" not in conditions:
            conditions["hyperlipidemia"] = Condition(
                name="hyperlipidemia", onset_age=onset_age, active=True
            )

    ckd_base = _lookup_age_rate(age, AGE_STRATIFIED_CKD_RATES)
    if has_diabetes:
        ckd_base = min(ckd_base * CKD_DIABETIC_MULTIPLIER, 0.50)
    if age >= 18 and rng.random() < min(ckd_base, 0.65):
        onset_age = _generate_onset_age(rng, age, min_age=18)
        if "chronic_kidney_disease" not in conditions:
            conditions["chronic_kidney_disease"] = Condition(
                name="chronic_kidney_disease", onset_age=onset_age, active=True
            )

    copd_prob = _lookup_age_rate(age, AGE_STRATIFIED_COPD_RATES)
    if age >= 18 and rng.random() < copd_prob:
        onset_age = _generate_onset_age(rng, age, min_age=35)
        if "copd" not in conditions:
            conditions["copd"] = Condition(name="copd", onset_age=onset_age, active=True)

    depression_prob = _lookup_age_rate(age, AGE_STRATIFIED_DEPRESSION_RATES)
    if age >= 18 and rng.random() < depression_prob:
        onset_age = _generate_onset_age(rng, age, min_age=12)
        if "depression" not in conditions:
            conditions["depression"] = Condition(
                name="depression", onset_age=onset_age, active=True
            )

    asthma_prob = _lookup_age_rate(age, AGE_STRATIFIED_ASTHMA_RATES)
    if age >= 5 and rng.random() < asthma_prob:
        onset_age = _generate_onset_age(rng, age, min_age=0)
        if "asthma" not in conditions:
            conditions["asthma"] = Condition(name="asthma", onset_age=onset_age, active=True)

    chf_prob = _lookup_age_rate(age, AGE_STRATIFIED_CHF_RATES)
    if has_diabetes:
        chf_prob *= 2.0
    if age >= 20 and rng.random() < min(chf_prob, 0.25):
        onset_age = _generate_onset_age(rng, age, min_age=30)
        if "congestive_heart_failure" not in conditions:
            conditions["congestive_heart_failure"] = Condition(
                name="congestive_heart_failure", onset_age=onset_age, active=True
            )

    afib_prob = _lookup_age_rate(age, AGE_STRATIFIED_AFIB_RATES)
    if age >= 18 and rng.random() < afib_prob:
        onset_age = _generate_onset_age(rng, age, min_age=40)
        if "atrial_fibrillation" not in conditions:
            conditions["atrial_fibrillation"] = Condition(
                name="atrial_fibrillation", onset_age=onset_age, active=True
            )

    cad_prob = _lookup_age_rate(age, AGE_STRATIFIED_CAD_RATES)
    if has_diabetes:
        cad_prob *= 2.0
    if age >= 20 and rng.random() < min(cad_prob, 0.30):
        onset_age = _generate_onset_age(rng, age, min_age=30)
        if "coronary_artery_disease" not in conditions:
            conditions["coronary_artery_disease"] = Condition(
                name="coronary_artery_disease", onset_age=onset_age, active=True
            )

    return list(conditions.values())
