"""Command-line interface for LabSchema."""

from __future__ import annotations

import argparse
import importlib
import json
import sys
from pathlib import Path
from typing import NoReturn

from labschema import __version__
from labschema.errors import LabSchemaError, ReadError, SchemaError
from labschema.infer import infer_schema, schema_to_python
from labschema.io import read_csv
from labschema.schema import TableSchema


def _load_schema(schema_path: str) -> TableSchema:
    """Load a schema from a file path or Python import path.

    Args:
        schema_path: Either a file path (ending in .json) or a Python import
                     path like 'mymodule:schema'.

    Returns:
        The loaded TableSchema.

    Raises:
        SchemaError: If the schema cannot be loaded.
    """
    if ":" in schema_path and not Path(schema_path).exists():
        module_path, attr_name = schema_path.rsplit(":", 1)
        try:
            module = importlib.import_module(module_path)
        except ImportError as e:
            raise SchemaError(f"Cannot import module {module_path!r}: {e}") from e

        try:
            schema = getattr(module, attr_name)
        except AttributeError as e:
            raise SchemaError(f"Module {module_path!r} has no attribute {attr_name!r}") from e

        if not isinstance(schema, TableSchema):
            raise SchemaError(
                f"{module_path}:{attr_name} is not a TableSchema (got {type(schema).__name__})"
            )
        return schema

    return TableSchema.load(schema_path)


def cmd_validate(args: argparse.Namespace) -> int:
    """Run the validate command."""
    try:
        schema = _load_schema(args.schema)
    except (SchemaError, ReadError) as e:
        print(f"Error loading schema: {e}", file=sys.stderr)
        return 2

    na_values = list(args.na) if args.na else []

    try:
        result = read_csv(
            args.data,
            schema,
            delimiter=args.delimiter,
            decimal=args.decimal,
            thousands=args.thousands,
            encoding=args.encoding,
            extra_na_values=na_values,
            skip_rows=args.skip_rows,
            comment=args.comment,
            max_errors=args.max_errors if args.max_errors > 0 else None,
        )
    except ReadError as e:
        print(f"Error reading file: {e}", file=sys.stderr)
        return 2

    if args.strict:
        has_problems = len(result.report.errors) > 0 or len(result.report.warnings) > 0
    else:
        has_problems = len(result.report.errors) > 0

    if args.quiet:
        return 1 if has_problems else 0

    if args.format == "json":
        output = {
            "file": str(args.data),
            "total_rows": result.total_rows,
            "valid_rows": result.valid_rows,
            **result.report.to_dict(),
        }
        print(json.dumps(output, indent=2))
    else:
        error_count = len(result.report.errors)
        warning_count = len(result.report.warnings)
        print(
            f"{args.data}: {result.total_rows} rows, "
            f"{result.valid_rows} valid, "
            f"{error_count} errors, "
            f"{warning_count} warnings"
        )

        if result.report.issues:
            result.report.print_summary()

    return 1 if has_problems else 0


def cmd_infer(args: argparse.Namespace) -> int:
    """Run the infer command."""
    try:
        schema = infer_schema(
            args.data,
            sample_rows=args.sample_rows,
            name=args.name,
        )
    except ReadError as e:
        print(f"Error reading file: {e}", file=sys.stderr)
        return 2

    output = schema_to_python(schema) if args.format == "python" else schema.to_json()

    if args.output:
        Path(args.output).write_text(output, encoding="utf-8")
    else:
        print(output)

    return 0


def cmd_export_schema(args: argparse.Namespace) -> int:
    """Run the export-schema command."""
    try:
        schema = _load_schema(args.schema)
    except (SchemaError, ReadError) as e:
        print(f"Error loading schema: {e}", file=sys.stderr)
        return 2

    if args.format == "jsonschema":
        output = json.dumps(schema.to_json_schema(), indent=2)
    else:
        output = schema.to_json()

    if args.output:
        Path(args.output).write_text(output, encoding="utf-8")
    else:
        print(output)

    return 0


def main(argv: list[str] | None = None) -> NoReturn:
    """Main entry point for the labschema CLI."""
    parser = argparse.ArgumentParser(
        prog="labschema",
        description="Validate lab-style CSV/TSV files against typed schemas with units.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"labschema {__version__}",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    validate_parser = subparsers.add_parser(
        "validate",
        help="Validate a data file against a schema.",
    )
    validate_parser.add_argument(
        "data",
        help="Path to the CSV/TSV file to validate.",
    )
    validate_parser.add_argument(
        "--schema",
        required=True,
        help="Path to a LabSchema JSON file, or a Python import path (module:attr).",
    )
    validate_parser.add_argument(
        "--delimiter",
        help="Column delimiter (default: auto-detect).",
    )
    validate_parser.add_argument(
        "--decimal",
        default=".",
        choices=[".", ","],
        help="Decimal separator (default: '.').",
    )
    validate_parser.add_argument(
        "--thousands",
        help="Thousands separator to strip.",
    )
    validate_parser.add_argument(
        "--encoding",
        default="utf-8-sig",
        help="File encoding (default: utf-8-sig).",
    )
    validate_parser.add_argument(
        "--skip-rows",
        type=int,
        default=0,
        dest="skip_rows",
        help="Lines to skip before the header.",
    )
    validate_parser.add_argument(
        "--comment",
        help="Lines starting with this prefix are ignored.",
    )
    validate_parser.add_argument(
        "--na",
        action="append",
        help="Extra missing-value sentinel (repeatable).",
    )
    validate_parser.add_argument(
        "--max-errors",
        type=int,
        default=1000,
        dest="max_errors",
        help="Maximum errors to collect (0 = unlimited, default: 1000).",
    )
    validate_parser.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="Output format (default: text).",
    )
    validate_parser.add_argument(
        "--strict",
        action="store_true",
        help="Treat warnings as errors.",
    )
    validate_parser.add_argument(
        "--quiet",
        action="store_true",
        help="Print nothing; rely on exit code.",
    )
    validate_parser.set_defaults(func=cmd_validate)

    infer_parser = subparsers.add_parser(
        "infer",
        help="Infer a draft schema from a data file.",
    )
    infer_parser.add_argument(
        "data",
        help="Path to the CSV/TSV file to analyze.",
    )
    infer_parser.add_argument(
        "--sample-rows",
        type=int,
        default=100,
        dest="sample_rows",
        help="Number of rows to sample (default: 100).",
    )
    infer_parser.add_argument(
        "--name",
        help="Schema name (default: derived from filename).",
    )
    infer_parser.add_argument(
        "--format",
        choices=["json", "python"],
        default="json",
        help="Output format (default: json).",
    )
    infer_parser.add_argument(
        "-o",
        "--output",
        help="Output file path (default: stdout).",
    )
    infer_parser.set_defaults(func=cmd_infer)

    export_parser = subparsers.add_parser(
        "export-schema",
        help="Export a schema to JSON or JSON Schema format.",
    )
    export_parser.add_argument(
        "schema",
        help="Path to a LabSchema JSON file, or a Python import path (module:attr).",
    )
    export_parser.add_argument(
        "--format",
        choices=["labschema", "jsonschema"],
        default="labschema",
        help="Output format (default: labschema).",
    )
    export_parser.add_argument(
        "-o",
        "--output",
        help="Output file path (default: stdout).",
    )
    export_parser.set_defaults(func=cmd_export_schema)

    args = parser.parse_args(argv)

    try:
        exit_code = args.func(args)
    except LabSchemaError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(2)
    except KeyboardInterrupt:
        sys.exit(130)

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
