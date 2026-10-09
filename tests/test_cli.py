"""Tests for the CLI module."""

import json
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture
def sample_csv(tmp_path: Path) -> Path:
    """Create a sample CSV file for testing."""
    csv_file = tmp_path / "sample.csv"
    csv_file.write_text("name,value\nAlice,10\nBob,20")
    return csv_file


@pytest.fixture
def sample_schema(tmp_path: Path) -> Path:
    """Create a sample schema file for testing."""
    schema_file = tmp_path / "schema.json"
    schema_file.write_text(
        json.dumps(
            {
                "labschema": "0.1",
                "name": "test",
                "fields": [
                    {"name": "name", "dtype": "str"},
                    {"name": "value", "dtype": "int"},
                ],
            }
        )
    )
    return schema_file


@pytest.fixture
def invalid_csv(tmp_path: Path) -> Path:
    """Create an invalid CSV file for testing."""
    csv_file = tmp_path / "invalid.csv"
    csv_file.write_text("name,value\nAlice,not_a_number")
    return csv_file


class TestCliValidate:
    """Tests for the validate command."""

    def test_validate_valid_csv(self, sample_csv: Path, sample_schema: Path) -> None:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "labschema",
                "validate",
                str(sample_csv),
                "--schema",
                str(sample_schema),
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "2 rows" in result.stdout
        assert "2 valid" in result.stdout

    def test_validate_invalid_csv(self, invalid_csv: Path, sample_schema: Path) -> None:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "labschema",
                "validate",
                str(invalid_csv),
                "--schema",
                str(sample_schema),
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 1
        assert "type_error" in result.stdout.lower()

    def test_validate_json_format(self, sample_csv: Path, sample_schema: Path) -> None:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "labschema",
                "validate",
                str(sample_csv),
                "--schema",
                str(sample_schema),
                "--format",
                "json",
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["total_rows"] == 2
        assert data["valid_rows"] == 2

    def test_validate_quiet(self, sample_csv: Path, sample_schema: Path) -> None:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "labschema",
                "validate",
                str(sample_csv),
                "--schema",
                str(sample_schema),
                "--quiet",
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert result.stdout == ""

    def test_validate_missing_schema(self, sample_csv: Path) -> None:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "labschema",
                "validate",
                str(sample_csv),
                "--schema",
                "nonexistent.json",
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 2


class TestCliInfer:
    """Tests for the infer command."""

    def test_infer_json(self, sample_csv: Path) -> None:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "labschema",
                "infer",
                str(sample_csv),
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["labschema"] == "0.1"
        assert len(data["fields"]) == 2

    def test_infer_python(self, sample_csv: Path) -> None:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "labschema",
                "infer",
                str(sample_csv),
                "--format",
                "python",
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "from labschema import" in result.stdout
        assert "TableSchema(" in result.stdout

    def test_infer_with_name(self, sample_csv: Path) -> None:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "labschema",
                "infer",
                str(sample_csv),
                "--name",
                "my_schema",
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["name"] == "my_schema"

    def test_infer_output_file(self, sample_csv: Path, tmp_path: Path) -> None:
        output_file = tmp_path / "output.json"
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "labschema",
                "infer",
                str(sample_csv),
                "-o",
                str(output_file),
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert output_file.exists()
        data = json.loads(output_file.read_text())
        assert "fields" in data


class TestCliExportSchema:
    """Tests for the export-schema command."""

    def test_export_labschema(self, sample_schema: Path) -> None:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "labschema",
                "export-schema",
                str(sample_schema),
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["labschema"] == "0.1"

    def test_export_jsonschema(self, sample_schema: Path) -> None:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "labschema",
                "export-schema",
                str(sample_schema),
                "--format",
                "jsonschema",
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert "$schema" in data
        assert data["title"] == "test"


class TestCliVersion:
    """Tests for version output."""

    def test_version(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "labschema", "--version"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "labschema" in result.stdout
        assert "0.1.0" in result.stdout
