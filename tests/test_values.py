"""Spot checks of specific values on the hand-written and Synthea fixtures."""

from __future__ import annotations

from conftest import HANDWRITTEN, SYNTHEA, by_type
from healthrecord_bridge.ccda import convert

HAROLD = next(p for p in SYNTHEA if p.name.startswith("Harold594"))


def _one(resources: list[dict], **match) -> dict:
    for r in resources:
        if all(r.get(k) == v for k, v in match.items()):
            return r
    raise AssertionError(f"no resource matching {match}")


def test_patient_header():
    bundle, _ = convert(HANDWRITTEN)
    patient = by_type(bundle)["Patient"][0]
    assert patient["name"][0]["family"] == "Sampleton"
    assert patient["name"][0]["given"] == ["Jane", "Quinn"]
    assert patient["name"][0]["prefix"] == ["Ms."]
    assert patient["gender"] == "female"
    assert patient["birthDate"] == "1984-07-22"
    assert patient["deceasedBoolean"] is False
    assert patient["identifier"][0]["value"] == "E1234567"
    assert patient["identifier"][0]["system"] == "urn:oid:1.2.840.114350.1.13.999.2.7.5.737384.14"
    assert patient["identifier"][0]["type"]["coding"][0]["code"] == "MR"
    assert patient["identifier"][1]["value"] == "MRN00042"
    assert patient["address"] == [
        {
            "use": "home",
            "line": ["1200 Example Avenue", "Unit 4B"],
            "city": "Overland Park",
            "state": "KS",
            "postalCode": "66210",
            "country": "US",
        }
    ]
    telecom = {t["value"]: t for t in patient["telecom"]}
    assert telecom["+1-913-555-0199"]["use"] == "mobile"
    assert telecom["jane.sampleton@example.com"]["system"] == "email"
    assert len(patient["telecom"]) == 3  # the nullFlavor telecom is dropped
    assert patient["communication"][0]["language"]["coding"][0]["code"] == "en"
    assert patient["communication"][0]["preferred"] is True
    assert patient["maritalStatus"]["coding"][0]["code"] == "M"
    ext = {e["url"].rsplit("/", 1)[1]: e for e in patient["extension"]}
    race = ext["us-core-race"]["extension"]
    assert race[0] == {
        "url": "ombCategory",
        "valueCoding": {
            "system": "urn:oid:2.16.840.1.113883.6.238",
            "code": "2106-3",
            "display": "White",
        },
    }
    assert race[1]["url"] == "detailed" and race[1]["valueCoding"]["code"] == "2108-9"
    assert race[2] == {"url": "text", "valueString": "White, European"}
    assert ext["us-core-ethnicity"]["extension"][0]["valueCoding"]["code"] == "2186-5"
    assert ext["us-core-birthsex"]["valueCode"] == "F"


def test_synthea_patient_header():
    bundle, _ = convert(HAROLD)
    patient = by_type(bundle)["Patient"][0]
    assert patient["name"][0]["given"] == ["Harold594"]
    assert patient["name"][0]["family"] == "Hilll811"
    assert patient["birthDate"] == "1993-03-24"
    assert patient["gender"] == "male"
    assert "telecom" not in patient  # <telecom nullFlavor="NI"/>


def test_custodian_and_document_reference():
    bundle, _ = convert(HANDWRITTEN)
    types = by_type(bundle)
    org = types["Organization"][0]
    assert org["name"] == "Example Health System"
    assert org["identifier"] == [{"system": "urn:oid:2.16.840.1.113883.4.6", "value": "1234567893"}]
    doc = types["DocumentReference"][0]
    assert doc["type"]["coding"][0]["code"] == "34133-9"
    assert doc["date"] == "2024-03-15T14:30:00-05:00"
    assert doc["author"] == [{"display": "Robert Clinician MD"}]
    assert doc["custodian"]["reference"] == f"Organization/{org['id']}"
    assert doc["content"][0]["attachment"] == {
        "contentType": "application/xml",
        "language": "en-US",
        "title": "Continuity of Care Document",
    }
    assert "data" not in doc["content"][0]["attachment"]
    assert doc["masterIdentifier"] == {
        "system": "urn:oid:1.2.840.114350.1.13.999.2.7.8.688883.9999",
        "value": "CCD-2024-000042",
    }


def test_allergy_with_reaction_severity_criticality():
    bundle, _ = convert(HANDWRITTEN)
    allergies = by_type(bundle)["AllergyIntolerance"]
    pcn = _one(allergies, type="allergy", category=["medication"])
    assert pcn["code"]["coding"][0] == {
        "system": "http://www.nlm.nih.gov/research/umls/rxnorm",
        "code": "7980",
        "display": "Penicillin G",
    }
    assert pcn["clinicalStatus"]["coding"][0]["code"] == "active"
    assert pcn["verificationStatus"]["coding"][0]["code"] == "confirmed"
    assert pcn["criticality"] == "high"
    assert pcn["onsetDateTime"] == "2012-06-04"
    assert pcn["recordedDate"] == "2012-06-04T10:15:00-05:00"
    assert pcn["reaction"] == [
        {
            "manifestation": [
                {
                    "coding": [
                        {
                            "system": "http://snomed.info/sct",
                            "code": "247472004",
                            "display": "Hives",
                        }
                    ]
                }
            ],
            "severity": "moderate",
            "onset": "2012-06-04",
        }
    ]
    assert pcn["note"] == [{"text": "Penicillin G Hives Moderate"}]
    nkfa = _one(allergies, category=["food"])
    assert nkfa["verificationStatus"]["coding"][0]["code"] == "refuted"
    assert nkfa["code"]["coding"][0]["code"] == "414285001"
    assert "onsetDateTime" not in nkfa


def test_synthea_allergies():
    marco = next(p for p in SYNTHEA if p.name.startswith("Marco578"))
    bundle, _ = convert(marco)
    allergies = by_type(bundle)["AllergyIntolerance"]
    assert len(allergies) == 4
    codes = {a["code"]["coding"][0]["code"] for a in allergies}
    assert codes == {"419474003", "418689008", "425525006", "91934008"}
    # originalText is carried to text even when the coding has a display.
    mould = _one(
        allergies,
        code={
            "coding": [
                {
                    "system": "http://snomed.info/sct",
                    "code": "419474003",
                    "display": "Allergy to mould",
                }
            ],
            "text": "Allergy to mould",
        },
    )
    assert mould["clinicalStatus"]["coding"][0]["code"] == "active"
    assert mould["onsetDateTime"] == "1989-08-20"
    assert mould["type"] == "allergy"


def test_medication_statement_and_request():
    bundle, _ = convert(HANDWRITTEN)
    types = by_type(bundle)
    stmt = types["MedicationStatement"][0]
    assert stmt["status"] == "active"
    assert stmt["medicationCodeableConcept"]["coding"][0]["code"] == "314076"
    assert stmt["medicationCodeableConcept"]["coding"][1]["system"] == (
        "urn:oid:1.2.840.114350.1.13.999.2.7.2.698288"
    )
    assert stmt["effectivePeriod"] == {"start": "2023-01-10"}
    dosage = stmt["dosage"][0]
    assert dosage["text"] == "Take 1 tablet (10 mg total) by mouth daily."
    assert dosage["route"]["coding"][0]["code"] == "C38288"
    assert dosage["doseAndRate"][0]["doseQuantity"] == {
        "value": 1,
        "unit": "{tbl}",
        "system": "http://unitsofmeasure.org",
        "code": "{tbl}",
    }
    assert dosage["timing"] == {"repeat": {"period": 24, "periodUnit": "h"}}
    assert stmt["reasonCode"][0]["coding"][0]["code"] == "59621000"

    req = types["MedicationRequest"][0]
    assert req["status"] == "active"
    assert req["intent"] == "plan"
    assert req["authoredOn"] == "2024-03-01T09:15:00-06:00"
    assert req["medicationCodeableConcept"]["coding"][0]["code"] == "617310"
    timing = req["dosageInstruction"][0]["timing"]["repeat"]
    assert timing["boundsPeriod"] == {"start": "2024-03-01", "end": "2025-03-01"}
    assert timing["period"] == 1 and timing["periodUnit"] == "d"


def test_synthea_medication_statement():
    bundle, _ = convert(HAROLD)
    stmt = by_type(bundle)["MedicationStatement"][0]
    assert stmt["status"] == "completed"
    assert stmt["medicationCodeableConcept"]["coding"] == [
        {
            "system": "http://www.nlm.nih.gov/research/umls/rxnorm",
            "code": "849574",
            "display": "Naproxen sodium 220 MG Oral Tablet",
        }
    ]
    assert stmt["effectivePeriod"] == {"start": "2017-11-13", "end": "2017-12-04"}


def test_conditions():
    bundle, _ = convert(HANDWRITTEN)
    conditions = by_type(bundle)["Condition"]
    htn = _one(conditions, onsetDateTime="2018-02-14")
    assert htn["code"]["coding"] == [
        {
            "system": "http://snomed.info/sct",
            "code": "59621000",
            "display": "Essential hypertension",
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "I10",
            "display": "Essential (primary) hypertension",
        },
    ]
    assert htn["clinicalStatus"]["coding"][0]["code"] == "active"
    assert htn["category"][0]["coding"][0]["code"] == "problem-list-item"
    assert "abatementDateTime" not in htn
    bronchitis = _one(conditions, onsetDateTime="2023-11-05")
    assert bronchitis["clinicalStatus"]["coding"][0]["code"] == "resolved"
    assert bronchitis["abatementDateTime"] == "2023-11-20"


def test_synthea_condition_code():
    bundle, _ = convert(HAROLD)
    conditions = by_type(bundle)["Condition"]
    sprain = _one(conditions, onsetDateTime="2017-11-13")
    assert sprain["code"]["coding"][0] == {
        "system": "http://snomed.info/sct",
        "code": "44465007",
        "display": "Sprain of ankle",
    }
    assert sprain["abatementDateTime"] == "2017-12-04"
    assert sprain["clinicalStatus"]["coding"][0]["code"] == "resolved"


def test_procedures():
    bundle, _ = convert(HANDWRITTEN)
    procedures = by_type(bundle)["Procedure"]
    colo = _one(procedures, performedDateTime="2022-09-08T08:15:00-05:00")
    assert colo["code"]["coding"][0]["system"] == "http://www.ama-assn.org/go/cpt"
    assert colo["code"]["coding"][0]["code"] == "45378"
    assert colo["code"]["coding"][1]["code"] == "73761001"
    assert colo["status"] == "completed"
    assert colo["bodySite"][0]["coding"][0]["code"] == "71854001"
    assert colo["performer"] == [
        {
            "actor": {"display": "Alma Endoscopist MD"},
            "onBehalfOf": {"display": "Example Endoscopy Center"},
        }
    ]
    ecg = _one(
        procedures,
        status="completed",
        performedPeriod={"start": "2023-11-05T10:00:00-06:00", "end": "2023-11-05T10:15:00-06:00"},
    )
    assert ecg["code"]["coding"][0]["code"] == "93000"


def test_encounters():
    bundle, _ = convert(HANDWRITTEN)
    encounters = by_type(bundle)["Encounter"]
    office = _one(
        encounters,
        period={"start": "2024-03-01T09:00:00-06:00", "end": "2024-03-01T09:30:00-06:00"},
    )
    assert office["status"] == "finished"
    assert office["class"]["code"] == "AMB"
    assert office["type"][0]["coding"][0]["code"] == "99213"
    assert office["participant"] == [{"individual": {"display": "Robert Clinician MD"}}]
    assert office["location"] == [{"location": {"display": "Example Family Medicine"}}]
    assert office["reasonCode"][0]["coding"][0]["code"] == "59621000"
    admission = _one(
        encounters,
        period={"start": "2023-11-05T09:45:00-06:00", "end": "2023-11-07T11:00:00-06:00"},
    )
    assert admission["class"]["code"] == "IMP"
    disposition = admission["hospitalization"]["dischargeDisposition"]["coding"][0]
    assert disposition["system"] == "http://terminology.hl7.org/CodeSystem/v2-0112"
    assert disposition["code"] == "01"


def test_vital_signs():
    bundle, _ = convert(HANDWRITTEN)
    vitals = [
        o
        for o in by_type(bundle)["Observation"]
        if o["category"][0]["coding"][0]["code"] == "vital-signs"
    ]
    assert len(vitals) == 3
    systolic = _one(
        vitals,
        code={
            "coding": [
                {
                    "system": "http://loinc.org",
                    "code": "8480-6",
                    "display": "Systolic blood pressure",
                }
            ]
        },
    )
    assert systolic["valueQuantity"] == {
        "value": 128,
        "unit": "mm[Hg]",
        "system": "http://unitsofmeasure.org",
        "code": "mm[Hg]",
    }
    assert systolic["effectiveDateTime"] == "2024-03-01T09:05:00-06:00"
    assert systolic["status"] == "final"


def test_lab_results():
    bundle, _ = convert(HANDWRITTEN)
    types = by_type(bundle)
    report = types["DiagnosticReport"][0]
    assert report["code"]["coding"][0]["code"] == "24323-8"
    assert report["status"] == "final"
    assert report["category"][0]["coding"][0]["code"] == "LAB"
    assert report["effectiveDateTime"] == "2024-03-01T07:30:00-06:00"
    assert report["performer"] == [{"display": "Example Reference Laboratory"}]
    assert len(report["result"]) == 4
    labs = [
        o for o in types["Observation"] if o["category"][0]["coding"][0]["code"] == "laboratory"
    ]
    glucose = _one(
        labs,
        code={
            "coding": [
                {
                    "system": "http://loinc.org",
                    "code": "2345-7",
                    "display": "Glucose [Mass/volume] in Serum or Plasma",
                }
            ]
        },
    )
    assert glucose["valueQuantity"] == {
        "value": 104,
        "unit": "mg/dL",
        "system": "http://unitsofmeasure.org",
        "code": "mg/dL",
    }
    assert glucose["interpretation"][0]["coding"][0] == {
        "system": "http://terminology.hl7.org/CodeSystem/v3-ObservationInterpretation",
        "code": "H",
        "display": "High",
    }
    assert glucose["referenceRange"] == [
        {
            "low": {
                "value": 70,
                "unit": "mg/dL",
                "system": "http://unitsofmeasure.org",
                "code": "mg/dL",
            },
            "high": {
                "value": 99,
                "unit": "mg/dL",
                "system": "http://unitsofmeasure.org",
                "code": "mg/dL",
            },
            "text": "70 - 99 mg/dL",
        }
    ]
    comment = _one(labs, valueString="Specimen slightly hemolyzed")
    assert comment["code"]["coding"][0]["code"] == "48767-8"
    blood_type = _one(
        labs,
        valueCodeableConcept={
            "coding": [
                {
                    "system": "http://snomed.info/sct",
                    "code": "278149003",
                    "display": "Blood group O Rh(D) positive",
                }
            ]
        },
    )
    assert blood_type["code"]["coding"][0]["code"] == "882-1"
    potassium = _one(
        labs,
        dataAbsentReason={
            "coding": [
                {
                    "system": "http://terminology.hl7.org/CodeSystem/data-absent-reason",
                    "code": "unknown",
                    "display": "Unknown",
                }
            ]
        },
    )
    assert "valueQuantity" not in potassium


def test_synthea_lab_value_and_report_text():
    bundle, _ = convert(HAROLD)
    types = by_type(bundle)
    report = types["DiagnosticReport"][0]
    assert report["code"] == {
        "text": "Complete blood count (hemogram) panel - Blood by Automated count"
    }
    labs = [
        o for o in types["Observation"] if o["category"][0]["coding"][0]["code"] == "laboratory"
    ]
    leuk = _one(labs, effectiveDateTime="2015-05-27")
    assert leuk["code"]["coding"] == [
        {
            "system": "http://loinc.org",
            "code": "6690-2",
            "display": "Leukocytes [#/volume] in Blood by Automated count",
        }
    ]
    assert leuk["valueQuantity"]["value"] == 8.772995479243308
    assert leuk["valueQuantity"]["code"] == "10*3/uL"
    # Synthea points originalText at the panel row, which is now kept as text.
    assert (
        leuk["code"]["text"] == "Complete blood count (hemogram) panel - Blood by Automated count"
    )


def test_immunizations():
    bundle, _ = convert(HANDWRITTEN)
    imms = by_type(bundle)["Immunization"]
    flu = _one(imms, status="completed")
    assert flu["vaccineCode"]["coding"][0] == {
        "system": "http://hl7.org/fhir/sid/cvx",
        "code": "150",
        "display": "Influenza, injectable, quadrivalent, preservative free",
    }
    assert flu["occurrenceDateTime"] == "2023-10-12"
    assert flu["lotNumber"] == "FLU2023-AB12"
    assert flu["manufacturer"] == {"display": "Example Vaccines Inc"}
    assert flu["route"]["coding"][0]["code"] == "C28161"
    assert flu["doseQuantity"]["value"] == 0.5
    assert flu["performer"] == [{"actor": {"display": "Robert Clinician"}}]
    refused = _one(imms, status="not-done")
    assert refused["vaccineCode"]["coding"][0]["code"] == "115"
    assert refused["statusReason"]["coding"][0]["code"] == "PATOBJ"


def test_synthea_immunization():
    bundle, _ = convert(HAROLD)
    imms = by_type(bundle)["Immunization"]
    first = _one(imms, occurrenceDateTime="2010-05-12")
    assert first["vaccineCode"]["coding"][0]["code"] == "140"
    assert first["vaccineCode"]["coding"][0]["system"] == "http://hl7.org/fhir/sid/cvx"
    assert first["status"] == "completed"
    assert all(i["status"] == "completed" for i in imms)


def test_social_history():
    bundle, _ = convert(HANDWRITTEN)
    social = [
        o
        for o in by_type(bundle)["Observation"]
        if o["category"][0]["coding"][0]["code"] == "social-history"
    ]
    assert len(social) == 2
    smoking = _one(
        social,
        code={
            "coding": [
                {
                    "system": "http://loinc.org",
                    "code": "72166-2",
                    "display": "Tobacco smoking status NHIS",
                }
            ]
        },
    )
    assert smoking["valueCodeableConcept"]["coding"][0] == {
        "system": "http://snomed.info/sct",
        "code": "8517006",
        "display": "Former smoker",
    }
    alcohol = _one(
        social,
        valueQuantity={
            "value": 2,
            "unit": "/wk",
            "system": "http://unitsofmeasure.org",
            "code": "/wk",
        },
    )
    assert "identifier" not in alcohol  # no CDA id: fallback id, no identifier


def test_synthea_smoking_status_in_vitals_is_coerced_to_coded_value():
    bundle, _ = convert(HAROLD)
    social = [
        o
        for o in by_type(bundle)["Observation"]
        if o["category"][0]["coding"][0]["code"] == "social-history"
    ]
    assert social, "Synthea writes smoking status into the vital signs organizer"
    for o in social:
        assert o["code"]["coding"][0]["code"] == "72166-2"
        assert o["valueCodeableConcept"]["coding"][0]["system"] == "http://snomed.info/sct"
        assert o["valueCodeableConcept"]["coding"][0]["code"] == "266919005"
        assert o["valueCodeableConcept"]["coding"][0]["display"] == "Never smoker"


def test_assume_timezone_keeps_time_of_day():
    bundle, report = convert(HAROLD, assume_timezone="-04:00")
    stmt = by_type(bundle)["MedicationStatement"][0]
    assert stmt["effectivePeriod"] == {
        "start": "2017-11-13T04:12:48-04:00",
        "end": "2017-12-04T04:12:48-04:00",
    }
    assert report.documents[0].notes == []
    _, report_default = convert(HAROLD)
    assert any("truncated" in n for n in report_default.documents[0].notes)
