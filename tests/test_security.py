"""Untrusted input handling."""

from __future__ import annotations

import pytest

from conftest import HANDWRITTEN
from healthrecord_bridge.ccda import (
    CcdaError,
    NotClinicalDocumentError,
    UnsafeXmlError,
    convert,
    convert_bytes,
)


def test_non_clinical_document_root_is_rejected(tmp_path):
    path = tmp_path / "not-cda.xml"
    path.write_text(
        '<?xml version="1.0"?><Bundle xmlns="http://hl7.org/fhir"><type value="x"/></Bundle>'
    )
    with pytest.raises(NotClinicalDocumentError):
        convert(path)


def test_wrong_namespace_is_rejected():
    with pytest.raises(NotClinicalDocumentError):
        convert_bytes(b"<ClinicalDocument/>")


def test_external_entity_is_rejected(tmp_path):
    path = tmp_path / "xxe.xml"
    path.write_text(
        '<?xml version="1.0"?>\n'
        '<!DOCTYPE ClinicalDocument [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>\n'
        '<ClinicalDocument xmlns="urn:hl7-org:v3"><title>&xxe;</title></ClinicalDocument>'
    )
    with pytest.raises(UnsafeXmlError):
        convert(path)


def test_internal_entity_and_doctype_are_rejected():
    data = (
        b'<?xml version="1.0"?><!DOCTYPE ClinicalDocument [<!ENTITY a "aaaa">]>'
        b'<ClinicalDocument xmlns="urn:hl7-org:v3"><title>&a;</title></ClinicalDocument>'
    )
    with pytest.raises(UnsafeXmlError):
        convert_bytes(data)
    with pytest.raises(UnsafeXmlError):
        convert_bytes(
            b'<?xml version="1.0"?><!DOCTYPE ClinicalDocument SYSTEM "http://example.invalid/cda.dtd">'
            b'<ClinicalDocument xmlns="urn:hl7-org:v3"/>'
        )


def test_malformed_xml_is_a_ccda_error():
    with pytest.raises(CcdaError):
        convert_bytes(b"<ClinicalDocument xmlns='urn:hl7-org:v3'>")


def test_missing_file():
    with pytest.raises(FileNotFoundError):
        convert("/nonexistent/path/record.xml")


def test_good_document_still_parses():
    bundle, _ = convert_bytes(HANDWRITTEN.read_bytes(), "inline.xml")
    assert len(bundle["entry"]) > 10
