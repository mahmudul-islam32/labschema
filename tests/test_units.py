"""Tests for the units module."""

import pytest

from labschema.errors import SchemaError
from labschema.units import (
    are_units_compatible,
    convert_value,
    get_registry,
    parse_header_unit,
    parse_unit,
)


class TestParseHeaderUnit:
    """Tests for parse_header_unit."""

    def test_simple_header_no_unit(self) -> None:
        name, unit, ambiguous = parse_header_unit("temperature")
        assert name == "temperature"
        assert unit is None
        assert not ambiguous

    def test_header_with_brackets(self) -> None:
        name, unit, ambiguous = parse_header_unit("concentration [mg/L]")
        assert name == "concentration"
        assert unit == "mg/L"
        assert not ambiguous

    def test_header_with_parentheses(self) -> None:
        name, unit, ambiguous = parse_header_unit("Time (min)")
        assert name == "Time"
        assert unit == "min"
        assert not ambiguous

    def test_header_with_celsius(self) -> None:
        name, unit, ambiguous = parse_header_unit("Temp (°C)")
        assert name == "Temp"
        assert unit == "°C"
        assert not ambiguous

    def test_header_with_ambiguous_c(self) -> None:
        name, unit, ambiguous = parse_header_unit("Temp (C)")
        assert name == "Temp"
        assert unit == "C"
        assert ambiguous

    def test_header_with_micro_prefix(self) -> None:
        name, unit, ambiguous = parse_header_unit("volume [µL]")
        assert name == "volume"
        assert unit == "µL"
        assert not ambiguous

    def test_header_with_arbitrary_unit(self) -> None:
        name, unit, ambiguous = parse_header_unit("OD600 [a.u.]")
        assert name == "OD600"
        assert unit == "a.u."
        assert not ambiguous

    def test_header_with_text_in_brackets(self) -> None:
        name, unit, ambiguous = parse_header_unit("Sample (replicate)")
        assert name == "Sample (replicate)"
        assert unit is None
        assert not ambiguous


class TestParseUnit:
    """Tests for parse_unit."""

    def test_simple_unit(self) -> None:
        unit = parse_unit("mg/L")
        assert str(unit) == "milligram / liter"

    def test_celsius(self) -> None:
        unit = parse_unit("degC")
        assert "celsius" in str(unit).lower()

    def test_micro_prefix(self) -> None:
        unit = parse_unit("µL")
        assert "microliter" in str(unit).lower()

    def test_arbitrary_unit(self) -> None:
        unit = parse_unit("a.u.")
        assert unit.dimensionless

    def test_rpm(self) -> None:
        unit = parse_unit("rpm")
        reg = get_registry()
        assert unit.dimensionality == reg.Unit("revolution / minute").dimensionality

    def test_molar(self) -> None:
        unit = parse_unit("M")
        reg = get_registry()
        assert unit.dimensionality == reg.Unit("mol / L").dimensionality

    def test_invalid_unit(self) -> None:
        with pytest.raises(SchemaError, match="Unknown unit"):
            parse_unit("invalid_unit_xyz")


class TestConvertValue:
    """Tests for convert_value."""

    def test_simple_conversion(self) -> None:
        result = convert_value(1000, "mg", "g")
        assert result == pytest.approx(1.0)

    def test_volume_conversion(self) -> None:
        result = convert_value(1, "L", "mL")
        assert result == pytest.approx(1000.0)

    def test_temperature_conversion_celsius_to_kelvin(self) -> None:
        result = convert_value(0, "degC", "kelvin")
        assert result == pytest.approx(273.15)

    def test_incompatible_units(self) -> None:
        with pytest.raises(SchemaError, match="incompatible"):
            convert_value(1, "mg", "L")


class TestAreUnitsCompatible:
    """Tests for are_units_compatible."""

    def test_compatible_mass_units(self) -> None:
        assert are_units_compatible("mg", "g")
        assert are_units_compatible("kg", "mg")

    def test_compatible_temperature_units(self) -> None:
        assert are_units_compatible("degC", "kelvin")
        assert are_units_compatible("degC", "degF")

    def test_incompatible_units(self) -> None:
        assert not are_units_compatible("mg", "L")
        assert not are_units_compatible("degC", "mg")
