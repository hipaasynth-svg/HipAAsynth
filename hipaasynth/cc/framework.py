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
CC audit framework — measures model performance across care-continuity profiles.

Key metrics
-----------
Continuity Degradation Index (CDI)
    CDI = mean_score(PROFILE_D) / mean_score(PROFILE_A).
    CDI of 1.0 means no degradation.  CDI < 0.8 is a FAIL.
    This mirrors the PSF SDI but on the continuity axis.

Per-profile score distribution
    Mean score at each of PROFILE_A–PROFILE_D.

Transition consistency (continuity bias)
    For matched-demographic patients presented at PROFILE_A and PROFILE_D,
    the delta in model score is the *continuity bias*: the model's confidence
    change attributable solely to record completeness rather than clinical
    content.  A model with continuity bias will under-triage the same patient
    when their record looks like a PROFILE_D compared to a PROFILE_A.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List

from hipaasynth.core.model_interface import ModelInterface, validate_model_score
from hipaasynth.cc.generator import CCGenerator, CONTINUITY_PROFILES


@dataclass(frozen=True)
class CCConfig:
    """Configuration for a CC audit run."""

    n_per_profile: int = 50
    n_matched_pairs: int = 20
    seed: int = 42
    cdi_threshold: float = 0.80
    model_name: str = "Unnamed Model"
    model_version: str = "0.0.0"

    def __post_init__(self) -> None:
        for name in ("n_per_profile", "n_matched_pairs"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be an integer >= 1, got {value!r}")


@dataclass
class CCResult:
    """
    Structured result of a CC audit.

    Attributes:
        cdi: Continuity Degradation Index = mean_score(PROFILE_D) /
            mean_score(PROFILE_A).
        cdi_pass: True when cdi >= config.cdi_threshold.
        per_profile_scores: Mean model score at each continuity profile.
        transition_deltas: List of (score_A − score_D) for matched pairs.
            Positive values mean the model scored the same patient higher
            when the record was complete (PROFILE_A) than when it was sparse
            (PROFILE_D) — the continuity bias.
        mean_transition_delta: Mean continuity bias across all matched pairs.
        config: The CCConfig used to produce this result.
    """

    cdi: float
    cdi_pass: bool
    per_profile_scores: Dict[str, float]
    transition_deltas: List[float]
    mean_transition_delta: float
    config: CCConfig
    raw_scores: Dict[str, List[float]] = field(default_factory=dict)

    def all_pass(self) -> bool:
        """Return True if every audit criterion passes."""
        return self.cdi_pass


class CCAudit:
    """
    Runs the Care Continuity (CC) adversarial axis audit.

    Usage::

        from hipaasynth.cc import CCAudit, CCConfig
        from hipaasynth.core.model_interface import MockClinicalModel

        audit  = CCAudit()
        result = audit.run(MockClinicalModel(), CCConfig(n_per_profile=100))
        print(result.cdi)         # Continuity Degradation Index
        print(result.cdi_pass)    # True / False
        print(result.mean_transition_delta)  # Continuity bias

    Args:
        generator: Optional pre-configured :class:`CCGenerator`.  If None,
            one is created from the seed in the supplied :class:`CCConfig`.
    """

    def __init__(self, generator: CCGenerator | None = None) -> None:
        self._generator = generator

    def run(
        self,
        model: ModelInterface,
        config: CCConfig | None = None,
    ) -> CCResult:
        """
        Execute the CC audit.

        Args:
            model: Any object implementing
                :class:`~hipaasynth.core.model_interface.ModelInterface`.
            config: Audit configuration.

        Returns:
            :class:`CCResult` with CDI, per-profile scores, and transition
            consistency measurement.
        """
        config = config or CCConfig()
        gen = self._generator or CCGenerator(seed=config.seed)

        # ── Per-profile scoring ──────────────────────────────────────────────
        cohort = gen.generate_all_profiles(n_per_profile=config.n_per_profile)

        raw_scores: Dict[str, List[float]] = {}
        per_profile_scores: Dict[str, float] = {}

        for profile in CONTINUITY_PROFILES:
            patients = cohort[profile]
            scores = [
                validate_model_score(model.evaluate(p), f"CC {profile}, patient {i}")
                for i, p in enumerate(patients)
            ]
            raw_scores[profile] = scores
            per_profile_scores[profile] = _mean(scores)

        d_score = per_profile_scores.get("PROFILE_D", 0.0)
        a_score = per_profile_scores.get("PROFILE_A", 1.0)
        cdi = d_score / a_score if a_score > 0 else 0.0

        # ── Transition consistency (continuity bias) ─────────────────────────
        # Generate matched pairs: same demographics, different completeness.
        # Delta = score(PROFILE_A) − score(PROFILE_D); positive = continuity bias.
        transition_deltas: List[float] = []
        for pair_idx in range(config.n_matched_pairs):
            pair_seed = config.seed + pair_idx + 1
            pair = gen.generate_matched_pair(base_seed=pair_seed)
            score_a = validate_model_score(
                model.evaluate(pair["PROFILE_A"]), f"CC matched pair {pair_idx} (PROFILE_A)")
            score_d = validate_model_score(
                model.evaluate(pair["PROFILE_D"]), f"CC matched pair {pair_idx} (PROFILE_D)")
            transition_deltas.append(round(score_a - score_d, 4))

        mean_delta = _mean(transition_deltas)

        return CCResult(
            cdi=round(cdi, 4),
            cdi_pass=cdi >= config.cdi_threshold,
            per_profile_scores=per_profile_scores,
            transition_deltas=transition_deltas,
            mean_transition_delta=mean_delta,
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
