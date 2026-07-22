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
HipAAsynth Oncology Staging Module

Assigns cancer stage and simplified TNM components.
Designed to plug into the main engine (no pandas, deterministic via shared RNG).
Uses stdlib random for compatibility with NixOS environment.
"""

import random


class StagingModule:
    """
    Oncology staging module.

    Args:
        n (int): number of patients
        rng (random.Random): shared deterministic RNG
        config (dict): optional configuration
    """

    def __init__(self, n: int, rng: random.Random, config: dict = None):
        self.n = n
        self.rng = rng
        self.config = config or self._default_config()

    def _default_config(self):
        # Stage-at-diagnosis distributions [I, II, III, IV] per site, chosen so
        # that the SEER summary-stage grouping is reproduced:
        #   localized ≈ I(+II), regional ≈ (II)III, distant ≈ IV.
        # SEER Cancer Stat Facts stage-at-diagnosis:
        #   breast    localized 64% / regional 27% / distant 6%
        #   lung      localized 15% / regional 22% / distant 57%
        #   colorect. localized 35% / regional 36% / distant 24%
        # Source: SEER Cancer Stat Facts (breast/lung/colorectal),
        # https://seer.cancer.gov/statfacts/  (distant = stage IV / M1).
        return {
            "stage_probs": {
                "breast": [0.38, 0.29, 0.27, 0.06],
                "lung":   [0.17, 0.08, 0.18, 0.57],
                "colon":  [0.21, 0.19, 0.36, 0.24],
            },
            "stages": ["I", "II", "III", "IV"],
        }

    def generate(self, sites):
        """
        Args:
            sites (list): cancer site per patient

        Returns:
            dict with stage + TNM lists
        """
        stages = self._assign_stages(sites)
        t_stage = self._assign_t(stages, sites)
        n_stage = self._assign_n(stages)
        m_stage = self._assign_m(stages)

        return {
            "stage": stages,
            "t_stage": t_stage,
            "n_stage": n_stage,
            "m_stage": m_stage,
        }

    def _assign_stages(self, sites):
        """Assign cancer stage based on site-specific probabilities."""
        stages = []

        for site in sites:
            probs = self.config["stage_probs"].get(site, [0.25, 0.25, 0.25, 0.25])
            stage = self.rng.choices(
                self.config["stages"],
                weights=probs,
                k=1,
            )[0]
            stages.append(stage)

        return stages

    def _assign_t(self, stages, sites):
        """Assign T stage (tumor size) based on overall stage and site."""
        t_stages = []

        for i, s in enumerate(stages):
            site = sites[i]

            if s == "I":
                t = self.rng.choices(["T1", "T2"], weights=[0.7, 0.3], k=1)[0]

            elif s == "II":
                if site == "breast":
                    t = self.rng.choices(["T2", "T3"], weights=[0.8, 0.2], k=1)[0]
                else:
                    t = self.rng.choices(
                        ["T2", "T3", "T4"], weights=[0.5, 0.3, 0.2], k=1
                    )[0]

            elif s == "III":
                t = self.rng.choices(["T3", "T4"], weights=[0.6, 0.4], k=1)[0]

            else:  # IV
                t = self.rng.choices(
                    ["T1", "T2", "T3", "T4"],
                    weights=[0.1, 0.2, 0.3, 0.4],
                    k=1,
                )[0]

            t_stages.append(t)

        return t_stages

    def _assign_n(self, stages):
        """Assign N stage (node involvement) based on overall stage."""
        n_stages = []

        for s in stages:
            if s == "I":
                n = self.rng.choices(["N0", "N1"], weights=[0.9, 0.1], k=1)[0]

            elif s == "II":
                n = self.rng.choices(
                    ["N0", "N1", "N2"],
                    weights=[0.4, 0.4, 0.2],
                    k=1,
                )[0]

            elif s == "III":
                n = self.rng.choices(
                    ["N1", "N2", "N3"],
                    weights=[0.3, 0.5, 0.2],
                    k=1,
                )[0]

            else:  # IV
                n = self.rng.choices(
                    ["N0", "N1", "N2", "N3"],
                    weights=[0.2, 0.2, 0.3, 0.3],
                    k=1,
                )[0]

            n_stages.append(n)

        return n_stages

    def _assign_m(self, stages):
        """Assign M stage (metastasis)."""
        return ["M1" if s == "IV" else "M0" for s in stages]
