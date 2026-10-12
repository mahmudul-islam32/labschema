# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 0.1.x   | :white_check_mark: |

## Reporting a Vulnerability

If you discover a security vulnerability in LabSchema, please report it responsibly:

1. **Do not** open a public GitHub issue for security vulnerabilities.

2. Send an email to [INSERT SECURITY EMAIL] with:
   - A description of the vulnerability
   - Steps to reproduce
   - Potential impact
   - Any suggested fixes (optional)

3. You should receive a response within 48 hours acknowledging your report.

4. We will work with you to understand and resolve the issue quickly.

## Security Considerations

### Code Execution

LabSchema is designed to process data files and schema definitions. By design:

- **Schema files** (JSON) are parsed as data, not executed
- **Data files** (CSV/TSV) are parsed as data, not executed
- **Custom validators** in Python schemas execute user-provided callables

The `MODULE:ATTR` syntax in the CLI allows loading Python modules. This is documented behavior that executes the specified module. Users should only load trusted modules.

### Data Handling

- LabSchema processes files in memory
- No data is transmitted over networks
- No external services are contacted
- File paths provided by users are used as-is

## Best Practices

When using LabSchema:

1. Only load schemas from trusted sources
2. When using the `MODULE:ATTR` CLI syntax, only reference trusted Python modules
3. Review custom validators before using schemas from others
4. Keep LabSchema and its dependencies up to date
