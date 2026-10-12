"""Tests for the schema module."""

import pytest

from labschema.errors import SchemaError
from labschema.fields import Field
from labschema.schema import TableSchema, normalize_name


class TestNormalizeName:
    """Tests for normalize_name."""

    def test_lowercase(self) -> None:
        assert normalize_name("Temperature") == "temperature"

    def test_special_chars_to_underscore(self) -> None:
        assert normalize_name("Conc. [mg/L]") == "conc_mg_l"

    def test_trim_underscores(self) -> None:
        assert normalize_name("_name_") == "name"

    def test_unicode_normalization(self) -> None:
        assert normalize_name("Temp (°C)") == "temp_c"


class TestTableSchemaConstruction:
    """Tests for TableSchema construction."""

    def test_basic_schema(self) -> None:
        schema = TableSchema(
            name="test",
            fields=[Field("name", str)],
        )
        assert schema.name == "test"
        assert len(schema.fields) == 1

    def test_schema_with_primary_key(self) -> None:
        schema = TableSchema(
            name="test",
            fields=[Field("id", int), Field("name", str)],
            primary_key=("id",),
        )
        assert schema.primary_key == ("id",)

    def test_schema_with_extra_columns_policy(self) -> None:
        schema = TableSchema(
            name="test",
            fields=[Field("name", str)],
            extra_columns="error",
        )
        assert schema.extra_columns == "error"


class TestTableSchemaValidation:
    """Tests for TableSchema construction-time validation."""

    def test_empty_name(self) -> None:
        with pytest.raises(SchemaError, match="name is required"):
            TableSchema(name="", fields=[Field("a", str)])

    def test_empty_fields(self) -> None:
        with pytest.raises(SchemaError, match="at least one field"):
            TableSchema(name="test", fields=[])

    def test_duplicate_field_names(self) -> None:
        with pytest.raises(SchemaError, match="Duplicate field name"):
            TableSchema(
                name="test",
                fields=[Field("a", str), Field("a", int)],
            )

    def test_primary_key_field_not_found(self) -> None:
        with pytest.raises(SchemaError, match="does not exist"):
            TableSchema(
                name="test",
                fields=[Field("a", str)],
                primary_key=("b",),
            )

    def test_nullable_primary_key_field(self) -> None:
        with pytest.raises(SchemaError, match="cannot be nullable"):
            TableSchema(
                name="test",
                fields=[Field("id", int, nullable=True)],
                primary_key=("id",),
            )

    def test_conflicting_aliases(self) -> None:
        with pytest.raises(SchemaError, match="Duplicate alias|conflicts"):
            TableSchema(
                name="test",
                fields=[
                    Field("a", str, aliases=("x",)),
                    Field("b", str, aliases=("x",)),
                ],
            )


class TestTableSchemaHelpers:
    """Tests for TableSchema helper methods."""

    def test_get_field(self) -> None:
        schema = TableSchema(
            name="test",
            fields=[Field("a", str), Field("b", int)],
        )
        assert schema.get_field("a") is not None
        assert schema.get_field("a").name == "a"
        assert schema.get_field("c") is None

    def test_match_header(self) -> None:
        schema = TableSchema(
            name="test",
            fields=[
                Field("temperature", float, aliases=("temp",)),
            ],
        )
        assert schema.match_header("temperature") is not None
        assert schema.match_header("Temperature") is not None
        assert schema.match_header("temp") is not None
        assert schema.match_header("unknown") is None

    def test_field_names(self) -> None:
        schema = TableSchema(
            name="test",
            fields=[Field("a", str), Field("b", int)],
        )
        assert schema.field_names == ("a", "b")

    def test_with_field(self) -> None:
        schema = TableSchema(
            name="test",
            fields=[Field("a", str)],
        )
        new_schema = schema.with_field(Field("b", int))
        assert len(new_schema.fields) == 2
        assert new_schema.fields[1].name == "b"

    def test_without_field(self) -> None:
        schema = TableSchema(
            name="test",
            fields=[Field("a", str), Field("b", int)],
        )
        new_schema = schema.without_field("b")
        assert len(new_schema.fields) == 1
        assert new_schema.fields[0].name == "a"

    def test_replace_field(self) -> None:
        schema = TableSchema(
            name="test",
            fields=[Field("a", str), Field("b", int)],
        )
        new_schema = schema.replace_field("b", Field("b", float))
        assert new_schema.get_field("b").dtype is float


class TestTableSchemaSerialization:
    """Tests for TableSchema serialization."""

    def test_to_dict(self) -> None:
        schema = TableSchema(
            name="test",
            fields=[Field("a", str)],
        )
        d = schema.to_dict()
        assert d["labschema"] == "0.1"
        assert d["name"] == "test"
        assert len(d["fields"]) == 1

    def test_to_json(self) -> None:
        schema = TableSchema(
            name="test",
            fields=[Field("a", str)],
        )
        json_str = schema.to_json()
        assert '"labschema": "0.1"' in json_str
        assert '"name": "test"' in json_str

    def test_from_dict(self) -> None:
        d = {
            "labschema": "0.1",
            "name": "test",
            "fields": [{"name": "a", "dtype": "str"}],
        }
        schema = TableSchema.from_dict(d)
        assert schema.name == "test"
        assert len(schema.fields) == 1

    def test_from_json(self) -> None:
        json_str = '{"labschema": "0.1", "name": "test", "fields": [{"name": "a", "dtype": "str"}]}'
        schema = TableSchema.from_json(json_str)
        assert schema.name == "test"

    def test_roundtrip(self) -> None:
        original = TableSchema(
            name="test",
            fields=[
                Field("a", str, nullable=True),
                Field("b", float, unit="degC", ge=-273.15),
            ],
            primary_key=(),
            description="Test schema",
            version="1.0",
        )
        restored = TableSchema.from_json(original.to_json())
        assert restored.name == original.name
        assert len(restored.fields) == len(original.fields)
        assert restored.description == original.description
        assert restored.version == original.version


class TestTableSchemaJsonSchema:
    """Tests for JSON Schema export."""

    def test_to_json_schema_basic(self) -> None:
        schema = TableSchema(
            name="test",
            fields=[Field("name", str)],
        )
        js = schema.to_json_schema()
        assert js["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        assert js["title"] == "test"
        assert "name" in js["properties"]
        assert js["properties"]["name"]["type"] == "string"

    def test_to_json_schema_nullable(self) -> None:
        schema = TableSchema(
            name="test",
            fields=[Field("value", int, nullable=True)],
        )
        js = schema.to_json_schema()
        assert js["properties"]["value"]["type"] == ["integer", "null"]

    def test_to_json_schema_constraints(self) -> None:
        schema = TableSchema(
            name="test",
            fields=[Field("value", float, ge=0, lt=100)],
        )
        js = schema.to_json_schema()
        prop = js["properties"]["value"]
        assert prop["minimum"] == 0
        assert prop["exclusiveMaximum"] == 100

    def test_to_json_schema_unit(self) -> None:
        schema = TableSchema(
            name="test",
            fields=[Field("temp", float, unit="degC")],
        )
        js = schema.to_json_schema()
        assert "x-unit" in js["properties"]["temp"]

    def test_to_json_schema_required(self) -> None:
        schema = TableSchema(
            name="test",
            fields=[
                Field("required_field", str),
                Field("optional_field", str, nullable=True),
            ],
        )
        js = schema.to_json_schema()
        assert "required_field" in js["required"]
        assert "optional_field" not in js["required"]
