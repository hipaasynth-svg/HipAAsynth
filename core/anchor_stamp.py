# Copyright 2026 Cody Carlson
# Licensed under the Apache License, Version 2.0

"""
HipAAsynth Anchor Stamp

Attaches anchor metadata to outputs.
Creates audit + verification layer.
"""

from typing import List, Dict


def stamp_population(population: List[Dict], anchor) -> List[Dict]:
    """
    Attach anchor hash to every patient record.
    """

    for p in population:
        p['anchor_hash'] = anchor.anchor_hash

    return population


def build_metadata(anchor, extra: Dict = None) -> Dict:
    """
    Build dataset-level metadata block.
    """

    meta = anchor.export()

    if extra:
        meta.update(extra)

    return meta
