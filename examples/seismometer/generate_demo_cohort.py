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

"""Regenerate the Seismometer demo cohort from a seed — no committed data.

HipAAsynth is a *deterministic* synthetic generator: the same
``(module, seed, n)`` always yields the same cohort, anchored by the same hash.
The Seismometer example therefore does **not** ship a multi-megabyte
``patients.json`` / ``results.csv``. It regenerates an equivalent cohort on
demand, so the repo stays lean and every demo run is reproducible and
self-verifying — the audit defence is "here is the seed, regenerate it
yourself," not "trust this committed file."

Public API
----------
    generate(out_dir, module="oud", n=1000, seed=42, label="us_oud_calibration")
        -> (patients_json_path, results_csv_path)

    Both outputs are the engine's *canonical* formats — the same dict-with-
    ``patients`` JSON and flat per-patient CSV that ``seismometer_adapter.run``
    consumes. No PHI: every record is synthetic and carries the engine's
    disclaimer.

CLI
---
    python generate_demo_cohort.py --out ./cohort --module oud --n 1000 --seed 42
"""

from __future__ import annotations

import argparse
import os
import sys

# Supported demo modules. Each entry maps a module name to the engine module path
# and the name of its ``generate_<x>_cohort`` function. All three expose the same
# ``generate_<x>_cohort(seed, n, label) -> (patients, anchor)`` and
# ``save_cohort(patients, anchor, out_dir, prefix)`` interface. Keep this map in
# lockstep with ``seismometer_adapter.PROFILES`` so a generated cohort always has
# a matching adapter profile.
_MODULE_GENERATORS: dict[str, tuple[str, str]] = {
    "oud": ("hipaasynth.modules.oud.oud_generator", "generate_oud_cohort"),
    "chf": ("hipaasynth.modules.chf.chf_generator", "generate_chf_cohort"),
    "copd": ("hipaasynth.modules.copd.copd_generator", "generate_copd_cohort"),
}
SUPPORTED_MODULES = tuple(_MODULE_GENERATORS)

# Sensible default cohort label per module (overridable via --label).
_DEFAULT_LABELS = {
    "oud": "us_oud_calibration",
    "chf": "us_chf_calibration",
    "copd": "us_copd_calibration",
}


def _ensure_engine_importable() -> None:
    """Put the repo root on ``sys.path`` so ``import hipaasynth`` resolves.

    The engine is pure standard library, so no install step is required — being
    importable is enough. This file lives at
    ``<repo>/examples/seismometer/generate_demo_cohort.py``; the repo root is two
    directories up.
    """
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)


def generate(
    out_dir: str,
    module: str = "oud",
    n: int = 1000,
    seed: int = 42,
    label: str | None = None,
) -> tuple[str, str]:
    """Generate a deterministic demo cohort and write canonical JSON + CSV.

    Parameters
    ----------
    out_dir:
        Directory to write the cohort into (created if absent).
    module:
        Clinical module to generate. Must be in :data:`SUPPORTED_MODULES`.
    n:
        Number of synthetic patients.
    seed:
        Anchor seed. The same seed + module + n reproduces the cohort exactly.
    label:
        Cohort label stamped into every record.

    Returns
    -------
    (patients_json_path, results_csv_path)
        Absolute paths to the two files, ready to hand to
        ``seismometer_adapter.run(patients_json=..., results_csv=...)``.

    Raises
    ------
    ValueError
        If ``module`` is not supported.
    """
    if module not in SUPPORTED_MODULES:
        raise ValueError(
            f"Unsupported demo module {module!r}. Supported: {', '.join(SUPPORTED_MODULES)}."
        )
    if label is None:
        label = _DEFAULT_LABELS.get(module, f"us_{module}_calibration")

    _ensure_engine_importable()
    import importlib

    # Lazy, registry-driven import: keeps this file importable for --help /
    # introspection and avoids import-time coupling to any one generator. Every
    # supported module exposes the same generate/save interface.
    mod_path, gen_name = _MODULE_GENERATORS[module]
    gen_mod = importlib.import_module(mod_path)
    generate_cohort = getattr(gen_mod, gen_name)
    save_cohort = getattr(gen_mod, "save_cohort")

    patients, anchor = generate_cohort(seed=seed, n=n, label=label)
    json_path, csv_path, _manifest = save_cohort(patients, anchor, out_dir, prefix=f"{module}_demo")
    return os.path.abspath(json_path), os.path.abspath(csv_path)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Regenerate the Seismometer demo cohort from a seed (no committed data)."
    )
    ap.add_argument("--out", required=True, help="Output directory for patients.json + results.csv")
    ap.add_argument("--module", default="oud", choices=SUPPORTED_MODULES, help="Clinical module")
    ap.add_argument("--n", type=int, default=1000, help="Number of synthetic patients")
    ap.add_argument("--seed", type=int, default=42, help="Anchor seed (reproducibility)")
    ap.add_argument("--label", default=None, help="Cohort label (defaults per module)")
    args = ap.parse_args(argv)

    patients_json, results_csv = generate(
        out_dir=args.out, module=args.module, n=args.n, seed=args.seed, label=args.label
    )
    # Machine-readable last two lines so callers (e.g. the demo shell script) can
    # capture the exact paths without guessing the engine's file-naming scheme.
    print(f"PATIENTS_JSON={patients_json}")
    print(f"RESULTS_CSV={results_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
