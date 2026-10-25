"""Registry of C-CDA sections: how each is recognised and which mapper handles it."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from .context import Context
from .document import Section
from .mappers.allergies import map_allergies
from .mappers.encounters import map_encounters
from .mappers.immunizations import map_immunizations
from .mappers.medications import map_medications
from .mappers.problems import map_problems
from .mappers.procedures import map_procedures
from .mappers.results import map_results
from .mappers.social_history import map_social_history
from .mappers.vitals import map_vitals
from .report import SectionReport

Mapper = Callable[[Context, Section, SectionReport], list[dict]]


@dataclass(frozen=True, slots=True)
class SectionSpec:
    """A section the converter knows how to map.

    A section matches when its LOINC ``code/@code`` equals ``loinc`` or any of its
    ``templateId/@root`` values is in ``template_roots``; either match wins.
    """

    name: str
    loinc: str
    template_roots: frozenset[str]
    mapper: Mapper

    def matches(self, section: Section) -> bool:
        if section.code == self.loinc:
            return True
        return bool(self.template_roots & section.template_ids)


def _spec(name: str, loinc: str, base: str, mapper: Mapper) -> SectionSpec:
    return SectionSpec(name, loinc, frozenset({base, f"{base}.1"}), mapper)


SECTION_SPECS: tuple[SectionSpec, ...] = (
    _spec("Allergies", "48765-2", "2.16.840.1.113883.10.20.22.2.6", map_allergies),
    _spec("Medications", "10160-0", "2.16.840.1.113883.10.20.22.2.1", map_medications),
    _spec("Problems", "11450-4", "2.16.840.1.113883.10.20.22.2.5", map_problems),
    _spec("Procedures", "47519-4", "2.16.840.1.113883.10.20.22.2.7", map_procedures),
    _spec("Encounters", "46240-8", "2.16.840.1.113883.10.20.22.2.22", map_encounters),
    _spec("Vital Signs", "8716-3", "2.16.840.1.113883.10.20.22.2.4", map_vitals),
    _spec("Results", "30954-2", "2.16.840.1.113883.10.20.22.2.3", map_results),
    _spec("Immunizations", "11369-6", "2.16.840.1.113883.10.20.22.2.2", map_immunizations),
    _spec("Social History", "29762-2", "2.16.840.1.113883.10.20.22.2.17", map_social_history),
)

KNOWN_UNMAPPED: dict[str, str] = {
    "18776-5": "Plan of Treatment",
    "18748-4": "Diagnostic Imaging Report",
    "121181": "DICOM Object Catalog",
    "47420-5": "Functional Status",
    "10190-7": "Mental Status",
    "10157-6": "Family History",
    "46264-8": "Medical Equipment",
    "48768-6": "Payers",
    "42348-3": "Advance Directives",
    "61146-7": "Goals",
    "75310-3": "Health Concerns",
    "51848-0": "Assessment",
    "29299-5": "Reason for Visit",
    "10154-3": "Chief Complaint",
    "46239-0": "Chief Complaint and Reason for Visit",
    "8653-8": "Hospital Discharge Instructions",
    "11488-4": "Consultation Note",
    "61144-2": "Diet and Nutrition",
    "42346-7": "Medications Administered",
    "10164-2": "History of Present Illness",
    "11348-0": "Past Medical History",
    "29545-1": "Physical Exam",
    "30954-2": "Results",
    "59774-0": "Procedure Findings",
    "8648-8": "Hospital Course",
    "11535-2": "Hospital Discharge Diagnosis",
    "10183-2": "Hospital Discharge Medications",
    "42344-2": "Discharge Diet",
    "48765-2": "Allergies",
    "69730-0": "Instructions",
    "10187-3": "Review of Systems",
    "57852-6": "Problem list - Reported",
    "47519-4": "History of Procedures",
    "11369-6": "History of Immunization",
    "81321-7": "Care Team",
    "85847-2": "Patient Notes",
    "34117-2": "History and Physical Note",
}


def find_spec(section: Section) -> SectionSpec | None:
    for spec in SECTION_SPECS:
        if spec.matches(section):
            return spec
    return None
