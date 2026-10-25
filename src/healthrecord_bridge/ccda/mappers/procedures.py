"""Procedures / Surgeries section (LOINC 47519-4) to ``Procedure``."""

from __future__ import annotations

from lxml import etree

from ..context import Context, mood, negated, status_code
from ..document import Section
from ..report import SectionReport, SkippedEntry
from ..xml import child, children, find, local_name
from ._shared import display_of, entries

_STATUS = {
    "completed": "completed",
    "active": "in-progress",
    "aborted": "stopped",
    "cancelled": "not-done",
    "suspended": "on-hold",
    "nullified": "entered-in-error",
    "new": "preparation",
}


def map_procedures(ctx: Context, section: Section, sr: SectionReport) -> list[dict]:
    out: list[dict] = []
    for ordinal, _entry, stmt in entries(section.element):
        if stmt is None:
            sr.skipped.append(SkippedEntry("entry has no clinical statement", ordinal))
            continue
        if local_name(stmt) not in {"procedure", "act", "observation"}:
            sr.skipped.append(SkippedEntry(f"unsupported statement {local_name(stmt)}", ordinal))
            continue
        res = _procedure(ctx, stmt, section.code, ordinal)
        if res is None:
            sr.skipped.append(SkippedEntry("procedure has no code", ordinal))
            continue
        out.append(res)
    return out


def _procedure(
    ctx: Context, el: etree._Element, section_code: str | None, ordinal: int
) -> dict | None:
    code = ctx.concept(child(el, "code"))
    if code is None:
        text = ctx.entry_text(el)
        if not text:
            return None
        code = {"text": text}
    res = ctx.new_resource("Procedure", el, section_code, ordinal)
    res["subject"] = ctx.patient_ref
    if negated(el):
        res["status"] = "not-done"
    elif mood(el) != "EVN":
        res["status"] = "preparation"
    else:
        res["status"] = _STATUS.get(status_code(el) or "", "unknown")
    res["code"] = code
    ctx.set_effective(res, child(el, "effectiveTime"), "performedDateTime", "performedPeriod")
    sites = [cc for s in children(el, "targetSiteCode") if (cc := ctx.concept(s))]
    if sites:
        res["bodySite"] = sites
    performers = []
    for perf in children(el, "performer"):
        entity = child(perf, "assignedEntity")
        person = _person(entity)
        org = display_of(child(entity, "representedOrganization"))
        actor = person or org
        if actor:
            p: dict = {"actor": {"display": actor}}
            if person and org:
                p["onBehalfOf"] = {"display": org}
            performers.append(p)
    if performers:
        res["performer"] = performers
    reason = _reason(ctx, el)
    if reason:
        res["reasonCode"] = [reason]
    return res


def _person(entity: etree._Element | None) -> str | None:
    from ..document import person_name

    return person_name(find(entity, "c:assignedPerson/c:name"))


def _reason(ctx: Context, el: etree._Element) -> dict | None:
    for rel in children(el, "entryRelationship"):
        if (rel.get("typeCode") or "").upper() != "RSON":
            continue
        obs = child(rel, "observation")
        cc = ctx.concept(child(obs, "value"))
        if cc:
            return cc
    return None
