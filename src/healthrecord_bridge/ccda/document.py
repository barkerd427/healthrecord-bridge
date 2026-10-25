"""Secure parsing of a C-CDA XML document and typed access to its header."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from lxml import etree

from .errors import NotClinicalDocumentError, UnsafeXmlError
from .ids import CdaId
from .narrative import NarrativeIndex
from .xml import HL7_NS, attr, child, child_text, children, find, findall, q

CLINICAL_DOCUMENT = q("ClinicalDocument")


def make_parser() -> etree.XMLParser:
    """Parser hardened for untrusted input: no entity expansion, no network, no huge trees."""
    return etree.XMLParser(
        resolve_entities=False,
        no_network=True,
        huge_tree=False,
        load_dtd=False,
        remove_comments=True,
        remove_pis=True,
    )


def parse_xml(data: bytes, source: str = "<bytes>") -> etree._Element:
    """Parse bytes and return the ``ClinicalDocument`` root or raise a ``CcdaError``."""
    try:
        root = etree.fromstring(data, make_parser())
    except etree.XMLSyntaxError as exc:
        raise NotClinicalDocumentError(f"{source}: not well-formed XML: {exc}") from exc
    tree = root.getroottree()
    info = tree.docinfo
    if info.doctype or info.internalDTD is not None or info.externalDTD is not None:
        raise UnsafeXmlError(
            f"{source}: documents with a DOCTYPE or entity declarations are rejected"
        )
    for el in root.iter():
        if isinstance(el, etree._Entity):
            raise UnsafeXmlError(f"{source}: unresolved entity reference {el.name!r} rejected")
    if root.tag != CLINICAL_DOCUMENT:
        raise NotClinicalDocumentError(
            f"{source}: root element is {root.tag!r}, expected {CLINICAL_DOCUMENT!r}"
        )
    return root


def read_cda_id(el: etree._Element | None) -> CdaId | None:
    """Read an ``<id root extension/>`` element, treating nullFlavor as absent."""
    if el is None or attr(el, "nullFlavor"):
        return None
    root = attr(el, "root")
    if not root:
        return None
    return CdaId(root, attr(el, "extension"))


def first_id(el: etree._Element | None) -> CdaId | None:
    """First usable ``id`` child of an element."""
    for id_el in children(el, "id"):
        cid = read_cda_id(id_el)
        if cid:
            return cid
    return None


@dataclass(slots=True)
class Section:
    """A CDA section with its identifying codes."""

    element: etree._Element
    code: str | None
    code_system: str | None
    template_ids: frozenset[str]
    title: str | None
    null_flavor: str | None

    @property
    def entries(self) -> list[etree._Element]:
        return children(self.element, "entry")


@dataclass(slots=True)
class CdaDocument:
    """A parsed C-CDA document with convenient header accessors."""

    root: etree._Element
    source_name: str
    narrative: NarrativeIndex = field(init=False)

    def __post_init__(self) -> None:
        self.narrative = NarrativeIndex(self.root)

    @classmethod
    def from_bytes(cls, data: bytes, source_name: str = "<bytes>") -> CdaDocument:
        return cls(parse_xml(data, source_name), source_name)

    @classmethod
    def from_path(cls, path: str | os.PathLike[str]) -> CdaDocument:
        p = Path(path)
        return cls.from_bytes(p.read_bytes(), p.name)

    # ---- header -----------------------------------------------------------------

    @property
    def id(self) -> CdaId:
        """Document id; a synthetic one derived from the title is used if missing."""
        cid = read_cda_id(child(self.root, "id"))
        if cid:
            return cid
        return CdaId("urn:healthrecord-bridge:missing-document-id", self.source_name)

    @property
    def code_element(self) -> etree._Element | None:
        return child(self.root, "code")

    @property
    def title(self) -> str | None:
        return child_text(self.root, "title")

    @property
    def effective_time(self) -> str | None:
        et = child(self.root, "effectiveTime")
        return attr(et, "value") if et is not None and not attr(et, "nullFlavor") else None

    @property
    def language(self) -> str | None:
        lc = child(self.root, "languageCode")
        return attr(lc, "code")

    @property
    def patient_role(self) -> etree._Element | None:
        return find(self.root, "c:recordTarget/c:patientRole")

    @property
    def authors(self) -> list[etree._Element]:
        return children(self.root, "author")

    @property
    def custodian_org(self) -> etree._Element | None:
        return find(
            self.root,
            "c:custodian/c:assignedCustodian/c:representedCustodianOrganization",
        )

    @property
    def service_event(self) -> etree._Element | None:
        return find(self.root, "c:documentationOf/c:serviceEvent")

    # ---- body -------------------------------------------------------------------

    def sections(self) -> list[Section]:
        """All sections in document order, including nested ones."""
        body = find(self.root, "c:component/c:structuredBody")
        if body is None:
            return []
        out: list[Section] = []
        for sec in body.iter(f"{{{HL7_NS}}}section"):
            code_el = child(sec, "code")
            out.append(
                Section(
                    element=sec,
                    code=attr(code_el, "code"),
                    code_system=attr(code_el, "codeSystem"),
                    template_ids=frozenset(
                        r for t in children(sec, "templateId") if (r := attr(t, "root"))
                    ),
                    title=child_text(sec, "title"),
                    null_flavor=attr(sec, "nullFlavor"),
                )
            )
        return out

    def author_display(self) -> str | None:
        """Name of the first author: organisation, person or authoring device."""
        for author in self.authors:
            aa = child(author, "assignedAuthor")
            org = child_text(find(aa, "c:representedOrganization"), "name")
            if org:
                return org
            person = person_name(find(aa, "c:assignedPerson/c:name"))
            if person:
                return person
            device = child(aa, "assignedAuthoringDevice")
            name = child_text(device, "softwareName") or child_text(device, "manufacturerModelName")
            if name:
                return name
        return None


def person_name(name_el: etree._Element | None) -> str | None:
    """Flatten a PN element into ``prefix given family suffix``."""
    if name_el is None or attr(name_el, "nullFlavor"):
        return None
    parts: list[str] = []
    for local in ("prefix", "given", "family", "suffix"):
        for el in findall(name_el, f"c:{local}"):
            t = (el.text or "").strip()
            if t:
                parts.append(t)
    if parts:
        return " ".join(parts)
    text = (name_el.text or "").strip()
    return text or None
