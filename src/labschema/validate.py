"""Validation engine for LabSchema."""

from __future__ import annotations

import json
import math
import numbers
import re
import sys
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, TextIO

from pydantic import ConfigDict, TypeAdapter, ValidationError, create_model

from labschema.errors import ErrorCode, ValidationIssue
from labschema.fields import Field
from labschema.units import (
    are_units_compatible,
    canonical_header_unit,
    convert_value,
    format_unit,
    parse_header_unit,
)

if TYPE_CHECKING:
    from labschema.schema import TableSchema

DEFAULT_NA_VALUES = frozenset(
    {
        "",
        "NA",
        "N/A",
        "n/a",
        "NaN",
        "nan",
        "null",
        "NULL",
        "None",
        "-",
        "--",
        "#N/A",
        "#DIV/0!",
        "#VALUE!",
        "#REF!",
        "#NUM!",
    }
)

_BOOL_TRUE = frozenset({"true", "yes", "y", "1", "t"})
_BOOL_FALSE = frozenset({"false", "no", "n", "0", "f"})
_INT_LITERAL = re.compile(r"[+-]?\d+")


def _q(text: str) -> str:
    """Quote text the way validation messages do."""
    escaped = text.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _format_number(value: Any) -> str:
    """Format a bound or converted value without a trailing ``.0``."""
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, float) and math.isfinite(value) and value.is_integer():
        return str(int(value))
    return str(value)


def _build_row_adapter(schema: TableSchema) -> TypeAdapter[Any]:
    """Build one strict TypeAdapter for a schema and reuse it for every row.

    Locale decimals, sentinels, and unit conversion happen before this adapter
    sees a value, so it runs in strict mode.
    """
    definitions: dict[str, Any] = {}
    for column in schema.fields:
        annotation: Any = column.dtype
        if column.nullable:
            annotation = annotation | None
        definitions[column.name] = (annotation, ...)
    model = create_model(
        "LabSchemaRow",
        __config__=ConfigDict(strict=True, extra="forbid", protected_namespaces=()),
        **definitions,
    )
    return TypeAdapter(model)


@dataclass
class ValidationReport:
    """An ordered collection of validation issues.

    Attributes:
        issues: All issues found during validation.
        truncated: True if max_errors was reached.
    """

    issues: list[ValidationIssue] = field(default_factory=list)
    truncated: bool = False

    @property
    def errors(self) -> tuple[ValidationIssue, ...]:
        """Get all error-severity issues."""
        return tuple(i for i in self.issues if i.severity == "error")

    @property
    def warnings(self) -> tuple[ValidationIssue, ...]:
        """Get all warning-severity issues."""
        return tuple(i for i in self.issues if i.severity == "warning")

    def by_code(self) -> dict[ErrorCode, list[ValidationIssue]]:
        """Group issues by error code."""
        result: dict[ErrorCode, list[ValidationIssue]] = defaultdict(list)
        for issue in self.issues:
            result[issue.code].append(issue)
        return dict(result)

    def print_summary(
        self,
        file: TextIO = sys.stdout,
        limit: int = 20,
    ) -> None:
        """Print a human-readable summary of the validation report.

        Args:
            file: Output stream (default: stdout).
            limit: Maximum examples per error code.
        """
        by_code = self.by_code()

        for code, issues in sorted(by_code.items(), key=lambda x: x[0].value):
            severity_str = ""
            if issues and issues[0].severity == "warning":
                severity_str = " (warning)"

            print(f"\n  {code.value}{severity_str} ({len(issues)})", file=file)

            for issue in issues[:limit]:
                print(f"    {issue.message}", file=file)

            if len(issues) > limit:
                print(f"    … and {len(issues) - limit} more", file=file)

        if self.truncated:
            print("\n  (report truncated due to max_errors limit)", file=file)

    def to_dict(self) -> dict[str, Any]:
        """Convert the report to a dictionary for JSON serialization."""
        return {
            "issues": [i.to_dict() for i in self.issues],
            "truncated": self.truncated,
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
        }

    def to_json(self, indent: int | None = 2) -> str:
        """Convert the report to a JSON string."""
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)


@dataclass
class ValidationResult:
    """Result of validating data against a schema.

    Attributes:
        report: The validation report with all issues.
        records: List of valid rows, with values coerced and unit-converted.
        column_units: Source unit per field as found in the header.
        total_rows: Total number of data rows processed.
        valid_rows: Number of rows without errors.
    """

    report: ValidationReport
    records: list[dict[str, Any]]
    column_units: dict[str, str]
    total_rows: int = 0
    valid_rows: int = 0

    @property
    def ok(self) -> bool:
        """True if there are no errors."""
        return len(self.report.errors) == 0

    @property
    def errors(self) -> tuple[ValidationIssue, ...]:
        """Shortcut for report.errors."""
        return self.report.errors

    def to_records(self) -> list[dict[str, Any]]:
        """Return the list of valid records."""
        return self.records

    def to_pandas(self) -> Any:
        """Convert valid records to a pandas DataFrame.

        Returns:
            A pandas DataFrame with correct dtypes. Units are stored in
            ``df.attrs["labschema"]``.

        Raises:
            ImportError: If pandas is not installed.
        """
        try:
            import pandas as pd
        except ImportError as e:
            raise ImportError(
                "pandas is required for to_pandas(). "
                "Install it with: pip install 'labschema[pandas]'"
            ) from e

        df = pd.DataFrame(self.records)
        for column in df.columns:
            series = df[column]
            non_null = series.dropna()
            if non_null.empty:
                continue
            sample = non_null.iloc[0]
            kind = str(series.dtype)
            if isinstance(sample, bool) or kind in {"bool", "boolean"}:
                df[column] = series.astype("boolean")
            elif isinstance(sample, numbers.Integral) or kind.startswith(("int", "Int", "uint")):
                df[column] = series.astype("Int64")
            elif isinstance(sample, numbers.Real) or kind.startswith("float"):
                df[column] = series.astype("float64")
            elif isinstance(sample, str) or kind in {"object", "string"}:
                df[column] = series.astype("string")

        df.attrs["labschema"] = {
            "column_units": self.column_units,
            "valid_rows": self.valid_rows,
            "total_rows": self.total_rows,
        }

        return df


class _Validator:
    """Internal validation engine."""

    def __init__(
        self,
        schema: TableSchema,
        na_values: frozenset[str],
        max_errors: int | None,
        decimal: str = ".",
        thousands: str | None = None,
        strip: bool = True,
    ) -> None:
        self.schema = schema
        self.na_values = na_values
        self.max_errors = max_errors
        self.decimal = decimal
        self.thousands = thousands
        self.strip = strip

        self.report = ValidationReport()
        self.records: list[dict[str, Any]] = []
        self.column_units: dict[str, str] = {}
        self.total_rows = 0
        self.valid_rows = 0

        self._header_to_field: dict[str, Field] = {}
        self._header_unit: dict[str, str | None] = {}
        self._header_canonical: dict[str, str | None] = {}
        self._header_ambiguous: dict[str, bool] = {}
        self._field_header: dict[str, str] = {}
        self._skipped_fields: set[str] = set()
        self._seen_primary_keys: dict[tuple[Any, ...], int] = {}
        self._error_count = 0
        self._adapter = _build_row_adapter(schema)

    def _add_issue(self, issue: ValidationIssue) -> bool:
        """Add an issue and return True if we should continue."""
        self.report.issues.append(issue)
        if issue.severity == "error":
            self._error_count += 1
            if self.max_errors is not None and self._error_count >= self.max_errors:
                self.report.truncated = True
                return False
        return True

    def add_parse_error(self, message: str) -> bool:
        """Record a malformed-CSV error."""
        return self._add_issue(
            ValidationIssue(
                code=ErrorCode.PARSE_ERROR,
                severity="error",
                message=f"Malformed CSV: {message}",
            )
        )

    def validate_headers(self, headers: list[str]) -> bool:
        """Validate and map column headers.

        Returns:
            True if validation can continue, False if too many errors.
        """
        matched_fields: dict[str, list[str]] = defaultdict(list)

        for header in headers:
            name, unit_str, is_ambiguous = parse_header_unit(header)
            column = self.schema.match_header(name)

            if column is not None:
                matched_fields[column.name].append(header)
                self._header_to_field[header] = column
                self._header_unit[header] = unit_str
                self._header_ambiguous[header] = is_ambiguous
                self._field_header[column.name] = header
                canonical = canonical_header_unit(unit_str) if unit_str else None
                self._header_canonical[header] = canonical

                if unit_str:
                    self.column_units[column.name] = unit_str

        for field_name, matching_headers in matched_fields.items():
            if len(matching_headers) > 1:
                quoted = ", ".join(_q(item) for item in matching_headers)
                if not self._add_issue(
                    ValidationIssue(
                        code=ErrorCode.DUPLICATE_COLUMN,
                        severity="error",
                        message=f"columns {quoted} both map to field {_q(field_name)}",
                        field_name=field_name,
                    )
                ):
                    return False

        for column in self.schema.fields:
            if column.name not in matched_fields:
                if column.nullable or column.has_default:
                    if not self._add_issue(
                        ValidationIssue(
                            code=ErrorCode.MISSING_COLUMN,
                            severity="warning",
                            message=(
                                f"missing column for field {_q(column.name)} (using null or default)"
                            ),
                            field_name=column.name,
                        )
                    ):
                        return False
                else:
                    if not self._add_issue(
                        ValidationIssue(
                            code=ErrorCode.MISSING_COLUMN,
                            severity="error",
                            message=f"missing column for required field {_q(column.name)}",
                            field_name=column.name,
                        )
                    ):
                        return False

        for header in headers:
            if header not in self._header_to_field:
                policy = self.schema.extra_columns
                if policy == "ignore":
                    continue
                severity = "error" if policy == "error" else "warning"
                if not self._add_issue(
                    ValidationIssue(
                        code=ErrorCode.EXTRA_COLUMN,
                        severity=severity,
                        message=f"column {_q(header)} does not match any field",
                        column=header,
                    )
                ):
                    return False

        for header, column in self._header_to_field.items():
            unit_str = self._header_unit.get(header)
            canonical = self._header_canonical.get(header)

            if self._header_ambiguous.get(header, False):
                if not self._add_issue(
                    ValidationIssue(
                        code=ErrorCode.UNIT_AMBIGUOUS,
                        severity="warning",
                        message=(
                            f"column {_q(header)}: unit {_q(unit_str or 'C')} "
                            "interpreted as degrees Celsius (ambiguous with coulomb)"
                        ),
                        column=header,
                        field_name=column.name,
                    )
                ):
                    return False

            if unit_str is None:
                continue

            if canonical is None:
                self._skipped_fields.add(column.name)
                if not self._add_issue(
                    ValidationIssue(
                        code=ErrorCode.UNIT_UNKNOWN,
                        severity="error",
                        message=f"column {_q(header)}: unit {_q(unit_str)} is not a known unit",
                        column=header,
                        field_name=column.name,
                        context={"header_unit": unit_str},
                    )
                ):
                    return False
                continue

            if column.unit is None:
                if not self._add_issue(
                    ValidationIssue(
                        code=ErrorCode.UNIT_UNEXPECTED,
                        severity="warning",
                        message=(
                            f"column {_q(header)}: unit {_q(unit_str)} "
                            f"is not declared on field {_q(column.name)}"
                        ),
                        column=header,
                        field_name=column.name,
                        context={"header_unit": unit_str},
                    )
                ):
                    return False
                continue

            field_unit = column.unit_string or str(column.unit)
            if not are_units_compatible(canonical, field_unit):
                self._skipped_fields.add(column.name)
                shown = format_unit(field_unit) or field_unit
                if not self._add_issue(
                    ValidationIssue(
                        code=ErrorCode.UNIT_INCOMPATIBLE,
                        severity="error",
                        message=(
                            f"column {_q(header)}: unit {_q(unit_str)} "
                            f"is incompatible with field unit {_q(shown)}"
                        ),
                        column=header,
                        field_name=column.name,
                        context={"header_unit": unit_str, "field_unit": field_unit},
                    )
                ):
                    return False

        return True

    def validate_row(
        self,
        row: list[str],
        headers: list[str],
        line_number: int,
    ) -> bool:
        """Validate a single data row.

        Returns:
            True if validation can continue, False if too many errors.
        """
        self.total_rows += 1

        if len(row) != len(headers):
            if not self._add_issue(
                ValidationIssue(
                    code=ErrorCode.ROW_LENGTH_MISMATCH,
                    severity="error",
                    message=(
                        f"line {line_number}: expected {len(headers)} columns, got {len(row)}"
                    ),
                    row=line_number,
                    context={"expected": len(headers), "actual": len(row)},
                )
            ):
                return False
            return True

        record: dict[str, Any] = {}
        row_has_error = False

        for column in self.schema.fields:
            if column.name in self._skipped_fields:
                continue

            header: str | None = None
            raw_value = ""
            for candidate in headers:
                mapped = self._header_to_field.get(candidate)
                if mapped is not None and mapped.name == column.name:
                    header = candidate
                    raw_value = row[headers.index(candidate)]
                    break

            if header is None:
                if column.has_default:
                    record[column.name] = column.default
                elif column.nullable:
                    record[column.name] = None
                continue

            value, issue = self._validate_cell(column, header, raw_value, line_number)

            if issue is not None:
                row_has_error = True
                if not self._add_issue(issue):
                    return False
            else:
                record[column.name] = value

        if not row_has_error and not self._skipped_fields:
            try:
                self._adapter.validate_python(record)
            except ValidationError as exc:
                row_has_error = True
                err = exc.errors()[0]
                loc = err.get("loc") or ()
                fname = str(loc[0]) if loc else None
                header_name = self._field_header.get(fname or "", fname or "")
                if not self._add_issue(
                    ValidationIssue(
                        code=ErrorCode.TYPE_ERROR,
                        severity="error",
                        message=(
                            f"line {line_number}, column {_q(header_name)}: "
                            f"value is not a valid {err.get('type', 'value')}"
                        ),
                        row=line_number,
                        column=header_name or None,
                        field_name=fname,
                        context={"error": err.get("msg", "")},
                    )
                ):
                    return False

        pk_blocked = any(name in self._skipped_fields for name in self.schema.primary_key)
        if not row_has_error and self.schema.primary_key and not pk_blocked:
            pk_tuple = tuple(record.get(key) for key in self.schema.primary_key)
            if pk_tuple in self._seen_primary_keys:
                first_line = self._seen_primary_keys[pk_tuple]
                if len(self.schema.primary_key) == 1:
                    key_name = self.schema.primary_key[0]
                    message = (
                        f"line {line_number}: {key_name} {_q(str(record.get(key_name)))} "
                        f"already appears on line {first_line}"
                    )
                else:
                    parts = ", ".join(
                        f"{key} {_q(str(record.get(key)))}" for key in self.schema.primary_key
                    )
                    message = (
                        f"line {line_number}: primary key ({parts}) "
                        f"already appears on line {first_line}"
                    )
                if not self._add_issue(
                    ValidationIssue(
                        code=ErrorCode.DUPLICATE_PRIMARY_KEY,
                        severity="error",
                        message=message,
                        row=line_number,
                        context={
                            "first_row": first_line,
                            "key": dict(zip(self.schema.primary_key, pk_tuple, strict=True)),
                        },
                    )
                ):
                    return False
                row_has_error = True
            else:
                self._seen_primary_keys[pk_tuple] = line_number

        if not row_has_error:
            self.records.append(record)
            self.valid_rows += 1

        return True

    def _validate_cell(
        self,
        column: Field,
        header: str,
        raw_value: str,
        line_number: int,
    ) -> tuple[Any, ValidationIssue | None]:
        """Validate a single cell value.

        Returns:
            (value, issue) where issue is None if valid.
        """
        display_value = raw_value[:80] if len(raw_value) > 80 else raw_value
        stripped = raw_value.strip()

        if stripped in self.na_values:
            if column.has_default:
                return column.default, None
            if column.nullable:
                return None, None
            return None, ValidationIssue(
                code=ErrorCode.NULL_NOT_ALLOWED,
                severity="error",
                message=f"line {line_number}, column {_q(header)}: null value not allowed",
                row=line_number,
                column=header,
                field_name=column.name,
                value=display_value,
            )

        value, coerce_issue = self._coerce_value(column, header, raw_value, line_number)
        if coerce_issue is not None:
            return None, coerce_issue

        if column.dtype in (int, float) and column.unit is not None:
            canonical = self._header_canonical.get(header)
            if canonical is not None:
                field_unit = column.unit_string or str(column.unit)
                if are_units_compatible(canonical, field_unit):
                    try:
                        value = convert_value(value, canonical, field_unit)
                    except Exception as exc:
                        return None, ValidationIssue(
                            code=ErrorCode.TYPE_ERROR,
                            severity="error",
                            message=(
                                f"line {line_number}, column {_q(header)}: "
                                f"value {_q(display_value)} could not be converted to "
                                f"{format_unit(field_unit) or field_unit}"
                            ),
                            row=line_number,
                            column=header,
                            field_name=column.name,
                            value=display_value,
                            context={"error": str(exc)},
                        )
                    if column.dtype is int and isinstance(value, float):
                        if math.isfinite(value) and value.is_integer():
                            value = int(value)
                        else:
                            return None, ValidationIssue(
                                code=ErrorCode.TYPE_ERROR,
                                severity="error",
                                message=(
                                    f"line {line_number}, column {_q(header)}: "
                                    f"value {_q(display_value)} is not a valid int"
                                ),
                                row=line_number,
                                column=header,
                                field_name=column.name,
                                value=display_value,
                                context={"dtype": "int"},
                            )

        value, constraint_issue = self._check_constraints(
            column, header, value, raw_value, line_number
        )
        if constraint_issue is not None:
            return None, constraint_issue

        return value, None

    def _coerce_value(
        self,
        column: Field,
        header: str,
        raw_value: str,
        line_number: int,
    ) -> tuple[Any, ValidationIssue | None]:
        """Coerce a raw string value to the field's dtype."""
        display_value = raw_value[:80] if len(raw_value) > 80 else raw_value
        value = raw_value.strip() if self.strip else raw_value

        if self.thousands and column.dtype in (int, float):
            value = value.replace(self.thousands, "")

        if self.decimal != "." and column.dtype in (int, float):
            value = value.replace(self.decimal, ".")

        try:
            if column.dtype is int:
                if _INT_LITERAL.fullmatch(value):
                    return int(value), None
                float_val = float(value)
                if not math.isfinite(float_val) or not float_val.is_integer():
                    raise ValueError("Not an integer")
                return int(float_val), None

            if column.dtype is float:
                return float(value), None

            if column.dtype is bool:
                lower = value.lower()
                if lower in _BOOL_TRUE:
                    return True, None
                if lower in _BOOL_FALSE:
                    return False, None
                raise ValueError(f"Not a valid boolean: {value}")

            return value, None

        except (ValueError, TypeError, OverflowError) as exc:
            return None, ValidationIssue(
                code=ErrorCode.TYPE_ERROR,
                severity="error",
                message=(
                    f"line {line_number}, column {_q(header)}: "
                    f"value {_q(display_value)} is not a valid {column.dtype.__name__}"
                ),
                row=line_number,
                column=header,
                field_name=column.name,
                value=display_value,
                context={"dtype": column.dtype.__name__, "error": str(exc)},
            )

    def _check_constraints(
        self,
        column: Field,
        header: str,
        value: Any,
        raw_value: str,
        line_number: int,
    ) -> tuple[Any, ValidationIssue | None]:
        """Check field constraints on a coerced value.

        Custom validators may replace ``value``. The returned value is the one
        that should be stored when there is no issue.
        """
        display_value = raw_value[:80] if len(raw_value) > 80 else raw_value
        shown_unit = format_unit(column.unit_string)
        unit_suffix = f" {shown_unit}" if shown_unit else ""
        unit_context = {"unit": shown_unit} if shown_unit else {}

        if column.dtype in (int, float):
            if column.ge is not None and value < column.ge:
                return value, ValidationIssue(
                    code=ErrorCode.LESS_THAN_MINIMUM,
                    severity="error",
                    message=(
                        f"line {line_number}, column {_q(header)}: "
                        f"value {_format_number(value)} is less than minimum "
                        f"{_format_number(column.ge)}{unit_suffix}"
                    ),
                    row=line_number,
                    column=header,
                    field_name=column.name,
                    value=display_value,
                    context={"ge": column.ge, **unit_context},
                )

            if column.gt is not None and value <= column.gt:
                return value, ValidationIssue(
                    code=ErrorCode.LESS_THAN_MINIMUM,
                    severity="error",
                    message=(
                        f"line {line_number}, column {_q(header)}: "
                        f"value {_format_number(value)} is not greater than "
                        f"{_format_number(column.gt)}{unit_suffix}"
                    ),
                    row=line_number,
                    column=header,
                    field_name=column.name,
                    value=display_value,
                    context={"gt": column.gt, **unit_context},
                )

            if column.le is not None and value > column.le:
                return value, ValidationIssue(
                    code=ErrorCode.GREATER_THAN_MAXIMUM,
                    severity="error",
                    message=(
                        f"line {line_number}, column {_q(header)}: "
                        f"value {_format_number(value)} is greater than maximum "
                        f"{_format_number(column.le)}{unit_suffix}"
                    ),
                    row=line_number,
                    column=header,
                    field_name=column.name,
                    value=display_value,
                    context={"le": column.le, **unit_context},
                )

            if column.lt is not None and value >= column.lt:
                return value, ValidationIssue(
                    code=ErrorCode.GREATER_THAN_MAXIMUM,
                    severity="error",
                    message=(
                        f"line {line_number}, column {_q(header)}: "
                        f"value {_format_number(value)} is not less than "
                        f"{_format_number(column.lt)}{unit_suffix}"
                    ),
                    row=line_number,
                    column=header,
                    field_name=column.name,
                    value=display_value,
                    context={"lt": column.lt, **unit_context},
                )

        if column.enum is not None and value not in column.enum:
            return value, ValidationIssue(
                code=ErrorCode.NOT_IN_ENUM,
                severity="error",
                message=(
                    f"line {line_number}, column {_q(header)}: "
                    f"value {_q(display_value)} is not in allowed values"
                ),
                row=line_number,
                column=header,
                field_name=column.name,
                value=display_value,
                context={"enum": list(column.enum)},
            )

        if column.pattern is not None and column.dtype is str:
            if not re.fullmatch(column.pattern, value):
                return value, ValidationIssue(
                    code=ErrorCode.PATTERN_MISMATCH,
                    severity="error",
                    message=(
                        f"line {line_number}, column {_q(header)}: "
                        f"value {_q(display_value)} does not match pattern {_q(column.pattern)}"
                    ),
                    row=line_number,
                    column=header,
                    field_name=column.name,
                    value=display_value,
                    context={"pattern": column.pattern},
                )

        for validator in column.validators:
            try:
                value = validator(value)
            except ValueError as exc:
                validator_name = getattr(validator, "__name__", repr(validator))
                return value, ValidationIssue(
                    code=ErrorCode.CUSTOM_VALIDATOR,
                    severity="error",
                    message=(
                        f"line {line_number}, column {_q(header)}: "
                        f"custom validator {validator_name} rejected value: {exc}"
                    ),
                    row=line_number,
                    column=header,
                    field_name=column.name,
                    value=display_value,
                    context={"validator": validator_name, "error": str(exc)},
                )

        return value, None

    def get_result(self) -> ValidationResult:
        """Get the final validation result."""
        return ValidationResult(
            report=self.report,
            records=self.records,
            column_units=self.column_units,
            total_rows=self.total_rows,
            valid_rows=self.valid_rows,
        )


def validate_rows(
    rows: Iterable[Mapping[str, Any]],
    schema: TableSchema,
    *,
    max_errors: int | None = 1000,
) -> ValidationResult:
    """Validate already-parsed data (e.g., dicts from another source).

    Args:
        rows: Iterable of dictionaries representing rows.
        schema: The TableSchema to validate against.
        max_errors: Stop collecting issues after this many errors. None = unlimited.

    Returns:
        ValidationResult with validated records.
    """
    validator = _Validator(
        schema=schema,
        na_values=DEFAULT_NA_VALUES,
        max_errors=max_errors,
    )

    headers = list(schema.field_names)
    validator.validate_headers(headers)

    for line_number, row_dict in enumerate(rows, start=2):
        row_values = [
            "" if row_dict.get(header) is None else str(row_dict.get(header)) for header in headers
        ]
        if not validator.validate_row(row_values, headers, line_number):
            break

    return validator.get_result()
