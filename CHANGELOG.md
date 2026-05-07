# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.5] - 2026-05-07

### Added

- Runtime configuration and shared CLI options (Story A.g):
  - `src/datarefinery/core/config.py` defines a frozen pydantic
    `RuntimeConfig` with `cache_root`, `log_level`, `log_target`,
    `plugin_path`, `workers` and a `resolve()` classmethod implementing
    the documented CLI > env > default precedence (env mapping
    overridable for testing). `DATAREFINERY_PLUGIN_PATH` is split on
    `os.pathsep` (POSIX `:`).
  - `cli/app.py` adds shared options at the root callback:
    `--cache-root`, `--log-level`, `--log-target`,
    `--plugin-path` (repeatable), `--workers`, `--seed`, `--variant`,
    `--no-color`, `--quiet`, `--verbose`. The callback builds a
    `RuntimeConfig` and stashes it on the typer `Context` for downstream
    commands.
  - `tests/unit/test_config.py` covers env-only, CLI-only, both
    (CLI wins), partial overrides, empty-string env, PATH-style splitting,
    `frozen=True`, and `extra="forbid"`.

## [0.1.4] - 2026-05-07

### Added

- Error hierarchy and CLI exit-code mapping (Story A.f):
  - `src/datarefinery/core/errors.py` defines `DataRefineryError` plus
    `RecipeError`, `ValidationError`, `PluginError`, `ContractError`,
    `MaterializeError`, `CacheError`.
  - `src/datarefinery/cli/_exit_codes.py` exposes `EXIT_OK`, `EXIT_USER`,
    `EXIT_SYSTEM`, `EXIT_INTERRUPT` and `exit_code_for(exc)` mapping per
    tech-spec (user 1 / system 2 / SIGINT 130).
  - `cli/app.py` adds `main_entry()` that runs the typer app with
    `standalone_mode=False`, catches `DataRefineryError` and
    `KeyboardInterrupt`, renders a `rich` error panel on stderr, and exits
    with the mapped code; uncaught exceptions exit 2.
  - Console script (`pyproject.toml`) and `__main__.py` now route through
    `main_entry`.

### Tests

- `tests/unit/test_errors.py` — exhaustive subclass and exit-code mapping.
- `tests/cli/test_exit_codes.py` — subprocess tests asserting each error
  class produces the documented exit code through `main_entry`, plus
  `KeyboardInterrupt → 130`, uncaught `RuntimeError → 2`, and that
  `--help` / `--version` still exit 0.

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
