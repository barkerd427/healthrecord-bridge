"""Allergies section (LOINC 48765-2) to ``AllergyIntolerance``."""

from __future__ import annotations

from lxml import etree

from ..codes import SNOMED, concept_text, simple_concept
from ..context import Context, negated, status_code
from ..document import Section
from ..report import SectionReport, SkippedEntry
from ..xml import attr, child, find, local_name
from ._shared import ALLERGY_CLINICAL, ALLERGY_VERIFICATION, entries, has_template, related

ALLERGY_OBSERVATION = "2.16.840.1.113883.10.20.22.4.7"
REACTION_OBSERVATION = "2.16.840.1.113883.10.20.22.4.9"
SEVERITY_OBSERVATION = "2.16.840.1.113883.10.20.22.4.8"
STATUS_OBSERVATION = "2.16.840.1.113883.10.20.22.4.28"
CRITICALITY_OBSERVATION = "2.16.840.1.113883.10.20.22.4.145"

# SNOMED "allergy type" values used in C-CDA Allergy Observation/value
_TYPE_BY_VALUE: dict[str, tuple[str | None, str | None]] = {
    "419199007": ("allergy", None),  # Allergy to substance
    "416098002": ("allergy", "medication"),  # Drug allergy
    "414285001": ("allergy", "food"),  # Food allergy
    "232347008": ("allergy", "environment"),  # Dander (animal) allergy
    "59037007": ("intolerance", "medication"),  # Drug intolerance
    "235719002": ("intolerance", "food"),  # Food intolerance
    "420134006": (None, None),  # Propensity to adverse reactions
    "418038007": (None, None),  # Propensity to adverse reactions to substance
    "419511003": (None, "medication"),  # Propensity to adverse reactions to drug
    "418471000": (None, "food"),  # Propensity to adverse reactions to food
}

_SEVERITY: dict[str, str] = {
    "255604002": "mild",
    "371923003": "mild",  # mild to moderate
    "6736007": "moderate",
    "371924009": "severe",  # moderate to severe
    "24484000": "severe",
    "399166001": "severe",  # fatal
}

_CRITICALITY = {"CRITL": "low", "CRITH": "high", "CRITU": "unable-to-assess"}

_STATUS_VALUES = {"55561003": "active", "73425007": "inactive", "413322009": "resolved"}


def map_allergies(ctx: Context, section: Section, sr: SectionReport) -> list[dict]:
    out: list[dict] = []
    for ordinal, _entry, stmt in entries(section.element):
        if stmt is None:
            sr.skipped.append(SkippedEntry("entry has no clinical statement", ordinal))
            continue
        observations = _allergy_observations(stmt)
        if not observations:
            sr.skipped.append(SkippedEntry("no allergy observation found", ordinal))
            continue
        for sub, obs in enumerate(observations):
            res = _allergy(ctx, stmt, obs, section.code, ordinal, sub)
            if res is None:
                sr.skipped.append(
                    SkippedEntry("allergy observation has no substance or code", ordinal)
                )
                continue
            out.append(res)
    return out


def _allergy_observations(stmt: etree._Element) -> list[etree._Element]:
    if local_name(stmt) == "observation":
        return [stmt]
    return related(stmt, "SUBJ", "observation") or related(stmt, None, "observation")


def _allergy(
    ctx: Context,
    act: etree._Element,
    obs: etree._Element,
    section_code: str | None,
    ordinal: int,
    sub: int,
) -> dict | None:
    substance_el = find(obs, "c:participant/c:participantRole/c:playingEntity/c:code")
    code = ctx.concept(substance_el)
    value_el = child(obs, "value")
    value = ctx.concept(value_el)
    if code is None:
        # No substance: fall back to the allergy type itself ("Allergy to substance")
        code = value
    if code is None:
        text = ctx.entry_text(obs) or ctx.entry_text(act)
        if not text:
            return None
        code = {"text": text}
    id_source = obs if ctx.ids_of(obs) else act
    res = ctx.new_resource("AllergyIntolerance", id_source, section_code, ordinal, sub)
    res["patient"] = ctx.patient_ref

    clinical = _clinical_status(act, obs)
    if clinical:
        res["clinicalStatus"] = simple_concept(ALLERGY_CLINICAL, clinical, clinical.capitalize())
    if negated(obs):
        res["verificationStatus"] = simple_concept(ALLERGY_VERIFICATION, "refuted", "Refuted")
    else:
        res["verificationStatus"] = simple_concept(ALLERGY_VERIFICATION, "confirmed", "Confirmed")

    kind, cat = _type_and_category(value_el)
    if kind:
        res["type"] = kind
    if cat:
        res["category"] = [cat]
    crit = _criticality(obs)
    if crit:
        res["criticality"] = crit
    res["code"] = code
    ctx.set_effective(res, child(obs, "effectiveTime"), "onsetDateTime", "onsetPeriod")
    if "onsetDateTime" not in res and "onsetPeriod" not in res:
        ctx.set_effective(res, child(act, "effectiveTime"), "onsetDateTime", "onsetPeriod")
    if "onsetPeriod" in res:
        # FHIR allows onsetPeriod, but importers expect onsetDateTime; keep the start.
        start = res.pop("onsetPeriod").get("start")
        if start:
            res["onsetDateTime"] = start
    author_time = find(obs, "c:author/c:time")
    recorded = ctx.ts_value(author_time)
    if recorded:
        res["recordedDate"] = recorded
    reactions = _reactions(ctx, obs)
    if reactions:
        res["reaction"] = reactions
    note = ctx.entry_text(obs)
    if note and note != concept_text(code):
        res["note"] = [{"text": note}]
    return res


def _clinical_status(act: etree._Element, obs: etree._Element) -> str | None:
    for st in related(obs, "REFR", "observation"):
        if has_template(st, STATUS_OBSERVATION):
            code = attr(child(st, "value"), "code")
            if code in _STATUS_VALUES:
                return _STATUS_VALUES[code]
    sc = status_code(act) or status_code(obs)
    if sc in {"active", "new"}:
        return "active"
    if sc in {"completed", "aborted", "cancelled", "nullified"}:
        # A completed concern act means the allergy is no longer being tracked.
        if attr(find(act, "c:effectiveTime/c:high"), "value"):
            return "resolved"
        return "inactive"
    if sc == "suspended":
        return "inactive"
    return None


def _type_and_category(value_el: etree._Element | None) -> tuple[str | None, str | None]:
    code = attr(value_el, "code")
    if code and code in _TYPE_BY_VALUE:
        return _TYPE_BY_VALUE[code]
    return (None, None)


def _criticality(obs: etree._Element) -> str | None:
    for st in related(obs, "SUBJ", "observation") + related(obs, "REFR", "observation"):
        if has_template(st, CRITICALITY_OBSERVATION):
            code = attr(child(st, "value"), "code")
            if code in _CRITICALITY:
                return _CRITICALITY[code]
    return None


def _severity(el: etree._Element) -> str | None:
    for st in related(el, "SUBJ", "observation"):
        if has_template(st, SEVERITY_OBSERVATION) or attr(child(st, "code"), "code") == "SEV":
            code = attr(child(st, "value"), "code")
            if code in _SEVERITY:
                return _SEVERITY[code]
    return None


def _reactions(ctx: Context, obs: etree._Element) -> list[dict]:
    out: list[dict] = []
    for st in related(obs, "MFST", "observation"):
        manifestation = ctx.concept(child(st, "value"))
        if manifestation is None:
            text = ctx.entry_text(st)
            if not text:
                continue
            manifestation = {"text": text}
        reaction: dict = {"manifestation": [manifestation]}
        sev = _severity(st)
        if sev:
            reaction["severity"] = sev
        onset = ctx.ts_value(find(st, "c:effectiveTime/c:low")) or ctx.ts_value(
            child(st, "effectiveTime")
        )
        if onset:
            reaction["onset"] = onset
        out.append(reaction)
    if not out:
        # Severity stated on the allergy itself with no reaction: surface it as a
        # reaction carrying the allergy type, so the severity is not lost.
        sev = _severity(obs)
        if sev:
            value = ctx.concept(child(obs, "value")) or simple_concept(
                SNOMED, "419199007", "Allergy to substance"
            )
            out.append({"manifestation": [value], "severity": sev})
    return out
