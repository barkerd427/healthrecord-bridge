"""Discover C-CDA documents inside zip archives, including IHE XDM exports.

Epic MyChart's "Download my record" produces an IHE XDM archive shaped like
``MachineReadable_XDMFormat/IHE_XDM/<subset>/DOC0001.XML`` next to
``METADATA.XML``, ``INDEX.HTM`` and ``README.TXT``. Any zip that holds C-CDA XML
anywhere is accepted; the XDM layout is just preferred when present.
"""

from __future__ import annotations

import os
import zipfile
from collections.abc import Iterator
from pathlib import Path, PurePosixPath

MAX_MEMBER_BYTES = 256 * 1024 * 1024
"""Members larger than this (uncompressed) are refused to avoid zip bombs."""

_SKIP_NAMES = {"metadata.xml", "index.htm", "index.html", "readme.txt"}


def is_zip(path: str | os.PathLike[str]) -> bool:
    return zipfile.is_zipfile(path)


def iter_xml_members(zf: zipfile.ZipFile) -> Iterator[zipfile.ZipInfo]:
    """Yield XML members in a stable order, preferring those under an ``IHE_XDM`` folder."""
    xdm: list[zipfile.ZipInfo] = []
    other: list[zipfile.ZipInfo] = []
    for info in zf.infolist():
        if info.is_dir():
            continue
        p = PurePosixPath(info.filename)
        if p.suffix.lower() != ".xml" or p.name.lower() in _SKIP_NAMES:
            continue
        if any(part.upper() == "IHE_XDM" for part in p.parts):
            xdm.append(info)
        else:
            other.append(info)
    members = xdm if xdm else other
    yield from sorted(members, key=lambda i: i.filename)


def iter_documents(path: str | os.PathLike[str]) -> Iterator[tuple[str, bytes]]:
    """Yield ``(member name, bytes)`` for every candidate XML in the zip.

    Members are checked against ``MAX_MEMBER_BYTES`` before extraction.
    """
    with zipfile.ZipFile(path) as zf:
        for info in iter_xml_members(zf):
            if info.file_size > MAX_MEMBER_BYTES:
                raise ValueError(
                    f"{Path(path).name}:{info.filename} is {info.file_size} bytes, "
                    f"over the {MAX_MEMBER_BYTES} byte limit"
                )
            with zf.open(info) as fh:
                yield f"{Path(path).name}:{info.filename}", fh.read(MAX_MEMBER_BYTES + 1)
