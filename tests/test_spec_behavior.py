"""Spec-driven checks for units, messages, streaming, and exports."""

from __future__ import annotations

import io
import json
import sys
import time
from pathlib import Path

import pytest

from labschema import Field, TableSchema, ValidationIssue, u
from labschema.errors import ErrorCode, SchemaError
from labschema.io import read_csv, read_text
from labschema.units import canonical_header_unit, parse_header_unit

FIXTURES = Path(__file__).parent / "fixtures"


def _plate_schema() -> TableSchema:
    return TableSchema(
        name="plate_reader_run",
        primary_key=("well",),
        fields=[
            Field("well", str, pattern=r"^[A-H](?:[1-9]|1[0-2])$"),
            Field("absorbance", float, ge=0),
            Field("temperature", float, unit="degC", ge=-273.15),
        ],
    )


class TestGoldenPlateReader:
    """The fixture report lists codes, rows, and counts."""

    def test_plate_reader_matches_expected(self) -> None:
        expected = json.loads((FIXTURES / "plate_reader_expected.json").read_text())
        result = read_csv(FIXTURES / "plate_reader.csv", _plate_schema())

        assert result.total_rows == expected["total_rows"]
        assert result.valid_rows == expected["valid_rows"]
        simplified = []
        for issue in result.errors:
            item = {"code": issue.code.value, "row": issue.row}
            if issue.column is not None:
                item["column"] = issue.column
            simplified.append(item)
        assert simplified == expected["expected_errors"]


class TestMessages:
    def test_bounds_message_matches_spec_shape(self) -> None:
        schema = TableSchema(
            name="temps",
            fields=[Field("temperature", float, unit="degC", ge=-273.15)],
        )
        result = read_text("temperature (°C)\n-300\n", schema)
        assert not result.ok
        message = result.errors[0].message
        assert message == (
            'line 2, column "temperature (°C)": value -300 is less than minimum -273.15 °C'
        )

    def test_type_error_quotes_the_raw_value(self) -> None:
        schema = TableSchema(name="abs", fields=[Field("absorbance", float)])
        result = read_text("absorbance\nOVRFLW\n", schema)
        assert result.errors[0].message == (
            'line 2, column "absorbance": value "OVRFLW" is not a valid float'
        )

    def test_issue_field_alias(self) -> None:
        issue = ValidationIssue(
            code=ErrorCode.TYPE_ERROR,
            severity="error",
            message="x",
            field_name="absorbance",
        )
        assert issue.field == "absorbance"


class TestUnits:
    def test_ambiguous_celsius_converts_as_temperature(self) -> None:
        schema = TableSchema(name="t", fields=[Field("temp", float, unit=u.degC)])
        result = read_text("temp (C)\n25\n", schema)
        assert result.ok
        assert any(issue.code == ErrorCode.UNIT_AMBIGUOUS for issue in result.report.warnings)
        assert result.records[0]["temp"] == pytest.approx(25.0)
        assert result.column_units["temp"] == "C"

    def test_fahrenheit_header_converts_to_celsius(self) -> None:
        schema = TableSchema(name="t", fields=[Field("temp", float, unit="degC")])
        result = read_text("temp [degF]\n32\n", schema)
        assert result.ok
        assert result.records[0]["temp"] == pytest.approx(0.0)

    def test_unknown_unit_expression(self) -> None:
        name, unit, ambiguous = parse_header_unit("conc [mg/not_a_unit]")
        assert name == "conc"
        assert unit == "mg/not_a_unit"
        assert not ambiguous
        assert canonical_header_unit("mg/not_a_unit") is None

        schema = TableSchema(
            name="t",
            fields=[Field("conc", float, unit="mg/L"), Field("note", str)],
        )
        result = read_text("conc [mg/not_a_unit],note\n1,ok\n", schema)
        assert not result.ok
        assert result.errors[0].code == ErrorCode.UNIT_UNKNOWN
        assert result.records[0] == {"note": "ok"}
        assert "conc" not in result.records[0]

    def test_replicate_parenthetical_is_not_a_unit(self) -> None:
        schema = TableSchema(name="t", fields=[Field("sample_replicate", str)])
        result = read_text("Sample (replicate)\nA\n", schema)
        assert result.ok
        assert result.records[0]["sample_replicate"] == "A"

    def test_incompatible_column_is_skipped(self) -> None:
        schema = TableSchema(
            name="t",
            fields=[Field("temp", float, unit="degC"), Field("name", str)],
        )
        result = read_text("temp [mg/L],name\n25,plate\n", schema)
        assert not result.ok
        assert result.errors[0].code == ErrorCode.UNIT_INCOMPATIBLE
        assert result.records == [{"name": "plate"}]

    def test_to_base_units_converts_bounds(self) -> None:
        schema = TableSchema(
            name="t",
            fields=[Field("temp", float, unit="degC", ge=-273.15, default=0)],
        )
        base = schema.to_base_units()
        field = base.get_field("temp")
        assert field is not None
        assert field.ge == pytest.approx(0.0)
        assert field.default == pytest.approx(273.15)
        assert "kelvin" in str(field.unit_string).lower()

    def test_mixed_registry_is_rejected(self) -> None:
        import pint

        other = pint.UnitRegistry()
        with pytest.raises(SchemaError, match="different pint registry"):
            Field("temp", float, unit=other.degC)

    def test_set_registry_before_use(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import pint

        import labschema.units as units

        monkeypatch.setattr(units, "_registry", None)
        monkeypatch.setattr(units, "_locked", False)
        custom = pint.UnitRegistry()
        units.set_registry(custom)
        assert units.get_registry() is custom


class TestCoercion:
    def test_integral_scientific_notation_is_an_int(self) -> None:
        schema = TableSchema(name="t", fields=[Field("n", int)])
        result = read_text("n\n1e3\n1.5e1\n1.2e0\n", schema)
        assert [issue.row for issue in result.errors] == [4]
        assert [row["n"] for row in result.records] == [1000, 15]

    def test_custom_validator_can_replace_the_value(self) -> None:
        def double(value: int) -> int:
            return value * 2

        schema = TableSchema(name="t", fields=[Field("n", int, validators=[double])])
        result = read_text("n\n4\n", schema)
        assert result.ok
        assert result.records[0]["n"] == 8

    def test_comment_lines_keep_file_line_numbers(self) -> None:
        schema = TableSchema(name="t", fields=[Field("n", int)])
        text = "# instrument\nn\nnope\n"
        result = read_text(text, schema, comment="#")
        assert result.errors[0].row == 3
        assert result.errors[0].code == ErrorCode.TYPE_ERROR

    def test_missing_sentinel_is_detected_before_strip_flag(self) -> None:
        schema = TableSchema(name="t", fields=[Field("label", str, nullable=True), Field("n", int)])
        result = read_text("label,n\n  NA  ,1\n kept ,2\n", schema, strip=False)
        assert result.ok
        assert result.records[0]["label"] is None
        assert result.records[1]["label"] == " kept "


class TestInferenceAndExport:
    def test_numeric_header_becomes_an_identifier(self) -> None:
        from labschema import infer_schema

        schema = infer_schema(io.StringIO("1st reading\n10\n11\n"), name="draft")
        field = schema.fields[0]
        assert field.name.startswith("col_")
        assert field.dtype is int

    def test_header_alias_when_it_differs(self) -> None:
        from labschema import infer_schema

        schema = infer_schema(io.StringIO("Temperature (°C)\n25.5\n"), name="draft")
        field = schema.get_field("temperature")
        assert field is not None
        assert field.aliases == ("Temperature (°C)",)
        assert field.unit is not None


class TestPandasExtra:
    def test_frame_export_without_optional_extra(self, monkeypatch: pytest.MonkeyPatch) -> None:
        schema = TableSchema(name="t", fields=[Field("n", int)])
        result = read_text("n\n1\n", schema)
        real_import = __import__

        def blocked(name: str, *args: object, **kwargs: object) -> object:
            if name == "pandas" or name.startswith("pandas."):
                raise ImportError("no pandas")
            return real_import(name, *args, **kwargs)

        for key in list(sys.modules):
            if key == "pandas" or key.startswith("pandas."):
                monkeypatch.delitem(sys.modules, key, raising=False)
        monkeypatch.setattr("builtins.__import__", blocked)
        with pytest.raises(ImportError, match=r"labschema\[pandas\]"):
            result.to_pandas()

    def test_frame_dtypes(self) -> None:
        pytest.importorskip("pandas")
        schema = TableSchema(
            name="t",
            fields=[Field("n", int), Field("label", str), Field("flag", bool)],
        )
        result = read_text("n,label,flag\n1,a,true\n", schema)
        frame = result.to_pandas()
        assert str(frame["n"].dtype) == "Int64"
        assert str(frame["label"].dtype) == "string"
        assert str(frame["flag"].dtype) == "boolean"
        assert frame.attrs["labschema"]["column_units"] == {}


class TestEdgeCoverage:
    """Exercise error paths that the happy-path tests do not reach."""

    def test_field_round_trip_keeps_optional_attributes(self) -> None:
        def positive(value: int) -> int:
            return value

        original = Field(
            "count",
            int,
            aliases=("n",),
            gt=0,
            lt=10,
            enum=[1, 2],
            default=1,
            validators=[positive],
        )
        with pytest.warns(UserWarning, match="validators"):
            restored = Field.from_dict(original.to_dict())
        assert restored.aliases == ("n",)
        assert restored.gt == 0
        assert restored.lt == 10
        assert list(restored.enum or []) == [1, 2]
        assert restored.default == 1

    def test_field_from_dict_rejects_bad_payloads(self) -> None:
        with pytest.raises(SchemaError, match="name"):
            Field.from_dict({"dtype": "str"})
        with pytest.raises(SchemaError, match="dtype"):
            Field.from_dict({"name": "a", "dtype": "date"})

    def test_pattern_and_string_default_round_trip(self) -> None:
        original = Field("code", str, pattern=r"[A-Z]+", description="id", default="NA")
        data = original.to_dict()
        assert data["pattern"] == r"[A-Z]+"
        assert data["default"] == "NA"
        restored = Field.from_dict(data)
        assert restored.pattern == r"[A-Z]+"
        assert restored.default == "NA"
        assert restored.description == "id"

    def test_to_base_units_converts_enum_and_keeps_text_default(self) -> None:
        schema = TableSchema(
            name="mass",
            fields=[
                Field("mass", float, unit="mg", enum=[1, 1000, "trace"], default="trace"),
            ],
        )
        field = schema.to_base_units().get_field("mass")
        assert field is not None
        assert field.default == "trace"
        assert field.enum is not None
        numeric = [item for item in field.enum if isinstance(item, (int, float))]
        assert numeric[0] == pytest.approx(numeric[1] / 1000)
        assert "trace" in list(field.enum)
        assert Field("score", float, le=1.0).to_dict()["le"] == 1.0

    def test_non_integral_unit_conversion_on_int_field(self) -> None:
        schema = TableSchema(name="t", fields=[Field("volume", int, unit="L")])
        bad = read_text("volume [mL]\n1.5\n", schema)
        assert bad.errors[0].code == ErrorCode.TYPE_ERROR
        good = read_text("volume [mL]\n1000\n", schema)
        assert good.ok
        assert good.records[0]["volume"] == 1

    def test_validator_return_is_checked_strictly(self) -> None:
        def corrupt(_value: int) -> str:
            return "nope"

        schema = TableSchema(name="t", fields=[Field("n", int, validators=[corrupt])])
        result = read_text("n\n1\n", schema)
        assert not result.ok
        assert result.errors[0].code == ErrorCode.TYPE_ERROR

    def test_unreadable_and_empty_inputs(self, tmp_path: Path) -> None:
        from labschema.errors import ReadError

        schema = TableSchema(name="t", fields=[Field("a", int)])
        with pytest.raises(ReadError):
            read_csv(tmp_path / "missing.csv", schema)
        with pytest.raises(ReadError, match="empty"):
            read_text("# only a comment\n", schema, comment="#")
        garbage = tmp_path / "bad.csv"
        garbage.write_bytes(b"\xff\xfe not utf-8")
        with pytest.raises(ReadError):
            read_csv(garbage, schema, encoding="utf-8")

    def test_malformed_csv_is_a_parse_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import csv

        class _BrokenReader:
            line_num = 0

            def __iter__(self) -> _BrokenReader:
                return self

            def __next__(self) -> list[str]:
                raise csv.Error("unterminated quote")

        monkeypatch.setattr(csv, "reader", lambda *_args, **_kwargs: _BrokenReader())
        schema = TableSchema(name="t", fields=[Field("a", int)])
        result = read_text("a\n1\n", schema)
        assert result.errors[0].code == ErrorCode.PARSE_ERROR
        assert not result.ok

    def test_format_unit_unknown_text_is_returned(self) -> None:
        from labschema.units import _install_aliases, format_unit, get_registry

        assert format_unit("not_a_unit") == "not_a_unit"
        assert "°C" in format_unit("degC")
        _install_aliases(get_registry())
        assert isinstance(repr(u), str)

    def test_cli_paths_in_process(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        from labschema.cli import main

        data = tmp_path / "data.csv"
        data.write_text("name,value\nAda,1\n")
        schema_path = tmp_path / "schema.json"
        TableSchema(
            name="people",
            fields=[Field("name", str), Field("value", int)],
        ).save(schema_path)

        with pytest.raises(SystemExit) as valid:
            main(["validate", str(data), "--schema", str(schema_path), "--format", "json"])
        assert valid.value.code == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["valid_rows"] == 1

        with pytest.raises(SystemExit) as quiet:
            main(["validate", str(data), "--schema", str(schema_path), "--quiet"])
        assert quiet.value.code == 0
        assert capsys.readouterr().out == ""

        with pytest.raises(SystemExit) as missing:
            main(["validate", str(tmp_path / "nope.csv"), "--schema", str(schema_path)])
        assert missing.value.code == 2

        with pytest.raises(SystemExit) as inferred:
            main(["infer", str(data), "--format", "python"])
        assert inferred.value.code == 0
        assert "TableSchema" in capsys.readouterr().out

        with pytest.raises(SystemExit) as exported:
            main(["export-schema", str(schema_path), "--format", "jsonschema"])
        assert exported.value.code == 0
        assert "json-schema.org" in capsys.readouterr().out

    def test_cli_interrupt_and_schema_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from labschema.cli import main

        def raise_keyboard(_args: object) -> int:
            raise KeyboardInterrupt

        monkeypatch.setattr("labschema.cli.cmd_validate", raise_keyboard)
        with pytest.raises(SystemExit) as interrupted:
            main(["validate", "data.csv", "--schema", "schema.json"])
        assert interrupted.value.code == 130

        def raise_schema(_args: object) -> int:
            raise SchemaError("broken schema")

        monkeypatch.setattr("labschema.cli.cmd_validate", raise_schema)
        with pytest.raises(SystemExit) as failed:
            main(["validate", "data.csv", "--schema", "schema.json"])
        assert failed.value.code == 2


class TestBenchmark:
    def test_ten_thousand_rows_validate_quickly(self) -> None:
        fields = [Field(f"c{i}", float, ge=0) for i in range(9)]
        fields.append(Field("name", str))
        schema = TableSchema(name="bench", fields=fields)
        header = ",".join(f"c{i}" for i in range(9)) + ",name"
        row = ",".join(["1.5"] * 9) + ",sample"
        text = header + "\n" + "\n".join([row] * 10_000) + "\n"
        started = time.perf_counter()
        result = read_text(text, schema)
        elapsed = time.perf_counter() - started
        assert result.ok
        assert result.valid_rows == 10_000
        assert elapsed < 2.0, f"validation took {elapsed:.2f}s"
