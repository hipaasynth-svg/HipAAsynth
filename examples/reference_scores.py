# HipAAsynth — Synthetic health data fairness testing for invisible populations.
# Copyright (C) 2026 HipAAsynth Contributors. Licensed under the GNU AGPL v3+.
"""Run every published clinical score through 7AAST and print a Markdown table.

    python examples/reference_scores.py [n] [seed]

Regenerates the tables in docs/REFERENCE_RESULTS.md (same n and seed, same
numbers).
"""

from __future__ import annotations

import sys

from hipaasynth.aast.reference import REFERENCE_MODELS, reference_adapter
from hipaasynth.aast.run import run_7aast


def _pct(interval: dict | None) -> str:
    if not interval:
        return "n/a"
    return f"{interval['estimate']:.0%} ({interval['low']:.0%}–{interval['high']:.0%})"


def main(n: int = 1000, seed: int = 42) -> None:
    print(f"n = {n} synthetic patients per score (half true cases), seed {seed}, record input.\n")
    print("| Score | Overall | Catch rate (sensitivity) | Look-alikes cleared (specificity) "
          "| Failing checks |")  # fmt: skip
    print("|---|---|---|---|---|")
    details = []
    for name, (condition, _output, _rule) in REFERENCE_MODELS.items():
        report = run_7aast(reference_adapter(name, "record"), condition, n=n, seed=seed)
        acc = report.axis("accuracy").metrics
        failing = [f"{a.axis} {a.name.split(':')[0]}" for a in report.axes if a.status == "FAIL"]
        print(f"| {name} ({condition}) | {report.overall} | {_pct(acc['sensitivity'])} "
              f"| {_pct(acc['specificity'])} | {', '.join(failing) or 'none'} |")  # fmt: skip
        split = acc.get("sensitivity_by_presentation")
        if split:
            details.append((name, split))
    if details:
        print("\nSepsis catch rate by presentation:\n")
        print("| Score | Septic shock | Normal blood pressure |")
        print("|---|---|---|")
        for name, split in details:
            print(f"| {name} | {_pct(split.get('septic_shock'))} "
                  f"| {_pct(split.get('normotensive'))} |")  # fmt: skip


if __name__ == "__main__":
    main(*(int(a) for a in sys.argv[1:3]))
