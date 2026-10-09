"""Tests for the validation module."""

import pytest

from labschema.errors import ErrorCode
from labschema.fields import Field
from labschema.schema import TableSchema
from labschema.validate import ValidationReport, ValidationResult, validate_rows


class TestValidationReport:
    """Tests for ValidationReport."""

    def test_errors_and_warnings(self) -> None:
        from labschema.errors import ValidationIssue

        report = ValidationReport()
        report.issues.append(
            ValidationIssue(
                code=ErrorCode.TYPE_ERROR,
                severity="error",
                message="Error 1",
            )
        )
        report.issues.append(
            ValidationIssue(
                code=ErrorCode.UNIT_UNEXPECTED,
                severity="warning",
                message="Warning 1",
            )
        )

        assert len(report.errors) == 1
        assert len(report.warnings) == 1

    def test_by_code(self) -> None:
        from labschema.errors import ValidationIssue

        report = ValidationReport()
        report.issues.append(
            ValidationIssue(code=ErrorCode.TYPE_ERROR, severity="error", message="E1")
        )
        report.issues.append(
            ValidationIssue(code=ErrorCode.TYPE_ERROR, severity="error", message="E2")
        )
        report.issues.append(
            ValidationIssue(code=ErrorCode.NULL_NOT_ALLOWED, severity="error", message="E3")
        )

        by_code = report.by_code()
        assert len(by_code[ErrorCode.TYPE_ERROR]) == 2
        assert len(by_code[ErrorCode.NULL_NOT_ALLOWED]) == 1

    def test_to_dict(self) -> None:
        from labschema.errors import ValidationIssue

        report = ValidationReport()
        report.issues.append(
            ValidationIssue(code=ErrorCode.TYPE_ERROR, severity="error", message="E1")
        )
        d = report.to_dict()
        assert d["error_count"] == 1
        assert d["warning_count"] == 0
        assert len(d["issues"]) == 1


class TestValidationResult:
    """Tests for ValidationResult."""

    def test_ok_with_no_errors(self) -> None:
        result = ValidationResult(
            report=ValidationReport(),
            records=[{"a": 1}],
            column_units={},
        )
        assert result.ok is True

    def test_not_ok_with_errors(self) -> None:
        from labschema.errors import ValidationIssue

        report = ValidationReport()
        report.issues.append(
            ValidationIssue(code=ErrorCode.TYPE_ERROR, severity="error", message="E1")
        )
        result = ValidationResult(
            report=report,
            records=[],
            column_units={},
        )
        assert result.ok is False

    def test_to_records(self) -> None:
        result = ValidationResult(
            report=ValidationReport(),
            records=[{"a": 1}, {"a": 2}],
            column_units={},
        )
        assert result.to_records() == [{"a": 1}, {"a": 2}]


class TestValidateRows:
    """Tests for validate_rows function."""

    def test_valid_rows(self) -> None:
        schema = TableSchema(
            name="test",
            fields=[Field("a", int), Field("b", str)],
        )
        rows = [
            {"a": "1", "b": "hello"},
            {"a": "2", "b": "world"},
        ]
        result = validate_rows(rows, schema)
        assert result.ok
        assert len(result.records) == 2
        assert result.records[0]["a"] == 1

    def test_type_error(self) -> None:
        schema = TableSchema(
            name="test",
            fields=[Field("a", int)],
        )
        rows = [{"a": "not_a_number"}]
        result = validate_rows(rows, schema)
        assert not result.ok
        assert len(result.errors) == 1
        assert result.errors[0].code == ErrorCode.TYPE_ERROR

    def test_null_not_allowed(self) -> None:
        schema = TableSchema(
            name="test",
            fields=[Field("a", int, nullable=False)],
        )
        rows = [{"a": ""}]
        result = validate_rows(rows, schema)
        assert not result.ok
        assert result.errors[0].code == ErrorCode.NULL_NOT_ALLOWED

    def test_nullable_field(self) -> None:
        schema = TableSchema(
            name="test",
            fields=[Field("a", int, nullable=True)],
        )
        rows = [{"a": "NA"}]
        result = validate_rows(rows, schema)
        assert result.ok
        assert result.records[0]["a"] is None

    def test_default_value(self) -> None:
        schema = TableSchema(
            name="test",
            fields=[Field("a", int, default=0)],
        )
        rows = [{"a": ""}]
        result = validate_rows(rows, schema)
        assert result.ok
        assert result.records[0]["a"] == 0

    def test_bounds_constraint_ge(self) -> None:
        schema = TableSchema(
            name="test",
            fields=[Field("a", float, ge=0)],
        )
        rows = [{"a": "-1"}]
        result = validate_rows(rows, schema)
        assert not result.ok
        assert result.errors[0].code == ErrorCode.LESS_THAN_MINIMUM

    def test_bounds_constraint_le(self) -> None:
        schema = TableSchema(
            name="test",
            fields=[Field("a", float, le=100)],
        )
        rows = [{"a": "150"}]
        result = validate_rows(rows, schema)
        assert not result.ok
        assert result.errors[0].code == ErrorCode.GREATER_THAN_MAXIMUM

    def test_enum_constraint(self) -> None:
        schema = TableSchema(
            name="test",
            fields=[Field("a", str, enum=["x", "y"])],
        )
        rows = [{"a": "z"}]
        result = validate_rows(rows, schema)
        assert not result.ok
        assert result.errors[0].code == ErrorCode.NOT_IN_ENUM

    def test_pattern_constraint(self) -> None:
        schema = TableSchema(
            name="test",
            fields=[Field("a", str, pattern=r"^[A-Z]+$")],
        )
        rows = [{"a": "abc"}]
        result = validate_rows(rows, schema)
        assert not result.ok
        assert result.errors[0].code == ErrorCode.PATTERN_MISMATCH

    def test_bool_coercion(self) -> None:
        schema = TableSchema(
            name="test",
            fields=[Field("a", bool)],
        )
        rows = [
            {"a": "true"},
            {"a": "yes"},
            {"a": "1"},
            {"a": "false"},
            {"a": "no"},
            {"a": "0"},
        ]
        result = validate_rows(rows, schema)
        assert result.ok
        assert result.records[0]["a"] is True
        assert result.records[3]["a"] is False

    def test_primary_key_duplicate(self) -> None:
        schema = TableSchema(
            name="test",
            fields=[Field("id", int), Field("name", str)],
            primary_key=("id",),
        )
        rows = [
            {"id": "1", "name": "a"},
            {"id": "1", "name": "b"},
        ]
        result = validate_rows(rows, schema)
        assert not result.ok
        assert any(e.code == ErrorCode.DUPLICATE_PRIMARY_KEY for e in result.errors)

    def test_custom_validator(self) -> None:
        def must_be_positive(value: int) -> int:
            if value <= 0:
                raise ValueError("Must be positive")
            return value

        schema = TableSchema(
            name="test",
            fields=[Field("a", int, validators=[must_be_positive])],
        )
        rows = [{"a": "-5"}]
        result = validate_rows(rows, schema)
        assert not result.ok
        assert result.errors[0].code == ErrorCode.CUSTOM_VALIDATOR

    def test_max_errors(self) -> None:
        schema = TableSchema(
            name="test",
            fields=[Field("a", int)],
        )
        rows = [{"a": "invalid"} for _ in range(100)]
        result = validate_rows(rows, schema, max_errors=5)
        assert len(result.errors) <= 5
        assert result.report.truncated

    def test_gt_constraint(self) -> None:
        schema = TableSchema(
            name="test",
            fields=[Field("a", float, gt=0)],
        )
        rows = [{"a": "0"}]
        result = validate_rows(rows, schema)
        assert not result.ok
        assert result.errors[0].code == ErrorCode.LESS_THAN_MINIMUM

    def test_lt_constraint(self) -> None:
        schema = TableSchema(
            name="test",
            fields=[Field("a", float, lt=100)],
        )
        rows = [{"a": "100"}]
        result = validate_rows(rows, schema)
        assert not result.ok
        assert result.errors[0].code == ErrorCode.GREATER_THAN_MAXIMUM

    def test_float_coercion(self) -> None:
        schema = TableSchema(
            name="test",
            fields=[Field("a", float)],
        )
        rows = [{"a": "1.5e-3"}, {"a": "inf"}]
        result = validate_rows(rows, schema)
        assert result.ok
        assert result.records[0]["a"] == pytest.approx(0.0015)

    def test_int_from_float_string(self) -> None:
        schema = TableSchema(
            name="test",
            fields=[Field("a", int)],
        )
        rows = [{"a": "3.0"}]
        result = validate_rows(rows, schema)
        assert result.ok
        assert result.records[0]["a"] == 3

    def test_int_from_non_integral_float_fails(self) -> None:
        schema = TableSchema(
            name="test",
            fields=[Field("a", int)],
        )
        rows = [{"a": "3.5"}]
        result = validate_rows(rows, schema)
        assert not result.ok
        assert result.errors[0].code == ErrorCode.TYPE_ERROR
