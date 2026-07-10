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

# Supported demo modules. The engine's generators come in two shapes:
#
#   * FUNCTION-based (oud/chf/copd): ``generate_<x>_cohort(seed, n, label) ->
#     (patients, anchor)`` plus the module's own ``save_cohort(...)``.
#   * CLASS-based (dmd/fabry/sma): ``<Class>(seed=...).generate(n) -> [patient,
#     ...]`` with no saver — we serialize the records with ``_save_generic``.
#
# Both shapes ultimately yield a list of flat patient dicts, which is all the
# Seismometer adapter needs. Keep these maps in lockstep with
# ``seismometer_adapter.PROFILES`` so every generated cohort has a matching profile.
_FUNCTION_GENERATORS: dict[str, tuple[str, str]] = {
    "oud": ("hipaasynth.modules.oud.oud_generator", "generate_oud_cohort"),
    "chf": ("hipaasynth.modules.chf.chf_generator", "generate_chf_cohort"),
    "copd": ("hipaasynth.modules.copd.copd_generator", "generate_copd_cohort"),
}
_CLASS_GENERATORS: dict[str, tuple[str, str]] = {
    "dmd": ("hipaasynth.modules.dmd.dmd", "DMDCohortGenerator"),
    "fabry": ("hipaasynth.modules.fabry.fabry", "FabryCohortGenerator"),
    "sma": ("hipaasynth.modules.sma.sma", "SMACohortGenerator"),
}


def _build_diabetes(seed: int, n: int) -> list:
    """Compose the diabetes multi-stage pipeline into one flat cohort.

    Diabetes ships no single cohort generator: a base population is enriched by
    four stages that each take the shared ``rng`` and return the mutated records
    (population -> glycemic -> complications -> treatments -> outcomes).
    """
    from hipaasynth.modules.diabetes import (
        DiabetesPopulationGenerator,
        GlycemicGenerator,
        ComplicationGenerator,
        TreatmentGenerator,
        OutcomeGenerator,
    )

    pop_gen = DiabetesPopulationGenerator(n=n, seed=seed)
    patients = pop_gen.generate()
    rng = pop_gen.rng
    for stage in (GlycemicGenerator, ComplicationGenerator, TreatmentGenerator, OutcomeGenerator):
        patients = stage(rng).generate(patients)
    return patients


def _build_longitudinal(condition: str):
    """Builder for modules that live inside the longitudinal population pipeline.

    sepsis and stroke are not standalone cohort generators — they are observation
    hooks attached to a full ``Patient`` when ``required_condition`` is set. We run
    the pipeline for the condition and flatten each nested ``Patient`` into one row
    by merging its ``demographics`` and ``observations`` (the clinical fields); the
    nested visits/conditions are not needed for a cross-sectional fairness audit.
    """

    def build(seed: int, n: int) -> list:
        from hipaasynth.core.config import GenerationConfig
        from hipaasynth.pipelines.population_pipeline import generate_patients

        cfg = GenerationConfig(patient_count=n, seed=seed, required_condition=condition)
        rows = []
        for patient in generate_patients(cfg):
            d = patient.to_dict()
            row = {}
            row.update(d.get("demographics", {}))
            row.update(d.get("observations", {}))
            rows.append(row)
        return rows

    return build


# PIPELINE-based modules: a builder function returns the finished patient list.
_PIPELINE_BUILDERS = {
    "diabetes": _build_diabetes,
    "sepsis": _build_longitudinal("sepsis"),
    "stroke": _build_longitudinal("stroke"),
}
SUPPORTED_MODULES = (
    tuple(_FUNCTION_GENERATORS) + tuple(_CLASS_GENERATORS) + tuple(_PIPELINE_BUILDERS)
)

# Sensible default cohort label per module (overridable via --label).
_DEFAULT_LABELS = {m: f"us_{m}_calibration" for m in SUPPORTED_MODULES}


def _save_generic(patients: list, out_dir: str, prefix: str, module: str, label: str):
    """Serialize a list of flat patient dicts to canonical JSON + CSV.

    Used for class-based generators that ship no ``save_cohort`` of their own.
    Mirrors the ``{prefix}_n{n}.json`` / ``.csv`` naming the function-based savers
    use so the demo runner's path-capture works identically. The JSON carries a
    top-level ``module`` key so the adapter can infer the profile without a flag.
    """
    import csv
    import json

    os.makedirs(out_dir, exist_ok=True)
    n = len(patients)
    json_path = os.path.join(out_dir, f"{prefix}_n{n}.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({"module": module, "label": label, "patients": patients}, f, default=str)

    # CSV over the union of keys (rare-disease records are already flat scalars).
    columns: list = []
    seen = set()
    for p in patients:
        for k in p:
            if k not in seen:
                seen.add(k)
                columns.append(k)
    csv_path = os.path.join(out_dir, f"{prefix}_n{n}.csv")
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        for p in patients:
            writer.writerow({k: p.get(k) for k in columns})
    return json_path, csv_path


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
    # introspection and avoids import-time coupling to any one generator.
    prefix = f"{module}_demo"
    if module in _FUNCTION_GENERATORS:
        mod_path, gen_name = _FUNCTION_GENERATORS[module]
        gen_mod = importlib.import_module(mod_path)
        generate_cohort = getattr(gen_mod, gen_name)
        save_cohort = getattr(gen_mod, "save_cohort")
        patients, anchor = generate_cohort(seed=seed, n=n, label=label)
        json_path, csv_path, _manifest = save_cohort(patients, anchor, out_dir, prefix=prefix)
    elif module in _CLASS_GENERATORS:
        mod_path, cls_name = _CLASS_GENERATORS[module]
        gen_mod = importlib.import_module(mod_path)
        generator = getattr(gen_mod, cls_name)(seed=seed)
        patients = generator.generate(n)
        json_path, csv_path = _save_generic(patients, out_dir, prefix, module, label)
    else:
        patients = _PIPELINE_BUILDERS[module](seed=seed, n=n)
        json_path, csv_path = _save_generic(patients, out_dir, prefix, module, label)
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
