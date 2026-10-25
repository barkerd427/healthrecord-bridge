"""Medications section (LOINC 10160-0) to ``MedicationStatement`` / ``MedicationRequest``.

A ``substanceAdministration`` in event mood (``EVN``) with a completed or active
status is something the patient took or takes: ``MedicationStatement``. Anything
else (intent or request moods, other statuses) is an order: ``MedicationRequest``.
"""

from __future__ import annotations

from lxml import etree

from ..codes import concept_text, quantity
from ..context import Context, mood, negated, status_code
from ..document import Section
from ..report import SectionReport, SkippedEntry
from ..xml import attr, child, children, find, local_name, xsi_type
from ._shared import entries

_STATEMENT_STATUS = {
    "completed": "completed",
    "active": "active",
}
_REQUEST_STATUS = {
    "active": "active",
    "completed": "completed",
    "aborted": "stopped",
    "cancelled": "cancelled",
    "suspended": "on-hold",
    "nullified": "entered-in-error",
    "new": "draft",
    "held": "on-hold",
}
_REQUEST_INTENT = {"INT": "plan", "RQO": "order", "PRP": "proposal", "PRMS": "plan"}
_PERIOD_UNITS = {"s", "min", "h", "d", "wk", "mo", "a"}


def map_medications(ctx: Context, section: Section, sr: SectionReport) -> list[dict]:
    out: list[dict] = []
    for ordinal, _entry, stmt in entries(section.element):
        if stmt is None:
            sr.skipped.append(SkippedEntry("entry has no clinical statement", ordinal))
            continue
        sa = stmt if local_name(stmt) == "substanceAdministration" else None
        if sa is None:
            # A bare supply or act at entry level: look one level down for the administration.
            nested = find(stmt, "c:entryRelationship/c:substanceAdministration")
            if nested is None:
                sr.skipped.append(
                    SkippedEntry(f"{local_name(stmt)} without substanceAdministration", ordinal)
                )
                continue
            sa = nested
        res = _medication(ctx, sa, section.code, ordinal)
        if res is None:
            sr.skipped.append(SkippedEntry("no medication code or name", ordinal))
            continue
        out.append(res)
    return out


def _medication(
    ctx: Context, sa: etree._Element, section_code: str | None, ordinal: int
) -> dict | None:
    material = find(sa, "c:consumable/c:manufacturedProduct/c:manufacturedMaterial")
    med = ctx.concept(child(material, "code"))
    name = _material_name(material)
    if med is None:
        text = name or ctx.entry_text(sa)
        if not text:
            return None
        med = {"text": text}
    elif name and not concept_text(med):
        med["text"] = name

    sc = status_code(sa)
    is_statement = mood(sa) == "EVN" and sc in _STATEMENT_STATUS
    rtype = "MedicationStatement" if is_statement else "MedicationRequest"
    res = ctx.new_resource(rtype, sa, section_code, ordinal)
    res["subject"] = ctx.patient_ref
    res["medicationCodeableConcept"] = med

    eff_el = _effective_time(sa)
    if is_statement:
        res["status"] = "not-taken" if negated(sa) else _STATEMENT_STATUS[sc or "active"]
        ctx.set_effective(res, eff_el, "effectiveDateTime", "effectivePeriod")
    else:
        res["status"] = _REQUEST_STATUS.get(sc or "", "unknown")
        res["intent"] = _REQUEST_INTENT.get(mood(sa), "order")
        if negated(sa):
            res["doNotPerform"] = True
        author_time = find(sa, "c:author/c:time")
        authored = ctx.ts_value(author_time)
        if authored:
            res["authoredOn"] = authored
    dosage = _dosage(ctx, sa, eff_el)
    if dosage:
        if is_statement:
            res["dosage"] = [dosage]
        else:
            res["dosageInstruction"] = [dosage]
            period = ctx.period(eff_el) if eff_el is not None else None
            if period:
                dosage.setdefault("timing", {}).setdefault("repeat", {})["boundsPeriod"] = period
    reason = _reason(ctx, sa)
    if reason:
        res["reasonCode"] = [reason]
    return res


def _material_name(material: etree._Element | None) -> str | None:
    n = child(material, "name")
    if n is not None and n.text and n.text.strip():
        return n.text.strip()
    return None


def _effective_time(sa: etree._Element) -> etree._Element | None:
    """The IVL_TS effectiveTime (the one with low/high or a value), not the PIVL frequency."""
    for et in children(sa, "effectiveTime"):
        if xsi_type(et) in {"PIVL_TS", "EIVL_TS", "SXPR_TS"}:
            continue
        return et
    return None


def _frequency(sa: etree._Element) -> etree._Element | None:
    for et in children(sa, "effectiveTime"):
        if xsi_type(et) == "PIVL_TS":
            return et
    return None


def _dosage(ctx: Context, sa: etree._Element, eff_el: etree._Element | None) -> dict | None:
    dosage: dict = {}
    text = ctx.entry_text(sa)
    if text:
        dosage["text"] = text
    route = ctx.concept(child(sa, "routeCode"))
    if route:
        dosage["route"] = route
    dose = quantity(child(sa, "doseQuantity"))
    if dose:
        dosage["doseAndRate"] = [{"doseQuantity": dose}]
    rate = quantity(child(sa, "rateQuantity"))
    if rate:
        dosage.setdefault("doseAndRate", [{}])[0]["rateQuantity"] = rate
    freq = _frequency(sa)
    if freq is not None:
        repeat: dict = {}
        period = child(freq, "period")
        pval = attr(period, "value")
        punit = attr(period, "unit")
        if pval and punit in _PERIOD_UNITS:
            try:
                repeat["period"] = float(pval) if "." in pval else int(pval)
                repeat["periodUnit"] = punit
            except ValueError:
                pass
        if repeat:
            dosage["timing"] = {"repeat": repeat}
    site = ctx.concept(child(sa, "approachSiteCode"))
    if site:
        dosage["site"] = site
    prn = child(sa, "precondition")
    if prn is not None:
        dosage["asNeededBoolean"] = True
    return dosage or None


def _reason(ctx: Context, sa: etree._Element) -> dict | None:
    for rel in children(sa, "entryRelationship"):
        if (attr(rel, "typeCode") or "").upper() != "RSON":
            continue
        obs = child(rel, "observation")
        cc = ctx.concept(child(obs, "value"))
        if cc:
            return cc
    return None
