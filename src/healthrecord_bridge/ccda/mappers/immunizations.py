"""Immunizations section (LOINC 11369-6) to ``Immunization``."""

from __future__ import annotations

from lxml import etree

from ..codes import concept_text, quantity
from ..context import Context, negated, status_code
from ..document import Section, person_name
from ..report import SectionReport, SkippedEntry
from ..xml import child, child_text, children, find, local_name
from ._shared import display_of, entries


def map_immunizations(ctx: Context, section: Section, sr: SectionReport) -> list[dict]:
    out: list[dict] = []
    for ordinal, _entry, stmt in entries(section.element):
        if stmt is None:
            sr.skipped.append(SkippedEntry("entry has no clinical statement", ordinal))
            continue
        if local_name(stmt) != "substanceAdministration":
            sr.skipped.append(SkippedEntry(f"unsupported statement {local_name(stmt)}", ordinal))
            continue
        res = _immunization(ctx, stmt, section.code, ordinal)
        if res is None:
            sr.skipped.append(SkippedEntry("no vaccine code or name", ordinal))
            continue
        out.append(res)
    return out


def _immunization(
    ctx: Context, sa: etree._Element, section_code: str | None, ordinal: int
) -> dict | None:
    material = find(sa, "c:consumable/c:manufacturedProduct/c:manufacturedMaterial")
    vaccine = ctx.concept(child(material, "code"))
    name = child_text(material, "name")
    if vaccine is None:
        text = name or ctx.entry_text(sa)
        if not text:
            return None
        vaccine = {"text": text}
    elif name and not concept_text(vaccine):
        vaccine["text"] = name
    res = ctx.new_resource("Immunization", sa, section_code, ordinal)
    sc = status_code(sa)
    if negated(sa) or sc in {"cancelled", "aborted"}:
        res["status"] = "not-done"
    elif sc == "nullified":
        res["status"] = "entered-in-error"
    else:
        res["status"] = "completed"
    reason = _refusal_reason(ctx, sa)
    if reason and res["status"] == "not-done":
        res["statusReason"] = reason
    res["vaccineCode"] = vaccine
    res["patient"] = ctx.patient_ref
    eff = child(sa, "effectiveTime")
    when = ctx.ts_value(eff) or ctx.ts_value(find(eff, "c:low"))
    if when:
        res["occurrenceDateTime"] = when
    else:
        res["occurrenceString"] = "unknown"
    res["primarySource"] = True
    lot = child_text(material, "lotNumberText")
    if lot:
        res["lotNumber"] = lot
    manufacturer = display_of(
        find(sa, "c:consumable/c:manufacturedProduct/c:manufacturerOrganization")
    )
    if manufacturer:
        res["manufacturer"] = {"display": manufacturer}
    route = ctx.concept(child(sa, "routeCode"))
    if route:
        res["route"] = route
    site = ctx.concept(child(sa, "approachSiteCode"))
    if site:
        res["site"] = site
    dose = quantity(child(sa, "doseQuantity"))
    if dose:
        res["doseQuantity"] = dose
    performers = []
    for perf in children(sa, "performer"):
        entity = child(perf, "assignedEntity")
        who = person_name(find(entity, "c:assignedPerson/c:name")) or display_of(
            child(entity, "representedOrganization")
        )
        if who:
            performers.append({"actor": {"display": who}})
    if performers:
        res["performer"] = performers
    return res


def _refusal_reason(ctx: Context, sa: etree._Element) -> dict | None:
    for rel in children(sa, "entryRelationship"):
        if (rel.get("typeCode") or "").upper() != "RSON":
            continue
        obs = child(rel, "observation")
        cc = ctx.concept(child(obs, "code")) if obs is not None else None
        if cc:
            return cc
    return None
