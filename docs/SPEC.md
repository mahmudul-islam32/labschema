# LabSchema — Technical Specification

| | |
|---|---|
| **Status** | Draft — pre-implementation |
| **Target release** | v0.1.0 |
| **Source** | Derived from `labschema-project-plan.html` |
| **Language** | Python ≥ 3.10 |
| **License** | MIT |
| **Last updated** | 2026-10-09 |

The key words **MUST**, **SHOULD**, and **MAY** are used as described in RFC 2119.

---

## Table of contents

1. [Overview](#1-overview)
2. [Goals and non-goals](#2-goals-and-non-goals)
3. [Users and use cases](#3-users-and-use-cases)
4. [Architecture](#4-architecture)
5. [Domain model](#5-domain-model)
6. [Units](#6-units)
7. [Reading and parsing input](#7-reading-and-parsing-input)
8. [Validation](#8-validation)
9. [Schema inference](#9-schema-inference)
10. [Schema serialization and export](#10-schema-serialization-and-export)
11. [Public Python API](#11-public-python-api)
12. [Command-line interface](#12-command-line-interface)
13. [Packaging and dependencies](#13-packaging-and-dependencies)
14. [Repository layout](#14-repository-layout)
15. [Testing strategy](#15-testing-strategy)
16. [CI/CD and release process](#16-cicd-and-release-process)
17. [Non-functional requirements](#17-non-functional-requirements)
18. [Open-source readiness](#18-open-source-readiness)
19. [Roadmap](#19-roadmap)
20. [Risks and mitigations](#20-risks-and-mitigations)
21. [Open questions](#21-open-questions)
22. [Glossary](#22-glossary)

---

## 1. Overview

LabSchema is a small, public Python library that turns messy lab-style tables (CSV, TSV, clipboard exports) into **typed schemas with physical units and validation**.

A user declares a schema once (column names, types, units, and constraints), then uses it to parse lab files into validated records or a pandas DataFrame. Every problem is reported with its row, column, expected type or unit, and the allowed range. Schemas can be exported as JSON / JSON Schema so the data contract can travel with the data.

**Design principle:** the schema is the source of truth. Inference produces a *draft* schema that a person reviews and edits; it is never a black box that silently decides how data is interpreted.

### 1.1 Problem statement

- Spreadsheets mix values, units embedded in headers (`Temp (°C)`), and ad-hoc notes.
- pandas loads such files with `object` or incorrect dtypes.
- Validation lives in one-off scripts rather than reusable contracts.
- Unit and constraint context is lost when data moves between tools.

---

## 2. Goals and non-goals

### 2.1 Goals (v0.1)

| ID | Goal |
|---|---|
| G1 | Declare a table schema in Python (types, units, nullability, constraints). |
| G2 | Read CSV/TSV files and validate every row against the schema. |
| G3 | Parse units from headers and convert values to the schema's declared unit via `pint`. |
| G4 | Produce a structured `ValidationReport` with stable error codes and precise locations. |
| G5 | Infer a draft schema from a file's header and first *N* rows. |
| G6 | Export schemas to LabSchema JSON and to JSON Schema (draft 2020-12). |
| G7 | Provide a CLI with `validate`, `infer`, and `export-schema` commands. |
| G8 | Ship to PyPI with CI, ≥ 90 % coverage on core modules, and trusted publishing. |

### 2.2 Non-goals (v0.1)

- Excel (`.xlsx`), HDF5, or proprietary instrument formats.
- Full ontology or ELN (electronic lab notebook) integration.
- A web UI or hosted validation service.
- Automatic statistical outlier detection.
- Multi-table / relational schemas (foreign keys across files).
- YAML schema sidecars (planned for v0.2).

---

## 3. Users and use cases

**Primary audience:** lab researchers, grad students, and data engineers who handle instrument exports and spreadsheets.

| ID | Use case |
|---|---|
| UC1 | A grad student defines a schema for plate-reader exports and validates each new run before analysis. |
| UC2 | A data engineer runs `labschema validate` in a pipeline and fails the job on exit code `1`. |
| UC3 | A researcher receives an unfamiliar CSV, runs `labschema infer`, edits the draft schema, and commits it alongside the data. |
| UC4 | A lab publishes a dataset with an exported JSON Schema so collaborators know column meanings and units. |
| UC5 | A user loads a European-locale export (`,` decimal separator, `;` delimiter) and gets correctly typed floats. |

---

## 4. Architecture

### 4.1 Data flow

```
 ┌──────────┐   ┌─────────────┐   ┌──────────────┐   ┌──────────────┐   ┌──────────────┐
 │  Input   │──▶│   Infer     │──▶│   Define     │──▶│   Validate   │──▶│    Output    │
 │ Lab file │   │ (optional)  │   │ TableSchema  │   │ parse/coerce │   │ records, df, │
 │ CSV/TSV  │   │ draft schema│   │ fields+units │   │ convert/check│   │ schema export│
 └──────────┘   └─────────────┘   └──────────────┘   └──────────────┘   └──────────────┘
                       │                  ▲
                       └── human edits ───┘
```

### 4.2 Modules

| Module | Responsibility |
|---|---|
| `labschema.fields` | `Field` definition, dtype coercion, constraint declarations. |
| `labschema.schema` | `TableSchema`: ordered fields, primary key, metadata, serialization. |
| `labschema.units` | Shared `pint` registry (`u`), lab unit aliases, header unit parsing. |
| `labschema.validate` | Row/batch validation engine, `ValidationResult`, `ValidationReport`, error codes. |
| `labschema.infer` | Draft-schema inference from header patterns and sample statistics. |
| `labschema.io.csv` | `read_csv` / `read_tsv`: tokenizing, missing-value handling, locale decimals. |
| `labschema.io.jsonschema` | Export to LabSchema JSON and JSON Schema. |
| `labschema.cli` | `labschema` console entry point. |

Dependencies flow one way: `cli → io/infer → validate → schema → fields → units`. Core modules MUST NOT import `pandas` at module import time.

---

## 5. Domain model

### 5.1 `Field`

Describes a single column.

| Attribute | Type | Default | Description |
|---|---|---|---|
| `name` | `str` | required | Canonical field name. MUST be a valid Python identifier-like string (`[A-Za-z_][A-Za-z0-9_]*`). |
| `dtype` | `type` | required | One of `int`, `float`, `str`, `bool` in v0.1. |
| `unit` | `pint.Unit \| str \| None` | `None` | Declared unit. Only allowed when `dtype` is `int` or `float`. |
| `nullable` | `bool` | `False` | Whether missing values are allowed. |
| `description` | `str \| None` | `None` | Human-readable description; exported to JSON Schema. |
| `aliases` | `tuple[str, ...]` | `()` | Extra header names that map to this field. |
| `ge`, `gt`, `le`, `lt` | `float \| None` | `None` | Numeric bounds, expressed in the field's declared unit. |
| `enum` | `Collection \| None` | `None` | Allowed values. |
| `pattern` | `str \| None` | `None` | Regex; `str` fields only. Matched with `re.fullmatch`. |
| `validators` | `Sequence[Callable]` | `()` | Custom callables `(value) -> value`; raise `ValueError` to reject. |
| `default` | `Any` | *unset* | Value substituted for missing cells (implies the cell is not reported as null). |

Construction-time rules (violations raise `SchemaError` immediately, not at validation time):

- `unit` set on a non-numeric dtype.
- `pattern` set on a non-`str` dtype.
- Bounds set on a non-numeric dtype.
- `ge`/`gt` both set, or `le`/`lt` both set.
- Unknown unit string.

`Field` instances are immutable (frozen) and hashable.

### 5.2 `TableSchema`

| Attribute | Type | Default | Description |
|---|---|---|---|
| `name` | `str` | required | Schema name (e.g. `plate_reader_run`). |
| `fields` | `Sequence[Field]` | required | Ordered list; names MUST be unique. |
| `primary_key` | `tuple[str, ...]` | `()` | Field names whose combined values MUST be unique per row. |
| `extra_columns` | `"ignore" \| "warn" \| "error"` | `"warn"` | Policy for columns in the file that match no field. |
| `version` | `str \| None` | `None` | User-defined schema version. |
| `description` | `str \| None` | `None` | Free text. |
| `metadata` | `dict[str, Any]` | `{}` | Arbitrary JSON-serializable metadata (instrument, protocol, operator). |

Rules:

- Duplicate field names or aliases (after normalization, §7.3) raise `SchemaError`.
- Every `primary_key` entry MUST name an existing, non-nullable field.
- `TableSchema` is immutable; helper methods return new instances (`with_field`, `without_field`, `replace_field`).

### 5.3 Validation outputs

**`ValidationIssue`**

| Attribute | Type | Description |
|---|---|---|
| `code` | `ErrorCode` | Stable machine-readable code (§8.3). |
| `severity` | `"error" \| "warning"` | Only errors make a result invalid. |
| `message` | `str` | Human-readable sentence. |
| `row` | `int \| None` | 1-based **file line number** (header is line 1). `None` for file-level issues. |
| `column` | `str \| None` | Raw header text as it appears in the file. |
| `field` | `str \| None` | Schema field name. |
| `value` | `str \| None` | Raw cell text (truncated to 80 chars). |
| `context` | `dict[str, Any]` | Code-specific details, e.g. `{"ge": 0, "unit": "mg/L"}`. |

**`ValidationReport`** — an ordered collection of issues with helpers:

- `errors`, `warnings` — filtered tuples.
- `by_code()` → `dict[ErrorCode, list[ValidationIssue]]`.
- `print_summary(file=sys.stdout, limit=20)` — grouped, human-readable output.
- `to_dict()` / `to_json()` — machine-readable output (used by `--format json`).
- `truncated: bool` — `True` if `max_errors` was reached.

**`ValidationResult`**

- `ok: bool` — `True` iff there are no errors.
- `errors` — shortcut for `report.errors`.
- `report: ValidationReport`.
- `records: list[dict[str, Any]]` — valid rows only, values coerced and unit-converted.
- `column_units: dict[str, str]` — source unit per field as found in the header (provenance).
- `to_records()` — returns `records`.
- `to_pandas()` — DataFrame of valid rows with correct dtypes; units stored in `df.attrs["labschema"]`. Raises `ImportError` with an install hint if the `pandas` extra is missing.

---

## 6. Units

### 6.1 Registry

- LabSchema exposes one shared `pint.UnitRegistry` as `labschema.u`.
- Users MUST be able to pass either `u.mg / u.L` or the string `"mg/L"`.
- Users MAY pass their own registry via `labschema.units.set_registry(reg)`; mixing registries raises `SchemaError`.

### 6.2 Lab aliases

The registry MUST understand these additional spellings:

| Input | Resolves to |
|---|---|
| `°C`, `degC`, `C` *(header context only)* | `degree_Celsius` |
| `µ`, `μ`, `u` prefix (e.g. `µL`, `uL`) | micro |
| `%` | `percent` |
| `a.u.`, `AU`, `au`, `RFU`, `OD` | `dimensionless` |
| `rpm` | `revolutions_per_minute` |
| `M` (molarity) | `mol/L` |

> `C` alone is ambiguous with coulomb; it is treated as Celsius **only** when parsed from a header, and a `unit_ambiguous` warning is emitted.

### 6.3 Header unit syntax

A header MAY carry a unit in square brackets or parentheses at the end:

```
concentration [mg/L]
Time (min)
Temp (°C)
OD600 [a.u.]
```

Regex (applied after trimming whitespace): `^(?P<name>.*?)\s*[\[(](?P<unit>[^\[\]()]+)[\])]\s*$`

If the bracketed text does not parse as a unit, it is treated as part of the name (e.g. `Sample (replicate)`), and no unit is assigned.

### 6.4 Conversion rules

Let **S** be the field's declared unit and **H** the unit found in the header.

| S | H | Behaviour |
|---|---|---|
| set | absent | Values are assumed to already be in **S**. |
| set | same as S | No conversion. |
| set | compatible dimension | Values converted H → S. Source unit recorded in `column_units`. |
| set | incompatible dimension | File-level `unit_incompatible` error; column skipped. |
| `None` | present | `unit_unexpected` warning; values are used as-is. |
| `None` | absent | No unit handling. |

- Bounds (`ge`, `le`, …) are evaluated **after** conversion, in unit **S**.
- Offset units (°C, °F) MUST be converted as absolute temperatures, not deltas.
- LabSchema never guesses a unit that is not explicitly present in the schema or header (see §20).

> **Output unit.** Values are stored in the field's declared unit **S**. Users who want SI output declare SI units in the schema, or call `schema.to_base_units()`, which returns a copy with every unit replaced by its SI base equivalent. See [Q1](#21-open-questions).

---

## 7. Reading and parsing input

### 7.1 Supported formats (v0.1)

| Format | Entry point | Notes |
|---|---|---|
| CSV | `read_csv(path, schema, …)` | Default delimiter `,`. |
| TSV | `read_tsv(path, schema, …)` | Same as `read_csv(..., delimiter="\t")`. |
| Text / clipboard | `read_text(text, schema, …)` | Parses an in-memory string. |
| File-like | `read_csv(fileobj, …)` | Any text stream. |

Fixed-width input is **deferred** (listed in the plan's data-flow diagram but not in v0.1 scope).

### 7.2 Reader options

| Option | Type | Default | Description |
|---|---|---|---|
| `delimiter` | `str \| None` | `None` | `None` → sniff with `csv.Sniffer` from the first 8 KiB, falling back to `,`. |
| `decimal` | `"." \| ","` | `"."` | Decimal separator for numeric fields. |
| `thousands` | `str \| None` | `None` | Thousands separator to strip (e.g. `" "`, `"'"`). MUST differ from `decimal`. |
| `encoding` | `str` | `"utf-8-sig"` | Strips a BOM if present. |
| `na_values` | `Collection[str] \| None` | `None` | Replaces the default sentinel set. |
| `extra_na_values` | `Collection[str]` | `()` | Added to the default sentinel set. |
| `skip_rows` | `int` | `0` | Lines to skip before the header (instrument preambles). |
| `comment` | `str \| None` | `None` | Lines starting with this prefix are ignored. |
| `max_errors` | `int \| None` | `1000` | Stop collecting issues after this many errors; `None` = unlimited. |
| `strip` | `bool` | `True` | Trim whitespace around cells. |

### 7.3 Header matching

1. Each header is split into `(name, unit)` per §6.3.
2. Names are **normalized**: Unicode NFKC, lowercase, trim, runs of non-alphanumerics → `_`, leading/trailing `_` removed. `"Temp (°C)"` → `temp`; `"Conc. [mg/L]"` → `conc`.
3. A header matches a field if its normalized name equals the normalized field name or any normalized alias.
4. Fields with no matching header → `missing_column` error (or, if the field is nullable or has a default, a `missing_column` **warning** and all values become null/default).
5. Headers matching no field → handled by `extra_columns` policy (`extra_column` issue).
6. Two headers matching the same field → `duplicate_column` error.

Column order in the file does not matter.

### 7.4 Missing values

Default sentinel set (compared after stripping, case-sensitive):

```
"", "NA", "N/A", "n/a", "NaN", "nan", "null", "NULL", "None", "-", "--",
"#N/A", "#DIV/0!", "#VALUE!", "#REF!", "#NUM!"
```

A missing cell:

- becomes `default` if the field has one;
- else becomes `None` if `nullable=True`;
- else produces a `null_not_allowed` error.

### 7.5 Type coercion

| dtype | Accepted input | Rejected (→ `type_error`) |
|---|---|---|
| `int` | Optional sign, digits; thousands separators removed; `"3.0"` accepted if integral. | `"3.5"`, `"1e3"` with fraction, text. |
| `float` | Decimal with configured separator; scientific notation (`1.2e-3`); `inf`/`-inf`. | Text, mixed separators. |
| `bool` | Case-insensitive `true/false`, `yes/no`, `y/n`, `1/0`, `t/f`. | Anything else. |
| `str` | Any text. | — |

Rows whose cell count differs from the header produce a `row_length_mismatch` error and are not validated further.

---

## 8. Validation

### 8.1 Pipeline

For each data row, per field, in this order:

1. **Missing check** (§7.4)
2. **Coerce** to dtype (§7.5)
3. **Convert units** (§6.4)
4. **Constraints**: `ge/gt/le/lt` → `enum` → `pattern`
5. **Custom validators**, in declaration order

The first failure for a cell stops further checks on **that cell**; other cells in the row are still checked so that all problems in a row are reported together.

After all rows: **primary-key uniqueness** across valid rows.

A row is included in `records` only if it has no errors.

### 8.2 Implementation note

Validation SHOULD build one `pydantic.TypeAdapter` (or a generated model) per schema and reuse it for all rows. Coercion of locale decimals, sentinels, and units happens before Pydantic sees the value, so Pydantic runs in strict mode.

### 8.3 Error codes

Codes are part of the public API: they MUST NOT change meaning within a major version.

| Code | Severity | Level | Raised when |
|---|---|---|---|
| `missing_column` | error / warning | file | A schema field has no matching header (§7.3). |
| `extra_column` | per policy | file | A header matches no field. |
| `duplicate_column` | error | file | Two headers map to one field. |
| `unit_unknown` | error | file | Header unit text looks like a unit but `pint` cannot parse it. |
| `unit_incompatible` | error | file | Header unit dimension ≠ field unit dimension. |
| `unit_unexpected` | warning | file | Header has a unit, field declares none. |
| `unit_ambiguous` | warning | file | Ambiguous header unit resolved by convention (e.g. `C`). |
| `row_length_mismatch` | error | row | Wrong number of cells. |
| `null_not_allowed` | error | cell | Missing value in a non-nullable field. |
| `type_error` | error | cell | Value cannot be coerced to dtype. |
| `less_than_minimum` | error | cell | Violates `ge` / `gt`. |
| `greater_than_maximum` | error | cell | Violates `le` / `lt`. |
| `not_in_enum` | error | cell | Value not in `enum`. |
| `pattern_mismatch` | error | cell | `str` value fails `pattern`. |
| `custom_validator` | error | cell | A custom validator raised `ValueError`. |
| `duplicate_primary_key` | error | row | Primary-key tuple seen before; `context` holds the first row number. |
| `parse_error` | error | file | Malformed CSV (e.g. unterminated quote). |

### 8.4 Error message format

Messages MUST be deterministic (stable for snapshot tests) and follow:

```
line 14, column "temperature (°C)": value -300 is less than minimum -273.15 °C
```

`print_summary()` groups by code and shows at most `limit` examples per code, followed by `… and N more`.

---

## 9. Schema inference

`infer_schema(source, *, sample_rows=100, name=None, **reader_options) -> TableSchema`

### 9.1 Algorithm

For each column:

1. **Name & unit** — split header per §6.3; field name = normalized name (§7.3); original header stored as an alias if it differs.
2. **Nullable** — `True` if any sampled cell is a missing sentinel.
3. **dtype** — the narrowest type that accepts every non-missing sample value, trying in order `bool → int → float → str`. An all-missing column becomes `str`, nullable.
4. **Unit** — header unit if parseable; otherwise none. Units are **never** inferred from values.
5. **Constraints** — none are inferred in v0.1. Observed min/max are written to `field.description` as a hint (e.g. `observed range 0.01–3.2 in 100 sampled rows`).
6. **Enum hint** — if a `str` column has ≤ 10 distinct values and ≥ 20 samples, the distinct values are listed in the description, **not** set as `enum`.

### 9.2 Output

Inference returns a normal `TableSchema` with `metadata["inferred"] = {"source": ..., "sample_rows": ..., "labschema_version": ...}`. The CLI can render it as LabSchema JSON or as Python source code for editing.

---

## 10. Schema serialization and export

### 10.1 LabSchema JSON (native, round-trippable)

```json
{
  "labschema": "0.1",
  "name": "plate_reader_run",
  "version": "1",
  "description": "96-well absorbance export",
  "primary_key": ["well"],
  "extra_columns": "warn",
  "metadata": {"instrument": "Synergy H1"},
  "fields": [
    {"name": "well", "dtype": "str", "pattern": "^[A-H](?:[1-9]|1[0-2])$"},
    {"name": "absorbance", "dtype": "float", "unit": "dimensionless", "ge": 0},
    {"name": "temperature", "dtype": "float", "unit": "degree_Celsius", "ge": -273.15}
  ]
}
```

- `TableSchema.to_json()` / `TableSchema.from_json()` and `save(path)` / `load(path)`.
- Round-trip MUST be lossless for every attribute except `validators` (callables are not serializable; their names are written to `"validators": ["name", …]` and `from_json` emits a warning).
- Units are serialized as `pint`'s canonical long-form string.

### 10.2 JSON Schema export

`TableSchema.to_json_schema()` returns a JSON Schema (draft 2020-12) describing **one row** as an object:

| LabSchema | JSON Schema |
|---|---|
| `int` / `float` / `str` / `bool` | `integer` / `number` / `string` / `boolean` |
| `nullable=True` | `"type": ["number", "null"]` |
| `ge` / `gt` / `le` / `lt` | `minimum` / `exclusiveMinimum` / `maximum` / `exclusiveMaximum` |
| `enum`, `pattern`, `description` | same keyword |
| `unit` | `"x-unit": "mg/L"` (vendor extension) |
| non-nullable fields without defaults | listed in `required` |
| `primary_key`, `metadata` | `"x-primary-key"`, `"x-metadata"` at top level |

JSON Schema export is one-way; importing JSON Schema is out of scope for v0.1.

---

## 11. Public Python API

Everything listed here is importable from the top-level package unless noted. Anything not listed is private and may change without notice.

```python
from labschema import (
    Field, TableSchema, u,                       # model
    ValidationResult, ValidationReport, ValidationIssue, ErrorCode,
    SchemaError, LabSchemaError,                 # exceptions
    infer_schema, validate_rows,
    __version__,
)
from labschema.io import read_csv, read_tsv, read_text
```

### 11.1 Example

```python
from labschema import TableSchema, Field, u
from labschema.io import read_csv

schema = TableSchema(
    name="plate_reader_run",
    primary_key=("well",),
    fields=[
        Field("well", str, pattern=r"^[A-H](?:[1-9]|1[0-2])$"),
        Field("absorbance", float, unit=u.dimensionless, ge=0),
        Field("temperature", float, unit=u.degC, ge=-273.15),
    ],
)

result = read_csv("run_042.csv", schema=schema, decimal=",")
if not result.ok:
    result.report.print_summary()
else:
    df = result.to_pandas()  # requires labschema[pandas]
```

### 11.2 Signatures

```python
def read_csv(
    source: str | os.PathLike | TextIO,
    schema: TableSchema,
    *,
    delimiter: str | None = None,
    decimal: Literal[".", ","] = ".",
    thousands: str | None = None,
    encoding: str = "utf-8-sig",
    na_values: Collection[str] | None = None,
    extra_na_values: Collection[str] = (),
    skip_rows: int = 0,
    comment: str | None = None,
    max_errors: int | None = 1000,
    strip: bool = True,
) -> ValidationResult: ...

def validate_rows(
    rows: Iterable[Mapping[str, Any]],
    schema: TableSchema,
    *,
    max_errors: int | None = 1000,
) -> ValidationResult: ...   # for already-parsed data (e.g. dicts from another source)

def infer_schema(
    source: str | os.PathLike | TextIO,
    *,
    sample_rows: int = 100,
    name: str | None = None,
    **reader_options,
) -> TableSchema: ...
```

### 11.3 Exceptions

```
LabSchemaError            # base class
├── SchemaError           # invalid schema definition (raised at construction / load)
└── ReadError             # unreadable file, encoding failure, empty file
```

Data problems are **never** raised as exceptions; they are returned in the `ValidationReport`.

### 11.4 Typing

The package MUST ship a `py.typed` marker and pass `mypy --strict` on `src/`.

---

## 12. Command-line interface

Entry point: `labschema` (also `python -m labschema`). Implemented with **argparse** to keep the core install dependency-free beyond pydantic and pint.

### 12.1 `labschema validate`

```
labschema validate DATA --schema SCHEMA [options]
```

| Option | Description |
|---|---|
| `--schema PATH \| MODULE:ATTR` | LabSchema JSON file, or a Python import path to a `TableSchema` object (e.g. `myproj.schemas:plate_run`). Required. |
| `--delimiter`, `--decimal`, `--thousands`, `--encoding`, `--skip-rows`, `--comment` | Map to reader options (§7.2). |
| `--na VALUE` | Extra missing-value sentinel; repeatable. |
| `--max-errors N` | Default 1000; `0` = unlimited. |
| `--format text\|json` | Report format on stdout. Default `text`. |
| `--strict` | Treat warnings as errors. |
| `--quiet` | Print nothing; rely on the exit code. |

### 12.2 `labschema infer`

```
labschema infer DATA [--sample-rows N] [--name NAME] [--format json|python] [-o OUT]
```

Writes a draft schema to stdout or `OUT`. `--format python` emits editable source code using the API in §11.1.

### 12.3 `labschema export-schema`

```
labschema export-schema SCHEMA [--format labschema|jsonschema] [-o OUT]
```

### 12.4 Global options

`--version`, `-h/--help`.

### 12.5 Exit codes

| Code | Meaning |
|---|---|
| `0` | Success; data valid (warnings allowed unless `--strict`). |
| `1` | Validation finished and found errors. |
| `2` | Usage error, unreadable file, or invalid schema. |

### 12.6 Example output

```
$ labschema validate run_042.csv --schema plate_run.json
run_042.csv: 96 rows, 93 valid, 4 errors, 1 warning

  type_error (2)
    line 14, column "absorbance": value "OVRFLW" is not a valid float
    line 51, column "absorbance": value "n.d." is not a valid float
  less_than_minimum (1)
    line 22, column "temperature (°C)": value -300 is less than minimum -273.15 °C
  duplicate_primary_key (1)
    line 88: well "H12" already appears on line 97
  extra_column (warning) (1)
    column "Notes" does not match any field
```

---

## 13. Packaging and dependencies

### 13.1 Metadata

- Build backend: **hatchling**, configured entirely in `pyproject.toml`.
- `src/` layout.
- Version: single source in `src/labschema/__init__.py` (`__version__`), read by hatch.
- Classifiers: Python 3.10–3.12, `License :: OSI Approved :: MIT License`, `Topic :: Scientific/Engineering`, `Typing :: Typed`.

### 13.2 Dependencies

| Group | Packages | Notes |
|---|---|---|
| core | `pydantic>=2.5,<3`, `pint>=0.23` | Kept minimal. |
| `[pandas]` | `pandas>=2.0` | Enables `to_pandas()`. |
| `[dev]` | `pytest`, `pytest-cov`, `ruff`, `mypy`, `pre-commit`, `pandas` | Contributor tooling. |

### 13.3 Console script

```toml
[project.scripts]
labschema = "labschema.cli:main"
```

---

## 14. Repository layout

```
labschema/
├── .github/
│   ├── workflows/
│   │   ├── ci.yml              # test + lint on PR/push
│   │   └── release.yml         # tag → PyPI (trusted publishing)
│   └── ISSUE_TEMPLATE/
├── docs/
│   └── SPEC.md                 # this document
├── src/
│   └── labschema/
│       ├── __init__.py
│       ├── __main__.py         # python -m labschema
│       ├── py.typed
│       ├── fields.py
│       ├── schema.py
│       ├── units.py            # pint wrapper + lab aliases
│       ├── validate.py
│       ├── errors.py           # ErrorCode, ValidationIssue, exceptions
│       ├── infer.py            # draft schema from sample
│       ├── io/
│       │   ├── __init__.py
│       │   ├── csv.py
│       │   └── jsonschema.py
│       └── cli.py
├── tests/
│   ├── test_fields.py
│   ├── test_schema.py
│   ├── test_units.py
│   ├── test_validation.py
│   ├── test_io_csv.py
│   ├── test_infer.py
│   ├── test_export.py
│   ├── test_cli.py
│   └── fixtures/               # tiny real-looking CSVs + expected reports
├── .pre-commit-config.yaml
├── pyproject.toml
├── README.md
├── CHANGELOG.md
├── CONTRIBUTING.md
├── CODE_OF_CONDUCT.md
├── SECURITY.md
└── LICENSE                     # MIT
```

---

## 15. Testing strategy

### 15.1 Unit tests

- Field coercion for `int`, `float`, `str`, `bool`; nullable and default rules.
- Construction-time `SchemaError` cases (§5.1).
- Header unit parsing, aliases, and conversions — including offset units (°C ↔ K ↔ °F) and incompatible dimensions.
- Locale decimals and thousands separators.
- Each error code in §8.3 has at least one test that triggers it.
- Error messages are snapshot-tested for stability.
- Inference: header regex → expected `Field` list; dtype ladder edge cases.

### 15.2 Integration tests

- **Golden files**: each invalid fixture in `tests/fixtures/` has a matching `*.expected.json` report; tests compare codes, rows, and counts.
- **Round-trip**: `schema → to_json → from_json` equals the original; `to_json_schema()` validates against the draft 2020-12 meta-schema.
- **CLI**: exit codes `0` / `1` / `2`; `--format json` output parses and matches the report.
- **pandas extra**: `to_pandas()` dtypes and `attrs`; a test runs without pandas installed to check the `ImportError` hint.

### 15.3 Coverage and benchmarks

- `pytest --cov=labschema --cov-fail-under=90`, gating on `schema`, `fields`, `validate`, and `units`.
- A non-gating benchmark validates a 10,000-row × 10-column fixture and reports wall time (target in §17).

---

## 16. CI/CD and release process

### 16.1 CI (`ci.yml`) — on push and pull request

| Job | Details |
|---|---|
| Lint | `ruff check` and `ruff format --check`. |
| Type check | `mypy --strict src/`. |
| Test matrix | Python 3.10, 3.11, 3.12 × `ubuntu-latest`, `macos-latest`; `pytest --cov --cov-fail-under=90`. |
| Minimal install | Install without extras and run the non-pandas test subset. |
| Build | `python -m build`, then `twine check dist/*`. |

### 16.2 Release (`release.yml`) — on tag `v*`

1. Build sdist and wheel.
2. Publish to PyPI using `pypa/gh-action-pypi-publish` with **OIDC trusted publishing** (no long-lived API tokens).
3. Create a GitHub Release with the CHANGELOG section and an install snippet.

### 16.3 Versioning

[Semantic Versioning](https://semver.org/). While in `0.x`, minor versions MAY contain breaking changes, but they MUST be listed in the CHANGELOG under **Breaking**.

### 16.4 Release checklist

- [ ] Update `CHANGELOG.md` (Keep a Changelog format).
- [ ] Bump `__version__`.
- [ ] Tag `vX.Y.Z`; confirm the release workflow publishes wheel and sdist.
- [ ] Publish the GitHub Release notes.
- [ ] Smoke test: `pip install labschema==X.Y.Z` in a clean venv and run `labschema --version` plus one `validate`.

---

## 17. Non-functional requirements

| ID | Requirement |
|---|---|
| NFR1 | **Performance:** validate a 10k-row × 10-column CSV in < 2 s on a typical laptop. |
| NFR2 | **Memory:** reading is streaming; memory is O(valid records) and does not hold the raw file. |
| NFR3 | **Install:** core install (`pip install labschema`) completes in < 30 s in a clean environment and pulls no pandas/numpy beyond what pint requires. |
| NFR4 | **Determinism:** identical input and schema produce byte-identical JSON reports. |
| NFR5 | **Portability:** works on Linux, macOS, and Windows (Windows not in the CI matrix for v0.1, but no POSIX-only code). |
| NFR6 | **Safety:** the library never executes code from data or schema files. `MODULE:ATTR` import in the CLI is an explicit user choice and is documented as executing that module. |
| NFR7 | **Code size:** v0.1 is roughly 1–2k lines of library code. |

---

## 18. Open-source readiness

**README MUST include**

- One-line description and a 30-second code example.
- Install: `pip install labschema` and `pip install "labschema[pandas]"`.
- CLI quickstart.
- Badges: CI status, PyPI version, supported Python versions, license.
- Link to docs (MkDocs Material optional for v0.2).

**Community files**

- `CONTRIBUTING.md` — dev setup, running tests, commit/PR conventions.
- `CODE_OF_CONDUCT.md` — Contributor Covenant.
- `SECURITY.md` — responsible-disclosure contact.
- Issue templates: bug report, feature request.
- `.pre-commit-config.yaml` matching CI (ruff, trailing whitespace, end-of-file).
- Seed "good first issues", e.g. new unit alias, extra header pattern for inference.

---

## 19. Roadmap

### 19.1 Milestones (v0.1, ~4 weeks)

| Week | Milestone | Exit criteria |
|---|---|---|
| 1 | Scaffold & core types | Repo, `pyproject.toml`, `Field`, `TableSchema`, units wrapper, first unit tests; CI running. |
| 2 | Validation & I/O | `read_csv`, validation pipeline, `ValidationReport`, all error codes, golden-file tests. |
| 3 | CLI, inference, docs | `validate` / `infer` / `export-schema`, JSON + JSON Schema export, README, CONTRIBUTING; CI green on full matrix. |
| 4 | Release & polish | Trusted publishing, `v0.1.0` tag, badges, example notebook or docs page, announcement. |

### 19.2 Versions

| Version | Scope |
|---|---|
| **0.1.0** | MVP: CSV/TSV + schema + units + validation + inference + CLI + JSON/JSON Schema export. |
| **0.2.0** | YAML schema sidecars, better inference, fixed-width reader, `date`/`datetime` dtypes, Arrow output, MkDocs site. |
| **1.0.0** | Frozen public API, migration guide from 0.x. |
| Later | Excel/HDF5 readers, multi-table schemas, ontology/ELN hooks. |

---

## 20. Risks and mitigations

| Risk | Mitigation |
|---|---|
| **Scope creep** | v0.1 is locked to CSV/TSV; Excel, YAML, and web UI are explicitly deferred (§2.2). |
| **Unit ambiguity** | Units come only from the schema or the header. Inference suggests, never silently converts unknowns. Ambiguous aliases emit warnings. |
| **PyPI name taken** | Reserve the name early; keep backup names documented (see Q3). |
| **Heavy dependencies** | pandas is an optional extra; core stays at pydantic + pint. |
| **Per-row Pydantic overhead** | Reuse a single `TypeAdapter`; pre-coerce in plain Python; benchmark in CI (NFR1). |
| **pint offset-unit pitfalls** | Dedicated tests for °C/°F conversions and bounds compared after conversion. |

---

## 21. Open questions

| ID | Question | Proposed answer |
|---|---|---|
| Q1 | The plan says "store canonical SI in output", but the API example declares `unit=u.degC`. Which wins? | Output uses the field's declared unit; SI is opt-in via `schema.to_base_units()`. |
| Q2 | Typer or argparse for the CLI? | argparse — no extra dependency; revisit if the CLI grows. |
| Q3 | Final package name? | `labschema` if available on PyPI and GitHub; otherwise pick from a documented backup list. |
| Q4 | Should rows with errors be available to the caller? | Not in v0.1; consider `result.invalid_rows` in v0.2. |
| Q5 | Support Python 3.13 in the matrix? | Add once pint and pydantic wheels are confirmed; does not block v0.1. |

---

## 22. Glossary

| Term | Meaning |
|---|---|
| **Field** | Specification of one column: name, type, unit, constraints. |
| **Schema** | A `TableSchema`: the ordered set of fields plus table-level rules. |
| **Sentinel** | A cell value that means "missing" (e.g. `NA`, `#DIV/0!`). |
| **Declared unit** | The unit set on a `Field`; values are stored in this unit. |
| **Header unit** | A unit found in a column header, e.g. `[mg/L]`. |
| **Draft schema** | The output of inference, meant for human review before use. |
| **Trusted publishing** | PyPI publishing via GitHub Actions OIDC, without stored API tokens. |
