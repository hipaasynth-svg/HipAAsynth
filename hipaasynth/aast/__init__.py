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

"""7-Axis Adversarial Stress Test (7AAST): one entry point across all axes."""

from hipaasynth.aast.adapter import (
    OUTPUT_TYPES,
    ModelAdapter,
    ModelResponse,
    parse_final_answer,
)
from hipaasynth.aast.stats import (
    FAIL,
    INCONCLUSIVE,
    PASS,
    Interval,
    NoiseFloor,
    Verdict,
    beyond_noise,
    bootstrap_interval,
    clopper_pearson,
    majority_decision,
    measure_noise_floor,
    verdict,
)

__all__ = [
    "FAIL",
    "INCONCLUSIVE",
    "OUTPUT_TYPES",
    "PASS",
    "Interval",
    "ModelAdapter",
    "ModelResponse",
    "NoiseFloor",
    "Verdict",
    "beyond_noise",
    "bootstrap_interval",
    "clopper_pearson",
    "majority_decision",
    "measure_noise_floor",
    "parse_final_answer",
    "verdict",
]
