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

Who ran it is locked into the report with ``model_version``, ``run_by``,
``organization``, ``intended_use`` and ``scenario`` (a prebuilt scenario sets the
condition and profile); the tool records the start and end times. On the local
tool, ``sign`` signs the report with this computer's key and ``stamp`` sends the
report hash to OpenTimestamps. ``compare_baseline`` also runs the model on the US
baseline population and returns a comparison document (see
:mod:`hipaasynth.aast.compare`) plus each run under ``reports``.

``POST /7aast/verify``  ``{document, regenerate?, bitcoin?}``  checks a saved report.
``POST /7aast/upgrade`` ``{document}`` fetches its Bitcoin proof (local tool only).

It can also be ``{"reference": <published score>}``, and, on the local tool
only (``hipaasynth ui``, 127.0.0.1), ``{"url": <model server>, "headers"?}`` or
``{"llm_provider": "openai" | "anthropic", "llm_model": ..., "llm_api_key"?,
"llm_base_url"?}``. An API key or header is used for the calls and never
written into the report. ``tests`` (a list of :data:`~hipaasynth.aast.run.TESTS`
keys) runs only those checks; accuracy always runs. No code is ever loaded.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

from hipaasynth.aast.adapter import INPUT_TYPES, OUTPUT_TYPES
from hipaasynth.aast.cli import summary_text
from hipaasynth.aast.demo import DEMO_MODELS, demo_adapter
from hipaasynth.aast.files import answers_adapter, export_cases
from hipaasynth.aast.reference import REFERENCE_MODELS, reference_adapter, reference_condition
from hipaasynth.aast.remote import (
    DEFAULT_MAX_TOKENS,
    LLM_PROVIDERS,
    MAX_TOKENS_RANGE,
    RemoteModelError,
    llm_adapter,
    url_adapter,
)
from hipaasynth.aast import ots, sign
from hipaasynth.aast.compare import BASELINE_PROFILE, build_comparison
from hipaasynth.aast.compare import plain_english as compare_english
from hipaasynth.aast.report import (
    COMPARISON_FORMAT,
    FORMAT,
    build_document,
    provenance,
    render_html,
    seal,
    upgrade_seal,
    utc_now,
    verify_document,
)
from hipaasynth.aast.run import MIN_N, PREVALENCE_RANGE, TESTS, run_7aast
from hipaasynth.decision_cohort import TRUTH_FLAG
from hipaasynth.scenarios import ScenarioError, resolve_scenario
from hipaasynth.sdk import SEED_MAX, available_profiles, canonical_profile

#: Largest cohort one HTTP request may ask for (a run makes ~13 calls per patient).
MAX_N = 1000

SETTING_KEYS = frozenset(
    {"condition", "input", "n", "seed", "prevalence", "profile", "natural_mix", "scenario"}
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
    "tests",
    "llm_provider",
    "llm_model",
    "llm_api_key",
    "llm_base_url",
    "llm_max_tokens",
    "model_version",
    "run_by",
    "organization",
    "intended_use",
    "scenario",
    "sign",
    "stamp",
    "compare_baseline",
}
PROVENANCE_KEYS = ("model_version", "run_by", "organization", "intended_use", "scenario")


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
    if params.get("scenario"):
        try:
            sc = resolve_scenario(str(params["scenario"]))
        except ScenarioError as err:
            raise RequestError(str(err)) from None
        if params.get("condition") not in (None, "", sc["module"]):
            raise RequestError(f"scenario {params['scenario']} is for {sc['module']}, "
                               f"not {params['condition']}")  # fmt: skip
        if params.get("profile") not in (None, "", sc["profile"]):
            raise RequestError(f"scenario {params['scenario']} uses profile {sc['profile']}")
        params = {**params, "condition": sc["module"], "profile": sc["profile"]}
    condition = params.get("condition")
    if condition not in TRUTH_FLAG:
        raise RequestError(f"'condition' must be one of {', '.join(sorted(TRUTH_FLAG))}")
    input_type = params.get("input")
    if input_type not in INPUT_TYPES:
        raise RequestError(f"'input' must be one of {', '.join(INPUT_TYPES)}")
    profile = canonical_profile(str(params.get("profile"))) if params.get("profile") else None
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
    if (params.get("sign") or params.get("stamp")) and not allow_url:
        raise RequestError("signing and timestamping are done by the local tool (hipaasynth ui)")
    try:
        key = _signing_key(params) if params.get("sign") else None
        prov = {k: params.get(k) for k in PROVENANCE_KEYS}
        provenance("", "", **prov)  # check the fields before the run, not after
    except (ValueError, OSError) as err:
        raise RequestError(str(err)) from err
    compare_baseline = bool(params.get("compare_baseline"))
    if compare_baseline:
        if params.get("answers"):
            raise RequestError(
                "comparing with the US baseline needs a model the tool can call (demo, published "
                "score, model address or LLM); an answers file covers only its own cases"
            )
        if (s["profile"] or BASELINE_PROFILE) == BASELINE_PROFILE:
            raise RequestError("choose a scenario or a population other than the US baseline "
                               "to compare against it")  # fmt: skip
    started = utc_now()
    demo, answers = params.get("demo"), params.get("answers")
    reference, url = params.get("reference"), params.get("url")
    llm = params.get("llm_provider")
    if sum(bool(x) for x in (demo, answers, reference, url, llm)) != 1:
        raise RequestError(
            "give exactly one of 'demo' (a built-in model), 'reference' (a published score), "
            "'answers' (a file), 'url' (a model server) or 'llm_provider' (an LLM API)"
        )
    if (url or llm) and not allow_url:
        raise RequestError(
            f"'{'url' if url else 'llm_provider'}' is only accepted by the local tool "
            "(hipaasynth ui); this server does not call out to other addresses"
        )
    tests = params.get("tests")
    if tests is not None:
        if not isinstance(tests, list) or not all(isinstance(t, str) for t in tests):
            raise RequestError("'tests' must be a list of test names")
        unknown = sorted(set(tests) - set(TESTS))
        if unknown:
            raise RequestError(f"unknown test(s) {unknown}; choose from {', '.join(TESTS)}")
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
        "tests": tests,
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
        adapter = reference_adapter(reference, s["input_type"])
        report = run_7aast(adapter, s["condition"], **run_kwargs)
    elif llm:
        if llm not in LLM_PROVIDERS:
            raise RequestError(f"'llm_provider' must be one of {', '.join(LLM_PROVIDERS)}")
        model_name = str(params.get("llm_model") or "").strip()
        if not model_name:
            raise RequestError("give 'llm_model', the model name your provider uses")
        api_key = str(params.get("llm_api_key") or "").strip() or None
        base_url = str(params.get("llm_base_url") or "").strip() or None
        max_tokens = _number(params, "llm_max_tokens", int, DEFAULT_MAX_TOKENS,
                             *MAX_TOKENS_RANGE)  # fmt: skip
        try:
            adapter = llm_adapter(llm, model_name, input=s["input_type"],
                                  condition=s["condition"], base_url=base_url,
                                  api_key=api_key, max_tokens=max_tokens)  # fmt: skip
            report = run_7aast(adapter, s["condition"], **run_kwargs)
        except (ValueError, RemoteModelError) as err:
            raise RequestError(str(err)) from err
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
    report.provenance = provenance(started, utc_now(), **prov)
    doc = build_document(report)
    summary = summary_text(report)
    if compare_baseline:
        started = utc_now()
        try:
            base = run_7aast(adapter, s["condition"], demo=bool(demo),
                             **{**run_kwargs, "profile": BASELINE_PROFILE})  # fmt: skip
        except (ValueError, RemoteModelError) as err:
            raise RequestError(str(err)) from err
        base.provenance = provenance(started, utc_now(),
                                     **{**prov, "scenario": None})  # fmt: skip
        doc = build_comparison(doc, build_document(base))
        summary += ("\n\nUS BASELINE:\n" + summary_text(base) + "\n\nCOMPARISON: "
                    + compare_english(doc["comparison"], s["condition"]))  # fmt: skip
    notes = seal(doc, key=key, timestamp=bool(params.get("stamp")))
    out = {"document": doc, "document_json": document_json(doc), "html": render_html(doc),
           "summary": summary, "seal_notes": notes}  # fmt: skip
    if compare_baseline:
        # Each run on its own, to save separately (exact text, so it still verifies).
        out["reports"] = {side: {"document_json": document_json(doc[side]),
                                 "html": render_html(doc[side])}
                          for side in ("target", "baseline")}  # fmt: skip
    return out


def document_json(doc: dict[str, Any]) -> str:
    """The document as text to save or send back unchanged.

    A browser re-serializing the parsed document would write 20.0 as 20 and so
    change the hashes; the page keeps this text instead.
    """
    return json.dumps(doc, indent=2, ensure_ascii=False) + "\n"


def _signing_key(params: dict[str, Any]) -> dict[str, Any]:
    """This computer's signing key; made on first use with the tester's name."""
    path = sign.default_key_path()
    if not path.exists():
        sign.new_key(path, signer=str(params.get("run_by") or ""),
                     organization=str(params.get("organization") or ""))  # fmt: skip
    return sign.load_key(path)


def _document(params: dict[str, Any], allowed: set[str]) -> dict[str, Any]:
    _unknown(params, frozenset(allowed))
    doc = params.get("document")
    if not isinstance(doc, dict) or doc.get("format") not in (FORMAT, COMPARISON_FORMAT):
        raise RequestError("'document' must be a 7AAST report document (the saved .json)")
    return doc


def verify_request(params: dict[str, Any], *, allow_network: bool = False) -> dict[str, Any]:
    """Handle ``POST /7aast/verify``: check a saved report."""
    doc = _document(params, {"document", "regenerate", "bitcoin"})
    if params.get("bitcoin") and not allow_network:
        raise RequestError("checking the Bitcoin block is done by the local tool (hipaasynth ui)")
    result = verify_document(doc, regenerate=bool(params.get("regenerate")),
                             bitcoin=bool(params.get("bitcoin")))  # fmt: skip
    return {"ok": result.ok, "text": result.text(),
            "checks": [{"name": c.name, "ok": c.ok, "detail": c.detail} for c in result.checks]}  # fmt: skip


def upgrade_request(params: dict[str, Any], *, allow_network: bool = False) -> dict[str, Any]:
    """Handle ``POST /7aast/upgrade``: fetch the Bitcoin proof for a pending timestamp."""
    doc = _document(params, {"document"})
    if not allow_network:
        raise RequestError("upgrading a timestamp is done by the local tool (hipaasynth ui)")
    try:
        changed = upgrade_seal(doc)
    except ots.OTSError as err:
        raise RequestError(str(err)) from err
    return {"document": doc, "document_json": document_json(doc), "html": render_html(doc),
            "changed": changed}  # fmt: skip
