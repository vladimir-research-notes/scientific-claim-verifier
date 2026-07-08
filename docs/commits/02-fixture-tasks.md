# Commit note — M2 Fixture tasks & validation

## Commit message

```
M2: fixture tasks, task loader, content hashing, and validation

Add the on-disk task format and the machinery to load and validate it:
- artifacts/hashing.py: deterministic sha256: content hashes
- artifacts/loader.py: task schema (ClaimInput/GoldClaim/TaskExpectation/
  TaskSpec on the M1 models), load_task (parse->validate->resolve->hash),
  fixture-path safety, stdlib CSV shape reader; input/gold separation
- artifacts/validation.py: directory validator + ValidationReport, collects
  all errors/warnings per task; CLI + script entry points
Wire `claimverifier validate-fixtures` and scripts/01_validate_fixtures.py.
Add six synthetic tasks (numeric table, dataset statistic, evidence passage,
underspecified, code reproduction, bioinformatics GC) and their fixtures
(measurements.csv, compute_accuracy.py, gc_content.py).
Add pyyaml dependency; mark yaml required in the env check.
Add tests (test_hashing.py, test_fixtures.py) and docs/ARTIFACT_FORMAT.md;
update website (index, milestones, artifact-bundles) and milestone notes.
```

## What this commit adds

- A strict, typed task-file format built on the M1 schema, so every fixture
  exercises the real contract (including the unique-ID integrity validator).
- Content hashing that finally populates the `content_hash` fields typed in M1.
- A fixture validator that catches structural and referential problems and is
  reachable from both the CLI and a script (used as a between-milestone guard).
- Six committed tasks spanning the task families, and their small synthetic
  fixtures — the raw material later milestones run on.

## Deliberately excluded (per the operating principles)

- Extraction, evidence linking, checks, sandbox execution, scoring, reports —
  later milestones. M2 loads and validates; it does not verify anything.
- Running the code fixtures. They are referenced and hashed only; execution is
  the reproducibility-sandbox milestone (M6).
- pandas/numpy — the CSV shape check uses the stdlib `csv` module; heavy
  data-analysis libs still arrive with M5.

## Verification performed at commit time

- `python3 -m pytest -q` → 66 passed (38 prior + 28 new).
- `ruff check .` → all checks passed.
- `python3 scripts/01_validate_fixtures.py` → 6 ok, 0 failed, 0 warnings (exit 0).
- `python3 scripts/00_check_environment.py` → exit 0 (`READY`; yaml required/found).
- Static site served locally on port 9002; pages fetched via Python's `urllib`
  (no `curl`/`wget`, per the permission policy).
- `git status` clean after commit.
