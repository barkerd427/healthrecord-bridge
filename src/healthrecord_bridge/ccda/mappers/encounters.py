"""Encounters section (LOINC 46240-8) to ``Encounter``."""

from __future__ import annotations

from lxml import etree

from ..codes import concept_text
from ..context import Context, status_code
from ..document import Section, person_name
from ..report import SectionReport, SkippedEntry
from ..xml import attr, child, children, find, local_name
from ._shared import V3_ACT_CODE, display_of, entries

_CLASS_DISPLAY = {
    "AMB": "ambulatory",
    "EMER": "emergency",
    "IMP": "inpatient encounter",
    "ACUTE": "inpatient acute",
    "NONAC": "inpatient non-acute",
    "OBSENC": "observation encounter",
    "PRENC": "pre-admission",
    "SS": "short stay",
    "HH": "home health",
    "VR": "virtual",
    "FLD": "field",
}

# SNOMED encounter types that imply a class other than ambulatory.
_SNOMED_CLASS = {
    "50849002": "EMER",  # Emergency room admission
    "4525004": "EMER",  # Emergency department patient visit
    "183452005": "EMER",  # Emergency hospital admission
    "32485007": "IMP",  # Hospital admission
    "305351004": "IMP",  # Admission to intensive care unit
    "183807002": "IMP",  # Inpatient stay for observation
    "8715000": "IMP",  # Hospital admission, elective
    "453701000124103": "IMP",  # Inpatient encounter
    "185347001": "AMB",  # Encounter for problem
    "439740005": "AMB",  # Postoperative follow-up visit
    "185349003": "AMB",  # Encounter for check up
    "308335008": "AMB",  # Patient encounter procedure
    "698314001": "VR",  # Consultation for treatment (telehealth)
    "448337001": "VR",  # Telemedicine consultation with patient
    "453691000124108": "VR",  # Telehealth encounter
    "371883000": "AMB",  # Outpatient procedure
    "702927004": "AMB",  # Urgent care clinic
    "439708006": "HH",  # Home visit
    "315637000": "HH",  # Home visit elderly assessment
}

_STATUS = {
    "completed": "finished",
    "active": "in-progress",
    "aborted": "cancelled",
    "cancelled": "cancelled",
    "suspended": "onleave",
}


def map_encounters(ctx: Context, section: Section, sr: SectionReport) -> list[dict]:
    out: list[dict] = []
    for ordinal, _entry, stmt in entries(section.element):
        if stmt is None:
            sr.skipped.append(SkippedEntry("entry has no clinical statement", ordinal))
            continue
        if local_name(stmt) != "encounter":
            sr.skipped.append(SkippedEntry(f"unsupported statement {local_name(stmt)}", ordinal))
            continue
        out.append(_encounter(ctx, stmt, section.code, ordinal))
    return out


def _encounter(ctx: Context, enc: etree._Element, section_code: str | None, ordinal: int) -> dict:
    res = ctx.new_resource("Encounter", enc, section_code, ordinal)
    res["status"] = _STATUS.get(status_code(enc) or "completed", "finished")
    type_cc = ctx.concept(child(enc, "code"))
    cls = _encounter_class(type_cc)
    res["class"] = {"system": V3_ACT_CODE, "code": cls, "display": _CLASS_DISPLAY.get(cls, cls)}
    if type_cc:
        res["type"] = [type_cc]
    res["subject"] = ctx.patient_ref
    participants = []
    for perf in children(enc, "performer"):
        entity = child(perf, "assignedEntity")
        name = person_name(find(entity, "c:assignedPerson/c:name")) or display_of(
            child(entity, "representedOrganization")
        )
        if name:
            participants.append({"individual": {"display": name}})
    if participants:
        res["participant"] = participants
    period = ctx.period(child(enc, "effectiveTime"))
    point = ctx.ts_value(child(enc, "effectiveTime"))
    if period:
        res["period"] = period
    elif point:
        res["period"] = {"start": point}
    reasons = _reasons(ctx, enc)
    if reasons:
        res["reasonCode"] = reasons
    locations = []
    for part in children(enc, "participant"):
        if (attr(part, "typeCode") or "").upper() != "LOC":
            continue
        role = child(part, "participantRole")
        name = display_of(child(role, "playingEntity")) or concept_text(
            ctx.concept(child(role, "code"))
        )
        if name:
            locations.append({"location": {"display": name}})
    if locations:
        res["location"] = locations
    discharge = child(enc, "dischargeDispositionCode") or child(
        enc, "dischargeDispositionCode", "urn:hl7-org:sdtc"
    )
    disposition = ctx.concept(discharge)
    if disposition:
        res["hospitalization"] = {"dischargeDisposition": disposition}
    return res


def _encounter_class(type_cc: dict | None) -> str:
    """Pick a v3 ActCode class from the encounter type code, defaulting to ambulatory."""
    if not type_cc:
        return "AMB"
    for coding in type_cc.get("coding", []):
        code = coding.get("code")
        if code in _SNOMED_CLASS:
            return _SNOMED_CLASS[code]
        if coding.get("system") == V3_ACT_CODE and code in _CLASS_DISPLAY:
            return code
    label = (concept_text(type_cc) or "").lower()
    if "emergency" in label:
        return "EMER"
    if "inpatient" in label or "hospital admission" in label or "admission" in label:
        return "IMP"
    if "telehealth" in label or "telemedicine" in label or "virtual" in label:
        return "VR"
    if "home visit" in label or "home health" in label:
        return "HH"
    return "AMB"


def _reasons(ctx: Context, enc: etree._Element) -> list[dict]:
    out: list[dict] = []
    for rel in children(enc, "entryRelationship"):
        if (attr(rel, "typeCode") or "").upper() != "RSON":
            continue
        obs = child(rel, "observation")
        cc = ctx.concept(child(obs, "value")) or ctx.concept(child(obs, "code"))
        if cc:
            out.append(cc)
    return out
