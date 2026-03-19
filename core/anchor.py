# Copyright 2026 Cody Carlson
# Licensed under the Apache License, Version 2.0

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
        return self.anchor_hash == other_hash

    # =============================
    # EXPORT
    # =============================

    def export(self) -> Dict:
        return {
            "anchor_hash": self.anchor_hash,
            "seed": self.seed,
            "modules": self.modules
        }