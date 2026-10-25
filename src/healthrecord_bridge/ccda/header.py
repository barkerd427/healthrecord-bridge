"""Header resources: Patient, custodian Organization, DocumentReference and Provenance."""

from __future__ import annotations

from lxml import etree

from .codes import simple_concept
from .context import Context
from .datetime_utils import date_only, to_instant
from .document import person_name
from .ids import CdaId, fallback_id, identifier, resource_id
from .xml import SDTC_NS, attr, child, child_text, children, find, findall

US_CORE_RACE = "http://hl7.org/fhir/us/core/StructureDefinition/us-core-race"
US_CORE_ETHNICITY = "http://hl7.org/fhir/us/core/StructureDefinition/us-core-ethnicity"
US_CORE_BIRTHSEX = "http://hl7.org/fhir/us/core/StructureDefinition/us-core-birthsex"
CDC_RACE_ETHNICITY = "urn:oid:2.16.840.1.113883.6.238"
_OMB_RACE = {"1002-5", "2028-9", "2054-5", "2076-8", "2106-3", "UNK", "ASKU"}
_OMB_ETHNICITY = {"2135-2", "2186-5", "UNK", "ASKU"}

_GENDER = {"M": "male", "F": "female", "UN": "other", "UNK": "unknown"}
_ADDRESS_USE = {"HP": "home", "H": "home", "HV": "home", "WP": "work", "TMP": "temp", "BAD": "old"}
_TELECOM_USE = {
    "HP": "home",
    "H": "home",
    "WP": "work",
    "MC": "mobile",
    "TMP": "temp",
    "BAD": "old",
}
_NAME_USE = {"L": "official", "P": "nickname", "A": "anonymous", "C": "usual", "OR": "official"}
_MARITAL = "http://terminology.hl7.org/CodeSystem/v3-MaritalStatus"


def map_patient(ctx: Context) -> dict:
    role = ctx.doc.patient_role
    patient_el = child(role, "patient")
    ids = ctx.ids_of(role)
    if ids:
        pid = resource_id("Patient", ids[0])
    else:
        pid = fallback_id("Patient", ctx.doc.id, "recordTarget")
    res: dict = {"resourceType": "Patient", "id": pid, "meta": ctx.meta()}
    if ids:
        res["identifier"] = [_patient_identifier(c, ids[0]) for c in ids]
    names = [n for el in children(patient_el, "name") if (n := _human_name(el))]
    if names:
        res["name"] = names
    telecoms = [t for el in children(role, "telecom") if (t := _contact_point(el))]
    if telecoms:
        res["telecom"] = telecoms
    gender = attr(child(patient_el, "administrativeGenderCode"), "code")
    if gender:
        res["gender"] = _GENDER.get(gender.upper(), "unknown")
    birth = ctx.parse(attr(child(patient_el, "birthTime"), "value"))
    if birth:
        res["birthDate"] = date_only(birth)
    deceased_time = attr(child(patient_el, "deceasedTime", SDTC_NS), "value")
    deceased_ind = (attr(child(patient_el, "deceasedInd", SDTC_NS), "value") or "").lower()
    if deceased_time and (dt := ctx.ts(deceased_time)):
        res["deceasedDateTime"] = dt
    elif deceased_ind in {"true", "false"}:
        res["deceasedBoolean"] = deceased_ind == "true"
    addresses = [a for el in children(role, "addr") if (a := _address(el))]
    if addresses:
        res["address"] = addresses
    marital = ctx.concept(child(patient_el, "maritalStatusCode"))
    if marital:
        for c in marital.get("coding", []):
            if c.get("system", "").startswith("urn:oid:2.16.840.1.113883.5.2"):
                c["system"] = _MARITAL
        res["maritalStatus"] = marital
    comms = []
    for lc in children(patient_el, "languageCommunication"):
        code = attr(child(lc, "languageCode"), "code")
        if not code:
            continue
        comm: dict = {"language": {"coding": [{"system": "urn:ietf:bcp:47", "code": code}]}}
        pref = (attr(child(lc, "preferenceInd"), "value") or "").lower()
        if pref in {"true", "false"}:
            comm["preferred"] = pref == "true"
        comms.append(comm)
    if comms:
        res["communication"] = comms
    extensions = []
    race = _race_ethnicity(
        ctx,
        children(patient_el, "raceCode") + children(patient_el, "raceCode", SDTC_NS),
        US_CORE_RACE,
        _OMB_RACE,
    )
    if race:
        extensions.append(race)
    eth = _race_ethnicity(
        ctx,
        children(patient_el, "ethnicGroupCode") + children(patient_el, "ethnicGroupCode", SDTC_NS),
        US_CORE_ETHNICITY,
        _OMB_ETHNICITY,
    )
    if eth:
        extensions.append(eth)
    if gender and gender.upper() in {"M", "F"}:
        extensions.append({"url": US_CORE_BIRTHSEX, "valueCode": gender.upper()})
    if extensions:
        res["extension"] = extensions
    org = find(role, "c:providerOrganization")
    org_name = child_text(org, "name")
    if org_name:
        res["managingOrganization"] = {"display": org_name}
    return res


def _patient_identifier(cda_id: CdaId, primary: CdaId) -> dict:
    ident = identifier(cda_id)
    if cda_id == primary and cda_id.extension:
        ident["type"] = simple_concept(
            "http://terminology.hl7.org/CodeSystem/v2-0203", "MR", "Medical record number"
        )
        ident["use"] = "usual"
    return ident


def _human_name(el: etree._Element) -> dict | None:
    if attr(el, "nullFlavor"):
        return None
    name: dict = {}
    use = attr(el, "use")
    if use and use.upper() in _NAME_USE:
        name["use"] = _NAME_USE[use.upper()]
    family = [t for f in findall(el, "c:family") if (t := (f.text or "").strip())]
    given = [t for g in findall(el, "c:given") if (t := (g.text or "").strip())]
    prefix = [t for p in findall(el, "c:prefix") if (t := (p.text or "").strip())]
    suffix = [t for s in findall(el, "c:suffix") if (t := (s.text or "").strip())]
    if family:
        name["family"] = " ".join(family)
    if given:
        name["given"] = given
    if prefix:
        name["prefix"] = prefix
    if suffix:
        name["suffix"] = suffix
    text = person_name(el)
    if text:
        name["text"] = text
    return name if ("family" in name or "given" in name or "text" in name) else None


def _contact_point(el: etree._Element) -> dict | None:
    if attr(el, "nullFlavor"):
        return None
    raw = attr(el, "value")
    if not raw:
        return None
    lower = raw.lower()
    if lower.startswith("tel:"):
        system, value = "phone", raw[4:]
    elif lower.startswith("mailto:"):
        system, value = "email", raw[7:]
    elif lower.startswith("fax:"):
        system, value = "fax", raw[4:]
    elif lower.startswith(("http:", "https:")):
        system, value = "url", raw
    elif "@" in raw:
        system, value = "email", raw
    else:
        system, value = "phone", raw
    out: dict = {"system": system, "value": value.strip()}
    use = attr(el, "use")
    if use:
        for token in use.split():
            if token.upper() in _TELECOM_USE:
                out["use"] = _TELECOM_USE[token.upper()]
                break
    return out


def _address(el: etree._Element) -> dict | None:
    if attr(el, "nullFlavor"):
        return None
    addr: dict = {}
    use = attr(el, "use")
    if use:
        for token in use.split():
            if token.upper() in _ADDRESS_USE:
                addr["use"] = _ADDRESS_USE[token.upper()]
                break
    lines = [t for s in findall(el, "c:streetAddressLine") if (t := (s.text or "").strip())]
    if lines:
        addr["line"] = lines
    for local, key in (
        ("city", "city"),
        ("state", "state"),
        ("postalCode", "postalCode"),
        ("country", "country"),
        ("county", "district"),
    ):
        v = child_text(el, local)
        if v:
            addr[key] = v
    return addr or None


def _race_ethnicity(
    ctx: Context, elements: list[etree._Element], url: str, omb_codes: set[str]
) -> dict | None:
    ext: list[dict] = []
    texts: list[str] = []
    for el in elements:
        if attr(el, "nullFlavor"):
            continue
        code = attr(el, "code")
        if not code:
            continue
        coding: dict = {"system": CDC_RACE_ETHNICITY, "code": code}
        display = attr(el, "displayName")
        if display:
            coding["display"] = display
            texts.append(display)
        kind = "ombCategory" if code in omb_codes else "detailed"
        ext.append({"url": kind, "valueCoding": coding})
    if not ext:
        return None
    ext.append({"url": "text", "valueString": ", ".join(texts) if texts else "unknown"})
    return {"url": url, "extension": ext}


def map_custodian(ctx: Context) -> dict | None:
    org = ctx.doc.custodian_org
    if org is None:
        return None
    name = child_text(org, "name")
    ids = ctx.ids_of(org)
    if not name and not ids:
        return None
    if ids:
        oid = resource_id("Organization", ids[0])
    else:
        oid = fallback_id("Organization", ctx.doc.id, "custodian", name or "")
    res: dict = {"resourceType": "Organization", "id": oid, "meta": ctx.meta(), "active": True}
    if ids:
        res["identifier"] = [identifier(c) for c in ids]
    if name:
        res["name"] = name
    telecoms = [t for el in children(org, "telecom") if (t := _contact_point(el))]
    if telecoms:
        res["telecom"] = telecoms
    addresses = [a for el in children(org, "addr") if (a := _address(el))]
    if addresses:
        res["address"] = addresses
    return res


def map_document_reference(ctx: Context, custodian: dict | None) -> dict:
    doc = ctx.doc
    res: dict = {
        "resourceType": "DocumentReference",
        "id": resource_id("DocumentReference", doc.id),
        "meta": ctx.meta(),
        "masterIdentifier": identifier(doc.id),
        "identifier": [identifier(doc.id)],
        "status": "current",
    }
    code = ctx.concept(doc.code_element)
    if code:
        res["type"] = code
    res["category"] = [
        simple_concept(
            "http://hl7.org/fhir/us/core/CodeSystem/us-core-documentreference-category",
            "clinical-note",
            "Clinical Note",
        )
    ]
    res["subject"] = ctx.patient_ref
    date = to_instant(doc.effective_time, ctx.assume_tz or "Z")
    if date:
        res["date"] = date
    author = doc.author_display()
    if author:
        res["author"] = [{"display": author}]
    if custodian:
        res["custodian"] = ctx.reference(custodian, custodian.get("name"))
    attachment: dict = {"contentType": "application/xml"}
    if doc.language:
        attachment["language"] = doc.language
    if doc.title:
        attachment["title"] = doc.title
    res["content"] = [{"attachment": attachment}]
    period = ctx.period(child(doc.service_event, "effectiveTime"))
    if period:
        res["context"] = {"period": period}
    return res


def map_provenance(ctx: Context, targets: list[dict]) -> dict:
    doc = ctx.doc
    res: dict = {
        "resourceType": "Provenance",
        "id": resource_id("Provenance", doc.id),
        "meta": ctx.meta(),
        "target": [ctx.reference(r) for r in targets],
    }
    period = ctx.period(child(doc.service_event, "effectiveTime"))
    if period:
        res["occurredPeriod"] = period
    recorded = to_instant(doc.effective_time, ctx.assume_tz or "Z")
    res["recorded"] = recorded or "1970-01-01T00:00:00Z"
    agent: dict = {
        "type": simple_concept(
            "http://terminology.hl7.org/CodeSystem/provenance-participant-type",
            "author",
            "Author",
        ),
        "who": {"display": doc.author_display() or "unknown author"},
    }
    res["agent"] = [agent]
    res["entity"] = [
        {"role": "source", "what": {"display": doc.source_name}},
    ]
    return res
