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
HipAAsynth Oncology Population Module

Generates oncology-aware demographics in a deterministic way.
Designed to plug into the main HipAAsynth engine (no internal RNG creation).
Uses stdlib random for compatibility with NixOS environment.
"""

import random


class PopulationModule:
    """
    Oncology population generator module.

    Args:
        n (int): number of patients
        rng (random.Random): shared deterministic RNG from engine
        config (dict): configuration for distributions
    """

    def __init__(self, n: int, rng: random.Random, config: dict = None):
        self.n = n
        self.rng = rng
        self.config = config or self._default_config()

    def _default_config(self):
        return {
            "sites": ["breast", "lung", "colon"],
            # Share among these three sites, from US annual incidence
            # (ACS Cancer Facts & Figures 2024: breast ~310k, lung ~235k,
            # colorectal ~153k new cases) normalized to sum to 1.
            # Source: Siegel RL et al. Cancer Statistics 2024. CA Cancer J Clin
            # 2024;74(1):12-49. https://doi.org/10.3322/caac.21820
            "site_probs": [0.44, 0.34, 0.22],
            # Median age at diagnosis by site (SEER Cancer Stat Facts):
            # breast 63, lung 71, colorectal 66. Means shaded slightly younger
            # to reflect the treated-cohort skew.
            # Source: SEER Cancer Stat Facts (breast/lung/colorectal),
            # https://seer.cancer.gov/statfacts/
            "age_params": {
                "breast": (60, 12),
                "lung": (70, 9),
                "colon": (66, 12),
            },
            # Male fraction by site. Breast ~1% male (Giordano SH.
            # N Engl J Med 2018;378:2311-2320); lung/colon near-even with
            # slight male predominance (SEER incidence by sex).
            "sex_probs": {
                "breast": [0.01, 0.99],  # [M, F]
                "lung": [0.54, 0.46],
                "colon": [0.53, 0.47],
            },
            # US population race/ethnicity frame (US Census ACS); race-specific
            # incidence differences are modeled downstream, not here.
            "races": ["White", "Black", "Asian", "Hispanic", "Other"],
            "race_probs": [0.70, 0.12, 0.08, 0.08, 0.02],
            "age_bounds": (18, 90),
        }

    def generate(self):
        sites = self._assign_sites()
        ages = self._assign_ages(sites)
        sexes = self._assign_sexes(sites)
        races = self._assign_races()

        return {
            "site": sites,
            "age": ages,
            "sex": sexes,
            "race": races,
        }

    def _assign_sites(self):
        """Sample cancer sites with configured probabilities."""
        return self.rng.choices(
            self.config["sites"],
            weights=self.config["site_probs"],
            k=self.n,
        )

    def _assign_ages(self, sites):
        """Sample ages from normal distribution, clipped to bounds."""
        ages = []
        age_params = self.config["age_params"]
        low, high = self.config["age_bounds"]

        for site in sites:
            mean, std = age_params[site]
            age = self.rng.gauss(mean, std)
            age = max(low, min(high, int(age)))
            ages.append(age)

        return ages

    def _assign_sexes(self, sites):
        """Sample sex based on cancer site probabilities."""
        sexes = []
        sex_probs = self.config["sex_probs"]

        for site in sites:
            probs = sex_probs[site]
            sex = self.rng.choices(["M", "F"], weights=probs, k=1)[0]
            sexes.append(sex)

        return sexes

    def _assign_races(self):
        """Sample race with configured probabilities."""
        return self.rng.choices(
            self.config["races"],
            weights=self.config["race_probs"],
            k=self.n,
        )
