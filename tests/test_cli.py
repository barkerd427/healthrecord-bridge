from __future__ import annotations

import json

from conftest import HANDWRITTEN, SYNTHEA, XDM_ZIP
from healthrecord_bridge.cli import main


def test_cli_writes_bundle_ndjson_and_report(tmp_path, capsys):
    out = tmp_path / "bundle.json"
    report = tmp_path / "report.json"
    ndjson = tmp_path / "ndjson"
    rc = main(
        [
            "ccda2fhir",
            str(HANDWRITTEN),
            str(XDM_ZIP),
            "-o",
            str(out),
            "--ndjson",
            str(ndjson),
            "--report",
            str(report),
            "--pretty",
        ]
    )
    assert rc == 0
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "mychart_like_ccd.xml" in captured.err
    assert "total across 2 documents" in captured.err
    bundle = json.loads(out.read_text())
    assert bundle["resourceType"] == "Bundle"
    rep = json.loads(report.read_text())
    assert len(rep["documents"]) == 2
    assert rep["resource_counts"]["Patient"] == 2
    files = sorted(p.name for p in ndjson.iterdir())
    assert "Patient.ndjson" in files and "Observation.ndjson" in files
    patients = [json.loads(line) for line in (ndjson / "Patient.ndjson").read_text().splitlines()]
    assert len(patients) == 2
    total_lines = sum(len(p.read_text().splitlines()) for p in ndjson.iterdir())
    assert total_lines == len(bundle["entry"])


def test_cli_stdout_default(capsys):
    rc = main(["ccda2fhir", str(SYNTHEA[0]), "-q"])
    assert rc == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    assert json.loads(captured.out)["type"] == "collection"


def test_cli_error_exit_code(tmp_path, capsys):
    bad = tmp_path / "bad.xml"
    bad.write_text("<nope/>")
    rc = main(["ccda2fhir", str(bad)])
    assert rc == 1
    assert "error" in capsys.readouterr().err


def test_cli_assume_timezone(capsys):
    rc = main(["ccda2fhir", str(SYNTHEA[0]), "-q", "--assume-timezone=-04:00"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "-04:00" in out
