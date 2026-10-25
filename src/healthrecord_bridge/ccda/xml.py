"""Small lxml helpers scoped to the HL7 v3 namespace."""

from __future__ import annotations

import re
from collections.abc import Iterator

from lxml import etree

HL7_NS = "urn:hl7-org:v3"
SDTC_NS = "urn:hl7-org:sdtc"
XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"
NSMAP = {"c": HL7_NS, "sdtc": SDTC_NS, "xsi": XSI_NS}

_WS = re.compile(r"\s+")


def q(local: str, ns: str = HL7_NS) -> str:
    """Clark-notation qualified name."""
    return f"{{{ns}}}{local}"


def attr(el: etree._Element | None, name: str) -> str | None:
    if el is None:
        return None
    v = el.get(name)
    return v.strip() if isinstance(v, str) and v.strip() else None


def xsi_type(el: etree._Element | None) -> str | None:
    """``xsi:type`` without any namespace prefix (``IVL_TS``, ``PQ``, ...)."""
    v = attr(el, q("type", XSI_NS))
    if v and ":" in v:
        v = v.split(":", 1)[1]
    return v


def child(el: etree._Element | None, local: str, ns: str = HL7_NS) -> etree._Element | None:
    if el is None:
        return None
    return el.find(q(local, ns))


def children(el: etree._Element | None, local: str, ns: str = HL7_NS) -> list[etree._Element]:
    if el is None:
        return []
    return el.findall(q(local, ns))


def find(el: etree._Element | None, path: str) -> etree._Element | None:
    """Find with a ``c:``-prefixed path relative to ``el``."""
    if el is None:
        return None
    return el.find(path, namespaces=NSMAP)


def findall(el: etree._Element | None, path: str) -> list[etree._Element]:
    if el is None:
        return []
    return el.findall(path, namespaces=NSMAP)


def iter_descendants(el: etree._Element, local: str) -> Iterator[etree._Element]:
    yield from el.iter(q(local))


def text_of(el: etree._Element | None) -> str | None:
    """Whitespace-normalised text content of an element and its descendants."""
    if el is None:
        return None
    parts = [t for t in el.itertext() if t and t.strip()]
    s = _WS.sub(" ", " ".join(parts)).strip()
    return s or None


def child_text(el: etree._Element | None, local: str) -> str | None:
    return text_of(child(el, local))


def local_name(el: etree._Element) -> str:
    return etree.QName(el).localname


def value_attr(el: etree._Element | None, local: str) -> str | None:
    """``value`` attribute of a named child, honouring nullFlavor."""
    c = child(el, local)
    if c is None or attr(c, "nullFlavor"):
        return None
    return attr(c, "value")
