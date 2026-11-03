"""Scrub identity and shift dates in a C-CDA document so it can be shared as a test fixture.

Names, addresses, telecoms and identifiers are replaced; every timestamp is moved
by the same number of days; codes, units, structure and narrative tables are left
alone so the converter still exercises the same paths on the output.
"""

from __future__ import annotations

import hashlib
import re
import secrets
import uuid
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from pathlib import Path

from lxml import etree

from .document import parse_xml
from .ids import _OID_RE, _UUID_RE
from .xml import HL7_NS, attr, findall, local_name, q

PATIENT_GIVEN = "Alex"
PATIENT_FAMILY = "Testperson"
PERSON_GIVEN = "Pat"
PERSON_FAMILY = "Clinician"
ORGANIZATION_NAME = "Example Health System"
ADDRESS = (
    ("streetAddressLine", "123 Example St"),
    ("city", "Springfield"),
    ("state", "KS"),
    ("postalCode", "00000"),
    ("country", "US"),
)
PHONE = "tel:+1-555-0100"
EMAIL = "mailto:patient@example.com"
AUTHORITY_NAME = "Example"
EPIC_CUSTOMER_OID = "1.2.840.114350.1.13.0"
NPI_REPLACEMENT = "0000000000"
MRN_REPLACEMENT = "MRN: 00000"
EMAIL_REPLACEMENT = "[email removed]"
PHONE_REPLACEMENT = "555-0100"

SUBSTITUTES: frozenset[str] = frozenset(
    {
        PATIENT_GIVEN,
        PATIENT_FAMILY,
        PERSON_GIVEN,
        PERSON_FAMILY,
        ORGANIZATION_NAME,
        AUTHORITY_NAME,
        *(v for _, v in ADDRESS),
        PHONE,
        EMAIL,
        PHONE.split(":", 1)[1],
        EMAIL.split(":", 1)[1],
        NPI_REPLACEMENT,
        MRN_REPLACEMENT,
        EMAIL_REPLACEMENT,
        PHONE_REPLACEMENT,
    }
)
"""Every string the scrubber writes; residual checks never report these."""

TS_ATTRIBUTES = frozenset({"value", "low", "high", "center", "time", "effectiveTime"})
NAME_PARTS = ("prefix", "given", "family", "suffix")

_TS_RE = re.compile(r"^(?P<date>\d{8})(?P<rest>\d*(?:\.\d+)?(?:[+-]\d{4})?)$")
_PHONE_RE = re.compile(r"(?<![\d.])\(?\d{3}\)?[-. ]?\d{3}[-. ]\d{4}(?!\.?\d)")
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_MRN_RE = re.compile(r"\bMRN\s*[:#]?\s*[A-Za-z]{0,3}\d+", re.IGNORECASE)
_NPI_RE = re.compile(r"\b(NPI\s*[:#]?\s*)\d{10}\b", re.IGNORECASE)
_LONG_DIGITS_RE = re.compile(r"(?<![\d.])\d{9,}")
_DIGIT_RUN_RE = re.compile(r"(?<!\d)\d{9,}(?!\d)")
_EPIC_CUSTOMER_RE = re.compile(r"1\.2\.840\.114350\.1\.13\.\d+")
_KEPT_AUTHORITIES = frozenset({"EPIC", "EPC"})
_CODE_LABEL_RE = re.compile(
    r"(?:SNOMED(?:[- ]?CT)?|LOINC|RXNORM|CVX|CPT|NDC|HCPCS|ICD-?(?:9|10)(?:-CM)?)\s*[:#]?\s*$",
    re.IGNORECASE,
)

# Elements whose <name> child is a person, an organisation, or must be left alone.
_PERSON_PARENTS = frozenset(
    {
        "patient",
        "assignedPerson",
        "guardianPerson",
        "associatedPerson",
        "relatedPerson",
        "informationRecipient",
        "subject",
    }
)
_ORGANIZATION_PARENTS = frozenset(
    {
        "representedOrganization",
        "representedCustodianOrganization",
        "providerOrganization",
        "guardianOrganization",
        "scopingOrganization",
        "serviceProviderOrganization",
        "receivedOrganization",
        "wholeOrganization",
        "location",
        "playingEntity",
    }
)
_KEEP_NAME_PARENTS = frozenset({"manufacturedMaterial", "labeledDrug", "manufacturerOrganization"})
_TEXT_ELEMENTS = ("text", "originalText", "title")


@dataclass(slots=True)
class AnonymizeReport:
    """What the scrubber changed and what a reviewer should still look at."""

    day_shift: int
    ids_rewritten: int = 0
    oids_rewritten: int = 0
    """Epic customer OIDs whose customer number became 0."""
    names_rewritten: int = 0
    telecoms_rewritten: int = 0
    addresses_rewritten: int = 0
    narrative_replacements: int = 0
    residual_findings: list[str] = field(default_factory=list)
    """Text that still looks like an identifier, phone number or email after scrubbing."""

    def to_dict(self) -> dict:
        return asdict(self)

    def summary(self) -> str:
        """One line for a terminal."""
        return (
            f"day shift {self.day_shift:+d}, ids {self.ids_rewritten}, "
            f"oids {self.oids_rewritten}, "
            f"names {self.names_rewritten}, telecoms {self.telecoms_rewritten}, "
            f"addresses {self.addresses_rewritten}, "
            f"narrative replacements {self.narrative_replacements}, "
            f"residual findings {len(self.residual_findings)}"
        )


def day_shift_for(seed: str) -> int:
    """Deterministic offset of 30 to 730 days, either sign, derived from the seed."""
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    days = 30 + int.from_bytes(digest[:4], "big") % 701
    return -days if digest[4] & 1 else days


def shift_ts(raw: str, days: int) -> str | None:
    """Shift the date part of an HL7 TS, keeping its precision; ``None`` if not a TS."""
    m = _TS_RE.match(raw)
    if not m:
        return None
    d = m.group("date")
    try:
        shifted = date(int(d[:4]), int(d[4:6]), int(d[6:8])) + timedelta(days=days)
    except ValueError:
        return None
    return f"{shifted.year:04d}{shifted.month:02d}{shifted.day:02d}{m.group('rest')}"


def anonymize(xml_bytes: bytes, *, seed: str | None = None) -> tuple[bytes, AnonymizeReport]:
    """Return the scrubbed document and a report. The same seed gives the same output."""
    root = parse_xml(xml_bytes)
    scrubber = _Scrubber(seed if seed is not None else secrets.token_hex(16))
    scrubber.run(root)
    tree = root.getroottree()
    info = tree.docinfo
    out = etree.tostring(
        tree,
        xml_declaration=True,
        encoding=info.encoding or "UTF-8",
    )
    return out, scrubber.report


def anonymize_file(src: Path, dst: Path, seed: str | None = None) -> AnonymizeReport:
    """Anonymize one XML file into another."""
    out, report = anonymize(Path(src).read_bytes(), seed=seed)
    Path(dst).write_bytes(out)
    return report


class _Scrubber:
    def __init__(self, seed: str) -> None:
        self.seed = seed
        self.report = AnonymizeReport(day_shift=day_shift_for(seed))
        self.tokens: dict[str, str] = {}

    def run(self, root: etree._Element) -> None:
        self._collect_tokens(root)
        self._shift_dates(root)
        self._rewrite_ids(root)
        self._rewrite_oids(root)
        self._rewrite_authorities(root)
        self._rewrite_names(root)
        self._rewrite_addresses(root)
        self._rewrite_telecoms(root)
        self._rewrite_narrative(root)
        self._find_residuals(root)

    # ---- hashing ------------------------------------------------------------------

    def _hash(self, original: str) -> str:
        return hashlib.sha256((self.seed + original).encode("utf-8")).hexdigest()[:16]

    def _hash_uuid(self, original: str) -> str:
        return str(uuid.uuid5(uuid.NAMESPACE_OID, self.seed + original))

    def _hash_digit_runs(self, original: str) -> str:
        """Replace every run of 9 or more digits with 8 seeded digits."""
        return _DIGIT_RUN_RE.sub(
            lambda m: f"{int(self._hash(m.group(0)), 16) % 10**8:08d}", original
        )

    # ---- tokens seen in the structured part ---------------------------------------

    def _collect_tokens(self, root: etree._Element) -> None:
        patient_role = root.find("c:recordTarget/c:patientRole", {"c": HL7_NS})
        if patient_role is not None:
            for name_el in findall(patient_role, "c:patient/c:name"):
                self._collect_person(name_el, PATIENT_GIVEN, PATIENT_FAMILY)
            for id_el in patient_role.findall(q("id")):
                ext = attr(id_el, "extension")
                if ext and len(ext) >= 4:
                    self.tokens.setdefault(ext.lower(), self._hash(ext))
        for name_el in root.iter(q("name")):
            kind = _name_kind(name_el)
            if kind == "person":
                self._collect_person(name_el, PERSON_GIVEN, PERSON_FAMILY)
            elif kind == "organization":
                text = _flat_text(name_el)
                if text:
                    self.tokens.setdefault(text.lower(), ORGANIZATION_NAME)

    def _collect_person(self, name_el: etree._Element, given: str, family: str) -> None:
        parts = [(local_name(c), (c.text or "").strip()) for c in name_el if isinstance(c.tag, str)]
        parts = [(k, v) for k, v in parts if k in NAME_PARTS and v]
        if not parts:
            words = (name_el.text or "").split()
            parts = [("given", w) for w in words[:-1]] + [("family", w) for w in words[-1:]]
        for kind, value in parts:
            replacement = {"given": given, "family": family}.get(kind, "")
            if len(value) >= 2:
                self.tokens.setdefault(value.lower(), replacement)

    # ---- dates ----------------------------------------------------------------------

    def _shift_dates(self, root: etree._Element) -> None:
        days = self.report.day_shift
        for el in root.iter():
            if not isinstance(el.tag, str):
                continue
            birth = local_name(el) == "birthTime"
            for name, value in el.attrib.items():
                if etree.QName(name).localname not in TS_ATTRIBUTES:
                    continue
                shifted = shift_ts(value.strip(), days)
                if shifted is None:
                    continue
                if birth:
                    shifted = shifted[:4] + "0101" + shifted[8:]
                el.set(name, shifted)

    # ---- identifiers ------------------------------------------------------------------

    def _rewrite_ids(self, root: etree._Element) -> None:
        for el in root.iter(q("id"), q("setId")):
            changed = False
            ext = attr(el, "extension")
            if ext:
                el.set("extension", self._hash(ext))
                changed = True
            root_attr = attr(el, "root")
            if root_attr and _UUID_RE.match(root_attr):
                el.set("root", self._hash_uuid(root_attr))
                changed = True
            elif root_attr and not _OID_RE.match(root_attr):
                el.set("root", self._hash(root_attr))
                changed = True
            elif root_attr and _DIGIT_RUN_RE.search(root_attr):
                el.set("root", self._hash_digit_runs(root_attr))
                changed = True
            if changed:
                self.report.ids_rewritten += 1
        self._rewrite_narrative_ids(root)

    def _rewrite_narrative_ids(self, root: etree._Element) -> None:
        """Hash long digit runs in narrative IDs, keeping the references that point at them."""
        renamed: dict[str, str] = {}
        for el in root.iter():
            if not isinstance(el.tag, str):
                continue
            old = el.get("ID")
            if old and _DIGIT_RUN_RE.search(old):
                new = self._hash_digit_runs(old)
                el.set("ID", new)
                renamed[old] = new
                self.report.ids_rewritten += 1
        if not renamed:
            return
        for el in root.iter():
            if not isinstance(el.tag, str):
                continue
            for name, value in el.attrib.items():
                if etree.QName(name).localname not in {"value", "href"}:
                    continue
                hash_mark, target = ("#", value[1:]) if value.startswith("#") else ("", value)
                if target in renamed:
                    el.set(name, hash_mark + renamed[target])

    def _rewrite_oids(self, root: etree._Element) -> None:
        """Replace the customer number in Epic OIDs, in attributes and text alike."""

        def sub(value: str) -> str:
            new, k = _EPIC_CUSTOMER_RE.subn(EPIC_CUSTOMER_OID, value)
            self.report.oids_rewritten += k
            return new

        for el in root.iter():
            if not isinstance(el.tag, str):
                continue
            for name, value in el.attrib.items():
                if "114350" in value:
                    el.set(name, sub(value))
            if el.text and "114350" in el.text:
                el.text = sub(el.text)
            if el.tail and "114350" in el.tail:
                el.tail = sub(el.tail)

    def _rewrite_authorities(self, root: etree._Element) -> None:
        for el in root.iter():
            if not isinstance(el.tag, str):
                continue
            value = el.get("assigningAuthorityName")
            if value and value.strip().upper() not in _KEPT_AUTHORITIES:
                el.set("assigningAuthorityName", AUTHORITY_NAME)

    # ---- names, addresses, telecoms ---------------------------------------------------

    def _rewrite_names(self, root: etree._Element) -> None:
        for name_el in list(root.iter(q("name"))):
            kind = _name_kind(name_el)
            if kind is None or _is_empty(name_el):
                continue
            if kind == "organization":
                if _flat_text(name_el) == ORGANIZATION_NAME:
                    continue
                _clear(name_el)
                name_el.text = ORGANIZATION_NAME
            else:
                given, family = (
                    (PATIENT_GIVEN, PATIENT_FAMILY)
                    if kind == "patient"
                    else (PERSON_GIVEN, PERSON_FAMILY)
                )
                _clear(name_el)
                etree.SubElement(name_el, q("given")).text = given
                etree.SubElement(name_el, q("family")).text = family
            self.report.names_rewritten += 1

    def _rewrite_addresses(self, root: etree._Element) -> None:
        for addr_el in root.iter(q("addr")):
            if _is_empty(addr_el):
                continue
            _clear(addr_el)
            for local, value in ADDRESS:
                etree.SubElement(addr_el, q(local)).text = value
            self.report.addresses_rewritten += 1

    def _rewrite_telecoms(self, root: etree._Element) -> None:
        for tel in root.iter(q("telecom")):
            value = attr(tel, "value")
            if not value:
                continue
            scheme = value.split(":", 1)[0].lower() if ":" in value else ""
            replacement = EMAIL if scheme == "mailto" or "@" in value else PHONE
            if value != replacement:
                tel.set("value", replacement)
                self.report.telecoms_rewritten += 1

    # ---- narrative ------------------------------------------------------------------------

    def _rewrite_narrative(self, root: etree._Element) -> None:
        tokens = {k: v for k, v in self.tokens.items() if k != v.lower()}
        token_re = None
        if tokens:
            alternatives = "|".join(re.escape(t) for t in sorted(tokens, key=len, reverse=True))
            token_re = re.compile(f"(?<![A-Za-z0-9])(?:{alternatives})(?![A-Za-z0-9])", re.I)

        def scrub(text: str) -> str:
            n = 0
            if token_re is not None:
                text, k = token_re.subn(lambda m: tokens[m.group(0).lower()], text)
                n += k
                if k:
                    text = re.sub(r" {2,}", " ", re.sub(r" ,", ",", text))
            text, k = _EMAIL_RE.subn(EMAIL_REPLACEMENT, text)
            n += k
            text, k = _PHONE_RE.subn(PHONE_REPLACEMENT, text)
            n += k
            text, k = _MRN_RE.subn(MRN_REPLACEMENT, text)
            n += k
            text, k = _NPI_RE.subn(rf"\g<1>{NPI_REPLACEMENT}", text)
            n += k
            self.report.narrative_replacements += n
            return text

        def scrub_tokens(text: str) -> str:
            if token_re is None:
                return text
            text, k = token_re.subn(lambda m: tokens[m.group(0).lower()], text)
            self.report.narrative_replacements += k
            return text

        narrative = list(_text_nodes(root))
        narrative_ids = {id(el) for el in narrative}
        for el in root.iter():
            if not isinstance(el.tag, str):
                continue
            fn = scrub if id(el) in narrative_ids else scrub_tokens
            if el.text:
                el.text = fn(el.text)
            if el.tail:
                el.tail = fn(el.tail)
        if token_re is not None:
            for el in root.iter():
                if not isinstance(el.tag, str):
                    continue
                display = el.get("displayName")
                if display:
                    new, k = token_re.subn(lambda m: tokens[m.group(0).lower()], display)
                    if k:
                        el.set("displayName", new)
                        self.report.narrative_replacements += k

    def _find_residuals(self, root: etree._Element) -> None:
        codes = {v for el in root.iter() if isinstance(el.tag, str) and (v := el.get("code"))}
        checks = (("digit run", _LONG_DIGITS_RE), ("email", _EMAIL_RE), ("phone", _PHONE_RE))
        for el in _text_nodes(root):
            for text in (el.text, el.tail):
                if not text:
                    continue
                for label, pattern in checks:
                    for m in pattern.finditer(text):
                        if m.group(0) in SUBSTITUTES:
                            continue
                        if label == "digit run" and (
                            m.group(0) in codes or _CODE_LABEL_RE.search(text[: m.start()])
                        ):
                            continue
                        self.report.residual_findings.append(
                            f"{label} {m.group(0)!r} in {_where(el)}: {_snippet(text)}"
                        )


def _name_kind(name_el: etree._Element) -> str | None:
    """``patient``, ``person``, ``organization`` or ``None`` for names to leave alone."""
    parent = name_el.getparent()
    if parent is None or not isinstance(parent.tag, str):
        return None
    local = local_name(parent)
    if local in _KEEP_NAME_PARENTS:
        return None
    if local == "playingEntity":
        class_code = attr(parent, "classCode") or ""
        if class_code == "MMAT":
            return None
        if class_code == "PSN":
            return "person"
    if local == "patient":
        return "patient"
    if local in _PERSON_PARENTS or any(
        isinstance(c.tag, str) and local_name(c) in NAME_PARTS for c in name_el
    ):
        return "person"
    if local in _ORGANIZATION_PARENTS:
        return "organization"
    return None


def _is_empty(el: etree._Element) -> bool:
    return len(el) == 0 and not _flat_text(el)


def _clear(el: etree._Element) -> None:
    for child in list(el):
        el.remove(child)
    el.text = None


def _flat_text(el: etree._Element) -> str:
    return " ".join(t.strip() for t in el.itertext() if t.strip())


def _text_nodes(root: etree._Element):
    """Elements whose text or tail is narrative: under ``text``, ``originalText`` or ``title``."""
    for local in _TEXT_ELEMENTS:
        for holder in root.iter(q(local)):
            for el in holder.iter():
                if isinstance(el.tag, str):
                    yield el


def _where(el: etree._Element) -> str:
    section = next(el.iterancestors(q("section")), None)
    if section is None:
        return "header"
    title = section.find(q("title"))
    if title is not None and title.text and title.text.strip():
        return title.text.strip()
    return f"section {attr(section.find(q('code')), 'code') or '?'}"


def _snippet(text: str, width: int = 80) -> str:
    s = " ".join(text.split())
    return s if len(s) <= width else s[: width - 3] + "..."
