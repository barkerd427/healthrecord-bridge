"""Epic result shapes on hand-built snippets: reused ids, ED values and null-coded names."""

from __future__ import annotations

from conftest import by_type
from healthrecord_bridge.ccda import convert_bytes
from healthrecord_bridge.ccda.ids import CdaId, resource_id

EPIC_LRR = "1.2.840.114350.1.13.0.2.7.2.768282"
DOCUMENT = """<?xml version="1.0" encoding="UTF-8"?>
<ClinicalDocument xmlns="urn:hl7-org:v3" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <templateId root="2.16.840.1.113883.10.20.22.1.2"/>
  <id root="1.2.3.4" extension="DOC-1"/>
  <code code="34133-9" codeSystem="2.16.840.1.113883.6.1"/>
  <title>Snippet</title>
  <effectiveTime value="20260301"/>
  <recordTarget>
    <patientRole>
      <id root="1.2.3.4.5" extension="P-1"/>
      <patient>
        <name><given>Alex</given><family>Testperson</family></name>
        <administrativeGenderCode code="F" codeSystem="2.16.840.1.113883.5.1"/>
        <birthTime value="19800101"/>
      </patient>
    </patientRole>
  </recordTarget>
  <component><structuredBody><component>
    <section>
      <templateId root="2.16.840.1.113883.10.20.22.2.3.1"/>
      <code code="30954-2" codeSystem="2.16.840.1.113883.6.1"/>
      <title>Results</title>
      <text><table><tbody><tr>{narrative}</tr></tbody></table></text>
      {entries}
    </section>
  </component></structuredBody></component>
</ClinicalDocument>
"""


def organizer(org_id: str, *observations: str) -> str:
    comps = "".join(f"<component>{o}</component>" for o in observations)
    return (
        '<entry><organizer classCode="BATTERY" moodCode="EVN">'
        f'<id root="9.9" extension="{org_id}"/>'
        '<code code="24323-8" codeSystem="2.16.840.1.113883.6.1" displayName="CMP"/>'
        '<statusCode code="completed"/><effectiveTime value="20260301"/>'
        f"{comps}</organizer></entry>"
    )


def observation(obs_id: str, code: str, value: str = "") -> str:
    return (
        '<observation classCode="OBS" moodCode="EVN">'
        f'<id root="9.9" extension="{obs_id}"/>{code}'
        '<statusCode code="completed"/><effectiveTime value="20260301"/>'
        f"{value}</observation>"
    )


def loinc(code: str) -> str:
    return f'<code code="{code}" codeSystem="2.16.840.1.113883.6.1"/>'


def document(entries: str, narrative: str = "") -> bytes:
    return DOCUMENT.format(entries=entries, narrative=narrative).encode("utf-8")


def labs(bundle: dict) -> list[dict]:
    return by_type(bundle)["Observation"]


def test_one_cda_id_on_two_observations_keeps_both():
    pq = '<value xsi:type="PQ" value="100" unit="mmol/L"/>'
    data = document(
        organizer("ORG-1", observation("SHARED", loinc("2075-0"), pq))
        + organizer("ORG-2", observation("SHARED", loinc("2885-2"), pq))
    )
    bundle, report = convert_bytes(data, "snippet.xml")
    again, _ = convert_bytes(data, "snippet.xml")
    assert bundle == again
    types = by_type(bundle)
    assert report.resource_counts["Observation"] == len(types["Observation"]) == 2
    chloride, protein = types["Observation"]
    assert chloride["id"] == resource_id("Observation", CdaId("9.9", "SHARED"))
    assert protein["id"] == resource_id("Observation", CdaId("9.9", "SHARED"), "30954-2", 1, 0)
    assert chloride["identifier"] == protein["identifier"]
    reports = types["DiagnosticReport"]
    assert reports[0]["result"] == [{"reference": f"Observation/{chloride['id']}"}]
    assert reports[1]["result"] == [{"reference": f"Observation/{protein['id']}"}]
    ids = [e["resource"]["id"] for e in bundle["entry"]]
    assert len(ids) == len(set(ids))


def test_organizer_id_reused_on_its_component_stays_plain():
    data = document(organizer("ORG-1", observation("ORG-1", loinc("718-7"))))
    bundle, _ = convert_bytes(data, "snippet.xml")
    types = by_type(bundle)
    assert types["DiagnosticReport"][0]["id"] == resource_id(
        "DiagnosticReport", CdaId("9.9", "ORG-1")
    )
    assert types["Observation"][0]["id"] == resource_id("Observation", CdaId("9.9", "ORG-1"))


def test_ed_value_by_reference_becomes_value_string():
    narrative = '<td ID="r1">No growth after 48 hours</td><td ID="r2"></td>'
    by_ref = '<value xsi:type="ED"><reference value="#r1"/></value>'
    empty = '<value xsi:type="ED"><reference value="#r2"/></value>'
    inline = '<value xsi:type="ED">Normal flora</value>'
    data = document(
        organizer(
            "ORG-1",
            observation("A", loinc("600-7"), by_ref),
            observation("B", loinc("630-4"), empty),
            observation("C", loinc("634-6"), inline),
        ),
        narrative,
    )
    bundle, _ = convert_bytes(data, "snippet.xml")
    a, b, c = labs(bundle)
    assert a["valueString"] == "No growth after 48 hours"
    assert "valueString" not in b
    assert b["dataAbsentReason"]["coding"][0]["code"] == "unknown"
    assert c["valueString"] == "Normal flora"


def test_null_coded_lab_keeps_its_narrative_name():
    narrative = '<td ID="n1">Hemoglobin A1c</td>'
    null_code = (
        '<code nullFlavor="UNK" codeSystem="2.16.840.1.113883.6.1">'
        '<originalText><reference value="#n1"/></originalText>'
        f'<translation code="123456" codeSystem="{EPIC_LRR}" displayName="HBA1C"/></code>'
    )
    with_display = (
        '<code code="4548-4" codeSystem="2.16.840.1.113883.6.1"'
        ' displayName="Hemoglobin A1c/Hemoglobin.total">'
        "<originalText>A1C</originalText></code>"
    )
    data = document(
        organizer("ORG-1", observation("A", null_code), observation("B", with_display)), narrative
    )
    bundle, report = convert_bytes(data, "snippet.xml")
    a, b = labs(bundle)
    assert a["code"] == {
        "coding": [{"system": f"urn:oid:{EPIC_LRR}", "code": "123456", "display": "HBA1C"}],
        "text": "Hemoglobin A1c",
    }
    assert b["code"]["text"] == "A1C"
    assert b["code"]["coding"][0]["display"] == "Hemoglobin A1c/Hemoglobin.total"
    assert EPIC_LRR in report.unmapped_code_systems
