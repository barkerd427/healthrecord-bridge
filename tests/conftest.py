from __future__ import annotations

from pathlib import Path

import pytest
from lxml import etree

FIXTURES = Path(__file__).parent / "fixtures"
SYNTHEA = sorted((FIXTURES / "synthea").glob("*.xml"))
HANDWRITTEN = FIXTURES / "handwritten" / "mychart_like_ccd.xml"
EPIC = FIXTURES / "epic" / "mychart_epic_synthetic.xml"
XDM_ZIP = FIXTURES / "xdm" / "mychart_export_letha284.zip"
XDM_SOURCE_XML = FIXTURES / "synthea" / "Letha284_Haag279_b9a32653-9fde-401f-bb32-9932e680c456.xml"
ALL_XML = [*SYNTHEA, HANDWRITTEN, EPIC]

NS = {"c": "urn:hl7-org:v3"}


def section_entry_counts(path: Path) -> dict[str, int]:
    """Independent count of ``entry`` elements per section LOINC code, straight from lxml."""
    tree = etree.parse(str(path))
    counts: dict[str, int] = {}
    for sec in tree.iterfind(".//c:section", NS):
        code = sec.find("c:code", NS)
        key = code.get("code") if code is not None else "?"
        counts[key] = counts.get(key, 0) + len(sec.findall("c:entry", NS))
    return counts


def component_observation_counts(path: Path, section_code: str) -> tuple[int, int]:
    """(organizers, component observations) in the section with ``section_code``."""
    tree = etree.parse(str(path))
    organizers = 0
    observations = 0
    for sec in tree.iterfind(".//c:section", NS):
        code = sec.find("c:code", NS)
        if code is None or code.get("code") != section_code:
            continue
        for entry in sec.findall("c:entry", NS):
            org = entry.find("c:organizer", NS)
            if org is not None:
                organizers += 1
                observations += len(org.findall("c:component/c:observation", NS))
            elif entry.find("c:observation", NS) is not None:
                observations += 1
    return organizers, observations


def by_type(bundle: dict) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for e in bundle["entry"]:
        r = e["resource"]
        out.setdefault(r["resourceType"], []).append(r)
    return out


@pytest.fixture(params=ALL_XML, ids=lambda p: p.stem[:24])
def fixture_path(request) -> Path:
    return request.param
