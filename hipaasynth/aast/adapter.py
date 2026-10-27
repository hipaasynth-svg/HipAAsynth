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
One adapter for every kind of clinical model under test.

Deployed clinical models rarely answer yes/no. They emit a risk score that the
site thresholds (Epic Sepsis Model, Deterioration Index), an ordinal level (ESI
triage 1-5), a ranked differential, or free text (LLM assistants). The 7AAST
axes all need one thing from each answer: *did the model call this case
positive at its deployed operating point?* ``ModelAdapter`` turns any of five
output types into one :class:`ModelResponse` so every axis reads every model the
same way.

What the model reads
--------------------
``input="text"``    a written presentation of the patient (a note, a FHIR JSON
                    string, a patient message, a prompt). LLMs and NLP models.
``input="record"``  a structured patient record (``dict``). Tabular risk models
                    such as the Epic Sepsis Model or the Deterioration Index.

Axes that compare the same patient across written forms (DIF, Axes 1-4) only
apply to ``text`` models; each axis declares which inputs it supports.

Output types
------------
``binary``   ``fn`` returns ``True``/``False``.
``score``    ``fn`` returns a finite real number; ``threshold`` is the site's
             deployed alert cutoff. Positive when ``score >= threshold``
             (``score <= threshold`` with ``higher_is_positive=False``).
``ordinal``  ``fn`` returns an ``int`` level; positive when the level is in
             ``acute_levels`` (e.g. ESI ``{1, 2}``).
``ranked``   ``fn`` returns a sequence of labels, best first; positive when the
             case's ``target`` label is within the top ``k``.
``text``     ``fn`` returns a string; ``parser`` maps it to ``True``/``False``,
             or ``None`` when no answer can be read.

Outcomes are never guessed
--------------------------
* ``None`` from ``fn`` (any type) is an explicit refusal: ``abstained=True``.
* For ``text``, a match of ``abstain_patterns`` is ``abstained=True`` and an
  unreadable answer is ``parse_failed=True``. Free text is untrusted output, so
  it is counted, never raised.
* For the structured types, an answer of the wrong type (a string from a score
  model, NaN, ``1`` from a binary model) is an integration bug, not a model
  outcome, and raises ``TypeError``/``ValueError`` so it cannot be miscounted.

A text model's self-reported confidence ("I am 80% sure") is not a score:
LLM verbalised confidence is poorly calibrated, so ``text`` responses never set
``score``. Use ``output="score"`` only for a model-native score.

All logic is deterministic and uses only the Python standard library.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from numbers import Real
from typing import Any

INPUT_TYPES = ("text", "record")
OUTPUT_TYPES = ("binary", "score", "ordinal", "ranked", "text")

# Same terminator convention as the Axis 5 evaluator's prompts.
_FINAL_ANSWER_RE = re.compile(r"FINAL_ANSWER\s*:\s*(Yes|No)\b", re.IGNORECASE)
DEFAULT_ABSTAIN_PATTERNS = (r"FINAL_ANSWER\s*:\s*(Unsure|Abstain|Cannot\s+determine|Unknown)\b",)


def parse_final_answer(raw: str) -> bool | None:
    """Default ``text`` parser: the last ``FINAL_ANSWER: Yes|No`` wins.

    Returns ``None`` when the terminator is absent, so prose that merely
    mentions "yes" is never read as a decision.
    """
    matches = _FINAL_ANSWER_RE.findall(raw)
    if not matches:
        return None
    return str(matches[-1]).lower() == "yes"


@dataclass(frozen=True)
class ModelResponse:
    """One normalised answer from the model under test.

    Attributes:
        decision:     Positive call at the deployed operating point, or ``None``
                      when the model abstained or the answer could not be read.
        score:        Model-native score (``score`` type only).
        level:        Ordinal level (``ordinal`` type only).
        rank:         1-based rank of the target label (``ranked`` type only);
                      ``None`` when the target is absent from the list.
        abstained:    The model explicitly declined to answer.
        parse_failed: A ``text`` answer that no decision could be read from.
        raw:          ``repr`` of the model's verbatim output, for the audit trail.
    """

    decision: bool | None
    score: float | None = None
    level: int | None = None
    rank: int | None = None
    abstained: bool = False
    parse_failed: bool = False
    raw: str = ""

    @property
    def answered(self) -> bool:
        """True when the response carries a usable decision."""
        return self.decision is not None


class ModelAdapter:
    """Wrap a model callable so every 7AAST axis can read its answers.

    Args:
        fn:                 The model. Called with the case each axis supplies:
                            a ``str`` for ``input="text"``, a ``dict`` record for
                            ``input="record"``.
        output:             One of :data:`OUTPUT_TYPES`.
        input:              One of :data:`INPUT_TYPES`: what the model reads.
        threshold:          ``score`` only: the deployed alert cutoff.
        higher_is_positive: ``score`` only: direction of the cutoff.
        acute_levels:       ``ordinal`` only: the levels that count as positive.
        k:                  ``ranked`` only: how deep in the list counts.
        parser:             ``text`` only: ``str -> bool | None``. Defaults to
                            :func:`parse_final_answer`.
        abstain_patterns:   ``text`` only: regexes that mark a refusal.
        name:               Label used in reports.

    Raises:
        ValueError: on an unknown output type, or a setting that is missing or
            does not apply to the chosen type.
    """

    def __init__(
        self,
        fn: Callable[[Any], Any],
        output: str,
        *,
        input: str,
        threshold: float | None = None,
        higher_is_positive: bool = True,
        acute_levels: Sequence[int] | None = None,
        k: int | None = None,
        parser: Callable[[str], bool | None] | None = None,
        abstain_patterns: Sequence[str] | None = None,
        name: str = "model",
    ) -> None:
        if not callable(fn):
            raise TypeError("fn must be callable")
        if output not in OUTPUT_TYPES:
            raise ValueError(f"output must be one of {OUTPUT_TYPES}, got {output!r}")
        if input not in INPUT_TYPES:
            raise ValueError(f"input must be one of {INPUT_TYPES}, got {input!r}")

        given = {
            "threshold": threshold is not None,
            "acute_levels": acute_levels is not None,
            "k": k is not None,
            "parser": parser is not None,
            "abstain_patterns": abstain_patterns is not None,
        }
        allowed = {
            "binary": set(),
            "score": {"threshold"},
            "ordinal": {"acute_levels"},
            "ranked": {"k"},
            "text": {"parser", "abstain_patterns"},
        }[output]
        stray = sorted(key for key, was_given in given.items() if was_given and key not in allowed)
        if stray:
            raise ValueError(f"{', '.join(stray)} does not apply to output={output!r}")

        if output == "score":
            if threshold is None:
                raise ValueError("output='score' needs threshold= (the deployed alert cutoff)")
            if (
                isinstance(threshold, bool)
                or not isinstance(threshold, Real)
                or not math.isfinite(threshold)
            ):
                raise ValueError(f"threshold must be a finite number, got {threshold!r}")
            threshold = float(threshold)
        if output == "ordinal":
            if not acute_levels:
                raise ValueError("output='ordinal' needs acute_levels= (e.g. {1, 2} for ESI)")
            if any(isinstance(v, bool) or not isinstance(v, int) for v in acute_levels):
                raise ValueError(f"acute_levels must be ints, got {list(acute_levels)!r}")
        if output == "ranked" and (
            k is None or isinstance(k, bool) or not isinstance(k, int) or k < 1
        ):
            raise ValueError(f"output='ranked' needs an int k >= 1, got {k!r}")

        self.fn = fn
        self.output = output
        self.input = input
        self.threshold = threshold
        self.higher_is_positive = bool(higher_is_positive)
        self.acute_levels = frozenset(acute_levels) if acute_levels is not None else None
        self.k = k
        self.parser = parser or parse_final_answer
        patterns = DEFAULT_ABSTAIN_PATTERNS if abstain_patterns is None else abstain_patterns
        self._abstain_res = tuple(re.compile(p, re.IGNORECASE) for p in patterns)
        self._abstain_patterns = tuple(patterns)
        self.name = name

    # ------------------------------------------------------------------ public

    def respond(self, case: Any, *, target: str | None = None) -> ModelResponse:
        """Call the model on ``case`` and normalise its answer.

        Args:
            case:   What the axis supplies: a ``str`` for ``input="text"``, a
                    mapping for ``input="record"``.
            target: ``ranked`` only: the correct label for this case.

        Raises:
            TypeError: when ``case`` does not match ``input``. That is an axis
                bug (it handed the model the wrong kind of input), never a
                model outcome.
        """
        if self.input == "text" and not isinstance(case, str):
            raise TypeError(
                f"{self.name}: input='text' needs a str case, got {type(case).__name__}"
            )
        if self.input == "record" and not isinstance(case, Mapping):
            raise TypeError(
                f"{self.name}: input='record' needs a mapping case, got {type(case).__name__}"
            )
        if self.output == "ranked" and target is None:
            raise ValueError("output='ranked' needs target= (the correct label for this case)")
        raw = self.fn(case)
        if raw is None:
            return ModelResponse(decision=None, abstained=True, raw="None")
        handler: Callable[[Any, str | None], ModelResponse] = getattr(self, f"_from_{self.output}")
        return handler(raw, target)

    def describe(self) -> dict[str, Any]:
        """Settings that determine how answers are read, for reports and hashing.

        Every key is always present, so reports and their hashes have one fixed
        layout regardless of output type.
        """
        return {
            "name": self.name,
            "input": self.input,
            "output": self.output,
            "threshold": self.threshold,
            "higher_is_positive": self.higher_is_positive if self.output == "score" else None,
            "acute_levels": sorted(self.acute_levels) if self.acute_levels is not None else None,
            "k": self.k,
            "parser": (
                getattr(self.parser, "__qualname__", repr(self.parser))
                if self.output == "text"
                else None
            ),
            "abstain_patterns": list(self._abstain_patterns) if self.output == "text" else None,
        }

    # ---------------------------------------------------------------- handlers

    def _from_binary(self, raw: Any, target: str | None) -> ModelResponse:
        if not isinstance(raw, bool):
            raise TypeError(
                f"{self.name}: output='binary' must return True/False (or None to abstain), "
                f"got {type(raw).__name__} {raw!r}"
            )
        return ModelResponse(decision=raw, raw=repr(raw))

    def _from_score(self, raw: Any, target: str | None) -> ModelResponse:
        if isinstance(raw, bool) or not isinstance(raw, Real):
            raise TypeError(
                f"{self.name}: output='score' must return a number (or None to abstain), "
                f"got {type(raw).__name__} {raw!r}"
            )
        score = float(raw)
        if not math.isfinite(score):
            raise ValueError(f"{self.name}: score must be finite, got {raw!r}")
        assert self.threshold is not None  # guaranteed by __init__
        if self.higher_is_positive:
            decision = score >= self.threshold
        else:
            decision = score <= self.threshold
        return ModelResponse(decision=decision, score=score, raw=repr(raw))

    def _from_ordinal(self, raw: Any, target: str | None) -> ModelResponse:
        if isinstance(raw, bool) or not isinstance(raw, int):
            raise TypeError(
                f"{self.name}: output='ordinal' must return an int level (or None to abstain), "
                f"got {type(raw).__name__} {raw!r}"
            )
        assert self.acute_levels is not None  # guaranteed by __init__
        return ModelResponse(decision=raw in self.acute_levels, level=raw, raw=repr(raw))

    def _from_ranked(self, raw: Any, target: str | None) -> ModelResponse:
        if isinstance(raw, (str, bytes)) or not isinstance(raw, Sequence):
            raise TypeError(
                f"{self.name}: output='ranked' must return a list of labels (or None to "
                f"abstain), got {type(raw).__name__} {raw!r}"
            )
        labels = list(raw)
        if not all(isinstance(label, str) for label in labels):
            raise TypeError(f"{self.name}: ranked labels must be strings, got {labels!r}")
        wanted = _norm_label(target)
        rank = next((i for i, label in enumerate(labels, 1) if _norm_label(label) == wanted), None)
        assert self.k is not None  # guaranteed by __init__
        decision = rank is not None and rank <= self.k
        return ModelResponse(decision=decision, rank=rank, raw=repr(labels))

    def _from_text(self, raw: Any, target: str | None) -> ModelResponse:
        if not isinstance(raw, str):
            raise TypeError(
                f"{self.name}: output='text' must return a string (or None to abstain), "
                f"got {type(raw).__name__} {raw!r}"
            )
        if any(rx.search(raw) for rx in self._abstain_res):
            return ModelResponse(decision=None, abstained=True, raw=repr(raw))
        decision = self.parser(raw)
        if decision is not None and not isinstance(decision, bool):
            raise TypeError(
                f"{self.name}: parser must return True, False or None, got {decision!r}"
            )
        return ModelResponse(decision=decision, parse_failed=decision is None, raw=repr(raw))


def _norm_label(label: str | None) -> str:
    """Case- and whitespace-insensitive label comparison for ranked outputs."""
    return " ".join((label or "").lower().split())
