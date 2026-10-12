"""Shared pint registry with lab-specific unit aliases."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, cast

import pint

if TYPE_CHECKING:
    from pint import Unit

_registry: pint.UnitRegistry | None = None
_locked = False

_ALIAS_DEFINITIONS = (
    "percent = 0.01 * dimensionless = %",
    "@alias revolution = rev",
    "revolutions_per_minute = revolution / minute = rpm",
    "molar = mol / liter = M",
    "arbitrary_unit = dimensionless = AU = au = a_u = RFU = OD",
)


def _install_aliases(reg: pint.UnitRegistry) -> None:
    """Add lab unit aliases to a registry, ignoring ones already defined."""
    for definition in _ALIAS_DEFINITIONS:
        try:
            reg.define(definition)
        except (pint.errors.RedefinitionError, pint.errors.DefinitionSyntaxError):
            continue


def _create_registry() -> pint.UnitRegistry:
    """Create and configure the LabSchema pint registry with lab aliases."""
    reg = pint.UnitRegistry()
    _install_aliases(reg)
    return reg


def get_registry() -> pint.UnitRegistry:
    """Get the shared LabSchema pint registry."""
    global _registry, _locked
    if _registry is None:
        _registry = _create_registry()
    _locked = True
    return _registry


def set_registry(registry: pint.UnitRegistry) -> None:
    """Set a custom pint registry for LabSchema to use.

    Call this before any other LabSchema operation. Mixing units from two
    registries raises ``SchemaError``.

    Args:
        registry: A pint.UnitRegistry to use for all unit operations.

    Raises:
        SchemaError: If a different registry is already in use.
    """
    global _registry, _locked
    if _locked and _registry is not None and _registry is not registry:
        from labschema.errors import SchemaError

        raise SchemaError(
            "Cannot change registry after it has been used. "
            "Call set_registry() before any other labschema operations."
        )
    _install_aliases(registry)
    _registry = registry
    _locked = True


class _RegistryProxy:
    """Defer registry creation so ``set_registry`` can run before first use."""

    def __getattr__(self, name: str) -> Any:
        return getattr(get_registry(), name)

    def __repr__(self) -> str:
        return repr(get_registry())


u = cast(pint.UnitRegistry, _RegistryProxy())


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

    if _looks_like_unit(unit_text):
        return name, unit_text, False

    return header, None, False


def _looks_like_unit(text: str) -> bool:
    """Return True when bracket text looks like a unit but may be unknown.

    Plain words (``replicate``, ``sample``) are names. Expressions with
    ``/``, ``*``, ``^``, or ``·``, and texts containing ``°`` or ``%``,
    look like units.
    """
    if re.fullmatch(r"[A-Za-z]+", text):
        return False
    if any(operator in text for operator in "/^*·"):
        return True
    return "°" in text or "%" in text


def canonical_header_unit(unit_text: str) -> str | None:
    """Return a registry unit string for header text, or None if it will not parse.

    Header-only aliases such as ``C`` for degrees Celsius are honored.
    """
    parsed, _ambiguous = _try_parse_unit(unit_text, from_header=True)
    return parsed


def format_unit(unit_str: str | None) -> str:
    """Return a compact display string for a unit, such as ``°C`` or ``mg/l``."""
    if not unit_str:
        return ""
    try:
        unit = parse_unit(unit_str)
    except Exception:
        return unit_str
    pretty = f"{unit:~P}".strip()
    return pretty or str(unit)


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
