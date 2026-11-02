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

"""Watching a run as it happens: every question the model is asked, and its answer.

:class:`Recorder` wraps a model so that each call is recorded, in order: which
run (the scenario, or the US baseline for a comparison), the case the model was
shown, its raw answer word for word, and how 7AAST read it (yes, no, declined,
unreadable). The record is the run's **transcript**; its SHA-256 goes into the
report's provenance, so a transcript can later be shown to be the one behind a
report. :class:`Jobs` runs a 7AAST request in a background thread so the page
can poll it, show progress and answers live, and stop it.

The model, the cases and the results are the same as without a recorder.
"""

from __future__ import annotations

import copy
import hashlib
import json
import threading
import time
import uuid
from typing import Any, Callable

from hipaasynth.aast.adapter import ModelAdapter
from hipaasynth.aast.cases import case_id

#: Characters of a case or answer sent to the page per event (the transcript keeps all).
PREVIEW = 4000
MAX_JOBS = 8


class Cancelled(Exception):
    """The person running the test pressed Stop."""


def _read_as(adapter: ModelAdapter, raw: Any) -> str:
    if raw is None:
        return "declined"
    if adapter.output == "ranked":
        return "ranked list"
    try:
        r = getattr(adapter, f"_from_{adapter.output}")(raw, None)
    except (TypeError, ValueError):
        return "unreadable"
    if r.abstained:
        return "declined"
    if r.decision is None:
        return "unreadable"
    return "yes" if r.decision else "no"


def _text(value: Any) -> str:
    return value if isinstance(value, str) else json.dumps(value, sort_keys=True, default=str)


class Recorder:
    """Records every model call; optional live callbacks, stop button and call estimate."""

    def __init__(self, *, live: bool = False) -> None:
        self.live = live
        self.run = "target"
        self.entries: list[dict[str, Any]] = []
        self.expected = 0
        self.cancel = threading.Event()
        self.started = time.monotonic()
        self._lock = threading.Lock()

    def watch(self, adapter: ModelAdapter) -> ModelAdapter:
        """A copy of ``adapter`` whose every call is recorded."""
        watched = copy.copy(adapter)
        inner = adapter.fn

        def fn(case: Any) -> Any:
            if self.cancel.is_set():
                raise Cancelled("stopped by the user")
            t0 = time.monotonic()
            raw = inner(case)
            entry = {
                "i": len(self.entries) + 1,
                "run": self.run,
                "case_id": case_id(case),
                "case": _text(case),
                "answer": "" if raw is None else _text(raw),
                "read_as": _read_as(adapter, raw),
                "ms": round(1000 * (time.monotonic() - t0)),
            }
            with self._lock:
                entry["i"] = len(self.entries) + 1
                self.entries.append(entry)
            return raw

        watched.fn = fn
        return watched

    def estimate(self, adapter: ModelAdapter, run: Callable[[ModelAdapter], Any]) -> None:
        """Add how many calls ``run`` will make, by running it once with a stand-in model."""
        if not self.live:
            return
        stub = copy.copy(adapter)
        answer: dict[str, Any] = {"binary": False, "score": 0.0, "ordinal": 5, "ranked": [],
                                  "text": "FINAL_ANSWER: No"}  # fmt: skip
        stub.fn = lambda case: answer[adapter.output]
        calls = {"n": 0}
        inner = stub.fn

        def counted(case: Any) -> Any:
            if self.cancel.is_set():
                raise Cancelled("stopped by the user")
            calls["n"] += 1
            return inner(case)

        stub.fn = counted
        run(stub)
        self.expected += calls["n"]

    def transcript(self, run: str) -> str:
        """The run's transcript as JSON lines (one call per line, in order)."""
        with self._lock:
            rows = [e for e in self.entries if e["run"] == run]
        return "".join(json.dumps(e, sort_keys=True, ensure_ascii=False) + "\n" for e in rows)

    def sha256(self, run: str) -> str:
        return hashlib.sha256(self.transcript(run).encode("utf-8")).hexdigest()

    def events(self, since: int) -> list[dict[str, Any]]:
        with self._lock:
            rows = self.entries[since:]
        return [{**e, "case": e["case"][:PREVIEW], "answer": e["answer"][:PREVIEW]} for e in rows]


class Jobs:
    """7AAST runs in background threads, for the page to follow live."""

    def __init__(self) -> None:
        self._jobs: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def start(self, work: Callable[[Recorder], dict[str, Any]]) -> str:
        with self._lock:
            running = [j for j in self._jobs.values() if j["state"] == "running"]
            if len(running) >= 2:
                raise RuntimeError("two runs are already going; wait or stop one")
            while len(self._jobs) >= MAX_JOBS:
                oldest = min(self._jobs, key=lambda k: self._jobs[k]["created"])
                del self._jobs[oldest]
            job_id = uuid.uuid4().hex
            rec = Recorder(live=True)
            job: dict[str, Any] = {"state": "running", "recorder": rec, "result": None,
                                   "error": None, "created": time.monotonic()}  # fmt: skip
            self._jobs[job_id] = job

        def target() -> None:
            try:
                job["result"] = work(rec)
                job["state"] = "done"
            except Cancelled:
                job["state"] = "stopped"
            except Exception as err:  # noqa: BLE001 - reported to the page
                job["error"] = str(err)
                job["state"] = "error"
            job["finished"] = time.monotonic()

        threading.Thread(target=target, daemon=True, name=f"7aast-{job_id[:8]}").start()
        return job_id

    def _get(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            job = self._jobs.get(job_id)
        if job is None:
            raise KeyError("no such run (the tool may have been restarted)")
        return job

    def status(self, job_id: str, since: int = 0) -> dict[str, Any]:
        job = self._get(job_id)
        rec: Recorder = job["recorder"]
        end = job.get("finished") or time.monotonic()
        out = {
            "state": job["state"],
            "run": rec.run,
            "calls": len(rec.entries),
            "expected": rec.expected,
            "elapsed_s": round(end - rec.started, 1),
            "events": rec.events(since),
            "error": job["error"],
        }
        if job["state"] == "done":
            out["result"] = job["result"]
        return out

    def cancel(self, job_id: str) -> None:
        self._get(job_id)["recorder"].cancel.set()

    def transcripts(self, job_id: str) -> dict[str, str]:
        rec: Recorder = self._get(job_id)["recorder"]
        runs = sorted({e["run"] for e in rec.entries})
        return {run: rec.transcript(run) for run in runs}
