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

"""Full-pipeline integration test: input -> processing -> output -> logging.

Complements the generate -> audit -> passport integration test by exercising the
run-context and logging path that the other integration test does not touch:
run-directory creation, config/environment snapshots, and the JSONL event log.
It also locks in the audit-log contract from issue #27 — no synthetic record
payload leaks into the logs.
"""

import json
import os

from hipaasynth.core.config import GenerationConfig
from hipaasynth.core.logger import log_event
from hipaasynth.core.run_context import RunContext
from hipaasynth.pipelines.population_pipeline import generate_patients


class TestPipelineWithLogging:
    def test_run_writes_logs_and_snapshots_without_leaking_records(self, tmp_path, monkeypatch):
        # RunContext writes under ./runs/<run_id>; run inside a temp cwd.
        monkeypatch.chdir(tmp_path)

        # input
        context = RunContext(
            master_seed=42,
            pipeline_name="integration_test",
            pipeline_version="1.0.2",
            stages_planned=["generate"],
        )
        context.create_run_directory()
        config = GenerationConfig(patient_count=10, seed=42)
        context.write_config_snapshot(config)
        context.write_environment_snapshot()

        # processing
        patients = generate_patients(config)
        assert len(patients) == 10

        # logging (metadata only — never record payloads)
        log_event(context, "INFO", "cohort_generated", stage="generate", count=len(patients))

        # output: run directory + artifacts exist
        assert os.path.isdir(context.run_dir)
        log_path = os.path.join(context.log_dir, "engine.jsonl")
        assert os.path.isfile(log_path), "engine.jsonl was not written"

        events = [json.loads(line) for line in open(log_path, encoding="utf-8")]
        assert any(
            e.get("event") == "cohort_generated" and e.get("count") == 10 for e in events
        ), "expected event not found in the log"
        assert all("run_id" in e and "ts" in e for e in events), "log entries missing run metadata"

        env = json.load(open(os.path.join(context.run_dir, "environment_snapshot.json")))
        assert "python_version" in env and env["engine_version"] == "1.0.2"

        # #27 contract: no synthetic record field value leaks into the log.
        log_text = open(log_path, encoding="utf-8").read()
        patient_id = patients[0].to_dict()["demographics"]["patient_id"]
        assert patient_id not in log_text, "a synthetic patient_id leaked into the run log"
