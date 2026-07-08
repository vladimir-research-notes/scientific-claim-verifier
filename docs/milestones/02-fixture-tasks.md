# M2 — Fixture tasks & validation

## Summary

Introduces the on-disk **task** format and the machinery that turns a task file
into the typed Milestone 1 objects: a content hasher, a task loader, and a
directory-level fixture validator wired to both a CLI verb
(`claimverifier validate-fixtures`) and a script
(`scripts/01_validate_fixtures.py`). Ships six small, synthetic tasks across the
task families in `docs/PLAN.md` §7, plus their fixtures.

No verification logic — this milestone only *loads and validates* fixtures. The
point is to (a) give later milestones real, typed tasks to run on, and (b)
exercise the M1 schema against actual data, confirming it is sufficient.

## Deliverables

- **`src/scientific_claim_verifier/artifacts/`** (new package):
  - `hashing.py` — deterministic `sha256:` content hashes (`hash_bytes`,
    `hash_text`, `hash_file`).
  - `loader.py` — the task-file schema (`ClaimInput`, `GoldClaim`,
    `TaskExpectation`, `TaskSpec`, all strict), `load_task` (parse → validate →
    resolve → hash → `LoadedTask`), fixture-path safety, and a stdlib CSV
    shape reader.
  - `validation.py` — `validate_tasks` / `validate_task_file`, `ValidationReport`,
    text rendering, and a `main` entry point.
- **CLI:** `claimverifier validate-fixtures [tasks_dir]` registered in `cli.py`.
- **Script:** `scripts/01_validate_fixtures.py` (runnable without an install;
  invoked by the milestone runner as a between-milestone guard).
- **Six tasks** under `tasks/` (numeric table, dataset statistic, evidence
  passage, underspecified, code reproduction, bioinformatics GC) with inline
  papers/tables and gold expectations.
- **Fixtures** under `data/fixtures/`: `datasets/measurements.csv` (12 rows,
  mean 3.4) and `code/{compute_accuracy,gc_content}.py` (trusted, stdlib-only,
  deterministic).
- **Tests:** `tests/test_hashing.py` (5) and `tests/test_fixtures.py` (23).
- **Docs:** `docs/ARTIFACT_FORMAT.md` (canonical task-format reference); this
  milestone's notes.
- **Env/deps:** `pyyaml>=6` added to `pyproject.toml`; `yaml` moved to the
  *required* set in the environment self-check (it is now on the default path).
- **Website:** `index.html`, `milestones.html`, `artifact-bundles.html` updated.

## Design decisions

- **Input / gold separation.** The task's `claim` block is the pipeline input
  and carries no extracted numeric fields; the extraction targets live in
  `expected.claim` (a `GoldClaim`). Loading a task therefore never leaks the
  answer to the M3 extractor. `LoadedTask.input_claim` builds the input
  `ScientificClaim` with those fields empty.
- **Reuse the M1 `ArtifactBundle` directly.** The task's `artifacts` block *is*
  an `ArtifactBundle`, so the unique-ID integrity validator runs on every
  fixture and M2 doubles as a real-world test of the M1 schema.
- **Loader populates `content_hash`.** Datasets/code are hashed over file bytes;
  inlined papers over a canonical JSON of their passages. This is where the
  content_hash fields typed in M1 first get filled.
- **Fixture-path safety.** Paths must be relative and resolve inside the repo;
  absolute paths and `..` escapes are hard errors, and paths outside
  `data/fixtures/` warn. A task can only point at small committed fixtures.
- **Validator collects all problems.** `validate_task_file` accumulates every
  error/warning rather than stopping at the first, so one run fully describes a
  broken fixture. Errors fail the run; warnings never do.
- **CSV cross-check without pandas.** Declared `columns`/`n_rows` are confirmed
  against the actual CSV using the stdlib `csv` module — pandas is still not a
  dependency until the checks milestone (M5).
- **No execution yet.** Code fixtures are referenced and hashed only; running
  them is the reproducibility sandbox's job (M6). The tasks declare expected
  stdout/values so that later run can be scored.

## Validation

Commands run (CPU-only, offline):

| Command | Result |
| --- | --- |
| `python3 -m pytest -q` | 66 passed (38 prior + 28 new) |
| `ruff check .` | All checks passed |
| `python3 scripts/01_validate_fixtures.py` | 6 ok, 0 failed, 0 warnings — VALID (exit 0) |
| `python3 scripts/00_check_environment.py` | exit 0 — `READY` (yaml now required, found) |

The new tests pin: hash format/determinism/known vectors; that all six committed
fixtures validate; that the required families are covered; input/gold separation
(input claim empty, gold populated); deterministic hashing; CSV shape reading;
and that the validator catches missing files, CSV-shape mismatch, dangling
evidence links, unresolved source passages, absolute/escaping paths, unknown
fields, duplicate artifact IDs, filename/task_id mismatch (warning), out-of-tree
fixtures (warning), and missing expected values (warning). CLI and script entry
points are exercised.

## Status

**Complete.** Next: **M3 — Rule-based claim extraction** (transparent extractors
for numeric values, comparison phrases, metric names, dataset/table references,
and passage IDs, scored against the `expected.claim` gold introduced here).
