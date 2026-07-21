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
Ingest an OHDSI ATLAS cohort definition and target a matching synthetic cohort.

ATLAS (and its Circe expression format) is how the OHDSI community defines a
cohort: concept sets plus entry/inclusion criteria. This module reads such a
definition, reverse-maps its concept sets through the HipAAsynth vocabulary, and
produces a plan describing which of the cohort's clinical concepts HipAAsynth can
generate — and a ready ``GenerationConfig`` that seeds every synthetic patient
with the cohort's index condition.

The bridge: **OHDSI defines the cohort, HipAAsynth generates the
under-represented population for it and stress-tests a model for fairness.** No
network access is required — this operates on an exported cohort-definition JSON.

Scope (v1): condition concept sets and the primary/entry condition. Measurement
and drug criteria in the definition are reported as matched/unmatched but do not
yet parameterize generation. Full Circe inclusion-rule evaluation is out of
scope.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Union

from hipaasynth.core.config import ALLOWED_CONDITIONS, GenerationConfig
from hipaasynth.vocabulary import terms_for_concept_id


@dataclass(frozen=True)
class MatchedConcept:
    concept_id: int
    concept_name: str
    domain_id: str
    hipaasynth_term: str
    codeset_id: Optional[int] = None


@dataclass(frozen=True)
class UnmatchedConcept:
    concept_id: int
    concept_name: str
    domain_id: str
    codeset_id: Optional[int] = None
    reason: str = "no HipAAsynth generator term for this concept"


@dataclass
class AtlasCohortPlan:
    """Result of reading an ATLAS cohort definition.

    ``required_condition`` is the generator term for the cohort's index event
    (or the first matched condition if the entry event is not resolvable) and is
    what seeds :meth:`to_generation_config`. ``matched`` / ``unmatched`` describe
    coverage of every concept referenced by the definition's concept sets.
    """
    source_name: Optional[str]
    required_condition: Optional[str]
    matched: list = field(default_factory=list)
    unmatched: list = field(default_factory=list)
    primary_codeset_ids: list = field(default_factory=list)

    @property
    def is_generatable(self) -> bool:
        """True when a synthetic cohort can be seeded (an index condition matched)."""
        return self.required_condition is not None

    def coverage_summary(self) -> str:
        total = len(self.matched) + len(self.unmatched)
        return (f"{len(self.matched)}/{total} concept(s) map to HipAAsynth terms; "
                f"index condition = {self.required_condition!r}")

    def to_generation_config(self, patient_count: int = 100, seed: int = 42,
                             **kwargs) -> GenerationConfig:
        """Build a GenerationConfig seeded with the cohort's index condition.

        Extra keyword args pass through to GenerationConfig (e.g. profile
        selection), so a caller can target a specific under-represented
        population for the OHDSI-defined cohort.
        """
        if not self.is_generatable:
            raise ValueError(
                "Cohort definition has no condition concept HipAAsynth can "
                "generate; cannot build a GenerationConfig. Unmatched concepts: "
                + ", ".join(f"{u.concept_id} ({u.concept_name})" for u in self.unmatched))
        return GenerationConfig(
            patient_count=patient_count,
            seed=seed,
            required_condition=self.required_condition,
            **kwargs,
        )


def _prefer_generatable_term(candidates: list) -> Optional[str]:
    """Pick the best generator term for a concept from reverse-lookup candidates.

    A concept_id can map to several synonymous terms (e.g. ``afib`` and
    ``atrial_fibrillation``). Prefer a condition term that the generator actually
    accepts (``ALLOWED_CONDITIONS``); otherwise fall back to the first condition
    term.
    """
    condition_terms = [term for section, term in candidates if section == "conditions"]
    for term in condition_terms:
        if term in ALLOWED_CONDITIONS:
            return term
    return condition_terms[0] if condition_terms else None


def _iter_concept_set_items(data: dict):
    """Yield (codeset_id, concept_dict) for every concept in every concept set."""
    for cs in data.get("ConceptSets", []) or []:
        codeset_id = cs.get("id")
        expression = cs.get("expression", {}) or {}
        for item in expression.get("items", []) or []:
            concept = item.get("concept") or {}
            if concept:
                yield codeset_id, concept


def _primary_codeset_ids(data: dict) -> list:
    """Extract codeset ids referenced by the primary (entry) criteria."""
    ids = []
    primary = data.get("PrimaryCriteria", {}) or {}
    for criterion in primary.get("CriteriaList", []) or []:
        # Each criterion is a single-key dict like {"ConditionOccurrence": {...}}.
        for _domain, body in criterion.items():
            if isinstance(body, dict) and body.get("CodesetId") is not None:
                ids.append(body["CodesetId"])
    return ids


def parse_atlas_cohort(data: dict) -> AtlasCohortPlan:
    """Parse an ATLAS/Circe cohort definition dict into an :class:`AtlasCohortPlan`."""
    matched: list = []
    unmatched: list = []
    # codeset_id -> generator term, for resolving the primary criteria below.
    codeset_condition_term: dict = {}

    for codeset_id, concept in _iter_concept_set_items(data):
        cid = concept.get("CONCEPT_ID")
        name = concept.get("CONCEPT_NAME", "")
        domain = concept.get("DOMAIN_ID", "")
        candidates = terms_for_concept_id(cid)
        term = _prefer_generatable_term(candidates)
        if term is not None:
            matched.append(MatchedConcept(
                concept_id=int(cid), concept_name=name, domain_id=domain,
                hipaasynth_term=term, codeset_id=codeset_id))
            if codeset_id is not None and codeset_id not in codeset_condition_term:
                codeset_condition_term[codeset_id] = term
        else:
            if cid is None:
                continue
            unmatched.append(UnmatchedConcept(
                concept_id=int(cid), concept_name=name, domain_id=domain,
                codeset_id=codeset_id))

    primary_ids = _primary_codeset_ids(data)
    required_condition = None
    for pid in primary_ids:
        if pid in codeset_condition_term:
            required_condition = codeset_condition_term[pid]
            break
    # Fall back to the first matched condition if the entry event didn't resolve.
    if required_condition is None:
        for m in matched:
            if m.domain_id == "Condition" or m.hipaasynth_term in ALLOWED_CONDITIONS:
                required_condition = m.hipaasynth_term
                break

    return AtlasCohortPlan(
        source_name=data.get("Name") or data.get("name"),
        required_condition=required_condition,
        matched=matched,
        unmatched=unmatched,
        primary_codeset_ids=primary_ids,
    )


def load_atlas_cohort(source: Union[str, Path, dict]) -> AtlasCohortPlan:
    """Load an ATLAS cohort definition from a path, JSON string, or dict.

    ATLAS can export a cohort either as a bare Circe ``expression`` object or
    wrapped as ``{"expression": "<json string>"}`` (the WebAPI form). Both are
    accepted.
    """
    if isinstance(source, dict):
        data = source
    else:
        text = Path(source).read_text(encoding="utf-8") if _looks_like_path(source) else str(source)
        data = json.loads(text)
    # WebAPI wraps the definition; the expression may itself be a JSON string.
    if "ConceptSets" not in data and "expression" in data:
        expr = data["expression"]
        data = json.loads(expr) if isinstance(expr, str) else expr
    return parse_atlas_cohort(data)


def _looks_like_path(source) -> bool:
    if not isinstance(source, (str, Path)):
        return False
    s = str(source)
    if "\n" in s or s.lstrip().startswith("{"):
        return False
    return Path(s).exists()
