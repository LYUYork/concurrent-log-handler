# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Concurrent Log Handler (CLH) is a Python logging handler that enables multiple processes and threads to safely write to
the same log file with rotation capabilities. It provides `ConcurrentRotatingFileHandler` (size-based rotation) and
`ConcurrentTimedRotatingFileHandler` (time-based rotation).

## Essential Commands

### Testing

```bash
# Run tests on current Python version
pytest

# Run specific test file
pytest tests/test_stresstest.py

# Generate coverage report
pytest --cov --cov-report=html --cov-report=xml --cov-report=lcov --cov-report=term-missing

# Run tests across all supported Python versions
hatch test
```

### Linting and Formatting

```bash
# Format code
black .

# Check for problems
ruff check .

# Type checking
mypy --install-types --non-interactive src/concurrent_log_handler
```

### Building

```bash
# Development installation
pip install -e .[dev]

# Build distribution
hatch build --clean
```

## Architecture

The package structure centers around two main handler classes in `src/concurrent_log_handler/__init__.py`:

1. **ConcurrentRotatingFileHandler**: Handles size-based log rotation with multi-process safety using file locks (via
   `portalocker`)
2. **ConcurrentTimedRotatingFileHandler**: Adds time-based rotation capabilities on top of size-based rotation

Key architectural decisions:

- Each process must create its own handler instance (handlers cannot be shared/serialized)
- Uses advisory file locking for process coordination
- Lock files can be placed in a separate directory via `lockfile_dir` parameter
- The `queue.py` module is deprecated and should not be used

## Testing Strategy

The test suite in `tests/` includes:

- Stress tests that verify multi-process safety with various configurations
- Tests for both `keep_file_open=True` and `False` modes
- Edge case testing for timed rotation
- Failure scenario testing

When adding new features, ensure tests cover multi-process scenarios as this is the core use case.
