# Changelog

All notable changes to this project are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [0.2.0] - Unreleased

### Added

- C-CDA synthesizer (`hrb synthesize`, `healthrecord_bridge.ccda.synthesize`): runs the
  anonymizer, then replaces every medication, problem, allergy, immunization, procedure,
  lab result, vital sign value, social history value and free-text field with made-up data
  from built-in tables, deterministically from a seed. Narratives are rebuilt as plain
  tables that keep the `ID` attributes entries point at; text-only and unrecognised
  sections are blanked. `SynthesizeReport` carries the anonymize report, entry counts per
  section, unrecognized sections and residual findings.
- Synthesizer: race, ethnicity, religion, marital status and a code-less gender are
  neutralized, the birth year is drawn 25 to 70 years before the latest date in the
  document, and provider specialty `originalText` and display names become "Removed".
- Synthesizer: Epic's `X-CE-PFD` patient-facing note section is blanked without being
  reported as unrecognized.

### Changed

- Anonymizer: names, addresses and telecoms with a `nullFlavor` but content are scrubbed
  like any other, keeping the `nullFlavor`.
- Anonymizer: Epic customer OIDs (`1.2.840.114350.1.13.<customer>`) get customer number `0`
  in every attribute and text node; the count is reported as `oids_rewritten`.
- Anonymizer: `assigningAuthorityName` values other than `EPIC`/`EPC` become `Example`.
- Anonymizer: runs of nine or more digits in OID roots and narrative `ID` attributes are
  hashed, with the references that point at them updated.
- Anonymizer: `NPI: 1234567890` patterns in narrative are blanked, and header name tokens are
  replaced in every text node of the document, not only in narrative.

### Fixed

- Anonymizer and synthesizer residual checks no longer report the scrubber's own
  substitutes (Alex, Testperson, Example Health System, ...), so a fully scrubbed document
  reports zero findings.
- Anonymizer: words of the provider organization name were treated as patient name parts,
  which turned "Patient Health Summary" into "Patient Alex Summary".
- Anonymizer: the phone pattern no longer matches digit groups inside OIDs in narrative.

## [0.1.0] - 2026-11-02

### Added

- C-CDA R2.1 to FHIR R4 converter (`hrb ccda2fhir`, `healthrecord_bridge.ccda.convert`).
- Input: bare C-CDA XML, IHE XDM zips as produced by Epic MyChart, plain zips containing
  C-CDA XML. Hardened XML parsing for untrusted archives.
- Header mapping to `Patient`, `Organization`, `DocumentReference` and `Provenance`.
- Section mapping for Allergies, Medications, Problems, Procedures, Encounters, Vital Signs,
  Results, Immunizations and Social History.
- Deterministic UUIDv5 resource ids, CDA identifiers carried as `identifier`, `meta.source`
  and `meta.tag` on every resource.
- `ConversionReport` with per-section entry, resource and skip counts, unmapped sections
  and unmapped code systems.
- NDJSON writer (one file per resource type) and a merged-bundle mode for several inputs.
- C-CDA anonymizer (`hrb anonymize`, `healthrecord_bridge.ccda.anonymize`): seeded day
  shift, hashed identifiers, substituted names, addresses and telecoms, narrative scrubbing
  and an `AnonymizeReport` with residual findings for a human reviewer.
