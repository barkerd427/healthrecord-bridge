"""Build FHIR ``Observation`` resources from CDA observation elements.

Shared by the Vital Signs, Results and Social History mappers.
"""

from __future__ import annotations

import re

from lxml import etree

from ..codes import SNOMED, concept_text, quantity, simple_concept
from ..context import Context, status_code
from ..xml import attr, child, children, text_of, xsi_type
from ._shared import observation_category

SMOKING_STATUS_LOINC = "72166-2"
_SMOKING_DISPLAY = {
    "449868002": "Current every day smoker",
    "428041000124106": "Current some day smoker",
    "8517006": "Former smoker",
    "266919005": "Never smoker",
    "77176002": "Smoker, current status unknown",
    "266927001": "Unknown if ever smoked",
    "428071000124103": "Current Heavy tobacco smoker",
    "428061000124105": "Current Light tobacco smoker",
}
_SNOMED_IN_TEXT = re.compile(r"^SNOMED-?\s?CT\s+(\d{6,18})\s*(.*)$", re.IGNORECASE)

_STATUS = {
    "completed": "final",
    "active": "preliminary",
    "aborted": "cancelled",
    "cancelled": "cancelled",
    "nullified": "entered-in-error",
    "held": "registered",
    "new": "registered",
}
_INTERPRETATION = "http://terminology.hl7.org/CodeSystem/v3-ObservationInterpretation"


def build_observation(
    ctx: Context,
    obs: etree._Element,
    category_code: str,
    section_code: str | None,
    *fallback_parts: str | int | None,
) -> dict | None:
    """Return an Observation or ``None`` when the element has no code at all."""
    code = ctx.concept(child(obs, "code"))
    if code is None:
        text = ctx.entry_text(obs)
        if not text:
            return None
        code = {"text": text}
    cat = category_code
    if _loinc_code(code) == SMOKING_STATUS_LOINC:
        cat = "social-history"
    res = ctx.new_resource("Observation", obs, section_code, *fallback_parts)
    res["status"] = _STATUS.get(status_code(obs) or "completed", "final")
    res["category"] = [observation_category(cat)]
    res["code"] = code
    res["subject"] = ctx.patient_ref
    ctx.set_effective(res, child(obs, "effectiveTime"), "effectiveDateTime", "effectivePeriod")
    issued_el = child(obs, "author")
    issued = ctx.parse(attr(child(issued_el, "time"), "value")) if issued_el is not None else None
    if issued and issued.has_time and not issued.truncated:
        res["issued"] = issued.value
    _set_value(ctx, res, obs, smoking=cat == "social-history")
    interp = [cc for ic in children(obs, "interpretationCode") if (cc := _interpretation(ctx, ic))]
    if interp:
        res["interpretation"] = interp
    ranges = _reference_ranges(ctx, obs)
    if ranges:
        res["referenceRange"] = ranges
    method = ctx.concept(child(obs, "methodCode"))
    if method:
        res["method"] = method
    site = ctx.concept(child(obs, "targetSiteCode"))
    if site:
        res["bodySite"] = site
    return res


def _loinc_code(cc: dict) -> str | None:
    for c in cc.get("coding", []):
        if c.get("system") == "http://loinc.org":
            return c.get("code")
    return None


def _set_value(ctx: Context, res: dict, obs: etree._Element, smoking: bool) -> None:
    for value in children(obs, "value"):
        if attr(value, "nullFlavor"):
            res["dataAbsentReason"] = simple_concept(
                "http://terminology.hl7.org/CodeSystem/data-absent-reason", "unknown", "Unknown"
            )
            return
        kind = xsi_type(value) or "ST"
        if kind == "PQ":
            q = quantity(value)
            if q is not None:
                res["valueQuantity"] = q
                return
        elif kind in {"CD", "CE", "CO", "CV"}:
            cc = ctx.concept(value)
            if cc:
                if smoking:
                    _fill_smoking_display(cc)
                res["valueCodeableConcept"] = cc
                return
        elif kind == "INT":
            raw = attr(value, "value")
            if raw and raw.lstrip("-").isdigit():
                res["valueInteger"] = int(raw)
                return
        elif kind == "REAL":
            raw = attr(value, "value")
            try:
                res["valueQuantity"] = {"value": float(raw or "")}
                return
            except ValueError:
                pass
        elif kind == "BL":
            raw = (attr(value, "value") or "").lower()
            if raw in {"true", "false"}:
                res["valueBoolean"] = raw == "true"
                return
        elif kind == "TS":
            ts = ctx.ts(attr(value, "value"))
            if ts:
                res["valueDateTime"] = ts
                return
        elif kind in {"IVL_PQ", "IVL_INT", "IVL_REAL"}:
            rng = _range(value)
            if rng:
                res["valueRange"] = rng
                return
        elif kind == "RTO" or kind.startswith("RTO_"):
            num = quantity(child(value, "numerator"))
            den = quantity(child(value, "denominator"))
            if num and den:
                res["valueRatio"] = {"numerator": num, "denominator": den}
                return
        text = text_of(value) or attr(value, "value")
        if text:
            if smoking:
                m = _SNOMED_IN_TEXT.match(text)
                if m:
                    code, display = (
                        m.group(1),
                        m.group(2).strip() or _SMOKING_DISPLAY.get(m.group(1)),
                    )
                    res["valueCodeableConcept"] = simple_concept(SNOMED, code, display)
                    return
            res["valueString"] = text
            return


def _fill_smoking_display(cc: dict) -> None:
    for c in cc.get("coding", []):
        if c.get("system") == SNOMED and "display" not in c and c.get("code") in _SMOKING_DISPLAY:
            c["display"] = _SMOKING_DISPLAY[c["code"]]


def _range(el: etree._Element) -> dict | None:
    out: dict = {}
    low = quantity(child(el, "low"))
    high = quantity(child(el, "high"))
    if low:
        out["low"] = low
    if high:
        out["high"] = high
    return out or None


def _reference_ranges(ctx: Context, obs: etree._Element) -> list[dict]:
    out: list[dict] = []
    for rr in children(obs, "referenceRange"):
        orange = child(rr, "observationRange")
        if orange is None:
            continue
        entry: dict = {}
        value = child(orange, "value")
        rng = _range(value) if value is not None else None
        if rng:
            entry.update(rng)
        text = ctx.entry_text(orange)
        if text:
            entry["text"] = text
        interp = ctx.concept(child(orange, "interpretationCode"))
        if interp and "low" not in entry and "high" not in entry and "text" not in entry:
            entry["text"] = concept_text(interp) or ""
        if entry:
            out.append(entry)
    return out


def _interpretation(ctx: Context, el: etree._Element) -> dict | None:
    cc = ctx.concept(el)
    if cc is None:
        return None
    for c in cc.get("coding", []):
        if c.get("system", "").startswith("urn:oid:2.16.840.1.113883.5.83") or "system" not in c:
            c["system"] = _INTERPRETATION
    return cc
