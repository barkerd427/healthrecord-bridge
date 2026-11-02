"""``hrb`` command line interface."""

from __future__ import annotations

import argparse
import json
import secrets
import sys
from collections.abc import Sequence
from pathlib import Path

from . import __version__
from .ccda import CcdaError, convert_many
from .ccda.anonymize import anonymize_file
from .fhir.ndjson import write_ndjson


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hrb",
        description="Convert personal health record exports into FHIR R4.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    c = sub.add_parser(
        "ccda2fhir",
        help="convert HL7 C-CDA XML (bare files or MyChart XDM zips) to a FHIR R4 Bundle",
    )
    c.add_argument("inputs", metavar="INPUT", nargs="+", help=".xml or .zip input files")
    c.add_argument(
        "-o", "--output", metavar="bundle.json", help="write the Bundle here (default: stdout)"
    )
    c.add_argument(
        "--ndjson", metavar="DIR", help="also write one <ResourceType>.ndjson per type into DIR"
    )
    c.add_argument("--pretty", action="store_true", help="indent the JSON output")
    c.add_argument("--report", metavar="report.json", help="write the conversion report as JSON")
    c.add_argument(
        "--assume-timezone",
        metavar="OFFSET",
        help=(
            "UTC offset for timestamps that have a time but no offset "
            "(write negative offsets as --assume-timezone=-05:00)"
        ),
    )
    c.add_argument("-q", "--quiet", action="store_true", help="do not print the report to stderr")
    c.set_defaults(func=cmd_ccda2fhir)

    a = sub.add_parser(
        "anonymize",
        help="scrub identity and shift dates in a C-CDA XML file so it can be shared",
    )
    a.add_argument("input", metavar="INPUT", help="C-CDA XML file")
    a.add_argument("output", metavar="OUTPUT", help="where to write the scrubbed XML")
    a.add_argument(
        "--seed",
        metavar="SEED",
        help="seed for the day shift and id hashes (same seed, same output; default: random)",
    )
    a.add_argument("--report", metavar="report.json", help="write the anonymize report as JSON")
    a.set_defaults(func=cmd_anonymize)
    return parser


def cmd_ccda2fhir(args: argparse.Namespace) -> int:
    try:
        bundle, report = convert_many(args.inputs, assume_timezone=args.assume_timezone)
    except (CcdaError, FileNotFoundError, ValueError, OSError) as exc:
        print(f"hrb: error: {exc}", file=sys.stderr)
        return 1
    indent = 2 if args.pretty else None
    text = json.dumps(bundle, indent=indent, ensure_ascii=False)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.write("\n")
    elif not args.ndjson:
        sys.stdout.write(text)
        sys.stdout.write("\n")
    if args.ndjson:
        write_ndjson(bundle, args.ndjson)
    if args.report:
        with open(args.report, "w", encoding="utf-8") as fh:
            json.dump(report.to_dict(), fh, indent=2)
            fh.write("\n")
    if not args.quiet:
        print(report.format(), file=sys.stderr)
    return 0


def cmd_anonymize(args: argparse.Namespace) -> int:
    seed = args.seed if args.seed is not None else secrets.token_hex(8)
    try:
        report = anonymize_file(Path(args.input), Path(args.output), seed=seed)
    except (CcdaError, FileNotFoundError, ValueError, OSError) as exc:
        print(f"hrb: error: {exc}", file=sys.stderr)
        return 1
    if args.report:
        with open(args.report, "w", encoding="utf-8") as fh:
            json.dump(report.to_dict(), fh, indent=2)
            fh.write("\n")
    print(f"{args.output}: {report.summary()} (seed {seed})")
    if report.residual_findings:
        print(
            f"hrb: warning: {len(report.residual_findings)} residual findings; "
            "read the output before sharing it",
            file=sys.stderr,
        )
        for finding in report.residual_findings:
            print(f"  {finding}", file=sys.stderr)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
