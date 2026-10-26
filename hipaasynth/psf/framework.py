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
PSF audit framework — measures model performance degradation across sparsity levels.

Key metrics
-----------
Sparsity Degradation Index (SDI)
    SDI = mean_score(S1) / mean_score(S7).
    SDI of 1.0 means no degradation.  SDI < 0.8 is a FAIL, signalling that
    the model relies on field density rather than clinical content.

Per-level score distribution
    Mean score at each of S1–S7.

Demographic-sparsity interaction
    At each level the mean score is broken down by race/ethnicity.  A fair
    model shows the same gradient for all demographic groups.  A biased model
    amplifies the sparsity penalty for historically under-served groups
    (e.g. AIAN patients at S1 score lower than White patients at S1).
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List

from hipaasynth.core.model_interface import ModelInterface, validate_model_score
from hipaasynth.psf.generator import PSFGenerator, SPARSITY_LEVELS


@dataclass(frozen=True)
class PSFConfig:
    """Configuration for a PSF audit run."""

    n_per_level: int = 50
    seed: int = 42
    sdi_threshold: float = 0.80
    model_name: str = "Unnamed Model"
    model_version: str = "0.0.0"

    def __post_init__(self) -> None:
        if isinstance(self.n_per_level, bool) or not isinstance(self.n_per_level, int) \
                or self.n_per_level < 1:
            raise ValueError(f"n_per_level must be an integer >= 1, got {self.n_per_level!r}")


@dataclass
class PSFResult:
    """
    Structured result of a PSF audit.

    Attributes:
        sdi: Sparsity Degradation Index = mean_score(S1) / mean_score(S7).
        sdi_pass: True when sdi >= config.sdi_threshold.
        per_level_scores: Mean model score at each sparsity level.
        demographic_scores: Nested dict[level][race_ethnicity] → mean score.
        config: The PSFConfig used to produce this result.
    """

    sdi: float
    sdi_pass: bool
    per_level_scores: Dict[str, float]
    demographic_scores: Dict[str, Dict[str, float]]
    config: PSFConfig
    raw_scores: Dict[str, List[float]] = field(default_factory=dict)

    def all_pass(self) -> bool:
        """Return True if every audit criterion passes."""
        return self.sdi_pass


class PSFAudit:
    """
    Runs the Population Sparsity Fairness (PSF) adversarial axis audit.

    Usage::

        from hipaasynth.psf import PSFAudit, PSFConfig
        from hipaasynth.core.model_interface import MockClinicalModel

        audit  = PSFAudit()
        result = audit.run(MockClinicalModel(), PSFConfig(n_per_level=100))
        print(result.sdi)          # Sparsity Degradation Index
        print(result.sdi_pass)     # True / False

    Args:
        generator: Optional pre-configured :class:`PSFGenerator`.  If None,
            one is created from the seed in the supplied :class:`PSFConfig`.
    """

    def __init__(self, generator: PSFGenerator | None = None) -> None:
        self._generator = generator

    def run(
        self,
        model: ModelInterface,
        config: PSFConfig | None = None,
    ) -> PSFResult:
        """
        Execute the PSF audit.

        Args:
            model: Any object implementing
                :class:`~hipaasynth.core.model_interface.ModelInterface`.
            config: Audit configuration.  Defaults to :class:`PSFConfig` with
                all default parameters.

        Returns:
            :class:`PSFResult` with SDI, per-level scores, and demographic
            interaction breakdown.
        """
        config = config or PSFConfig()
        gen = self._generator or PSFGenerator(seed=config.seed)

        cohort = gen.generate_all_levels(n_per_level=config.n_per_level)

        raw_scores: Dict[str, List[float]] = {}
        per_level_scores: Dict[str, float] = {}
        demographic_scores: Dict[str, Dict[str, float]] = {}

        for level in SPARSITY_LEVELS:
            patients = cohort[level]
            scores = [
                validate_model_score(model.evaluate(p), f"PSF level {level}, patient {i}")
                for i, p in enumerate(patients)
            ]
            raw_scores[level] = scores
            per_level_scores[level] = _mean(scores)

            # Demographic breakdown
            demo_buckets: Dict[str, List[float]] = {}
            for p, s in zip(patients, scores):
                race = p.get("race_ethnicity", "Unknown")
                demo_buckets.setdefault(race, []).append(s)
            demographic_scores[level] = {
                race: _mean(vals) for race, vals in demo_buckets.items()
            }

        s1_score = per_level_scores.get("S1", 0.0)
        s7_score = per_level_scores.get("S7", 1.0)
        sdi = s1_score / s7_score if s7_score > 0 else 0.0

        return PSFResult(
            sdi=round(sdi, 4),
            sdi_pass=sdi >= config.sdi_threshold,
            per_level_scores=per_level_scores,
            demographic_scores=demographic_scores,
            config=config,
            raw_scores=raw_scores,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mean(values: List[float]) -> float:
    if not values:
        return 0.0
    return round(sum(values) / len(values), 4)
