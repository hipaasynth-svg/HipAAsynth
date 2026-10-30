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

"""File in, file out: test any model, including ones nobody can call directly.

1. :func:`export_cases` writes every case a 7AAST run will show the model, one
   JSON object per line (``case_id``, ``input``), plus an answers template.
2. The customer runs those cases through their model however they normally do
   (inside the EHR, a batch job, a vendor portal) and fills in ``answer``.
3. :func:`answers_adapter` turns the answers file into a model, and
   ``run_7aast`` produces the report as if it had called the model itself.

A ``case_id`` is the SHA-256 of the case content, and cohorts are seeded, so
the same settings reproduce the same cases and the answers line up exactly. A
case the answers file does not cover stops the run with a clear error rather
than being guessed.

Answer formats by output type: ``binary`` yes/no, true/false or 1/0; ``score``
a number; ``ordinal`` an integer; ``ranked`` labels separated by ``|``; ``text``
the model's text. A blank answer is an abstention.

A file of single answers cannot show re-run noise, so the noise floor of a
file-based run reflects only that the answers are fixed.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from hipaasynth.aast.adapter import ModelAdapter
from hipaasynth.aast.cases import case_id
from hipaasynth.aast.run import run_7aast

_TRUE = {"yes", "y", "true", "t", "1", "positive"}
_FALSE = {"no", "n", "false", "f", "0", "negative"}


class AnswerFileError(ValueError):
    """The answers file is missing, malformed, or does not match the cases."""


def export_cases(
    path: str | Path,
    *,
    condition: str,
    input_type: str,
    n: int = 200,
    seed: int = 42,
    prevalence: float = 0.5,
    profile: str | None = None,
    balance_groups: bool = True,
) -> dict[str, Any]:
    """Write every case a run with these settings will show the model.

    Writes ``path`` (JSON Lines: ``{"case_id", "input"}``) and an answers
    template next to it (``<stem>_answers.csv`` with ``case_id,answer``).

    Returns:
        ``{"cases": <unique cases>, "cases_file": ..., "answers_template": ...}``.
    """
    seen: dict[str, Any] = {}

    def record(case: Any) -> None:
        seen.setdefault(case_id(case), case)

    run_7aast(
        ModelAdapter(record, "binary", input=input_type, name="export"),
        condition,
        n=n,
        seed=seed,
        prevalence=prevalence,
        profile=profile,
        balance_groups=balance_groups,
    )
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for cid, case in seen.items():
            fh.write(json.dumps({"case_id": cid, "input": case}, sort_keys=True) + "\n")
    template = path.with_name(f"{path.stem}_answers.csv")
    with template.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["case_id", "answer"])
        for cid in seen:
            writer.writerow([cid, ""])
    return {"cases": len(seen), "cases_file": str(path), "answers_template": str(template)}


def load_answers(path: str | Path) -> dict[str, str]:
    """``{case_id: raw answer}`` from a ``.csv`` (case_id,answer) or ``.jsonl`` file."""
    path = Path(path)
    if not path.is_file():
        raise AnswerFileError(f"answers file not found: {path}")
    answers: dict[str, str] = {}
    if path.suffix.lower() == ".jsonl":
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
                answers[str(row["case_id"])] = "" if row.get("answer") is None else row["answer"]
            except (ValueError, KeyError, TypeError) as err:
                raise AnswerFileError(f"{path}:{n}: not a {{case_id, answer}} object") from err
        return answers
    with path.open(encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        if not reader.fieldnames or not {"case_id", "answer"} <= set(reader.fieldnames):
            raise AnswerFileError(f"{path}: needs a header row with case_id and answer")
        for row in reader:
            answers[row["case_id"].strip()] = row["answer"] or ""
    return answers


def _parse(raw: Any, output: str, cid: str) -> Any:
    if not isinstance(raw, str):
        if output == "text" and raw is not None:
            raw = str(raw)
        elif raw is None:
            return None
        else:
            raw = json.dumps(raw) if isinstance(raw, list) else str(raw)
    text = raw.strip()
    if text == "":
        return None
    try:
        if output == "binary":
            low = text.lower()
            if low in _TRUE:
                return True
            if low in _FALSE:
                return False
            raise ValueError("expected yes/no, true/false or 1/0")
        if output == "score":
            return float(text)
        if output == "ordinal":
            return int(text)
        if output == "ranked":
            if text.startswith("["):
                return [str(x) for x in json.loads(text)]
            return [part.strip() for part in text.split("|") if part.strip()]
        return raw
    except ValueError as err:
        raise AnswerFileError(
            f"case {cid[:12]}: cannot read {output} answer {raw!r}: {err}"
        ) from err


def answers_adapter(path: str | Path, output: str, *, input: str, **settings: Any) -> ModelAdapter:
    """A :class:`ModelAdapter` that answers from a filled-in answers file.

    ``settings`` are the usual adapter settings (``threshold``, ``acute_levels``,
    ``k``, ``parser``, ``abstain_patterns``, ``name``).
    """
    answers = load_answers(path)
    settings.setdefault("name", f"answers from {Path(path).name}")

    def model(case: Any) -> Any:
        cid = case_id(case)
        if cid not in answers:
            raise AnswerFileError(
                f"the answers file has no answer for case {cid[:12]}...: export the cases again "
                "with the same condition, input, n, seed, prevalence and profile as this run"
            )
        return _parse(answers[cid], output, cid)

    return ModelAdapter(model, output, input=input, **settings)
