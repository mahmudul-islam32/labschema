"""Validation engine for LabSchema."""

from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, TextIO

from labschema.errors import ErrorCode, ValidationIssue
from labschema.fields import Field
from labschema.units import are_units_compatible, convert_value, parse_header_unit

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
                print(f"    ... and {len(issues) - limit} more", file=file)

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
            A pandas DataFrame with correct dtypes.

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
    ) -> None:
        self.schema = schema
        self.na_values = na_values
        self.max_errors = max_errors
        self.decimal = decimal
        self.thousands = thousands

        self.report = ValidationReport()
        self.records: list[dict[str, Any]] = []
        self.column_units: dict[str, str] = {}
        self.total_rows = 0
        self.valid_rows = 0

        self._header_to_field: dict[str, Field] = {}
        self._header_unit: dict[str, str | None] = {}
        self._header_ambiguous: dict[str, bool] = {}
        self._seen_primary_keys: dict[tuple[Any, ...], int] = {}
        self._error_count = 0

    def _add_issue(self, issue: ValidationIssue) -> bool:
        """Add an issue and return True if we should continue."""
        self.report.issues.append(issue)
        if issue.severity == "error":
            self._error_count += 1
            if self.max_errors is not None and self._error_count >= self.max_errors:
                self.report.truncated = True
                return False
        return True

    def validate_headers(self, headers: list[str]) -> bool:
        """Validate and map column headers.

        Returns:
            True if validation can continue, False if too many errors.
        """
        matched_fields: dict[str, list[str]] = defaultdict(list)

        for header in headers:
            name, unit_str, is_ambiguous = parse_header_unit(header)
            f = self.schema.match_header(name)

            if f is not None:
                matched_fields[f.name].append(header)
                self._header_to_field[header] = f
                self._header_unit[header] = unit_str
                self._header_ambiguous[header] = is_ambiguous

                if unit_str:
                    self.column_units[f.name] = unit_str

        for field_name, matching_headers in matched_fields.items():
            if len(matching_headers) > 1:
                if not self._add_issue(
                    ValidationIssue(
                        code=ErrorCode.DUPLICATE_COLUMN,
                        severity="error",
                        message=f"Multiple columns map to field {field_name!r}: {matching_headers}",
                        field_name=field_name,
                    )
                ):
                    return False

        for f in self.schema.fields:
            if f.name not in matched_fields:
                if f.nullable or f.has_default:
                    if not self._add_issue(
                        ValidationIssue(
                            code=ErrorCode.MISSING_COLUMN,
                            severity="warning",
                            message=f"Missing column for field {f.name!r} (will use null/default)",
                            field_name=f.name,
                        )
                    ):
                        return False
                else:
                    if not self._add_issue(
                        ValidationIssue(
                            code=ErrorCode.MISSING_COLUMN,
                            severity="error",
                            message=f"Missing column for required field {f.name!r}",
                            field_name=f.name,
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
                        message=f"Column {header!r} does not match any field",
                        column=header,
                    )
                ):
                    return False

        for header, f in self._header_to_field.items():
            unit_str = self._header_unit.get(header)

            if self._header_ambiguous.get(header, False):
                if not self._add_issue(
                    ValidationIssue(
                        code=ErrorCode.UNIT_AMBIGUOUS,
                        severity="warning",
                        message=f"Column {header!r}: unit 'C' interpreted as Celsius (ambiguous with coulomb)",
                        column=header,
                        field_name=f.name,
                    )
                ):
                    return False

            if unit_str is not None:
                if f.unit is None:
                    if not self._add_issue(
                        ValidationIssue(
                            code=ErrorCode.UNIT_UNEXPECTED,
                            severity="warning",
                            message=f"Column {header!r} has unit {unit_str!r} but field {f.name!r} has no declared unit",
                            column=header,
                            field_name=f.name,
                            context={"header_unit": unit_str},
                        )
                    ):
                        return False
                else:
                    field_unit = f.unit_string or str(f.unit)
                    if not are_units_compatible(unit_str, field_unit):
                        if not self._add_issue(
                            ValidationIssue(
                                code=ErrorCode.UNIT_INCOMPATIBLE,
                                severity="error",
                                message=(
                                    f"Column {header!r}: unit {unit_str!r} is incompatible "
                                    f"with field unit {field_unit!r}"
                                ),
                                column=header,
                                field_name=f.name,
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
                    message=f"line {line_number}: expected {len(headers)} columns, got {len(row)}",
                    row=line_number,
                    context={"expected": len(headers), "actual": len(row)},
                )
            ):
                return False
            return True

        record: dict[str, Any] = {}
        row_has_error = False

        for f in self.schema.fields:
            header: str | None = None
            raw_value: str = ""
            for h in headers:
                if h in self._header_to_field and self._header_to_field[h].name == f.name:
                    header = h
                    idx = headers.index(h)
                    raw_value = row[idx]
                    break

            if header is None:
                if f.has_default:
                    record[f.name] = f.default
                elif f.nullable:
                    record[f.name] = None
                continue

            value, issue = self._validate_cell(f, header, raw_value, line_number)

            if issue is not None:
                row_has_error = True
                if not self._add_issue(issue):
                    return False
            else:
                record[f.name] = value

        if not row_has_error and self.schema.primary_key:
            pk_tuple = tuple(record.get(k) for k in self.schema.primary_key)
            if pk_tuple in self._seen_primary_keys:
                first_line = self._seen_primary_keys[pk_tuple]
                pk_str = ", ".join(f"{k}={record.get(k)!r}" for k in self.schema.primary_key)
                if not self._add_issue(
                    ValidationIssue(
                        code=ErrorCode.DUPLICATE_PRIMARY_KEY,
                        severity="error",
                        message=f"line {line_number}: duplicate primary key ({pk_str}) first seen on line {first_line}",
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
        f: Field,
        header: str,
        raw_value: str,
        line_number: int,
    ) -> tuple[Any, ValidationIssue | None]:
        """Validate a single cell value.

        Returns:
            (value, issue) where issue is None if valid.
        """
        display_value = raw_value[:80] if len(raw_value) > 80 else raw_value

        if raw_value.strip() in self.na_values:
            if f.has_default:
                return f.default, None
            elif f.nullable:
                return None, None
            else:
                return None, ValidationIssue(
                    code=ErrorCode.NULL_NOT_ALLOWED,
                    severity="error",
                    message=f"line {line_number}, column {header!r}: null value not allowed",
                    row=line_number,
                    column=header,
                    field_name=f.name,
                    value=display_value,
                )

        value, coerce_issue = self._coerce_value(f, header, raw_value, line_number)
        if coerce_issue is not None:
            return None, coerce_issue

        if f.dtype in (int, float) and f.unit is not None:
            header_unit = self._header_unit.get(header)
            if header_unit is not None:
                field_unit = f.unit_string or str(f.unit)
                if are_units_compatible(header_unit, field_unit):
                    try:
                        value = convert_value(value, header_unit, field_unit)
                    except Exception:
                        pass

        constraint_issue = self._check_constraints(f, header, value, raw_value, line_number)
        if constraint_issue is not None:
            return None, constraint_issue

        return value, None

    def _coerce_value(
        self,
        f: Field,
        header: str,
        raw_value: str,
        line_number: int,
    ) -> tuple[Any, ValidationIssue | None]:
        """Coerce a raw string value to the field's dtype."""
        display_value = raw_value[:80] if len(raw_value) > 80 else raw_value
        value = raw_value.strip()

        if self.thousands and f.dtype in (int, float):
            value = value.replace(self.thousands, "")

        if self.decimal != "." and f.dtype in (int, float):
            value = value.replace(self.decimal, ".")

        try:
            if f.dtype is int:
                if "." in value:
                    float_val = float(value)
                    if float_val != int(float_val):
                        raise ValueError("Not an integer")
                    return int(float_val), None
                return int(value), None

            elif f.dtype is float:
                return float(value), None

            elif f.dtype is bool:
                lower = value.lower()
                if lower in _BOOL_TRUE:
                    return True, None
                elif lower in _BOOL_FALSE:
                    return False, None
                raise ValueError(f"Not a valid boolean: {value}")

            else:
                return value, None

        except (ValueError, TypeError) as e:
            return None, ValidationIssue(
                code=ErrorCode.TYPE_ERROR,
                severity="error",
                message=f"line {line_number}, column {header!r}: value {display_value!r} is not a valid {f.dtype.__name__}",
                row=line_number,
                column=header,
                field_name=f.name,
                value=display_value,
                context={"dtype": f.dtype.__name__, "error": str(e)},
            )

    def _check_constraints(
        self,
        f: Field,
        header: str,
        value: Any,
        raw_value: str,
        line_number: int,
    ) -> ValidationIssue | None:
        """Check field constraints on a coerced value."""
        display_value = raw_value[:80] if len(raw_value) > 80 else raw_value

        if f.dtype in (int, float):
            unit_str = f.unit_string or ""
            unit_suffix = f" {unit_str}" if unit_str else ""

            if f.ge is not None and value < f.ge:
                return ValidationIssue(
                    code=ErrorCode.LESS_THAN_MINIMUM,
                    severity="error",
                    message=f"line {line_number}, column {header!r}: value {value} is less than minimum {f.ge}{unit_suffix}",
                    row=line_number,
                    column=header,
                    field_name=f.name,
                    value=display_value,
                    context={"ge": f.ge, "unit": unit_str} if unit_str else {"ge": f.ge},
                )

            if f.gt is not None and value <= f.gt:
                return ValidationIssue(
                    code=ErrorCode.LESS_THAN_MINIMUM,
                    severity="error",
                    message=f"line {line_number}, column {header!r}: value {value} is not greater than {f.gt}{unit_suffix}",
                    row=line_number,
                    column=header,
                    field_name=f.name,
                    value=display_value,
                    context={"gt": f.gt, "unit": unit_str} if unit_str else {"gt": f.gt},
                )

            if f.le is not None and value > f.le:
                return ValidationIssue(
                    code=ErrorCode.GREATER_THAN_MAXIMUM,
                    severity="error",
                    message=f"line {line_number}, column {header!r}: value {value} is greater than maximum {f.le}{unit_suffix}",
                    row=line_number,
                    column=header,
                    field_name=f.name,
                    value=display_value,
                    context={"le": f.le, "unit": unit_str} if unit_str else {"le": f.le},
                )

            if f.lt is not None and value >= f.lt:
                return ValidationIssue(
                    code=ErrorCode.GREATER_THAN_MAXIMUM,
                    severity="error",
                    message=f"line {line_number}, column {header!r}: value {value} is not less than {f.lt}{unit_suffix}",
                    row=line_number,
                    column=header,
                    field_name=f.name,
                    value=display_value,
                    context={"lt": f.lt, "unit": unit_str} if unit_str else {"lt": f.lt},
                )

        if f.enum is not None and value not in f.enum:
            return ValidationIssue(
                code=ErrorCode.NOT_IN_ENUM,
                severity="error",
                message=f"line {line_number}, column {header!r}: value {display_value!r} is not in allowed values",
                row=line_number,
                column=header,
                field_name=f.name,
                value=display_value,
                context={"enum": list(f.enum)},
            )

        if f.pattern is not None and f.dtype is str:
            if not re.fullmatch(f.pattern, value):
                return ValidationIssue(
                    code=ErrorCode.PATTERN_MISMATCH,
                    severity="error",
                    message=f"line {line_number}, column {header!r}: value {display_value!r} does not match pattern {f.pattern!r}",
                    row=line_number,
                    column=header,
                    field_name=f.name,
                    value=display_value,
                    context={"pattern": f.pattern},
                )

        for validator in f.validators:
            try:
                value = validator(value)
            except ValueError as e:
                validator_name = getattr(validator, "__name__", repr(validator))
                return ValidationIssue(
                    code=ErrorCode.CUSTOM_VALIDATOR,
                    severity="error",
                    message=f"line {line_number}, column {header!r}: custom validator {validator_name} rejected value: {e}",
                    row=line_number,
                    column=header,
                    field_name=f.name,
                    value=display_value,
                    context={"validator": validator_name, "error": str(e)},
                )

        return None

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
        row_values = [str(row_dict.get(h, "")) for h in headers]
        if not validator.validate_row(row_values, headers, line_number):
            break

    return validator.get_result()
