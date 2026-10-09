"""JSON Schema export for LabSchema."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from labschema.schema import TableSchema


def export_json_schema(
    schema: TableSchema,
    *,
    indent: int | None = 2,
) -> str:
    """Export a TableSchema as JSON Schema (draft 2020-12).

    The JSON Schema describes one row as an object.

    Args:
        schema: The TableSchema to export.
        indent: JSON indentation (default: 2).

    Returns:
        JSON Schema as a string.
    """
    return json.dumps(schema.to_json_schema(), indent=indent, ensure_ascii=False)


def save_json_schema(
    schema: TableSchema,
    path: str | Path,
    *,
    indent: int | None = 2,
) -> None:
    """Save a TableSchema as JSON Schema to a file.

    Args:
        schema: The TableSchema to export.
        path: File path to write to.
        indent: JSON indentation (default: 2).
    """
    path = Path(path)
    path.write_text(export_json_schema(schema, indent=indent), encoding="utf-8")


def export_labschema_json(
    schema: TableSchema,
    *,
    indent: int | None = 2,
) -> str:
    """Export a TableSchema as LabSchema JSON (native, round-trippable).

    Args:
        schema: The TableSchema to export.
        indent: JSON indentation (default: 2).

    Returns:
        LabSchema JSON as a string.
    """
    return schema.to_json(indent=indent)


def save_labschema_json(
    schema: TableSchema,
    path: str | Path,
) -> None:
    """Save a TableSchema as LabSchema JSON to a file.

    Args:
        schema: The TableSchema to export.
        path: File path to write to.
    """
    schema.save(path)
