"""Resolve ``<reference value="#id"/>`` pointers into a section's narrative ``text``."""

from __future__ import annotations

from lxml import etree

from .xml import HL7_NS, text_of


class NarrativeIndex:
    """Index of ``ID`` attributes in a section's narrative block.

    CDA entries point at their human-readable description with
    ``<reference value="#allergies-desc-1"/>``. The target is any element in the
    section ``<text>`` carrying ``ID="allergies-desc-1"``. The index is built
    lazily on first lookup and covers the whole document, since some vendors
    reference narrative that lives in a different section.
    """

    def __init__(self, root: etree._Element) -> None:
        self._root = root
        self._index: dict[str, etree._Element] | None = None

    def _build(self) -> dict[str, etree._Element]:
        index: dict[str, etree._Element] = {}
        for text in self._root.iter(f"{{{HL7_NS}}}text"):
            for el in text.iter():
                if not isinstance(el.tag, str):
                    continue
                ident = el.get("ID")
                if ident and ident not in index:
                    index[ident] = el
        return index

    def resolve(self, reference: str | None) -> str | None:
        """Return the normalised text behind ``#id`` (or ``id``), if any."""
        if not reference:
            return None
        if self._index is None:
            self._index = self._build()
        key = reference[1:] if reference.startswith("#") else reference
        el = self._index.get(key)
        return text_of(el) if el is not None else None


def referenced_text(el: etree._Element | None, index: NarrativeIndex) -> str | None:
    """Text for an entry's ``<text>`` element: inline text or a resolved reference."""
    if el is None:
        return None
    ref = el.find(f"{{{HL7_NS}}}reference")
    if ref is not None:
        resolved = index.resolve(ref.get("value"))
        if resolved:
            return resolved
    return text_of(el)
