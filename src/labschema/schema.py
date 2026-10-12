"""TableSchema: the complete schema for a lab data table."""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from pathlib import Path
from typing import Any, Literal

from labschema.errors import SchemaError
from labschema.fields import Field

_NORMALIZE_PATTERN = re.compile(r"[^a-z0-9]+")


def normalize_name(name: str) -> str:
    """Normalize a column name for matching.

    Applies: Unicode NFKC, lowercase, trim, runs of non-alphanumerics -> '_',
    leading/trailing '_' removed.

    Args:
        name: The raw column name.

    Returns:
        The normalized name.
    """
    normalized = unicodedata.normalize("NFKC", name)
    normalized = normalized.lower().strip()
    normalized = _NORMALIZE_PATTERN.sub("_", normalized)
    normalized = normalized.strip("_")
    return normalized


@dataclass(frozen=True)
class TableSchema:
    """A complete schema for a lab data table.

    Attributes:
        name: Schema name (e.g., 'plate_reader_run').
        fields: Ordered list of field definitions. Names must be unique.
        primary_key: Field names whose combined values must be unique per row.
        extra_columns: Policy for columns in the file that match no field.
        version: User-defined schema version.
        description: Free text description.
        metadata: Arbitrary JSON-serializable metadata.
    """

    name: str
    fields: Sequence[Field]
    primary_key: tuple[str, ...] = ()
    extra_columns: Literal["ignore", "warn", "error"] = "warn"
    version: str | None = None
    description: str | None = None
    metadata: dict[str, Any] = dataclass_field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate schema configuration at construction time."""
        if not self.name:
            raise SchemaError("Schema name is required")

        if not self.fields:
            raise SchemaError("Schema must have at least one field")

        field_names: set[str] = set()
        normalized_names: dict[str, str] = {}
        all_aliases: dict[str, str] = {}

        for f in self.fields:
            if f.name in field_names:
                raise SchemaError(f"Duplicate field name: {f.name!r}")
            field_names.add(f.name)

            norm = normalize_name(f.name)
            if norm in normalized_names:
                raise SchemaError(
                    f"Fields {f.name!r} and {normalized_names[norm]!r} "
                    f"have the same normalized name: {norm!r}"
                )
            normalized_names[norm] = f.name

            for alias in f.aliases:
                norm_alias = normalize_name(alias)
                if norm_alias in normalized_names:
                    raise SchemaError(
                        f"Alias {alias!r} for field {f.name!r} conflicts with "
                        f"field name {normalized_names[norm_alias]!r}"
                    )
                if norm_alias in all_aliases:
                    raise SchemaError(
                        f"Duplicate alias: {alias!r} is used by both "
                        f"{f.name!r} and {all_aliases[norm_alias]!r}"
                    )
                all_aliases[norm_alias] = f.name

        for pk_field in self.primary_key:
            if pk_field not in field_names:
                raise SchemaError(f"Primary key field {pk_field!r} does not exist in schema")
            pk_field_obj = self.get_field(pk_field)
            if pk_field_obj is not None and pk_field_obj.nullable:
                raise SchemaError(f"Primary key field {pk_field!r} cannot be nullable")

        if self.extra_columns not in ("ignore", "warn", "error"):
            raise SchemaError(
                f"Invalid extra_columns policy: {self.extra_columns!r}. "
                f"Must be 'ignore', 'warn', or 'error'"
            )

    def get_field(self, name: str) -> Field | None:
        """Get a field by name.

        Args:
            name: The field name to look up.

        Returns:
            The Field if found, or None.
        """
        for f in self.fields:
            if f.name == name:
                return f
        return None

    def match_header(self, header: str) -> Field | None:
        """Match a header to a field using normalization rules.

        Args:
            header: The raw header text (without unit).

        Returns:
            The matching Field if found, or None.
        """
        norm_header = normalize_name(header)

        for f in self.fields:
            if normalize_name(f.name) == norm_header:
                return f
            for alias in f.aliases:
                if normalize_name(alias) == norm_header:
                    return f

        return None

    @property
    def field_names(self) -> tuple[str, ...]:
        """Get all field names in order."""
        return tuple(f.name for f in self.fields)

    def with_field(self, field: Field, position: int | None = None) -> TableSchema:
        """Return a new schema with an additional field.

        Args:
            field: The field to add.
            position: Insert position (default: append at end).

        Returns:
            A new TableSchema with the field added.

        Raises:
            SchemaError: If the field name conflicts with existing fields.
        """
        fields = list(self.fields)
        if position is None:
            fields.append(field)
        else:
            fields.insert(position, field)
        return TableSchema(
            name=self.name,
            fields=fields,
            primary_key=self.primary_key,
            extra_columns=self.extra_columns,
            version=self.version,
            description=self.description,
            metadata=dict(self.metadata),
        )

    def without_field(self, name: str) -> TableSchema:
        """Return a new schema without the specified field.

        Args:
            name: The field name to remove.

        Returns:
            A new TableSchema without the field.

        Raises:
            SchemaError: If the field is part of the primary key.
        """
        if name in self.primary_key:
            raise SchemaError(f"Cannot remove field {name!r}: it is part of the primary key")

        fields = [f for f in self.fields if f.name != name]
        if len(fields) == len(self.fields):
            raise SchemaError(f"Field {name!r} not found in schema")

        return TableSchema(
            name=self.name,
            fields=fields,
            primary_key=self.primary_key,
            extra_columns=self.extra_columns,
            version=self.version,
            description=self.description,
            metadata=dict(self.metadata),
        )

    def replace_field(self, name: str, field: Field) -> TableSchema:
        """Return a new schema with a field replaced.

        Args:
            name: The field name to replace.
            field: The new field definition.

        Returns:
            A new TableSchema with the field replaced.

        Raises:
            SchemaError: If the field doesn't exist.
        """
        fields = []
        found = False
        for f in self.fields:
            if f.name == name:
                fields.append(field)
                found = True
            else:
                fields.append(f)

        if not found:
            raise SchemaError(f"Field {name!r} not found in schema")

        pk = self.primary_key
        if name in pk and field.name != name:
            pk = tuple(field.name if n == name else n for n in pk)

        return TableSchema(
            name=self.name,
            fields=fields,
            primary_key=pk,
            extra_columns=self.extra_columns,
            version=self.version,
            description=self.description,
            metadata=dict(self.metadata),
        )

    def to_base_units(self) -> TableSchema:
        """Return a new schema with all units converted to SI base units.

        Returns:
            A new TableSchema with SI base units.
        """
        new_fields = []

        for f in self.fields:
            if f.unit is not None:
                from labschema.units import get_registry, parse_unit

                reg = get_registry()
                unit = parse_unit(f.unit if isinstance(f.unit, str) else str(f.unit))
                quantity = reg.Quantity(1, unit)
                base_unit = quantity.to_base_units().units
                new_fields.append(
                    Field(
                        name=f.name,
                        dtype=f.dtype,
                        unit=str(base_unit),
                        nullable=f.nullable,
                        description=f.description,
                        aliases=f.aliases,
                        ge=f.ge,
                        gt=f.gt,
                        le=f.le,
                        lt=f.lt,
                        enum=f.enum,
                        pattern=f.pattern,
                        validators=f.validators,
                        default=f.default if f.has_default else f.default,
                    )
                )
            else:
                new_fields.append(f)

        return TableSchema(
            name=self.name,
            fields=new_fields,
            primary_key=self.primary_key,
            extra_columns=self.extra_columns,
            version=self.version,
            description=self.description,
            metadata=dict(self.metadata),
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert the schema to a dictionary for JSON serialization."""
        result: dict[str, Any] = {
            "labschema": "0.1",
            "name": self.name,
            "fields": [f.to_dict() for f in self.fields],
        }

        if self.version is not None:
            result["version"] = self.version

        if self.description is not None:
            result["description"] = self.description

        if self.primary_key:
            result["primary_key"] = list(self.primary_key)

        if self.extra_columns != "warn":
            result["extra_columns"] = self.extra_columns

        if self.metadata:
            result["metadata"] = self.metadata

        return result

    def to_json(self, indent: int | None = 2) -> str:
        """Convert the schema to a JSON string.

        Args:
            indent: JSON indentation (default: 2).

        Returns:
            JSON string representation.
        """
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    def save(self, path: str | Path) -> None:
        """Save the schema to a JSON file.

        Args:
            path: File path to write to.
        """
        path = Path(path)
        path.write_text(self.to_json(), encoding="utf-8")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TableSchema:
        """Create a TableSchema from a dictionary.

        Args:
            data: Dictionary with schema attributes.

        Returns:
            A new TableSchema instance.

        Raises:
            SchemaError: If the dictionary contains invalid data.
        """
        if "labschema" in data:
            version = data["labschema"]
            if not version.startswith("0."):
                raise SchemaError(
                    f"Unsupported LabSchema version: {version}. This library supports version 0.x"
                )

        name = data.get("name")
        if not isinstance(name, str) or not name:
            raise SchemaError("Schema 'name' is required and must be a non-empty string")

        fields_data = data.get("fields")
        if not isinstance(fields_data, list) or not fields_data:
            raise SchemaError("Schema 'fields' is required and must be a non-empty list")

        fields = [Field.from_dict(f) for f in fields_data]

        kwargs: dict[str, Any] = {
            "name": name,
            "fields": fields,
        }

        if "version" in data:
            kwargs["version"] = data["version"]

        if "description" in data:
            kwargs["description"] = data["description"]

        if "primary_key" in data:
            kwargs["primary_key"] = tuple(data["primary_key"])

        if "extra_columns" in data:
            kwargs["extra_columns"] = data["extra_columns"]

        if "metadata" in data:
            kwargs["metadata"] = data["metadata"]

        return cls(**kwargs)

    @classmethod
    def from_json(cls, json_str: str) -> TableSchema:
        """Create a TableSchema from a JSON string.

        Args:
            json_str: JSON string representation.

        Returns:
            A new TableSchema instance.

        Raises:
            SchemaError: If the JSON is invalid.
        """
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as e:
            raise SchemaError(f"Invalid JSON: {e}") from e

        return cls.from_dict(data)

    @classmethod
    def load(cls, path: str | Path) -> TableSchema:
        """Load a TableSchema from a JSON file.

        Args:
            path: File path to read from.

        Returns:
            A new TableSchema instance.

        Raises:
            SchemaError: If the file cannot be read or contains invalid data.
            ReadError: If the file cannot be opened.
        """
        from labschema.errors import ReadError

        path = Path(path)
        try:
            content = path.read_text(encoding="utf-8")
        except OSError as e:
            raise ReadError(f"Cannot read schema file: {e}") from e

        return cls.from_json(content)

    def to_json_schema(self) -> dict[str, Any]:
        """Export the schema as JSON Schema (draft 2020-12).

        The JSON Schema describes one row as an object.

        Returns:
            JSON Schema dictionary.
        """
        properties: dict[str, Any] = {}
        required: list[str] = []

        for f in self.fields:
            prop: dict[str, Any] = {}

            type_map = {
                int: "integer",
                float: "number",
                str: "string",
                bool: "boolean",
            }
            base_type = type_map[f.dtype]

            if f.nullable:
                prop["type"] = [base_type, "null"]
            else:
                prop["type"] = base_type

            if f.description is not None:
                prop["description"] = f.description

            if f.unit is not None:
                prop["x-unit"] = f.unit_string

            if f.ge is not None:
                prop["minimum"] = f.ge
            if f.gt is not None:
                prop["exclusiveMinimum"] = f.gt
            if f.le is not None:
                prop["maximum"] = f.le
            if f.lt is not None:
                prop["exclusiveMaximum"] = f.lt

            if f.enum is not None:
                prop["enum"] = list(f.enum)

            if f.pattern is not None:
                prop["pattern"] = f.pattern

            properties[f.name] = prop

            if not f.nullable and not f.has_default:
                required.append(f.name)

        schema: dict[str, Any] = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "title": self.name,
            "properties": properties,
        }

        if required:
            schema["required"] = required

        if self.description is not None:
            schema["description"] = self.description

        if self.primary_key:
            schema["x-primary-key"] = list(self.primary_key)

        if self.metadata:
            schema["x-metadata"] = self.metadata

        return schema
