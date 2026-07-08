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
HipAAsynth Anchor System

Defines the deterministic root of truth for the entire simulation.
Everything derives from this.

This is what makes the system:
- reproducible
- auditable
- tamper-evident
"""

import hashlib
from typing import Dict


class Anchor:
    """
    Global deterministic anchor.

    Combines:
    - seed
    - config
    - module versions

    Produces:
    - master hash (source of truth)
    """

    def __init__(self, seed: int, config: Dict, modules: Dict):
        """Build a deterministic anchor from the seed, run config, and module
        versions. The SHA-256 anchor hash is computed at construction so every run is
        reproducible and tamper-evident.

        Inputs: seed (int), config (dict), modules (dict of name->version).
        Side effects: none. Sets self.anchor_hash.
        """
        self.seed = seed
        self.config = config
        self.modules = modules

        self.anchor_hash = self._build_anchor()

    # =============================
    # CORE
    # =============================

    def _build_anchor(self) -> str:
        """
        Build deterministic fingerprint of entire system state.
        """

        payload = {
            "seed": self.seed,
            "config": self.config,
            "modules": self.modules
        }

        serialized = self._stable_serialize(payload)

        return hashlib.sha256(serialized.encode()).hexdigest()

    def _stable_serialize(self, obj) -> str:
        """
        Deterministic serialization (order-safe).
        """

        if isinstance(obj, dict):
            return "{" + ",".join(
                f"{k}:{self._stable_serialize(obj[k])}"
                for k in sorted(obj)
            ) + "}"

        elif isinstance(obj, list):
            return "[" + ",".join(self._stable_serialize(x) for x in obj) + "]"

        else:
            return str(obj)

    # =============================
    # CHILD SEEDS
    # =============================

    def derive_seed(self, namespace: str) -> int:
        """
        Deterministically derive sub-seeds for modules.
        """

        combined = f"{self.anchor_hash}:{namespace}"
        return int(hashlib.sha256(combined.encode()).hexdigest(), 16) % (10**9)

    # =============================
    # VERIFY
    # =============================

    def verify(self, other_hash: str) -> bool:
        """Return True if ``other_hash`` equals this anchor's hash.

        An integrity check for third-party reproduction: a matching hash proves the
        same seed/config/module versions were used. No side effects.
        """
        return self.anchor_hash == other_hash

    # =============================
    # EXPORT
    # =============================

    def export(self) -> Dict:
        """Return the anchor as a JSON-serializable dict (seed, config, modules,
        anchor_hash) for inclusion in the run manifest. No side effects; no PHI.
        """
        return {
            "anchor_hash": self.anchor_hash,
            "seed": self.seed,
            "modules": self.modules
        }