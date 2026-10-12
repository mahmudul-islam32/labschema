"""Error codes, validation issues, and exceptions for LabSchema."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ErrorCode(str, Enum):
    """Stable machine-readable error codes for validation issues.

    These codes are part of the public API and will not change meaning
    within a major version.
    """

    MISSING_COLUMN = "missing_column"
    EXTRA_COLUMN = "extra_column"
    DUPLICATE_COLUMN = "duplicate_column"
    UNIT_UNKNOWN = "unit_unknown"
    UNIT_INCOMPATIBLE = "unit_incompatible"
    UNIT_UNEXPECTED = "unit_unexpected"
    UNIT_AMBIGUOUS = "unit_ambiguous"
    ROW_LENGTH_MISMATCH = "row_length_mismatch"
    NULL_NOT_ALLOWED = "null_not_allowed"
    TYPE_ERROR = "type_error"
    LESS_THAN_MINIMUM = "less_than_minimum"
    GREATER_THAN_MAXIMUM = "greater_than_maximum"
    NOT_IN_ENUM = "not_in_enum"
    PATTERN_MISMATCH = "pattern_mismatch"
    CUSTOM_VALIDATOR = "custom_validator"
    DUPLICATE_PRIMARY_KEY = "duplicate_primary_key"
    PARSE_ERROR = "parse_error"


@dataclass(frozen=True)
class ValidationIssue:
    """A single validation issue found during validation.

    Attributes:
        code: Stable machine-readable error code.
        severity: 'error' or 'warning'. Only errors make a result invalid.
        message: Human-readable description of the issue.
        row: 1-based file line number (header is line 1). None for file-level issues.
        column: Raw header text as it appears in the file. None for row-level issues.
        field_name: Schema field name. None if the issue isn't field-specific.
            ``field`` is the public alias of this attribute.
        value: Raw cell text (truncated to 80 chars). None if not applicable.
        context: Code-specific details (e.g., {'ge': 0, 'unit': 'mg/L'}).
    """

    code: ErrorCode
    severity: str
    message: str
    row: int | None = None
    column: str | None = None
    field_name: str | None = None
    value: str | None = None
    context: dict[str, Any] = field(default_factory=dict)

    @property
    def field(self) -> str | None:
        """Schema field name. Public alias of ``field_name``."""
        return self.field_name

    def to_dict(self) -> dict[str, Any]:
        """Convert the issue to a dictionary for JSON serialization."""
        result: dict[str, Any] = {
            "code": self.code.value,
            "severity": self.severity,
            "message": self.message,
        }
        if self.row is not None:
            result["row"] = self.row
        if self.column is not None:
            result["column"] = self.column
        if self.field_name is not None:
            result["field"] = self.field_name
        if self.value is not None:
            result["value"] = self.value
        if self.context:
            result["context"] = self.context
        return result


class LabSchemaError(Exception):
    """Base exception for all LabSchema errors."""

    pass


class SchemaError(LabSchemaError):
    """Exception raised for invalid schema definitions.

    This is raised at construction or load time, not during validation.
    """

    pass


class ReadError(LabSchemaError):
    """Exception raised when a file cannot be read.

    This includes encoding failures, empty files, and other I/O errors.
    """

    pass
