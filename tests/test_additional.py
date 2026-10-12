"""Additional tests to increase coverage."""

import io
import json
from pathlib import Path

import pytest

from labschema import Field, TableSchema, ValidationIssue, infer_schema
from labschema.errors import ErrorCode, ReadError, SchemaError
from labschema.fields import _UNSET
from labschema.infer import schema_to_python
from labschema.io import read_csv, read_text
from labschema.schema import normalize_name
from labschema.units import get_unit_string, set_registry
from labschema.validate import ValidationReport


class TestValidationReportPrintSummary:
    """Tests for ValidationReport.print_summary."""

    def test_print_summary_with_issues(self) -> None:
        report = ValidationReport()
        report.issues.append(
            ValidationIssue(
                code=ErrorCode.TYPE_ERROR,
                severity="error",
                message="test error 1",
            )
        )
        report.issues.append(
            ValidationIssue(
                code=ErrorCode.TYPE_ERROR,
                severity="error",
                message="test error 2",
            )
        )
        output = io.StringIO()
        report.print_summary(file=output, limit=1)
        content = output.getvalue()
        assert "type_error" in content
        assert "… and 1 more" in content

    def test_print_summary_truncated(self) -> None:
        report = ValidationReport()
        report.truncated = True
        output = io.StringIO()
        report.print_summary(file=output)
        content = output.getvalue()
        assert "truncated" in content


class TestTableSchemaEdgeCases:
    """Edge case tests for TableSchema."""

    def test_without_field_not_found(self) -> None:
        schema = TableSchema(
            name="test",
            fields=[Field("a", str)],
        )
        with pytest.raises(SchemaError, match="not found"):
            schema.without_field("b")

    def test_without_field_in_primary_key(self) -> None:
        schema = TableSchema(
            name="test",
            fields=[Field("id", int), Field("name", str)],
            primary_key=("id",),
        )
        with pytest.raises(SchemaError, match="primary key"):
            schema.without_field("id")

    def test_replace_field_not_found(self) -> None:
        schema = TableSchema(
            name="test",
            fields=[Field("a", str)],
        )
        with pytest.raises(SchemaError, match="not found"):
            schema.replace_field("b", Field("b", int))

    def test_replace_field_in_primary_key(self) -> None:
        schema = TableSchema(
            name="test",
            fields=[Field("id", int), Field("name", str)],
            primary_key=("id",),
        )
        new_schema = schema.replace_field("id", Field("new_id", int))
        assert "new_id" in new_schema.primary_key

    def test_to_base_units(self) -> None:
        schema = TableSchema(
            name="test",
            fields=[
                Field("temp", float, unit="degC"),
                Field("name", str),
            ],
        )
        base_schema = schema.to_base_units()
        assert base_schema.get_field("temp") is not None

    def test_save_and_load(self, tmp_path: Path) -> None:
        schema = TableSchema(
            name="test",
            fields=[Field("a", str)],
        )
        path = tmp_path / "schema.json"
        schema.save(path)
        loaded = TableSchema.load(path)
        assert loaded.name == schema.name

    def test_load_nonexistent_file(self) -> None:
        with pytest.raises(ReadError):
            TableSchema.load("nonexistent.json")

    def test_from_json_invalid(self) -> None:
        with pytest.raises(SchemaError, match="Invalid JSON"):
            TableSchema.from_json("{invalid json")

    def test_from_dict_missing_name(self) -> None:
        with pytest.raises(SchemaError, match="name"):
            TableSchema.from_dict({"fields": [{"name": "a", "dtype": "str"}]})

    def test_from_dict_missing_fields(self) -> None:
        with pytest.raises(SchemaError, match="fields"):
            TableSchema.from_dict({"name": "test"})

    def test_from_dict_unsupported_version(self) -> None:
        with pytest.raises(SchemaError, match="Unsupported"):
            TableSchema.from_dict({"labschema": "1.0", "name": "test", "fields": []})


class TestFieldEdgeCases:
    """Edge case tests for Field."""

    def test_unset_type(self) -> None:
        assert repr(_UNSET) == "<UNSET>"
        assert not _UNSET

    def test_field_unit_string(self) -> None:
        f = Field("temp", float, unit="degC")
        assert f.unit_string is not None

    def test_field_from_dict_with_validators_warning(self) -> None:
        with pytest.warns(UserWarning, match="validators"):
            Field.from_dict(
                {
                    "name": "a",
                    "dtype": "int",
                    "validators": ["some_validator"],
                }
            )


class TestCsvEdgeCases:
    """Edge case tests for CSV reading."""

    def test_read_csv_with_bom(self, tmp_path: Path) -> None:
        schema = TableSchema(
            name="test",
            fields=[Field("a", int)],
        )
        csv_file = tmp_path / "data.csv"
        csv_file.write_bytes(b"\xef\xbb\xbfa\n1\n2")
        result = read_csv(csv_file, schema)
        assert result.ok

    def test_read_text_semicolon_delimiter(self) -> None:
        schema = TableSchema(
            name="test",
            fields=[Field("a", int), Field("b", int)],
        )
        result = read_text("a;b\n1;2", schema, delimiter=";")
        assert result.ok

    def test_duplicate_column_error(self) -> None:
        schema = TableSchema(
            name="test",
            fields=[Field("a", int)],
        )
        result = read_text("a,a\n1,2", schema)
        assert not result.ok
        assert any(e.code == ErrorCode.DUPLICATE_COLUMN for e in result.errors)

    def test_unit_incompatible(self) -> None:
        schema = TableSchema(
            name="test",
            fields=[Field("temp", float, unit="degC")],
        )
        result = read_text("temp [mg/L]\n25", schema)
        assert not result.ok
        assert any(e.code == ErrorCode.UNIT_INCOMPATIBLE for e in result.errors)

    def test_ambiguous_unit_warning(self) -> None:
        schema = TableSchema(
            name="test",
            fields=[Field("temp", float, unit="degC")],
        )
        result = read_text("temp (C)\n25", schema)
        assert any(w.code == ErrorCode.UNIT_AMBIGUOUS for w in result.report.warnings)

    def test_unit_unexpected_warning(self) -> None:
        schema = TableSchema(
            name="test",
            fields=[Field("value", float)],  # No unit declared
        )
        result = read_text("value [mg/L]\n25", schema)
        assert any(w.code == ErrorCode.UNIT_UNEXPECTED for w in result.report.warnings)

    def test_missing_nullable_column_warning(self) -> None:
        schema = TableSchema(
            name="test",
            fields=[Field("a", int), Field("b", int, nullable=True)],
        )
        result = read_text("a\n1", schema)
        assert result.ok
        assert any(w.code == ErrorCode.MISSING_COLUMN for w in result.report.warnings)


class TestInferEdgeCases:
    """Edge case tests for schema inference."""

    def test_infer_all_missing_column(self) -> None:
        schema = infer_schema(io.StringIO("a\nNA\nNA"), name="test")
        field = schema.get_field("a")
        assert field is not None
        assert field.nullable

    def test_infer_distinct_values_hint(self) -> None:
        data = "status\n" + "\n".join(["active"] * 15 + ["inactive"] * 15)
        schema = infer_schema(io.StringIO(data), name="test")
        field = schema.get_field("status")
        assert field is not None
        assert field.description is not None
        assert "distinct values" in field.description

    def test_schema_to_python_with_constraints(self) -> None:
        schema = TableSchema(
            name="test",
            primary_key=("id",),
            extra_columns="error",
            version="1.0",
            description="Test schema",
            fields=[
                Field("id", int, ge=0, lt=100, description="The ID field"),
                Field("status", str, enum=["a", "b"], pattern=r"^[a-z]$"),
                Field("temp", float, unit="degC", aliases=("temperature",)),
            ],
        )
        code = schema_to_python(schema)
        assert "primary_key=" in code
        assert "extra_columns='error'" in code
        assert "version='1.0'" in code
        assert "ge=0" in code
        assert "lt=100" in code
        assert "enum=" in code
        assert "pattern=" in code
        assert "aliases=" in code


class TestUnitsEdgeCases:
    """Edge case tests for units module."""

    def test_get_unit_string_none(self) -> None:
        assert get_unit_string(None) is None

    def test_set_registry_already_set(self) -> None:
        from labschema.units import get_registry

        get_registry()  # Initialize the registry
        with pytest.raises(SchemaError, match="Cannot change registry"):
            import pint

            set_registry(pint.UnitRegistry())


class TestNormalizeName:
    """Additional tests for normalize_name."""

    def test_empty_after_normalization(self) -> None:
        result = normalize_name("___")
        assert result == ""

    def test_unicode_chars(self) -> None:
        result = normalize_name("café")
        # NFKC normalization keeps the é, and it gets converted to underscore
        assert "caf" in result


class TestCsvParseError:
    """Tests for CSV parse errors."""

    def test_thousands_same_as_decimal(self) -> None:
        schema = TableSchema(
            name="test",
            fields=[Field("a", int)],
        )
        with pytest.raises(ReadError, match="thousands separator"):
            read_text("a\n1", schema, decimal=",", thousands=",")


class TestValidationReportToJson:
    """Tests for ValidationReport.to_json."""

    def test_to_json(self) -> None:
        from labschema.errors import ValidationIssue

        report = ValidationReport()
        report.issues.append(
            ValidationIssue(
                code=ErrorCode.TYPE_ERROR,
                severity="error",
                message="test",
                row=1,
                column="a",
                field_name="a",
                value="x",
                context={"key": "value"},
            )
        )
        json_str = report.to_json()
        data = json.loads(json_str)
        assert data["error_count"] == 1
        assert len(data["issues"]) == 1
        assert data["issues"][0]["row"] == 1


class TestValidationIssueToDict:
    """Tests for ValidationIssue.to_dict."""

    def test_to_dict_all_fields(self) -> None:
        issue = ValidationIssue(
            code=ErrorCode.TYPE_ERROR,
            severity="error",
            message="test",
            row=1,
            column="col",
            field_name="field",
            value="val",
            context={"k": "v"},
        )
        d = issue.to_dict()
        assert d["code"] == "type_error"
        assert d["row"] == 1
        assert d["column"] == "col"
        assert d["field"] == "field"
        assert d["value"] == "val"
        assert d["context"] == {"k": "v"}
