"""Tests for the schema inference module."""

import io
import tempfile

import pytest

from labschema.errors import ReadError
from labschema.infer import infer_schema, schema_to_python


class TestInferSchema:
    """Tests for infer_schema."""

    def test_infer_basic_types(self) -> None:
        csv_content = "name,age,active\nAlice,30,true\nBob,25,false"
        schema = infer_schema(io.StringIO(csv_content), name="test")

        assert schema.name == "test"
        assert len(schema.fields) == 3

        name_field = schema.get_field("name")
        assert name_field is not None
        assert name_field.dtype is str

        age_field = schema.get_field("age")
        assert age_field is not None
        assert age_field.dtype is int

        active_field = schema.get_field("active")
        assert active_field is not None
        assert active_field.dtype is bool

    def test_infer_float_type(self) -> None:
        csv_content = "value\n1.5\n2.5\n3.5"
        schema = infer_schema(io.StringIO(csv_content), name="test")

        value_field = schema.get_field("value")
        assert value_field is not None
        assert value_field.dtype is float

    def test_infer_nullable(self) -> None:
        csv_content = "value\n1\nNA\n3"
        schema = infer_schema(io.StringIO(csv_content), name="test")

        value_field = schema.get_field("value")
        assert value_field is not None
        assert value_field.nullable is True

    def test_infer_unit_from_header(self) -> None:
        csv_content = "temperature [°C]\n25.5\n30.0"
        schema = infer_schema(io.StringIO(csv_content), name="test")

        temp_field = schema.get_field("temperature")
        assert temp_field is not None
        assert temp_field.unit is not None

    def test_infer_alias_from_header(self) -> None:
        csv_content = "Temperature (°C)\n25.5\n30.0"
        schema = infer_schema(io.StringIO(csv_content), name="test")

        field = schema.get_field("temperature")
        assert field is not None
        assert len(field.aliases) > 0 or field.name == "temperature"

    def test_infer_metadata(self) -> None:
        csv_content = "a\n1\n2"
        schema = infer_schema(io.StringIO(csv_content), name="test")

        assert "inferred" in schema.metadata
        assert "sample_rows" in schema.metadata["inferred"]
        assert "labschema_version" in schema.metadata["inferred"]

    def test_infer_from_file(self) -> None:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            f.write("value\n1\n2\n3")
            f.flush()

            schema = infer_schema(f.name)
            assert schema.name is not None
            assert len(schema.fields) == 1

    def test_infer_description_with_range(self) -> None:
        csv_content = "value\n1\n2\n3\n4\n5"
        schema = infer_schema(io.StringIO(csv_content), name="test")

        value_field = schema.get_field("value")
        assert value_field is not None
        assert value_field.description is not None
        assert "range" in value_field.description.lower()

    def test_infer_empty_file_error(self) -> None:
        with pytest.raises(ReadError):
            infer_schema(io.StringIO(""), name="test")


class TestSchemaToPython:
    """Tests for schema_to_python."""

    def test_basic_schema(self) -> None:
        csv_content = "name,age\nAlice,30"
        schema = infer_schema(io.StringIO(csv_content), name="test")
        python_code = schema_to_python(schema)

        assert "from labschema import" in python_code
        assert "TableSchema(" in python_code
        assert "name='test'" in python_code or 'name="test"' in python_code
        assert "Field(" in python_code

    def test_schema_with_unit(self) -> None:
        csv_content = "temp [°C]\n25.5"
        schema = infer_schema(io.StringIO(csv_content), name="test")
        python_code = schema_to_python(schema)

        assert "unit=" in python_code

    def test_schema_with_nullable(self) -> None:
        csv_content = "value\n1\nNA"
        schema = infer_schema(io.StringIO(csv_content), name="test")
        python_code = schema_to_python(schema)

        assert "nullable=True" in python_code
