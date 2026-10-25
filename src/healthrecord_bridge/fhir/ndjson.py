"""Write a Bundle as one NDJSON file per resource type (``Patient.ndjson``, ...).

This is the layout FHIR bulk-data importers and SQL-on-FHIR tools expect.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from .bundle import resources_by_type


def write_ndjson(bundle: dict, directory: str | os.PathLike[str]) -> dict[str, Path]:
    """Write ``<ResourceType>.ndjson`` files into ``directory`` and return their paths.

    Existing files for the same resource types are overwritten; files for types
    absent from the bundle are left alone.
    """
    out_dir = Path(directory)
    out_dir.mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}
    for rtype, resources in sorted(resources_by_type(bundle).items()):
        path = out_dir / f"{rtype}.ndjson"
        with path.open("w", encoding="utf-8") as fh:
            for r in resources:
                fh.write(json.dumps(r, ensure_ascii=False, separators=(",", ":")))
                fh.write("\n")
        written[rtype] = path
    return written
