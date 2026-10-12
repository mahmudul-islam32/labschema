"""Tests for the CLI module."""

import argparse
import json
import subprocess
import sys
from pathlib import Path

import pytest

from labschema.cli import cmd_export_schema, cmd_infer, cmd_validate, main


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


class TestCliDirectCalls:
    """Tests for direct CLI function calls."""

    def test_cmd_validate_strict_mode(self, tmp_path: Path) -> None:
        csv_file = tmp_path / "data.csv"
        csv_file.write_text("name,extra\nAlice,x")
        schema_file = tmp_path / "schema.json"
        schema_file.write_text(
            json.dumps(
                {
                    "labschema": "0.1",
                    "name": "test",
                    "fields": [{"name": "name", "dtype": "str"}],
                    "extra_columns": "warn",
                }
            )
        )

        args = argparse.Namespace(
            data=str(csv_file),
            schema=str(schema_file),
            delimiter=None,
            decimal=".",
            thousands=None,
            encoding="utf-8-sig",
            skip_rows=0,
            comment=None,
            na=[],
            max_errors=1000,
            format="text",
            strict=True,
            quiet=False,
        )
        exit_code = cmd_validate(args)
        assert exit_code == 1  # Warnings treated as errors

    def test_cmd_infer_read_error(self) -> None:
        args = argparse.Namespace(
            data="nonexistent_file.csv",
            sample_rows=100,
            name=None,
            format="json",
            output=None,
        )
        exit_code = cmd_infer(args)
        assert exit_code == 2

    def test_cmd_export_schema_output_file(self, tmp_path: Path) -> None:
        schema_file = tmp_path / "schema.json"
        schema_file.write_text(
            json.dumps(
                {
                    "labschema": "0.1",
                    "name": "test",
                    "fields": [{"name": "a", "dtype": "str"}],
                }
            )
        )
        output_file = tmp_path / "output.json"

        args = argparse.Namespace(
            schema=str(schema_file),
            format="jsonschema",
            output=str(output_file),
        )
        exit_code = cmd_export_schema(args)
        assert exit_code == 0
        assert output_file.exists()

    def test_main_labschema_error(self, tmp_path: Path) -> None:
        csv_file = tmp_path / "data.csv"
        csv_file.write_text("a\n1")
        with pytest.raises(SystemExit) as exc_info:
            main(["validate", str(csv_file), "--schema", "nonexistent.json"])
        assert exc_info.value.code == 2

    def test_load_schema_from_module(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # Create a test module
        module_dir = tmp_path / "test_module"
        module_dir.mkdir()
        (module_dir / "__init__.py").write_text("")
        (module_dir / "schemas.py").write_text("""
from labschema import TableSchema, Field
test_schema = TableSchema(name="test", fields=[Field("a", str)])
""")
        monkeypatch.syspath_prepend(str(tmp_path))

        from labschema.cli import _load_schema

        schema = _load_schema("test_module.schemas:test_schema")
        assert schema.name == "test"

    def test_validate_with_options(self, tmp_path: Path) -> None:
        csv_file = tmp_path / "data.csv"
        csv_file.write_text("# comment\na;b\n1;2")
        schema_file = tmp_path / "schema.json"
        schema_file.write_text(
            json.dumps(
                {
                    "labschema": "0.1",
                    "name": "test",
                    "fields": [
                        {"name": "a", "dtype": "int"},
                        {"name": "b", "dtype": "int"},
                    ],
                }
            )
        )

        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "labschema",
                "validate",
                str(csv_file),
                "--schema",
                str(schema_file),
                "--delimiter",
                ";",
                "--skip-rows",
                "1",
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0

    def test_export_schema_output_file_labschema(self, tmp_path: Path) -> None:
        schema_file = tmp_path / "schema.json"
        schema_file.write_text(
            json.dumps(
                {
                    "labschema": "0.1",
                    "name": "test",
                    "fields": [{"name": "a", "dtype": "str"}],
                }
            )
        )
        output_file = tmp_path / "output.json"

        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "labschema",
                "export-schema",
                str(schema_file),
                "--format",
                "labschema",
                "-o",
                str(output_file),
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert output_file.exists()
