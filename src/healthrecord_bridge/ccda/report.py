"""Structured account of what a conversion did and did not map."""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass, field


@dataclass(slots=True)
class SkippedEntry:
    """One CDA entry that produced no resource."""

    reason: str
    ordinal: int
    """Zero-based position of the entry within its section."""


@dataclass(slots=True)
class SectionReport:
    """Outcome for one recognised section."""

    name: str
    code: str | None
    entries_seen: int = 0
    resources_produced: int = 0
    skipped: list[SkippedEntry] = field(default_factory=list)
    null_flavor: str | None = None
    """Set when the section itself is marked ``nullFlavor`` (for example "no known allergies")."""


@dataclass(slots=True)
class UnknownSection:
    """A section the converter does not map yet."""

    code: str | None
    title: str | None
    entries: int


@dataclass(slots=True)
class DocumentReport:
    """Report for a single C-CDA document."""

    source: str
    document_id: str
    sections: list[SectionReport] = field(default_factory=list)
    unknown_sections: list[UnknownSection] = field(default_factory=list)
    unmapped_code_systems: list[str] = field(default_factory=list)
    resource_counts: dict[str, int] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def section(self, name: str) -> SectionReport | None:
        for s in self.sections:
            if s.name == name:
                return s
        return None


@dataclass(slots=True)
class ConversionReport:
    """Report for a whole conversion run (one or more documents)."""

    documents: list[DocumentReport] = field(default_factory=list)

    @property
    def resource_counts(self) -> dict[str, int]:
        total: Counter[str] = Counter()
        for d in self.documents:
            total.update(d.resource_counts)
        return dict(sorted(total.items()))

    @property
    def unmapped_code_systems(self) -> list[str]:
        return sorted({oid for d in self.documents for oid in d.unmapped_code_systems})

    def to_dict(self) -> dict:
        return {
            "documents": [asdict(d) for d in self.documents],
            "resource_counts": self.resource_counts,
            "unmapped_code_systems": self.unmapped_code_systems,
        }

    def format(self) -> str:
        """Plain-text rendering for a terminal."""
        lines: list[str] = []
        for d in self.documents:
            lines.append(f"{d.source} (document id {d.document_id})")
            width = max((len(s.name) for s in d.sections), default=10)
            for s in d.sections:
                flag = f"  [section nullFlavor={s.null_flavor}]" if s.null_flavor else ""
                lines.append(
                    f"  {s.name:<{width}}  entries {s.entries_seen:>4}  "
                    f"resources {s.resources_produced:>4}  skipped {len(s.skipped):>3}{flag}"
                )
                reasons = Counter(k.reason for k in s.skipped)
                for reason, n in reasons.most_common():
                    lines.append(f"  {'':<{width}}    {n} x {reason}")
            if d.unknown_sections:
                lines.append("  not mapped in this version:")
                for u in d.unknown_sections:
                    lines.append(
                        f"    {u.code or '(no code)':<10} {u.title or ''} ({u.entries} entries)"
                    )
            if d.unmapped_code_systems:
                lines.append(
                    "  code systems emitted as urn:oid: " + ", ".join(d.unmapped_code_systems)
                )
            for note in d.notes:
                lines.append(f"  note: {note}")
            counts = ", ".join(f"{k} {v}" for k, v in sorted(d.resource_counts.items()))
            lines.append(f"  resources: {counts}")
        if len(self.documents) > 1:
            counts = ", ".join(f"{k} {v}" for k, v in self.resource_counts.items())
            lines.append(f"total across {len(self.documents)} documents: {counts}")
        return "\n".join(lines)
