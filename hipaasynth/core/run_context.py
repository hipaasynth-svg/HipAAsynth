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
import platform
import secrets
import sys
from datetime import datetime, timezone


class RunContext:

    def __init__(self, master_seed, pipeline_name, pipeline_version, stages_planned):
        self.master_seed = master_seed
        self.pipeline_name = pipeline_name
        self.pipeline_version = pipeline_version
        self.stages_planned = list(stages_planned)
        self.stages_completed = []

        self.base_dir = "runs"
        self.run_id = self._generate_run_id()
        self.run_dir = os.path.join(self.base_dir, self.run_id)
        self.log_dir = os.path.join(self.run_dir, "logs")
        self.checkpoint_dir = os.path.join(self.run_dir, "checkpoints")
        self.output_dir = os.path.join(self.run_dir, "outputs")
        self.manifest_path = os.path.join(self.run_dir, "run_manifest.json")

    def _generate_run_id(self):
        """
        Generate a unique run ID.

        Includes a microsecond timestamp plus a random suffix to avoid collisions
        when multiple runs start in the same second.
        """
        now = datetime.now()
        date_part = now.strftime("%Y-%m-%d_%H%M%S_%f")
        suffix = secrets.token_hex(4)
        return f"{date_part}_run_{suffix}"

    def create_run_directory(self):
        try:
            os.makedirs(self.run_dir, exist_ok=True)
            os.makedirs(self.log_dir, exist_ok=True)
            os.makedirs(self.checkpoint_dir, exist_ok=True)
            os.makedirs(self.output_dir, exist_ok=True)
        except OSError as exc:
            raise RuntimeError(f"Failed to create run directories under {self.run_dir}") from exc

    def write_config_snapshot(self, cfg):
        snapshot = {}
        if hasattr(cfg, "__dict__"):
            snapshot = {k: v for k, v in cfg.__dict__.items()}
        elif isinstance(cfg, dict):
            snapshot = dict(cfg)
        path = os.path.join(self.run_dir, "config_snapshot.json")
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(snapshot, f, indent=2, default=str)
        except OSError as exc:
            raise RuntimeError(f"Failed to write config snapshot: {path}") from exc
        return path

    def write_environment_snapshot(self):
        """Write reproducibility metadata for the run to environment_snapshot.json.

        Captures the Python version, platform string, current working directory,
        process id, timestamp, and engine version — host/runtime details that let
        a third party reproduce a run. No patient/synthetic data is recorded. Note
        that ``cwd`` and ``platform`` may reveal host paths and OS details; in a
        locked-down deployment, keep run directories within the controlled output
        area (see docs/DEPLOYMENT.md).
        """
        snapshot = {
            "python_version": sys.version,
            "platform": platform.platform(),
            "cwd": os.getcwd(),
            "pid": os.getpid(),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "engine_version": self.pipeline_version,
        }
        path = os.path.join(self.run_dir, "environment_snapshot.json")
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(snapshot, f, indent=2)
        except OSError as exc:
            raise RuntimeError(f"Failed to write environment snapshot: {path}") from exc
        return path

    def write_replay_command(self, argv):
        cmd = "python " + " ".join(argv)
        path = os.path.join(self.run_dir, "replay_command.txt")
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(cmd + "\n")
        except OSError as exc:
            raise RuntimeError(f"Failed to write replay command: {path}") from exc
        return path
