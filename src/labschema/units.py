"""Shared pint registry with lab-specific unit aliases."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import pint

if TYPE_CHECKING:
    from pint import Unit

_registry: pint.UnitRegistry | None = None


def _create_registry() -> pint.UnitRegistry:
    """Create and configure the LabSchema pint registry with lab aliases."""
    reg = pint.UnitRegistry()

    reg.define("percent = 0.01 * dimensionless = %")
    reg.define("@alias revolution = rev")
    reg.define("revolutions_per_minute = revolution / minute = rpm")
    reg.define("molar = mol / liter = M")
    reg.define("arbitrary_unit = dimensionless = AU = au = a_u = RFU = OD")

    return reg


def get_registry() -> pint.UnitRegistry:
    """Get the shared LabSchema pint registry."""
    global _registry
    if _registry is None:
        _registry = _create_registry()
    return _registry


def set_registry(registry: pint.UnitRegistry) -> None:
    """Set a custom pint registry for LabSchema to use.

    Args:
        registry: A pint.UnitRegistry to use for all unit operations.

    Raises:
        SchemaError: If the registry is incompatible or already set to a different registry.
    """
    global _registry
    if _registry is not None and _registry is not registry:
        from labschema.errors import SchemaError

        raise SchemaError(
            "Cannot change registry after it has been used. "
            "Call set_registry() before any other labschema operations."
        )
    _registry = registry


u = get_registry()


_HEADER_UNIT_PATTERN = re.compile(r"^(?P<name>.*?)\s*[\[(](?P<unit>[^\[\]()]+)[\])]\s*$")

_TEMP_ALIASES: dict[str, str] = {
    "°C": "degC",
    "degC": "degC",
    "°F": "degF",
    "degF": "degF",
    "K": "kelvin",
}

_MICRO_ALIASES = {"µ", "μ", "u"}


def parse_header_unit(header: str) -> tuple[str, str | None, bool]:
    """Parse a column header to extract name and unit.

    Args:
        header: The raw column header text.

    Returns:
        A tuple of (name, unit_string, is_ambiguous) where:
        - name: The column name without the unit
        - unit_string: The unit string if found, or None
        - is_ambiguous: True if the unit was resolved using an ambiguous alias (e.g., 'C')
    """
    header = header.strip()
    match = _HEADER_UNIT_PATTERN.match(header)

    if not match:
        return header, None, False

    name = match.group("name").strip()
    unit_text = match.group("unit").strip()

    if not unit_text:
        return header, None, False

    parsed_unit, is_ambiguous = _try_parse_unit(unit_text, from_header=True)
    if parsed_unit is not None:
        return name, unit_text, is_ambiguous

    return header, None, False


def _try_parse_unit(unit_text: str, from_header: bool = False) -> tuple[str | None, bool]:
    """Try to parse a unit string, returning (normalized_unit, is_ambiguous).

    Args:
        unit_text: The unit string to parse.
        from_header: If True, allows header-specific aliases like 'C' for Celsius.

    Returns:
        A tuple of (unit_string, is_ambiguous). unit_string is None if parsing failed.
    """
    reg = get_registry()
    is_ambiguous = False

    if unit_text in ("a.u.", "AU", "au", "RFU", "OD"):
        return "dimensionless", False

    if unit_text in _TEMP_ALIASES:
        return _TEMP_ALIASES[unit_text], False

    if from_header and unit_text == "C":
        is_ambiguous = True
        return "degC", True

    normalized = unit_text
    for alias in _MICRO_ALIASES:
        if alias in normalized:
            normalized = normalized.replace(alias, "u")
            break

    try:
        parsed = reg.parse_expression(normalized)
        return str(parsed.units), is_ambiguous
    except (pint.UndefinedUnitError, pint.DimensionalityError):
        pass

    return None, False


def parse_unit(unit_str: str) -> Unit:
    """Parse a unit string into a pint Unit.

    Args:
        unit_str: The unit string to parse (e.g., 'mg/L', 'degC').

    Returns:
        A pint Unit object.

    Raises:
        SchemaError: If the unit string cannot be parsed.
    """
    reg = get_registry()

    if unit_str in ("a.u.", "AU", "au", "RFU", "OD"):
        return reg.dimensionless

    if unit_str in _TEMP_ALIASES:
        return reg.Unit(_TEMP_ALIASES[unit_str])

    normalized = unit_str
    for alias in _MICRO_ALIASES:
        if alias in normalized:
            normalized = normalized.replace(alias, "u")
            break

    try:
        return reg.Unit(normalized)
    except (pint.UndefinedUnitError, pint.DimensionalityError) as e:
        from labschema.errors import SchemaError

        raise SchemaError(f"Unknown unit: {unit_str!r}") from e


def convert_value(value: float | int, from_unit: str, to_unit: str) -> float:
    """Convert a numeric value between compatible units.

    Args:
        value: The numeric value to convert.
        from_unit: The source unit string.
        to_unit: The target unit string.

    Returns:
        The converted value as a float.

    Raises:
        SchemaError: If the units are incompatible or unknown.
    """
    reg = get_registry()

    from_u = parse_unit(from_unit)
    to_u = parse_unit(to_unit)

    quantity = reg.Quantity(value, from_u)
    try:
        converted = quantity.to(to_u)
        return float(converted.magnitude)
    except pint.DimensionalityError as e:
        from labschema.errors import SchemaError

        raise SchemaError(
            f"Cannot convert from {from_unit!r} to {to_unit!r}: incompatible dimensions"
        ) from e


def are_units_compatible(unit1: str, unit2: str) -> bool:
    """Check if two units are dimensionally compatible.

    Args:
        unit1: First unit string.
        unit2: Second unit string.

    Returns:
        True if the units can be converted between each other.
    """
    try:
        u1 = parse_unit(unit1)
        u2 = parse_unit(unit2)
        return u1.dimensionality == u2.dimensionality
    except Exception:
        return False


def get_unit_string(unit: Unit | str | None) -> str | None:
    """Get the canonical string representation of a unit.

    Args:
        unit: A pint Unit, unit string, or None.

    Returns:
        The canonical unit string, or None if the input is None.
    """
    if unit is None:
        return None
    if isinstance(unit, str):
        return str(parse_unit(unit))
    return str(unit)
