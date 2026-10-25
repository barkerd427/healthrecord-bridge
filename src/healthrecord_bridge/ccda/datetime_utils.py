"""HL7 v3 timestamp (TS) parsing into FHIR ``date``, ``dateTime`` and ``instant`` strings.

HL7 TS values look like ``YYYYMMDDHHMMSS.ffff+ZZZZ`` with any prefix allowed.
FHIR keeps the precision of the source, so ``201905`` becomes ``2019-05`` and a
value with time-of-day keeps its time. FHIR requires a timezone whenever a time
is present. When the source omits it, the caller may supply an assumed offset;
otherwise the value is truncated to a date and the caller is told so.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_TS_RE = re.compile(
    r"^(?P<y>\d{4})(?P<mo>\d{2})?(?P<d>\d{2})?(?P<h>\d{2})?(?P<mi>\d{2})?(?P<s>\d{2})?"
    r"(?:\.(?P<f>\d+))?(?P<tz>[+-]\d{4})?$"
)
_OFFSET_RE = re.compile(r"^(Z|[+-]\d{2}:\d{2})$")


@dataclass(frozen=True, slots=True)
class ParsedTs:
    """Result of parsing a TS value."""

    value: str
    """FHIR string at the best precision that is valid."""
    has_time: bool
    """True when the source carried a time of day."""
    truncated: bool
    """True when the time of day was dropped because no timezone was known."""


def normalize_offset(offset: str | None) -> str | None:
    """Accept ``Z``, ``+HH:MM``, ``+HHMM`` or ``-HH:MM`` and return FHIR form."""
    if offset is None:
        return None
    offset = offset.strip()
    if offset.upper() == "Z":
        return "Z"
    m = re.match(r"^([+-])(\d{2}):?(\d{2})$", offset)
    if not m:
        raise ValueError(f"not a timezone offset: {offset!r}")
    return f"{m.group(1)}{m.group(2)}:{m.group(3)}"


def parse_ts(raw: str | None, assume_tz: str | None = None) -> ParsedTs | None:
    """Parse an HL7 TS into a FHIR date or dateTime string.

    Returns ``None`` for empty or malformed input. ``assume_tz`` is a FHIR
    offset such as ``-05:00`` or ``Z`` used when the value has a time but no
    offset of its own.
    """
    if not raw:
        return None
    m = _TS_RE.match(raw.strip())
    if not m:
        return None
    y, mo, d, h, mi, s, f, tz = m.groups()
    if int(y) == 0:
        return None
    date = y
    if mo:
        if not 1 <= int(mo) <= 12:
            return None
        date += f"-{mo}"
        if d:
            if not 1 <= int(d) <= 31:
                return None
            date += f"-{d}"
    if not (h and d):
        return ParsedTs(date, False, False)
    if not 0 <= int(h) <= 23:
        return None
    mi = mi or "00"
    s = s or "00"
    if int(mi) > 59 or int(s) > 60:
        return None
    time = f"{h}:{mi}:{s}"
    if f:
        time += f".{f[:3]}"
    if tz:
        offset: str | None = f"{tz[:3]}:{tz[3:]}"
    else:
        offset = assume_tz
    if offset is None:
        return ParsedTs(date, True, True)
    return ParsedTs(f"{date}T{time}{offset}", True, False)


def to_instant(raw: str | None, fallback_tz: str = "Z") -> str | None:
    """Coerce a TS to a FHIR ``instant`` (full date, time and offset).

    Missing time components are padded with zeros and a missing offset is filled
    with ``fallback_tz``. Only used for the few fields FHIR declares as ``instant``
    (``Provenance.recorded`` and ``DocumentReference.date``).
    """
    parsed = parse_ts(raw, fallback_tz)
    if parsed is None:
        return None
    v = parsed.value
    if "T" in v:
        return v
    if len(v) == 4:
        v += "-01-01"
    elif len(v) == 7:
        v += "-01"
    return f"{v}T00:00:00{fallback_tz}"


def date_only(parsed: ParsedTs | None) -> str | None:
    """Return just the date part of a parsed TS (for FHIR ``date`` fields)."""
    if parsed is None:
        return None
    return parsed.value.split("T", 1)[0]
