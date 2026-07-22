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
HipAAsynth Oncology Outcomes Module (stdlib)

Generates:
- response
- progression
- survival
"""

import random
import math


class OutcomesModule:
    def __init__(self, n: int, rng: random.Random):
        self.n = n
        self.rng = rng

    def generate(self, sites, stages, treatments, biomarkers, comorbidity):
        data = self._empty()

        for i in range(self.n):
            stage = stages[i]
            site = sites[i]

            chemo = treatments["chemotherapy"][i]
            targeted = treatments["targeted_therapy"][i]
            io = treatments["immunotherapy"][i]

            egfr = biomarkers.get("egfr_status", [None]*self.n)[i]
            her2 = biomarkers.get("her2_status", [None]*self.n)[i]
            msi = biomarkers.get("msi_status", [None]*self.n)[i]
            pdl1 = biomarkers.get("pd_l1_tps", [0]*self.n)[i]

            cci = comorbidity.get("charlson_index", [0]*self.n)[i]

            # ---------------- RESPONSE ----------------
            response = None
            if chemo or targeted or io:
                if targeted and egfr == "+":
                    prob = 0.75
                elif targeted and her2 == "+":
                    prob = 0.5
                elif io and msi == "MSI-H":
                    prob = 0.5
                elif io and pdl1 >= 50:
                    prob = 0.4
                elif io:
                    prob = 0.2
                elif chemo:
                    prob = 0.35
                else:
                    prob = 0.1

                if self.rng.random() < prob:
                    response = "CR" if self.rng.random() < 0.1 else "PR"
                    data["response_month"][i] = self._randint(2, 6)
                else:
                    response = "SD" if self.rng.random() < 0.4 else "PD"

            data["best_response"][i] = response

            # ---------------- PROGRESSION ----------------
            prog_prob, median_ttp = self._stage_progression(site, stage)

            if response == "CR":
                prog_prob *= 0.2
                median_ttp *= 3
            elif response == "PR":
                prog_prob *= 0.5
                median_ttp *= 2
            elif response == "PD":
                prog_prob = 1.0
                median_ttp = 2

            if self.rng.random() < prog_prob:
                ttp = self._exp(median_ttp)
                data["progression"][i] = True
                data["progression_month"][i] = min(ttp, 60)
                data["progression_site"][i] = self._progression_site(site)

            # ---------------- SURVIVAL ----------------
            os_5yr, median_os = self._stage_survival(site, stage)

            if response == "CR":
                median_os *= 2
            elif response == "PR":
                median_os *= 1.5
            elif response == "PD":
                median_os *= 0.6

            median_os *= (0.9 ** cci)

            death = self.rng.random() > os_5yr
            if death:
                ttd = self._weibull(median_os)
                data["death"][i] = True
                data["death_month"][i] = min(ttd, 60)

        return data

    # ---------------- HELPERS ----------------

    def _stage_progression(self, site, stage):
        """Progression probability + median time-to-progression (months).

        Progression risk rises with stage and is broadly site-independent;
        survival (below) is where the three sites diverge sharply.
        """
        table = {
            "I":   (0.15, 36),
            "II":  (0.30, 24),
            "III": (0.50, 18),
            "IV":  (0.90, 6),
        }
        return table.get(stage, (0.90, 6))

    # 5-year overall survival by SITE and stage. Using one curve for all three
    # sites is clinically wrong (e.g. stage I lung ~65% vs stage I breast ~99%),
    # so each site carries its own stage-specific 5-year survival, calibrated to:
    #   breast — SEER Cancer Stat Facts (localized ~99% / regional ~86% /
    #            distant ~30%).
    #   lung   — SEER / ACS non-small-cell lung (localized ~65% / regional
    #            ~37% / distant ~9%).
    #   colon  — O'Connell JB et al. J Natl Cancer Inst 2004;96(19):1420-1425,
    #            SEER AJCC 6th ed., n=119,363 (I 93.2% / II ~83% / III ~60% /
    #            IV 8.1%). https://doi.org/10.1093/jnci/djh275
    # median_os (months) is a modeling parameter scaled from the 5-year figure.
    _SURVIVAL = {
        "breast": {"I": (0.99, 180), "II": (0.93, 150), "III": (0.86, 96),  "IV": (0.30, 36)},
        "lung":   {"I": (0.65, 96),  "II": (0.53, 60),  "III": (0.37, 36),  "IV": (0.09, 12)},
        "colon":  {"I": (0.93, 150), "II": (0.84, 120), "III": (0.64, 60),  "IV": (0.11, 18)},
    }

    def _stage_survival(self, site, stage):
        site_curve = self._SURVIVAL.get(site, self._SURVIVAL["colon"])
        return site_curve.get(stage, (0.20, 18))

    def _exp(self, mean):
        return -mean * math.log(1 - self.rng.random())

    def _weibull(self, scale):
        shape = 1.5
        return scale * (-math.log(1 - self.rng.random())) ** (1/shape)

    def _randint(self, a, b):
        return a + int(self.rng.random() * (b - a))

    def _progression_site(self, site):
        if site == "breast":
            return self._choice(["bone", "liver", "lung", "brain"])
        if site == "lung":
            return self._choice(["brain", "bone", "liver"])
        return self._choice(["liver", "lung", "peritoneum"])

    def _choice(self, options):
        return options[self.rng.randrange(len(options))]

    def _empty(self):
        return {
            "best_response": [None]*self.n,
            "response_month": [None]*self.n,
            "progression": [False]*self.n,
            "progression_month": [None]*self.n,
            "progression_site": [None]*self.n,
            "death": [False]*self.n,
            "death_month": [None]*self.n,
        }