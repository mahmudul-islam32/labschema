"""CSV and TSV reading for LabSchema."""

from __future__ import annotations

import csv
import io
import os
from collections.abc import Collection, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Literal, TextIO

from labschema.errors import ErrorCode, ReadError, ValidationIssue
from labschema.validate import DEFAULT_NA_VALUES, ValidationReport, ValidationResult, _Validator

if TYPE_CHECKING:
    from labschema.schema import TableSchema

_SNIFF_BYTES = 8192


def _detect_delimiter(sample: str) -> str:
    """Detect the delimiter from a sample of the file."""
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        return dialect.delimiter
    except csv.Error:
        return ","


class _TrackedLines:
    """Yield non-comment lines and remember their 1-based file line numbers."""

    def __init__(self, stream: TextIO, skip_rows: int, comment: str | None) -> None:
        self._stream = stream
        self._skip_rows = skip_rows
        self._comment = comment
        self.file_line = 0
        self.emitted_file_lines: list[int] = []

    def __iter__(self) -> _TrackedLines:
        return self

    def __next__(self) -> str:
        while True:
            line = self._stream.readline()
            if line == "":
                raise StopIteration
            self.file_line += 1
            if self.file_line <= self._skip_rows:
                continue
            body = line.rstrip("\r\n")
            if self._comment and body.startswith(self._comment):
                continue
            self.emitted_file_lines.append(self.file_line)
            return body + "\n"


def _open_source(
    source: str | os.PathLike[str] | TextIO,
    encoding: str,
) -> tuple[TextIO, bool]:
    if isinstance(source, (str, os.PathLike)):
        path = Path(source)
        try:
            return path.open(encoding=encoding, newline=""), True
        except (OSError, UnicodeError) as exc:
            raise ReadError(f"Cannot read file: {exc}") from exc
    return source, False


class _ParseFailure(Exception):
    """Internal signal that the CSV text itself is malformed."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


@contextmanager
def open_table(
    source: str | os.PathLike[str] | TextIO,
    *,
    delimiter: str | None = None,
    encoding: str = "utf-8-sig",
    skip_rows: int = 0,
    comment: str | None = None,
    strip: bool = True,
) -> Iterator[tuple[list[str], Iterator[tuple[int, list[str]]]]]:
    """Stream a delimited table as ``(headers, rows)``.

    Rows are ``(file_line_number, cells)``. The header is file line 1 when
    nothing is skipped. Memory stays proportional to one row plus an 8 KiB
    sniff sample, not the whole file.

    Raises:
        ReadError: The file is missing, empty, or not decodable.
        _ParseFailure: The CSV dialect cannot parse a row.
    """
    stream, close = _open_source(source, encoding)
    try:
        headers, rows = _stream_table(
            stream,
            delimiter=delimiter,
            skip_rows=skip_rows,
            comment=comment,
            strip=strip,
        )
        yield headers, rows
    finally:
        if close:
            stream.close()


def _stream_table(
    stream: TextIO,
    *,
    delimiter: str | None,
    skip_rows: int,
    comment: str | None,
    strip: bool,
) -> tuple[list[str], Iterator[tuple[int, list[str]]]]:
    tracked = _TrackedLines(stream, skip_rows, comment)
    sample: list[str] = []
    sample_size = 0
    try:
        while sample_size < _SNIFF_BYTES:
            piece = next(tracked)
            sample.append(piece)
            sample_size += len(piece)
    except StopIteration:
        pass
    except UnicodeError as exc:
        raise ReadError(f"Cannot read file: {exc}") from exc

    if not sample:
        raise ReadError("File is empty or contains no data rows")

    if delimiter is None:
        delimiter = _detect_delimiter("".join(sample)[:_SNIFF_BYTES])

    try:
        reader = csv.reader(_chain(sample, tracked), delimiter=delimiter)
        header_row = next(reader)
    except StopIteration as exc:
        raise ReadError("File is empty or contains no data rows") from exc
    except csv.Error as exc:
        raise _ParseFailure(str(exc)) from exc
    except UnicodeError as exc:
        raise ReadError(f"Cannot read file: {exc}") from exc

    headers = [cell.strip() if strip else cell for cell in header_row]
    start_index = reader.line_num

    def rows() -> Iterator[tuple[int, list[str]]]:
        nonlocal start_index
        while True:
            try:
                row = next(reader)
            except StopIteration:
                return
            except csv.Error as exc:
                raise _ParseFailure(str(exc)) from exc
            except UnicodeError as exc:
                raise ReadError(f"Cannot read file: {exc}") from exc
            file_line = tracked.emitted_file_lines[start_index]
            start_index = reader.line_num
            if strip:
                row = [cell.strip() for cell in row]
            yield file_line, row

    return headers, rows()


def _chain(first: list[str], rest: _TrackedLines) -> Iterator[str]:
    yield from first
    yield from rest


def _parse_error_result(message: str) -> ValidationResult:
    report = ValidationReport()
    report.issues.append(
        ValidationIssue(
            code=ErrorCode.PARSE_ERROR,
            severity="error",
            message=f"Malformed CSV: {message}",
        )
    )
    return ValidationResult(report=report, records=[], column_units={})


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
        delimiter: Column delimiter. None = auto-detect from the first 8 KiB.
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

    try:
        with open_table(
            source,
            delimiter=delimiter,
            encoding=encoding,
            skip_rows=skip_rows,
            comment=comment,
            strip=strip,
        ) as (headers, rows):
            validator = _Validator(
                schema=schema,
                na_values=all_na_values,
                max_errors=max_errors,
                decimal=decimal,
                thousands=thousands,
                strip=strip,
            )
            if not validator.validate_headers(headers):
                return validator.get_result()

            try:
                for line_number, row in rows:
                    if not validator.validate_row(row, headers, line_number):
                        break
            except _ParseFailure as exc:
                validator.add_parse_error(exc.message)
            return validator.get_result()
    except _ParseFailure as exc:
        return _parse_error_result(exc.message)


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
    """Read and validate CSV data from an in-memory string."""
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
