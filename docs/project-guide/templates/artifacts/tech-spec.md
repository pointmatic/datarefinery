# tech-spec.md -- {{project_name}} ({{programming_language}})

This document defines **how** the `{{project_name}}` project is built -- architecture, module layout, dependencies, data models, API signatures, and cross-cutting concerns.

For requirements and behavior, see [`features.md`](features.md). For the implementation plan, see [`stories.md`](stories.md). For project-specific must-know facts (workflow rules, architecture quirks, hidden coupling), see [`project-essentials.md`](project-essentials.md) — `plan_tech_spec` populates it after this document is approved. For the workflow steps tailored to the current mode (cycle steps, approval gates, conventions), see [`docs/project-guide/go.md`](../project-guide/go.md) — re-read it whenever the mode changes or after context compaction.

---

## Runtime & Tooling

{{runtime_and_tooling}}

---

## Dependencies

{{dependencies}}

---

## Package Structure

{{package_structure}}

---

## Filename Conventions

{{filename_conventions}}

---

## Key Component Design

{{key_components}}

---

## Data Models

{{data_models}}

---

## Configuration

{{configuration}}

---

## CLI Design

{{cli_design}}

---

## Cross-Cutting Concerns

### Logging and User Output

This project uses two-channel output discipline:

- **User-facing output** — `rich` (Python) / `chalk` / `pterm` / `console`. CLI output, progress bars, tables, colored hints, error messages humans read in their terminal. Lives on stdout/stderr.
- **Operator logs** — stdlib `logging` (Python, with JSON formatter) / `pino` / `slog` / `tracing`. Structured, filterable, level-tagged events for log aggregation, monitoring, and post-hoc debugging.

Warnings and operational concerns ("stage X took longer than expected", "fell back to slower path", "retried 3 times") go to the **operator-log** channel — even when the message *feels* user-facing. If downstream tooling can't filter or alert on it, it's useless. Errors that block the user go on both channels: human-readable stderr message *and* structured log entry.

See `docs/project-guide/developer/best-practices-guide.md` for full rationale.

### Additional Cross-Cutting Concerns

{{cross_cutting}}

---

## Performance Implementation

{{performance_implementation}}

---

## Testing Strategy

{{testing_strategy}}

---

## Packaging and Distribution

{{packaging_and_distribution}}

---

## CI/CD Automation

One-line summary of CI/CD scope (linting/testing on push, coverage reporting, automated registry publishing on tag). `plan_stories` reads this section as the single source of truth for whether to include a Phase G (CI/CD & Automation) in the story plan. If the project explicitly opts out of CI/CD, write "None" here.

{{ci_cd_automation}}
