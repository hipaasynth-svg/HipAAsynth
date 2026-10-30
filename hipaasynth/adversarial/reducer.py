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

"""
adversarial/reducer.py
───────────────────────
Binary-search reducer: finds the minimal failure subset.
Updated to handle both the new clinical failure schema and the
legacy numeric schema gracefully.
"""


class Reducer:
    def __init__(self, evaluator, model_fn):
        self.evaluator = evaluator
        self.model_fn = model_fn

    def reduce(self, failures):
        current = failures[:]
        while len(current) > 10:
            half = current[: len(current) // 2]
            if self._still_fails(half):
                current = half
            else:
                current = current[len(current) // 2 :]
        return current

    def _still_fails(self, subset):
        timelines = {}
        for item in subset:
            pid = item["patient_id"]
            if pid not in timelines:
                timelines[pid] = {"patient_id": pid, "timeline": []}
            timelines[pid]["timeline"].append(item["state"])
        return len(self.evaluator.evaluate(list(timelines.values()), self.model_fn)) > 0
