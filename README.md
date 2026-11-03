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
- Reports what it did not map, per section.

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

## Anonymizing a real export

A real MyChart export is useful as a test fixture only once nothing in it points back to a
person. `hrb anonymize` rewrites one C-CDA XML file into a copy that keeps the clinical
content and the document structure but not the identity:

```sh
hrb anonymize DOC0001.XML fixture.xml --seed my-seed --report anonymize.json
```

What it changes:

- Every HL7 timestamp (`effectiveTime`, `low`, `high`, `time`, `birthTime`, ...) is moved by
  the same number of days, between 30 and 730 in either direction, derived from the seed.
  Precision is kept, so intervals between dates survive. The birth date is additionally
  rounded to January 1 of its shifted year.
- Every `<id>` extension (and any root that is not an OID) becomes a stable hash of the
  seed and the original value, so the same identifier still maps to the same output
  everywhere in the document. Runs of nine or more digits inside OID roots and narrative
  `ID` attributes (Epic record numbers) are hashed too, with references following.
- Epic customer OIDs (`1.2.840.114350.1.13.<customer>...`) get customer number `0` wherever
  they appear; `assigningAuthorityName` values other than `EPIC`/`EPC` become `Example`.
- The patient becomes Alex Testperson; everyone else (authors, performers, informants,
  guardians, custodians) becomes Pat Clinician at Example Health System, with a fixed
  address and `tel:+1-555-0100` / `mailto:patient@example.com` telecoms. A name or address
  that carries a `nullFlavor` but still has content is replaced the same way.
- Every text node in the document has the names seen in the header replaced with the same
  substitutes; in section narrative, titles and `originalText`, phone numbers, email
  addresses, `MRN: 12345` and `NPI: 1234567890` patterns are blanked as well.

Codes, code systems, units, measurement values and the narrative tables are left as they
are, so the converter produces the same resources from the scrubbed file as from the
original. The same seed always gives byte-identical output; without `--seed` a random seed
is used and printed.

The scrubber only knows the names that appear in structured header elements. Free text can
mention relatives, employers, other clinicians or places it has never seen, so a person
must still read the whole output before sharing it. The report lists `residual_findings`
(long digit runs, phone and email shapes that survived scrubbing) as a starting point, and
the command warns on stderr when that list is not empty.

```python
from healthrecord_bridge.ccda.anonymize import anonymize, anonymize_file

scrubbed, report = anonymize(xml_bytes, seed="my-seed")
report = anonymize_file("DOC0001.XML", "fixture.xml", seed="my-seed")
print(report.day_shift, report.residual_findings)
```

## Making a synthetic fixture from a real export

Anonymizing keeps the clinical content, which is often enough to identify a person on its
own. `hrb synthesize` goes one step further: it runs the anonymizer and then replaces every
piece of clinical content with made-up data from built-in tables, so what is left is the
shape of the export and nothing else:

```sh
hrb synthesize DOC0001.XML fixture.xml --seed my-seed --report synthesize.json
```

What it keeps: every section, entry and element, in the same order; template ids,
hashed ids, status codes, mood codes, `nullFlavor` values, the shape of every
`effectiveTime`, the generic codes that describe the record (section codes, concern acts,
status and severity observations, vital sign and social history codes, encounter type
codes), and the header as the anonymizer left it (language, document title,
confidentiality). Race and ethnicity become "Other Race" and "Not Hispanic or Latino",
religion and marital status become unknown, a gender without a code becomes
"Undifferentiated", the birth year is drawn 25 to 70 years before the latest date in the
document, and provider specialty text is removed while the specialty codes stay.

What it replaces: every medication (about 40 common drugs with RxNorm codes, doses, routes
and sig text), every problem and encounter diagnosis (about 45 conditions with SNOMED CT and
ICD-10-CM codes), allergens with their reactions and severities, immunizations (CVX codes;
lot numbers are hashed and manufacturers blanked), procedures (CPT or SNOMED CT), lab panels
and results (about 45 LOINC tests; every value is drawn inside its normal range and the
reference range and interpretation are rewritten to match), vital sign values (plausible,
with a constant height and a weight that stays within a small band), smoking status (always
"Never smoker"), and every free-text field. Each section's narrative is rebuilt as a plain
table with one row per entry, keeping the `ID` attributes that entries point at.
Text-only sections (plan of care, notes, history of present illness, payers, family history
and so on) are reduced to "Narrative removed." with "Removed" in place of their entry text
and hashed codes; sections the converter does not recognise get the same treatment and are
listed in the report under `unrecognized_sections`.

All choices come from a generator seeded with `--seed`, so the same seed gives
byte-identical output; without a seed a random one is used and printed. Nothing leaves your
machine: there is no network access and no model involved. The converter produces the same
number of resources of each type from the synthetic file as from the original.

The output is still worth a read before you share it. After rewriting, the tool checks that
no text in the document still contains any display name, narrative cell, drug name or free
text it collected from the input and lists anything that slipped through under
`residual_findings`; the command warns on stderr when that list, or the list of
unrecognized sections, is not empty.

```python
from healthrecord_bridge.ccda.synthesize import synthesize, synthesize_file

synthetic, report = synthesize(xml_bytes, seed="my-seed")
report = synthesize_file("DOC0001.XML", "fixture.xml", seed="my-seed")
print(report.summary(), report.entries_replaced, report.unrecognized_sections)
```

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
