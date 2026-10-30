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

"""7AAST over HTTP: the request handling behind ``POST /7aast`` and the 7AAST page.

Two requests, both JSON objects:

``POST /7aast/export``  ``{condition, input, n?, seed?, prevalence?, profile?}``
    Returns ``{cases_jsonl, answers_csv, cases}``: the cases to run through the
    model and the answers template to fill in.

``POST /7aast``  the same settings plus how the model is supplied, either
    ``{"demo": "demo_guideline" | "demo_biased"}`` or
    ``{"answers": "<filled-in answers file>", "answers_format": "csv" | "jsonl",
    "output": ..., "threshold"?, "lower_is_positive"?, "acute_levels"?, "k"?,
    "name"?}``, and optionally ``deployment_prevalence``.
    Returns ``{"document", "html", "summary"}``: the report document with its
    hash chain, the report page and the terminal summary.

A model is never called over the network and no code is loaded: the server
only runs built-in demo models or replays an answers file. To test a live
model, use ``hipaasynth 7aast run --model module:function`` or the Python API.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from hipaasynth.aast.adapter import INPUT_TYPES, OUTPUT_TYPES
from hipaasynth.aast.cli import summary_text
from hipaasynth.aast.demo import DEMO_MODELS, demo_adapter
from hipaasynth.aast.files import answers_adapter, export_cases
from hipaasynth.aast.reference import REFERENCE_MODELS, reference_adapter, reference_condition
from hipaasynth.aast.remote import RemoteModelError, url_adapter
from hipaasynth.aast.report import build_document, render_html
from hipaasynth.aast.run import MIN_N, PREVALENCE_RANGE, run_7aast
from hipaasynth.decision_cohort import TRUTH_FLAG
from hipaasynth.sdk import SEED_MAX, available_profiles

#: Largest cohort one HTTP request may ask for (a run makes ~13 calls per patient).
MAX_N = 1000

SETTING_KEYS = frozenset(
    {"condition", "input", "n", "seed", "prevalence", "profile", "natural_mix"}
)
RUN_KEYS = SETTING_KEYS | {
    "demo",
    "answers",
    "answers_format",
    "output",
    "threshold",
    "lower_is_positive",
    "acute_levels",
    "k",
    "name",
    "deployment_prevalence",
    "reference",
    "url",
    "headers",
}


class RequestError(ValueError):
    """A request the 7AAST endpoints cannot run; the message is shown to the user."""


def _number(
    params: dict[str, Any], key: str, kind: type, default: Any, lo: float, hi: float
) -> Any:
    raw = params.get(key, default)
    if raw is None or raw == "":
        return default
    if isinstance(raw, bool):
        raise RequestError(f"'{key}' must be a number")
    try:
        value = kind(raw)
    except (TypeError, ValueError):
        raise RequestError(f"'{key}' must be a number, got {raw!r}") from None
    if kind is int and isinstance(raw, float) and raw != value:
        raise RequestError(f"'{key}' must be a whole number, got {raw!r}")
    if not lo <= value <= hi:
        raise RequestError(f"'{key}' must be between {lo} and {hi}, got {value}")
    return value


def _unknown(params: dict[str, Any], allowed: frozenset[str]) -> None:
    unknown = sorted(str(k) for k in params if k not in allowed)
    if unknown:
        raise RequestError(
            f"unknown field(s): {', '.join(unknown)}; supported: {', '.join(sorted(allowed))}"
        )


def _settings(params: dict[str, Any]) -> dict[str, Any]:
    condition = params.get("condition")
    if condition not in TRUTH_FLAG:
        raise RequestError(f"'condition' must be one of {', '.join(sorted(TRUTH_FLAG))}")
    input_type = params.get("input")
    if input_type not in INPUT_TYPES:
        raise RequestError(f"'input' must be one of {', '.join(INPUT_TYPES)}")
    profile = params.get("profile") or None
    if profile is not None and profile not in available_profiles():
        raise RequestError(f"'profile' must be one of {', '.join(available_profiles())}")
    return {
        "condition": condition,
        "input_type": input_type,
        "n": _number(params, "n", int, 200, MIN_N, MAX_N),
        "seed": _number(params, "seed", int, 42, 0, SEED_MAX),
        "prevalence": _number(params, "prevalence", float, 0.5, *PREVALENCE_RANGE),
        "profile": profile,
        "balance_groups": not bool(params.get("natural_mix")),
    }


def export_request(params: dict[str, Any]) -> dict[str, Any]:
    """Handle ``POST /7aast/export``."""
    _unknown(params, SETTING_KEYS)
    s = _settings(params)
    with tempfile.TemporaryDirectory(prefix="hipaasynth-7aast-") as tmp:
        out = export_cases(Path(tmp) / "cases.jsonl", **s)
        return {
            "cases": out["cases"],
            "cases_jsonl": Path(out["cases_file"]).read_text(encoding="utf-8"),
            "answers_csv": Path(out["answers_template"]).read_text(encoding="utf-8"),
        }


def _adapter_settings(params: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if params.get("threshold") not in (None, ""):
        out["threshold"] = _number(params, "threshold", float, None, -1e12, 1e12)
    if params.get("lower_is_positive"):
        out["higher_is_positive"] = False
    levels = params.get("acute_levels")
    if levels not in (None, "", []):
        items = levels if isinstance(levels, list) else str(levels).split(",")
        try:
            out["acute_levels"] = {int(str(x).strip()) for x in items if str(x).strip()}
        except ValueError:
            raise RequestError("'acute_levels' must be whole numbers, e.g. 1,2") from None
    if params.get("k") not in (None, ""):
        out["k"] = _number(params, "k", int, None, 1, 1000)
    if params.get("name"):
        out["name"] = str(params["name"])[:120]
    return out


def run_request(params: dict[str, Any], *, allow_url: bool = False) -> dict[str, Any]:
    """Handle ``POST /7aast``.

    ``url`` (a model server the run calls) is only accepted when ``allow_url``
    is set, which ``hipaasynth ui`` does for its 127.0.0.1-only server: a
    shared server must not be made to send requests to arbitrary addresses.
    """
    _unknown(params, RUN_KEYS)
    s = _settings(params)
    demo, answers = params.get("demo"), params.get("answers")
    reference, url = params.get("reference"), params.get("url")
    if sum(bool(x) for x in (demo, answers, reference, url)) != 1:
        raise RequestError(
            "give exactly one of 'demo' (a built-in model), 'reference' (a published score), "
            "'answers' (a file) or 'url' (a model server)"
        )
    if url and not allow_url:
        raise RequestError(
            "'url' is only accepted by the local tool (hipaasynth ui); this server does not "
            "call out to other addresses"
        )
    deployment = None
    if params.get("deployment_prevalence") not in (None, ""):
        deployment = _number(params, "deployment_prevalence", float, None, 1e-6, 1.0)
    run_kwargs = {
        "n": s["n"],
        "seed": s["seed"],
        "prevalence": s["prevalence"],
        "profile": s["profile"],
        "balance_groups": s["balance_groups"],
        "deployment_prevalence": deployment,
    }
    if demo:
        if demo not in DEMO_MODELS:
            raise RequestError(f"'demo' must be one of {', '.join(DEMO_MODELS)}")
        adapter = demo_adapter(demo, s["condition"], s["input_type"])
        report = run_7aast(adapter, s["condition"], demo=True, **run_kwargs)
    elif reference:
        if reference not in REFERENCE_MODELS:
            raise RequestError(f"'reference' must be one of {', '.join(sorted(REFERENCE_MODELS))}")
        if reference_condition(reference) != s["condition"]:
            raise RequestError(
                f"'{reference}' decides {reference_condition(reference)}, not {s['condition']}"
            )
        report = run_7aast(reference_adapter(reference, s["input_type"]), s["condition"],
                           **run_kwargs)  # fmt: skip
    elif url:
        output = params.get("output", "binary")
        if output not in OUTPUT_TYPES:
            raise RequestError(f"'output' must be one of {', '.join(OUTPUT_TYPES)}")
        headers = params.get("headers") or {}
        if not isinstance(headers, dict) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in headers.items()
        ):
            raise RequestError("'headers' must be an object of header names to text values")
        try:
            adapter = url_adapter(str(url), output, input=s["input_type"],
                                  condition=s["condition"], headers=headers,
                                  **_adapter_settings(params))  # fmt: skip
            report = run_7aast(adapter, s["condition"], **run_kwargs)
        except (ValueError, RemoteModelError) as err:
            raise RequestError(str(err)) from err
    else:
        if not isinstance(answers, str):
            raise RequestError("'answers' must be the text of the answers file")
        output = params.get("output", "binary")
        if output not in OUTPUT_TYPES:
            raise RequestError(f"'output' must be one of {', '.join(OUTPUT_TYPES)}")
        fmt = params.get("answers_format", "csv")
        if fmt not in ("csv", "jsonl"):
            raise RequestError("'answers_format' must be 'csv' or 'jsonl'")
        with tempfile.TemporaryDirectory(prefix="hipaasynth-7aast-") as tmp:
            path = Path(tmp) / f"answers.{fmt}"
            path.write_text(answers, encoding="utf-8")
            settings = _adapter_settings(params)
            settings.setdefault("name", "uploaded answers")
            adapter = answers_adapter(path, output, input=s["input_type"], **settings)
            report = run_7aast(adapter, s["condition"], **run_kwargs)
    doc = build_document(report)
    return {"document": doc, "html": render_html(doc), "summary": summary_text(report)}
