# Contributing to kiln-controller

Thank you for your interest in contributing to kiln-controller! This document outlines how to set up your development environment, run tests, and contribute code.

## Development Setup

The project uses [uv](https://docs.astral.sh/uv/) for dependency management with `pyproject.toml`. While `uv` is recommended, you can also use a standard `pip` + `venv` workflow.

### Using uv (recommended)

1. Install [uv](https://docs.astral.sh/uv/getting-started/installation/).
2. Clone the repository:
   ```bash
   git clone https://github.com/jbruce12000/kiln-controller
   cd kiln-controller
   ```
3. Set up the development environment:
   ```bash
   make dev-setup
   ```
   This creates a virtual environment in `venv/` and installs all dependencies (including dev dependencies). The project is installed in editable mode.

4. Activate the virtual environment if needed (uv commands like `uv run` work without activation, but for direct python commands):
   ```bash
   source venv/bin/activate
   ```

### Using pip + venv (alternative)

1. Clone and enter the repository:
   ```bash
   git clone https://github.com/jbruce12000/kiln-controller
   cd kiln-controller
   ```
2. Create and activate a virtual environment:
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   ```
3. Install in editable mode with all dependencies:
   ```bash
   pip install -e ".[dev]"  # or pip install -e . and then pip install pytest ruff black tomli
   ```

## Running Tests

Tests are located in the `Test/` directory and use pytest. With uv:

```bash
make test
# or
uv run pytest Test -q
```

With venv activated:
```bash
pytest Test -q
```

## Linting and Code Style

We use [ruff](https://docs.astral.sh/ruff/) for linting. Formatters like black are available as dev dependencies. Run linting with:

```bash
make lint
# or
uv run ruff check .
```

## Makefile Targets

- `make dev-setup` - Set up the development environment with uv
- `make test` - Run the test suite
- `make lint` - Run linting checks

## Dependencies

- Runtime dependencies are defined in `pyproject.toml` under `[project.dependencies]`
- Development dependencies are defined under `[dependency-groups.dev]`
- The full dependency tree is locked in `uv.lock` for reproducibility
- Python 3.11+ is required. Note: 3.11 and 3.12 are the tested versions —
  `lgpio` (via `rpi-lgpio`) only ships wheels for those, so Python 3.13+
  currently fails to install unless you build `lgpio` from source (requires `swig`).

## Submitting Changes

1. Fork the repository and create a feature branch
2. Make your changes, ensuring tests still pass and linting is clean
3. Submit a pull request with a clear description of your changes

## Questions?

Feel free to open an issue if you have questions about contributing!
