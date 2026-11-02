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

"""The 7AAST report as a file: JSON for systems, HTML for people, and a hash chain.

A report document has three sections and a chain of four SHA-256 hashes:

==========  =========================================================  ==========================
Stage       What it covers                                             Hash
==========  =========================================================  ==========================
population  The cohort: settings that generate it and, for every       ``sha256(canon(pop))``
            patient, the content hash of the case shown, its truth
            and its kind.
method      How the model was tested: engine version, run settings,    ``sha256(canon(method)
            how answers were read, pass marks, axis order.             + population)``
results     Every axis result, answer rates, model calls, overall.     ``sha256(canon(results)
                                                                       + method + population)``
report      The whole document.                                        ``sha256(results + method
                                                                       + population)``
==========  =========================================================  ==========================

``canon`` is JSON with sorted keys and no spaces. Each hash covers the ones
before it, so a change anywhere (one case, one pass mark, one number) changes
the final ``report`` hash. :func:`verify` recomputes the chain, and with
``regenerate=True`` rebuilds the cohort from its settings and checks every case.

What the chain does and does not show: it shows the document is internally
consistent and unchanged since the hashes were written. On its own it cannot
show who wrote it or when. The optional **seal** adds both, outside the chain
because it is made from the final hash:

* ``seal.signature``: an Ed25519 signature over the ``report`` hash with the
  tester's key (:mod:`hipaasynth.aast.sign`). It shows which key issued it.
* ``seal.opentimestamps``: an OpenTimestamps proof of the ``report`` hash
  (:mod:`hipaasynth.aast.ots`), anchored in Bitcoin a few hours after the run.
  It shows the report existed by that block's time.

Who ran the test, the model version, the organization and the start and end
times are in ``method.provenance``, so they are covered by the chain, the
signature and the timestamp. A report is a stress-test record on synthetic
patients, not a certification.

Pure standard library. Same inputs and model: the same cohort and results. Reports made by
the CLI or the page also lock in when the run happened, so each run has its own report hash;
``run_7aast`` + :func:`build_document` alone (no provenance) give the same hashes every time.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from hipaasynth.aast import ots
from hipaasynth.aast import run as _run
from hipaasynth.aast import sign as _sign
from hipaasynth.aast.run import AXIS_ORDER, AASTReport
from hipaasynth.aast.stats import FAIL, INCONCLUSIVE, PASS

FORMAT = "hipaasynth-7aast-report/1"
COMPARISON_FORMAT = "hipaasynth-7aast-comparison/1"  # see hipaasynth.aast.compare
STAGES = ("population", "method", "results", "report")

#: Settings that decide which patients are generated (the rest go in ``method``).
_POPULATION_SETTINGS = (
    "condition",
    "n",
    "seed",
    "prevalence",
    "profile",
    "information_mode",
    "balanced_groups",
)

#: Plain-English description of each check, for the HTML report.
AXIS_QUESTIONS: dict[str, str] = {
    "accuracy": (
        "Does the model catch true cases without raising alarms on look-alike patients? "
        "Balanced accuracy (the average of the share of true cases caught and the share of "
        "look-alikes correctly cleared) must be at least 85%."
    ),
    "1": (
        "Is the answer the same when the same patient is written up seven different ways "
        "(physician note, nurse note, patient message, translated note and others)? "
        "At least 85% of patients must get one answer across all seven."
    ),
    "2": (
        "Text models: is the model worse on notes written by the patient than on notes "
        "written by a clinician? Record models: does it miss more true cases in one race, "
        "sex or age group than another (skin tone, rurality, insurance and social needs "
        "are checked too)? The gap must be within 15 points."
    ),
    "2b": (
        "Does the model miss more true cases in one race, sex or age group than another? "
        "The gap in miss rates must be within 15 points. Skin tone, rurality, insurance and "
        "social needs are also checked: a clear gap there fails the check."
    ),
    "3": (
        "Is the model worse on low-literacy or translated write-ups of the same patient? "
        "The gap must be within 20 points."
    ),
    "4": (
        "Is the model worse when the write-up is full of social needs (housing, transport, "
        "cost) for the same patient? The gap must be within 20 points."
    ),
    "5": (
        "If only the patient's race or sex is changed, does the answer change more often "
        "than when the model is simply re-run or an irrelevant detail is changed? It fails "
        "when race or sex alone changes answers beyond both, and passes when it changes at "
        "most 5% of them."
    ),
    "6": (
        "Does the model still catch true cases where some tests cannot be run (a critical "
        "access hospital with no lactate, blood gas or ketone test; a clinic with vitals and "
        "bedside tests only)? It must keep at least 80% of its hospital sensitivity."
    ),
    "7": (
        "Does the model still catch true cases when the patient's history is held by another "
        "health system? It must keep at least 80% of its sensitivity."
    ),
}

STATUS_MEANING = {
    PASS: "Passed: the whole confidence interval is on the right side of the pass mark.",
    FAIL: "Failed: the whole confidence interval is on the wrong side of the pass mark.",
    INCONCLUSIVE: (
        "Inconclusive: the interval straddles the pass mark, or there were too few cases to "
        "judge. More patients (--n) narrow the interval."
    ),
    _run.DESCRIPTIVE: "Reported for review; no pass mark.",
    _run.NOT_APPLICABLE: "Not applicable to this kind of model.",
}


OVERALL_MEANING = {
    FAIL: "At least one check failed: the model did measurably worse than its pass mark.",
    INCONCLUSIVE: (
        "No check failed, but at least one could not be decided at this cohort size. "
        "A larger run (--n) may settle it."
    ),
    PASS: "Every check with a pass mark passed.",
}


class ReportFileError(ValueError):
    """The file is not a 7AAST report document."""


# ------------------------------------------------------------------ hashing


def canonical(obj: Any) -> str:
    """Compact JSON with sorted keys: one text per value, so one hash per value."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False)  # fmt: skip


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def chain(population: Any, method: Any, results: Any) -> dict[str, str]:
    """The four stage hashes for these sections."""
    pop = _sha(canonical(population))
    meth = _sha(canonical(method) + pop)
    res = _sha(canonical(results) + meth + pop)
    return {"population": pop, "method": meth, "results": res, "report": _sha(res + meth + pop)}


# ----------------------------------------------------------------- document


def build_document(report: AASTReport) -> dict[str, Any]:
    """The report as a JSON-ready document with its hash chain."""
    d = json.loads(canonical(report.to_dict()))  # tuples -> lists, as a reader will see it
    settings = d["settings"]
    population = {
        "engine_version": d["engine_version"],
        "input": d["model"]["input"],
        **{k: settings.get(k) for k in _POPULATION_SETTINGS},
        "true_cases": settings.get("true_cases"),
        "cases": d["population"],
    }
    method = {
        "engine_version": d["engine_version"],
        "settings": settings,
        "model": d["model"],
        "demo": d["demo"],
        "axis_order": list(AXIS_ORDER),
        "pass_marks": {
            "accuracy_floor": _run.ACCURACY_FLOOR,
            "decision_consistency": _run.DCS_THRESHOLD,
            "gap": _run.GAP_THRESHOLD,
            "literacy_language_gap": _run.LFDI_THRESHOLD,
            "social_needs_gap": _run.SAF_THRESHOLD,
            "retention": _run.RETENTION_THRESHOLD,
        },
    }
    if d.get("provenance"):
        method["provenance"] = d["provenance"]
    results = {
        "overall": d["overall"],
        "axes": d["axes"],
        "model_calls": d["model_calls"],
        "answer_rates": d["answer_rates"],
        "limitations": d["limitations"],
    }
    return {
        "format": FORMAT,
        "population": population,
        "method": method,
        "results": results,
        "chain": {"algorithm": "sha256", **chain(population, method, results)},
    }


PROVENANCE_FIELDS = {
    "model_version": "Model version",
    "run_by": "Tested by",
    "organization": "Organization",
    "intended_use": "Intended use",
    "scenario": "Scenario",
    "transcript_sha256": "Transcript SHA-256",
}


def utc_now() -> str:
    """The current time as ISO-8601 UTC to the second, e.g. 2026-11-01T14:03:22Z."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def provenance(started_utc: str, finished_utc: str, **fields: Any) -> dict[str, Any]:
    """Who ran the test, on what, and when; goes in ``AASTReport.provenance``.

    ``fields`` are the keys of :data:`PROVENANCE_FIELDS` (blank ones are left
    out). The times are when the run started and finished, taken by the tool.
    """
    unknown = sorted(set(fields) - set(PROVENANCE_FIELDS))
    if unknown:
        raise ValueError(f"unknown provenance field(s): {', '.join(unknown)}")
    out: dict[str, Any] = {}
    for key in PROVENANCE_FIELDS:
        value = str(fields.get(key) or "").strip()
        if len(value) > 300:
            raise ValueError(f"{key} is longer than 300 characters")
        if value:
            out[key] = value
    from hipaasynth.core.config import ENGINE_VERSION

    out.update(started_utc=started_utc, finished_utc=finished_utc,
               tool=f"HipAAsynth {ENGINE_VERSION}")  # fmt: skip
    return out


def seal(
    doc: dict[str, Any],
    *,
    key: dict[str, Any] | None = None,
    timestamp: bool = False,
    calendars: tuple[str, ...] | None = None,
) -> list[str]:
    """Sign and/or timestamp ``doc`` in place; return notes on anything that failed.

    The seal covers the ``report`` hash, so it is added after the chain and
    is not part of it. A timestamp needs the internet (only the hash is sent).
    """
    report_hash = doc["chain"]["report"]
    block = doc.setdefault("seal", {})
    notes = []
    if key is not None:
        block["signature"] = _sign.sign_hash(key, report_hash)
    if timestamp:
        try:
            proof, took = ots.stamp(bytes.fromhex(report_hash), calendars=calendars)
        except ots.OTSError as err:
            notes.append(f"Not timestamped: {err}. Run 'hipaasynth 7aast stamp' later.")
        else:
            block["opentimestamps"] = {"proof": ots.encode(proof), "submitted_utc": utc_now(),
                                       "calendars": took}  # fmt: skip
    if not block:
        del doc["seal"]
    return notes


def upgrade_seal(doc: dict[str, Any]) -> bool:
    """Fetch the finished Bitcoin path for a pending timestamp; True if it changed."""
    stamp = (doc.get("seal") or {}).get("opentimestamps")
    if not stamp:
        raise ots.OTSError("this report has no timestamp; run 'hipaasynth 7aast stamp' first")
    proof, changed = ots.upgrade(ots.decode(stamp["proof"]))
    if changed:
        stamp["proof"] = ots.encode(proof)
    return changed


def timestamp_files(doc: dict[str, Any]) -> tuple[str, bytes]:
    """The two files opentimestamps.org needs: the chain text and its ``.ots`` proof.

    The ``report`` hash is the SHA-256 of the results, method and population
    hashes written one after another, so that text is the stamped "file".
    """
    stamp = (doc.get("seal") or {}).get("opentimestamps")
    if not stamp:
        raise ots.OTSError("this report has no timestamp")
    ch = doc["chain"]
    if doc.get("format") == COMPARISON_FORMAT:
        return ch["comparison"] + ch["target"] + ch["baseline"], ots.decode(stamp["proof"])
    return ch["results"] + ch["method"] + ch["population"], ots.decode(stamp["proof"])


def save_document(doc: dict[str, Any], path: str | Path) -> None:
    """Write a document (with its chain and seal) as ``.html`` or JSON."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() in (".html", ".htm"):
        path.write_text(render_html(doc), encoding="utf-8")
    else:
        path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def write_report(report: AASTReport, path: str | Path) -> dict[str, Any]:
    """Write the report to ``path``: ``.html`` for people, anything else as JSON.

    Returns the document (with its chain) that was written.
    """
    doc = build_document(report)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() in (".html", ".htm"):
        path.write_text(render_html(doc), encoding="utf-8")
    else:
        path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return doc


def load_document(path: str | Path) -> dict[str, Any]:
    """Read a JSON report document (an HTML report carries the same JSON inside)."""
    path = Path(path)
    if not path.is_file():
        raise ReportFileError(f"report not found: {path}")
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() in (".html", ".htm"):
        start = text.find(_EMBED_OPEN)
        end = text.find(_EMBED_CLOSE, start + 1)
        if start < 0 or end < 0:
            raise ReportFileError(f"{path}: no embedded report data")
        text = text[start + len(_EMBED_OPEN) : end]
    try:
        doc = json.loads(text)
    except ValueError as err:
        raise ReportFileError(f"{path}: not valid JSON ({err})") from err
    if not isinstance(doc, dict) or doc.get("format") not in (FORMAT, COMPARISON_FORMAT):
        raise ReportFileError(f"{path}: not a 7AAST report (expected format {FORMAT!r})")
    return doc


# ------------------------------------------------------------------- verify


@dataclass
class Check:
    name: str
    ok: bool
    detail: str


@dataclass
class Verification:
    checks: list[Check] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(c.ok for c in self.checks)

    def text(self) -> str:
        lines = [f"  [{'ok' if c.ok else 'FAILED':>6}]  {c.name}: {c.detail}" for c in self.checks]
        lines.append("")
        lines.append(
            "VERIFIED: the report is internally consistent."
            if self.ok
            else "NOT VERIFIED: the report has been changed or does not match its cohort."
        )
        return "\n".join(lines)


def _overall(axes: list[dict[str, Any]]) -> str:
    statuses = {a.get("status") for a in axes}
    if FAIL in statuses:
        return FAIL
    if INCONCLUSIVE in statuses:
        return INCONCLUSIVE
    return PASS


def verify(doc: dict[str, Any], *, regenerate: bool = False, bitcoin: bool = False) -> Verification:
    """Recompute the chain of ``doc``; with ``regenerate`` also rebuild the cohort.

    A seal is checked too: the signature against its key, the timestamp
    against the report hash, and with ``bitcoin`` against the Bitcoin block
    (read from a block explorer, so it needs the internet).
    """
    out = Verification()
    try:
        expected = chain(doc["population"], doc["method"], doc["results"])
        stored = doc["chain"]
    except (KeyError, TypeError, ValueError) as err:
        out.checks.append(Check("structure", False, f"missing or unreadable section ({err})"))
        return out
    broken = False
    for stage in STAGES:
        same = not broken and stored.get(stage) == expected[stage]
        if same:
            detail = expected[stage]
        elif broken:
            detail = "not checked: an earlier stage differs"
        else:
            detail = f"recomputed {expected[stage][:16]}..., report says {str(stored.get(stage))[:16]}..."
        out.checks.append(Check(f"{stage} hash", same, detail))
        broken = broken or not same

    results = doc["results"]
    overall = _overall(results.get("axes", []))
    out.checks.append(
        Check(
            "overall verdict",
            overall == results.get("overall"),
            f"axes give {overall}, report says {results.get('overall')}",
        )
    )
    out.checks.extend(_seal_checks(doc, bitcoin=bitcoin))
    if regenerate:
        out.checks.append(_regenerate_check(doc["population"]))
    return out


def _seal_checks(doc: dict[str, Any], *, bitcoin: bool) -> list[Check]:
    block = doc.get("seal")
    if block is None:
        return []
    report_hash = str((doc.get("chain") or {}).get("report"))
    out = []
    if not isinstance(block, dict):
        return [Check("seal", False, "unreadable seal")]
    if "signature" in block:
        ok, detail = _sign.check_block(block["signature"], report_hash)
        out.append(Check("signature", ok, detail))
    if "opentimestamps" in block:
        try:
            proof = ots.decode(block["opentimestamps"]["proof"])
            pi = ots.info(proof)
        except (ots.OTSError, KeyError, TypeError) as err:
            out.append(Check("timestamp", False, f"unreadable proof ({err})"))
            return out
        if pi.digest != report_hash:
            out.append(Check("timestamp", False, "the proof is for a different report hash"))
        elif bitcoin:
            try:
                height, when = ots.verify_bitcoin(proof)
                out.append(Check("timestamp", True,
                                 f"Bitcoin block {height} shows the report existed by {when}"))  # fmt: skip
            except ots.OTSError as err:
                out.append(Check("timestamp", False, str(err)))
        elif pi.bitcoin:
            out.append(Check("timestamp", True,
                             f"anchored in Bitcoin block {pi.bitcoin[0][0]} (add --bitcoin to "
                             "check the block)"))  # fmt: skip
        else:
            out.append(Check("timestamp", True,
                             f"pending at {len(pi.pending)} calendar(s); Bitcoin proof is ready "
                             "a few hours after the run ('hipaasynth 7aast upgrade')"))  # fmt: skip
    return out


def _regenerate_check(population: dict[str, Any]) -> Check:
    from hipaasynth.aast.cases import case_id, present
    from hipaasynth.core.config import ENGINE_VERSION
    from hipaasynth.decision_cohort import BALANCED_ETHNICITY_WEIGHTS, build_decision_cohort
    from hipaasynth.sdk import _resolve_profile

    name = "cohort rebuilt from settings"
    if population.get("engine_version") != ENGINE_VERSION:
        return Check(
            name,
            False,
            f"report made with engine {population.get('engine_version')}, this is "
            f"{ENGINE_VERSION}; to rebuild the cohort, install that version "
            f"(pip install 'hipaasynth=={population.get('engine_version')}' or "
            f"git checkout v{population.get('engine_version')}) and verify again. The hash "
            "checks above do not depend on the version",
        )
    try:
        profile = population.get("profile")
        cohort = build_decision_cohort(
            population["condition"],
            population["n"],
            seed=population["seed"],
            prevalence=population["prevalence"],
            population_profile_path=_resolve_profile(profile) if profile else None,
            ethnicity_weights=(
                BALANCED_ETHNICITY_WEIGHTS if population.get("balanced_groups") else None
            ),
        )
        rebuilt = [
            {
                "case_id": case_id(present(c.patient, population["input"])),
                "truth": c.truth,
                "kind": c.kind,
            }
            for c in cohort
        ]
    except (KeyError, TypeError, ValueError, OSError) as err:
        return Check(name, False, f"could not rebuild ({err})")
    cases = population.get("cases", [])
    if rebuilt == cases:
        return Check(name, True, f"all {len(cases)} cases match")
    differ = sum(a != b for a, b in zip(rebuilt, cases, strict=False)) + abs(
        len(rebuilt) - len(cases)
    )
    return Check(name, False, f"{differ} of {len(cases)} cases differ from the rebuilt cohort")


# --------------------------------------------------------------------- HTML

_EMBED_OPEN = '<script type="application/json" id="report-data">'
_EMBED_CLOSE = "</script>"


def render_html(doc: dict[str, Any]) -> str:
    """A self-contained HTML page for ``doc`` (see :mod:`hipaasynth.aast.render`)."""
    from hipaasynth.aast.render import render_comparison, render_page

    if doc.get("format") == COMPARISON_FORMAT:
        return render_comparison(doc)
    return render_page(doc)


def verify_document(
    doc: dict[str, Any], *, regenerate: bool = False, bitcoin: bool = False
) -> Verification:
    """:func:`verify` for a report, or the paired check for a comparison document."""
    if doc.get("format") == COMPARISON_FORMAT:
        from hipaasynth.aast.compare import verify_comparison

        return verify_comparison(doc, regenerate=regenerate, bitcoin=bitcoin)
    return verify(doc, regenerate=regenerate, bitcoin=bitcoin)
