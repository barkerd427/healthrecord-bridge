"""Deterministic ids and identifiers."""

from __future__ import annotations

import uuid

from conftest import HANDWRITTEN, SYNTHEA, by_type
from healthrecord_bridge.ccda import NAMESPACE_HRB, convert, convert_many
from healthrecord_bridge.ccda.ids import CdaId, fallback_id, identifier, resource_id


def test_namespace_is_fixed():
    assert uuid.uuid5(uuid.NAMESPACE_DNS, "healthrecord-bridge") == NAMESPACE_HRB
    assert str(NAMESPACE_HRB) == "c56c34af-5015-509c-ba3d-34930e66992b"


def test_resource_id_formula():
    cid = CdaId("1.2.3", "ABC")
    assert resource_id("Observation", cid) == str(
        uuid.uuid5(NAMESPACE_HRB, "Observation|1.2.3|ABC")
    )
    assert resource_id("Observation", CdaId("1.2.3")) == str(
        uuid.uuid5(NAMESPACE_HRB, "Observation|1.2.3|")
    )
    assert resource_id("Condition", cid) != resource_id("Observation", cid)
    doc = CdaId("9.9", "DOC")
    assert fallback_id("Observation", doc, "29762-2", 1, 0) == str(
        uuid.uuid5(NAMESPACE_HRB, "Observation|9.9|DOC|29762-2|1|0")
    )


def test_identifier_shapes():
    assert identifier(CdaId("2.16.840.1.113883.19.5", "X1")) == {
        "system": "urn:oid:2.16.840.1.113883.19.5",
        "value": "X1",
    }
    assert identifier(CdaId("2.16.840.1.113883.19.5")) == {
        "system": "urn:ietf:rfc:3986",
        "value": "urn:oid:2.16.840.1.113883.19.5",
    }
    assert identifier(CdaId("5e09b6b3-5091-40f1-83ec-422879429da9")) == {
        "system": "urn:ietf:rfc:3986",
        "value": "urn:uuid:5e09b6b3-5091-40f1-83ec-422879429da9",
    }


def test_ids_are_deterministic_across_runs(fixture_path):
    first, _ = convert(fixture_path)
    second, _ = convert(fixture_path)
    assert first == second
    ids = [e["resource"]["id"] for e in first["entry"]]
    assert len(ids) == len(set(ids)), "ids must be unique within a bundle"
    for e in first["entry"]:
        r = e["resource"]
        if "identifier" in r:
            cid = r["identifier"][0]
            if cid["system"] == "urn:ietf:rfc:3986":
                root = cid["value"].split(":", 2)[2]
                expected = resource_id(r["resourceType"], CdaId(root))
            else:
                root = cid["system"].split(":", 2)[2]
                expected = resource_id(r["resourceType"], CdaId(root, cid["value"]))
            if r["resourceType"] not in {"DocumentReference", "Provenance"}:
                assert r["id"] == expected, r["resourceType"]


def test_meta_source_names_the_document():
    bundle, _ = convert(HANDWRITTEN)
    for e in bundle["entry"]:
        assert e["resource"]["meta"]["source"] == (
            "urn:healthrecord-bridge:ccda:1.2.840.114350.1.13.999.2.7.8.688883.9999:CCD-2024-000042"
        )


def test_merge_dedupes_and_later_wins():
    bundle, report = convert_many([HANDWRITTEN, HANDWRITTEN])
    single, _ = convert(HANDWRITTEN)
    assert len(bundle["entry"]) == len(single["entry"])
    assert len(report.documents) == 2
    assert report.resource_counts["Patient"] == 2  # per-document counts are summed
    assert len(by_type(bundle)["Patient"]) == 1


def test_merge_distinct_documents():
    bundle, _ = convert_many(SYNTHEA[:2])
    a, _ = convert(SYNTHEA[0])
    b, _ = convert(SYNTHEA[1])
    assert len(bundle["entry"]) == len(a["entry"]) + len(b["entry"])
    assert len(by_type(bundle)["Patient"]) == 2
