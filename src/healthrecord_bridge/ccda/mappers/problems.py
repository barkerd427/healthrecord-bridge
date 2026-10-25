"""Problems section (LOINC 11450-4) to ``Condition``."""

from __future__ import annotations

from lxml import etree

from ..codes import simple_concept
from ..context import Context, negated, status_code
from ..document import Section
from ..report import SectionReport, SkippedEntry
from ..xml import attr, child, find, local_name
from ._shared import CONDITION_CATEGORY, CONDITION_CLINICAL, entries, has_template, related

PROBLEM_OBSERVATION = "2.16.840.1.113883.10.20.22.4.4"
PROBLEM_STATUS = "2.16.840.1.113883.10.20.22.4.6"
_STATUS_VALUES = {
    "55561003": "active",
    "73425007": "inactive",
    "413322009": "resolved",
    "7087005": "inactive",  # intermittent
    "255227004": "recurrence",
    "246455001": "recurrence",  # recurrence
    "277022003": "remission",
}
_VERIFICATION = "http://terminology.hl7.org/CodeSystem/condition-ver-status"


def map_problems(ctx: Context, section: Section, sr: SectionReport) -> list[dict]:
    out: list[dict] = []
    for ordinal, _entry, stmt in entries(section.element):
        if stmt is None:
            sr.skipped.append(SkippedEntry("entry has no clinical statement", ordinal))
            continue
        observations = _problem_observations(stmt)
        if not observations:
            sr.skipped.append(SkippedEntry("no problem observation found", ordinal))
            continue
        for sub, obs in enumerate(observations):
            res = _condition(ctx, stmt, obs, section.code, ordinal, sub)
            if res is None:
                sr.skipped.append(SkippedEntry("problem observation has no code", ordinal))
                continue
            out.append(res)
    return out


def _problem_observations(stmt: etree._Element) -> list[etree._Element]:
    if local_name(stmt) == "observation":
        return [stmt]
    subj = [o for o in related(stmt, "SUBJ", "observation") if not has_template(o, PROBLEM_STATUS)]
    if subj:
        return subj
    return [o for o in related(stmt, None, "observation") if has_template(o, PROBLEM_OBSERVATION)]


def _condition(
    ctx: Context,
    act: etree._Element,
    obs: etree._Element,
    section_code: str | None,
    ordinal: int,
    sub: int,
) -> dict | None:
    code = ctx.concept(child(obs, "value"))
    if code is None:
        text = ctx.entry_text(obs) or ctx.entry_text(act)
        if not text:
            return None
        code = {"text": text}
    id_source = obs if ctx.ids_of(obs) else act
    res = ctx.new_resource("Condition", id_source, section_code, ordinal, sub)
    res["subject"] = ctx.patient_ref
    clinical = _clinical_status(act, obs)
    if clinical:
        res["clinicalStatus"] = simple_concept(CONDITION_CLINICAL, clinical, clinical.capitalize())
    if negated(obs):
        res["verificationStatus"] = simple_concept(_VERIFICATION, "refuted", "Refuted")
    res["category"] = [simple_concept(CONDITION_CATEGORY, "problem-list-item", "Problem List Item")]
    res["code"] = code
    eff = child(obs, "effectiveTime")
    if eff is None or attr(eff, "nullFlavor"):
        eff = child(act, "effectiveTime")
    onset = ctx.ts_value(find(eff, "c:low")) or ctx.ts_value(eff)
    abatement = ctx.ts_value(find(eff, "c:high"))
    if onset:
        res["onsetDateTime"] = onset
    if abatement:
        res["abatementDateTime"] = abatement
    recorded = ctx.ts_value(find(obs, "c:author/c:time")) or ctx.ts_value(
        find(act, "c:author/c:time")
    )
    if recorded:
        res["recordedDate"] = recorded
    return res


def _clinical_status(act: etree._Element, obs: etree._Element) -> str | None:
    for st in related(obs, "REFR", "observation") + related(act, "REFR", "observation"):
        if has_template(st, PROBLEM_STATUS):
            code = attr(child(st, "value"), "code")
            if code in _STATUS_VALUES:
                return _STATUS_VALUES[code]
    eff = child(obs, "effectiveTime")
    if eff is None or attr(eff, "nullFlavor"):
        eff = child(act, "effectiveTime")
    if attr(find(eff, "c:high"), "value"):
        return "resolved"
    sc = status_code(act) or status_code(obs)
    if sc in {"active", "completed", "new"}:
        return "active"
    if sc in {"aborted", "cancelled"}:
        return "resolved"
    if sc == "suspended":
        return "inactive"
    return None
