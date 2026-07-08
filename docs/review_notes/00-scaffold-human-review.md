Human review: M0 — Scaffold & project contract

TL;DR
Milestone 0 adds the runnable Python package scaffold: pyproject.toml (src/
layout, `claimverifier` console script, pydantic-only runtime dependency),
the `scientific_claim_verifier` package (__init__, cli, envcheck, schemas
stub), an offline environment self-check script, and 13 CPU-only tests. No
verification logic yet — that lands in later milestones. Website and docs
updated to mark M0 done.

What changed
- New: pyproject.toml, src/scientific_claim_verifier/{__init__,cli,envcheck,
  schemas}.py, scripts/00_check_environment.py, tests/{test_package,
  test_envcheck,test_cli}.py.
- Updated: site/index.html and site/milestones.html (M0 status → done, added a
  "Running it today" section), README (this milestone updates status/quickstart
  if applicable), and this milestone's docs under docs/milestones and
  docs/commits.

What should be checked later
- Whether argparse (vs typer) remains the right CLI choice as the command
  surface grows in later milestones.
- Whether `pydantic` should stay the sole runtime dependency, or whether
  numpy/pandas belong in `dependencies` once M5 lands (currently reported as
  optional by the env check and added per-milestone).
- The `schemas.py` stub is replaced wholesale in M1; confirm the M1 models match
  docs/PLAN.md section 6 and docs/CLAIM_SCHEMA.md when that lands.
- Version single-sourcing (pyproject dynamic attr → `__init__.__version__`)
  behaves as expected under an actual `pip install`/build.

Technical risks
- Low. This is scaffolding only; no verification behavior is implemented.
- Tests rely on pydantic being importable (declared dependency) for the
  env-check "READY" assertion; if the dependency is not installed the env check
  correctly reports NOT READY and those tests would fail — that is the intended
  contract, not a bug.
- `pip install -e .` was not executed here (to avoid any network fetch of build
  deps in the offline sandbox); tests instead import from `src/` via pytest's
  `pythonpath`. Verify the editable install/build path in a networked env.

Commands to verify
- python3 -m pytest -q
- ruff check .
- python3 scripts/00_check_environment.py
- ./scripts/serve_site.sh   then load http://localhost:9002/milestones.html

Human feedback
<!-- Human will fill this later. -->
