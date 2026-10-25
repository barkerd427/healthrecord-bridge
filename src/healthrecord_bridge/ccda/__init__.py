"""C-CDA R2.1 to FHIR R4 conversion.

Typical use::

    from healthrecord_bridge.ccda import convert
    bundle, report = convert("DOC0001.XML")

``convert`` accepts a bare C-CDA XML file or a zip archive (an IHE XDM export
from Epic MyChart, or any zip with C-CDA XML inside). It returns a FHIR R4
``Bundle`` of type ``collection`` as a plain dict plus a :class:`ConversionReport`.
"""

from __future__ import annotations

import os
from pathlib import Path

from ..fhir.bundle import make_bundle, merge_bundles
from . import xdm
from .context import Context
from .datetime_utils import normalize_offset
from .document import CdaDocument
from .errors import CcdaError, NoDocumentsFoundError, NotClinicalDocumentError, UnsafeXmlError
from .header import map_custodian, map_document_reference, map_patient, map_provenance
from .ids import NAMESPACE_HRB
from .report import ConversionReport, DocumentReport, SectionReport, UnknownSection
from .sections import KNOWN_UNMAPPED, find_spec

__all__ = [
    "NAMESPACE_HRB",
    "CcdaError",
    "ConversionReport",
    "DocumentReport",
    "NoDocumentsFoundError",
    "NotClinicalDocumentError",
    "UnsafeXmlError",
    "convert",
    "convert_bytes",
    "convert_document",
    "convert_many",
]


def convert_document(
    doc: CdaDocument, *, assume_timezone: str | None = None
) -> tuple[list[dict], DocumentReport]:
    """Convert one parsed document to a list of FHIR resources plus its report.

    ``assume_timezone`` (for example ``"-05:00"`` or ``"Z"``) is applied to
    timestamps that carry a time of day but no UTC offset. Without it those
    timestamps are truncated to a date, because FHIR forbids a time without an
    offset, and the report notes how many were truncated.
    """
    report = DocumentReport(source=doc.source_name, document_id=str(doc.id))
    ctx = Context(doc=doc, report=report, assume_tz=normalize_offset(assume_timezone))

    patient = map_patient(ctx)
    ctx.patient_ref = ctx.reference(patient)
    resources: list[dict] = [patient]
    custodian = map_custodian(ctx)
    if custodian:
        resources.append(custodian)

    for section in doc.sections():
        spec = find_spec(section)
        if spec is None:
            title = section.title or KNOWN_UNMAPPED.get(section.code or "")
            report.unknown_sections.append(
                UnknownSection(section.code, title, len(section.entries))
            )
            continue
        sr = SectionReport(spec.name, section.code or spec.loinc, null_flavor=section.null_flavor)
        sr.entries_seen = len(section.entries)
        produced = spec.mapper(ctx, section, sr)
        sr.resources_produced = len(produced)
        report.sections.append(sr)
        resources.extend(produced)

    resources.append(map_document_reference(ctx, custodian))
    resources.append(map_provenance(ctx, resources))

    report.unmapped_code_systems = sorted(ctx.unmapped)
    counts: dict[str, int] = {}
    for r in resources:
        counts[r["resourceType"]] = counts.get(r["resourceType"], 0) + 1
    report.resource_counts = dict(sorted(counts.items()))
    if ctx.truncated_timestamps:
        report.notes.append(
            f"{ctx.truncated_timestamps} timestamps had a time of day but no UTC offset and "
            "were truncated to a date; pass assume_timezone to keep the time"
        )
    return resources, report


def convert_bytes(
    data: bytes, source_name: str = "<bytes>", *, assume_timezone: str | None = None
) -> tuple[dict, ConversionReport]:
    """Convert a single C-CDA document held in memory."""
    doc = CdaDocument.from_bytes(data, source_name)
    resources, report = convert_document(doc, assume_timezone=assume_timezone)
    return make_bundle(resources), ConversionReport([report])


def convert(
    path: str | os.PathLike[str], *, assume_timezone: str | None = None
) -> tuple[dict, ConversionReport]:
    """Convert a C-CDA XML file or a zip archive of them into one FHIR Bundle."""
    return convert_many([path], assume_timezone=assume_timezone)


def convert_many(
    paths: list[str | os.PathLike[str]], *, assume_timezone: str | None = None
) -> tuple[dict, ConversionReport]:
    """Convert several inputs (XML files and/or zips) into one merged Bundle.

    Resources are deduplicated by ``resourceType`` and ``id``; when two
    documents produce the same resource the later one wins.
    """
    bundles: list[dict] = []
    reports: list[DocumentReport] = []
    for path in paths:
        for name, data in _iter_inputs(path):
            doc = CdaDocument.from_bytes(data, name)
            resources, report = convert_document(doc, assume_timezone=assume_timezone)
            bundles.append(make_bundle(resources))
            reports.append(report)
    if not bundles:
        raise NoDocumentsFoundError("no C-CDA documents found in the given inputs")
    return merge_bundles(bundles), ConversionReport(reports)


def _iter_inputs(path: str | os.PathLike[str]):
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(str(p))
    if xdm.is_zip(p):
        found = False
        for name, data in xdm.iter_documents(p):
            found = True
            yield name, data
        if not found:
            raise NoDocumentsFoundError(f"{p.name}: zip contains no XML documents")
    else:
        yield p.name, p.read_bytes()
