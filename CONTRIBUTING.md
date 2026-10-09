# Contributing to LabSchema

Thank you for your interest in contributing to LabSchema! This document provides guidelines for contributing.

## Development Setup

1. Clone the repository:
```bash
git clone https://github.com/labschema/labschema.git
cd labschema
```

2. Create a virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install development dependencies:
```bash
pip install -e ".[dev]"
```

4. Install pre-commit hooks:
```bash
pre-commit install
```

## Running Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=labschema --cov-report=html

# Run specific test file
pytest tests/test_validation.py

# Run with verbose output
pytest -v
```

## Code Quality

### Linting

We use [Ruff](https://github.com/astral-sh/ruff) for linting and formatting:

```bash
# Check for linting issues
ruff check src/ tests/

# Auto-fix linting issues
ruff check --fix src/ tests/

# Check formatting
ruff format --check src/ tests/

# Auto-format
ruff format src/ tests/
```

### Type Checking

We use [mypy](https://mypy.readthedocs.io/) for type checking:

```bash
mypy --strict src/
```

## Pull Request Process

1. **Fork** the repository and create your branch from `main`.

2. **Make your changes** following the code style guidelines.

3. **Add tests** for any new functionality or bug fixes.

4. **Update documentation** if needed.

5. **Run the full test suite** to ensure all tests pass:
```bash
pytest
ruff check src/ tests/
mypy --strict src/
```

6. **Submit a pull request** with a clear description of the changes.

## Commit Messages

Use clear, descriptive commit messages:

- `feat: add support for YAML schema files`
- `fix: handle BOM in UTF-8 files correctly`
- `docs: update README with CLI examples`
- `test: add tests for unit conversion edge cases`
- `refactor: simplify validation pipeline`

## Code Style Guidelines

- Follow PEP 8 with a line length of 100 characters
- Use type hints for all public APIs
- Write docstrings for all public functions and classes
- Keep functions focused and single-purpose
- Prefer descriptive variable names

## Adding New Features

Before starting work on a new feature:

1. Check existing issues and pull requests to avoid duplication
2. Open an issue to discuss the feature with maintainers
3. Get feedback on the design before implementation

## Reporting Bugs

When reporting bugs, please include:

- Python version
- LabSchema version
- Operating system
- Minimal code example to reproduce the issue
- Expected behavior
- Actual behavior
- Full error traceback if applicable

## Good First Issues

Look for issues labeled `good first issue` if you're new to the project. These are typically:

- Adding new unit aliases
- Improving error messages
- Adding test cases
- Documentation improvements

## Questions?

If you have questions, feel free to:

- Open a GitHub issue
- Start a discussion in GitHub Discussions

Thank you for contributing!
