"""Vital Signs section (LOINC 8716-3) to one ``Observation`` per organizer component.

Organizer grouping (a panel Observation with ``hasMember``) is not emitted in
this version; each vital sign stands alone with category ``vital-signs``.
"""

from __future__ import annotations

from ..context import Context
from ..document import Section
from ..report import SectionReport, SkippedEntry
from ..xml import children, local_name
from ._observation import build_observation
from ._shared import entries


def map_vitals(ctx: Context, section: Section, sr: SectionReport) -> list[dict]:
    out: list[dict] = []
    for ordinal, _entry, stmt in entries(section.element):
        if stmt is None:
            sr.skipped.append(SkippedEntry("entry has no clinical statement", ordinal))
            continue
        if local_name(stmt) == "observation":
            components = [stmt]
        elif local_name(stmt) == "organizer":
            components = [
                o for c in children(stmt, "component") for o in children(c, "observation")
            ]
        else:
            sr.skipped.append(SkippedEntry(f"unsupported statement {local_name(stmt)}", ordinal))
            continue
        produced = 0
        for sub, obs in enumerate(components):
            res = build_observation(ctx, obs, "vital-signs", section.code, ordinal, sub)
            if res is not None:
                out.append(res)
                produced += 1
        if components and produced == 0:
            sr.skipped.append(SkippedEntry("organizer has no codable observations", ordinal))
        elif not components:
            sr.skipped.append(SkippedEntry("organizer has no components", ordinal))
    return out
