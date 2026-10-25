"""Zip / IHE XDM input."""

from __future__ import annotations

import copy
import zipfile

import pytest

from conftest import HANDWRITTEN, XDM_SOURCE_XML, XDM_ZIP, by_type
from healthrecord_bridge.ccda import NoDocumentsFoundError, convert
from healthrecord_bridge.ccda.xdm import iter_xml_members


def _strip_source_entity(bundle: dict) -> dict:
    out = copy.deepcopy(bundle)
    for e in out["entry"]:
        if e["resource"]["resourceType"] == "Provenance":
            e["resource"].pop("entity")
    return out


def test_xdm_zip_matches_bare_xml():
    from_zip, zip_report = convert(XDM_ZIP)
    from_xml, xml_report = convert(XDM_SOURCE_XML)
    assert _strip_source_entity(from_zip) == _strip_source_entity(from_xml)
    prov = by_type(from_zip)["Provenance"][0]
    assert prov["entity"][0]["what"]["display"] == (
        "mychart_export_letha284.zip:MachineReadable_XDMFormat/IHE_XDM/SUBSET01/DOC0001.XML"
    )
    assert zip_report.resource_counts == xml_report.resource_counts
    assert len(zip_report.documents) == 1


def test_member_selection_skips_metadata_and_prefers_ihe_xdm(tmp_path):
    path = tmp_path / "mixed.zip"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("INDEX.HTM", "<html/>")
        zf.writestr("README.TXT", "x")
        zf.writestr("other/stray.xml", "<x/>")
        zf.writestr("IHE_XDM/SUBSET01/METADATA.XML", "<m/>")
        zf.writestr("IHE_XDM/SUBSET01/DOC0002.XML", "<b/>")
        zf.writestr("IHE_XDM/SUBSET01/DOC0001.xml", "<a/>")
    with zipfile.ZipFile(path) as zf:
        names = [m.filename for m in iter_xml_members(zf)]
    assert names == ["IHE_XDM/SUBSET01/DOC0001.xml", "IHE_XDM/SUBSET01/DOC0002.XML"]


def test_plain_zip_with_ccda_anywhere(tmp_path):
    path = tmp_path / "plain.zip"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("exports/2024/record.xml", HANDWRITTEN.read_bytes())
    bundle, _ = convert(path)
    assert by_type(bundle)["Patient"][0]["name"][0]["family"] == "Sampleton"


def test_zip_without_xml_is_rejected(tmp_path):
    path = tmp_path / "empty.zip"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("INDEX.HTM", "<html/>")
    with pytest.raises(NoDocumentsFoundError):
        convert(path)
