# Claude Contributor Guidelines for Concurrent Log Handler

This document provides guidance for AI assistants, like Claude, to ensure
contributions to this repository are consistent, high-quality, and align with
the project's design principles.

## 1. Project Philosophy

The core mission of Concurrent Log Handler (CLH) is to **preserve log records
reliably** in multi-process or even multi-host environments (those with shared
filesystems).

- **Reliability over Performance:** Prioritize data integrity and robust file
  locking. Performance optimizations should never come at the cost of losing
  logs, unless explicitly configurable by the user.
- **Simplicity and Compatibility:** Adhere to the standard Python
  `logging.Handler` interface. New features should feel like natural extensions,
  not radical departures.
- **Clarity:** Concurrency logic is complex. Prioritize clear, well-commented
  code over overly clever or obscure implementations.
- **Error handling:** fail loudly in development, gracefully in production.
  
In general, maintaining backwards compatibility is important.

## 2. Development Environment Setup

To begin, set up an editable installation with all development dependencies:

```bash
# (Assuming Python virtual environment already established)
# Install the package in editable mode with dev tools
pip install -e .[dev]
```

## 3. Key Development Commands

### Running Tests

The test suite is the primary tool for verifying correctness, especially across
multiple processes.

```bash
# Run tests on the current Python version
pytest

# Run a specific test file (useful for focused development)
pytest tests/test_shutdown_handling.py

```

Tests across multiple platforms can be performed in the GitHub Actions.

### Code Quality (Linting & Formatting)

Code must be formatted and linted before it is considered complete.

```bash
# Auto-format all code
black .

# Check for linting errors and style issues
ruff check . --fix

# Perform static type checking
mypy --install-types --non-interactive src/concurrent_log_handler

# On Linux-style platforms, this runs all of the above in one script:
./lint.sh
```

### Building the Package

```bash
# Create the source and wheel distributions
hatch build --clean
```

## 4. Core Architecture & Constraints

The package structure is centered around handler classes in
`src/concurrent_log_handler/__init__.py`.

### Key Components

- **`ConcurrentRotatingFileHandler`**: The base class for size-based log
  rotation.
- **`ConcurrentTimedRotatingFileHandler`**: A subclass for time-based rotation.
- **`portalocker`**: The library used for all advisory file locking, which is
  the foundation of multi-process safety.

### Architectural Constraints (Rules to Follow)

- **Handlers are Not Shared:** A handler instance is created **per-process**.
  They are not designed to be serialized or passed between processes. All new
  features must respect this fundamental constraint.
- **File-Based Locking:** Coordination is always managed through a `.lock` file
  on a shared filesystem.
- **Backwards Compatibility:** Changes should not break existing user
  configurations without a clear deprecation path and warning.

## 5. Contribution Guidelines

### Testing Requirements

New features are incomplete without tests. When adding or modifying code, you
**must**:

1. **Add or Update Tests:** Cover your new code paths and edge cases.
2. **Verify Multi-Process Safety:** If your change touches file I/O or locking,
   it must be verified in a multi-process stress test. This is the library's
   most critical feature.
3. **Run the Full Suite:** Run `pytest` to ensure your changes work. It's also
    important that all changes work (or at least degrade gracefully) on all
    supported Python versions, currently 3.6 and higher, and don't cause
    regressions, including in the test execution.
4. **Generate Coverage Reports:** Aim to maintain or increase test coverage.
    Coverage of the main classes is currently at about ~70% and we would like
    new code to adhere to similar numbers. Completely exhaustive coverage of
    every single code path is not necessary.

    ```bash
    pytest --cov=src/concurrent_log_handler --cov-report=term-missing
    ```

### Coding Style

- Use modern Python features and f-strings.
- Type hints are required for all new functions and methods.
    - Type hints must be compatible with Python 3.6 usage for now.
- Follow the existing code's style for comments and structure. Docstrings should
  explain the "why," while code comments explain the "how" of complex sections.
- Do not introduce new external dependencies without very explicit
  authorization.

