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
import sys
import traceback
from datetime import datetime, timezone


def _log_dir(context) -> str:
    """Return the log directory for a context, falling back to cwd."""
    return getattr(context, "log_dir", "")


def log_event(context, level, event, **kwargs):
    """Append one structured event to the run's JSONL log.

    ``**kwargs`` must carry event *metadata* only (ids, counts, stage names,
    hashes) — never synthetic record payloads or field values. Keeping record
    contents out of the logs preserves audit-log cleanliness and ensures no
    generated data is ever duplicated into a second on-disk location.
    """
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "run_id": getattr(context, "run_id", "unknown"),
        "level": level,
        "event": event,
    }
    entry.update(kwargs)

    log_dir = _log_dir(context)
    if not log_dir:
        # No log directory configured; write to stderr as a last resort.
        sys.stderr.write(json.dumps(entry, default=str) + "\n")
        return

    try:
        os.makedirs(log_dir, exist_ok=True)
    except OSError as exc:
        sys.stderr.write(f"Failed to create log directory {log_dir}: {exc}\n")
        sys.stderr.write(json.dumps(entry, default=str) + "\n")
        return

    log_path = os.path.join(log_dir, "engine.jsonl")
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, default=str) + "\n")
    except OSError as exc:
        sys.stderr.write(f"Failed to write log to {log_path}: {exc}\n")
        sys.stderr.write(json.dumps(entry, default=str) + "\n")


def log_error(context, event, error, **kwargs):
    tb = traceback.format_exception(type(error), error, error.__traceback__)
    log_event(
        context,
        "ERROR",
        event,
        error=str(error),
        error_type=type(error).__name__,
        traceback="".join(tb),
        **kwargs,
    )
