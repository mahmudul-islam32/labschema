"""Tests for schema export functionality."""

import json
import tempfile
from pathlib import Path

from labschema.fields import Field
from labschema.io.jsonschema import (
    export_json_schema,
    export_labschema_json,
    save_json_schema,
    save_labschema_json,
)
from labschema.schema import TableSchema


class TestExportLabSchemaJson:
    """Tests for LabSchema JSON export."""

    def test_export_basic(self) -> None:
        schema = TableSchema(
            name="test",
            fields=[Field("a", str), Field("b", int)],
        )
        json_str = export_labschema_json(schema)
        data = json.loads(json_str)

        assert data["labschema"] == "0.1"
        assert data["name"] == "test"
        assert len(data["fields"]) == 2

    def test_save_to_file(self) -> None:
        schema = TableSchema(
            name="test",
            fields=[Field("a", str)],
        )
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            save_labschema_json(schema, f.name)
            content = Path(f.name).read_text()

        data = json.loads(content)
        assert data["name"] == "test"

    def test_roundtrip(self) -> None:
        original = TableSchema(
            name="test",
            fields=[
                Field("a", str, nullable=True),
                Field("b", float, unit="degC", ge=-273.15),
            ],
            version="1.0",
            description="Test schema",
        )
        json_str = export_labschema_json(original)
        restored = TableSchema.from_json(json_str)

        assert restored.name == original.name
        assert restored.version == original.version
        assert restored.description == original.description
        assert len(restored.fields) == len(original.fields)


class TestExportJsonSchema:
    """Tests for JSON Schema export."""

    def test_export_basic(self) -> None:
        schema = TableSchema(
            name="test",
            fields=[Field("a", str), Field("b", int)],
        )
        json_str = export_json_schema(schema)
        data = json.loads(json_str)

        assert data["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        assert data["title"] == "test"
        assert "a" in data["properties"]
        assert "b" in data["properties"]

    def test_export_types(self) -> None:
        schema = TableSchema(
            name="test",
            fields=[
                Field("s", str),
                Field("i", int),
                Field("f", float),
                Field("b", bool),
            ],
        )
        json_str = export_json_schema(schema)
        data = json.loads(json_str)

        assert data["properties"]["s"]["type"] == "string"
        assert data["properties"]["i"]["type"] == "integer"
        assert data["properties"]["f"]["type"] == "number"
        assert data["properties"]["b"]["type"] == "boolean"

    def test_export_nullable(self) -> None:
        schema = TableSchema(
            name="test",
            fields=[Field("a", int, nullable=True)],
        )
        json_str = export_json_schema(schema)
        data = json.loads(json_str)

        assert data["properties"]["a"]["type"] == ["integer", "null"]

    def test_export_constraints(self) -> None:
        schema = TableSchema(
            name="test",
            fields=[Field("value", float, ge=0, lt=100)],
        )
        json_str = export_json_schema(schema)
        data = json.loads(json_str)

        prop = data["properties"]["value"]
        assert prop["minimum"] == 0
        assert prop["exclusiveMaximum"] == 100

    def test_export_enum(self) -> None:
        schema = TableSchema(
            name="test",
            fields=[Field("status", str, enum=["active", "inactive"])],
        )
        json_str = export_json_schema(schema)
        data = json.loads(json_str)

        assert data["properties"]["status"]["enum"] == ["active", "inactive"]

    def test_export_pattern(self) -> None:
        schema = TableSchema(
            name="test",
            fields=[Field("code", str, pattern=r"^[A-Z]{3}$")],
        )
        json_str = export_json_schema(schema)
        data = json.loads(json_str)

        assert data["properties"]["code"]["pattern"] == r"^[A-Z]{3}$"

    def test_export_unit(self) -> None:
        schema = TableSchema(
            name="test",
            fields=[Field("temp", float, unit="degC")],
        )
        json_str = export_json_schema(schema)
        data = json.loads(json_str)

        assert "x-unit" in data["properties"]["temp"]

    def test_export_required(self) -> None:
        schema = TableSchema(
            name="test",
            fields=[
                Field("required", str),
                Field("optional", str, nullable=True),
                Field("with_default", str, default="default"),
            ],
        )
        json_str = export_json_schema(schema)
        data = json.loads(json_str)

        assert "required" in data["required"]
        assert "optional" not in data["required"]
        assert "with_default" not in data["required"]

    def test_export_primary_key(self) -> None:
        schema = TableSchema(
            name="test",
            fields=[Field("id", int), Field("name", str)],
            primary_key=("id",),
        )
        json_str = export_json_schema(schema)
        data = json.loads(json_str)

        assert data["x-primary-key"] == ["id"]

    def test_save_to_file(self) -> None:
        schema = TableSchema(
            name="test",
            fields=[Field("a", str)],
        )
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            save_json_schema(schema, f.name)
            content = Path(f.name).read_text()

        data = json.loads(content)
        assert data["title"] == "test"
