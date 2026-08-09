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

"""HipAAsynth REST API — on-demand synthetic cohort generation.

**Framework decision (stdlib-only, flagged like Tier 1's pyarrow choice).** This
is the project's first network-facing surface. It is built on the Python standard
library's :mod:`http.server` (`ThreadingHTTPServer` + `BaseHTTPRequestHandler`) —
**zero new dependencies** — to preserve the engine's "stdlib-only core" value. A
microframework (Flask/FastAPI) would give nicer routing/validation but adds a hard
runtime dependency for a small, well-scoped set of endpoints; the routing and
validation needed here are modest enough to do directly. If the API surface grows
substantially, revisit and add a microframework as an **optional extra** (the same
pattern Tier 1 used for `pyarrow`), not a core dependency.

Endpoints
---------
``GET  /``            → the static web UI (a dependency-free HTML/JS client)
``GET  /health``      → ``{"status": "ok", "engine_version": ...}``
``GET  /formats``     → supported formats, modules, profile + scenario names
``GET  /scenarios``   → named scenario blueprints (module+profile shortcuts)
``GET  /generate``    → generate a cohort using query-string params
``POST /generate``    → generate a cohort using a JSON (or form-encoded) body
``GET  /viz/demographics`` → SVG of a cohort's age/sex/ethnicity distribution
``GET  /viz/fairness``     → SVG fairness heatmap from a demo DIF audit (mock model)

The web UI is a single static ``ui/index.html`` (kept as a real file — not a
Python string — so it stays editable, lintable and Playwright-testable) served
from this same server, so it shares the API's origin and needs no CORS handling.

`/generate` params (all optional; validated):
  * ``count``    — patients to generate (int, 1..``max_count``; default 100)
  * ``seed``     — RNG seed (int, 0..2**32-1; default 42)
  * ``module``   — decision module: ``sepsis`` (default) | ``stroke`` | ``dka`` | ``fabry``
  * ``profile``  — a **bundled** population-profile name (see ``/formats``); a
    network client may not supply an arbitrary filesystem path
  * ``scenario`` — a named blueprint (see ``/scenarios``) supplying a default
    ``module``+``profile``; an explicit ``module``/``profile`` still overrides it
  * ``format``  — ``json`` (default) | ``csv`` | ``fhir-bundle`` | ``ndjson`` |
    ``omop`` | ``parquet``. ``ndjson`` is streamed (chunked); ``parquet`` needs the
    optional ``pyarrow`` extra.

All records are synthetic (no PHI). Output paths/handling are the caller's; the
server holds nothing on disk beyond a short-lived temp file for the Parquet path.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import tempfile
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from hipaasynth.core.config import (
    DEFAULT_SYNTHETIC_DISCLAIMER,
    ENGINE_VERSION,
    GenerationConfig,
)
from hipaasynth.core.profile_loader import load_population_profile
from hipaasynth.exporters.exporters import (
    _flat_patient_rows,
    _patient_to_fhir,
    export_parquet,
)
from hipaasynth.exporters.omop import build_cdm_tables
from hipaasynth.pipelines.population_pipeline import generate_patients
from hipaasynth.scenarios import (
    ScenarioError,
    available_scenarios,
    resolve_scenario,
    scenario_summaries,
)
from hipaasynth.sdk import MODULES as MODULE_TO_CONDITION  # canonical module map
from hipaasynth.viz import demographics_distribution_svg, fairness_heatmap_svg
# Response formats the API can serialize to a single HTTP response.
API_FORMATS = ("json", "csv", "fhir-bundle", "ndjson", "omop", "parquet")
# Built-in mock models the /viz/fairness demo audit can run (no model-under-test
# is available to a stateless HTTP call, so the heatmap is a *demonstration* audit
# against a documented mock — see _VIZ_MODELS below).
_VIZ_MODELS = ("biased", "fair", "sdoh")
# Bound the demo DIF audit: it renders 7 forms per patient, so keep it cheap.
VIZ_FAIRNESS_MAX_COUNT = 300
# Stamped into every /viz/fairness SVG. The endpoint has no model-under-test, so
# the heatmap can only ever be a demonstration; this travels with the image once
# it is saved or pasted somewhere that no longer shows the surrounding page.
VIZ_FAIRNESS_MOCK_NOTE = (
    "Demonstration audit of a built-in mock model — not an audit of any real model."
)
# Network safety: cap on-demand cohort size unless the operator raises it.
DEFAULT_MAX_COUNT = 10_000
# Hard cap on a POST body. A legitimate /generate body is a tiny JSON object
# ({count, seed, module, profile, format}) — well under a kilobyte — so 1 MB is
# already absurdly generous. The point is to never trust a client's Content-Length
# and allocate/read toward it: a forged huge value (e.g. 999999999999) would
# otherwise MemoryError the handling thread.
MAX_BODY_BYTES = 1_000_000
_PROFILES_DIR = Path(__file__).resolve().parent / "profiles"
_UI_DIR = Path(__file__).resolve().parent / "ui"


class ApiError(Exception):
    """A client-facing error carrying an HTTP status and a safe message."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def available_profiles() -> list[str]:
    """Bundled population-profile names a client may request (no arbitrary paths)."""
    return sorted(p.stem for p in _PROFILES_DIR.glob("*.json"))


def _parse_int(name, value, *, minimum=None, maximum=None) -> int:
    try:
        n = int(str(value).strip())
    except (TypeError, ValueError):
        raise ApiError(400, f"'{name}' must be an integer, got {value!r}")
    if minimum is not None and n < minimum:
        raise ApiError(400, f"'{name}' must be >= {minimum}, got {n}")
    if maximum is not None and n > maximum:
        raise ApiError(400, f"'{name}' must be <= {maximum}, got {n}")
    return n


def parse_generate_request(params: dict, *, max_count: int = DEFAULT_MAX_COUNT) -> dict:
    """Validate raw request params → a normalized request dict, or raise ApiError.

    This is the input-validation boundary for the network surface: it rejects
    non-integer / out-of-range ``count``/``seed``, unknown ``format``/``module``,
    and unknown ``profile`` names (and never dereferences an arbitrary path).
    """
    count = _parse_int("count", params.get("count", 100), minimum=1, maximum=max_count)
    seed = _parse_int("seed", params.get("seed", 42), minimum=0, maximum=2**32 - 1)

    fmt = str(params.get("format", "json"))
    if fmt not in API_FORMATS:
        raise ApiError(400, f"unknown format {fmt!r}; supported: {', '.join(API_FORMATS)}")

    # A scenario blueprint is a shortcut: it supplies default module + profile,
    # which an explicit ``module``/``profile`` param may still override (purely
    # additive — it never changes what module/profile do on their own).
    scenario_name = params.get("scenario")
    scenario_module = scenario_profile = None
    if scenario_name not in (None, ""):
        scenario_name = str(scenario_name)
        try:
            resolved = resolve_scenario(scenario_name)
        except ScenarioError as err:
            raise ApiError(400, str(err)) from err
        scenario_module = resolved["module"]
        scenario_profile = resolved["profile"]
    else:
        scenario_name = None

    module = str(params.get("module") or scenario_module or "sepsis")
    if module not in MODULE_TO_CONDITION:
        raise ApiError(
            400, f"unknown module {module!r}; supported: {', '.join(MODULE_TO_CONDITION)}"
        )

    profile_name = params.get("profile")
    if profile_name in (None, "") and scenario_profile is not None:
        profile_name = scenario_profile
    profile_path = None
    if profile_name not in (None, ""):
        profile_name = str(profile_name)
        if profile_name not in available_profiles():
            raise ApiError(
                400,
                f"unknown profile {profile_name!r}; available: "
                f"{', '.join(available_profiles())}",
            )
        profile_path = str(_PROFILES_DIR / f"{profile_name}.json")
    else:
        profile_name = None

    return {
        "count": count,
        "seed": seed,
        "format": fmt,
        "module": module,
        "profile": profile_name,
        "profile_path": profile_path,
        "scenario": scenario_name,
    }


def build_config(req: dict) -> GenerationConfig:
    """Build a GenerationConfig from a validated request dict."""
    profile_data = load_population_profile(req["profile_path"]) if req["profile_path"] else None
    return GenerationConfig(
        patient_count=req["count"],
        seed=req["seed"],
        age_min=18,
        age_max=90,
        required_condition=MODULE_TO_CONDITION[req["module"]],
        sex_ratio_female=profile_data["sex_ratio_female"] if profile_data else 0.5,
        ethnicity_weights=profile_data["ethnicity_weights"] if profile_data else None,
        include_visits=True,
        include_labs=True,
        visits_min=1,
        visits_max=3,
        synthetic_disclaimer=DEFAULT_SYNTHETIC_DISCLAIMER,
        run_date=date.today().isoformat(),
        age_band_weights=profile_data.get("age_band_weights") if profile_data else None,
        population_profile_path=req["profile_path"],
        profile_name=profile_data["profile_name"] if profile_data else None,
    )


def _fhir_bundle(patients) -> dict:
    bundle = {"resourceType": "Bundle", "type": "collection", "entry": []}
    for patient in patients:
        for resource in _patient_to_fhir(patient):
            bundle["entry"].append(
                {"fullUrl": f"urn:uuid:{resource['id']}", "resource": resource}
            )
    return bundle


def iter_ndjson_lines(patients):
    """Yield one JSON line per FHIR resource — the streaming-friendly bulk format."""
    for patient in patients:
        for resource in _patient_to_fhir(patient):
            yield json.dumps(resource, ensure_ascii=False)


def serialize(patients, fmt: str) -> tuple[str, bytes]:
    """Serialize a cohort to ``(content_type, body_bytes)`` for a buffered response.

    NDJSON is intentionally *not* handled here — it is streamed by the handler.
    """
    if fmt == "json":
        body = json.dumps([p.to_dict() for p in patients], ensure_ascii=False).encode("utf-8")
        return "application/json", body
    if fmt == "csv":
        fieldnames, rows = _flat_patient_rows(patients)
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
        return "text/csv; charset=utf-8", buf.getvalue().encode("utf-8")
    if fmt == "fhir-bundle":
        body = json.dumps(_fhir_bundle(patients), ensure_ascii=False).encode("utf-8")
        return "application/fhir+json", body
    if fmt == "omop":
        body = json.dumps(build_cdm_tables(patients), ensure_ascii=False).encode("utf-8")
        return "application/json", body
    if fmt == "parquet":
        # Delegate to export_parquet, which lazily imports pyarrow (the optional
        # [parquet] extra). We deliberately do NOT import pyarrow here, so api.py
        # stays stdlib-only; a missing extra surfaces as export_parquet's
        # RuntimeError, which we map to a 400.
        tmp = tempfile.NamedTemporaryFile(suffix=".parquet", delete=False)
        tmp.close()
        try:
            export_parquet(patients, tmp.name)
            data = Path(tmp.name).read_bytes()
        except RuntimeError as err:
            raise ApiError(
                400,
                "format 'parquet' requires the optional 'pyarrow' extra "
                "(pip install 'hipaasynth[parquet]')",
            ) from err
        finally:
            if os.path.exists(tmp.name):
                os.unlink(tmp.name)
        return "application/vnd.apache.parquet", data
    raise ApiError(400, f"unsupported format {fmt!r}")


class HipAASynthHandler(BaseHTTPRequestHandler):
    """stdlib request handler for the HipAAsynth API."""

    protocol_version = "HTTP/1.1"
    server_version = f"HipAAsynth/{ENGINE_VERSION}"
    max_count = DEFAULT_MAX_COUNT
    # Known routes and the methods they accept (for correct 404 vs 405).
    _ROUTES = {
        "/": {"GET"},
        "/health": {"GET"},
        "/formats": {"GET"},
        "/scenarios": {"GET"},
        "/generate": {"GET", "POST"},
        "/viz/demographics": {"GET"},
        "/viz/fairness": {"GET"},
    }

    def log_message(self, *args):  # keep the test/console output quiet by default
        pass

    # ── response helpers ─────────────────────────────────────────────────────
    def _send_bytes(self, status: int, ctype: str, body: bytes):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _send_json(self, status: int, obj):
        self._send_bytes(status, "application/json",
                         json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    def _send_svg(self, svg: str):
        self._send_bytes(200, "image/svg+xml; charset=utf-8", svg.encode("utf-8"))

    def _send_api_error(self, err: ApiError):
        self._send_json(err.status, {"error": err.message, "status": err.status})

    def _send_ui(self):
        """Serve the bundled static web UI (``ui/index.html``)."""
        index = _UI_DIR / "index.html"
        try:
            body = index.read_bytes()
        except OSError:  # pragma: no cover - the file ships with the package
            return self._send_json(
                500, {"error": "web UI asset missing", "status": 500})
        self._send_bytes(200, "text/html; charset=utf-8", body)

    def _read_body(self, declared_length: int) -> bytes:
        """Read the request body in bounded chunks, never exceeding
        ``MAX_BODY_BYTES``.

        We do not hand the (client-controlled) ``declared_length`` straight to a
        single ``rfile.read(n)``: we read in fixed-size chunks and stop at
        ``min(declared_length, MAX_BODY_BYTES)``, so a lie in either direction — a
        forged huge Content-Length, or a small one followed by a longer stream —
        can never make us allocate or read past the cap. Callers must already have
        rejected ``declared_length > MAX_BODY_BYTES`` with a 413.
        """
        remaining = min(max(declared_length, 0), MAX_BODY_BYTES)
        chunk_size = 65_536
        chunks = []
        while remaining > 0:
            chunk = self.rfile.read(min(chunk_size, remaining))
            if not chunk:  # client closed / short body
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)

    def _route(self):
        parsed = urlparse(self.path)
        return (parsed.path.rstrip("/") or "/"), parsed

    def _method_guard(self, route: str, method: str) -> bool:
        """Return True if handled as 404/405; False if the route+method is valid."""
        if route not in self._ROUTES:
            self._send_json(404, {"error": f"not found: {route}", "status": 404})
            return True
        if method not in self._ROUTES[route]:
            self.send_response(405)
            self.send_header("Allow", ", ".join(sorted(self._ROUTES[route])))
            self.send_header("Content-Length", "0")
            self.end_headers()
            return True
        return False

    # ── verbs ────────────────────────────────────────────────────────────────
    def do_GET(self):
        route, parsed = self._route()
        if self._method_guard(route, "GET"):
            return
        if route == "/":
            return self._send_ui()
        if route == "/health":
            return self._send_json(200, {"status": "ok", "engine_version": ENGINE_VERSION})
        if route == "/formats":
            return self._send_json(200, {
                "formats": list(API_FORMATS),
                "modules": list(MODULE_TO_CONDITION),
                "profiles": available_profiles(),
                "scenarios": available_scenarios(),
                "max_count": self.max_count,
            })
        if route == "/scenarios":
            return self._send_json(200, {"scenarios": scenario_summaries()})
        params = {k: v[0] for k, v in parse_qs(parsed.query).items()}
        if route == "/viz/demographics":
            return self._handle_viz_demographics(params)
        if route == "/viz/fairness":
            return self._handle_viz_fairness(params)
        if route == "/generate":
            return self._handle_generate(params)

    def do_POST(self):
        route, parsed = self._route()
        if self._method_guard(route, "POST"):
            return
        # /generate is the only POST route.
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return self._send_api_error(ApiError(400, "invalid Content-Length"))
        if length < 0:
            return self._send_api_error(ApiError(400, "invalid Content-Length"))
        # Reject an oversized (or forged) Content-Length BEFORE reading/allocating
        # toward it — a huge value must not be trusted into self.rfile.read().
        if length > MAX_BODY_BYTES:
            return self._send_api_error(ApiError(
                413,
                f"request body too large: {length} bytes exceeds the "
                f"{MAX_BODY_BYTES}-byte limit",
            ))
        raw = self._read_body(length)
        body_params: dict = {}
        if raw:
            ctype = self.headers.get("Content-Type", "")
            if "application/json" in ctype:
                try:
                    parsed_body = json.loads(raw.decode("utf-8"))
                except (json.JSONDecodeError, UnicodeDecodeError):
                    return self._send_api_error(ApiError(400, "invalid JSON body"))
                if not isinstance(parsed_body, dict):
                    return self._send_api_error(ApiError(400, "JSON body must be an object"))
                body_params = {k: v for k, v in parsed_body.items()}
            else:  # form-encoded fallback
                body_params = {k: v[0] for k, v in parse_qs(raw.decode("utf-8")).items()}
        query_params = {k: v[0] for k, v in parse_qs(parsed.query).items()}
        params = {**query_params, **body_params}  # body overrides query
        return self._handle_generate(params)

    def do_HEAD(self):
        # Allow HEAD on GET routes; reuse do_GET's dispatch with no body written.
        self.do_GET()

    # ── core ─────────────────────────────────────────────────────────────────
    def _handle_generate(self, params: dict):
        try:
            req = parse_generate_request(params, max_count=self.max_count)
            cfg = build_config(req)
            patients = generate_patients(cfg)
        except ApiError as err:
            return self._send_api_error(err)
        except ValueError as err:  # GenerationConfig validation, etc.
            return self._send_api_error(ApiError(400, str(err)))
        except Exception as err:  # pragma: no cover - defensive 500
            return self._send_json(500, {"error": f"generation failed: {err}", "status": 500})

        if req["format"] == "ndjson":
            return self._stream_ndjson(patients)
        try:
            ctype, body = serialize(patients, req["format"])
        except ApiError as err:
            return self._send_api_error(err)
        self._send_bytes(200, ctype, body)

    def _handle_viz_demographics(self, params: dict):
        """Return an SVG of the requested cohort's age/sex/ethnicity distribution."""
        try:
            req = parse_generate_request(params, max_count=self.max_count)
            cfg = build_config(req)
            patients = generate_patients(cfg)
            svg = demographics_distribution_svg(patients)
        except ApiError as err:
            return self._send_api_error(err)
        except ValueError as err:
            return self._send_api_error(ApiError(400, str(err)))
        except Exception as err:  # pragma: no cover - defensive 500
            return self._send_json(500, {"error": f"viz failed: {err}", "status": 500})
        self._send_svg(svg)

    def _handle_viz_fairness(self, params: dict):
        """Return an SVG fairness heatmap from a *demonstration* DIF audit.

        A stateless HTTP call has no real device-under-test, so this runs the
        polymorphic audit against a documented built-in **mock** model
        (``model=biased`` by default) over the requested cohort. It illustrates
        the per-form error heatmap + cohort metrics; it is not an audit of any
        real model. The cohort is capped (``VIZ_FAIRNESS_MAX_COUNT``) since the
        audit renders all seven forms per patient.
        """
        from hipaasynth.dif import DIFConfig, run_audit
        from hipaasynth.dif.model_interface import (
            MockBiasedModel,
            MockFairModel,
            MockSDoHBiasedModel,
        )

        model_name = str(params.get("model", "biased"))
        if model_name not in _VIZ_MODELS:
            return self._send_api_error(ApiError(
                400, f"unknown model {model_name!r}; supported: {', '.join(_VIZ_MODELS)}"))
        models = {
            "biased": MockBiasedModel,
            "fair": MockFairModel,
            "sdoh": MockSDoHBiasedModel,
        }
        try:
            req = parse_generate_request(params, max_count=self.max_count)
            if req["count"] > VIZ_FAIRNESS_MAX_COUNT:
                raise ApiError(
                    400,
                    f"'count' for /viz/fairness must be <= {VIZ_FAIRNESS_MAX_COUNT} "
                    f"(the demo audit renders 7 forms per patient), got {req['count']}",
                )
            cfg = build_config(req)
            dif_cfg = DIFConfig(
                device_name=f"Demo {model_name} model", device_version="0.0.0")
            passports = run_audit(models[model_name](), generate_patients, cfg, dif_cfg)
            # Stamp the caveat into the image itself. This endpoint can only ever
            # audit a built-in mock, and the SVG outlives the page that served it.
            svg = fairness_heatmap_svg(passports, note=VIZ_FAIRNESS_MOCK_NOTE)
        except ApiError as err:
            return self._send_api_error(err)
        except ValueError as err:
            return self._send_api_error(ApiError(400, str(err)))
        except Exception as err:  # pragma: no cover - defensive 500
            return self._send_json(500, {"error": f"viz failed: {err}", "status": 500})
        self._send_svg(svg)

    def _stream_ndjson(self, patients):
        """Stream FHIR NDJSON with HTTP chunked transfer (never buffers the whole
        cohort in memory) — the streaming answer for large-cohort responses."""
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()
        for line in iter_ndjson_lines(patients):
            data = (line + "\n").encode("utf-8")
            self.wfile.write(f"{len(data):X}\r\n".encode("ascii"))
            self.wfile.write(data)
            self.wfile.write(b"\r\n")
        self.wfile.write(b"0\r\n\r\n")


def make_server(host: str = "127.0.0.1", port: int = 8000,
                max_count: int = DEFAULT_MAX_COUNT) -> ThreadingHTTPServer:
    """Build (but do not start) a threaded HTTP server bound to host:port.

    Pass ``port=0`` to bind an ephemeral port (useful for tests); read it back
    from ``server.server_address[1]``.
    """
    handler = type("BoundHipAASynthHandler", (HipAASynthHandler,), {"max_count": max_count})
    return ThreadingHTTPServer((host, port), handler)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="HipAAsynth REST API (stdlib http.server; no external deps)."
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--max-count", type=int, default=DEFAULT_MAX_COUNT,
                        help="Maximum patients per request (default %(default)s).")
    args = parser.parse_args(argv)
    server = make_server(args.host, args.port, args.max_count)
    host, port = server.server_address[0], server.server_address[1]
    print(f"HipAAsynth API listening on http://{host}:{port}  (Ctrl-C to stop)")
    print(f"  Web UI: http://{host}:{port}/")
    print("  GET / | GET /health | GET /formats | GET /scenarios | GET|POST /generate")
    print("  GET /viz/demographics | GET /viz/fairness")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nshutting down…")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
