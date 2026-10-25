"""Social History section (LOINC 29762-2) to ``Observation`` (category social-history).

Smoking status (LOINC 72166-2) is recognised explicitly: its value is coerced to
a SNOMED ``valueCodeableConcept`` even when the source writes it as text such
as ``SNOMED-CT 266919005 Never smoker``. Other entries become generic coded
observations.
"""

from __future__ import annotations

from ..context import Context
from ..document import Section
from ..report import SectionReport, SkippedEntry
from ..xml import children, local_name
from ._observation import build_observation
from ._shared import entries


def map_social_history(ctx: Context, section: Section, sr: SectionReport) -> list[dict]:
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
            res = build_observation(ctx, obs, "social-history", section.code, ordinal, sub)
            if res is not None:
                out.append(res)
                produced += 1
        if produced == 0:
            sr.skipped.append(SkippedEntry("observation has no code", ordinal))
    return out
