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

"""Container packaging (Tier 3 step 3).

Static correctness checks for the Dockerfile / .dockerignore / docker-compose.yml.
A real `docker build`/`docker run` needs a Docker daemon, which is not available in
this test environment; the Dockerfile's runtime behavior was verified separately by
a shell dry-run (clean venv `pip install .` + running the entrypoint + hitting
/health) — see the roadmap change log. These tests guard the artifacts from
regressing.
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DOCKERFILE = (REPO / "Dockerfile").read_text(encoding="utf-8")
DOCKERIGNORE = (REPO / ".dockerignore").read_text(encoding="utf-8")
COMPOSE = (REPO / "docker-compose.yml").read_text(encoding="utf-8")

API_PORT = "8000"


def test_dockerfile_uses_supported_python_base():
    # Must match pyproject requires-python >=3.11.
    assert "FROM python:3.11" in DOCKERFILE


def test_dockerfile_installs_the_package():
    assert "pip install" in DOCKERFILE
    # Installs the package itself (the current dir), not some random requirement.
    assert "pip install --no-cache-dir ." in DOCKERFILE


def test_dockerfile_exposes_and_runs_the_api():
    assert f"EXPOSE {API_PORT}" in DOCKERFILE
    # Entrypoint runs the REST API module.
    assert '"python", "-m", "hipaasynth.api"' in DOCKERFILE
    # CMD binds 0.0.0.0 so the API is reachable from outside the container.
    assert '"--host", "0.0.0.0"' in DOCKERFILE
    assert f'"--port", "{API_PORT}"' in DOCKERFILE


def test_dockerfile_runs_as_non_root():
    assert "USER appuser" in DOCKERFILE
    assert "useradd" in DOCKERFILE
    # USER must come before the ENTRYPOINT so the process drops privileges.
    assert DOCKERFILE.index("USER appuser") < DOCKERFILE.index("ENTRYPOINT")


def test_dockerfile_healthcheck_hits_health_endpoint():
    assert "HEALTHCHECK" in DOCKERFILE
    assert "/health" in DOCKERFILE


def test_dockerignore_excludes_dev_cruft():
    for pattern in (".git", "tests", "__pycache__", "*.duckdb"):
        assert pattern in DOCKERIGNORE
    # But keeps the files the build needs.
    assert "!README.md" in DOCKERIGNORE
    assert "!LICENSE.md" in DOCKERIGNORE


def test_compose_builds_and_maps_the_port():
    assert "build: ." in COMPOSE
    assert f'"{API_PORT}:{API_PORT}"' in COMPOSE
    assert "0.0.0.0" in COMPOSE
    assert "--max-count" in COMPOSE


def test_compose_is_valid_yaml_when_pyyaml_available():
    """If PyYAML is installed, the compose file must parse and have one service."""
    try:
        import yaml
    except ImportError:
        import pytest
        pytest.skip("PyYAML not installed")
    data = yaml.safe_load(COMPOSE)
    assert "services" in data
    assert "api" in data["services"]
    svc = data["services"]["api"]
    assert svc["build"] == "."
    assert f"{API_PORT}:{API_PORT}" in svc["ports"]


def test_port_is_consistent_across_artifacts():
    """EXPOSE, CMD, and compose all agree on the API port."""
    assert f"EXPOSE {API_PORT}" in DOCKERFILE
    assert f'"--port", "{API_PORT}"' in DOCKERFILE
    assert f'"{API_PORT}:{API_PORT}"' in COMPOSE
