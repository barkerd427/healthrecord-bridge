"""The synthetic Epic MyChart export converts, and Epic's structure is handled as documented.

Resource counts, section lists and code systems are hard-coded from one observed run so
that any change in what the converter makes of a real Epic layout shows up here.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

import pytest
from lxml import etree

from conftest import EPIC, NS, by_type, component_observation_counts, section_entry_counts
from healthrecord_bridge.ccda import convert, convert_bytes
from healthrecord_bridge.ccda.document import CdaDocument
from healthrecord_bridge.ccda.ids import CdaId, resource_id
from healthrecord_bridge.ccda.sections import KNOWN_UNMAPPED
from healthrecord_bridge.cli import main

RXNORM = "http://www.nlm.nih.gov/research/umls/rxnorm"
NDC = "http://hl7.org/fhir/sid/ndc"
NDDF = "urn:oid:2.16.840.1.113883.6.208"
EPIC_EAP = "urn:oid:1.2.840.114350.1.13.0.2.7.2.696580"
EPIC_LRR = "urn:oid:1.2.840.114350.1.13.0.2.7.2.768282"
EPIC_RESULT_TEXT = "urn:oid:1.2.840.114350.1.72.1.5220"
EPIC_OBS_ROOT = "1.2.840.114350.1.13.0.2.7.3.696580.52175"
IMO_PROBLEM_IT = "urn:oid:2.16.840.1.113883.3.247.1.1"
EPIC_CUSTOMER = re.compile(r"1\.2\.840\.114350\.1\.13\.(\d+)")

EXPECTED_COUNTS = {
    "AllergyIntolerance": 1,
    "Condition": 4,
    "DiagnosticReport": 11,
    "DocumentReference": 1,
    "Immunization": 1,
    "MedicationRequest": 5,
    "Observation": 151,
    "Organization": 1,
    "Patient": 1,
    "Procedure": 4,
    "Provenance": 1,
}
SECTION_ORDER = [
    "X-CE-PFD",
    "48765-2",
    "10160-0",
    "11450-4",
    "11369-6",
    "29762-2",
    "8716-3",
    "46264-8",
    "47519-4",
    "30954-2",
    "85847-2",
]
ENTRY_COUNTS = {
    "X-CE-PFD": 0,
    "48765-2": 1,
    "10160-0": 5,
    "11450-4": 4,
    "11369-6": 1,
    "29762-2": 9,
    "8716-3": 5,
    "46264-8": 0,
    "47519-4": 4,
    "30954-2": 13,
    "85847-2": 1,
}
RESULT_ORGANIZERS = 13
RESULT_COMPONENTS = 148
NARRATIVE_REFS = 341
UNMAPPED_CODE_SYSTEMS = [
    "1.2.840.114350.1.13.0.2.7.10.696580.52175",
    "1.2.840.114350.1.13.0.2.7.2.696580",
    "1.2.840.114350.1.13.0.2.7.2.768282",
    "1.2.840.114350.1.72.1.5220",
    "2.16.840.1.113883.3.247.1.1",
    "2.16.840.1.113883.6.208",
]


@pytest.fixture(scope="module")
def converted() -> tuple[dict, object]:
    return convert(EPIC)


@pytest.fixture(scope="module")
def root() -> etree._Element:
    return etree.parse(str(EPIC)).getroot()


def section(root: etree._Element, code: str) -> etree._Element:
    return root.xpath(f".//c:section[c:code/@code='{code}']", namespaces=NS)[0]


def labs(bundle: dict) -> list[dict]:
    return [
        o
        for o in by_type(bundle).get("Observation", [])
        if o["category"][0]["coding"][0]["code"] == "laboratory"
    ]


def narrative_ids_and_refs(root: etree._Element) -> tuple[set[str], list[str]]:
    ids = [el.get("ID") for el in root.iter() if el.get("ID")]
    assert len(ids) == len(set(ids))
    refs = [r.get("value") for r in root.iter("{urn:hl7-org:v3}reference") if r.get("value")]
    return set(ids), refs


def test_section_set_and_order(root):
    codes = [s.find("c:code", NS).get("code") for s in root.iterfind(".//c:section", NS)]
    assert codes == SECTION_ORDER
    assert section_entry_counts(EPIC) == ENTRY_COUNTS
    roots = {t.get("root") for t in root.findall("c:templateId", NS)}
    assert "1.2.840.114350.1.72.1.51693" in roots
    assert "2.16.840.1.113883.10.20.22.1.2" in roots
    pfd = section(root, "X-CE-PFD")
    assert pfd.find("c:code", NS).get("codeSystem") == "1.2.840.114350.1.72.2"
    assert pfd.find("c:templateId", NS) is None
    device = root.find("c:author/c:assignedAuthor/c:assignedAuthoringDevice", NS)
    assert device.find("c:softwareName", NS).text.startswith("Epic")


def test_one_patient_and_resource_counts(converted):
    bundle, report = converted
    types = by_type(bundle)
    assert {k: len(v) for k, v in types.items()} == EXPECTED_COUNTS
    assert len(bundle["entry"]) == sum(EXPECTED_COUNTS.values())
    assert len(report.documents) == 1
    patient = types["Patient"][0]
    assert [n["use"] for n in patient["name"]] == ["official", "nickname"]
    assert patient["name"][0]["family"] == "Testperson"
    assert patient["gender"] == "other"
    assert patient["birthDate"].endswith("-01-01")
    assert patient["identifier"][0]["type"]["coding"][0]["code"] == "MR"
    assert patient["identifier"][0]["system"].startswith("urn:oid:1.2.840.114350.1.13.0.")
    assert patient["managingOrganization"] == {"display": "Example Health System"}
    assert len(types["Organization"]) == 1


def test_report_has_no_failures(converted, root):
    _, report = converted
    doc = report.documents[0]
    assert doc.notes == []
    assert [s.name for s in doc.sections] == [
        "Allergies",
        "Medications",
        "Problems",
        "Immunizations",
        "Social History",
        "Vital Signs",
        "Procedures",
        "Results",
    ]
    for s in doc.sections:
        assert s.null_flavor is None
        assert s.entries_seen == ENTRY_COUNTS[s.code]
        if s.name != "Results":
            assert s.skipped == [], s.name
            assert s.resources_produced >= s.entries_seen
    results = doc.section("Results")
    skipped = [(k.reason, k.ordinal) for k in results.skipped]
    assert skipped == [
        ("organizer has no codable observations", 11),
        ("organizer has no codable observations", 12),
    ]
    organizers = section(root, "30954-2").findall("c:entry/c:organizer", NS)
    for ordinal in (11, 12):
        for obs in organizers[ordinal].findall("c:component/c:observation", NS):
            code = obs.find("c:code", NS)
            assert code.get("nullFlavor") == "UNK" and len(code) == 0
    assert results.resources_produced == 145


def test_unmapped_sections_are_reported(converted, root):
    bundle, report = converted
    doc = report.documents[0]
    unknown = [(u.code, u.title, u.entries) for u in doc.unknown_sections]
    assert unknown == [
        ("X-CE-PFD", "Note from Example Health System", 0),
        ("46264-8", "Medical Devices", 0),
        ("85847-2", "Care Teams", 1),
    ]
    for code, _, _ in unknown:
        assert code in KNOWN_UNMAPPED
    organizer = section(root, "85847-2").find("c:entry/c:organizer", NS)
    assert {t.get("root") for t in organizer.findall("c:templateId", NS)} == {
        "2.16.840.1.113883.10.20.22.4.500"
    }
    assert organizer.find("c:component/c:act", NS).get("classCode") == "PCPR"
    assert set(by_type(bundle)) == set(EXPECTED_COUNTS)
    text = report.format()
    assert "not mapped in this version:" in text
    assert "85847-2    Care Teams (1 entries)" in text
    assert "X-CE-PFD   Note from Example Health System (0 entries)" in text
    assert "46264-8    Medical Devices (0 entries)" in text


def test_results_become_reports_and_observations(converted):
    bundle, report = converted
    types = by_type(bundle)
    assert component_observation_counts(EPIC, "30954-2") == (RESULT_ORGANIZERS, RESULT_COMPONENTS)
    reports = types["DiagnosticReport"]
    skipped = len(report.documents[0].section("Results").skipped)
    assert len(reports) == RESULT_ORGANIZERS - skipped
    assert [len(dr["result"]) for dr in reports] == [11, 11, 11, 6, 1, 1, 1, 8, 4, 31, 49]
    lab = labs(bundle)
    lab_ids = {o["id"] for o in lab}
    assert {ref["reference"].split("/")[1] for dr in reports for ref in dr["result"]} == lab_ids
    for dr in reports:
        assert dr["status"] == "final"
        assert dr["category"][0]["coding"][0]["code"] == "LAB"
        assert dr.get("performer", [{"display": "Example Health System"}]) == [
            {"display": "Example Health System"}
        ]
        systems = [c["system"] for c in dr["code"]["coding"]]
        assert systems[-1] == EPIC_EAP
    assert sum(1 for dr in reports if "performer" in dr) == 9
    assert reports[0]["code"]["coding"][0] == {"system": "http://loinc.org", "code": "24323-8"}
    assert reports[0]["code"]["text"] == "Comprehensive metabolic 2000 panel - Serum or Plasma"
    assert "effectivePeriod" in reports[0]
    # Three text-only reports have a null organizer code and keep just the Epic order id.
    assert [dr["code"]["coding"][0]["system"] for dr in reports[4:7]] == [EPIC_EAP] * 3
    systems = Counter(tuple(c["system"] for c in o["code"]["coding"]) for o in lab)
    assert systems == {(EPIC_LRR,): 109, ("http://loinc.org",): 19, (EPIC_RESULT_TEXT,): 6}
    values = Counter(next((k for k in o if k.startswith("value")), "none") for o in lab)
    assert values["valueQuantity"] == 119
    # Six ED values reference a narrative block and come through as strings.
    assert values["valueString"] == 6
    text_only = [o for o in lab if o["code"]["coding"][0]["system"] == EPIC_RESULT_TEXT]
    assert all("valueString" in o for o in text_only)
    absent = sum(1 for o in lab if "dataAbsentReason" in o)
    assert absent == 9
    assert values["none"] == absent
    # Null LOINC codes keep the narrative name as text next to the Epic-local translation.
    null_coded = [o for o in lab if o["code"]["coding"][0]["system"] == EPIC_LRR]
    assert all(o["code"]["coding"][0]["display"] == "Removed" for o in null_coded)
    assert all(o["code"]["text"] for o in null_coded)
    assert sum(1 for o in lab if "referenceRange" in o) == 69
    assert all("interpretation" not in o for o in lab)
    ranged = next(o for o in lab if "referenceRange" in o)
    assert ranged["referenceRange"][0]["text"]


def test_component_ids_reused_by_epic_stay_distinct(converted, root):
    """Epic reuses CDA ids across result observations; each still gets its own resource."""
    bundle, report = converted
    ids = Counter(
        (i.get("root"), i.get("extension"))
        for i in section(root, "30954-2").iterfind(
            "c:entry/c:organizer/c:component/c:observation/c:id", NS
        )
    )
    duplicated = sorted(ext for (_, ext), n in ids.items() if n > 1)
    assert len(duplicated) == 5
    organizers = section(root, "30954-2").findall("c:entry/c:organizer", NS)
    organizer_ids = {o.find("c:id", NS).get("extension") for o in organizers}
    assert len(set(duplicated) & organizer_ids) == 4
    types = by_type(bundle)
    assert report.resource_counts == {k: len(v) for k, v in types.items()}
    resource_ids = [e["resource"]["id"] for e in bundle["entry"]]
    assert len(resource_ids) == len(set(resource_ids))
    by_id = {o["id"]: o for o in types["Observation"]}
    reports = iter(types["DiagnosticReport"])
    for organizer in organizers:
        expected = []
        for obs in organizer.findall("c:component/c:observation", NS):
            code = obs.find("c:code", NS)
            codes = [code.get("code"), *(t.get("code") for t in code.findall("c:translation", NS))]
            if any(codes):
                expected.append(next(c for c in codes if c))
        if not expected:
            continue
        dr = next(reports)
        got = [
            by_id[r["reference"].split("/")[1]]["code"]["coding"][0]["code"] for r in dr["result"]
        ]
        assert got == expected
    # One id sits on two LOINC-coded observations in different organizers.
    ext = next(ext for (root_oid, ext), n in ids.items() if n > 1 and root_oid == EPIC_OBS_ROOT)
    shared = [o for o in types["Observation"] if o["identifier"][0]["value"] == ext]
    placed = [(9, 30), (10, 48)]
    assert [o["code"]["coding"][0]["code"] for o in shared] == [
        organizers[i].findall("c:component/c:observation", NS)[j].find("c:code", NS).get("code")
        for i, j in placed
    ]
    assert shared[0]["id"] == resource_id("Observation", CdaId(EPIC_OBS_ROOT, ext))
    assert shared[1]["id"] == resource_id(
        "Observation", CdaId(EPIC_OBS_ROOT, ext), "30954-2", 10, 48
    )


def test_medications_keep_rxnorm_and_translations(converted, root):
    bundle, report = converted
    meds = by_type(bundle)["MedicationRequest"]
    material = "c:consumable/c:manufacturedProduct/c:manufacturedMaterial/c:code"
    xml_codes = [
        m.get("code")
        for m in section(root, "10160-0").iterfind(
            f"c:entry/c:substanceAdministration/{material}", NS
        )
    ]
    assert len(xml_codes) == 5
    # Epic nests supply orders under the administration; they must not become extra resources.
    supply = "c:supply/c:product/c:manufacturedProduct/c:manufacturedMaterial/c:code"
    nested = section(root, "10160-0").findall(f".//c:entryRelationship/{supply}", NS)
    assert len(nested) == 3
    assert [m["medicationCodeableConcept"]["coding"][0]["code"] for m in meds] == xml_codes
    for m in meds:
        concept = m["medicationCodeableConcept"]
        assert [c["system"] for c in concept["coding"]] == [RXNORM, NDC, NDDF]
        assert concept["text"].endswith(("Tablet", "Capsule"))
        assert m["status"] == "active" and m["intent"] == "plan"
        assert m["authoredOn"].startswith("2026-07-10T")
        dosage = m["dosageInstruction"][0]
        assert dosage["text"].startswith("Take 1 tablet by mouth")
        assert dosage["route"]["coding"][0]["code"] == "C38288"
        assert dosage["timing"]["repeat"]["periodUnit"] == "d"
    assert meds[0]["medicationCodeableConcept"]["text"] == "atorvastatin 80 MG Oral Tablet"
    assert "2.16.840.1.113883.6.208" in report.unmapped_code_systems
    assert "2.16.840.1.113883.6.69" not in report.unmapped_code_systems


def test_narrative_references_resolve(root):
    ids, refs = narrative_ids_and_refs(root)
    assert len(ids) == 315 and len(refs) == NARRATIVE_REFS
    assert all(ref.lstrip("#") in ids for ref in refs)
    doc = CdaDocument.from_path(EPIC)
    assert all(doc.narrative.resolve(ref) for ref in refs)
    assert doc.narrative.resolve("#med5") == "atorvastatin 80 MG Oral Tablet"
    assert doc.narrative.resolve("#sig5") == "Take 1 tablet by mouth at bedtime."
    assert doc.narrative.resolve("#nof3") == "No known allergies"
    # Epic builds result narrative ids out of its own OIDs; the customer number is 0 there too.
    result_refs = [r for r in refs if r.startswith("#Result.")]
    assert result_refs
    assert all(r.startswith("#Result.1.2.840.114350.1.13.0.") for r in result_refs)


def test_epic_code_systems_carry_customer_zero(converted, root):
    _, report = converted
    customers = set(EPIC_CUSTOMER.findall(EPIC.read_text(encoding="utf-8")))
    assert customers == {"0"}
    assert report.unmapped_code_systems == UNMAPPED_CODE_SYSTEMS
    names = {
        el.get("codeSystemName")
        for el in root.iter()
        if el.get("codeSystem", "").startswith("1.2.840.114350.")
    }
    assert {"Epic.EAP.ID", "Epic.LRR.ID", "Epic.ResultText", "Epic.SER.ProviderSpecialty"} <= names
    epic_templates = {
        t.get("root")
        for t in root.iter("{urn:hl7-org:v3}templateId")
        if t.get("root", "").startswith("1.2.840.114350.")
    }
    assert len(epic_templates) == 6


def test_other_sections_map_epic_shapes(converted, root):
    bundle, _ = converted
    types = by_type(bundle)
    observations = types["Observation"]
    vitals = [o for o in observations if o["category"][0]["coding"][0]["code"] == "vital-signs"]
    assert component_observation_counts(EPIC, "8716-3") == (5, 8)
    assert len(vitals) == 8
    assert all(o["code"]["coding"][0]["system"] == "http://loinc.org" for o in vitals)
    assert all(o["code"]["text"] == "Vital sign" and "valueQuantity" in o for o in vitals)
    social = [o for o in observations if o["category"][0]["coding"][0]["code"] == "social-history"]
    assert len(social) == 9
    social_systems = {o["code"]["coding"][0]["system"] for o in social}
    assert social_systems == {"http://loinc.org", "http://snomed.info/sct"}
    smoking = next(o for o in social if o["code"]["coding"][0]["code"] == "72166-2")
    assert smoking["valueCodeableConcept"]["coding"][0]["display"] == "Never smoker"
    allergy = types["AllergyIntolerance"][0]
    assert allergy["verificationStatus"]["coding"][0]["code"] == "refuted"
    assert allergy["note"] == [{"text": "No known allergies"}]
    imm = types["Immunization"][0]
    assert imm["status"] == "not-done"
    # Epic codes the refused vaccine only by a SNOMED translation under a null code.
    assert imm["vaccineCode"]["coding"][0]["system"] == "http://snomed.info/sct"
    assert imm["vaccineCode"]["coding"][0]["display"] == "Removed"
    for cond in types["Condition"]:
        systems = [c["system"] for c in cond["code"]["coding"]]
        assert systems == [
            "http://snomed.info/sct",
            "http://hl7.org/fhir/sid/icd-10-cm",
            "http://hl7.org/fhir/sid/icd-9-cm",
            IMO_PROBLEM_IT,
        ]
        assert cond["clinicalStatus"]["coding"][0]["code"] == "active"
    procedures = types["Procedure"]
    assert all(p["status"] == "completed" and p["reasonCode"] for p in procedures)
    assert procedures[0]["code"]["text"] == "SNOMED CT 609588000"
    assert section(root, "46264-8").find("c:entry", NS) is None


def _same_structure(out: Path) -> None:
    assert section_entry_counts(out) == ENTRY_COUNTS
    for code in ("30954-2", "8716-3", "29762-2"):
        assert component_observation_counts(out, code) == component_observation_counts(EPIC, code)
    ids, refs = narrative_ids_and_refs(etree.parse(str(out)).getroot())
    assert len(refs) == NARRATIVE_REFS and all(ref.lstrip("#") in ids for ref in refs)
    _, report = convert_bytes(out.read_bytes(), out.name)
    assert report.resource_counts == EXPECTED_COUNTS


def test_cli_anonymize_is_idempotent(tmp_path, capsys):
    out = tmp_path / "anon.xml"
    rep = tmp_path / "anon.json"
    rc = main(["anonymize", str(EPIC), str(out), "--seed", "epic", "--report", str(rep)])
    assert rc == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    assert "residual findings 0" in captured.out
    report = json.loads(rep.read_text())
    assert report["residual_findings"] == []
    assert report["narrative_replacements"] == 0
    assert report["telecoms_rewritten"] == 0
    assert set(EPIC_CUSTOMER.findall(out.read_text(encoding="utf-8"))) == {"0"}
    _same_structure(out)


def test_cli_synthesize_is_idempotent(tmp_path, capsys):
    out = tmp_path / "syn.xml"
    rep = tmp_path / "syn.json"
    rc = main(["synthesize", str(EPIC), str(out), "--seed", "epic", "--report", str(rep)])
    assert rc == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    assert "unrecognized sections 0, residual findings 0" in captured.out
    report = json.loads(rep.read_text())
    assert report["residual_findings"] == []
    assert report["unrecognized_sections"] == []
    assert report["anonymize"]["residual_findings"] == []
    assert report["entries_replaced"] == ENTRY_COUNTS
    _same_structure(out)
    again = tmp_path / "again.xml"
    main(["synthesize", str(EPIC), str(again), "--seed", "epic"])
    assert again.read_bytes() == out.read_bytes()
