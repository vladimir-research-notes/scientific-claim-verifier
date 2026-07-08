# M0 — Scaffold & project contract

## Summary

Establishes a runnable, dependency-light Python package for the project. Before
this milestone the repository contained only the orchestration/contract layer
(`CLAUDE.md`, `docs/PLAN.md`, prompts, milestone runner, website skeleton). M0
turns that contract into installable, testable code: the
`scientific_claim_verifier` package, the `claimverifier` console script, an
offline environment self-check, and the first CPU-only test suite.

No verification logic yet — that lands milestone by milestone (schemas in M1,
fixtures in M2, and so on). M0 deliberately implements only the scaffold.

## Deliverables

- **`pyproject.toml`** — `src/` layout via setuptools; package
  `scientific_claim_verifier`; console script `claimverifier`; version sourced
  from `__init__.__version__`; sole runtime dependency `pydantic>=2`; `dev`
  extra (`pytest`, `ruff`); pytest configured with `pythonpath = ["src"]` so
  tests run without an install; ruff config (`E,F,I,W,UP,B`, line length 100).
- **`src/scientific_claim_verifier/__init__.py`** — package marker, `__version__ = "0.1.0"`.
- **`src/scientific_claim_verifier/schemas.py`** — intentional stub. Documents
  the typed model coming in M1 and keeps the package import-light (no `pydantic`
  import until the models exist). Exposes `SCHEMA_VERSION`.
- **`src/scientific_claim_verifier/envcheck.py`** — offline environment check:
  interpreter version/floor, platform, and required/optional library
  availability. Returns a structured `EnvReport`; `run()` prints and returns an
  exit code.
- **`src/scientific_claim_verifier/cli.py`** — argparse CLI (`claimverifier`)
  with `check-env`, `version`, and a `--version` flag. Verification subcommands
  are intentionally *not* registered yet, so an unimplemented verb fails loudly.
- **`scripts/00_check_environment.py`** — runs the env check from a source
  checkout (bootstraps `src/` onto `sys.path`) or via the console script.
- **`tests/`** — `test_package.py`, `test_envcheck.py`, `test_cli.py`
  (13 tests): package import/version, schema stub, env-check readiness, CLI
  commands, and that unknown verbs error.

## Validation

Commands run (CPU-only, offline):

| Command | Result |
| --- | --- |
| `python3 -m pytest -q` | 13 passed |
| `ruff check .` | All checks passed |
| `python3 scripts/00_check_environment.py` | exit 0 — `READY` |
| `claimverifier version` (via module) | prints `0.1.0` |
| Site served on :9002, 11 pages fetched via `urllib` | all HTTP 200 |

## Notes / decisions

- **argparse over typer.** `typer` is not installed and would add a dependency;
  `CLAUDE.md` permits "typer or argparse". argparse keeps the CLI stdlib-only
  and the baseline dependency-light and installable offline.
- **Single runtime dependency (`pydantic`).** numpy/pandas/scipy/matplotlib are
  declared *in the env report as optional* and added in the milestones that
  first need them, rather than front-loaded. The env check reports them as
  informational, never failing when absent.
- **`schemas.py` is a deliberate stub.** Implementing the typed models here
  would overreach into M1. The stub records what is coming and avoids importing
  `pydantic` until the models land.
- **Tests run without install** via pytest's `pythonpath = ["src"]`, satisfying
  the "offline, free" test contract without an editable install step.
- **Unimplemented CLI verbs are unregistered on purpose** so they error rather
  than silently no-op — honesty over a friendly stub.

## Status

**Complete.** Next: **M1 — Core schemas** (typed `pydantic` models and their
vocabularies, with unit tests).
