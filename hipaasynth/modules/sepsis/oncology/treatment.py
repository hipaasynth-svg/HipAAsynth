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
HipAAsynth Oncology Treatment Module (stdlib version)

Assigns treatments based on stage, biomarkers, and patient factors.
No numpy, no pandas.
"""

import random


class TreatmentModule:
    def __init__(self, n: int, rng: random.Random):
        self.n = n
        self.rng = rng

    def generate(self, sites, stages, biomarkers):
        data = self._empty()

        for i in range(self.n):
            site = sites[i]
            stage = stages[i]

            # pull biomarkers safely
            er = biomarkers.get("er_status", [None] * self.n)[i]
            her2 = biomarkers.get("her2_status", [None] * self.n)[i]
            egfr = biomarkers.get("egfr_status", [None] * self.n)[i]
            alk = biomarkers.get("alk_status", [None] * self.n)[i]
            pdl1 = biomarkers.get("pd_l1_tps", [0] * self.n)[i]
            msi = biomarkers.get("msi_status", [None] * self.n)[i]
            kras = biomarkers.get("kras_status", [None] * self.n)[i]
            nras = biomarkers.get("nras_status", [None] * self.n)[i]
            side = biomarkers.get("primary_side", ["right"] * self.n)[i]

            # ---------------- BREAST ----------------
            if site == "breast":
                if stage in ["I", "II", "III"]:
                    data["surgery"][i] = True
                    data["surgery_type"][i] = (
                        "lumpectomy"
                        if self.rng.random() < (0.6 if stage == "I" else 0.4)
                        else "mastectomy"
                    )

                    if data["surgery_type"][i] == "lumpectomy" or stage == "III":
                        data["radiation"][i] = True

                if stage in ["II", "III"]:
                    if her2 == "+" or stage == "III":
                        data["chemotherapy"][i] = True
                        data["chemo_regimen"][i] = self._choice(["AC-T", "TC", "AC-THP"])
                        data["chemo_cycles"][i] = self._choice([4, 6])

                    if her2 == "+":
                        data["targeted_therapy"][i] = True
                        data["targeted_agent"][i] = "trastuzumab"

                    if er == "+":
                        data["endocrine_therapy"][i] = True
                        data["endocrine_agent"][i] = self._choice(
                            ["tamoxifen", "anastrozole", "letrozole"]
                        )

                if stage == "IV":
                    if her2 == "+":
                        data["targeted_therapy"][i] = True
                        data["targeted_agent"][i] = self._choice(
                            ["trastuzumab", "trastuzumab_deruxtecan"]
                        )
                    elif er == "+":
                        data["endocrine_therapy"][i] = True
                        data["endocrine_agent"][i] = self._choice(
                            ["fulvestrant", "palbociclib_combo"]
                        )
                    else:
                        data["chemotherapy"][i] = True
                        data["chemo_regimen"][i] = self._choice(["carboplatin", "taxane"])

            # ---------------- LUNG ----------------
            elif site == "lung":
                if stage in ["I", "II"]:
                    data["surgery"][i] = True
                    data["surgery_type"][i] = self._choice(["lobectomy", "segmentectomy", "wedge"])

                    if stage == "II":
                        data["chemotherapy"][i] = True
                        data["chemo_regimen"][i] = "cisplatin_combo"
                        data["chemo_cycles"][i] = 4

                elif stage == "III":
                    data["chemotherapy"][i] = True
                    data["radiation"][i] = True
                    data["chemo_regimen"][i] = "cisplatin_etoposide"

                    if self.rng.random() < 0.8:
                        data["immunotherapy"][i] = True
                        data["io_agent"][i] = "durvalumab"
                        data["io_cycles"][i] = self._choice([12, 24])

                elif stage == "IV":
                    if egfr == "+":
                        data["targeted_therapy"][i] = True
                        data["targeted_agent"][i] = "osimertinib"
                    elif alk == "+":
                        data["targeted_therapy"][i] = True
                        data["targeted_agent"][i] = "alectinib"
                    elif pdl1 >= 50:
                        data["immunotherapy"][i] = True
                        data["io_agent"][i] = "pembrolizumab"
                        data["io_cycles"][i] = self._choice([12, 24, 36])
                    else:
                        data["chemotherapy"][i] = True
                        data["chemo_regimen"][i] = "platinum_combo"
                        data["chemo_cycles"][i] = 4

                        if self.rng.random() < 0.7:
                            data["immunotherapy"][i] = True
                            data["io_agent"][i] = "pembrolizumab"

            # ---------------- COLON ----------------
            elif site == "colon":
                if stage in ["I", "II", "III"]:
                    data["surgery"][i] = True
                    data["surgery_type"][i] = self._choice(
                        ["right_hemi", "left_hemi", "LAR", "APR"]
                    )

                    if stage == "III":
                        data["chemotherapy"][i] = True
                        data["chemo_regimen"][i] = self._choice(["FOLFOX", "CAPOX"])
                        data["chemo_cycles"][i] = self._choice([8, 12])

                elif stage == "IV":
                    if msi == "MSI-H":
                        data["immunotherapy"][i] = True
                        data["io_agent"][i] = "pembrolizumab"
                        data["io_cycles"][i] = self._choice([12, 24, 36])
                    else:
                        data["chemotherapy"][i] = True
                        data["chemo_regimen"][i] = "FOLFOX"
                        data["chemo_cycles"][i] = self._choice([8, 12, 16])

                        ras_mut = (kras == "+") or (nras == "+")
                        data["targeted_therapy"][i] = True
                        data["targeted_agent"][i] = (
                            "bevacizumab" if ras_mut or side == "right" else "cetuximab"
                        )

            # ---------------- TOXICITIES ----------------
            if data["chemotherapy"][i]:
                if self.rng.random() < 0.25:
                    data["chemo_toxicity_grade"][i] = self._choice(["3", "4", "5"])
                    data["chemo_discontinuation"][i] = self.rng.random() < 0.6
                else:
                    data["chemo_toxicity_grade"][i] = self._choice(["0", "1", "2"])

            if data["immunotherapy"][i]:
                if self.rng.random() < 0.2:
                    tox = self._choice(["colitis", "pneumonitis", "thyroiditis"])
                    data["io_toxicity_type"][i] = tox
                    data["io_discontinuation"][i] = (
                        tox in ["colitis", "pneumonitis"] and self.rng.random() < 0.7
                    )

        return data

    def _choice(self, options):
        return options[self.rng.randrange(len(options))]

    def _empty(self):
        return {
            "surgery": [False] * self.n,
            "surgery_type": [None] * self.n,
            "radiation": [False] * self.n,
            "chemotherapy": [False] * self.n,
            "chemo_regimen": [None] * self.n,
            "chemo_cycles": [0] * self.n,
            "targeted_therapy": [False] * self.n,
            "targeted_agent": [None] * self.n,
            "immunotherapy": [False] * self.n,
            "io_agent": [None] * self.n,
            "io_cycles": [0] * self.n,
            "endocrine_therapy": [False] * self.n,
            "endocrine_agent": [None] * self.n,
            "chemo_toxicity_grade": [None] * self.n,
            "chemo_discontinuation": [False] * self.n,
            "io_toxicity_type": [None] * self.n,
            "io_discontinuation": [False] * self.n,
        }
