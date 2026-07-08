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

import csv
import json
import os
import tempfile
from datetime import datetime, timezone

from hipaasynth.core.hashing import compute_sha256
from hipaasynth.core.logger import log_event


def _append_hash(context, relative_path, digest):
    """Append a ``(relative_path, sha256)`` entry to the run's checkpoint hash
    file, under a lock and via an atomic replace.

    Side effect: writes checkpoints hashes JSON. Records integrity digests only —
    never record contents.
    """
    hashes_path = os.path.join(context.run_dir, "hashes.json")
    lock_path = hashes_path + ".lock"
    try:
        import fcntl
        with open(lock_path, "w") as lockfile:
            fcntl.flock(lockfile.fileno(), fcntl.LOCK_EX)
            try:
                if os.path.exists(hashes_path):
                    with open(hashes_path, "r", encoding="utf-8") as f:
                        hashes = json.load(f)
                else:
                    hashes = {}
                hashes[relative_path] = digest
                fd, tmp_path = tempfile.mkstemp(dir=context.run_dir, suffix=".json")
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(hashes, f, indent=2)
                os.replace(tmp_path, hashes_path)
            finally:
                fcntl.flock(lockfile.fileno(), fcntl.LOCK_UN)
    except (ImportError, AttributeError):
        # Windows: fcntl not available, fall back to best-effort atomic rename
        if os.path.exists(hashes_path):
            with open(hashes_path, "r", encoding="utf-8") as f:
                hashes = json.load(f)
        else:
            hashes = {}
        hashes[relative_path] = digest
        fd, tmp_path = tempfile.mkstemp(dir=context.run_dir, suffix=".json")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(hashes, f, indent=2)
        os.replace(tmp_path, hashes_path)


def _dict_of_columns_to_rows(df: dict) -> tuple[list[str], list[dict]]:
    """Convert a dict-of-columns to (fieldnames, rows), validating column lengths."""
    keys = list(df.keys())
    if not keys:
        return [], []

    lengths = {len(v) for v in df.values()}
    if len(lengths) > 1:
        raise ValueError(f"Dict-of-columns has inconsistent column lengths: {lengths}")

    row_count = len(df[keys[0]])
    rows = [{k: df[k][i] for k in keys} for i in range(row_count)]
    return keys, rows


def save_checkpoint(context, stage_name, df, stage_index):
    """Persist a pipeline stage's output as a JSON checkpoint and record its
    SHA-256 digest for integrity.

    Inputs: context (RunContext), stage_name (str), df (column->values dict),
    stage_index (int). Side effects: writes the checkpoint file and its hash entry.
    Data is synthetic; no PHI is written.
    """
    prefix = f"{stage_index:02d}_{stage_name}"
    csv_path = os.path.join(context.checkpoint_dir, f"{prefix}.csv")
    meta_path = os.path.join(context.checkpoint_dir, f"{prefix}.meta.json")

    if os.path.exists(csv_path):
        raise FileExistsError(f"Checkpoint already exists: {csv_path}")

    try:
        if isinstance(df, list) and len(df) > 0 and isinstance(df[0], dict):
            all_keys = []
            seen = set()
            for row in df:
                for k in row:
                    if k not in seen:
                        all_keys.append(k)
                        seen.add(k)
            row_count = len(df)
            col_count = len(all_keys)

            with open(csv_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=all_keys, extrasaction="ignore")
                writer.writeheader()
                writer.writerows(df)

        elif isinstance(df, dict):
            keys, rows = _dict_of_columns_to_rows(df)
            row_count = len(rows)
            col_count = len(keys)

            with open(csv_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=keys)
                writer.writeheader()
                writer.writerows(rows)

        elif hasattr(df, "demographics"):
            row_count = 1
            col_count = 0
            with open(csv_path, "w", encoding="utf-8") as f:
                f.write("patient_object\n")

        elif isinstance(df, list):
            row_count = len(df)
            col_count = 0

            with open(csv_path, "w", newline="", encoding="utf-8") as f:
                if row_count > 0 and hasattr(df[0], "to_dict"):
                    rows = [p.to_dict() for p in df]
                    all_keys = []
                    seen = set()
                    for row in rows:
                        for k in row:
                            if k not in seen:
                                all_keys.append(k)
                                seen.add(k)
                    col_count = len(all_keys)
                    writer = csv.DictWriter(f, fieldnames=all_keys, extrasaction="ignore")
                    writer.writeheader()
                    writer.writerows(rows)
                else:
                    f.write("value\n")
                    for item in df:
                        f.write(f"{item}\n")
        else:
            raise TypeError(f"Unsupported data type for checkpoint: {type(df)}")
    except OSError as exc:
        raise RuntimeError(f"Failed to write checkpoint CSV: {csv_path}") from exc

    metadata = {
        "run_id": context.run_id,
        "stage": stage_name,
        "row_count": row_count,
        "column_count": col_count,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "master_seed": context.master_seed,
    }

    try:
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2)
    except OSError as exc:
        raise RuntimeError(f"Failed to write checkpoint metadata: {meta_path}") from exc

    try:
        digest = compute_sha256(csv_path)
    except OSError as exc:
        raise RuntimeError(f"Failed to compute SHA256 for checkpoint: {csv_path}") from exc

    relative_key = f"checkpoints/{prefix}.csv"
    _append_hash(context, relative_key, digest)
    log_event(context, "INFO", "checkpoint_hashed", stage=stage_name, sha256=digest)

    return csv_path
