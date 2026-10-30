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
adversarial/run_context_shim.py
────────────────────────────────
Lightweight shim so the adversarial layer can call:

    RunContext(seed=42, metadata={"year": 3})

without touching temporal.py or the canonical core.run_context.RunContext
(which has a different 4-arg signature used by the full pipeline audit trail).

This shim is ONLY used inside the adversarial package.
"""


class RunContext:
    """
    Adversarial-layer RunContext.

    Carries a seed and an arbitrary metadata dict.
    Does not create run directories or write manifests —
    those concerns belong to the canonical engine's own RunContext
    when a full audit run is needed.
    """

    def __init__(self, seed: int = 42, metadata: dict | None = None):
        self.seed = seed
        self.metadata = metadata or {}

    def __repr__(self):
        return f"RunContext(seed={self.seed}, metadata={self.metadata})"
