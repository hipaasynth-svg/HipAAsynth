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

"""Downstream-utility probe (Tier 4, step 3).

Per ground rule 5, the probe's two moving parts — the ROC-AUC statistic and the
logistic learner — are verified against *constructed* reference cases (perfect /
inverted / tied separation; linearly-separable vs. pure-noise data) before the
probe is trusted to claim that a generated cohort carries learnable signal.
"""
import random

import pytest

from hipaasynth.core.config import GenerationConfig
from hipaasynth.pipelines.population_pipeline import generate_patients
from hipaasynth.validation.utility_probe import (
    downstream_utility_probe,
    roc_auc,
    train_logistic,
)


# ─────────────────────────────────────────────────────────────────────────────
# ROC-AUC against constructed reference cases.
# ─────────────────────────────────────────────────────────────────────────────
def test_auc_perfect_separation_is_one():
    assert roc_auc([0.1, 0.2, 0.8, 0.9], [0, 0, 1, 1]) == 1.0


def test_auc_inverted_separation_is_zero():
    assert roc_auc([0.9, 0.8, 0.2, 0.1], [0, 0, 1, 1]) == 0.0


def test_auc_constant_score_is_half():
    # All-tied scores → average-rank handling gives exactly chance.
    assert roc_auc([0.5, 0.5, 0.5, 0.5], [0, 1, 0, 1]) == 0.5


def test_auc_single_class_is_none():
    assert roc_auc([0.1, 0.2, 0.3], [1, 1, 1]) is None
    assert roc_auc([0.1, 0.2, 0.3], [0, 0, 0]) is None


def test_auc_mismatched_lengths_raises():
    with pytest.raises(ValueError):
        roc_auc([0.1, 0.2], [1])


# ─────────────────────────────────────────────────────────────────────────────
# The learner against constructed reference cases.
# ─────────────────────────────────────────────────────────────────────────────
def test_logistic_learns_linearly_separable_data():
    X = [[0.0], [0.1], [0.2], [0.9], [1.0], [1.1]]
    y = [0, 0, 0, 1, 1, 1]
    model = train_logistic(X, y, epochs=500, lr=0.5)
    preds = [model.predict(row) for row in X]
    assert preds == y


def test_logistic_on_pure_noise_is_near_chance():
    # Random features, random labels → no learnable signal. Train AUC on held-in
    # data must sit near 0.5 (a probe artifact would push it high on noise).
    rng = random.Random(1234)
    X = [[rng.gauss(0, 1), rng.gauss(0, 1)] for _ in range(200)]
    y = [rng.randint(0, 1) for _ in range(200)]
    model = train_logistic(X, y, epochs=300, lr=0.1)
    scores = [model.score(row) for row in X]
    auc = roc_auc(scores, y)
    assert auc is not None
    assert abs(auc - 0.5) < 0.15


# ─────────────────────────────────────────────────────────────────────────────
# The end-to-end probe on a generated cohort.
# ─────────────────────────────────────────────────────────────────────────────
def _diabetes_cohort(n=400, seed=21):
    cfg = GenerationConfig(patient_count=n, seed=seed, age_min=40, age_max=90,
                           include_visits=True, include_labs=True,
                           visits_min=1, visits_max=2)
    return generate_patients(cfg)


def test_probe_recovers_diabetes_signal():
    result = downstream_utility_probe(_diabetes_cohort(), seed=0)
    assert result.target == "type2_diabetes"
    # Learnable signal: AUC well above chance and clear lift over the
    # majority-class baseline.
    assert result.auc is not None and result.auc > 0.75
    assert result.accuracy >= result.baseline_accuracy
    assert result.accuracy_lift > 0.0


def test_probe_result_serializes():
    d = downstream_utility_probe(_diabetes_cohort(), seed=0).as_dict()
    assert set(d) >= {"target", "auc", "accuracy", "baseline_accuracy", "prevalence"}
    assert d["n_train"] + d["n_test"] == d["n_total"]


def test_probe_is_deterministic():
    a = downstream_utility_probe(_diabetes_cohort(), seed=0).as_dict()
    b = downstream_utility_probe(_diabetes_cohort(), seed=0).as_dict()
    assert a == b


def test_probe_rejects_single_class_target():
    # No patient has this condition → only one class → probe can't run.
    with pytest.raises(ValueError):
        downstream_utility_probe(_diabetes_cohort(), target="nonexistent_condition")


def test_probe_rejects_tiny_cohort():
    cfg = GenerationConfig(patient_count=5, seed=1)
    with pytest.raises(ValueError):
        downstream_utility_probe(generate_patients(cfg))
