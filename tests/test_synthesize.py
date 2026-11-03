"""The synthesizer keeps the document's structure and none of its clinical content."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from lxml import etree

from conftest import HANDWRITTEN, NS, SYNTHEA, component_observation_counts, section_entry_counts
from healthrecord_bridge.ccda import convert_bytes
from healthrecord_bridge.ccda.synthesize import (
    ALLERGENS,
    CONDITIONS,
    DRUGS,
    LAB_BY_CODE,
    LAB_CODED,
    LAB_PANELS,
    LAB_TESTS,
    LAB_TEXT,
    PROCEDURES,
    REACTIONS,
    SEVERITIES,
    VACCINES,
    synthesize,
    synthesize_file,
)
from healthrecord_bridge.cli import main

MARCO = next(p for p in SYNTHEA if p.name.startswith("Marco578"))
FIXTURES = [HANDWRITTEN, MARCO]
KEPT_SECTIONS = {"8716-3", "29762-2", "46240-8"}
UNKNOWN_SECTION = b"""
      <component>
        <section>
          <templateId root="2.16.840.1.113883.10.20.99.1"/>
          <code code="99999-9" codeSystem="2.16.840.1.113883.6.1" displayName="Mystery note"/>
          <title>Mystery</title>
          <text><paragraph>Patient reports a secret hobby.</paragraph></text>
          <entry>
            <observation classCode="OBS" moodCode="EVN">
              <code code="12345-6" codeSystem="2.16.840.1.113883.6.1" displayName="Secret code"/>
              <text>Secret note</text>
              <statusCode code="completed"/>
              <value xsi:type="ST">Secret value</value>
            </observation>
          </entry>
        </section>
      </component>
    </structuredBody>"""


def table_strings() -> set[str]:
    """Every display string the synthesizer can write, lowercased."""
    out: set[str] = set()
    tables = (
        DRUGS,
        CONDITIONS,
        ALLERGENS,
        REACTIONS,
        SEVERITIES,
        VACCINES,
        PROCEDURES,
        LAB_TESTS,
        LAB_PANELS,
        LAB_TEXT,
        LAB_CODED,
    )
    for table in tables:
        out.update(v.lower() for row in table for v in row if isinstance(v, str))
    return out


def content_tokens(root: etree._Element) -> set[str]:
    """Drug names, condition and lab displays and narrative cells from an input document."""
    tokens: set[str] = set()
    for sec in root.iterfind(".//c:section", NS):
        code_el = sec.find("c:code", NS)
        code = code_el.get("code") if code_el is not None else None
        if code not in KEPT_SECTIONS:
            for cell in sec.iterfind("c:text//c:td", NS):
                tokens.add((cell.text or "").strip())
            for item in sec.iterfind("c:text//c:item", NS):
                tokens.add((item.text or "").strip())
        if code == "10160-0":
            for m in sec.iterfind(".//c:manufacturedMaterial", NS):
                tokens.add(m.findtext("c:name", default="", namespaces=NS).strip())
                tokens.add(m.find("c:code", NS).get("displayName", ""))
        if code == "11450-4":
            for obs in sec.iterfind(".//c:observation", NS):
                roots = {t.get("root") for t in obs.findall("c:templateId", NS)}
                if "2.16.840.1.113883.10.20.22.4.4" in roots:
                    tokens.add(obs.find("c:value", NS).get("displayName", ""))
        if code == "30954-2":
            for c in sec.iterfind(".//c:observation/c:code", NS):
                tokens.add(c.get("displayName", ""))
    return {t for t in tokens if len(t) >= 5 and not t[0].isdigit()}


def kept_displays(root: etree._Element) -> set[str]:
    """Display names of codes the synthesizer keeps: vitals, social history, encounters."""
    out: set[str] = set()
    for sec in root.iterfind(".//c:section", NS):
        code_el = sec.find("c:code", NS)
        if code_el is not None and code_el.get("code") in KEPT_SECTIONS:
            for el in sec.iterfind(".//c:entry//c:code", NS):
                out.add(el.get("displayName", "").lower())
    return out


@pytest.fixture(params=FIXTURES, ids=lambda p: p.stem[:24])
def pair(request):
    src = request.param
    original = src.read_bytes()
    out, report = synthesize(original, seed="fixture-seed")
    return src, original, out, report


def test_same_seed_same_bytes_and_different_seed_differs():
    data = HANDWRITTEN.read_bytes()
    a, _ = synthesize(data, seed="one")
    b, _ = synthesize(data, seed="one")
    c, _ = synthesize(data, seed="two")
    assert a == b
    assert a != c
    assert a.startswith(b"<?xml version='1.0' encoding='UTF-8'?>")


def test_section_and_entry_counts_unchanged(pair, tmp_path):
    src, _, out, _ = pair
    dst = tmp_path / "out.xml"
    dst.write_bytes(out)
    assert section_entry_counts(dst) == section_entry_counts(src)
    for code in ("30954-2", "8716-3", "29762-2"):
        assert component_observation_counts(dst, code) == component_observation_counts(src, code)
    rb, ra = etree.fromstring(src.read_bytes()), etree.fromstring(out)
    assert [s.get("nullFlavor") for s in ra.iterfind(".//c:section", NS)] == [
        s.get("nullFlavor") for s in rb.iterfind(".//c:section", NS)
    ]
    assert len(ra.findall(".//c:templateId", NS)) == len(rb.findall(".//c:templateId", NS))
    assert [e.get("code") for e in ra.iter("{urn:hl7-org:v3}statusCode")] == [
        e.get("code") for e in rb.iter("{urn:hl7-org:v3}statusCode")
    ]


def test_converter_produces_same_resource_counts(pair):
    _, original, out, _ = pair
    _, before = convert_bytes(original, "before.xml")
    bundle, after = convert_bytes(out, "after.xml")
    assert after.resource_counts == before.resource_counts
    patient = next(
        e["resource"] for e in bundle["entry"] if e["resource"]["resourceType"] == "Patient"
    )
    assert patient["name"][0]["family"] == "Testperson"


def test_no_original_content_survives(pair):
    _, original, out, report = pair
    tokens = content_tokens(etree.fromstring(original))
    assert tokens
    haystack = out.decode("utf-8").lower()
    allowed = table_strings() | kept_displays(etree.fromstring(original))
    leaked = [
        t for t in tokens if t.lower() in haystack and not any(t.lower() in a for a in allowed)
    ]
    assert leaked == []
    assert report.residual_findings == []
    assert report.unrecognized_sections == []


def test_lab_values_inside_new_reference_ranges(pair):
    _, _, out, _ = pair
    root = etree.fromstring(out)
    seen = 0
    for sec in root.iterfind(".//c:section", NS):
        code = sec.find("c:code", NS)
        if code is None or code.get("code") != "30954-2":
            continue
        for obs in sec.iterfind(".//c:component/c:observation", NS):
            value = obs.find("c:value", NS)
            if value is None or value.get("value") is None:
                continue
            seen += 1
            loinc = obs.find("c:code", NS).get("code")
            test = LAB_BY_CODE[loinc]
            v = float(value.get("value"))
            assert test[3] <= v <= test[4]
            assert value.get("unit") == test[2]
            for ic in obs.findall("c:interpretationCode", NS):
                assert ic.get("code") == "N"
            rr = obs.find("c:referenceRange/c:observationRange/c:value", NS)
            if rr is not None:
                low = float(rr.find("c:low", NS).get("value"))
                high = float(rr.find("c:high", NS).get("value"))
                assert low <= v <= high
    assert seen > 0


def test_vitals_plausible(pair):
    _, _, out, _ = pair
    root = etree.fromstring(out)
    bands = {
        "8480-6": (100, 135),
        "8462-4": (55, 90),
        "29463-7": (50, 100),
        "8302-2": (150, 190),
        "39156-5": (18, 30),
        "8867-4": (55, 100),
    }
    heights = set()
    seen = 0
    for sec in root.iterfind(".//c:section", NS):
        code = sec.find("c:code", NS)
        if code is None or code.get("code") != "8716-3":
            continue
        for obs in sec.iterfind(".//c:observation", NS):
            loinc = obs.find("c:code", NS).get("code")
            value = obs.find("c:value", NS)
            if loinc in bands and value is not None and value.get("value"):
                seen += 1
                low, high = bands[loinc]
                assert low <= float(value.get("value")) <= high, loinc
            if loinc == "8302-2" and value is not None:
                heights.add(value.get("value"))
            if loinc == "72166-2":
                assert "266919005" in (value.get("code") or value.text)
    assert seen > 0
    assert len(heights) <= 1


def test_smoking_status_and_text_sections():
    out, report = synthesize(HANDWRITTEN.read_bytes(), seed="s")
    root = etree.fromstring(out)
    smoking = root.xpath(".//c:observation[c:code/@code='72166-2']/c:value", namespaces=NS)[0]
    assert smoking.get("code") == "266919005"
    assert smoking.get("displayName") == "Never smoker"
    plan = root.xpath(".//c:section[c:code/@code='18776-5']", namespaces=NS)[0]
    assert plan.find("c:text/c:paragraph", NS).text == "Narrative removed."
    enc = plan.find(".//c:encounter", NS)
    assert enc.find("c:text", NS).text == "Removed"
    assert enc.find("c:code", NS).get("code") != "185389009"
    assert enc.find("c:code", NS).get("displayName") == "Removed"
    assert report.entries_replaced["18776-5"] == 1
    assert report.entries_replaced["10160-0"] == 3
    imm = root.xpath(".//c:section[c:code/@code='11369-6']//c:manufacturedMaterial", namespaces=NS)[
        0
    ]
    assert imm.find("c:lotNumberText", NS).text != "FLU2023-AB12"
    assert imm.getparent().find("c:manufacturerOrganization/c:name", NS).text is None


def test_narrative_ids_still_resolve(pair):
    _, _, out, _ = pair
    root = etree.fromstring(out)
    ids = [el.get("ID") for el in root.iter() if el.get("ID")]
    assert len(ids) == len(set(ids))
    for ref in root.iter("{urn:hl7-org:v3}reference"):
        target = (ref.get("value") or "").lstrip("#")
        if target:
            assert target in ids, target
    sig = root.find(".//*[@ID='med1-sig']", NS)
    if sig is not None:
        assert sig.text.startswith(("Take", "Inject", "Inhale"))


def test_unknown_section_is_blanked_and_reported():
    data = HANDWRITTEN.read_bytes().replace(b"    </structuredBody>", UNKNOWN_SECTION)
    out, report = synthesize(data, seed="s")
    text = out.decode("utf-8")
    assert "Secret" not in text and "secret" not in text
    sec = etree.fromstring(out).xpath(".//c:section[c:code/@code='99999-9']", namespaces=NS)[0]
    assert sec.find("c:text/c:paragraph", NS).text == "Narrative removed."
    obs = sec.find(".//c:observation", NS)
    assert obs.find("c:text", NS).text == "Removed"
    assert obs.find("c:value", NS).text == "Removed"
    assert obs.find("c:code", NS).get("displayName") == "Removed"
    assert obs.find("c:code", NS).get("code") != "12345-6"
    assert report.unrecognized_sections == [{"code": "99999-9", "title": "Mystery", "entries": 1}]
    assert report.residual_findings == []
    d = report.to_dict()
    assert set(d) == {"anonymize", "entries_replaced", "unrecognized_sections", "residual_findings"}
    assert d["anonymize"]["day_shift"] == report.anonymize.day_shift
    assert "unrecognized sections 1" in report.summary()


def test_residual_findings_report_leftover_text():
    data = HANDWRITTEN.read_bytes().replace(
        b"<title>Vital Signs</title>", b"<title>Vital Signs, lisinopril 10 MG tablet</title>"
    )
    _, report = synthesize(data, seed="s")
    assert any("lisinopril 10 MG tablet" in f and "/title" in f for f in report.residual_findings)


def test_cli_synthesize(tmp_path, capsys):
    out = tmp_path / "syn.xml"
    rep = tmp_path / "report.json"
    rc = main(["synthesize", str(HANDWRITTEN), str(out), "--seed", "cli", "--report", str(rep)])
    assert rc == 0
    captured = capsys.readouterr()
    assert "entries replaced" in captured.out and "seed cli" in captured.out
    assert captured.err == ""
    expected = synthesize_file(HANDWRITTEN, tmp_path / "again.xml", seed="cli")
    assert out.read_bytes() == (tmp_path / "again.xml").read_bytes()
    assert json.loads(rep.read_text()) == expected.to_dict()


def test_cli_synthesize_warns(tmp_path, capsys):
    src = tmp_path / "in.xml"
    src.write_bytes(HANDWRITTEN.read_bytes().replace(b"    </structuredBody>", UNKNOWN_SECTION))
    rc = main(["synthesize", str(src), str(tmp_path / "out.xml"), "--seed", "s"])
    assert rc == 0
    err = capsys.readouterr().err
    assert "warning" in err and "99999-9" in err and "Mystery" in err


def test_cli_synthesize_error(tmp_path, capsys):
    bad = tmp_path / "bad.xml"
    bad.write_text("<nope/>")
    rc = main(["synthesize", str(bad), str(tmp_path / "out.xml")])
    assert rc == 1
    assert "error" in capsys.readouterr().err


def test_random_seed_when_none():
    data = Path(HANDWRITTEN).read_bytes()
    a, _ = synthesize(data)
    b, _ = synthesize(data)
    assert a != b
