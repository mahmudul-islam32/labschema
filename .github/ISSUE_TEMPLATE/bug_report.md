---
name: Bug Report
about: Report a bug in LabSchema
title: "[BUG] "
labels: bug
assignees: ''
---

## Description

A clear and concise description of the bug.

## To Reproduce

Steps to reproduce the behavior:

1. Create a schema with '...'
2. Read CSV file '...'
3. See error

## Expected Behavior

A clear and concise description of what you expected to happen.

## Actual Behavior

What actually happened, including any error messages or tracebacks.

## Environment

- OS: [e.g., Ubuntu 22.04, macOS 14, Windows 11]
- Python version: [e.g., 3.11.5]
- LabSchema version: [e.g., 0.1.0]

## Minimal Example

```python
# Paste a minimal code example that reproduces the issue
from labschema import TableSchema, Field
from labschema.io import read_csv

schema = TableSchema(
    name="example",
    fields=[...]
)

# What you tried
result = read_csv("data.csv", schema)
```

## Sample Data

If applicable, paste a small sample of the CSV/TSV data that triggers the issue:

```csv
column1,column2
value1,value2
```

## Additional Context

Add any other context about the problem here.
