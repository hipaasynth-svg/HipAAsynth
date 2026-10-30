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

"""``hipaasynth 7aast``: run the 7-Axis Adversarial Stress Test from a terminal.

Try it with a built-in demo model::

    hipaasynth 7aast run --condition sepsis --input text --demo demo_biased

Test your own model by file (no integration needed)::

    hipaasynth 7aast export --condition sepsis --input record --out cases.jsonl
    #   ... run cases.jsonl through your model, fill in cases_answers.csv ...
    hipaasynth 7aast run --condition sepsis --input record --output score \\
        --threshold 6 --answers cases_answers.csv --report report.json

Or call a Python function ``module:function`` that takes one case::

    hipaasynth 7aast run --condition stroke --input text --output text \\
        --model my_package.my_model:predict

Use the same --condition, --input, --n, --seed, --prevalence and --profile for
``export`` and ``run``.

Save the report (``.html`` to read, ``.json`` for systems) and check it later::

    hipaasynth 7aast run --condition sepsis --input text --demo demo_biased \\
        --report report.html
    hipaasynth 7aast verify report.html --regenerate
"""

from __future__ import annotations

import argparse
import importlib
import sys
from typing import Any

from hipaasynth.aast.adapter import INPUT_TYPES, OUTPUT_TYPES, ModelAdapter
from hipaasynth.aast.demo import DEMO_MODELS, demo_adapter
from hipaasynth.aast.files import AnswerFileError, answers_adapter, export_cases
from hipaasynth.aast.report import load_document, verify, write_report
from hipaasynth.aast.run import AASTReport, run_7aast
from hipaasynth.decision_cohort import TRUTH_FLAG

_ICON = {
    "PASS": "PASS",
    "FAIL": "FAIL",
    "INCONCLUSIVE": "INCONCLUSIVE",
    "DESCRIPTIVE": "INFO",
    "NOT_APPLICABLE": "n/a",
}


def summary_text(report: AASTReport) -> str:
    """The report as plain text for a terminal."""
    s = report.settings
    lines = []
    if report.demo:
        lines.append("*** DEMO MODEL: not a clinical tool ***")
    lines += [
        (
            f"7AAST  {s['condition']}  |  model: {report.model['name']} "
            f"({report.model['input']} in, {report.model['output']} out)"
        ),
        (
            f"{s['n']} synthetic patients ({s['true_cases']} true cases, the rest look-alikes), "
            f"seed {s['seed']}, engine {report.engine_version}"
        ),
        "",
        f"OVERALL: {report.overall}",
        "",
    ]
    for a in report.axes:
        label = f"{'Axis ' + a.axis if a.axis[0].isdigit() else a.name}"
        name = a.name if a.axis[0].isdigit() else ""
        lines.append(f"  [{_ICON.get(a.status, a.status):>12}]  {label}  {name}".rstrip())
        lines.append(f"                  {a.summary}")
        if a.status == "INCONCLUSIVE" and a.reason:
            lines.append(f"                  ({a.reason})")
    r = report.answer_rates
    lines += [
        "",
        (
            f"Model calls: {report.model_calls}.  Answers on the main cases: {r['answered']} of "
            f"{r['cases']} ({r['abstained']} declined, {r['unreadable']} unreadable)."
        ),
    ]
    lines += [f"Note: {note}" for note in report.limitations]
    return "\n".join(lines)


def _load_function(spec: str) -> Any:
    module_name, _, attr = spec.partition(":")
    if not module_name or not attr:
        raise ValueError(f"--model must look like module:function, got {spec!r}")
    return getattr(importlib.import_module(module_name), attr)


def _adapter_settings(args: argparse.Namespace) -> dict[str, Any]:
    settings: dict[str, Any] = {}
    if args.threshold is not None:
        settings["threshold"] = args.threshold
    if args.lower_is_positive:
        settings["higher_is_positive"] = False
    if args.acute_levels:
        settings["acute_levels"] = {int(x) for x in args.acute_levels.split(",") if x.strip()}
    if args.k is not None:
        settings["k"] = args.k
    if args.name:
        settings["name"] = args.name
    return settings


def _common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--condition", required=True, choices=sorted(TRUTH_FLAG))
    p.add_argument("--input", required=True, choices=INPUT_TYPES,
                   help="What the model reads: written text or a structured record.")  # fmt: skip
    p.add_argument("--n", type=int, default=200, help="Synthetic patients (default 200).")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--prevalence", type=float, default=0.5,
                   help="Share of true cases (default 0.5).")  # fmt: skip
    p.add_argument("--profile", default=None, help="Bundled population profile name or path.")
    p.add_argument("--natural-mix", action="store_true",
                   help="Without a profile, keep the default population's race/ethnicity mix "
                   "instead of representing every group equally.")  # fmt: skip


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hipaasynth 7aast",
        description="7-Axis Adversarial Stress Test on synthetic patients.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split("\n", 2)[2] if __doc__ else None,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    exp = sub.add_parser("export", help="Write the cases for a file-based run.")
    _common(exp)
    exp.add_argument("--out", required=True, help="Cases file to write (.jsonl).")

    run = sub.add_parser("run", help="Run 7AAST and print the report.")
    _common(run)
    source = run.add_mutually_exclusive_group(required=True)
    source.add_argument("--demo", choices=DEMO_MODELS, help="Use a built-in DEMO model.")
    source.add_argument("--answers", help="Filled-in answers file from 'export'.")
    source.add_argument("--model", help="Python function module:function taking one case.")
    run.add_argument("--output", choices=OUTPUT_TYPES, default="binary",
                     help="What the model answers (default binary).")  # fmt: skip
    run.add_argument("--threshold", type=float, help="score: the deployed alert cutoff.")
    run.add_argument("--lower-is-positive", action="store_true",
                     help="score: lower scores are positive.")  # fmt: skip
    run.add_argument("--acute-levels", help="ordinal: positive levels, e.g. 1,2.")
    run.add_argument("--k", type=int, help="ranked: how deep in the list counts.")
    run.add_argument("--name", help="Model name for the report.")
    run.add_argument("--deployment-prevalence", type=float,
                     help="Real-world prevalence, for a positive predictive value estimate.")  # fmt: skip
    run.add_argument("--report",
                     help="Also save the full report here: .html to read, .json for systems.")  # fmt: skip

    ver = sub.add_parser("verify", help="Check a saved report has not been changed.")
    ver.add_argument("report", help="Report file (.json or .html) from 'run --report'.")
    ver.add_argument("--regenerate", action="store_true",
                     help="Also rebuild every case from the seed and compare.")  # fmt: skip
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exit_:
        # argparse exits 2 on a usage error; 2 means "a check failed" here, so a
        # typo in a pipeline must not read as a failed model.
        return 1 if exit_.code == 2 else int(exit_.code or 0)
    try:
        if args.command == "verify":
            result = verify(load_document(args.report), regenerate=args.regenerate)
            print(result.text())
            return 0 if result.ok else 3
        if args.command == "export":
            out = export_cases(
                args.out,
                condition=args.condition,
                input_type=args.input,
                n=args.n,
                seed=args.seed,
                prevalence=args.prevalence,
                profile=args.profile,
                balance_groups=not args.natural_mix,
            )
            print(f"Wrote {out['cases']} cases to {out['cases_file']}.")
            print(f"Fill in the 'answer' column of {out['answers_template']} and run:")
            print(
                f"  hipaasynth 7aast run --condition {args.condition} --input {args.input} "
                f"--n {args.n} --seed {args.seed} --answers {out['answers_template']}"
                + (" --natural-mix" if args.natural_mix else "")
            )
            return 0
        if args.demo:
            if args.output != "binary":
                parser.error("--demo models answer yes/no; leave --output as binary")
            adapter = demo_adapter(args.demo, args.condition, args.input)
        elif args.answers:
            adapter = answers_adapter(
                args.answers, args.output, input=args.input, **_adapter_settings(args)
            )
        else:
            fn = _load_function(args.model)
            settings = _adapter_settings(args)
            settings.setdefault("name", args.model)
            adapter = ModelAdapter(fn, args.output, input=args.input, **settings)
        report = run_7aast(
            adapter,
            args.condition,
            n=args.n,
            seed=args.seed,
            prevalence=args.prevalence,
            profile=args.profile,
            deployment_prevalence=args.deployment_prevalence,
            demo=bool(args.demo),
            balance_groups=not args.natural_mix,
        )
    except (AnswerFileError, ValueError, TypeError, ImportError, AttributeError, OSError) as err:
        print(f"hipaasynth 7aast: error: {err}", file=sys.stderr)
        return 1
    print(summary_text(report))
    if args.report:
        try:
            doc = write_report(report, args.report)
        except OSError as err:
            print(f"hipaasynth 7aast: error: cannot write report: {err}", file=sys.stderr)
            return 1
        print(f"\nFull report: {args.report}")
        print(f"Report hash: {doc['chain']['report']}")
    return 0 if report.overall != "FAIL" else 2
