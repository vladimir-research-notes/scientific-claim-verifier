# Fixture data

Small, **synthetic or open** artifacts used to exercise the verification checks.
Everything here is committed and intended to run fully offline.

```
fixtures/
  datasets/    small CSVs for statistic recomputation
  code/        tiny Python scripts computing a reported metric
```

Paper snippets and expected/gold values are held **inline in the task files**
under `tasks/` (see `docs/ARTIFACT_FORMAT.md`), so only file-backed artifacts —
datasets and code — live here. Standalone `papers/` and `expected/` directories
will be added if a fixture ever outgrows inlining.

## Committed fixtures (from Milestone 2)

- `datasets/measurements.csv` — 12 synthetic scalar measurements (mean 3.4).
- `code/compute_accuracy.py` — prints `accuracy=0.80` (trusted, stdlib-only).
- `code/gc_content.py` — prints `gc_content=0.50` (toy bioinformatics).

The code fixtures are referenced and content-hashed by their tasks now;
executing them is the reproducibility-sandbox milestone's job.

## Rules

- No private or real papers; no real patient data; no credentials.
- No large datasets, model weights, or binary blobs (see repo `.gitignore`).
- Keep each fixture small enough to read and reason about by hand.
- Every fixture is referenced by at least one task under `tasks/` and validated
  by `scripts/01_validate_fixtures.py` / `claimverifier validate-fixtures`.
