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

"""Named scenario blueprints — a profile + decision-module shortcut.

A *scenario* is a small, human-readable name that resolves to a
``(module, profile)`` pair the engine already understands, plus a description.
It is a pure convenience layer over the existing ``--module``/``--profile``
surface: resolving a scenario just yields those two values, so the CLI, REST API
and web UI can offer one-click blueprints without changing what module/profile
already do.

The blueprints live in :data:`SCENARIOS_PATH` (``scenarios.json``). Every entry
is validated at load time against the *real* engine surface — its ``module`` must
be a key of :data:`hipaasynth.sdk.MODULES` and its ``profile`` must be a bundled
profile name — so a typo or an invented module/profile fails loudly rather than
producing a broken shortcut. All generated records are synthetic — no PHI.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional

from hipaasynth.sdk import MODULES, available_profiles

SCENARIOS_PATH = Path(__file__).resolve().parent / "scenarios.json"


class ScenarioError(ValueError):
    """Raised when a scenario name is unknown or a blueprint is invalid."""


@dataclass(frozen=True)
class Scenario:
    """A named ``(module, profile)`` blueprint with a human-readable description."""

    name: str
    module: str
    profile: str
    description: str
    label: str = ""
    default_count: Optional[int] = None

    def to_dict(self) -> dict:
        """JSON-serializable summary for the API / UI."""
        return {
            "name": self.name,
            "label": self.label or self.name,
            "module": self.module,
            "profile": self.profile,
            "description": self.description,
            "default_count": self.default_count,
        }


def _validate(entry: dict, known_profiles: List[str]) -> Scenario:
    """Build a :class:`Scenario` from a raw dict, validating module + profile."""
    try:
        name = str(entry["name"])
        module = str(entry["module"])
        profile = str(entry["profile"])
        description = str(entry["description"])
    except KeyError as err:
        raise ScenarioError(f"scenario missing required field {err}") from err
    if module not in MODULES:
        raise ScenarioError(
            f"scenario {name!r} uses unknown module {module!r}; "
            f"real modules are: {', '.join(MODULES)}"
        )
    if profile not in known_profiles:
        raise ScenarioError(
            f"scenario {name!r} uses unknown profile {profile!r}; "
            f"bundled profiles are: {', '.join(known_profiles)}"
        )
    return Scenario(
        name=name,
        module=module,
        profile=profile,
        description=description,
        label=str(entry.get("label", "")),
        default_count=entry.get("default_count"),
    )


@lru_cache(maxsize=1)
def load_scenarios() -> Dict[str, Scenario]:
    """Load and validate all bundled scenario blueprints, keyed by name."""
    raw = json.loads(SCENARIOS_PATH.read_text(encoding="utf-8"))
    known_profiles = available_profiles()
    scenarios: Dict[str, Scenario] = {}
    for entry in raw.get("scenarios", []):
        scenario = _validate(entry, known_profiles)
        if scenario.name in scenarios:
            raise ScenarioError(f"duplicate scenario name {scenario.name!r}")
        scenarios[scenario.name] = scenario
    return scenarios


def available_scenarios() -> List[str]:
    """Sorted names of the bundled scenario blueprints."""
    return sorted(load_scenarios())


def get_scenario(name: str) -> Scenario:
    """Return the :class:`Scenario` for ``name`` or raise :class:`ScenarioError`."""
    scenarios = load_scenarios()
    try:
        return scenarios[name]
    except KeyError:
        raise ScenarioError(
            f"unknown scenario {name!r}; available: {', '.join(sorted(scenarios))}"
        ) from None


def resolve_scenario(name: str) -> Dict[str, str]:
    """Resolve a scenario name to its ``{module, profile}`` params."""
    scenario = get_scenario(name)
    return {"module": scenario.module, "profile": scenario.profile}


def scenario_summaries() -> List[dict]:
    """All scenarios as JSON-serializable dicts (stable order) for the API/UI."""
    return [load_scenarios()[name].to_dict() for name in available_scenarios()]
