"""Tests for the CSV I/O module."""

import io
import tempfile

import pytest

from labschema.errors import ErrorCode, ReadError
from labschema.fields import Field
from labschema.io.csv import read_csv, read_text, read_tsv
from labschema.schema import TableSchema


class TestReadCsv:
    """Tests for read_csv."""

    def test_simple_csv(self) -> None:
        schema = TableSchema(
            name="test",
            fields=[Field("a", int), Field("b", str)],
        )
        csv_content = "a,b\n1,hello\n2,world"
        result = read_text(csv_content, schema)
        assert result.ok
        assert len(result.records) == 2
        assert result.records[0]["a"] == 1
        assert result.records[0]["b"] == "hello"

    def test_csv_with_header_units(self) -> None:
        schema = TableSchema(
            name="test",
            fields=[Field("temp", float, unit="degC")],
        )
        csv_content = "temp (°C)\n25.5\n30.0"
        result = read_text(csv_content, schema)
        assert result.ok
        assert result.records[0]["temp"] == 25.5
        assert "temp" in result.column_units

    def test_csv_with_unit_conversion(self) -> None:
        schema = TableSchema(
            name="test",
            fields=[Field("volume", float, unit="L")],
        )
        csv_content = "volume [mL]\n1000\n2000"
        result = read_text(csv_content, schema)
        assert result.ok
        assert result.records[0]["volume"] == pytest.approx(1.0)
        assert result.records[1]["volume"] == pytest.approx(2.0)

    def test_csv_with_missing_values(self) -> None:
        schema = TableSchema(
            name="test",
            fields=[Field("a", int, nullable=True)],
        )
        csv_content = "a\n1\nNA\n3"
        result = read_text(csv_content, schema)
        assert result.ok
        assert result.records[1]["a"] is None

    def test_csv_with_decimal_comma(self) -> None:
        schema = TableSchema(
            name="test",
            fields=[Field("value", float)],
        )
        csv_content = "value\n1,5\n2,5"
        result = read_text(csv_content, schema, delimiter=";", decimal=",")
        assert result.ok
        assert result.records[0]["value"] == 1.5

    def test_csv_with_thousands_separator(self) -> None:
        schema = TableSchema(
            name="test",
            fields=[Field("value", int)],
        )
        csv_content = "value\n1 000\n2 000"
        result = read_text(csv_content, schema, thousands=" ")
        assert result.ok
        assert result.records[0]["value"] == 1000

    def test_csv_skip_rows(self) -> None:
        schema = TableSchema(
            name="test",
            fields=[Field("a", int)],
        )
        csv_content = "# Header comment\n# Another comment\na\n1\n2"
        result = read_text(csv_content, schema, skip_rows=2)
        assert result.ok
        assert len(result.records) == 2

    def test_csv_comment_lines(self) -> None:
        schema = TableSchema(
            name="test",
            fields=[Field("a", int)],
        )
        csv_content = "a\n1\n# comment\n2"
        result = read_text(csv_content, schema, comment="#")
        assert result.ok
        assert len(result.records) == 2

    def test_csv_extra_columns_warn(self) -> None:
        schema = TableSchema(
            name="test",
            fields=[Field("a", int)],
            extra_columns="warn",
        )
        csv_content = "a,b\n1,extra"
        result = read_text(csv_content, schema)
        assert result.ok
        assert any(w.code == ErrorCode.EXTRA_COLUMN for w in result.report.warnings)

    def test_csv_extra_columns_error(self) -> None:
        schema = TableSchema(
            name="test",
            fields=[Field("a", int)],
            extra_columns="error",
        )
        csv_content = "a,b\n1,extra"
        result = read_text(csv_content, schema)
        assert not result.ok
        assert any(e.code == ErrorCode.EXTRA_COLUMN for e in result.errors)

    def test_csv_extra_columns_ignore(self) -> None:
        schema = TableSchema(
            name="test",
            fields=[Field("a", int)],
            extra_columns="ignore",
        )
        csv_content = "a,b\n1,extra"
        result = read_text(csv_content, schema)
        assert result.ok
        assert len(result.report.issues) == 0

    def test_csv_missing_column(self) -> None:
        schema = TableSchema(
            name="test",
            fields=[Field("a", int), Field("b", str)],
        )
        csv_content = "a\n1"
        result = read_text(csv_content, schema)
        assert not result.ok
        assert any(e.code == ErrorCode.MISSING_COLUMN for e in result.errors)

    def test_csv_row_length_mismatch(self) -> None:
        schema = TableSchema(
            name="test",
            fields=[Field("a", int), Field("b", str)],
        )
        csv_content = "a,b\n1"
        result = read_text(csv_content, schema)
        assert not result.ok
        assert any(e.code == ErrorCode.ROW_LENGTH_MISMATCH for e in result.errors)

    def test_csv_from_file(self) -> None:
        schema = TableSchema(
            name="test",
            fields=[Field("a", int)],
        )
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            f.write("a\n1\n2")
            f.flush()
            result = read_csv(f.name, schema)
        assert result.ok
        assert len(result.records) == 2

    def test_empty_file_error(self) -> None:
        schema = TableSchema(
            name="test",
            fields=[Field("a", int)],
        )
        with pytest.raises(ReadError, match="empty"):
            read_text("", schema)


class TestReadTsv:
    """Tests for read_tsv."""

    def test_simple_tsv(self) -> None:
        schema = TableSchema(
            name="test",
            fields=[Field("a", int), Field("b", str)],
        )
        tsv_content = "a\tb\n1\thello\n2\tworld"
        result = read_tsv(io.StringIO(tsv_content), schema)
        assert result.ok
        assert len(result.records) == 2


class TestValidationResultPandas:
    """Tests for to_pandas method."""

    def test_to_pandas(self) -> None:
        pytest.importorskip("pandas")
        schema = TableSchema(
            name="test",
            fields=[Field("a", int), Field("b", str)],
        )
        csv_content = "a,b\n1,hello\n2,world"
        result = read_text(csv_content, schema)

        df = result.to_pandas()
        assert len(df) == 2
        assert list(df.columns) == ["a", "b"]
        assert "labschema" in df.attrs
