"""Field definition for LabSchema table columns."""

from __future__ import annotations

import re
from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from typing import TYPE_CHECKING, Any

from labschema.errors import SchemaError
from labschema.units import get_registry, get_unit_string, parse_unit

if TYPE_CHECKING:
    from pint import Unit

_VALID_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

_ALLOWED_DTYPES = (int, float, str, bool)


class _UnsetType:
    """Sentinel for unset default values."""

    _instance: _UnsetType | None = None

    def __new__(cls) -> _UnsetType:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return "<UNSET>"

    def __bool__(self) -> bool:
        return False


_UNSET: _UnsetType = _UnsetType()


def _validate_name(name: str) -> None:
    """Validate that a field name is a valid Python identifier-like string."""
    if not _VALID_NAME_PATTERN.match(name):
        raise SchemaError(f"Invalid field name: {name!r}. Names must match [A-Za-z_][A-Za-z0-9_]*")


@dataclass(frozen=True, eq=True)
class Field:
    """Describes a single column in a table schema.

    Attributes:
        name: Canonical field name. Must be a valid Python identifier-like string.
        dtype: One of int, float, str, bool.
        unit: Declared unit. Only allowed when dtype is int or float.
        nullable: Whether missing values are allowed.
        description: Human-readable description; exported to JSON Schema.
        aliases: Extra header names that map to this field.
        ge: Greater than or equal constraint (numeric fields only).
        gt: Greater than constraint (numeric fields only).
        le: Less than or equal constraint (numeric fields only).
        lt: Less than constraint (numeric fields only).
        enum: Allowed values.
        pattern: Regex pattern for str fields. Matched with re.fullmatch.
        validators: Custom callables (value) -> value; raise ValueError to reject.
        default: Value substituted for missing cells.
    """

    name: str
    dtype: type
    unit: Unit | str | None = None
    nullable: bool = False
    description: str | None = None
    aliases: tuple[str, ...] = ()
    ge: float | None = None
    gt: float | None = None
    le: float | None = None
    lt: float | None = None
    enum: Collection[Any] | None = None
    pattern: str | None = None
    validators: Sequence[Callable[[Any], Any]] = ()
    default: Any = dataclass_field(default_factory=lambda: _UNSET)

    def __post_init__(self) -> None:
        """Validate field configuration at construction time."""
        _validate_name(self.name)

        if self.dtype not in _ALLOWED_DTYPES:
            raise SchemaError(
                f"Invalid dtype for field {self.name!r}: {self.dtype}. "
                f"Allowed types: int, float, str, bool"
            )

        if self.unit is not None and self.dtype not in (int, float):
            raise SchemaError(
                f"Field {self.name!r}: unit is only allowed for numeric types (int, float)"
            )

        if self.unit is not None and not isinstance(self.unit, str):
            unit_registry = getattr(self.unit, "_REGISTRY", None)
            if unit_registry is not None and unit_registry is not get_registry():
                raise SchemaError(
                    f"Field {self.name!r}: unit belongs to a different pint registry. "
                    "Call labschema.units.set_registry() before creating units, "
                    "or pass the unit as a string."
                )

        if self.unit is not None:
            try:
                parse_unit(self.unit if isinstance(self.unit, str) else str(self.unit))
            except SchemaError as e:
                raise SchemaError(f"Field {self.name!r}: {e}") from e

        if self.pattern is not None and self.dtype is not str:
            raise SchemaError(f"Field {self.name!r}: pattern is only allowed for str type")

        if self.pattern is not None:
            try:
                re.compile(self.pattern)
            except re.error as e:
                raise SchemaError(f"Field {self.name!r}: invalid regex pattern: {e}") from e

        if self.dtype not in (int, float) and any(
            b is not None for b in (self.ge, self.gt, self.le, self.lt)
        ):
            raise SchemaError(
                f"Field {self.name!r}: bounds (ge/gt/le/lt) are only allowed "
                f"for numeric types (int, float)"
            )

        if self.ge is not None and self.gt is not None:
            raise SchemaError(f"Field {self.name!r}: cannot set both 'ge' and 'gt'")

        if self.le is not None and self.lt is not None:
            raise SchemaError(f"Field {self.name!r}: cannot set both 'le' and 'lt'")

    def __hash__(self) -> int:
        """Make Field hashable by using only hashable attributes."""
        enum_hash = tuple(self.enum) if self.enum is not None else None
        validators_hash = tuple(id(v) for v in self.validators)
        default_hash = id(self.default) if self.default is _UNSET else hash(str(self.default))
        return hash(
            (
                self.name,
                self.dtype,
                get_unit_string(self.unit),
                self.nullable,
                self.description,
                self.aliases,
                self.ge,
                self.gt,
                self.le,
                self.lt,
                enum_hash,
                self.pattern,
                validators_hash,
                default_hash,
            )
        )

    @property
    def has_default(self) -> bool:
        """Check if this field has a default value set."""
        return self.default is not _UNSET

    @property
    def unit_string(self) -> str | None:
        """Get the canonical string representation of the unit."""
        return get_unit_string(self.unit)

    def to_dict(self) -> dict[str, Any]:
        """Convert the field to a dictionary for JSON serialization."""
        result: dict[str, Any] = {
            "name": self.name,
            "dtype": self.dtype.__name__,
        }

        if self.unit is not None:
            result["unit"] = self.unit_string

        if self.nullable:
            result["nullable"] = True

        if self.description is not None:
            result["description"] = self.description

        if self.aliases:
            result["aliases"] = list(self.aliases)

        if self.ge is not None:
            result["ge"] = self.ge
        if self.gt is not None:
            result["gt"] = self.gt
        if self.le is not None:
            result["le"] = self.le
        if self.lt is not None:
            result["lt"] = self.lt

        if self.enum is not None:
            result["enum"] = list(self.enum)

        if self.pattern is not None:
            result["pattern"] = self.pattern

        if self.validators:
            result["validators"] = [getattr(v, "__name__", repr(v)) for v in self.validators]

        if self.has_default:
            result["default"] = self.default

        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Field:
        """Create a Field from a dictionary.

        Args:
            data: Dictionary with field attributes.

        Returns:
            A new Field instance.

        Raises:
            SchemaError: If the dictionary contains invalid data.
        """
        dtype_map = {"int": int, "float": float, "str": str, "bool": bool}

        name = data.get("name")
        if not isinstance(name, str):
            raise SchemaError("Field 'name' is required and must be a string")

        dtype_str = data.get("dtype")
        if dtype_str not in dtype_map:
            raise SchemaError(
                f"Field {name!r}: invalid dtype {dtype_str!r}. Allowed: int, float, str, bool"
            )
        dtype = dtype_map[dtype_str]

        kwargs: dict[str, Any] = {
            "name": name,
            "dtype": dtype,
        }

        if "unit" in data:
            kwargs["unit"] = data["unit"]

        if data.get("nullable"):
            kwargs["nullable"] = True

        if "description" in data:
            kwargs["description"] = data["description"]

        if "aliases" in data:
            kwargs["aliases"] = tuple(data["aliases"])

        for bound in ("ge", "gt", "le", "lt"):
            if bound in data:
                kwargs[bound] = data[bound]

        if "enum" in data:
            kwargs["enum"] = data["enum"]

        if "pattern" in data:
            kwargs["pattern"] = data["pattern"]

        if "default" in data:
            kwargs["default"] = data["default"]

        if "validators" in data and data["validators"]:
            import warnings

            warnings.warn(
                f"Field {name!r}: validators cannot be deserialized from JSON. "
                f"Original validators: {data['validators']}",
                UserWarning,
                stacklevel=2,
            )

        return cls(**kwargs)
