"""Helpers shared by section mappers."""

from __future__ import annotations

from collections.abc import Iterator

from lxml import etree

from ..codes import simple_concept
from ..xml import HL7_NS, attr, children, local_name

CLINICAL_STATEMENTS = {
    "act",
    "observation",
    "substanceAdministration",
    "procedure",
    "encounter",
    "organizer",
    "supply",
    "observationMedia",
    "regionOfInterest",
}

OBS_CATEGORY = "http://terminology.hl7.org/CodeSystem/observation-category"
CONDITION_CLINICAL = "http://terminology.hl7.org/CodeSystem/condition-clinical"
CONDITION_CATEGORY = "http://terminology.hl7.org/CodeSystem/condition-category"
ALLERGY_CLINICAL = "http://terminology.hl7.org/CodeSystem/allergyintolerance-clinical"
ALLERGY_VERIFICATION = "http://terminology.hl7.org/CodeSystem/allergyintolerance-verification"
V3_ACT_CODE = "http://terminology.hl7.org/CodeSystem/v3-ActCode"
V2_0074 = "http://terminology.hl7.org/CodeSystem/v2-0074"
DATA_ABSENT = "http://terminology.hl7.org/CodeSystem/data-absent-reason"


def statement_of(entry: etree._Element) -> etree._Element | None:
    """The clinical statement inside an ``entry`` (act, observation, ...)."""
    for el in entry:
        if not isinstance(el.tag, str) or not el.tag.startswith(f"{{{HL7_NS}}}"):
            continue
        if local_name(el) in CLINICAL_STATEMENTS:
            return el
    return None


def entries(
    section_el: etree._Element,
) -> Iterator[tuple[int, etree._Element, etree._Element | None]]:
    """Yield ``(ordinal, entry, statement)`` for each entry of a section."""
    for i, entry in enumerate(children(section_el, "entry")):
        yield i, entry, statement_of(entry)


def related(
    el: etree._Element, type_code: str | None = None, local: str | None = None
) -> list[etree._Element]:
    """Clinical statements inside ``entryRelationship`` children, filtered by typeCode and name."""
    out: list[etree._Element] = []
    for rel in children(el, "entryRelationship"):
        if type_code and (attr(rel, "typeCode") or "").upper() != type_code:
            continue
        for stmt in rel:
            if not isinstance(stmt.tag, str):
                continue
            if local and local_name(stmt) != local:
                continue
            if local_name(stmt) in CLINICAL_STATEMENTS:
                out.append(stmt)
    return out


def has_template(el: etree._Element | None, *roots: str) -> bool:
    if el is None:
        return False
    found = {attr(t, "root") for t in children(el, "templateId")}
    return any(r in found for r in roots)


def category(system: str, code: str, display: str) -> dict:
    return simple_concept(system, code, display)


def observation_category(code: str) -> dict:
    display = {
        "vital-signs": "Vital Signs",
        "laboratory": "Laboratory",
        "social-history": "Social History",
        "survey": "Survey",
        "exam": "Exam",
    }.get(code, code)
    return simple_concept(OBS_CATEGORY, code, display)


def display_of(el: etree._Element | None) -> str | None:
    """``name`` child text or displayName, for organisations and persons."""
    if el is None:
        return None
    for n in children(el, "name"):
        t = " ".join(s.strip() for s in n.itertext() if s.strip())
        if t:
            return t
    return None
