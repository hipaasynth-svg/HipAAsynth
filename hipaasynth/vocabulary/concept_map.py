"""
OHDSI/OMOP vocabulary layer for HipAAsynth.

HipAAsynth generators emit a finite, controlled set of internal term strings
(condition names, lab names, visit types). This module maps those terms to
standard clinical terminologies (SNOMED CT, ICD-10-CM, LOINC) and OMOP standard
``concept_id`` values, so that HipAAsynth output can be consumed by the OHDSI
tool ecosystem (ATLAS, ACHILLES, DataQualityDashboard, HADES) and by
coding-aware FHIR consumers.

Design notes
------------
* The map is data, not code: it lives in ``concept_map.json`` next to this
  module and is loaded once, lazily, and cached.
* Lookups are normalized (case-insensitive, trimmed) and return ``None`` for
  unmapped terms rather than raising — callers decide whether an unmapped term
  is fatal.
* ``concept_id`` values are curated best-effort and are flagged as
  ``UNVALIDATED`` in the map metadata. They MUST be validated against a pinned
  ATHENA vocabulary release before use in production OMOP tooling. See
  ``README.md`` in this package.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Optional

_MAP_PATH = Path(__file__).with_name("concept_map.json")


@dataclass(frozen=True)
class ConceptMapping:
    """A single mapping from a HipAAsynth internal term to standard concepts."""

    source_term: str
    domain: str
    omop_concept_id: Optional[int]
    omop_concept_name: Optional[str]
    snomed_code: Optional[str] = None
    snomed_name: Optional[str] = None
    icd10cm: Optional[str] = None
    loinc: Optional[str] = None
    loinc_name: Optional[str] = None
    rxnorm: Optional[str] = None
    rxnorm_name: Optional[str] = None
    atc: Optional[str] = None
    atc_name: Optional[str] = None
    concept_type: Optional[str] = None
    unit_ucum: Optional[str] = None
    components: tuple = ()

    def fhir_coding(self) -> list[dict]:
        """Return FHIR ``coding[]`` entries for this concept.

        Emits one entry per terminology available for the term (SNOMED, LOINC,
        ICD-10-CM, RxNorm, ATC — plus component ingredients for a combination
        drug). Callers wrap this in a ``CodeableConcept`` alongside a ``text``
        display.
        """
        codings: list[dict] = []
        if self.snomed_code:
            codings.append(
                {
                    "system": "http://snomed.info/sct",
                    "code": self.snomed_code,
                    "display": self.snomed_name,
                }
            )
        if self.loinc:
            codings.append(
                {
                    "system": "http://loinc.org",
                    "code": self.loinc,
                    "display": self.loinc_name,
                }
            )
        if self.icd10cm:
            codings.append(
                {
                    "system": "http://hl7.org/fhir/sid/icd-10-cm",
                    "code": self.icd10cm,
                }
            )
        if self.rxnorm:
            codings.append(
                {
                    "system": "http://www.nlm.nih.gov/research/umls/rxnorm",
                    "code": self.rxnorm,
                    "display": self.rxnorm_name,
                }
            )
        if self.atc:
            codings.append(
                {
                    "system": "http://www.whocc.no/atc",
                    "code": self.atc,
                    "display": self.atc_name,
                }
            )
        for comp in self.components:
            code = comp.get("rxnorm")
            if code:
                codings.append(
                    {
                        "system": "http://www.nlm.nih.gov/research/umls/rxnorm",
                        "code": code,
                        "display": comp.get("rxnorm_name"),
                    }
                )
        return codings


@lru_cache(maxsize=1)
def _raw_map() -> dict:
    with open(_MAP_PATH, encoding="utf-8") as f:
        return json.load(f)


def map_version() -> str:
    """Return the semantic version of the shipped concept map."""
    return _raw_map()["metadata"]["map_version"]


def validation_status() -> str:
    """Return the validation status of the concept_id values in the map."""
    return _raw_map()["metadata"]["validation_status"]


def _normalize(term: str) -> str:
    return term.strip().lower()


def _lookup(section: str, term: str) -> Optional[ConceptMapping]:
    if term is None:
        return None
    entries = _raw_map().get(section, {})
    # Section keys are stored normalized-friendly; measurements keep original
    # casing (e.g. "Glucose") so match both exact and normalized.
    entry = entries.get(term)
    if entry is None:
        wanted = _normalize(term)
        for key, value in entries.items():
            if _normalize(key) == wanted:
                entry = value
                break
    if entry is None:
        return None
    return ConceptMapping(
        source_term=term,
        domain=entry.get("domain", section.rstrip("s").capitalize()),
        omop_concept_id=entry.get("omop_concept_id"),
        omop_concept_name=entry.get("omop_concept_name"),
        snomed_code=entry.get("snomed_code"),
        snomed_name=entry.get("snomed_name"),
        icd10cm=entry.get("icd10cm"),
        loinc=entry.get("loinc"),
        loinc_name=entry.get("loinc_name"),
        rxnorm=entry.get("rxnorm"),
        rxnorm_name=entry.get("rxnorm_name"),
        atc=entry.get("atc"),
        atc_name=entry.get("atc_name"),
        concept_type=entry.get("concept_type"),
        unit_ucum=entry.get("unit_ucum"),
        components=tuple(entry.get("components", ())),
    )


def lookup_condition(name: str) -> Optional[ConceptMapping]:
    """Map a HipAAsynth condition term to standard concepts, or ``None``."""
    return _lookup("conditions", name)


def lookup_measurement(name: str) -> Optional[ConceptMapping]:
    """Map a HipAAsynth lab/measurement term to standard concepts, or ``None``."""
    return _lookup("measurements", name)


def lookup_visit(visit_type: str) -> Optional[ConceptMapping]:
    """Map a HipAAsynth visit type to an OMOP visit concept, or ``None``."""
    return _lookup("visits", visit_type)


def lookup_medication(name: str) -> Optional[ConceptMapping]:
    """Map a HipAAsynth medication term to standard drug concepts, or ``None``.

    Medication terms are either drug *classes* (``concept_type == 'atc_class'``,
    carrying an ATC code) or single ingredients (``concept_type ==
    'rxnorm_ingredient'``, carrying an RxNorm code), or a fixed-dose
    ``combination`` carrying component RxNorm codes. ``omop_concept_id`` is
    intentionally null in the shipped map and is resolved from the ATC/RxNorm
    code during ATHENA validation (see ``validate.py``) rather than fabricated.
    """
    return _lookup("medications", name)


def unmapped_terms(conditions=(), measurements=(), visits=(), medications=()) -> dict[str, list[str]]:
    """Return terms with no concept mapping, grouped by domain.

    Useful for coverage checks in CI: pass the term sets a generator can emit
    and assert the result is empty.
    """
    return {
        "conditions": [c for c in conditions if lookup_condition(c) is None],
        "measurements": [m for m in measurements if lookup_measurement(m) is None],
        "visits": [v for v in visits if lookup_visit(v) is None],
        "medications": [m for m in medications if lookup_medication(m) is None],
    }
