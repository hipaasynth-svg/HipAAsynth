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
HipAAsynth Anchor Stamp

Attaches anchor metadata to outputs.
Creates audit + verification layer.
"""

from typing import List, Dict


def stamp_population(population: List[Dict], anchor) -> List[Dict]:
    """
    Attach anchor hash to every patient record.

    Returns a new list of records; the input records are not modified.
    """
    stamped = []
    for p in population:
        record = dict(p)
        record["anchor_hash"] = anchor.anchor_hash
        stamped.append(record)
    return stamped


def build_metadata(anchor, extra: Dict | None = None) -> Dict:
    """
    Build dataset-level metadata block.
    """

    meta: Dict = anchor.export()

    if extra:
        meta.update(extra)

    return meta
