# Commit note — M0 Scaffold & project contract

## Commit message

```
M0: package scaffold, claimverifier CLI, and environment self-check

Add the runnable Python package for the project:
- pyproject.toml (src/ layout, console script, pydantic-only runtime dep,
  pytest+ruff config; version from __init__)
- scientific_claim_verifier: __init__, cli (check-env/version), envcheck,
  schemas stub
- scripts/00_check_environment.py (offline env check)
- tests/ (13 CPU-only offline tests)
Update website (index + milestones) to mark M0 done; add milestone/commit/
review notes.
```

## What this commit adds

- A dependency-light, installable package (`scientific_claim_verifier`) and the
  `claimverifier` console script with `check-env` and `version`.
- An offline environment self-check reused by both the script and the CLI.
- The first CPU-only, offline test suite (13 tests) and lint/test configuration.
- Website status updates (M0 → done) and the M0 milestone/commit/review docs.

## Deliberately excluded (per the operating principles)

- Typed data models / enums — these are **M1**; `schemas.py` is a documented stub.
- Fixtures, extractors, checks, sandbox, scoring, reports, adapters — later
  milestones.
- numpy/pandas/scipy/matplotlib as hard dependencies — added when first used.
- Any network access, paid-API path, or editable-install requirement in tests.

## Verification performed at commit time

- `python3 -m pytest -q` → 13 passed.
- `ruff check .` → all checks passed.
- `python3 scripts/00_check_environment.py` → exit 0 (`READY`).
- Static site served locally on port 9002; all 11 pages returned HTTP 200 via
  Python's `urllib` (no `curl`/`wget`, per the permission policy).
- `git status` clean after commit.
