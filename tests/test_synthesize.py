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
NS_SDTC = {"sdtc": "urn:hl7-org:sdtc"}
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
PATIENT_NOTE = b"""
      <component>
        <section>
          <code code="X-CE-PFD" codeSystem="1.2.840.114350.1.72.2" displayName="Note"/>
          <title>Note from Dr Example</title>
          <text><paragraph>Dear Jane, your potassium was high again.</paragraph></text>
        </section>
      </component>
    </structuredBody>"""
SPECIALTY = b"""
  <documentationOf>
    <serviceEvent classCode="PCPR">
      <performer typeCode="PRF">
        <assignedEntity>
          <id root="2.16.840.1.113883.4.6" extension="1234567893"/>
          <code code="207R00000X" codeSystem="2.16.840.1.113883.6.101"
              displayName="Internal Medicine">
            <originalText>Internal Medicine</originalText>
            <translation code="17" codeSystem="1.2.840.114350.1.13.362.2.7.10.836982.1050"
                displayName="Internal Medicine"/>
          </code>
        </assignedEntity>
      </performer>
    </serviceEvent>
  </documentationOf>
  <documentationOf>"""


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


def test_demographics_are_neutralized():
    data = HANDWRITTEN.read_bytes().replace(
        b'<administrativeGenderCode code="F" codeSystem="2.16.840.1.113883.5.1" '
        b'displayName="Female"/>',
        b'<administrativeGenderCode nullFlavor="ASKU"><originalText>Declined</originalText>'
        b"</administrativeGenderCode>"
        b'<religiousAffiliationCode code="1013" codeSystem="2.16.840.1.113883.5.1076" '
        b'codeSystemName="ReligiousAffiliation" displayName="Christian"/>',
    )
    out, report = synthesize(data, seed="s")
    text = out.decode("utf-8")
    for token in ("White", "European", "Christian", "Married", "Declined"):
        assert token not in text, token
    patient = etree.fromstring(out).find(".//c:recordTarget/c:patientRole/c:patient", NS)
    for race in patient.findall("c:raceCode", NS) + patient.findall("sdtc:raceCode", NS_SDTC):
        assert race.get("code") == "2131-1" and race.get("displayName") == "Other Race"
        assert race.get("codeSystem") == "2.16.840.1.113883.6.238"
    assert len(patient.findall("sdtc:raceCode", NS_SDTC)) == 1
    ethnic = patient.find("c:ethnicGroupCode", NS)
    assert ethnic.get("code") == "2186-5" and ethnic.get("displayName") == "Not Hispanic or Latino"
    religion = patient.find("c:religiousAffiliationCode", NS)
    assert dict(religion.attrib) == {"nullFlavor": "UNK"}
    marital = patient.find("c:maritalStatusCode", NS)
    assert marital.get("code") == "U" and marital.get("displayName") == "Unknown"
    assert marital.get("codeSystem") == "2.16.840.1.113883.5.2"
    gender = patient.find("c:administrativeGenderCode", NS)
    assert dict(gender.attrib) == {
        "code": "UN",
        "codeSystem": "2.16.840.1.113883.5.1",
        "displayName": "Undifferentiated",
    }
    assert len(gender) == 0
    assert patient.find("c:languageCommunication/c:languageCode", NS).get("code") == "en"
    assert report.residual_findings == []


def test_gender_with_code_is_kept():
    out, _ = synthesize(HANDWRITTEN.read_bytes(), seed="s")
    gender = etree.fromstring(out).find(".//c:patient/c:administrativeGenderCode", NS)
    assert gender.get("code") == "F" and gender.get("displayName") == "Female"


def test_birth_year_in_range_and_seed_stable():
    data = HANDWRITTEN.read_bytes()
    years = set()
    for seed in ("a", "b", "c", "d", "e", "f"):
        out, _ = synthesize(data, seed=seed)
        again, _ = synthesize(data, seed=seed)
        assert out == again
        value = etree.fromstring(out).find(".//c:patient/c:birthTime", NS).get("value")
        assert len(value) == 8 and value[4:] == "0101"
        assert 2024 - 70 <= int(value[:4]) <= 2024 - 25
        years.add(value[:4])
    assert len(years) > 1
    data = data.replace(b'<birthTime value="19840722"/>', b'<birthTime value="19840722143000"/>')
    out, _ = synthesize(data, seed="a")
    value = etree.fromstring(out).find(".//c:patient/c:birthTime", NS).get("value")
    assert len(value) == 14 and value[4:] == "0101143000"


def test_specialty_text_is_removed_and_codes_kept():
    data = HANDWRITTEN.read_bytes().replace(b"  <documentationOf>", SPECIALTY, 1)
    out, report = synthesize(data, seed="s")
    assert b"Internal Medicine" not in out
    code = etree.fromstring(out).find(".//c:performer[@typeCode='PRF']/c:assignedEntity/c:code", NS)
    assert code.get("code") == "207R00000X" and code.get("displayName") == "Removed"
    assert code.find("c:originalText", NS).text == "Removed"
    translation = code.find("c:translation", NS)
    assert translation.get("code") == "17" and translation.get("displayName") == "Removed"
    assert translation.get("codeSystem") == "1.2.840.114350.1.13.0.2.7.10.836982.1050"
    assert report.residual_findings == []


VACCINE_150 = b'<code code="150" codeSystem="2.16.840.1.113883.12.292"'
SNOMED_TRANSLATION = (
    b'<translation code="415070008" codeSystem="2.16.840.1.113883.6.96"'
    b' displayName="Percutaneous coronary intervention"/>'
)
SIG = (
    b'<entryRelationship typeCode="SUBJ" inversionInd="true">'
    b'<substanceAdministration classCode="SBADM" moodCode="INT">'
    b'<templateId root="2.16.840.1.113883.10.20.22.4.147"/>'
    b'<code code="76662-6" codeSystem="2.16.840.1.113883.6.1"'
    b' displayName="Medication Instructions"/>'
    b"<text>Take with food.</text><consumable><manufacturedProduct>"
    b'<manufacturedLabeledDrug nullFlavor="NA"/></manufacturedProduct></consumable>'
    b"</substanceAdministration></entryRelationship></substanceAdministration>"
)


def vaccine_code(root: etree._Element) -> etree._Element:
    path = ".//c:section[c:code/@code='11369-6']//c:manufacturedMaterial/c:code"
    return root.xpath(path, namespaces=NS)[0]


def test_translations_follow_the_primary_code_or_are_hashed():
    data = HANDWRITTEN.read_bytes()
    start = data.index(VACCINE_150)
    end = data.index(b"/>", start)
    data = data[:end] + b">" + SNOMED_TRANSLATION + b"</code>" + data[end + 2 :]
    out, report = synthesize(data, seed="s")
    assert report.residual_findings == []
    root = etree.fromstring(out)
    vaccine = vaccine_code(root)
    assert vaccine.get("codeSystem") == "2.16.840.1.113883.12.292"
    translation = vaccine.find("c:translation", NS)
    assert translation.get("codeSystem") == "2.16.840.1.113883.6.96"
    assert len(translation.get("code")) == 12 and translation.get("displayName") == "Removed"
    assert b"Percutaneous" not in out
    path = ".//c:section[c:code/@code='47519-4']//c:procedure/c:code"
    procedure = root.xpath(path, namespaces=NS)[0]
    cpt = procedure.get("code")
    snomed = procedure.find("c:translation[@codeSystem='2.16.840.1.113883.6.96']", NS)
    assert (cpt, snomed.get("code"), snomed.get("displayName")) in PROCEDURES
    assert snomed.get("displayName") == procedure.get("displayName")


def test_null_vaccine_code_hashes_its_translation_and_keeps_sig_code():
    data = HANDWRITTEN.read_bytes()
    start = data.index(VACCINE_150)
    end = data.index(b"/>", start) + 2
    null_code = b'<code nullFlavor="OTH">' + SNOMED_TRANSLATION + b"</code>"
    data = data[:start] + null_code + data[end:]
    data = data.replace(b"</substanceAdministration>", SIG, 1)
    out, report = synthesize(data, seed="s")
    assert report.residual_findings == []
    root = etree.fromstring(out)
    vaccine = vaccine_code(root)
    assert vaccine.get("nullFlavor") == "OTH" and vaccine.get("code") is None
    translation = vaccine.find("c:translation", NS)
    assert translation.get("codeSystem") == "2.16.840.1.113883.6.96"
    assert len(translation.get("code")) == 12 and translation.get("displayName") == "Removed"
    assert b"Percutaneous" not in out
    sig_code = root.xpath(".//c:substanceAdministration/c:code[@code='76662-6']", namespaces=NS)
    assert len(sig_code) == 1 and sig_code[0].get("displayName") == "Medication Instructions"
    assert b"Take with food" not in out


def test_unplaced_narrative_ids_land_on_named_content(pair):
    _, _, out, _ = pair
    root = etree.fromstring(out)
    contents = [el for el in root.iter("{urn:hl7-org:v3}content") if el.get("ID")]
    for content in contents:
        assert content.text and content.text.strip()
        assert content.text == content.getparent().getparent().find("c:td", NS).text


def test_patient_facing_note_is_blanked_without_report():
    data = HANDWRITTEN.read_bytes().replace(b"    </structuredBody>", PATIENT_NOTE)
    out, report = synthesize(data, seed="s")
    assert b"potassium" not in out
    sec = etree.fromstring(out).xpath(".//c:section[c:code/@code='X-CE-PFD']", namespaces=NS)[0]
    assert sec.find("c:text/c:paragraph", NS).text == "Narrative removed."
    assert report.unrecognized_sections == []
    assert report.entries_replaced["X-CE-PFD"] == 0


def test_residual_check_ignores_anonymizer_substitutes():
    data = HANDWRITTEN.read_bytes().replace(
        b'<item ID="enc2">Hospital admission</item>',
        b'<item ID="enc2">Hospital admission of Jane Sampleton at Example Health System, '
        b"seen by Robert Clinician (NPI 1234567890), 123 Example St, Springfield</item>",
    )
    _, report = synthesize(data, seed="s")
    assert report.residual_findings == []
    assert report.anonymize.residual_findings == []


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
