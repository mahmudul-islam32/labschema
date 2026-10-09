"""Schema inference from CSV/TSV files."""

from __future__ import annotations

import csv
import io
import os
from collections.abc import Collection
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, TextIO

from labschema.errors import ReadError
from labschema.fields import Field
from labschema.schema import TableSchema, normalize_name
from labschema.units import parse_header_unit
from labschema.validate import DEFAULT_NA_VALUES

if TYPE_CHECKING:
    pass


def _get_version() -> str:
    """Get version without circular import."""
    from labschema import __version__

    return __version__


def _detect_delimiter(sample: str) -> str:
    """Detect the delimiter from a sample of the file."""
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        return dialect.delimiter
    except csv.Error:
        return ","


def _try_parse_bool(value: str) -> bool | None:
    """Try to parse a value as boolean."""
    lower = value.lower()
    if lower in ("true", "yes", "y", "1", "t"):
        return True
    if lower in ("false", "no", "n", "0", "f"):
        return False
    return None


def _try_parse_int(value: str, decimal: str = ".") -> int | None:
    """Try to parse a value as integer."""
    try:
        if decimal != ".":
            value = value.replace(decimal, ".")

        if "." in value:
            float_val = float(value)
            if float_val == int(float_val):
                return int(float_val)
            return None
        return int(value)
    except (ValueError, TypeError):
        return None


def _try_parse_float(value: str, decimal: str = ".") -> float | None:
    """Try to parse a value as float."""
    try:
        if decimal != ".":
            value = value.replace(decimal, ".")
        return float(value)
    except (ValueError, TypeError):
        return None


def _infer_dtype(values: list[str], decimal: str = ".") -> tuple[type, bool]:
    """Infer the dtype from a list of non-missing values.

    Returns:
        (dtype, nullable) where nullable is True if there were any missing values.
    """
    if not values:
        return str, True

    all_bool = True
    all_int = True
    all_float = True

    for v in values:
        if all_bool and _try_parse_bool(v) is None:
            all_bool = False

        if all_int and _try_parse_int(v, decimal) is None:
            all_int = False

        if all_float and _try_parse_float(v, decimal) is None:
            all_float = False

        if not (all_bool or all_int or all_float):
            break

    if all_bool:
        return bool, False
    if all_int:
        return int, False
    if all_float:
        return float, False
    return str, False


def _format_observed_range(values: list[Any], dtype: type) -> str | None:
    """Format the observed range for a description."""
    if not values:
        return None

    if dtype in (int, float):
        numeric_values = []
        for v in values:
            parsed = _try_parse_int(str(v)) if dtype is int else _try_parse_float(str(v))
            if parsed is not None:
                numeric_values.append(parsed)

        if numeric_values:
            min_val = min(numeric_values)
            max_val = max(numeric_values)
            return f"observed range {min_val}–{max_val} in {len(values)} sampled rows"

    return None


def infer_schema(
    source: str | os.PathLike[str] | TextIO,
    *,
    sample_rows: int = 100,
    name: str | None = None,
    delimiter: str | None = None,
    decimal: Literal[".", ","] = ".",
    thousands: str | None = None,
    encoding: str = "utf-8-sig",
    na_values: Collection[str] | None = None,
    extra_na_values: Collection[str] = (),
    skip_rows: int = 0,
    comment: str | None = None,
    strip: bool = True,
) -> TableSchema:
    """Infer a draft schema from a CSV/TSV file.

    The inferred schema is a draft meant for human review before use.
    Units are only inferred from headers, never from values.

    Args:
        source: File path, Path object, or text stream.
        sample_rows: Number of rows to sample for type inference.
        name: Schema name (default: derived from filename or 'inferred_schema').
        delimiter: Column delimiter. None = auto-detect.
        decimal: Decimal separator for numeric fields.
        thousands: Thousands separator to strip.
        encoding: File encoding (default: utf-8-sig to handle BOM).
        na_values: Replace the default missing-value sentinel set.
        extra_na_values: Add to the default missing-value sentinel set.
        skip_rows: Lines to skip before the header.
        comment: Lines starting with this prefix are ignored.
        strip: Trim whitespace around cells.

    Returns:
        A TableSchema with inferred field types and units.

    Raises:
        ReadError: If the file cannot be read.
    """
    if na_values is not None:
        all_na_values = frozenset(na_values)
    else:
        all_na_values = DEFAULT_NA_VALUES | frozenset(extra_na_values)

    source_name: str | None = None

    if isinstance(source, (str, os.PathLike)):
        path = Path(source)
        source_name = str(source)
        try:
            content = path.read_text(encoding=encoding)
        except OSError as e:
            raise ReadError(f"Cannot read file: {e}") from e
        file_obj = io.StringIO(content)
        if name is None:
            name = normalize_name(path.stem) or "inferred_schema"
    else:
        file_obj = source
        if name is None:
            name = "inferred_schema"

    lines = file_obj.read().splitlines(keepends=False)

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
        raise ReadError(f"Malformed CSV: {e}") from e

    if not rows:
        raise ReadError("File is empty or contains no data rows")

    headers = rows[0]
    if strip:
        headers = [h.strip() for h in headers]

    data_rows = rows[1 : 1 + sample_rows]

    column_values: dict[int, list[str]] = {i: [] for i in range(len(headers))}
    column_missing: dict[int, int] = dict.fromkeys(range(len(headers)), 0)

    for row in data_rows:
        if strip:
            row = [cell.strip() for cell in row]

        for i, cell in enumerate(row):
            if i >= len(headers):
                continue

            if thousands and i < len(headers):
                cell = cell.replace(thousands, "")

            if cell in all_na_values:
                column_missing[i] += 1
            else:
                column_values[i].append(cell)

    fields: list[Field] = []

    for i, header in enumerate(headers):
        col_name, unit_str, _ = parse_header_unit(header)
        field_name = normalize_name(col_name)

        if not field_name:
            field_name = f"column_{i + 1}"

        values = column_values.get(i, [])
        has_missing = column_missing.get(i, 0) > 0

        if not values:
            dtype = str
            nullable = True
        else:
            dtype, _ = _infer_dtype(values, decimal)
            nullable = has_missing

        alias = header if header != col_name and header != field_name else None

        description_parts: list[str] = []
        observed_range = _format_observed_range(values, dtype)
        if observed_range:
            description_parts.append(observed_range)

        if dtype is str and values:
            unique_values = set(values)
            if len(unique_values) <= 10 and len(values) >= 20:
                sorted_values = sorted(unique_values)
                description_parts.append(f"distinct values: {sorted_values}")

        description = "; ".join(description_parts) if description_parts else None

        field_kwargs: dict[str, Any] = {
            "name": field_name,
            "dtype": dtype,
            "nullable": nullable,
        }

        if unit_str and dtype in (int, float):
            field_kwargs["unit"] = unit_str

        if description:
            field_kwargs["description"] = description

        if alias:
            field_kwargs["aliases"] = (alias,)

        fields.append(Field(**field_kwargs))

    metadata: dict[str, Any] = {
        "inferred": {
            "sample_rows": len(data_rows),
            "labschema_version": _get_version(),
        }
    }
    if source_name:
        metadata["inferred"]["source"] = source_name

    return TableSchema(
        name=name,
        fields=fields,
        metadata=metadata,
    )


def schema_to_python(schema: TableSchema) -> str:
    """Generate Python source code for a TableSchema.

    This creates editable source code that can be used in a Python script.

    Args:
        schema: The TableSchema to convert.

    Returns:
        Python source code as a string.
    """
    lines = [
        "from labschema import Field, TableSchema, u",
        "",
        "schema = TableSchema(",
        f"    name={schema.name!r},",
    ]

    if schema.primary_key:
        lines.append(f"    primary_key={schema.primary_key!r},")

    if schema.extra_columns != "warn":
        lines.append(f"    extra_columns={schema.extra_columns!r},")

    if schema.version:
        lines.append(f"    version={schema.version!r},")

    if schema.description:
        lines.append(f"    description={schema.description!r},")

    lines.append("    fields=[")

    for f in schema.fields:
        parts = [f"        Field({f.name!r}, {f.dtype.__name__}"]

        if f.unit:
            unit_str = f.unit_string or str(f.unit)
            parts.append(f", unit={unit_str!r}")

        if f.nullable:
            parts.append(", nullable=True")

        if f.ge is not None:
            parts.append(f", ge={f.ge!r}")
        if f.gt is not None:
            parts.append(f", gt={f.gt!r}")
        if f.le is not None:
            parts.append(f", le={f.le!r}")
        if f.lt is not None:
            parts.append(f", lt={f.lt!r}")

        if f.enum:
            parts.append(f", enum={list(f.enum)!r}")

        if f.pattern:
            parts.append(f", pattern={f.pattern!r}")

        if f.description:
            desc = f.description
            if len(desc) > 50:
                desc = desc[:47] + "..."
            parts.append(f", description={desc!r}")

        if f.aliases:
            parts.append(f", aliases={f.aliases!r}")

        parts.append("),")
        lines.append("".join(parts))

    lines.append("    ],")
    lines.append(")")
    lines.append("")

    return "\n".join(lines)
