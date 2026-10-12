# LabSchema

[![CI](https://github.com/mahmudul-islam32/labschema/actions/workflows/ci.yml/badge.svg)](https://github.com/mahmudul-islam32/labschema/actions/workflows/ci.yml)
[![PyPI version](https://img.shields.io/pypi/v/labschema.svg)](https://pypi.org/project/labschema/)
[![Python versions](https://img.shields.io/pypi/pyversions/labschema.svg)](https://pypi.org/project/labschema/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**LabSchema** is a Python library that turns messy lab-style tables (CSV, TSV) into **typed schemas with physical units and validation**.

## Features

- **Declarative schemas** — Define column names, types, units, and constraints once
- **Physical units** — Parse units from headers and convert values automatically via [Pint](https://pint.readthedocs.io/)
- **Comprehensive validation** — Get detailed error reports with row, column, and error codes
- **Schema inference** — Generate draft schemas from your data files
- **Multiple exports** — Export schemas as JSON or JSON Schema (draft 2020-12)
- **CLI included** — Validate files, infer schemas, and export from the command line

The full contract is in [docs/SPEC.md](docs/SPEC.md).

## Installation

```bash
pip install labschema
```

For pandas DataFrame support:

```bash
pip install "labschema[pandas]"
```

## Quick Start

### 30-Second Example

```python
from labschema import TableSchema, Field, u
from labschema.io import read_csv

# Define your schema
schema = TableSchema(
    name="plate_reader_run",
    primary_key=("well",),
    fields=[
        Field("well", str, pattern=r"^[A-H](?:[1-9]|1[0-2])$"),
        Field("absorbance", float, unit=u.dimensionless, ge=0),
        Field("temperature", float, unit=u.degC, ge=-273.15),
    ],
)

# Validate your data
result = read_csv("run_042.csv", schema=schema)

if not result.ok:
    result.report.print_summary()
else:
    df = result.to_pandas()  # Requires labschema[pandas]
    print(f"Loaded {len(df)} valid rows")
```

### Sample Output

```
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

## CLI Usage

### Validate a file

```bash
labschema validate data.csv --schema schema.json
```

### Infer a schema from data

```bash
labschema infer data.csv --name my_schema -o schema.json
```

### Export to JSON Schema

```bash
labschema export-schema schema.json --format jsonschema -o schema.jsonschema
```

`--schema` accepts a LabSchema JSON file or a Python import path such as `myproj.schemas:plate_run`. An import path loads and executes that module; only point it at code you trust.

Exit codes: `0` when the data is valid (warnings are allowed unless `--strict`), `1` when validation finds errors, `2` for usage errors, unreadable files, or an invalid schema.

### Options

```bash
labschema validate --help
labschema infer --help
labschema export-schema --help
```

## Schema Definition

### Fields

```python
from labschema import Field, u

# Basic string field
Field("name", str)

# Numeric with unit and bounds
Field("temperature", float, unit=u.degC, ge=-273.15)

# Nullable field
Field("notes", str, nullable=True)

# Field with enum constraint
Field("status", str, enum=["active", "inactive", "pending"])

# Field with regex pattern (full match)
Field("well", str, pattern=r"^[A-H](?:[1-9]|1[0-2])$")

# Field with default value
Field("replicate", int, default=1)

# Field with custom validator
def positive(value):
    if value <= 0:
        raise ValueError("Must be positive")
    return value

Field("count", int, validators=[positive])
```

### TableSchema

```python
from labschema import TableSchema, Field, u

schema = TableSchema(
    name="experiment_data",
    version="1.0",
    description="Data from plate reader experiments",
    primary_key=("sample_id", "replicate"),
    extra_columns="warn",  # "ignore", "warn", or "error"
    fields=[
        Field("sample_id", str),
        Field("replicate", int, ge=1),
        Field("absorbance", float, unit=u.dimensionless, ge=0),
        Field("concentration", float, unit="mg/L", nullable=True),
    ],
    metadata={
        "instrument": "Synergy H1",
        "protocol": "Standard absorbance",
    },
)
```

## Units

LabSchema uses [Pint](https://pint.readthedocs.io/) for unit handling. Units can be specified in:

- Field definitions: `Field("temp", float, unit=u.degC)`
- Column headers: `temperature (°C)`, `concentration [mg/L]`

### Supported Aliases

| Input | Resolves to |
|-------|-------------|
| `°C`, `degC` | degree_Celsius |
| `µL`, `μL`, `uL` | microliter |
| `%` | percent |
| `a.u.`, `AU`, `RFU`, `OD` | dimensionless |
| `rpm` | revolutions_per_minute |
| `M` | mol/L |

### Unit Conversion

Values are automatically converted from header units to field units:

```python
# Field declares liters
Field("volume", float, unit="L")

# CSV header has milliliters
# volume [mL]
# 1000

# Result: volume = 1.0 (converted to liters)
```

Values are stored in the field's declared unit. `schema.to_base_units()` returns a copy whose units, bounds, and numeric defaults are the SI base equivalents. Offset temperatures (°C, °F) convert as absolute temperatures.

Call `labschema.units.set_registry(reg)` before any other LabSchema operation to use your own Pint registry. Mixing units from two registries raises `SchemaError`.

## Validation

### Error Codes

| Code | Description |
|------|-------------|
| `missing_column` | Schema field has no matching header |
| `extra_column` | Header matches no field |
| `duplicate_column` | Multiple headers map to one field |
| `unit_incompatible` | Header unit incompatible with field unit |
| `row_length_mismatch` | Wrong number of cells in row |
| `null_not_allowed` | Missing value in non-nullable field |
| `type_error` | Value cannot be coerced to dtype |
| `less_than_minimum` | Violates ge/gt constraint |
| `greater_than_maximum` | Violates le/lt constraint |
| `not_in_enum` | Value not in enum |
| `pattern_mismatch` | String doesn't match pattern |
| `duplicate_primary_key` | Primary key already seen |
| `unit_unknown` | Header unit looks like a unit but cannot be parsed |
| `unit_unexpected` | Header has a unit and the field declares none |
| `unit_ambiguous` | Ambiguous header unit resolved by convention (`C` means °C) |
| `custom_validator` | A custom validator raised `ValueError` |
| `parse_error` | Malformed CSV |

### Accessing Results

```python
result = read_csv("data.csv", schema=schema)

# Check if valid
if result.ok:
    print("All data is valid!")

# Get valid records
records = result.to_records()

# Get as DataFrame (requires pandas)
df = result.to_pandas()

# Inspect errors
for error in result.errors:
    print(f"{error.code}: {error.message}")

# Get detailed report
result.report.print_summary()

# JSON output
print(result.report.to_json())
```

## Schema Inference

```python
from labschema import infer_schema

# Infer from file
schema = infer_schema("data.csv", sample_rows=100, name="my_data")

# Save as JSON
schema.save("schema.json")

# Or get as Python code for editing
from labschema.infer import schema_to_python
print(schema_to_python(schema))
```

## Export Formats

### LabSchema JSON (round-trippable)

```python
# Save
schema.save("schema.json")

# Load
schema = TableSchema.load("schema.json")
```

### JSON Schema (draft 2020-12)

```python
json_schema = schema.to_json_schema()
```

## Reader Options

```python
result = read_csv(
    "data.csv",
    schema=schema,
    delimiter=";",           # Auto-detected if not specified
    decimal=",",             # European decimal separator
    thousands=" ",           # Thousands separator to strip
    encoding="utf-8-sig",    # Handles BOM
    skip_rows=2,             # Skip preamble lines
    comment="#",             # Ignore comment lines
    na_values=["NA", "-"],   # Custom missing values
    max_errors=100,          # Stop after N errors
)
```

## Development

```bash
# Clone the repository
git clone https://github.com/mahmudul-islam32/labschema.git
cd labschema

# Install development dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Run linting
ruff check src/ tests/
ruff format --check src/ tests/

# Type checking
mypy --strict src/
```

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

## License

MIT License. See [LICENSE](LICENSE) for details.
