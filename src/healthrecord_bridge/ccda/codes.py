"""Code system mapping and ``CodeableConcept`` construction from CDA ``CD``/``CE`` elements."""

from __future__ import annotations

from collections.abc import Callable

from lxml import etree

from .xml import attr, child, children, text_of

OID_TO_URI: dict[str, str] = {
    "2.16.840.1.113883.6.96": "http://snomed.info/sct",
    "2.16.840.1.113883.6.1": "http://loinc.org",
    "2.16.840.1.113883.6.88": "http://www.nlm.nih.gov/research/umls/rxnorm",
    "2.16.840.1.113883.12.292": "http://hl7.org/fhir/sid/cvx",
    "2.16.840.1.113883.6.90": "http://hl7.org/fhir/sid/icd-10-cm",
    "2.16.840.1.113883.6.3": "http://hl7.org/fhir/sid/icd-10",
    "2.16.840.1.113883.6.103": "http://hl7.org/fhir/sid/icd-9-cm",
    "2.16.840.1.113883.6.104": "http://hl7.org/fhir/sid/icd-9-cm",
    "2.16.840.1.113883.6.12": "http://www.ama-assn.org/go/cpt",
    "2.16.840.1.113883.6.69": "http://hl7.org/fhir/sid/ndc",
    "2.16.840.1.113883.6.8": "http://unitsofmeasure.org",
    "2.16.840.1.113883.6.285": "https://www.cms.gov/Medicare/Coding/HCPCSReleaseCodeSets",
    "2.16.840.1.113883.6.14": "https://www.cms.gov/Medicare/Coding/HCPCSReleaseCodeSets",
    "2.16.840.1.113883.6.238": "urn:oid:2.16.840.1.113883.6.238",
    "2.16.840.1.113883.6.86": "http://www.whocc.no/atc",
    "2.16.840.1.113883.6.101": "http://nucc.org/provider-taxonomy",
    "2.16.840.1.113883.6.259": "http://terminology.hl7.org/CodeSystem/hsloc",
    "2.16.840.1.113883.6.13": "http://www.ada.org/cdt",
    "2.16.840.1.113883.3.26.1.1": "http://ncithesaurus-stage.nci.nih.gov",
    "2.16.840.1.113883.3.26.1.5": "http://ncimeta.nci.nih.gov",
    "2.16.840.1.113883.4.9": "http://fdasis.nlm.nih.gov",
    "2.16.840.1.113883.6.4": "http://www.cms.gov/Medicare/Coding/ICD10",
    "2.16.840.1.113883.4.642.4.1": "http://terminology.hl7.org/CodeSystem/v3-NullFlavor",
    "1.2.840.10008.2.16.4": "http://dicom.nema.org/resources/ontology/DCM",
    "1.2.840.10008.2.6.1": "urn:oid:1.2.840.10008.2.6.1",
    # HL7 v3 code systems
    "2.16.840.1.113883.5.1": "http://terminology.hl7.org/CodeSystem/v3-AdministrativeGender",
    "2.16.840.1.113883.5.4": "http://terminology.hl7.org/CodeSystem/v3-ActCode",
    "2.16.840.1.113883.5.6": "http://terminology.hl7.org/CodeSystem/v3-ActClass",
    "2.16.840.1.113883.5.8": "http://terminology.hl7.org/CodeSystem/v3-ActReason",
    "2.16.840.1.113883.5.2": "http://terminology.hl7.org/CodeSystem/v3-MaritalStatus",
    "2.16.840.1.113883.5.60": "http://terminology.hl7.org/CodeSystem/v3-LanguageAbilityMode",
    "2.16.840.1.113883.5.61": "http://terminology.hl7.org/CodeSystem/v3-LanguageAbilityProficiency",
    "2.16.840.1.113883.5.83": "http://terminology.hl7.org/CodeSystem/v3-ObservationInterpretation",
    "2.16.840.1.113883.5.88": "http://terminology.hl7.org/CodeSystem/v3-ParticipationFunction",
    "2.16.840.1.113883.5.90": "http://terminology.hl7.org/CodeSystem/v3-ParticipationType",
    "2.16.840.1.113883.5.110": "http://terminology.hl7.org/CodeSystem/v3-RoleClass",
    "2.16.840.1.113883.5.111": "http://terminology.hl7.org/CodeSystem/v3-RoleCode",
    "2.16.840.1.113883.5.112": "http://terminology.hl7.org/CodeSystem/v3-RouteOfAdministration",
    "2.16.840.1.113883.5.1001": "http://terminology.hl7.org/CodeSystem/v3-ActMood",
    "2.16.840.1.113883.5.1008": "http://terminology.hl7.org/CodeSystem/v3-NullFlavor",
    "2.16.840.1.113883.5.1063": "http://terminology.hl7.org/CodeSystem/v3-ObservationValue",
    "2.16.840.1.113883.5.14": "http://terminology.hl7.org/CodeSystem/v3-ActStatus",
    "2.16.840.1.113883.5.7": "http://terminology.hl7.org/CodeSystem/v3-ActPriority",
    "2.16.840.1.113883.5.25": "http://terminology.hl7.org/CodeSystem/v3-Confidentiality",
    "2.16.840.1.113883.5.1076": "http://terminology.hl7.org/CodeSystem/v3-ReligiousAffiliation",
    "2.16.840.1.113883.5.1119": "http://terminology.hl7.org/CodeSystem/v3-AddressUse",
    "2.16.840.1.113883.5.139": "http://terminology.hl7.org/CodeSystem/v3-TimingEvent",
    "2.16.840.1.113883.5.1070": "http://terminology.hl7.org/CodeSystem/v3-EntityNamePartQualifier",
    "2.16.840.1.113883.11.20.9.38": "http://terminology.hl7.org/CodeSystem/v3-ObservationValue",
    "2.16.840.1.113883.1.11.78": "http://terminology.hl7.org/CodeSystem/v3-ObservationInterpretation",
    "2.16.840.1.113883.5.1115": "http://terminology.hl7.org/CodeSystem/v3-RoleStatus",
    "2.16.840.1.113883.5.1052": "http://terminology.hl7.org/CodeSystem/v3-ActSite",
    "2.16.840.1.113883.5.1119.1": "http://terminology.hl7.org/CodeSystem/v3-AddressUse",
}

UCUM = "http://unitsofmeasure.org"
SNOMED = OID_TO_URI["2.16.840.1.113883.6.96"]
LOINC = OID_TO_URI["2.16.840.1.113883.6.1"]
RXNORM = OID_TO_URI["2.16.840.1.113883.6.88"]
CVX = OID_TO_URI["2.16.840.1.113883.12.292"]

_V2_TABLE_PREFIX = "2.16.840.1.113883.12."
"""HL7 v2 tables (``2.16.840.1.113883.12.<table>``) map to ``v2-<table>`` code systems."""

Resolver = Callable[[str], str | None]
"""Resolves a narrative reference such as ``#allergies-desc-1`` to plain text."""


def system_uri(oid: str | None, unmapped: set[str] | None = None) -> str | None:
    """Map a CDA ``codeSystem`` OID to a FHIR system URI.

    Unknown OIDs become ``urn:oid:<oid>`` and are recorded in ``unmapped`` when
    given. Values that already look like URIs are returned unchanged.
    """
    if not oid:
        return None
    if oid in OID_TO_URI:
        return OID_TO_URI[oid]
    if "://" in oid or oid.startswith("urn:"):
        return oid
    if oid.startswith(_V2_TABLE_PREFIX):
        table = oid[len(_V2_TABLE_PREFIX) :]
        if table.isdigit():
            return f"http://terminology.hl7.org/CodeSystem/v2-{int(table):04d}"
    if unmapped is not None:
        unmapped.add(oid)
    return f"urn:oid:{oid}"


def is_null(el: etree._Element | None) -> bool:
    """True when the element is absent or carries a ``nullFlavor``."""
    return el is None or attr(el, "nullFlavor") is not None


def coding(el: etree._Element | None, unmapped: set[str] | None = None) -> dict | None:
    """Build a FHIR ``Coding`` from a CD/CE element (ignoring translations)."""
    if is_null(el):
        return None
    code = attr(el, "code")
    if code is None:
        return None
    out: dict = {"code": code}
    system = system_uri(attr(el, "codeSystem"), unmapped)
    if system:
        out["system"] = system
    display = attr(el, "displayName")
    if display:
        out["display"] = display
    return _order_coding(out)


def _order_coding(c: dict) -> dict:
    ordered = {}
    for k in ("system", "code", "display"):
        if k in c:
            ordered[k] = c[k]
    return ordered


def codeable_concept(
    el: etree._Element | None,
    unmapped: set[str] | None = None,
    resolve: Resolver | None = None,
) -> dict | None:
    """Build a ``CodeableConcept`` from a CD/CE element.

    ``translation`` children become additional codings (duplicates of the
    primary coding are dropped). ``originalText`` is carried to ``text``, either
    inline or by resolving a ``<reference value="#id"/>`` into the section
    narrative, whether or not a coding has a display: with a null primary code
    and local translations it is the only readable name.
    """
    if el is None:
        return None
    primary = coding(el, unmapped)
    codings: list[dict] = []
    if primary:
        codings.append(primary)
    for tr in children(el, "translation"):
        c = coding(tr, unmapped)
        if c and c not in codings:
            codings.append(c)
    text = original_text(el, resolve)
    if not codings and not text:
        return None
    out: dict = {}
    if codings:
        out["coding"] = codings
    if text:
        out["text"] = text
    return out


def original_text(el: etree._Element, resolve: Resolver | None) -> str | None:
    """Return ``originalText`` content, resolving a narrative reference if present."""
    ot = child(el, "originalText")
    if ot is None:
        return None
    ref = child(ot, "reference")
    if ref is not None and resolve is not None:
        target = attr(ref, "value")
        if target:
            resolved = resolve(target)
            if resolved:
                return resolved
    return text_of(ot)


def concept_text(cc: dict | None) -> str | None:
    """Best human-readable label for a ``CodeableConcept``."""
    if not cc:
        return None
    if cc.get("text"):
        return cc["text"]
    for c in cc.get("coding", []):
        if c.get("display"):
            return c["display"]
    return None


def simple_concept(system: str, code: str, display: str | None = None) -> dict:
    """``CodeableConcept`` with exactly one coding."""
    c: dict = {"system": system, "code": code}
    if display:
        c["display"] = display
    return {"coding": [c]}


def quantity(el: etree._Element | None) -> dict | None:
    """Build a FHIR ``Quantity`` from a PQ element (``value`` and ``unit``)."""
    if is_null(el):
        return None
    raw = attr(el, "value")
    if raw is None:
        return None
    try:
        num = float(raw)
    except ValueError:
        return None
    out: dict = {"value": int(num) if num.is_integer() and "." not in raw else num}
    unit = attr(el, "unit")
    if unit and unit != "1":
        out["unit"] = unit
        out["system"] = UCUM
        out["code"] = unit
    return out
