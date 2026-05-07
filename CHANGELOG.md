# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.3] - 2026-05-07

### Added

- Logging foundation (Story A.e):
  - `src/datarefinery/logging.py` exposes `JsonFormatter` (single-line JSON
    with `ts`, `level`, `logger`, `stage`, `op_id`, `message`, plus an
    `extras` bucket for non-reserved record attributes) and `get_logger`
    helper that idempotently attaches a `NullHandler` and a
    `JsonFormatter` `StreamHandler(stderr)` to the `datarefinery` package
    logger. Importing the module does not touch root logging.
  - CLI startup in `cli/app.py` now initializes the package logger via
    `get_logger("cli")`. `--log-target` is accepted as a reserved no-op
    stub; full routing lands in Story A.g.
  - `tests/unit/test_logging.py` covers single-line JSON shape, required
    fields, `extras` round-trip, and the no-root-handler invariant.

## [0.0.2] - 2026-05-06

### Added

- Hello-world Typer CLI (Story A.b):
  - `src/datarefinery/cli/app.py` exposes a `Typer` app with `--version` and `--help`; `--version` reads `datarefinery.__version__`.
  - `src/datarefinery/__main__.py` so `python -m datarefinery` invokes the CLI.
  - `tests/cli/test_smoke.py` smoke tests asserting `--version` and `--help` exit 0 and surface the package version.

## [0.0.1] - 2026-05-06

### Added

- Initial project scaffolding (Story A.a):
  - Apache-2.0 `LICENSE`.
  - `pyproject.toml` with hatchling backend, runtime dependencies, optional `[llm]` extra, console script, plugin entry-point group, and ruff / mypy / pytest configuration.
  - `requirements-dev.txt` listing the dev tool pinset for the pyve testenv.
  - `src/datarefinery/` package with `__version__` and PEP 561 `py.typed` marker.
  - `tests/` skeleton (`conftest.py` plus `unit/`, `integration/`, `cli/`, `plugin_contract/`, `fixtures/` subdirectories).
  - `README.md` with project tagline, install snippet, and one-line usage example.
  - `.gitignore` covering Python, pyve, build artifacts, and `data/`.
  - `environment.yml` for the pyve micromamba environment (Python 3.12.x).
