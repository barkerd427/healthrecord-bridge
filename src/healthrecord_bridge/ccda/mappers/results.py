"""Results section (LOINC 30954-2) to ``DiagnosticReport`` + ``Observation`` per component."""

from __future__ import annotations

from lxml import etree

from ..codes import simple_concept
from ..context import Context, status_code
from ..document import Section, person_name
from ..report import SectionReport, SkippedEntry
from ..xml import child, children, find, local_name
from ._observation import build_observation
from ._shared import V2_0074, display_of, entries

_REPORT_STATUS = {
    "completed": "final",
    "active": "partial",
    "aborted": "cancelled",
    "cancelled": "cancelled",
    "nullified": "entered-in-error",
}


def map_results(ctx: Context, section: Section, sr: SectionReport) -> list[dict]:
    out: list[dict] = []
    for ordinal, _entry, stmt in entries(section.element):
        if stmt is None:
            sr.skipped.append(SkippedEntry("entry has no clinical statement", ordinal))
            continue
        if local_name(stmt) == "observation":
            obs = build_observation(ctx, stmt, "laboratory", section.code, ordinal, 0)
            if obs is None:
                sr.skipped.append(SkippedEntry("observation has no code", ordinal))
            else:
                out.append(obs)
            continue
        if local_name(stmt) != "organizer":
            sr.skipped.append(SkippedEntry(f"unsupported statement {local_name(stmt)}", ordinal))
            continue
        observations: list[dict] = []
        comps = [o for c in children(stmt, "component") for o in children(c, "observation")]
        for sub, comp in enumerate(comps):
            obs = build_observation(ctx, comp, "laboratory", section.code, ordinal, sub)
            if obs is not None:
                observations.append(obs)
        if not observations:
            sr.skipped.append(SkippedEntry("organizer has no codable observations", ordinal))
            continue
        report = _report(ctx, stmt, comps, observations, section.code, ordinal)
        out.append(report)
        out.extend(observations)
    return out


def _report(
    ctx: Context,
    org: etree._Element,
    comps: list[etree._Element],
    observations: list[dict],
    section_code: str | None,
    ordinal: int,
) -> dict:
    res = ctx.new_resource("DiagnosticReport", org, section_code, ordinal)
    res["status"] = _REPORT_STATUS.get(status_code(org) or "completed", "final")
    res["category"] = [simple_concept(V2_0074, "LAB", "Laboratory")]
    code = ctx.concept(child(org, "code"))
    if code is None:
        # Many exports leave the organizer code null; the narrative row the first
        # component points at usually names the panel.
        text = next((t for c in comps if (t := ctx.entry_text(c))), None)
        code = {"text": text or "Laboratory results"}
    res["code"] = code
    res["subject"] = ctx.patient_ref
    ctx.set_effective(res, child(org, "effectiveTime"), "effectiveDateTime", "effectivePeriod")
    if "effectiveDateTime" not in res and "effectivePeriod" not in res:
        times = sorted(o["effectiveDateTime"] for o in observations if "effectiveDateTime" in o)
        if times:
            res["effectiveDateTime"] = times[0]
    performers = []
    for perf in children(org, "performer"):
        entity = child(perf, "assignedEntity")
        name = display_of(child(entity, "representedOrganization")) or person_name(
            find(entity, "c:assignedPerson/c:name")
        )
        if name:
            performers.append({"display": name})
    if performers:
        res["performer"] = performers
    res["result"] = [ctx.reference(o) for o in observations]
    return res
