"""Smoke test over the full Synthea C-CDA sample set (1,180 documents).

Deselected by default (``-m "not slow"`` in addopts). Enable with::

    HRB_SYNTHEA_DIR=/path/to/extracted/ccda uv run pytest -m slow
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from healthrecord_bridge.ccda import convert

pytestmark = pytest.mark.slow


def _synthea_dir() -> Path | None:
    raw = os.environ.get("HRB_SYNTHEA_DIR")
    if not raw:
        return None
    p = Path(raw)
    return p if p.is_dir() else None


def test_full_synthea_sample_set():
    directory = _synthea_dir()
    if directory is None:
        pytest.skip("set HRB_SYNTHEA_DIR to the extracted Synthea C-CDA sample set")
    files = sorted(directory.glob("*.xml"))
    assert files, f"no XML files under {directory}"
    failures: list[tuple[str, str]] = []
    total_resources = 0
    for path in files:
        try:
            bundle, report = convert(path)
        except Exception as exc:
            failures.append((path.name, f"{type(exc).__name__}: {exc}"))
            continue
        total_resources += len(bundle["entry"])
        doc = report.documents[0]
        for section in doc.sections:
            if section.skipped:
                failures.append((path.name, f"{section.name}: {section.skipped[0].reason}"))
                break
    print(f"\n{len(files)} documents, {total_resources} resources, {len(failures)} with problems")
    for name, why in failures[:20]:
        print(f"  {name}: {why}")
    assert not failures, f"{len(failures)} of {len(files)} documents had problems"
