# healthrecord-bridge

Convert personal health record exports into FHIR R4 you can load into your own tools.

The first converter takes HL7 C-CDA R2.1 documents, the format Epic MyChart produces when
you click "Download my record" (and what most US hospital portals hand out), and turns them
into a FHIR R4 Bundle plus NDJSON files. It is built for people running their own health
data stack at home: MediKeep, a Postgres database with SQL-on-FHIR views, Syntropy Health,
or anything else that reads FHIR R4 JSON.

- Pure Python, one runtime dependency (`lxml`).
- Deterministic resource ids, so re-importing the same export updates rows instead of
  duplicating them.
- Reads bare XML or the IHE XDM zip MyChart emits, without unpacking anything by hand.
- Tells you what it did not map, per section, so nothing silently disappears.

## Install

```sh
pip install healthrecord-bridge
# or, as an isolated command-line tool
uv tool install healthrecord-bridge
```

Python 3.11 or newer.

## Command line

```sh
# One MyChart export straight from the browser download
hrb ccda2fhir MyChart_Export.zip -o bundle.json --pretty

# Several exports (zips and bare XML) merged into one bundle, plus NDJSON per resource type
hrb ccda2fhir export-2023.zip export-2024.zip DOC0001.XML -o bundle.json --ndjson out/

# Write the conversion report as JSON too
hrb ccda2fhir MyChart_Export.zip -o bundle.json --report report.json
```

`INPUT` is any `.xml` or `.zip`. Without `-o` the bundle goes to stdout. The conversion
report is printed to stderr (silence it with `-q`). When several inputs produce the same
resource (for example the same Patient in two exports) the later input wins.

Timestamps in some exports carry a time of day but no UTC offset. FHIR does not allow that,
so such values are truncated to a date and the report tells you how many were affected. If
you know the offset, pass `--assume-timezone=-05:00` to keep the time of day. Note the `=`
when the offset starts with a minus sign.

Report output looks like this:

```
DOC0001.XML (document id 1.2.840.114350.1.13.999.2.7.8.688883.9999:CCD-2024-000042)
  Allergies       entries    2  resources    2  skipped   0
  Medications     entries    3  resources    2  skipped   1
                    1 x act without substanceAdministration
  Problems        entries    2  resources    2  skipped   0
  ...
  not mapped in this version:
    18776-5    Plan of Treatment (1 entries)
  code systems emitted as urn:oid: 1.2.840.114350.1.13.999.2.7.2.698288
  resources: AllergyIntolerance 2, Condition 2, DiagnosticReport 1, ...
```

## Library

```python
from healthrecord_bridge.ccda import convert

bundle, report = convert("MyChart_Export.zip")
# bundle is a dict: {"resourceType": "Bundle", "type": "collection", "entry": [...]}
# report is a ConversionReport with per-document, per-section counts

print(report.format())
for entry in bundle["entry"]:
    print(entry["resource"]["resourceType"], entry["resource"]["id"])
```

Other entry points:

```python
from healthrecord_bridge.ccda import convert_many, convert_bytes
from healthrecord_bridge.fhir.ndjson import write_ndjson

bundle, report = convert_many(["a.zip", "b.xml"], assume_timezone="-06:00")
bundle, report = convert_bytes(xml_bytes, "DOC0001.XML")
write_ndjson(bundle, "out/")  # out/Patient.ndjson, out/Observation.ndjson, ...
report.to_dict()  # JSON-friendly version of the report
```

`convert` raises `healthrecord_bridge.ccda.CcdaError` (a `ValueError`) when the input is
not a C-CDA document or is unsafe to parse.

## Input formats

- A bare C-CDA XML file. The root element must be `{urn:hl7-org:v3}ClinicalDocument`.
- An IHE XDM zip as MyChart produces it: every `*.XML` under an `IHE_XDM/` folder is
  converted (for example `MachineReadable_XDMFormat/IHE_XDM/SUBSET01/DOC0001.XML`);
  `METADATA.XML`, `INDEX.HTM` and `README.TXT` are ignored.
- Any other zip with C-CDA XML files somewhere inside.

Archive contents are treated as untrusted. XML is parsed with entity resolution and network
access disabled, documents with a DOCTYPE or entity declarations are rejected, oversized
members are refused, and anything whose root is not a `ClinicalDocument` is rejected.

## What is mapped

The converter locates sections by LOINC `section/code` or by `templateId`; either match wins.

| C-CDA section | LOINC | FHIR R4 output |
|---|---|---|
| Header: recordTarget | | `Patient` (name, gender, birthDate, deceased, address, telecom, identifiers including MRN, marital status, language, US Core race, ethnicity and birth sex extensions) |
| Header: custodian | | `Organization` |
| Header: document | | `DocumentReference` (type, date, author, custodian, title, `application/xml`, no embedded data) and one `Provenance` targeting every resource from the document |
| Allergies | 48765-2 | `AllergyIntolerance` (substance code, clinicalStatus, verificationStatus refuted for "no known" entries, type, category, criticality, onset, reactions with manifestation and severity) |
| Medications | 10160-0 | `MedicationStatement` for event-mood entries with completed or active status, otherwise `MedicationRequest`; RxNorm code, dosage text, dose, route, frequency, effective period, reason |
| Problems | 11450-4 | `Condition` (SNOMED and ICD-10-CM codes, onset, abatement, clinicalStatus, category problem-list-item) |
| Procedures | 47519-4 | `Procedure` (code, status, performed date or period, body site, performer) |
| Encounters | 46240-8 | `Encounter` (class derived from the type code, type, period, participants, location display, reason, discharge disposition) |
| Vital Signs | 8716-3 | One `Observation` per organizer component (category vital-signs, LOINC code, UCUM quantity, effective time) |
| Results | 30954-2 | `DiagnosticReport` per organizer plus one `Observation` per component (category laboratory; quantity, string, coded or range values; reference ranges; interpretation) |
| Immunizations | 11369-6 | `Immunization` (CVX code, occurrence date, completed or not-done with reason, lot number, manufacturer, route, site, dose, performer) |
| Social History | 29762-2 | `Observation` (category social-history). Smoking status (LOINC 72166-2) is coerced to a coded SNOMED value, including when the source writes it as text |

Code systems: SNOMED CT, LOINC, RxNorm, CVX, ICD-10-CM, ICD-9-CM, CPT, HCPCS, NDC, UCUM,
NCI Thesaurus routes, the CDC race and ethnicity set, HL7 v2 tables and the HL7 v3 code
systems (ActCode, AdministrativeGender, RouteOfAdministration, ObservationInterpretation and
others) map to their FHIR URIs. Any other OID becomes `urn:oid:<oid>` and is listed in the
report. `translation` codes are kept as extra `coding` entries. When a code has no display
name, the narrative text it references (`<reference value="#id"/>`) is carried into
`CodeableConcept.text`. `nullFlavor` values are treated as absent everywhere.

### Not mapped yet

Plan of Treatment, Imaging Studies and the DICOM catalog, Functional Status, Mental Status,
Family History, Medical Equipment, Payers, Advance Directives, Goals, Health Concerns, Care
Team, notes sections, and any other section not in the table. These are counted and listed
in the report with their entry counts so you can see what is being left behind. Vital sign
panels are not grouped (no blood pressure panel with components; systolic and diastolic are
separate Observations). Encounter and medication references between resources (for example
`Condition.encounter`) are not populated.

## Deterministic ids and upserts

Every resource id is a UUID version 5 under a fixed namespace:

```
NAMESPACE_HRB = uuid5(NAMESPACE_DNS, "healthrecord-bridge")
id = uuid5(NAMESPACE_HRB, f"{resourceType}|{cda id root}|{cda id extension}")
```

When a CDA entry has no `id`, the key is the document id plus the section code and the
entry's position within the section instead. Either way, converting the same export twice
produces byte-identical output, and converting a newer export that contains the same
entries produces the same ids for them. An importer can therefore `INSERT ... ON CONFLICT
(id) DO UPDATE` or use a FHIR `PUT` and get updates rather than duplicates.

Each resource also carries:

- `identifier[]` with the original CDA id: `system` is `urn:oid:<root>` (or
  `urn:uuid:<root>` when the root is a UUID) and `value` is the extension; when there is no
  extension the system is `urn:ietf:rfc:3986` and the value is the root as a URN.
- `meta.source = "urn:healthrecord-bridge:ccda:<document id root[:extension]>"`, which
  tells you which document a row came from.
- `meta.tag = [{"system": "urn:healthrecord-bridge", "code": "ccda"}]`, so rows from this
  converter are easy to select or delete as a group.

## Validation

Output is FHIR R4 JSON that follows the base resource structures (required fields present,
correct value types, valid dateTime precision). It is not validated against US Core or any
other profile yet, and the converter does not call a terminology server. If your downstream
tool enforces profiles, run the bundle through the HL7 FHIR validator first and open an
issue with what it reports.

## Development

```sh
uv sync --all-extras
uv run ruff check . && uv run ruff format --check .
uv run pytest
HRB_SYNTHEA_DIR=/path/to/synthea/ccda uv run pytest -m slow   # full 1,180 document smoke test
```

Test fixtures are synthetic (Synthea) or hand-written; see `tests/fixtures/README.md`.

## Roadmap

- Epic EHI export tables (TSV) to FHIR.
- A FHIR bundle normalizer that merges bundles from several portals and reconciles
  duplicates across sources.
- VA Blue Button text parser.
- SQL-on-FHIR view definitions for the resource types produced here.
- Importers for MediKeep.

## License

MIT. See `LICENSE`.
