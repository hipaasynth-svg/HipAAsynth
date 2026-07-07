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
SMA Module — Spinal Muscular Atrophy Synthetic Cohort Generator
Copyright (c) 2026 Cody Carlson
Version: 0.2.0-SMA
Calibration: SPINRAZA trials, SMArtCARE registry, FDA label

Stdlib-only (no numpy/pandas). Anchor-compatible.
"""

import random
import math
from typing import List, Dict, Optional

from hipaasynth.core.config import DEFAULT_SYNTHETIC_DISCLAIMER


SMA_TYPES = ["SMA-I", "SMA-II", "SMA-III", "SMA-IV"]

SMA_TYPE_RATES = [0.55, 0.30, 0.14, 0.01]

SMN2_DIST = {
    "SMA-I":   [0.70, 0.25, 0.05, 0.00],
    "SMA-II":  [0.10, 0.60, 0.25, 0.05],
    "SMA-III": [0.00, 0.20, 0.50, 0.30],
    "SMA-IV":  [0.00, 0.05, 0.35, 0.60],
}

ONSET_PARAMS = {
    "SMA-I":   (2.5, 1.5),
    "SMA-II":  (10.0, 3.0),
    "SMA-III": (36.0, 12.0),
    "SMA-IV":  (240.0, 60.0),
}

SURVIVAL_PARAMS = {
    "SMA-I": {
        "hazards": [0.25, 0.08, 0.02],
        "intervals": [6, 18, 216],
        "max_months": 240,
    },
    "SMA-II": {
        "hazards": [0.005, 0.003, 0.002],
        "intervals": [120, 240, 240],
        "max_months": 600,
    },
    "SMA-III": {
        "hazards": [0.002, 0.001, 0.001],
        "intervals": [240, 240, 240],
        "max_months": 720,
    },
    "SMA-IV": {
        "hazards": [0.0015, 0.001, 0.001],
        "intervals": [240, 240, 240],
        "max_months": 600,
    },
}

NUSINERSEN_SURVIVAL_BENEFIT = 0.50

VENTILATION_RATES = {
    "SMA-I":   0.80,
    "SMA-II":  0.30,
    "SMA-III": 0.05,
    "SMA-IV":  0.02,
}

MILESTONE_PARAMS = {
    "SMA-II":  {"sits_mean": 12.0, "walks_mean": 20.0, "ambulation_loss_age": 480.0},
    "SMA-III": {"sits_mean": 15.0, "walks_mean": 24.0, "ambulation_loss_age": 480.0},
}


def _weighted_choice(rng, options, weights):
    cumulative = []
    total = 0
    for w in weights:
        total += w
        cumulative.append(total)
    r = rng.random() * total
    for i, c in enumerate(cumulative):
        if r <= c:
            return options[i]
    return options[-1]


def _clamp(val, lo, hi):
    return max(lo, min(hi, val))


def _exponential(rng, scale):
    u = rng.random()
    u = max(u, 1e-15)
    return -scale * math.log(u)


def _piecewise_survival(rng, hazards, intervals):
    t = 0.0
    for h, duration in zip(hazards, intervals):
        if h <= 0:
            t += duration
            continue
        u = rng.random()
        u = max(u, 1e-15)
        time_to_event = -math.log(1 - u) / h if u < 1.0 else float("inf")
        if time_to_event < duration:
            return t + time_to_event, "deceased"
        t += duration
    return t, "censored"


class SMACohortGenerator:

    def __init__(self, rng=None, seed=None, treatment_rate=0.65):
        if rng is not None:
            self._rng = rng
        elif seed is not None:
            self._rng = random.Random(seed)
        else:
            self._rng = random.Random()
        self.treatment_rate = treatment_rate
        self._call_count = 0

    def random(self):
        return self._rng.random()

    def generate(self, n=1000, include_genetics=True, include_motor_milestones=True):
        patients = []
        for i in range(n):
            pid = f"SMA-{i:06d}"
            patients.append(self._generate_patient(
                pid, self.treatment_rate,
                include_genetics, include_motor_milestones
            ))
        return patients

    def _tracked_random(self):
        self._call_count += 1
        return self._rng.random()

    def _tracked_gauss(self, mu, sigma):
        self._call_count += 1
        return self._rng.gauss(mu, sigma)

    def _tracked_uniform(self, a, b):
        self._call_count += 1
        return self._rng.uniform(a, b)

    def _tracked_exponential(self, scale):
        self._call_count += 1
        return _exponential(self._rng, scale)

    def _tracked_choice(self, options, weights):
        self._call_count += 1
        return _weighted_choice(self._rng, options, weights)

    def _assign_smn2_copies(self, sma_type):
        return self._tracked_choice([1, 2, 3, 4], SMN2_DIST[sma_type])

    def _calculate_onset_age(self, sma_type):
        mean, std = ONSET_PARAMS[sma_type]
        return _clamp(self._tracked_gauss(mean, std), 0.1, mean + 4 * std)

    def _generate_patient(self, patient_id, treatment_rate,
                          include_genetics, include_motor_milestones):
        self._call_count = 0

        sma_type = self._tracked_choice(SMA_TYPES, SMA_TYPE_RATES)

        smn2_copies = self._assign_smn2_copies(sma_type)

        onset_age_months = self._calculate_onset_age(sma_type)

        if sma_type == "SMA-I":
            diagnosis_delay = self._tracked_exponential(3)
        else:
            diagnosis_delay = self._tracked_exponential(6)
        diagnosis_age_months = onset_age_months + diagnosis_delay

        on_nusinersen = self._tracked_random() < treatment_rate

        if on_nusinersen:
            presymptomatic = self._tracked_random() < 0.25

            if presymptomatic:
                treatment_start = max(0.1, onset_age_months - self._tracked_uniform(1, 3))
            else:
                treatment_start = diagnosis_age_months + self._tracked_uniform(0, 3)
        else:
            presymptomatic = False
            treatment_start = None

        smn2_modifier = 1.0 - (0.15 * (smn2_copies - 2))
        smn2_modifier = _clamp(smn2_modifier, 0.5, 1.2)

        if on_nusinersen:
            if presymptomatic:
                treatment_effect_multiplier = 0.4
            elif treatment_start - onset_age_months < 6:
                treatment_effect_multiplier = 0.6
            else:
                treatment_effect_multiplier = 0.8
        else:
            treatment_effect_multiplier = 1.0

        survival_months, vital_status = self._model_survival(
            sma_type, onset_age_months, on_nusinersen
        )

        survival_months *= (1 / smn2_modifier)
        survival_months *= (1 / treatment_effect_multiplier)

        age_at_death_or_censor_months = onset_age_months + survival_months
        current_age_years = age_at_death_or_censor_months / 12

        motor_data = {}
        if include_motor_milestones:

            milestone_shift = (smn2_copies - 2) * -2

            if on_nusinersen:
                if presymptomatic:
                    milestone_shift -= 6
                elif treatment_start - onset_age_months < 6:
                    milestone_shift -= 3

            if sma_type == "SMA-I":
                if presymptomatic:
                    motor_data = {
                        'achieved_sitting': True,
                        'age_sitting_months': round(self._tracked_gauss(8, 2), 2),
                        'achieved_walking': self._tracked_random() < 0.3,
                        'age_walking_months': round(self._tracked_gauss(16, 4), 2),
                        'lost_ambulation': False,
                        'age_ambulation_lost_months': None
                    }
                else:
                    motor_data = {
                        'achieved_sitting': False,
                        'age_sitting_months': None,
                        'achieved_walking': False,
                        'age_walking_months': None,
                        'lost_ambulation': False,
                        'age_ambulation_lost_months': None
                    }

            elif sma_type == "SMA-II":
                mp = MILESTONE_PARAMS["SMA-II"]
                age_sits = self._tracked_gauss(mp["sits_mean"] + milestone_shift, 3)
                motor_data = {
                    'achieved_sitting': current_age_years * 12 > age_sits,
                    'age_sitting_months': round(age_sits, 2),
                    'achieved_walking': presymptomatic and self._tracked_random() < 0.2,
                    'age_walking_months': round(self._tracked_gauss(20, 5), 2) if presymptomatic else None,
                    'lost_ambulation': False,
                    'age_ambulation_lost_months': None
                }

            elif sma_type == "SMA-III":
                mp = MILESTONE_PARAMS["SMA-III"]
                age_sits = self._tracked_gauss(15 + milestone_shift, 4)
                age_walks = self._tracked_gauss(mp["walks_mean"] + milestone_shift, 6)

                amb_loss_risk = 0.40 - (0.05 * (smn2_copies - 3))
                if on_nusinersen:
                    amb_loss_risk *= 0.7

                lost_amb = (
                    current_age_years * 12 > mp["ambulation_loss_age"] and
                    self._tracked_random() < amb_loss_risk
                )

                motor_data = {
                    'achieved_sitting': current_age_years * 12 > age_sits,
                    'age_sitting_months': round(age_sits, 2),
                    'achieved_walking': current_age_years * 12 > age_walks,
                    'age_walking_months': round(age_walks, 2),
                    'lost_ambulation': lost_amb,
                    'age_ambulation_lost_months': round(self._tracked_gauss(480, 60), 2) if lost_amb else None
                }

            else:
                motor_data = {
                    'achieved_sitting': True,
                    'age_sitting_months': 8.0,
                    'achieved_walking': True,
                    'age_walking_months': 14.0,
                    'lost_ambulation': False,
                    'age_ambulation_lost_months': None
                }

        respiratory_data = self._model_respiratory(
            sma_type, age_at_death_or_censor_months, on_nusinersen
        )

        genetic_data = {}
        if include_genetics:
            smn2_fl = int(self._tracked_gauss(smn2_copies * 0.3, 0.5))
            genetic_data = {
                'smn1_status': 'homozygous_deletion',
                'smn2_copies': int(smn2_copies),
                'smn2_full_length_transcripts': max(0, smn2_fl),
                'c_859c_t_mutation': self._tracked_random() < 0.05
            }

        return {
            'patient_id': patient_id,
            'synthetic': True,
            'disclaimer': DEFAULT_SYNTHETIC_DISCLAIMER,
            'sma_type': sma_type,
            'age_at_onset_months': round(onset_age_months, 2),
            'age_at_diagnosis_months': round(diagnosis_age_months, 2),
            'on_disease_modifying_therapy': on_nusinersen,
            'treatment_start_months': round(treatment_start, 2) if treatment_start else None,
            'presymptomatic_treatment': presymptomatic,
            'dmt_type': 'nusinersen' if on_nusinersen else None,
            'age_at_death_or_censor_years': round(current_age_years, 2),
            'vital_status': vital_status,
            'survival_months_from_onset': round(survival_months, 2),
            'rng_calls': self._call_count,
            **genetic_data,
            **motor_data,
            **respiratory_data
        }

    def _model_survival(self, sma_type, onset_months, on_nusinersen):
        sp = SURVIVAL_PARAMS[sma_type]
        hazards = list(sp["hazards"])
        intervals = sp["intervals"]
        max_m = sp["max_months"]

        if on_nusinersen and sma_type == "SMA-I":
            hazards = [h * (1 - NUSINERSEN_SURVIVAL_BENEFIT) for h in hazards]
        elif on_nusinersen and sma_type == "SMA-II":
            hazards = [h * 0.7 for h in hazards]

        survival, status = _piecewise_survival(self._rng, hazards, intervals)
        self._call_count += len(hazards)
        survival = min(survival, max_m)
        if survival >= max_m:
            status = "censored"

        return survival, status

    def _model_respiratory(self, sma_type, age_months, on_nusinersen):
        vent_rate = VENTILATION_RATES.get(sma_type, 0.02)
        needs_ventilation = self._tracked_random() < vent_rate
        if on_nusinersen and needs_ventilation:
            needs_ventilation = self._tracked_random() < 0.6

        if sma_type == "SMA-I":
            niv_hours = _clamp(round(self._tracked_gauss(16, 4), 1), 0, 24) if needs_ventilation else 0
            trach = needs_ventilation and self._tracked_random() < 0.30
        elif sma_type == "SMA-II":
            niv_hours = _clamp(round(self._tracked_gauss(8, 3), 1), 0, 24) if needs_ventilation else 0
            trach = needs_ventilation and self._tracked_random() < 0.05
        else:
            niv_hours = _clamp(round(self._tracked_gauss(4, 2), 1), 0, 24) if needs_ventilation else 0
            trach = False

        scoliosis = False
        if sma_type in ("SMA-I", "SMA-II"):
            scoliosis = self._tracked_random() < 0.60
        elif sma_type == "SMA-III":
            scoliosis = self._tracked_random() < 0.30

        feeding_support = False
        if sma_type == "SMA-I":
            feeding_support = self._tracked_random() < 0.85
        elif sma_type == "SMA-II":
            feeding_support = self._tracked_random() < 0.25

        return {
            'needs_ventilation': needs_ventilation,
            'niv_hours_per_day': niv_hours,
            'tracheostomy': trach,
            'scoliosis': scoliosis,
            'feeding_support': feeding_support,
        }

    def _estimate_cost(self, sma_type, treated, treatment_name, ventilation):
        base = {"SMA-I": 85000, "SMA-II": 45000, "SMA-III": 25000, "SMA-IV": 12000}
        cost = base.get(sma_type, 30000)

        if treated and treatment_name:
            drug_costs = {
                "nusinersen": 375000,
                "onasemnogene": 425000,
                "risdiplam": 100000,
            }
            cost += drug_costs.get(treatment_name, 200000)

        if ventilation:
            cost += 65000

        return cost


def main():
    rng = random.Random(42)
    gen = SMACohortGenerator(rng=rng, treatment_rate=0.65)
    cohort = gen.generate(n=1000, include_genetics=True, include_motor_milestones=True)

    n = len(cohort)
    print(f"--- SMA COHORT STATS (n={n}) ---")

    for t in SMA_TYPES:
        ct = sum(1 for p in cohort if p["sma_type"] == t)
        print(f"  {t}: {ct} ({ct/n:.0%})")

    treated = sum(1 for p in cohort if p["on_disease_modifying_therapy"])
    print(f"  On DMT: {treated/n:.0%}")

    presymp = sum(1 for p in cohort if p.get("presymptomatic_treatment"))
    print(f"  Presymptomatic tx: {presymp/n:.0%}")

    deceased = sum(1 for p in cohort if p["vital_status"] == "deceased")
    print(f"  Deceased: {deceased/n:.0%}")

    mean_surv = sum(p["survival_months_from_onset"] for p in cohort) / n
    print(f"  Mean survival (from onset): {mean_surv:.1f} months")

    vent = sum(1 for p in cohort if p["needs_ventilation"])
    print(f"  Ventilation: {vent/n:.0%}")

    trach = sum(1 for p in cohort if p.get("tracheostomy"))
    print(f"  Tracheostomy: {trach/n:.0%}")

    scol = sum(1 for p in cohort if p["scoliosis"])
    print(f"  Scoliosis: {scol/n:.0%}")

    feed = sum(1 for p in cohort if p["feeding_support"])
    print(f"  Feeding support: {feed/n:.0%}")

    sits = sum(1 for p in cohort if p.get("achieved_sitting"))
    walks = sum(1 for p in cohort if p.get("achieved_walking"))
    print(f"  Achieved sitting: {sits/n:.0%}")
    print(f"  Achieved walking: {walks/n:.0%}")

    genetics = sum(1 for p in cohort if "smn1_status" in p)
    print(f"  Genetics data: {genetics/n:.0%}")

    mean_rng = sum(p["rng_calls"] for p in cohort) / n
    print(f"  Mean RNG calls/patient: {mean_rng:.1f}")

    print("--------------------------------")
    print(f"\nSample record:")
    for k, v in cohort[0].items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
