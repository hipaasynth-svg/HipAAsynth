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

A synthetic dataset is only useful if a model can *learn* from it. This module
runs a minimal "train on synthetic" probe: it trains a tiny baseline classifier
on a generated cohort to predict a ground-truth condition from patient features,
and reports how well it does (test accuracy, ROC-AUC, and lift over the
majority-class baseline).

The point is to demonstrate that **learnable signal exists** — that the engine's
feature→label couplings (e.g. diabetes raising glucose, age/BMI raising diabetes
risk) survive round-tripping through the exported table and are recoverable by a
learner — **not** to build production ML. It is therefore a deliberately small,
**pure-Python** logistic-regression + z-score standardizer with no numpy/sklearn
dependency; a hand-rolled learner is honestly adequate for a signal-existence
probe, and keeping the core stdlib-only matters more here than raw model quality.

Default target: ``type2_diabetes``. The engine draws a diabetic's Glucose as
``max(baseline, N(164, 40))`` and raises diabetes incidence with age and BMI
(``generator_conditions``), so ``[age, bmi, mean Glucose, …]`` carries real
signal an untrained baseline (majority class) does not.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

# Numeric feature columns pulled from each patient. Missing values are imputed to
# the training-set column mean (i.e. a standardized 0), so a patient lacking an
# analyte contributes no artificial signal.
FEATURE_NAMES: List[str] = ["age", "bmi", "Glucose", "Creatinine", "LDL", "WBC"]
_LAB_FEATURES = {"Glucose", "Creatinine", "LDL", "WBC"}
DEFAULT_TARGET = "type2_diabetes"


# ─────────────────────────────────────────────────────────────────────────────
# Metrics — verified against constructed reference cases in the tests.
# ─────────────────────────────────────────────────────────────────────────────
def roc_auc(scores: Sequence[float], labels: Sequence[int]) -> Optional[float]:
    """ROC-AUC via the rank-sum (Mann–Whitney U) identity, tie-aware.

    Returns the probability that a random positive scores above a random
    negative (0.5 = chance, 1.0 = perfect separation, 0.0 = perfectly inverted).
    ``None`` when AUC is undefined — only one class present, or no data. Ties are
    handled with average ranks, so a constant score gives exactly 0.5.
    """
    if len(scores) != len(labels):
        raise ValueError("roc_auc requires equal-length scores and labels")
    n = len(scores)
    n_pos = sum(1 for y in labels if y == 1)
    n_neg = n - n_pos
    if n_pos == 0 or n_neg == 0:
        return None

    # Average ranks (1-based), ties share the mean of their rank block.
    order = sorted(range(n), key=lambda i: scores[i])
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and scores[order[j + 1]] == scores[order[i]]:
            j += 1
        avg_rank = (i + j) / 2.0 + 1.0  # 1-based average of positions i..j
        for k in range(i, j + 1):
            ranks[order[k]] = avg_rank
        i = j + 1

    rank_sum_pos = sum(ranks[i] for i in range(n) if labels[i] == 1)
    return (rank_sum_pos - n_pos * (n_pos + 1) / 2.0) / (n_pos * n_neg)


def accuracy(predictions: Sequence[int], labels: Sequence[int]) -> float:
    if not labels:
        return 0.0
    return sum(1 for p, y in zip(predictions, labels) if p == y) / len(labels)


# ─────────────────────────────────────────────────────────────────────────────
# Minimal pure-Python logistic regression.
# ─────────────────────────────────────────────────────────────────────────────
def _sigmoid(z: float) -> float:
    # Numerically stable logistic.
    if z >= 0:
        ez = math.exp(-z)
        return 1.0 / (1.0 + ez)
    ez = math.exp(z)
    return ez / (1.0 + ez)


@dataclass
class LogisticModel:
    weights: List[float]
    bias: float
    feature_means: List[float]
    feature_stds: List[float]

    def _standardize(self, row: Sequence[float]) -> List[float]:
        return [
            (row[j] - self.feature_means[j]) / self.feature_stds[j]
            for j in range(len(row))
        ]

    def score(self, row: Sequence[float]) -> float:
        z = self.bias + sum(w * x for w, x in zip(self.weights, self._standardize(row)))
        return _sigmoid(z)

    def predict(self, row: Sequence[float], threshold: float = 0.5) -> int:
        return 1 if self.score(row) >= threshold else 0


def train_logistic(
    X: Sequence[Sequence[float]],
    y: Sequence[int],
    *,
    epochs: int = 400,
    lr: float = 0.1,
    l2: float = 0.0,
) -> LogisticModel:
    """Train logistic regression by full-batch gradient descent on z-scored X.

    Deterministic: no randomness in the optimizer. Features are standardized
    using the *training* mean/std (folded into the returned model so inference
    standardizes identically). A zero-variance column is given std 1 so it
    contributes nothing rather than dividing by zero.
    """
    n = len(X)
    if n == 0:
        raise ValueError("cannot train on an empty dataset")
    d = len(X[0])

    means = [sum(row[j] for row in X) / n for j in range(d)]
    stds = []
    for j in range(d):
        var = sum((row[j] - means[j]) ** 2 for row in X) / n
        stds.append(math.sqrt(var) if var > 0 else 1.0)

    Xs = [[(row[j] - means[j]) / stds[j] for j in range(d)] for row in X]

    w = [0.0] * d
    b = 0.0
    for _ in range(epochs):
        gw = [0.0] * d
        gb = 0.0
        for xi, yi in zip(Xs, y):
            p = _sigmoid(b + sum(w[j] * xi[j] for j in range(d)))
            err = p - yi
            for j in range(d):
                gw[j] += err * xi[j]
            gb += err
        for j in range(d):
            w[j] -= lr * (gw[j] / n + l2 * w[j])
        b -= lr * (gb / n)

    return LogisticModel(weights=w, bias=b, feature_means=means, feature_stds=stds)


# ─────────────────────────────────────────────────────────────────────────────
# Feature extraction + deterministic split.
# ─────────────────────────────────────────────────────────────────────────────
def _patient_mean_lab(patient: Any, lab_name: str) -> Optional[float]:
    vals = [lab.value for v in patient.visits for lab in v.labs if lab.lab_name == lab_name]
    return sum(vals) / len(vals) if vals else None


def extract_features(patient: Any) -> Tuple[List[Optional[float]], int, str]:
    """Return ``(raw_feature_row, label, patient_id)`` for one patient.

    Lab features are per-patient means; a missing analyte is ``None`` (imputed to
    the column mean later). The label is unused by the caller here — the target
    is resolved in :func:`downstream_utility_probe`.
    """
    row: List[Optional[float]] = []
    for name in FEATURE_NAMES:
        if name == "age":
            row.append(float(patient.demographics.age))
        elif name == "bmi":
            row.append(float(patient.anthropometrics.bmi))
        elif name in _LAB_FEATURES:
            row.append(_patient_mean_lab(patient, name))
        else:  # pragma: no cover - guarded by FEATURE_NAMES
            row.append(None)
    return row, 0, patient.demographics.patient_id


def _impute(rows: List[List[Optional[float]]]) -> List[List[float]]:
    """Replace ``None`` in each column with that column's observed mean."""
    if not rows:
        return []
    d = len(rows[0])
    col_means: List[float] = []
    for j in range(d):
        present = [r[j] for r in rows if r[j] is not None]
        col_means.append(sum(present) / len(present) if present else 0.0)
    return [[(r[j] if r[j] is not None else col_means[j]) for j in range(d)] for r in rows]


def _split(
    n: int, test_fraction: float, seed: int
) -> Tuple[List[int], List[int]]:
    """Deterministic index split into (train, test)."""
    idx = list(range(n))
    random.Random(seed).shuffle(idx)
    n_test = max(1, int(round(n * test_fraction)))
    return idx[n_test:], idx[:n_test]


@dataclass
class UtilityProbeResult:
    target: str
    n_total: int
    n_train: int
    n_test: int
    prevalence: float
    baseline_accuracy: float
    accuracy: float
    auc: Optional[float]
    accuracy_lift: float
    feature_names: List[str]
    note: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return {
            "target": self.target,
            "n_total": self.n_total,
            "n_train": self.n_train,
            "n_test": self.n_test,
            "prevalence": round(self.prevalence, 4),
            "baseline_accuracy": round(self.baseline_accuracy, 4),
            "accuracy": round(self.accuracy, 4),
            "auc": None if self.auc is None else round(self.auc, 4),
            "accuracy_lift": round(self.accuracy_lift, 4),
            "feature_names": list(self.feature_names),
            "note": self.note,
        }


def downstream_utility_probe(
    patients: Sequence[Any],
    *,
    target: str = DEFAULT_TARGET,
    test_fraction: float = 0.3,
    seed: int = 0,
    epochs: int = 400,
    lr: float = 0.1,
) -> UtilityProbeResult:
    """Train-on-synthetic probe: can a baseline learner recover ``target``?

    Trains the pure-Python logistic model on a deterministic train split and
    reports test-set accuracy, ROC-AUC, and lift over the majority-class
    baseline. A meaningful AUC well above 0.5 is evidence that the engine's
    feature→label signal is real and learnable.

    Raises ``ValueError`` if the cohort is too small or a class is absent in the
    train or test split (AUC would be undefined and the probe uninformative).
    """
    patients = list(patients)
    if len(patients) < 10:
        raise ValueError("utility probe needs at least 10 patients")

    raw_rows: List[List[Optional[float]]] = []
    labels: List[int] = []
    for p in patients:
        row, _, _ = extract_features(p)
        raw_rows.append(row)
        labels.append(1 if any(c.name == target for c in p.conditions) else 0)

    if len(set(labels)) < 2:
        raise ValueError(
            f"target {target!r} has only one class in this cohort; probe needs both"
        )

    X = _impute(raw_rows)
    train_idx, test_idx = _split(len(patients), test_fraction, seed)
    y_train = [labels[i] for i in train_idx]
    y_test = [labels[i] for i in test_idx]
    if len(set(y_train)) < 2 or len(set(y_test)) < 2:
        raise ValueError(
            "train/test split left a fold with a single class; increase cohort "
            "size, raise target prevalence, or change the split seed"
        )

    model = train_logistic(
        [X[i] for i in train_idx], y_train, epochs=epochs, lr=lr
    )

    scores = [model.score(X[i]) for i in test_idx]
    preds = [1 if s >= 0.5 else 0 for s in scores]
    acc = accuracy(preds, y_test)
    auc = roc_auc(scores, y_test)

    # Majority-class baseline on the test fold.
    pos_rate = sum(y_test) / len(y_test)
    baseline = max(pos_rate, 1 - pos_rate)

    return UtilityProbeResult(
        target=target,
        n_total=len(patients),
        n_train=len(train_idx),
        n_test=len(test_idx),
        prevalence=sum(labels) / len(labels),
        baseline_accuracy=baseline,
        accuracy=acc,
        auc=auc,
        accuracy_lift=acc - baseline,
        feature_names=list(FEATURE_NAMES),
        note="Pure-Python logistic-regression signal-existence probe; not a "
             "production model. AUC>>0.5 indicates learnable feature->label signal.",
    )
