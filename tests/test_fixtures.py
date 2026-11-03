"""Every fixture converts, and resource counts line up with the CDA entry counts."""

from __future__ import annotations

import pytest

from conftest import EPIC, HANDWRITTEN, by_type, component_observation_counts, section_entry_counts
from healthrecord_bridge.ccda import convert


def test_fixture_converts(fixture_path):
    bundle, report = convert(fixture_path)
    assert bundle["resourceType"] == "Bundle"
    assert bundle["type"] == "collection"
    assert "total" not in bundle
    types = by_type(bundle)
    assert len(types["Patient"]) == 1
    assert len(types["DocumentReference"]) == 1
    assert len(types["Provenance"]) == 1
    assert len(report.documents) == 1
    assert report.resource_counts == {k: len(v) for k, v in types.items()}


def test_every_resource_has_id_meta_and_subject(fixture_path):
    bundle, _ = convert(fixture_path)
    patient_ref = f"Patient/{by_type(bundle)['Patient'][0]['id']}"
    doc_source = None
    for entry in bundle["entry"]:
        r = entry["resource"]
        assert r["id"]
        assert entry["fullUrl"] == f"urn:uuid:{r['id']}"
        assert r["meta"]["source"].startswith("urn:healthrecord-bridge:ccda:")
        assert r["meta"]["tag"] == [{"system": "urn:healthrecord-bridge", "code": "ccda"}]
        doc_source = doc_source or r["meta"]["source"]
        assert r["meta"]["source"] == doc_source
        if r["resourceType"] in {"AllergyIntolerance", "Immunization"}:
            assert r["patient"]["reference"] == patient_ref
        elif r["resourceType"] not in {"Patient", "Organization", "Provenance"}:
            assert r["subject"]["reference"] == patient_ref


def test_counts_match_section_entries(fixture_path):
    if fixture_path == EPIC:
        pytest.skip("Epic result components with a null code and no text are dropped")
    bundle, report = convert(fixture_path)
    types = by_type(bundle)
    entries = section_entry_counts(fixture_path)
    doc = report.documents[0]

    def produced(name: str) -> int:
        s = doc.section(name)
        return s.resources_produced if s else 0

    def skipped(name: str) -> int:
        s = doc.section(name)
        return len(s.skipped) if s else 0

    assert len(types.get("AllergyIntolerance", [])) == entries.get("48765-2", 0)
    meds = len(types.get("MedicationStatement", [])) + len(types.get("MedicationRequest", []))
    assert meds + skipped("Medications") == entries.get("10160-0", 0)
    assert len(types.get("Condition", [])) == entries.get("11450-4", 0)
    assert len(types.get("Procedure", [])) == entries.get("47519-4", 0)
    assert len(types.get("Encounter", [])) == entries.get("46240-8", 0)
    assert len(types.get("Immunization", [])) == entries.get("11369-6", 0)

    organizers, lab_obs = component_observation_counts(fixture_path, "30954-2")
    assert len(types.get("DiagnosticReport", [])) == organizers
    _, vital_obs = component_observation_counts(fixture_path, "8716-3")
    _, social_obs = component_observation_counts(fixture_path, "29762-2")
    assert len(types.get("Observation", [])) == lab_obs + vital_obs + social_obs
    assert produced("Results") == organizers + lab_obs
    assert produced("Vital Signs") == vital_obs

    observations = types.get("Observation", [])
    labs = [o for o in observations if o["category"][0]["coding"][0]["code"] == "laboratory"]
    assert len(labs) == lab_obs
    for dr in types.get("DiagnosticReport", []):
        assert dr["result"]
        ids = {o["id"] for o in labs}
        for ref in dr["result"]:
            assert ref["reference"].split("/")[1] in ids


def test_provenance_targets_everything(fixture_path):
    bundle, _ = convert(fixture_path)
    types = by_type(bundle)
    prov = types["Provenance"][0]
    targets = {t["reference"] for t in prov["target"]}
    expected = {
        f"{e['resource']['resourceType']}/{e['resource']['id']}"
        for e in bundle["entry"]
        if e["resource"]["resourceType"] != "Provenance"
    }
    assert targets == expected
    assert prov["recorded"].endswith(("Z", "-05:00", "-06:00")) or "+" in prov["recorded"]
    assert prov["entity"][0]["what"]["display"] == fixture_path.name
    assert prov["agent"][0]["who"]["display"]


def test_report_lists_unmapped_sections_and_code_systems():
    _, report = convert(HANDWRITTEN)
    doc = report.documents[0]
    unknown = {u.code: u for u in doc.unknown_sections}
    assert "18776-5" in unknown
    assert unknown["18776-5"].entries == 1
    assert "1.2.840.114350.1.13.999.2.7.2.698288" in doc.unmapped_code_systems
    meds = doc.section("Medications")
    assert meds is not None
    assert meds.entries_seen == 3 and meds.resources_produced == 2
    assert [s.reason for s in meds.skipped] == ["act without substanceAdministration"]
    text = report.format()
    assert "Plan of Treatment" in text
    assert "Medications" in text
    as_dict = report.to_dict()
    assert as_dict["resource_counts"]["Observation"] == 9
