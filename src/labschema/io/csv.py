"""CSV and TSV reading for LabSchema."""

from __future__ import annotations

import csv
import io
import os
from collections.abc import Collection
from pathlib import Path
from typing import TYPE_CHECKING, Literal, TextIO

from labschema.errors import ErrorCode, ReadError, ValidationIssue
from labschema.validate import DEFAULT_NA_VALUES, ValidationReport, ValidationResult, _Validator

if TYPE_CHECKING:
    from labschema.schema import TableSchema


def _detect_delimiter(sample: str) -> str:
    """Detect the delimiter from a sample of the file."""
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        return dialect.delimiter
    except csv.Error:
        return ","


def read_csv(
    source: str | os.PathLike[str] | TextIO,
    schema: TableSchema,
    *,
    delimiter: str | None = None,
    decimal: Literal[".", ","] = ".",
    thousands: str | None = None,
    encoding: str = "utf-8-sig",
    na_values: Collection[str] | None = None,
    extra_na_values: Collection[str] = (),
    skip_rows: int = 0,
    comment: str | None = None,
    max_errors: int | None = 1000,
    strip: bool = True,
) -> ValidationResult:
    """Read and validate a CSV file against a schema.

    Args:
        source: File path, Path object, or text stream.
        schema: The TableSchema to validate against.
        delimiter: Column delimiter. None = auto-detect.
        decimal: Decimal separator for numeric fields.
        thousands: Thousands separator to strip.
        encoding: File encoding (default: utf-8-sig to handle BOM).
        na_values: Replace the default missing-value sentinel set.
        extra_na_values: Add to the default missing-value sentinel set.
        skip_rows: Lines to skip before the header.
        comment: Lines starting with this prefix are ignored.
        max_errors: Stop collecting issues after this many errors. None = unlimited.
        strip: Trim whitespace around cells.

    Returns:
        ValidationResult with validated records.

    Raises:
        ReadError: If the file cannot be read.
    """
    if thousands is not None and thousands == decimal:
        raise ReadError("thousands separator cannot be the same as decimal separator")

    if na_values is not None:
        all_na_values = frozenset(na_values)
    else:
        all_na_values = DEFAULT_NA_VALUES | frozenset(extra_na_values)

    if isinstance(source, (str, os.PathLike)):
        path = Path(source)
        try:
            content = path.read_text(encoding=encoding)
        except OSError as e:
            raise ReadError(f"Cannot read file: {e}") from e
        text_content = content
    else:
        text_content = source.read()

    lines = text_content.splitlines(keepends=False)

    for _ in range(skip_rows):
        if lines:
            lines.pop(0)

    if comment:
        lines = [line for line in lines if not line.startswith(comment)]

    if not lines:
        raise ReadError("File is empty or contains no data rows")

    if delimiter is None:
        sample = "\n".join(lines[: min(10, len(lines))])
        delimiter = _detect_delimiter(sample)

    content = "\n".join(lines)

    try:
        reader = csv.reader(io.StringIO(content), delimiter=delimiter)
        rows = list(reader)
    except csv.Error as e:
        report = ValidationReport()
        report.issues.append(
            ValidationIssue(
                code=ErrorCode.PARSE_ERROR,
                severity="error",
                message=f"Malformed CSV: {e}",
            )
        )
        return ValidationResult(
            report=report,
            records=[],
            column_units={},
        )

    if not rows:
        raise ReadError("File is empty or contains no data rows")

    headers = rows[0]
    if strip:
        headers = [h.strip() for h in headers]

    data_rows = rows[1:]

    validator = _Validator(
        schema=schema,
        na_values=all_na_values,
        max_errors=max_errors,
        decimal=decimal,
        thousands=thousands,
    )

    if not validator.validate_headers(headers):
        return validator.get_result()

    for i, row in enumerate(data_rows):
        if strip:
            row = [cell.strip() for cell in row]
        line_number = i + 2 + skip_rows
        if not validator.validate_row(row, headers, line_number):
            break

    return validator.get_result()


def read_tsv(
    source: str | os.PathLike[str] | TextIO,
    schema: TableSchema,
    *,
    decimal: Literal[".", ","] = ".",
    thousands: str | None = None,
    encoding: str = "utf-8-sig",
    na_values: Collection[str] | None = None,
    extra_na_values: Collection[str] = (),
    skip_rows: int = 0,
    comment: str | None = None,
    max_errors: int | None = 1000,
    strip: bool = True,
) -> ValidationResult:
    """Read and validate a TSV file against a schema.

    This is equivalent to read_csv(..., delimiter="\\t").

    Args:
        source: File path, Path object, or text stream.
        schema: The TableSchema to validate against.
        decimal: Decimal separator for numeric fields.
        thousands: Thousands separator to strip.
        encoding: File encoding (default: utf-8-sig to handle BOM).
        na_values: Replace the default missing-value sentinel set.
        extra_na_values: Add to the default missing-value sentinel set.
        skip_rows: Lines to skip before the header.
        comment: Lines starting with this prefix are ignored.
        max_errors: Stop collecting issues after this many errors. None = unlimited.
        strip: Trim whitespace around cells.

    Returns:
        ValidationResult with validated records.

    Raises:
        ReadError: If the file cannot be read.
    """
    return read_csv(
        source,
        schema,
        delimiter="\t",
        decimal=decimal,
        thousands=thousands,
        encoding=encoding,
        na_values=na_values,
        extra_na_values=extra_na_values,
        skip_rows=skip_rows,
        comment=comment,
        max_errors=max_errors,
        strip=strip,
    )


def read_text(
    text: str,
    schema: TableSchema,
    *,
    delimiter: str | None = None,
    decimal: Literal[".", ","] = ".",
    thousands: str | None = None,
    na_values: Collection[str] | None = None,
    extra_na_values: Collection[str] = (),
    skip_rows: int = 0,
    comment: str | None = None,
    max_errors: int | None = 1000,
    strip: bool = True,
) -> ValidationResult:
    """Read and validate CSV data from an in-memory string.

    Args:
        text: The CSV text to parse.
        schema: The TableSchema to validate against.
        delimiter: Column delimiter. None = auto-detect.
        decimal: Decimal separator for numeric fields.
        thousands: Thousands separator to strip.
        na_values: Replace the default missing-value sentinel set.
        extra_na_values: Add to the default missing-value sentinel set.
        skip_rows: Lines to skip before the header.
        comment: Lines starting with this prefix are ignored.
        max_errors: Stop collecting issues after this many errors. None = unlimited.
        strip: Trim whitespace around cells.

    Returns:
        ValidationResult with validated records.
    """
    return read_csv(
        io.StringIO(text),
        schema,
        delimiter=delimiter,
        decimal=decimal,
        thousands=thousands,
        na_values=na_values,
        extra_na_values=extra_na_values,
        skip_rows=skip_rows,
        comment=comment,
        max_errors=max_errors,
        strip=strip,
    )
