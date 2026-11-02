# Changelog

All notable changes to this project are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [0.1.0] - Unreleased

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
