# Synthetic Epic MyChart export

`mychart_epic_synthetic.xml` started life as a real Epic MyChart "Download my record"
Continuity of Care Document. It was run through `hrb synthesize` three times, with seeds that
are not published, so that none of the output can be traced back to the download. Every name,
identifier, address, telecom, date, code translation and clinical value in it is made up;
Epic customer OIDs carry customer number `0`.

What survives is Epic's structure, which neither Synthea nor the hand-written fixture
reproduces: the section set and order (including a patient-facing note section coded
`X-CE-PFD`, Medical Devices and Care Teams), Epic's document and entry template ids,
result organizers with `sdtc:text` and specimen and performer details, lab observations
coded only by Epic-local code systems with the test name only in the narrative, text results
as `ED` values that reference the narrative, CDA ids reused across result observations,
medication orders with NDC and NDDF translations, narrative references in every section, and
the reference range and interpretation layout Epic uses.

`tests/test_epic_fixture.py` exercises it.
