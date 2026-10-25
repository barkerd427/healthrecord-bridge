"""Shared state and helpers handed to every section mapper."""

from __future__ import annotations

from dataclasses import dataclass, field

from lxml import etree

from . import codes
from .datetime_utils import ParsedTs, parse_ts
from .document import CdaDocument, first_id
from .ids import CdaId, fallback_id, identifier, resource_id
from .narrative import referenced_text
from .report import DocumentReport
from .xml import attr, child, children, xsi_type

HRB_TAG_SYSTEM = "urn:healthrecord-bridge"


@dataclass(slots=True)
class Context:
    """Everything a mapper needs: the document, the patient reference and the report."""

    doc: CdaDocument
    report: DocumentReport
    assume_tz: str | None = None
    patient_ref: dict = field(default_factory=dict)
    unmapped: set[str] = field(default_factory=set)
    truncated_timestamps: int = 0

    # ---- codes and text ---------------------------------------------------------

    def concept(self, el: etree._Element | None) -> dict | None:
        return codes.codeable_concept(el, self.unmapped, self.doc.narrative.resolve)

    def system(self, oid: str | None) -> str | None:
        return codes.system_uri(oid, self.unmapped)

    def entry_text(self, el: etree._Element | None) -> str | None:
        """Narrative text for an entry's ``<text>`` child."""
        return referenced_text(child(el, "text"), self.doc.narrative)

    # ---- time -------------------------------------------------------------------

    def parse(self, raw: str | None) -> ParsedTs | None:
        p = parse_ts(raw, self.assume_tz)
        if p is not None and p.truncated:
            self.truncated_timestamps += 1
        return p

    def ts(self, raw: str | None) -> str | None:
        p = self.parse(raw)
        return p.value if p else None

    def ts_value(self, el: etree._Element | None) -> str | None:
        """FHIR dateTime for a ``<effectiveTime value=".."/>`` style element."""
        if el is None or attr(el, "nullFlavor"):
            return None
        return self.ts(attr(el, "value"))

    def period(self, el: etree._Element | None) -> dict | None:
        """FHIR Period from an IVL_TS element with ``low``/``high`` children."""
        if el is None:
            return None
        out: dict = {}
        low = self.ts_value(child(el, "low"))
        high = self.ts_value(child(el, "high"))
        if low:
            out["start"] = low
        if high:
            out["end"] = high
        return out or None

    def effective(self, el: etree._Element | None) -> tuple[str, str | dict] | None:
        """Interpret an effectiveTime as ``("dateTime", str)`` or ``("period", dict)``.

        A point in time (``value``) wins; otherwise ``low``/``high``; when only
        a ``center`` exists it is used as the point in time. PIVL/EIVL timing
        elements are not effective times and return ``None``.
        """
        if el is None or attr(el, "nullFlavor"):
            return None
        if xsi_type(el) in {"PIVL_TS", "EIVL_TS", "SXPR_TS"}:
            return None
        point = self.ts_value(el)
        if point:
            return ("dateTime", point)
        period = self.period(el)
        if period:
            return ("period", period)
        center = self.ts_value(child(el, "center"))
        if center:
            return ("dateTime", center)
        return None

    def set_effective(
        self, resource: dict, el: etree._Element | None, point_key: str, period_key: str
    ) -> None:
        eff = self.effective(el)
        if eff is None:
            return
        kind, value = eff
        resource[point_key if kind == "dateTime" else period_key] = value

    # ---- ids and resource skeletons ---------------------------------------------

    def ids_of(self, el: etree._Element | None) -> list[CdaId]:
        out: list[CdaId] = []
        for id_el in children(el, "id"):
            if attr(id_el, "nullFlavor"):
                continue
            root = attr(id_el, "root")
            if root:
                out.append(CdaId(root, attr(id_el, "extension")))
        return out

    def new_resource(
        self,
        resource_type: str,
        el: etree._Element | None,
        *fallback_parts: str | int | None,
    ) -> dict:
        """Skeleton with deterministic ``id``, ``identifier``, ``meta`` and subject.

        The id derives from the element's first ``id``; without one it derives
        from the document id plus ``fallback_parts`` (section code, ordinals).
        """
        cda_ids = self.ids_of(el)
        if cda_ids:
            rid = resource_id(resource_type, cda_ids[0])
        else:
            parts = [str(p) for p in fallback_parts if p is not None]
            rid = fallback_id(resource_type, self.doc.id, *parts)
        resource: dict = {
            "resourceType": resource_type,
            "id": rid,
            "meta": self.meta(),
        }
        if cda_ids:
            resource["identifier"] = [identifier(c) for c in cda_ids]
        return resource

    def meta(self) -> dict:
        return {
            "source": f"urn:healthrecord-bridge:ccda:{self.doc.id}",
            "tag": [{"system": HRB_TAG_SYSTEM, "code": "ccda"}],
        }

    def first_cda_id(self, el: etree._Element | None) -> CdaId | None:
        return first_id(el)

    def reference(self, resource: dict, display: str | None = None) -> dict:
        ref: dict = {"reference": f"{resource['resourceType']}/{resource['id']}"}
        if display:
            ref["display"] = display
        return ref


def status_code(el: etree._Element | None) -> str | None:
    """``statusCode/@code`` lowercased, or None."""
    sc = child(el, "statusCode")
    code = attr(sc, "code")
    return code.lower() if code else None


def negated(el: etree._Element | None) -> bool:
    return (attr(el, "negationInd") or "").lower() == "true"


def mood(el: etree._Element | None) -> str:
    return (attr(el, "moodCode") or "EVN").upper()
