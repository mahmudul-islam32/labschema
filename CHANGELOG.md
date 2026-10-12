# Changelog

All notable changes to LabSchema will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-10-09

### Added

- Initial release of LabSchema
- `Field` class for defining column specifications with:
  - Data types: `int`, `float`, `str`, `bool`
  - Physical units via Pint integration
  - Nullability and default values
  - Constraints: `ge`, `gt`, `le`, `lt`, `enum`, `pattern`
  - Custom validators
  - Aliases for flexible header matching
- `TableSchema` class for defining table schemas with:
  - Ordered field definitions
  - Primary key constraints
  - Extra columns policy (ignore/warn/error)
  - Metadata support
  - JSON serialization (round-trippable)
  - JSON Schema export (draft 2020-12)
- Unit handling:
  - Shared Pint registry with lab-specific aliases
  - Header unit parsing from `[brackets]` and `(parentheses)`
  - Automatic unit conversion
  - Temperature offset handling
- Validation engine:
  - Comprehensive error codes with stable identifiers
  - Row and cell-level validation
  - Primary key uniqueness checking
  - Detailed ValidationReport with grouping and summaries
- I/O support:
  - `read_csv()` for CSV files
  - `read_tsv()` for TSV files  
  - `read_text()` for in-memory strings
  - Delimiter auto-detection
  - Locale-aware decimal/thousands separators
  - Configurable missing value sentinels
  - Skip rows and comment lines
- Schema inference:
  - `infer_schema()` for generating draft schemas from data
  - Type inference (bool → int → float → str)
  - Unit extraction from headers
  - Nullable detection
  - Python source code export
- Command-line interface:
  - `labschema validate` - Validate data files against schemas
  - `labschema infer` - Infer schemas from data files
  - `labschema export-schema` - Export schemas to JSON/JSON Schema
  - JSON and text output formats
  - Exit codes for CI integration
- pandas integration (optional):
  - `to_pandas()` method on ValidationResult
  - Unit metadata in DataFrame attrs

### Fixed

- A header unit of `C` is read as degrees Celsius (with a `unit_ambiguous` warning) and converted as an absolute temperature.
- Header text that looks like a unit but cannot be parsed raises `unit_unknown`, and that column is skipped.
- Custom validators may replace the cell value they accept.
- `TableSchema.to_base_units()` converts bounds, numeric defaults, and numeric enum values into the base unit.
- CSV and TSV reads stream rows. Comment lines and skipped preambles keep the original file line numbers.
- `set_registry()` can install a Pint registry before the first unit operation.

### Dependencies

- pydantic >= 2.5
- pint >= 0.23
- pandas >= 2.0 (optional)

[Unreleased]: https://github.com/mahmudul-islam32/labschema/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/mahmudul-islam32/labschema/releases/tag/v0.1.0
