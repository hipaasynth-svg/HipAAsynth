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

import json
import os
import tempfile
from datetime import datetime, timezone


def _read_manifest(path: str) -> dict:
    """Read manifest JSON, returning an empty dict if it does not exist or is unreadable."""
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Failed to read manifest: {path}") from exc


def _write_manifest(path: str, manifest: dict) -> None:
    """Write manifest JSON atomically via a temporary file."""
    run_dir = os.path.dirname(path)
    try:
        fd, tmp_path = tempfile.mkstemp(dir=run_dir, suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(manifest, f, indent=2)
            os.replace(tmp_path, path)
        except Exception:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            raise
    except OSError as exc:
        raise RuntimeError(f"Failed to write manifest: {path}") from exc


def init_manifest(context):
    """Create the initial run manifest (run id, pipeline identity, timestamps)
    and write it to the run's manifest path.

    Side effect: writes run_manifest.json. Returns the manifest dict. No PHI.
    """
    manifest = {
        "run_id": context.run_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "running",
        "master_seed": context.master_seed,
        "pipeline_name": context.pipeline_name,
        "pipeline_version": context.pipeline_version,
        "stages_planned": context.stages_planned,
        "stages_completed": [],
    }

    _write_manifest(context.manifest_path, manifest)
    return manifest


def update_manifest(context, updates):
    """Merge ``updates`` into the run manifest and rewrite it atomically.

    Inputs: context (RunContext), updates (dict). Side effect: rewrites
    run_manifest.json. Returns the updated manifest dict.
    """
    manifest = _read_manifest(context.manifest_path)
    manifest.update(updates)
    _write_manifest(context.manifest_path, manifest)
    return manifest
