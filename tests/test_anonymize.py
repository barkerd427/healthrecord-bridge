"""The anonymizer removes identity and shifts dates without changing what the converter sees."""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

import pytest
from lxml import etree

from conftest import HANDWRITTEN, NS, XDM_SOURCE_XML
from healthrecord_bridge.ccda import convert_bytes
from healthrecord_bridge.ccda.anonymize import anonymize, anonymize_file, day_shift_for, shift_ts
from healthrecord_bridge.cli import main

FIXTURES = [HANDWRITTEN, XDM_SOURCE_XML]
PATIENT_TOKENS = {
    HANDWRITTEN: ["Jane", "Quinn", "Sampleton", "jane.sampleton", "913-555", "Overland Park"],
    XDM_SOURCE_XML: ["Letha284", "Haag279", "Robel Vale", "Bedford"],
}


def ts_values(root: etree._Element) -> list[tuple[str, str]]:
    """(local tag, value) for every ``value`` attribute that looks like a TS."""
    out = []
    for el in root.iter():
        v = el.get("value")
        if v and re.match(r"^\d{8}", v):
            out.append((etree.QName(el).localname, v))
    return out


@pytest.fixture(params=FIXTURES, ids=lambda p: p.stem[:24])
def pair(request) -> tuple[Path, bytes, bytes]:
    src = request.param
    original = src.read_bytes()
    out, _ = anonymize(original, seed="fixture-seed")
    return src, original, out


def test_day_shift_range_and_sign():
    seen = {day_shift_for(str(i)) for i in range(200)}
    assert all(30 <= abs(d) <= 730 for d in seen)
    assert any(d < 0 for d in seen) and any(d > 0 for d in seen)
    assert day_shift_for("x") == day_shift_for("x")


def test_shift_ts_keeps_precision():
    assert shift_ts("20240315", 10) == "20240325"
    assert shift_ts("20240315143000-0500", -15) == "20240229143000-0500"
    assert shift_ts("20240315143000.123+0000", 1) == "20240316143000.123+0000"
    assert shift_ts("2024", 1) is None
    assert shift_ts("120", 1) is None
    assert shift_ts("20241399", 1) is None


def test_dates_shift_consistently(pair):
    _, original, out = pair
    shift = day_shift_for("fixture-seed")
    before = ts_values(etree.fromstring(original))
    after = ts_values(etree.fromstring(out))
    assert len(before) == len(after)
    for (tag_b, b), (tag_a, a) in zip(before, after, strict=True):
        assert tag_a == tag_b
        assert len(a) == len(b)
        assert a[8:] == b[8:]
        assert a != b
        if tag_b != "birthTime":
            assert _days(a[:8]) - _days(b[:8]) == shift
    root_before = etree.fromstring(original)
    root_after = etree.fromstring(out)
    lo_b = root_before.find(".//c:serviceEvent/c:effectiveTime/c:low", NS).get("value")
    hi_b = root_before.find(".//c:serviceEvent/c:effectiveTime/c:high", NS).get("value")
    lo_a = root_after.find(".//c:serviceEvent/c:effectiveTime/c:low", NS).get("value")
    hi_a = root_after.find(".//c:serviceEvent/c:effectiveTime/c:high", NS).get("value")
    assert _days(hi_a[:8]) - _days(lo_a[:8]) == _days(hi_b[:8]) - _days(lo_b[:8])
    assert lo_a != lo_b


def test_birth_date_is_january_first(pair):
    _, original, out = pair
    before = etree.fromstring(original).find(".//c:patient/c:birthTime", NS).get("value")
    after = etree.fromstring(out).find(".//c:patient/c:birthTime", NS).get("value")
    assert after[4:8] == "0101"
    assert len(after) == len(before)
    assert after[8:] == before[8:]


def test_no_patient_token_remains(pair):
    src, _, out = pair
    text = out.decode("utf-8").lower()
    for token in PATIENT_TOKENS[src]:
        assert token.lower() not in text, token
    root = etree.fromstring(out)
    name = root.find(".//c:recordTarget//c:patient/c:name", NS)
    assert [c.text for c in name] == ["Alex", "Testperson"]
    assert name.find("c:prefix", NS) is None and name.find("c:suffix", NS) is None
    addr = root.find(".//c:patientRole/c:addr", NS)
    assert addr.find("c:city", NS).text == "Springfield"
    assert addr.find("c:postalCode", NS).text == "00000"
    for tel in root.iterfind(".//c:telecom", NS):
        assert tel.get("value") in {None, "tel:+1-555-0100", "mailto:patient@example.com"}
    for person in root.iterfind(".//c:assignedPerson/c:name", NS):
        assert [c.text for c in person] == ["Pat", "Clinician"]
    for org in root.iterfind(".//c:representedCustodianOrganization/c:name", NS):
        assert org.text == "Example Health System"


def test_ids_change_and_repeat_consistently(pair):
    _, original, out = pair
    before = [
        (e.get("root"), e.get("extension"))
        for e in etree.fromstring(original).iter("{urn:hl7-org:v3}id")
    ]
    after = [
        (e.get("root"), e.get("extension"))
        for e in etree.fromstring(out).iter("{urn:hl7-org:v3}id")
    ]
    assert len(before) == len(after)
    mapping: dict[tuple, tuple] = {}
    for b, a in zip(before, after, strict=True):
        if b == (None, None):
            assert a == b
            continue
        assert a != b
        if b[1]:
            assert a[1] != b[1] and re.fullmatch(r"[0-9a-f]{16}", a[1])
        assert mapping.setdefault(b, a) == a
    assert len(set(mapping.values())) == len(mapping)
    doc_id = etree.fromstring(out).find("c:id", NS)
    assert doc_id.get("extension") == mapping[before[0]][1]


def test_codes_and_structure_unchanged(pair):
    _, original, out = pair
    rb, ra = etree.fromstring(original), etree.fromstring(out)

    def codes(root):
        return [(e.get("code"), e.get("codeSystem")) for e in root.iter() if e.get("code")]

    assert codes(ra) == codes(rb)
    assert len(codes(ra)) == original.count(b" code=")
    assert [e.tag for e in ra.iterfind(".//c:section", NS)] == [
        e.tag for e in rb.iterfind(".//c:section", NS)
    ]
    assert len(ra.findall(".//c:text//c:tr", NS)) == len(rb.findall(".//c:text//c:tr", NS))
    units_b = [e.get("unit") for e in rb.iter() if e.get("unit")]
    units_a = [e.get("unit") for e in ra.iter() if e.get("unit")]
    assert units_a == units_b
    pq_b = [e.get("value") for e in rb.iter("{urn:hl7-org:v3}value") if e.get("unit")]
    pq_a = [e.get("value") for e in ra.iter("{urn:hl7-org:v3}value") if e.get("unit")]
    assert pq_a == pq_b


def test_output_still_converts(pair):
    _, original, out = pair
    bundle_b, report_b = convert_bytes(original, "before.xml")
    bundle_a, report_a = convert_bytes(out, "after.xml")
    assert report_a.resource_counts == report_b.resource_counts
    assert len(bundle_a["entry"]) == len(bundle_b["entry"])
    patient = next(
        e["resource"] for e in bundle_a["entry"] if e["resource"]["resourceType"] == "Patient"
    )
    assert patient["name"][0]["family"] == "Testperson"
    assert patient["birthDate"].endswith("-01-01")


def test_report_has_no_residual_findings(pair):
    _, original, _ = pair
    _, report = anonymize(original, seed="fixture-seed")
    assert report.residual_findings == []
    assert report.ids_rewritten > 0
    assert report.names_rewritten > 0
    assert report.addresses_rewritten > 0
    d = report.to_dict()
    assert d["day_shift"] == report.day_shift
    assert set(d) == {
        "day_shift",
        "ids_rewritten",
        "names_rewritten",
        "telecoms_rewritten",
        "addresses_rewritten",
        "narrative_replacements",
        "residual_findings",
    }


def test_same_seed_same_bytes_and_different_seed_differs():
    data = HANDWRITTEN.read_bytes()
    a, _ = anonymize(data, seed="one")
    b, _ = anonymize(data, seed="one")
    c, _ = anonymize(data, seed="two")
    assert a == b
    assert a != c
    assert a.startswith(b"<?xml version='1.0' encoding='UTF-8'?>")


def test_narrative_phone_email_and_mrn_are_scrubbed():
    data = HANDWRITTEN.read_bytes().replace(
        b'<item ID="enc2">Hospital admission</item>',
        b'<item ID="enc2">Hospital admission, call (913) 555-0147 or jane@example.org, '
        b"MRN: 1234567, dose 500 mg, SSN-like 123456789</item>",
    )
    out, report = anonymize(data, seed="s")
    item = etree.fromstring(out).find(".//c:item[@ID='enc2']", NS).text
    assert "555-0147" not in item and "jane@example.org" not in item
    assert "MRN: 1234567" not in item
    assert "dose 500 mg" in item
    assert report.narrative_replacements >= 3
    assert any("123456789" in f for f in report.residual_findings)
    assert any("Encounters" in f for f in report.residual_findings)


def test_cli_anonymize(tmp_path, capsys):
    out = tmp_path / "anon.xml"
    rep = tmp_path / "report.json"
    rc = main(["anonymize", str(HANDWRITTEN), str(out), "--seed", "cli", "--report", str(rep)])
    assert rc == 0
    captured = capsys.readouterr()
    assert "day shift" in captured.out and "seed cli" in captured.out
    assert captured.err == ""
    expected = anonymize_file(HANDWRITTEN, tmp_path / "again.xml", seed="cli")
    assert out.read_bytes() == (tmp_path / "again.xml").read_bytes()
    assert json.loads(rep.read_text()) == expected.to_dict()


def test_cli_anonymize_warns_on_residuals(tmp_path, capsys):
    src = tmp_path / "in.xml"
    src.write_bytes(
        HANDWRITTEN.read_bytes().replace(b"Hospital admission", b"Hospital admission 987654321")
    )
    rc = main(["anonymize", str(src), str(tmp_path / "out.xml"), "--seed", "s"])
    assert rc == 0
    assert "warning" in capsys.readouterr().err


def test_cli_anonymize_error(tmp_path, capsys):
    bad = tmp_path / "bad.xml"
    bad.write_text("<nope/>")
    rc = main(["anonymize", str(bad), str(tmp_path / "out.xml")])
    assert rc == 1
    assert "error" in capsys.readouterr().err


def _days(yyyymmdd: str) -> int:
    return date(int(yyyymmdd[:4]), int(yyyymmdd[4:6]), int(yyyymmdd[6:8])).toordinal()
